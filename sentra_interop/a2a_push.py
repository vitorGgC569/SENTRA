"""Authenticated A2A push inbox. Receiving a callback never dispatches work."""
import hmac
import time

from sentra_core.conversations import _encode,_decode
from .a2a_provider import decode
from .gate import EffectRejected
from .provider_store import digest,identifier


class A2APushIngress:
    def __init__(self,control,*,owner,machine_id,config,credential):
        self.control,self.owner,self.machine_id,self.config,self.credential=control,owner,machine_id,config,credential
        db=control.store.connect("interop_push")
        try:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS a2a_push_inbox(
                    owner TEXT NOT NULL,machine TEXT NOT NULL,event_id TEXT NOT NULL,
                    work_item TEXT NOT NULL,local_id TEXT NOT NULL,task_id TEXT NOT NULL,
                    content TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(owner,machine,event_id))""")
        finally:db.close()

    def receive(self,*,raw_body,headers):
        if not self.config.callback_url or not callable(self.credential):raise EffectRejected("A2A push is not configured")
        if not isinstance(raw_body,bytes) or not 0<len(raw_body)<=262144:raise ValueError("A2A push body exceeds bound")
        values={str(k).lower():str(v) for k,v in headers.items()}
        if not hmac.compare_digest(values.get("authorization",""),"Bearer "+self.credential()):
            raise EffectRejected("A2A callback sender authentication failed")
        payload=decode(raw_body)
        if not isinstance(payload,dict) or len(payload)!=1:raise ValueError("invalid A2A push payload")
        body=payload.get("task",payload.get("statusUpdate",payload.get("artifactUpdate")))
        if not isinstance(body,dict):raise ValueError("unsupported A2A push event")
        task=identifier(body.get("id") or body.get("taskId"));context=identifier(body.get("contextId"))
        db=self.control.store.connect("interop_projections")
        try:
            rows=db.execute("SELECT * FROM interop_bindings WHERE owner=? AND machine=? AND remote_id=? AND context_id=? AND config=?",
                (self.owner,self.machine_id,task,context,self.config.fingerprint)).fetchall()
        finally:db.close()
        if len(rows)!=1:raise EffectRejected("A2A push does not identify one admitted scoped task")
        binding=rows[0];item=self.control.work_item_info(binding["work_item"],self.owner)
        project=identifier(item.get("metadata",{}).get("workspace_id"))
        eid=digest(payload)
        db=self.control.store.connect("interop_push")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                old=db.execute("SELECT 1 FROM a2a_push_inbox WHERE owner=? AND machine=? AND event_id=?",
                               (self.owner,self.machine_id,eid)).fetchone()
                if not old:db.execute("INSERT INTO a2a_push_inbox VALUES(?,?,?,?,?,?,?,?)",(
                    self.owner,self.machine_id,eid,binding["work_item"],binding["local_id"],task,_encode(payload),time.time()))
        finally:db.close()
        return {"ok":True,"event_id":eid,"project_id":project,"workspace_id":project,
                "local_id":binding["local_id"],"duplicate":bool(old),"effect_dispatched":False}

    def value(self,request,event_id):
        db=self.control.store.connect("interop_push")
        try:row=db.execute("SELECT * FROM a2a_push_inbox WHERE owner=? AND machine=? AND event_id=? AND work_item=? AND local_id=?",
            (self.owner,self.machine_id,event_id,request.work_item_id,request.arguments["local_id"])).fetchone()
        finally:db.close()
        if row is None:raise EffectRejected("A2A authenticated callback not found in this scope")
        payload=_decode(row["content"])
        if digest(payload)!=event_id:raise ValueError("A2A callback integrity failed")
        return payload
