"""Opt-in OpenHands Agent Server HTTP provider using the pinned SDK routers.

The host injects a durable gate. SQLite below stores conversation associations
and protected event projections, never Run/Operation/Grant/Lease authority.
No automatic server startup, client-tool execution, HTTP effect retries or
reattach fallback to conversation creation.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from sentra_core.conversations import _encode, _decode
from sentra_runtime.contracts import OperationRequest, OperationResult, PolicyDecision
from .gate import DispatchOutcome, EffectRejected, InteropGate, _fingerprint
from .openhands import OpenHandsSDKEvent


def _id(value):
    if not isinstance(value,str) or not value or len(value)>256 or "\0" in value:
        raise ValueError("invalid OpenHands identity")
    return value


def _uuid(value):
    return str(uuid.UUID(_id(value)))


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(",",":"),
                                    ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class OpenHandsServerConfig:
    base_url: str
    provider_id: str
    remote_workspace: str
    agent_profile_id: str
    enabled: bool = False
    timeout: float = 30
    max_response_bytes: int = 2_000_000

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if (url.scheme not in {"https","http"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or (url.scheme == "http" and url.hostname not in {"localhost","127.0.0.1","::1"})
            or url.path.rstrip("/") not in {"","/api"}):
            raise ValueError("OpenHands requires an explicit HTTPS or loopback /api origin")
        _id(self.provider_id)
        _uuid(self.agent_profile_id)
        if (not isinstance(self.remote_workspace,str) or not self.remote_workspace or "\0" in self.remote_workspace
            or not (self.remote_workspace.startswith("/") or Path(self.remote_workspace).is_absolute())
            or type(self.enabled) is not bool or type(self.timeout) not in (int,float) or not 0<self.timeout<=120
            or type(self.max_response_bytes) is not int or not 65536<=self.max_response_bytes<=8_000_000):
            raise ValueError("invalid trusted OpenHands server configuration")

    @property
    def api_url(self):
        url = self.base_url.rstrip("/")
        return url if url.endswith("/api") else url+"/api"

    @property
    def fingerprint(self):
        return _digest({"url":self.api_url,"provider":self.provider_id,"workspace":self.remote_workspace,
                        "agent_profile_id":self.agent_profile_id})


class OpenHandsHTTPError(RuntimeError):
    def __init__(self,status: int, *, saved_message: bool = False):
        self.status, self.saved_message = status, saved_message
        super().__init__("OpenHands HTTP status " + str(status))  # Never echo server/token/body.


class OpenHandsRecoveryLimit(ValueError):
    def __init__(self,cursor):
        self.cursor=cursor
        super().__init__("OpenHands recovery page budget exhausted; continue explicit authorized reads")


class OpenHandsHTTPTransport:
    def __init__(self, config: OpenHandsServerConfig, *, api_key: str | None = None, client=None):
        if not config.enabled: raise ValueError("OpenHands provider is not enabled")
        if api_key is not None and (not isinstance(api_key,str) or not api_key or any(c in api_key for c in "\r\n\0")):
            raise ValueError("invalid separately supplied OpenHands API key")
        self.config, self._key, self._client = config, api_key, client
        self._owned = client is None

    async def request(self, method: str, path: str, *, body=None, params=None):
        from sentra_runtime.effect_boundary import current_effect_context
        context = current_effect_context.get()
        if context is not None: context.checkpoint()
        if not path.startswith("/conversations") or ".." in path or "?" in path:
            raise ValueError("unapproved OpenHands route")
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("OpenHands HTTP requires separately installed httpx") from exc
            self._client = httpx.AsyncClient(follow_redirects=False,trust_env=False,timeout=self.config.timeout)
        headers = {"Accept":"application/json"}
        if self._key: headers["X-Session-API-Key"] = self._key
        # Stream with a bound; do not allocate an arbitrary server response.
        async with self._client.stream(method,self.config.api_url+path,json=body,params=params,headers=headers,
                                       follow_redirects=False,timeout=self.config.timeout) as response:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data)>self.config.max_response_bytes: raise ValueError("OpenHands response exceeds bound")
            if not 200<=response.status_code<300:
                raise OpenHandsHTTPError(response.status_code,
                    saved_message=method=="POST" and path.endswith("/events") and response.status_code==429)
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result: raise ValueError("duplicate OpenHands JSON key")
                    result[key]=value
                return result
            return json.loads(data,object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite OpenHands JSON")))

    async def close(self):
        if self._owned and self._client is not None:
            await self._client.aclose()
            self._client = None


class OpenHandsIdentityStore:
    def __init__(self, database: str, *, workspace: str):
        root, self.path = Path(workspace).resolve(), Path(database).resolve()
        if self.path==root or not self.path.is_relative_to(root): raise ValueError("OpenHands association DB outside workspace")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS oh_bindings(
                local_id TEXT PRIMARY KEY,provider TEXT NOT NULL,config_digest TEXT NOT NULL,
                remote_id TEXT NOT NULL,principal TEXT NOT NULL,machine TEXT NOT NULL,work_item TEXT NOT NULL,
                parent_local TEXT,state TEXT NOT NULL,cursor TEXT,UNIQUE(provider,remote_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS oh_events(
                local_id TEXT NOT NULL,event_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
                sha256 TEXT NOT NULL,kind TEXT NOT NULL,protected_event TEXT NOT NULL,
                PRIMARY KEY(local_id,event_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS oh_tools(
                local_id TEXT NOT NULL,tool_call_id TEXT NOT NULL,event_id TEXT NOT NULL,
                status TEXT,PRIMARY KEY(local_id,tool_call_id))""")

    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def get(self, local_id, config, request):
        result=self.lookup(local_id)
        if result is None: return None
        if (result["provider"],result["config_digest"],result["principal"],result["machine"],result["work_item"]) != (
            config.provider_id,config.fingerprint,request.principal_id,request.machine_id,request.work_item_id):
            raise EffectRejected("OpenHands association scope/config mismatch")
        return result

    def lookup(self, local_id):
        """Host-only association metadata, not an authorized content-read API."""
        with self._db() as db:
            row=db.execute("SELECT * FROM oh_bindings WHERE local_id=?",(_id(local_id),)).fetchone()
        return dict(row) if row is not None else None

    def prepare(self, local_id, remote_id, parent_local, config, request):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM oh_bindings WHERE local_id=?",(local_id,)).fetchone():
                raise EffectRejected("OpenHands association exists; read/reattach, never create again")
            db.execute("INSERT INTO oh_bindings VALUES(?,?,?,?,?,?,?,?,?,?)",(local_id,config.provider_id,
                config.fingerprint,remote_id,request.principal_id,request.machine_id,request.work_item_id,parent_local,"PREPARED",None))

    def update(self, local_id, *, state=None, cursor=None):
        with self._db() as db:
            if state is not None: db.execute("UPDATE oh_bindings SET state=? WHERE local_id=?",(state,local_id))
            else: db.execute("UPDATE oh_bindings SET cursor=? WHERE local_id=?",(cursor,local_id))

    def ingest_page(self, local_id, events, cursor):
        protected = [(event,_encode(json.loads(event.canonical_json))) for event in events]
        added=[]
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            ordinal=db.execute("SELECT COALESCE(MAX(ordinal),-1)+1 FROM oh_events WHERE local_id=?",(local_id,)).fetchone()[0]
            for event, encrypted in protected:
                old=db.execute("SELECT sha256,kind,ordinal FROM oh_events WHERE local_id=? AND event_id=?",(local_id,event.event_id)).fetchone()
                if old:
                    if old["sha256"]==event.source_digest: continue
                    raise ValueError("immutable OpenHands event changed")
                else:
                    db.execute("INSERT INTO oh_events VALUES(?,?,?,?,?,?)",(local_id,event.event_id,ordinal,
                        event.source_digest,event.kind,encrypted))
                    added.append({**event.public(),"ordinal":ordinal,"updated":False})
                    ordinal+=1
                if event.tool_call_id:
                    status = event.tool_status or ("reported_result" if event.kind=="ObservationEvent" else "reported_action")
                    current=db.execute("SELECT status FROM oh_tools WHERE local_id=? AND tool_call_id=?",
                                       (local_id,event.tool_call_id)).fetchone()
                    terminal={"completed","failed","reported_result"}
                    if current is None or current["status"] not in terminal or status in terminal:
                        db.execute("INSERT INTO oh_tools VALUES(?,?,?,?) ON CONFLICT(local_id,tool_call_id) DO UPDATE "
                                   "SET event_id=excluded.event_id,status=excluded.status",
                                   (local_id,event.tool_call_id,event.event_id,status))
            db.execute("UPDATE oh_bindings SET cursor=? WHERE local_id=?",(cursor,local_id))
        return added

    def tools(self, local_id):
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT tool_call_id,event_id,status FROM oh_tools WHERE local_id=?",
                                                   (local_id,))]

    def evidence(self, local_id, event_id):
        with self._db() as db:
            row=db.execute("SELECT * FROM oh_events WHERE local_id=? AND event_id=?",(local_id,event_id)).fetchone()
        if row is None: raise FileNotFoundError("OpenHands event evidence not found")
        raw=_decode(row["protected_event"])
        event=OpenHandsSDKEvent.from_mapping(raw)
        if event.source_digest!=row["sha256"]: raise ValueError("OpenHands evidence digest mismatch")
        return {**event.public(),"ordinal":row["ordinal"],"event":raw}


