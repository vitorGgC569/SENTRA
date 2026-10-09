"""Protected working context; task information never creates an execution grant."""
import hashlib
import json
import time

from sentra_core.conversations import _encode,_decode


class AgentWorkingContext:
    def __init__(self,store):
        self.store=store
        with store.tx():
            store.db.execute("CREATE TABLE IF NOT EXISTS canvas_working_context("
                "principal TEXT NOT NULL,workspace TEXT NOT NULL,agent TEXT NOT NULL,revision INTEGER NOT NULL,"
                "content TEXT NOT NULL,sha256 TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(principal,workspace,agent))")

    @staticmethod
    def _digest(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()).hexdigest()

    def get(self,workspace,agent):
        self.store.resource("agents",agent,workspace)
        with self.store.lock:
            row=self.store.db.execute("SELECT * FROM canvas_working_context WHERE principal=? AND workspace=? AND agent=?",
                (self.store.principal,workspace,agent)).fetchone()
        if row is None:return {"revision":0,"goal":"","parent_agent_id":None,"source_work_item_ids":[],"sharing":"local-directed"}
        value=_decode(row["content"])
        if self._digest(value)!=row["sha256"]:raise ValueError("agent working context integrity failure")
        return {**value,"revision":row["revision"]}

    def set(self,workspace,agent,*,goal,expected_revision,parent_agent_id=None,source_work_item_ids=()):
        self.store.resource("agents",agent,workspace)
        if not isinstance(goal,str) or len(goal.encode())>16000 or type(expected_revision) is not int or expected_revision<0:
            raise ValueError("bounded working goal and expected revision required")
        if parent_agent_id is not None:
            self.store.resource("agents",parent_agent_id,workspace)
            if parent_agent_id==agent:raise ValueError("agent cannot inherit its own context")
        if not isinstance(source_work_item_ids,(tuple,list)) or len(source_work_item_ids)>32 or any(
                not isinstance(value,str) or not 1<=len(value)<=128 for value in source_work_item_ids):
            raise ValueError("bounded work item provenance required")
        value={"goal":goal,"parent_agent_id":parent_agent_id,"source_work_item_ids":list(source_work_item_ids),"sharing":"local-directed"}
        with self.store.tx():
            old=self.store.db.execute("SELECT revision FROM canvas_working_context WHERE principal=? AND workspace=? AND agent=?",
                (self.store.principal,workspace,agent)).fetchone()
            current=old[0] if old else 0
            if current!=expected_revision:raise ValueError("working context revision changed")
            self.store.db.execute("INSERT INTO canvas_working_context VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(principal,workspace,agent) DO UPDATE SET revision=excluded.revision,content=excluded.content,"
                "sha256=excluded.sha256,updated=excluded.updated",
                (self.store.principal,workspace,agent,current+1,_encode(value),self._digest(value),time.time()))
        return self.get(workspace,agent)
