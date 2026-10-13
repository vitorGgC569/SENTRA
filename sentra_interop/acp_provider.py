"""Host-facing ACP lifecycle using negotiated adapter state and central effects."""
import asyncio
import copy
from pathlib import Path

from sentra_runtime.contracts import OperationResult
from .acp import ACPSessionAdapter, ACPProtocolError
from .gate import EffectRejected
from .provider_store import digest, identifier


class ACPProviderSession:
    def __init__(self,transport,gate,*,configuration,workspace,store,content,local_id):
        self.transport,self.gate,self.config,self.store,self.content=transport,gate,configuration,store,content
        self.workspace=str(Path(workspace).resolve())
        self.local_id=identifier(local_id)
        self.config_digest=digest(configuration)
        self.adapter=ACPSessionAdapter(gate,transport,workspace=workspace,
            supported_versions=tuple(configuration.get("supported_versions",[1])),provider=configuration["provider_id"])
        self._event_count=0

    def binding(self,request):
        binding=self.store.get(request,self.local_id,self.config_digest)
        if binding is None or binding["remote_id"] is None or binding["state"]=="DELETED":
            raise EffectRejected("ACP durable session unavailable; reconcile the creation operation")
        return binding

    async def collect_one(self,request,timeout):
        packet=await self.transport.next_update(timeout)
        binding=self.binding(request)
        if packet.get("sessionId")!=binding["remote_id"] or not isinstance(packet.get("update"),dict):
            raise ACPProtocolError("ACP update belongs to another session")
        self.adapter.state.apply(packet["update"])
        self._event_count+=1
        self.store.ingest(request,self.local_id,event_id=digest({"operation":request.operation_id,
            "ordinal":self._event_count,"packet":packet}),payload=packet)
        return packet["update"]

    async def rpc_with_updates(self,request,method,params):
        task=asyncio.create_task(self.transport.request(method,params,120))
        try:
            while not task.done():
                try:
                    await self.collect_one(request,.1)
                except asyncio.TimeoutError:pass
            result=await task
            while not self.transport._updates.empty():
                await self.collect_one(request,.1)
            return result
        finally:
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    async def handle(self,request):
        args=request.arguments;cap=request.capability_id
        if cap=="acp:events":return self.store.events(request,self.local_id,after=args["after"],limit=args["limit"])
        if cap=="acp:state":
            binding=self.binding(request)
            return {"session_id":binding["remote_id"],"state":binding["state"],
                    "protocol_version":self.adapter.protocol_version,"capabilities":dict(self.adapter.capabilities),
                    "config_options":copy.deepcopy(self.adapter.state.config_options if self.adapter.state else []),
                    "terminals":copy.deepcopy(self.adapter.state.terminals if self.adapter.state else {}),
                    "plan":copy.deepcopy(self.adapter.state.plan if self.adapter.state else None),
                    "usage":copy.deepcopy(self.adapter.state.usage if self.adapter.state else None),
                    "usage_known":bool(self.adapter.state and self.adapter.state.usage is not None)}
        if cap=="acp:session":
            self.store.prepare(request,self.local_id,self.config_digest)
            await self.adapter._initialize(30)
            result=await self.transport.request("session/new",{"cwd":self.workspace,"mcpServers":[]},30)
            remote=identifier(result.get("sessionId"))
            self.store.bind(request,self.local_id,self.config_digest,remote)
            self.adapter.session_id=remote;self.adapter.state.setup(result)
            return {"local_id":self.local_id,"session_id":remote,"protocol_version":self.adapter.protocol_version,
                    "capabilities":self.adapter.capabilities,"config_options":self.adapter.state.config_options}
        await self.adapter._initialize(30)
        if cap=="acp:list":
            if not self.adapter.supports("session/list"):raise EffectRejected("ACP list not advertised")
            params={"cwd":self.workspace}
            if args.get("cursor") is not None:params["cursor"]=args["cursor"]
            result=await self.transport.request("session/list",params,30)
            sessions=result.get("sessions")
            if not isinstance(sessions,list) or len(sessions)>1000:raise ValueError("invalid ACP session page")
            # Agent-side listing is not authority for another SENTRA WorkItem.
            # Return only the exact already-bound external session.
            binding=self.store.get(request,self.local_id,self.config_digest)
            rows=[s for s in sessions if isinstance(s,dict) and binding and s.get("sessionId")==binding["remote_id"]]
            return {"sessions":rows,"next_cursor":result.get("nextCursor")}
        binding=self.binding(request);remote=binding["remote_id"]
        if cap in {"acp:resume","acp:load"}:
            method="session/load" if cap=="acp:load" else "session/resume"
            if not self.adapter.supports(method):raise EffectRejected("ACP resume/load not advertised")
            response=await self.transport.request(method,{"sessionId":remote,"cwd":self.workspace,"mcpServers":[]},30)
            if response.get("sessionId",remote)!=remote:raise ValueError("ACP resume changed external identity")
            self.adapter.session_id=remote;self.adapter.state.setup(response)
            self.store.state(request,self.local_id,"ACTIVE")
            return {"session_id":remote,"resumed":True,"effects_replayed":False}
        if self.adapter.session_id!=remote:raise EffectRejected("ACP detached; launch then explicitly resume")
        if cap in {"acp:close","acp:delete"}:
            method="session/"+cap.split(":")[1]
            if not self.adapter.supports(method):raise EffectRejected("ACP lifecycle method not advertised")
            response=await self.transport.request(method,{"sessionId":remote},30)
            self.store.state(request,self.local_id,"DELETED" if cap=="acp:delete" else "CLOSED")
            self.adapter.session_id=None
            return response
        if cap=="acp:config":
            option=next((o for o in self.adapter.state.config_options if o["id"]==args["config_id"]),None)
            if option is None:raise EffectRejected("ACP option not advertised")
            value=self.content.resolve_value(request,"value_sha256")
            if (option["type"]=="boolean" and type(value) is not bool or option["type"]=="select"
                    and value not in self.adapter.state.option_values(option)):
                raise EffectRejected("ACP option value not supported")
            params={"sessionId":remote,"configId":args["config_id"],"value":value}
            if option["type"]=="boolean":params["type"]="boolean"
            response=await self.transport.request("session/set_config_option",params,30)
            self.adapter.state.set_config(response.get("configOptions"))
            return {"config_options":self.adapter.state.config_options}
        if cap=="acp:mode":
            if not self.adapter.supports("session/set_mode") or args["mode_id"] not in {
                    m.get("id") for m in self.adapter.state.modes.get("availableModes",[])}:
                raise EffectRejected("ACP mode not advertised")
            result=await self.transport.request("session/set_mode",{"sessionId":remote,"modeId":args["mode_id"]},30)
            self.adapter.state.modes["currentModeId"]=args["mode_id"]
            return result
        if cap=="acp:cancel":
            await self.transport.notify("session/cancel",{"sessionId":remote})
            self.store.state(request,self.local_id,"UNCERTAIN")
            return OperationResult(request.operation_id,"UNCERTAIN",{"session_id":remote,"cancel_requested":True},
                                   "ACP cancellation sent; remote completion requires observation")
        if cap=="acp:prompt":
            text=self.content.resolve(request)
            result=await self.rpc_with_updates(request,"session/prompt",{"sessionId":remote,
                "prompt":[{"type":"text","text":text}]})
            if self.adapter.protocol_version==2:
                return {"message_id":identifier(result.get("messageId")),"completion_confirmed":False}
            reason=result.get("stopReason")
            if reason not in {"end_turn","max_tokens","max_turn_requests","refusal","cancelled"}:
                raise ValueError("ACP invalid stop reason")
            if reason=="cancelled":
                return OperationResult(request.operation_id,"CANCELLED",{"stop_reason":reason})
            return {"stop_reason":reason,"completion_confirmed":reason=="end_turn",
                    "usage":self.adapter.state.usage,"usage_known":self.adapter.state.usage is not None}
        raise EffectRejected("unknown ACP provider capability")

    async def close(self):
        await self.transport.close()
