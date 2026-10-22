"""Durable protocol input requests, bound to the original central Operation.

Owner-authenticated UI may answer forms and one-shot peer permission questions.
An answer does not issue Grants, change ChatTrust, or authorize host tools.
"""
import asyncio
import json
import time
import uuid
from dataclasses import asdict

from sentra_core.conversations import _encode,_decode
from sentra_runtime.contracts import OperationRequest
from .gate import EffectRejected
from .provider_store import canonical,digest,identifier


class ProtocolInteractionService:
    def __init__(self,control,*,owner):
        self.control,self.owner=control,owner
        db=control.store.connect("interop_interactions")
        try:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS protocol_inputs(
                    owner TEXT NOT NULL,interaction TEXT NOT NULL PRIMARY KEY,workspace TEXT NOT NULL,
                    operation TEXT NOT NULL,peer_request TEXT NOT NULL,method TEXT NOT NULL,
                    request TEXT NOT NULL,question TEXT NOT NULL,question_sha TEXT NOT NULL,
                    state TEXT NOT NULL,expires REAL NOT NULL,answer TEXT,reply_key TEXT,
                    UNIQUE(owner,operation,peer_request))""")
        finally:db.close()

    async def ask(self,packet,request,policy,*,timeout=115):
        method=packet.get("method")
        if method not in {"elicitation/create","session/request_permission"}:
            raise EffectRejected("protocol reverse request is not supported")
        params=packet.get("params")
        if not isinstance(params,dict) or len(canonical(params).encode())>32768:
            raise EffectRejected("protocol interaction exceeds limit")
        if method=="elicitation/create" and params.get("mode","form")!="form":
            return {"action":"decline"}  # URL flows require a separately configured browser operation.
        if policy(request).allowed is not True:raise EffectRejected("protocol input grant unavailable")
        item=self.control.work_item_info(request.work_item_id,self.owner)
        workspace=identifier(item.get("metadata",{}).get("workspace_id"))
        peer=identifier(str(packet.get("id")))
        iid=str(uuid.uuid4());sha=digest(params)
        db=self.control.store.connect("interop_interactions")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                old=db.execute("SELECT * FROM protocol_inputs WHERE owner=? AND operation=? AND peer_request=?",
                    (self.owner,request.operation_id,peer)).fetchone()
                if old:
                    if old["question_sha"]!=sha or old["state"]!="PENDING":
                        raise EffectRejected("protocol interaction replay/conflict")
                    iid=old["interaction"]
                else:
                    db.execute("INSERT INTO protocol_inputs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (self.owner,iid,workspace,request.operation_id,peer,method,_encode(asdict(request)),
                         _encode(params),sha,"PENDING",time.time()+timeout,None,None))
        finally:db.close()
        try:
            while True:
                db=self.control.store.connect("interop_interactions")
                try:row=db.execute("SELECT * FROM protocol_inputs WHERE owner=? AND interaction=?",(self.owner,iid)).fetchone()
                finally:db.close()
                if row["state"]=="ANSWERED":
                    if policy(request).allowed is not True:raise EffectRejected("protocol input grant revoked")
                    answer=_decode(row["answer"])
                    self._consume(iid)
                    return answer
                if time.time()>=row["expires"] or policy(request).allowed is not True:
                    self._consume(iid,"EXPIRED")
                    return {"outcome":{"outcome":"cancelled"}} if method=="session/request_permission" else {"action":"cancel"}
                await asyncio.sleep(.2)
        except asyncio.CancelledError:
            self._consume(iid,"CANCELLED")
            raise

    def _consume(self,iid,state="CONSUMED"):
        db=self.control.store.connect("interop_interactions")
        try:
            with db:db.execute("UPDATE protocol_inputs SET state=? WHERE owner=? AND interaction=? AND state IN ('PENDING','ANSWERED')",
                               (state,self.owner,iid))
        finally:db.close()

    def register_embedded(self,request,input_requests):
        item=self.control.work_item_info(request.work_item_id,self.owner)
        workspace=identifier(item.get("metadata",{}).get("workspace_id"))
        if not isinstance(input_requests,dict) or len(input_requests)>32:raise ValueError("MCP input request limit")
        result={}
        db=self.control.store.connect("interop_interactions")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                for key,spec in input_requests.items():
                    identifier(key)
                    if not isinstance(spec,dict) or spec.get("method")!="elicitation/create":
                        raise EffectRejected("MCP sampling/roots input is not enabled")
                    question=spec.get("params",{})
                    if question.get("mode","form")!="form" or not isinstance(question.get("requestedSchema"),dict):
                        raise EffectRejected("MCP embedded input requires a bounded form")
                    iid=str(uuid.uuid4());peer="embedded:"+key;sha=digest(question)
                    old=db.execute("SELECT * FROM protocol_inputs WHERE owner=? AND operation=? AND peer_request=?",
                                   (self.owner,request.operation_id,peer)).fetchone()
                    if old:
                        if old["question_sha"]!=sha:raise EffectRejected("MCP embedded input changed")
                        iid=old["interaction"]
                    else:
                        db.execute("INSERT INTO protocol_inputs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(self.owner,iid,workspace,
                            request.operation_id,peer,"elicitation/create",_encode(asdict(request)),_encode(question),sha,
                            "PENDING",time.time()+900,None,None))
                    result[key]=iid
        finally:db.close()
        return result

    def consume_embedded(self,request,source_operation,responses):
        db=self.control.store.connect("interop_interactions")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                rows=db.execute("SELECT * FROM protocol_inputs WHERE owner=? AND operation=? AND peer_request LIKE 'embedded:%'",
                                (self.owner,source_operation)).fetchall()
                if set(responses)!={r["peer_request"][9:] for r in rows}:raise EffectRejected("MCP input answers incomplete")
                for row in rows:
                    original=OperationRequest(**_decode(row["request"]))
                    if (original.machine_id,original.work_item_id,original.principal_id)!=(request.machine_id,request.work_item_id,request.principal_id):
                        raise EffectRejected("MCP human input belongs to another operation scope")
                    if row["state"]!="ANSWERED" or row["expires"]<=time.time() or _decode(row["answer"])!=responses[row["peer_request"][9:]]:
                        raise EffectRejected("MCP input requires an owner-authenticated answer")
                for row in rows:db.execute("UPDATE protocol_inputs SET state='CONSUMED' WHERE interaction=?",(row["interaction"],))
        finally:db.close()

    def pending(self,*,workspace_id,limit=100):
        if type(limit) is not int or not 1<=limit<=100:raise ValueError("invalid interaction page")
        db=self.control.store.connect("interop_interactions")
        try:rows=db.execute("SELECT * FROM protocol_inputs WHERE owner=? AND workspace=? AND state='PENDING' "
                           "AND expires>? ORDER BY expires LIMIT ?",(self.owner,workspace_id,time.time(),limit)).fetchall()
        finally:db.close()
        return [{"interaction_id":r["interaction"],"operation_id":r["operation"],"method":r["method"],
                 "question":_decode(r["question"]),"expires_at":r["expires"],"grants_created":False} for r in rows]

    def reply(self,*,workspace_id,interaction_id,answer,request_key):
        identifier(request_key)
        db=self.control.store.connect("interop_interactions")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT * FROM protocol_inputs WHERE owner=? AND workspace=? AND interaction=?",
                    (self.owner,workspace_id,interaction_id)).fetchone()
                if row is None:raise FileNotFoundError("protocol interaction not found")
                if row["state"]=="ANSWERED" and row["reply_key"]==request_key and _decode(row["answer"])==answer:
                    return {"interaction_id":interaction_id,"status":"answered","deduplicated":True}
                if row["state"]!="PENDING" or row["expires"]<=time.time():raise EffectRejected("protocol interaction unavailable")
                request=OperationRequest(**_decode(row["request"]))
                item=self.control.work_item_info(request.work_item_id,self.owner)
                if item.get("metadata",{}).get("workspace_id")!=workspace_id or item["state"]!="RUNNING":
                    raise EffectRejected("protocol input WorkItem no longer active")
                question=_decode(row["question"])
                if row["method"]=="elicitation/create":
                    if not isinstance(answer,dict) or answer.get("action") not in {"accept","decline","cancel"}:
                        raise ValueError("invalid protocol form answer")
                    if answer["action"]=="accept":
                        from jsonschema import Draft202012Validator
                        schema=question.get("requestedSchema")
                        if not isinstance(schema,dict):raise ValueError("protocol form schema unavailable")
                        Draft202012Validator(schema).validate(answer.get("content"))
                    elif set(answer)!={"action"}:raise ValueError("declined form cannot include values")
                else:
                    outcome=answer.get("outcome",{}) if isinstance(answer,dict) else {}
                    if outcome.get("outcome")=="selected":
                        options=question.get("options",[])
                        if not any(isinstance(o,dict) and o.get("optionId")==outcome.get("optionId")
                                   and o.get("kind") in {"allow_once","reject_once"} for o in options):
                            raise ValueError("only advertised one-shot protocol decisions are permitted")
                    elif outcome!={"outcome":"cancelled"}:raise ValueError("invalid peer permission answer")
                if len(canonical(answer).encode())>32768:raise ValueError("protocol answer exceeds bound")
                db.execute("UPDATE protocol_inputs SET state='ANSWERED',answer=?,reply_key=? WHERE interaction=?",
                           (_encode(answer),request_key,interaction_id))
        finally:db.close()
        return {"interaction_id":interaction_id,"status":"answered","grants_created":False}
