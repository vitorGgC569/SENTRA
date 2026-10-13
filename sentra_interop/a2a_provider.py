"""Configured A2A JSON-RPC provider against the pinned PascalCase revision.

HTTPS authentication and an independently approved Agent Card hash bind the
peer. Discovery cannot select a new URL or grant any task. Reconnect subscribes
to an existing task; it never repeats SendMessage.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from sentra_runtime.contracts import OperationResult
from sentra_runtime.effect_boundary import current_effect_context
from .a2a import A2AEnvelope, AgentIdentity, STATES, TERMINAL,normalize_parts
from .gate import EffectRejected
from .provider_store import canonical, digest, identifier


def decode(data):
    def unique(pairs):
        value = {}
        for key,item in pairs:
            if key in value:
                raise ValueError("duplicate protocol JSON property")
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite protocol value")))


def approved_url(value):
    url = urlsplit(value)
    if (url.scheme not in {"https","http"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or any(c.isspace() for c in value)
            or url.scheme == "http" and url.hostname not in {"localhost","127.0.0.1","::1"}):
        raise ValueError("protocol requires configured HTTPS or loopback endpoint")
    return value.rstrip("/")


@dataclass(frozen=True)
class A2AProviderConfig:
    endpoint: str
    provider_id: str
    trust_domain: str
    card_sha256: str
    enabled: bool = False
    card_url: str | None = None
    timeout: float = 30
    tenant: str | None = None
    callback_url: str | None = None

    def __post_init__(self):
        approved_url(self.endpoint)
        identifier(self.provider_id)
        identifier(self.trust_domain)
        if (self.enabled is not True or len(self.card_sha256)!=64
                or any(c not in "0123456789abcdef" for c in self.card_sha256)
                or type(self.timeout) not in (int,float) or not 0<self.timeout<=120):
            raise ValueError("enabled A2A endpoint and approved card pin required")
        if self.tenant is not None:
            identifier(self.tenant)
        if self.card_url:
            approved_url(self.card_url)
            if urlsplit(self.card_url).netloc != urlsplit(self.endpoint).netloc:
                raise ValueError("A2A card must use configured peer origin")
        if self.callback_url:
            approved_url(self.callback_url)

    @property
    def fingerprint(self):
        return digest({"endpoint":self.endpoint,"provider":self.provider_id,"trust":self.trust_domain,
                       "card":self.card_sha256,"tenant":self.tenant,"callback":self.callback_url})


class A2AHTTPTransport:
    def __init__(self, config, credential=None):
        self.config, self.credential = config, credential
        self.client = None

    def checkpoint(self):
        context = current_effect_context.get()
        if context is None:
            raise EffectRejected("A2A network access outside central effect admission")
        context.checkpoint()

    def headers(self):
        value = {"Accept":"application/json, text/event-stream"}
        if self.credential:
            token = self.credential()
            if not isinstance(token,str) or not token or any(c in token for c in "\r\n\0"):
                raise EffectRejected("A2A credential unavailable")
            value["Authorization"] = "Bearer "+token
        return value

    def http(self):
        if self.client is None:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("A2A HTTP provider requires httpx") from exc
            self.client = httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=self.config.timeout)
        return self.client

    async def card(self):
        self.checkpoint()
        parsed = urlsplit(self.config.endpoint)
        url = self.config.card_url or f"{parsed.scheme}://{parsed.netloc}/.well-known/agent-card.json"
        async with self.http().stream("GET",url,headers=self.headers()) as response:
            raw = await self._body(response)
        card = decode(raw)
        if not isinstance(card,dict) or digest(card)!=self.config.card_sha256:
            raise EffectRejected("A2A Agent Card does not match approved peer revision")
        interfaces = card.get("supportedInterfaces", [])
        if not any(isinstance(i,dict) and i.get("url","").rstrip("/")==self.config.endpoint.rstrip("/")
                   and i.get("protocolBinding") == "JSONRPC" and i.get("tenant") in (None,self.config.tenant)
                   for i in interfaces):
            raise EffectRejected("A2A card does not advertise configured JSONRPC interface")
        if not isinstance(card.get("capabilities",{}),dict):
            raise ValueError("invalid A2A capabilities")
        self.checkpoint()
        return card

    async def _body(self,response):
        if not 200<=response.status_code<300:
            raise RuntimeError("A2A HTTP status "+str(response.status_code))
        data = bytearray()
        async for chunk in response.aiter_bytes():
            self.checkpoint()
            data.extend(chunk)
            if len(data)>2*1024*1024:
                raise ValueError("A2A response exceeds bound")
        return data

    def packet(self,method,params,request_id):
        if self.config.tenant:
            params = {**params,"tenant":self.config.tenant}
        return {"jsonrpc":"2.0","id":request_id,"method":method,"params":params}

    def result(self,packet,request_id):
        if (not isinstance(packet,dict) or packet.get("jsonrpc")!="2.0" or packet.get("id")!=request_id
                or ("result" in packet)==("error" in packet)):
            raise ValueError("A2A response identity mismatch")
        if "error" in packet:
            raise RuntimeError("A2A peer rejected protocol request")
        if not isinstance(packet["result"],dict):
            raise ValueError("invalid A2A result")
        return packet["result"]

    async def rpc(self,method,params,request_id):
        self.checkpoint()
        async with self.http().stream("POST",self.config.endpoint,headers=self.headers(),
                                      json=self.packet(method,params,request_id)) as response:
            raw = await self._body(response)
        self.checkpoint()
        return self.result(decode(raw),request_id)

    async def stream(self,method,params,request_id,*,event_limit=100):
        self.checkpoint()
        async with self.http().stream("POST",self.config.endpoint,headers=self.headers(),
                                      json=self.packet(method,params,request_id)) as response:
            if response.status_code!=200 or "text/event-stream" not in response.headers.get("content-type",""):
                raise ValueError("A2A peer did not open an event stream")
            buffer=b"";data=[];size=0;count=0;event_id=None
            async for chunk in response.aiter_bytes():
                self.checkpoint()
                buffer+=chunk
                if len(buffer)>262144:
                    raise ValueError("A2A SSE buffer exceeds bound")
                while b"\n" in buffer:
                    line,buffer=buffer.split(b"\n",1);line=line.rstrip(b"\r")
                    if line.startswith(b"data:"):
                        data.append(line[5:].lstrip());size+=len(line)
                        if size>262144:raise ValueError("A2A SSE event exceeds bound")
                    elif line.startswith(b"id:"):
                        event_id=identifier(line[3:].strip().decode())
                    elif not line and data:
                        value=self.result(decode(b"\n".join(data)),request_id)
                        yield event_id,value
                        count+=1;data=[];size=0;event_id=None
                        if count>=event_limit:return
            if data or buffer.strip():
                raise ValueError("A2A incomplete event stream")

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
            self.client=None


class A2AProvider:
    def __init__(self,config,store,transport,content,callback_credential=None,callback_ingress=None):
        self.config,self.store,self.transport,self.content = config,store,transport,content
        self.callback_credential=callback_credential
        self.callback_ingress=callback_ingress
        self.identity=AgentIdentity(config.provider_id,config.provider_id,config.trust_domain)

    def binding(self,request):
        value=self.store.get(request,request.arguments["local_id"],self.config.fingerprint)
        if value is None or value["remote_id"] is None:
            raise EffectRejected("A2A task identity is unavailable; inspect original operation")
        return value

    def ingest(self,request,payload,event_id=None):
        local=request.arguments["local_id"]
        binding=self.store.get(request,local,self.config.fingerprint)
        if binding is None:raise EffectRejected("A2A event has no admitted task")
        if set(payload)=={"message"}:
            message=payload["message"]
            if not isinstance(message,dict):raise ValueError("invalid A2A response message")
            remote=identifier(message.get("messageId"));context=identifier(message.get("contextId"))
            normalize_parts(message.get("parts",[]))
            self.store.bind(request,local,self.config.fingerprint,remote,context,"MESSAGE")
            result=self.store.ingest(request,local,event_id=event_id or digest(payload),payload=payload)
            return {**result,"message_id":remote,"context_id":context,"state":"message_received",
                    "task_completion_confirmed":False}
        # A task response is a full snapshot. Artifact and status updates carry
        # explicit identities and append/final flags; duplicate event IDs cannot
        # append twice. Content hashes are fallback IDs for immutable snapshots.
        envelope=A2AEnvelope.from_stream_response(payload,identity=self.identity,
            authenticated_principal_id=self.identity.principal_id,event_id=event_id or digest(payload),
            sequence=0,current_state=binding["state"] if binding["state"] in STATES else None)
        if binding["remote_id"] is not None and (envelope.task_id,envelope.context_id)!=(
                binding["remote_id"],binding["context_id"]):
            raise EffectRejected("A2A event task/context belongs to another binding")
        old_state=binding["state"]
        try:old_event=self.store.event(request,local,envelope.event_id)
        except FileNotFoundError:old_event=None
        if old_event is not None:
            if digest(old_event)!=digest(payload):raise EffectRejected("A2A repeated event content changed")
            return {"event_id":envelope.event_id,"duplicate":True,"task_id":envelope.task_id,
                    "context_id":envelope.context_id,"state":old_state,"task_completion_confirmed":old_state=="completed"}
        if old_state in TERMINAL and envelope.state!=old_state:
            raise EffectRejected("A2A terminal task state cannot change")
        # Do not regress current state when a previously persisted event is
        # replayed after resubscription.
        if binding["remote_id"] is None:
            self.store.bind(request,local,self.config.fingerprint,envelope.task_id,envelope.context_id,envelope.state)
        artifact=None
        recover_artifact=False
        if envelope.artifact_id:
            if envelope.artifact_append and not event_id:
                # A2A does not mandate an SSE event id. Identical append chunks
                # cannot be deduplicated by content; recover a full Task
                # snapshot instead of silently dropping or repeating bytes.
                recover_artifact=True
            else:
                artifact={"artifact_id":envelope.artifact_id,"append":envelope.artifact_append,
                          "complete":envelope.artifact_final,"parts":list(envelope.parts)}
        snapshots=[]
        if "task" in payload:
            for item in payload["task"].get("artifacts",[]):
                # Snapshots are immutable per digest. Full artifacts replace
                # incomplete stream projections once and never replay chunks.
                if not isinstance(item,dict):raise ValueError("invalid task artifact")
                aid=identifier(item.get("artifactId"))
                parts=item.get("parts",[])
                normalized=normalize_parts(parts)
                snapshots.append({"artifact_id":aid,"append":False,"complete":True,"parts":normalized})
        result=self.store.ingest(request,local,event_id=envelope.event_id,payload=payload,artifact=artifact,artifacts=snapshots)
        if not result["duplicate"]:self.store.state(request,local,envelope.state)
        return {**result,"task_id":envelope.task_id,"context_id":envelope.context_id,
                "state":envelope.state,"task_completion_confirmed":envelope.state=="completed",
                "artifact_recovery_required":recover_artifact}

    async def handle(self,request):
        args=request.arguments;cap=request.capability_id;local=args.get("local_id")
        if cap=="a2a:events":return self.store.events(request,local,after=args["after"],limit=args["limit"])
        if cap=="a2a:artifact":return self.store.artifact(request,local,args["artifact_id"])
        if cap=="a2a:callback":
            # Incoming HTTP adapter has already verified its configured peer
            # token/signature. This operation only stores a typed projection.
            if self.callback_ingress is None:raise EffectRejected("A2A callback ingress not configured")
            payload=self.callback_ingress.value(request,args["event_id"])
            projection=self.ingest(request,payload)
            if "artifactUpdate" in payload:
                binding=self.binding(request)
                snapshot=await self.transport.rpc("GetTask",{"id":binding["remote_id"]},request.operation_id)
                projection=self.ingest(request,{"task":snapshot})
            return projection
        card=await self.transport.card()
        if cap=="a2a:discover":
            return {"provider_id":self.config.provider_id,"card_sha256":self.config.card_sha256,
                    "capabilities":card["capabilities"],"skills":card.get("skills",[])}
        if cap=="a2a:extended_card":
            if card["capabilities"].get("extendedAgentCard") is not True:
                raise EffectRejected("A2A extended card not supported")
            result=await self.transport.rpc("GetExtendedAgentCard",{},request.operation_id)
            return {"card":result,"public_card_sha256":self.config.card_sha256}
        if cap=="a2a:send":
            self.store.prepare(request,local,self.config.fingerprint)
            message={"messageId":args["message_id"],"role":"ROLE_USER",
                     "parts":[{"text":self.content.resolve(request)}]}
            result=await self.transport.rpc("SendMessage",{"message":message,
                "configuration":{"acceptedOutputModes":["text/plain","application/json"],
                                 "historyLength":0,"returnImmediately":True}},request.operation_id)
            return self.ingest(request,result)
        binding=self.binding(request)
        if binding["state"]=="MESSAGE":raise EffectRejected("A2A peer returned a stateless message, not a task")
        if cap=="a2a:continue":
            if binding["state"] not in {"input-required","auth-required","working","submitted"}:
                raise EffectRejected("A2A terminal task cannot continue")
            result=await self.transport.rpc("SendMessage",{"message":{"messageId":args["message_id"],
                "role":"ROLE_USER","taskId":binding["remote_id"],"contextId":binding["context_id"],
                "parts":[{"text":self.content.resolve(request)}]},"configuration":{"returnImmediately":True,
                "acceptedOutputModes":["text/plain","application/json"],"historyLength":0}},request.operation_id)
            return self.ingest(request,result)
        if cap in {"a2a:get","a2a:cancel"}:
            result=await self.transport.rpc("GetTask" if cap=="a2a:get" else "CancelTask",
                                           {"id":binding["remote_id"]},request.operation_id)
            projection=self.ingest(request,{"task":result})
            if cap=="a2a:cancel":
                return OperationResult(request.operation_id,"CANCELLED" if projection["state"]=="canceled" else "UNCERTAIN",
                    projection,None if projection["state"]=="canceled" else "A2A cancellation not confirmed")
            return projection
        if cap=="a2a:subscribe":
            if card["capabilities"].get("streaming") is not True:
                raise EffectRejected("A2A peer does not advertise streaming")
            updates=[]
            async for eid,value in self.transport.stream("SubscribeToTask",{"id":binding["remote_id"]},
                                                         request.operation_id,event_limit=args["limit"]):
                updates.append(self.ingest(request,value,eid))
            if any(i.get("artifact_recovery_required") for i in updates):
                snapshot=await self.transport.rpc("GetTask",{"id":binding["remote_id"]},request.operation_id)
                updates.append(self.ingest(request,{"task":snapshot}))
            return {"items":updates,"resubscribe_task_id":binding["remote_id"],"send_replayed":False}
        if cap=="a2a:push_set":
            if card["capabilities"].get("pushNotifications") is not True or not self.config.callback_url:
                raise EffectRejected("A2A push callback is not configured/supported")
            if not self.callback_credential:raise EffectRejected("A2A callback credential not configured")
            response=await self.transport.rpc("CreateTaskPushNotificationConfig",{"taskId":binding["remote_id"],
                "config":{"id":args["config_id"],"url":self.config.callback_url,
                          "token":self.callback_credential()}},request.operation_id)
            if response.get("taskId")!=binding["remote_id"]:raise ValueError("A2A push task mismatch")
            return {"task_id":binding["remote_id"],"config_id":args["config_id"],"configured":True}
        if cap=="a2a:push_delete":
            await self.transport.rpc("DeleteTaskPushNotificationConfig",{"taskId":binding["remote_id"],
                                     "id":args["config_id"]},request.operation_id)
            return {"config_id":args["config_id"],"deleted":True}
        if cap=="a2a:extended_card":
            if card["capabilities"].get("extendedAgentCard") is not True:
                raise EffectRejected("A2A extended card not supported")
            result=await self.transport.rpc("GetExtendedAgentCard",{},request.operation_id)
            return {"card":result,"public_card_sha256":self.config.card_sha256}
        raise EffectRejected("unknown A2A operation")

    async def close(self):
        await self.transport.close()
