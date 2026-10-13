"""Protected protocol projections in the existing ControlStore.

These tables hold external identities, event cursors and artifacts. Operations,
leases, grants and dispatch receipts always remain in the central authority.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

from sentra_core.conversations import _encode, _decode
from .gate import EffectRejected


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(c in value for c in "\0\r\n"):
        raise ValueError("invalid protocol identity")
    return value


class ProviderProjectionStore:
    def __init__(self, store, owner):
        self.store, self.owner = store, owner
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS interop_bindings(
                owner TEXT NOT NULL,machine TEXT NOT NULL,work_item TEXT NOT NULL,
                local_id TEXT NOT NULL,config TEXT NOT NULL,remote_id TEXT,context_id TEXT,
                state TEXT NOT NULL,sequence INTEGER NOT NULL DEFAULT -1,
                PRIMARY KEY(owner,machine,work_item,local_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS interop_events(
                owner TEXT NOT NULL,machine TEXT NOT NULL,work_item TEXT NOT NULL,
                local_id TEXT NOT NULL,event_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
                sha256 TEXT NOT NULL,content TEXT NOT NULL,
                PRIMARY KEY(owner,machine,work_item,local_id,event_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS interop_artifacts(
                owner TEXT NOT NULL,machine TEXT NOT NULL,work_item TEXT NOT NULL,
                local_id TEXT NOT NULL,artifact_id TEXT NOT NULL,sha256 TEXT NOT NULL,
                complete INTEGER NOT NULL,content TEXT NOT NULL,
                PRIMARY KEY(owner,machine,work_item,local_id,artifact_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS interop_input_claims(
                owner TEXT NOT NULL,machine TEXT NOT NULL,work_item TEXT NOT NULL,local_id TEXT NOT NULL,
                source_operation TEXT NOT NULL,operation TEXT NOT NULL,
                PRIMARY KEY(owner,machine,work_item,local_id,source_operation))""")

    def event(self,request,local_id,event_id):
        with self.db() as db:
            row=db.execute("SELECT content,sha256 FROM interop_events WHERE owner=? AND machine=? "
                "AND work_item=? AND local_id=? AND event_id=?",(*self.scope(request,local_id),identifier(event_id))).fetchone()
        if row is None:raise FileNotFoundError("protocol event not found")
        value=_decode(row["content"])
        if digest(value)!=row["sha256"]:raise ValueError("protocol event digest mismatch")
        return value

    def claim_input(self,request,local_id,source_operation):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM interop_input_claims WHERE owner=? AND machine=? AND work_item=? "
                          "AND local_id=? AND source_operation=?",(*self.scope(request,local_id),source_operation)).fetchone():
                raise EffectRejected("MCP input continuation already consumed or uncertain")
            db.execute("INSERT INTO interop_input_claims VALUES(?,?,?,?,?,?)",
                       (*self.scope(request,local_id),identifier(source_operation),request.operation_id))

    @contextmanager
    def db(self):
        db = self.store.connect("interop_projections")
        try:
            with db:
                yield db
        finally:
            db.close()

    def scope(self, request, local_id):
        return self.owner, request.machine_id, request.work_item_id, identifier(local_id)

    def get(self, request, local_id, config):
        with self.db() as db:
            row = db.execute("SELECT * FROM interop_bindings WHERE owner=? AND machine=? "
                             "AND work_item=? AND local_id=?", self.scope(request, local_id)).fetchone()
        if row is None:
            return None
        if row["config"] != config:
            raise EffectRejected("protocol configuration changed; explicit migration required")
        return dict(row)

    def prepare(self, request, local_id, config, *, context_id=None):
        scope = self.scope(request, local_id)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT 1 FROM interop_bindings WHERE owner=? AND machine=? "
                             "AND work_item=? AND local_id=?", scope).fetchone()
            if old:
                raise EffectRejected("protocol creation exists or is uncertain; reconcile")
            db.execute("INSERT INTO interop_bindings VALUES(?,?,?,?,?,?,?,?,-1)",
                       (*scope, config, None, context_id, "PREPARED"))

    def bind(self, request, local_id, config, remote_id, context_id=None, state="ACTIVE"):
        identifier(remote_id)
        if context_id is not None:
            identifier(context_id)
        scope = self.scope(request, local_id)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM interop_bindings WHERE owner=? AND machine=? "
                             "AND work_item=? AND local_id=?", scope).fetchone()
            if (old is None or old["config"] != config or old["state"] == "DELETED"
                    or old["remote_id"] not in (None, remote_id)
                    or old["context_id"] not in (None, context_id)):
                raise EffectRejected("immutable external identity conflict")
            db.execute("UPDATE interop_bindings SET remote_id=?,context_id=?,state=? WHERE "
                       "owner=? AND machine=? AND work_item=? AND local_id=?",
                       (remote_id, context_id, state, *scope))

    def state(self, request, local_id, state):
        with self.db() as db:
            db.execute("UPDATE interop_bindings SET state=? WHERE owner=? AND machine=? AND "
                       "work_item=? AND local_id=? AND state!='DELETED'",
                       (identifier(state), *self.scope(request, local_id)))

    def ingest(self, request, local_id, *, event_id, payload, sequence=None, artifact=None,artifacts=None):
        scope = self.scope(request, local_id)
        event_id = identifier(event_id)
        encoded = canonical(payload)
        if len(encoded.encode()) > 262144:
            raise ValueError("protocol event exceeds limit")
        sha = digest(payload)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            binding = db.execute("SELECT sequence FROM interop_bindings WHERE owner=? AND "
                                 "machine=? AND work_item=? AND local_id=?", scope).fetchone()
            if binding is None:
                raise EffectRejected("event has no scoped association")
            old = db.execute("SELECT sha256,ordinal FROM interop_events WHERE owner=? AND "
                             "machine=? AND work_item=? AND local_id=? AND event_id=?", (*scope,event_id)).fetchone()
            if old:
                if old["sha256"] != sha:
                    raise EffectRejected("immutable event changed")
                return {"event_id": event_id, "ordinal": old["ordinal"], "duplicate": True}
            ordinal = db.execute("SELECT COALESCE(MAX(ordinal),-1)+1 FROM interop_events WHERE "
                                 "owner=? AND machine=? AND work_item=? AND local_id=?",scope).fetchone()[0]
            if sequence is not None:
                if type(sequence) is not int or sequence < 0 or sequence != binding["sequence"] + 1:
                    raise EffectRejected("protocol stream gap; recover before applying")
            if artifact is not None:
                self._artifact(db, scope, artifact)
            for value in artifacts or []:
                self._artifact(db,scope,value)
            db.execute("INSERT INTO interop_events VALUES(?,?,?,?,?,?,?,?)",
                       (*scope,event_id,ordinal,sha,_encode(payload)))
            if sequence is not None:
                db.execute("UPDATE interop_bindings SET sequence=? WHERE owner=? AND machine=? "
                           "AND work_item=? AND local_id=?",(sequence,*scope))
        return {"event_id": event_id, "ordinal": ordinal, "sha256": sha, "duplicate": False}

    def _artifact(self, db, scope, artifact):
        key = identifier(artifact["artifact_id"])
        if type(artifact["append"]) is not bool or type(artifact["complete"]) is not bool:
            raise ValueError("invalid artifact flags")
        parts = artifact["parts"]
        if not isinstance(parts, list):
            raise ValueError("invalid artifact parts")
        row = db.execute("SELECT * FROM interop_artifacts WHERE owner=? AND machine=? "
                         "AND work_item=? AND local_id=? AND artifact_id=?",(*scope,key)).fetchone()
        if row and row["complete"]:
            if not artifact["append"] and digest(parts)==row["sha256"] and artifact["complete"]:
                return
            raise EffectRejected("completed artifact cannot be changed")
        if artifact["append"] and row is None:
            raise EffectRejected("artifact append lacks first chunk")
        content = [*(_decode(row["content"]) if artifact["append"] else []),*parts]
        if len(canonical(content).encode()) > 1_900_000:
            raise ValueError("assembled artifact exceeds limit")
        db.execute("INSERT INTO interop_artifacts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT "
                   "(owner,machine,work_item,local_id,artifact_id) DO UPDATE SET "
                   "sha256=excluded.sha256,complete=excluded.complete,content=excluded.content",
                   (*scope,key,digest(content),int(artifact["complete"]),_encode(content)))

    def events(self, request, local_id, *, after=-1, limit=100):
        if type(after) is not int or after < -1 or type(limit) is not int or not 1<=limit<=100:
            raise ValueError("invalid event page")
        with self.db() as db:
            rows = db.execute("SELECT event_id,ordinal,sha256,content FROM interop_events WHERE "
                "owner=? AND machine=? AND work_item=? AND local_id=? AND ordinal>? ORDER BY ordinal LIMIT ?",
                (*self.scope(request,local_id),after,limit+1)).fetchall()
        result = [{"event_id":r["event_id"],"ordinal":r["ordinal"],"sha256":r["sha256"],
                   "event":_decode(r["content"])} for r in rows[:limit]]
        return {"items":result,"next_cursor":result[-1]["ordinal"] if len(rows)>limit else None}

    def artifact(self, request, local_id, artifact_id):
        with self.db() as db:
            row = db.execute("SELECT sha256,complete,content FROM interop_artifacts WHERE owner=? "
                "AND machine=? AND work_item=? AND local_id=? AND artifact_id=?",
                (*self.scope(request,local_id),identifier(artifact_id))).fetchone()
        if row is None:
            raise FileNotFoundError("protocol artifact not found")
        parts = _decode(row["content"])
        if digest(parts) != row["sha256"]:
            raise ValueError("artifact digest mismatch")
        return {"artifact_id":artifact_id,"sha256":row["sha256"],"complete":bool(row["complete"]),"parts":parts}
