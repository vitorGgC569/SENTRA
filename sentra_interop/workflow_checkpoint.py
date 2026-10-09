"""Protected workflow projections, parents/pending writes, signals and TTL memory.

This database references central operation IDs; it cannot reserve, authorize,
complete or replay a SENTRA Operation. A projected result is usable only after
the host's central journal confirms the associated operation.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from sentra_core.conversations import _encode, _decode
from .workflow_contracts import digest, ident


class WorkflowCheckpointConflict(ValueError): pass


def namespace(value):
    if not isinstance(value,str) or len(value)>1024 or len(value.split("/"))>16: raise ValueError("invalid checkpoint namespace")
    for part in value.split("/") if value else (): ident(part)
    return value


class WorkflowCheckpointStore:
    def __init__(self,database,*,workspace):
        root,self.path=Path(workspace).resolve(),Path(database).resolve()
        if self.path==root or not self.path.is_relative_to(root): raise ValueError("workflow checkpoint outside workspace")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS wf_instances(
                workflow_id TEXT NOT NULL,namespace TEXT NOT NULL,principal TEXT NOT NULL,machine TEXT NOT NULL,
                work_item TEXT NOT NULL,definition_digest TEXT NOT NULL,worker_version TEXT NOT NULL,
                head TEXT NOT NULL,parent_namespace TEXT,PRIMARY KEY(workflow_id,namespace))""")
            db.execute("""CREATE TABLE IF NOT EXISTS wf_checkpoints(
                id TEXT PRIMARY KEY,workflow_id TEXT NOT NULL,namespace TEXT NOT NULL,parent_id TEXT,
                revision INTEGER NOT NULL,sha256 TEXT NOT NULL,protected_state TEXT NOT NULL,created REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS wf_pending_writes(
                workflow_id TEXT NOT NULL,namespace TEXT NOT NULL,step_id TEXT NOT NULL,attempt INTEGER NOT NULL,
                operation_id TEXT NOT NULL,sha256 TEXT NOT NULL,protected_write TEXT NOT NULL,
                PRIMARY KEY(workflow_id,namespace,step_id,attempt))""")
            db.execute("""CREATE TABLE IF NOT EXISTS wf_signals(
                workflow_id TEXT NOT NULL,namespace TEXT NOT NULL,signal_id TEXT NOT NULL,name TEXT NOT NULL,
                sha256 TEXT NOT NULL,protected_payload TEXT NOT NULL,state TEXT NOT NULL,operation_id TEXT NOT NULL,
                PRIMARY KEY(workflow_id,namespace,signal_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS wf_memory(
                workflow_id TEXT NOT NULL,namespace TEXT NOT NULL,key TEXT NOT NULL,protected_value TEXT NOT NULL,
                sha256 TEXT NOT NULL,expires REAL,PRIMARY KEY(workflow_id,namespace,key))""")

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=10000")
            with db: yield db
        finally: db.close()

    def open(self,*,workflow_id,ns,definition,request,inputs,parent_namespace=None):
        ident(workflow_id); namespace(ns)
        scope=(request.principal_id,request.machine_id,request.work_item_id,definition.fingerprint,definition.worker_version)
        protected=_encode({"input":inputs,"definition_id":definition.definition_id,"definition_version":definition.version,
            "status":"READY","steps":{},"created":time.time(),"cancel_requested":False})
        state_hash=digest(_decode(protected))
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT * FROM wf_instances WHERE workflow_id=? AND namespace=?",(workflow_id,ns)).fetchone()
            if old:
                if tuple(old[k] for k in ("principal","machine","work_item","definition_digest","worker_version"))!=scope:
                    raise WorkflowCheckpointConflict("workflow scope/definition/worker changed")
                initial=db.execute("SELECT protected_state FROM wf_checkpoints WHERE workflow_id=? AND namespace=? AND revision=0",
                                   (workflow_id,ns)).fetchone()
                if initial is None or digest(_decode(initial[0])["input"])!=digest(inputs) or old["parent_namespace"]!=parent_namespace:
                    raise WorkflowCheckpointConflict("workflow initial input/parent changed")
                return old["head"]
            checkpoint_id=uuid.uuid4().hex
            db.execute("INSERT INTO wf_checkpoints VALUES(?,?,?,?,?,?,?,?)",(checkpoint_id,workflow_id,ns,None,0,state_hash,protected,time.time()))
            db.execute("INSERT INTO wf_instances VALUES(?,?,?,?,?,?,?,?,?)",(workflow_id,ns,*scope,checkpoint_id,parent_namespace))
            return checkpoint_id

    def load(self,workflow_id,ns,request,*,checkpoint_id=None):
        namespace(ns)
        with self.db() as db:
            instance=db.execute("SELECT * FROM wf_instances WHERE workflow_id=? AND namespace=?",(workflow_id,ns)).fetchone()
            if instance is None: raise FileNotFoundError("workflow checkpoint not found")
            if tuple(instance[k] for k in ("principal","machine","work_item"))!=(request.principal_id,request.machine_id,request.work_item_id):
                raise PermissionError("workflow namespace belongs to another scope")
            row=db.execute("SELECT * FROM wf_checkpoints WHERE id=? AND workflow_id=? AND namespace=?",
                           (checkpoint_id or instance["head"],workflow_id,ns)).fetchone()
            if row is None: raise FileNotFoundError("checkpoint does not belong to workflow namespace")
        state=_decode(row["protected_state"])
        if digest(state)!=row["sha256"]: raise ValueError("workflow checkpoint digest mismatch")
        return {"instance":dict(instance),"id":row["id"],"parent_id":row["parent_id"],"revision":row["revision"],
                "sha256":row["sha256"],"state":state}

    def save(self,loaded,state):
        protected=_encode(state)
        instance=loaded["instance"]
        checkpoint_id=uuid.uuid4().hex
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed=db.execute("UPDATE wf_instances SET head=? WHERE workflow_id=? AND namespace=? AND head=?",
                              (checkpoint_id,instance["workflow_id"],instance["namespace"],loaded["id"]))
            if changed.rowcount!=1: raise WorkflowCheckpointConflict("workflow checkpoint CAS conflict")
            db.execute("INSERT INTO wf_checkpoints VALUES(?,?,?,?,?,?,?,?)",(checkpoint_id,instance["workflow_id"],
                instance["namespace"],loaded["id"],loaded["revision"]+1,digest(state),protected,time.time()))
        return checkpoint_id

    def put_write(self,workflow_id,ns,step_id,attempt,operation_id,value):
        protected,hash_value=_encode(value),digest(value)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT operation_id,sha256 FROM wf_pending_writes WHERE workflow_id=? AND namespace=? AND step_id=? AND attempt=?",
                           (workflow_id,ns,step_id,attempt)).fetchone()
            if old and (old["operation_id"],old["sha256"])!=(operation_id,hash_value):
                raise WorkflowCheckpointConflict("pending activity write changed")
            db.execute("INSERT OR IGNORE INTO wf_pending_writes VALUES(?,?,?,?,?,?,?)",
                       (workflow_id,ns,step_id,attempt,operation_id,hash_value,protected))

    def get_write(self,workflow_id,ns,step_id,attempt,*,operation_id=None):
        with self.db() as db:
            row=db.execute("SELECT * FROM wf_pending_writes WHERE workflow_id=? AND namespace=? AND step_id=? AND attempt=?",
                           (workflow_id,ns,step_id,attempt)).fetchone()
        if row is None: return None
        if operation_id is not None and row["operation_id"]!=operation_id:
            raise WorkflowCheckpointConflict("pending write operation identity mismatch")
        value=_decode(row["protected_write"])
        if digest(value)!=row["sha256"]: raise ValueError("pending write digest mismatch")
        return value

    def admit_signal(self,workflow_id,ns,signal_id,name,payload,operation_id):
        ident(signal_id); ident(name)
        encrypted,hash_value=_encode(payload),digest(payload)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT name,sha256,state FROM wf_signals WHERE workflow_id=? AND namespace=? AND signal_id=?",
                           (workflow_id,ns,signal_id)).fetchone()
            if old:
                if (old["name"],old["sha256"])!=(name,hash_value): raise WorkflowCheckpointConflict("signal identity conflict")
                return old["state"],True
            db.execute("INSERT INTO wf_signals VALUES(?,?,?,?,?,?,?,?)",(workflow_id,ns,signal_id,name,hash_value,encrypted,"ADMITTED",operation_id))
        return "ADMITTED",False

    def pending_signals(self,workflow_id,ns,name):
        with self.db() as db:
            rows=db.execute("SELECT * FROM wf_signals WHERE workflow_id=? AND namespace=? AND name=? AND state='ADMITTED' ORDER BY rowid",
                            (workflow_id,ns,name)).fetchall()
        return [dict(r) for r in rows]

    def complete_signal(self,loaded,state,signal_id):
        # Commit consumption and the checkpoint together. A crash cannot
        # consume a signal without retaining the node's resulting state.
        encrypted=_encode(state)
        instance=loaded["instance"]
        new_id=uuid.uuid4().hex
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("UPDATE wf_instances SET head=? WHERE workflow_id=? AND namespace=? AND head=?",
                (new_id,instance["workflow_id"],instance["namespace"],loaded["id"])).rowcount!=1:
                raise WorkflowCheckpointConflict("signal checkpoint changed")
            if db.execute("UPDATE wf_signals SET state='COMPLETED' WHERE workflow_id=? AND namespace=? AND signal_id=? AND state='ADMITTED'",
                (instance["workflow_id"],instance["namespace"],signal_id)).rowcount!=1:
                raise WorkflowCheckpointConflict("signal already consumed")
            db.execute("INSERT INTO wf_checkpoints VALUES(?,?,?,?,?,?,?,?)",(new_id,instance["workflow_id"],instance["namespace"],
                loaded["id"],loaded["revision"]+1,digest(state),encrypted,time.time()))
        return new_id

    def memory_put(self,workflow_id,ns,key,value,*,ttl_seconds=None):
        ident(key); namespace(ns)
        if ttl_seconds is not None and (type(ttl_seconds) not in (int,float) or not 0<ttl_seconds<=31536000):
            raise ValueError("invalid memory TTL")
        with self.db() as db:
            db.execute("INSERT INTO wf_memory VALUES(?,?,?,?,?,?) ON CONFLICT(workflow_id,namespace,key) DO UPDATE SET "
                "protected_value=excluded.protected_value,sha256=excluded.sha256,expires=excluded.expires",
                (workflow_id,ns,key,_encode(value),digest(value),time.time()+ttl_seconds if ttl_seconds else None))

    def memory_search(self,workflow_id,ns,*,query="",limit=20,key=None):
        namespace(ns)
        if not isinstance(query,str) or len(query)>4096 or type(limit) is not int or not 1<=limit<=100:
            raise ValueError("invalid workflow memory query")
        with self.db() as db:
            rows=db.execute("SELECT * FROM wf_memory WHERE workflow_id=? AND (expires IS NULL OR expires>?) ORDER BY namespace,key",
                            (workflow_id,time.time())).fetchall()
        found=[]
        for row in rows:
            if ns and row["namespace"]!=ns and not row["namespace"].startswith(ns+"/"): continue
            if key is not None and row["key"]!=key: continue
            value=_decode(row["protected_value"])
            if digest(value)!=row["sha256"]: raise ValueError("workflow memory digest mismatch")
            if query and query.casefold() not in str(value).casefold(): continue
            found.append({"namespace":row["namespace"],"key":row["key"],"value":value,"sha256":row["sha256"],"expires":row["expires"]})
            if len(found)>=limit: break
        return found