class OpenHandsAgentServerProvider:
    def __init__(self, gate: InteropGate, *, config: OpenHandsServerConfig,
                 identity_store: OpenHandsIdentityStore, transport: OpenHandsHTTPTransport,
                 authorize_parent=None, message_resolver=None):
        if not config.enabled or transport.config != config: raise ValueError("explicit matching OpenHands configuration required")
        if not callable(getattr(gate,"physical_context",None)):
            raise ValueError("OpenHands real provider requires host-injected durable physical gate")
        self.gate,self.config,self.store,self.transport=gate,config,identity_store,transport
        self.authorize_parent=authorize_parent
        self.message_resolver=message_resolver

    async def host_handler(self,request):
        """Register directly with host.bind_provider; content stays host-resolved.

        Resolver(request) retrieves protected text matching the admitted hash.
        It cannot change the remote destination/profile or grant an operation.
        """
        args=request.arguments
        local=args.get("local_id")
        cap=request.capability_id
        if cap in {"openhands:create","openhands:message"}:
            needs_text=cap=="openhands:message" or args.get("initial_message_sha256") is not None
            text=None
            if needs_text:
                if not callable(self.message_resolver): raise EffectRejected("host protected content resolver unavailable")
                text=self.message_resolver(request)
                if inspect.isawaitable(text): text=await text
            outcome=(await self.create(request,local_id=local,conversation_id=args.get("conversation_id"),
                parent_local_id=args.get("parent_local_id"),initial_message=text) if cap=="openhands:create"
                else await self.send_message(request,local_id=local,text=text,run=args.get("run",False)))
        elif cap=="openhands:read": outcome=await self.read(request,local_id=local)
        elif cap=="openhands:events": outcome=await self.events(request,local_id=local,
            page_id=args.get("page_id"),limit=args.get("limit",100))
        elif cap=="openhands:evidence": outcome=await self.evidence(request,local_id=local,event_id=args.get("event_id"))
        elif cap=="openhands:run": outcome=await self.run(request,local_id=local)
        elif cap=="openhands:cancel": outcome=await self.cancel(request,local_id=local,immediate=args.get("immediate",True))
        else: raise EffectRejected("unknown OpenHands host capability")
        return self.host_result(outcome)

    async def close(self):
        """Close only the owned client; never pause/delete remote conversations."""
        await self.transport.close()

    async def _admit(self,request,effect,*,timeout=None):
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        if context is None:
            return await self.gate.execute(request,effect,timeout=timeout)
        if _fingerprint(context.request)!=_fingerprint(request):
            raise EffectRejected("OpenHands nested physical intent mismatch")
        # Host bind_provider already reserved and fenced this exact intent.
        # Do not reserve it a second time or acquire the same physical lock.
        context.checkpoint()
        payload=await effect()
        if isinstance(payload,OperationResult):
            return DispatchOutcome(payload,dict(payload.evidence))
        return DispatchOutcome(OperationResult(request.operation_id,"SUCCEEDED"),payload)

    @staticmethod
    def host_result(outcome: DispatchOutcome):
        """Unwrap a provider method for a host's already-fenced callback."""
        return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation

    def _check(self,request,cap,args):
        if request.capability_id!=cap or request.arguments!=args:
            raise EffectRejected("OpenHands operation intent mismatch")

    def _binding(self, local_id, request):
        binding=self.store.get(local_id,self.config,request)
        if binding is None: raise EffectRejected("OpenHands binding missing; explicit create required")
        return binding

    async def _parent_binding(self,local_id,request):
        parent=self.store.lookup(local_id)
        if parent is None or parent["provider"]!=self.config.provider_id or parent["config_digest"]!=self.config.fingerprint:
            raise EffectRejected("OpenHands parent config/binding unavailable")
        if (parent["principal"],parent["machine"],parent["work_item"])!=(
            request.principal_id,request.machine_id,request.work_item_id):
            if not callable(self.authorize_parent): raise EffectRejected("OpenHands cross-scope parent access denied")
            decision=self.authorize_parent(dict(parent),request)
            if inspect.isawaitable(decision): decision=await decision
            if not isinstance(decision,PolicyDecision) or decision.allowed is not True or decision.constraints:
                raise EffectRejected("OpenHands parent reference not authorized by host")
        return parent

    def create_arguments(self, *, local_id, conversation_id, parent_local_id=None, initial_message=None):
        return {"local_id":_id(local_id),"conversation_id":_uuid(conversation_id),"parent_local_id":parent_local_id,
                "initial_message_sha256":_digest(initial_message) if initial_message is not None else None,
                "config_sha256":self.config.fingerprint}

    async def create(self, request, *, local_id, conversation_id, parent_local_id=None, initial_message=None):
        async def effect():
            remote_id=_uuid(conversation_id)
            self._check(request,"openhands:create",self.create_arguments(local_id=local_id,
                conversation_id=remote_id,parent_local_id=parent_local_id,initial_message=initial_message))
            parent=await self._parent_binding(parent_local_id,request) if parent_local_id is not None else None
            if parent and parent["state"] in {"PREPARED","UNCERTAIN"}: raise EffectRejected("parent conversation not confirmed")
            body={"conversation_id":remote_id,"workspace":{"working_dir":self.config.remote_workspace},
                  "agent_profile_id":self.config.agent_profile_id}
            if parent: body["parent_conversation_id"]=parent["remote_id"]
            if initial_message is not None:
                if not isinstance(initial_message,str) or not initial_message or len(initial_message.encode())>32768:
                    raise EffectRejected("invalid initial OpenHands message")
                body["initial_message"]={"role":"user","content":[{"type":"text","text":initial_message}],"run":False}
            self.store.prepare(local_id,remote_id,parent_local_id,self.config,request)
            try:
                info=await self.transport.request("POST","/conversations",body=body)
                result=self._info(info,remote_id,parent["remote_id"] if parent else None)
                self.store.update(local_id,state=result["execution_status"])
                return {"local_id":local_id,**result,"completion_confirmed":False}
            except BaseException:
                self.store.update(local_id,state="UNCERTAIN")
                raise
        return await self._admit(request,effect,timeout=self.config.timeout+1)

    def _info(self,raw,remote_id,parent_id):
        if not isinstance(raw,Mapping) or _uuid(raw.get("id"))!=remote_id:
            raise ValueError("OpenHands conversation identity mismatch")
        workspace=raw.get("workspace")
        if not isinstance(workspace,Mapping) or workspace.get("working_dir")!=self.config.remote_workspace:
            raise ValueError("OpenHands server workspace mismatch")
        parent=raw.get("parent_conversation_id")
        if (_uuid(parent) if parent is not None else None)!=parent_id:
            raise ValueError("OpenHands parent identity mismatch")
        state=raw.get("execution_status")
        if state not in {"idle","running","paused","finished","error","stuck","deleting"}:
            raise ValueError("unknown OpenHands execution status")
        children=raw.get("sub_conversation_ids",[])
        if not isinstance(children,list) or len(children)>1000: raise ValueError("invalid OpenHands child catalog")
        return {"conversation_id":remote_id,"parent_conversation_id":parent,"execution_status":state,
                "sub_conversation_ids":[_uuid(x) for x in children]}

    async def read(self, request, *, local_id):
        async def effect():
            self._check(request,"openhands:read",{"local_id":local_id})
            binding=self._binding(local_id,request)
            parent=await self._parent_binding(binding["parent_local"],request) if binding["parent_local"] else None
            raw=await self.transport.request("GET","/conversations/"+binding["remote_id"])
            info=self._info(raw,binding["remote_id"],parent["remote_id"] if parent else None)
            self.store.update(local_id,state=info["execution_status"])
            return {"local_id":local_id,**info,"reattached":True,"cursor":binding["cursor"]}
        return await self._admit(request,effect,timeout=self.config.timeout+1)

    async def reattach(self, request, *, local_id):
        return await self.read(request,local_id=local_id)  # GET only, never create/run/send.

    async def events(self, request, *, local_id, page_id=None, limit=100):
        async def effect():
            self._check(request,"openhands:events",{"local_id":local_id,"page_id":page_id,"limit":limit})
            binding=self._binding(local_id,request)
            if type(limit) is not int or not 1<=limit<=100 or (page_id is not None and (not isinstance(page_id,str) or len(page_id)>4096)):
                raise EffectRejected("invalid OpenHands page cursor")
            params={"sort_order":"TIMESTAMP","limit":limit}
            if page_id is not None: params["page_id"]=page_id
            raw=await self.transport.request("GET","/conversations/"+binding["remote_id"]+"/events/search",params=params)
            if not isinstance(raw,Mapping) or not isinstance(raw.get("items"),list) or len(raw["items"])>limit:
                raise ValueError("invalid OpenHands event page")
            cursor=raw.get("next_page_id")
            if cursor is not None and (not isinstance(cursor,str) or not cursor or len(cursor)>4096 or cursor==page_id):
                raise ValueError("invalid/repeated OpenHands cursor")
            typed=[OpenHandsSDKEvent.from_mapping(row) for row in raw["items"]]
            added=self.store.ingest_page(local_id,typed,cursor)
            return {"local_id":local_id,"events":added,"next_page_id":cursor,
                    "duplicates":len(typed)-len(added),"server_sequence_available":False,
                    "tool_projection":self.store.tools(local_id)}
        return await self._admit(request,effect,timeout=self.config.timeout+1)

    async def recover_events(self, *, local_id, request_factory, max_pages=32):
        """Start at the head after disconnect to catch gaps/out-of-order inserts.

        Factory receives exact capability/arguments and must create a fresh
        authorized read operation identity. Only GETs are performed here.
        """
        if type(max_pages) is not int or not 1<=max_pages<=1000: raise ValueError("invalid recovery page budget")
        cursor=None
        seen=set()
        for _ in range(max_pages):
            args={"local_id":local_id,"page_id":cursor,"limit":100}
            result=await self.events(request_factory("openhands:events",args),local_id=local_id,page_id=cursor)
            yield result
            if result.operation.state!="SUCCEEDED": return
            cursor=result.payload["next_page_id"]
            if cursor is None: return
            if cursor in seen: raise ValueError("OpenHands pagination cycle")
            seen.add(cursor)
        raise OpenHandsRecoveryLimit(cursor)

    async def evidence(self,request,*,local_id,event_id):
        async def effect():
            self._check(request,"openhands:evidence",{"local_id":local_id,"event_id":event_id})
            self._binding(local_id,request)
            return self.store.evidence(local_id,_id(event_id))
        return await self._admit(request,effect)

    async def send_message(self,request,*,local_id,text,run=False):
        async def effect():
            self._check(request,"openhands:message",{"local_id":local_id,"text_sha256":_digest(text),"run":run})
            binding=self._binding(local_id,request)
            if not isinstance(text,str) or not text or len(text.encode())>32768 or type(run) is not bool:
                raise EffectRejected("invalid OpenHands message")
            try:
                result=await self.transport.request("POST","/conversations/"+binding["remote_id"]+"/events",
                    body={"role":"user","content":[{"type":"text","text":text}],"run":run})
            except OpenHandsHTTPError as exc:
                if exc.saved_message:
                    return OperationResult(request.operation_id,"UNCERTAIN",{
                        "message_saved":True,"run_capacity_full":True,"resend_message":False},
                        "message saved; inspect events before separately authorized run")
                raise
            if not isinstance(result,Mapping) or result.get("success") is not True: raise ValueError("invalid OpenHands message ack")
            return {"conversation_id":binding["remote_id"],"message_saved":True,"completion_confirmed":False}
        return await self._admit(request,effect,timeout=self.config.timeout+1)

    async def run(self,request,*,local_id):
        async def effect():
            self._check(request,"openhands:run",{"local_id":local_id})
            binding=self._binding(local_id,request)
            result=await self.transport.request("POST","/conversations/"+binding["remote_id"]+"/run")
            if not isinstance(result,Mapping) or result.get("success") is not True: raise ValueError("invalid OpenHands run ack")
            return {"conversation_id":binding["remote_id"],"run_accepted":True,"completion_confirmed":False}
        return await self._admit(request,effect,timeout=self.config.timeout+1)

    async def cancel(self,request,*,local_id,immediate=True):
        async def effect():
            self._check(request,"openhands:cancel",{"local_id":local_id,"immediate":immediate})
            binding=self._binding(local_id,request)
            if type(immediate) is not bool: raise EffectRejected("invalid cancellation mode")
            path="/conversations/"+binding["remote_id"]
            response=await self.transport.request("POST",path+("/interrupt" if immediate else "/pause"))
            if not isinstance(response,Mapping) or response.get("success") is not True: raise ValueError("invalid cancellation ack")
            try:
                info=await self.transport.request("GET",path)
                parent=await self._parent_binding(binding["parent_local"],request) if binding["parent_local"] else None
                state=self._info(info,binding["remote_id"],parent["remote_id"] if parent else None)["execution_status"]
            except Exception:
                self.store.update(local_id,state="UNCERTAIN")
                return OperationResult(request.operation_id,"UNCERTAIN",{
                    "conversation_id":binding["remote_id"],"acknowledged":True,"pause_confirmed":False,
                    "effects_rolled_back":False,"diagnostic":"STATUS_UNAVAILABLE_AFTER_ACK"},
                    "cancellation acknowledged; status unavailable, read same conversation")
            confirmed=state=="paused"
            self.store.update(local_id,state="paused" if confirmed else "UNCERTAIN")
            return OperationResult(request.operation_id,"CANCELLED" if confirmed else "UNCERTAIN",{
                "conversation_id":binding["remote_id"],"acknowledged":True,"pause_confirmed":confirmed,
                "effects_rolled_back":False,"mode":"interrupt" if immediate else "pause"},
                None if confirmed else "pause not confirmed; read same conversation, never repeat effects")
        return await self._admit(request,effect,timeout=self.config.timeout*2+1)
