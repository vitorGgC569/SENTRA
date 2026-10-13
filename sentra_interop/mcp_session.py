"""Revision-aware MCP tools/resources/prompts over a central-owned transport."""
from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping

from sentra_runtime.contracts import OperationResult
from .gate import EffectRejected
from .mcp_stdio import MCPStdioClient, MCPStdioError
from .provider_store import digest, identifier, canonical


class MCPSDKProcessClient(MCPStdioClient):
    async def connect_sdk(self, *, endpoint, protocol_version, token=None, elicitation=False,session_id=None,discovery=None):
        response = await self._call("sentra/connect",{"endpoint":endpoint,"protocol_version":protocol_version,
                                   "token":token,"elicitation":elicitation,"session_id":session_id,"discovery":discovery},30)
        if response.get("protocolVersion")!=protocol_version:
            raise MCPStdioError("MCP SDK revision differs from approved pin")
        self.protocol_version=protocol_version
        self.server_capabilities=response.get("capabilities",{})
        self._initialized=True
        return response

    async def _answer_server(self,msg):
        if msg.get("method")!="sentra/checkpoint":
            return await super()._answer_server(msg)
        from sentra_runtime.effect_boundary import current_effect_context
        contexts=[c for key,c in self._contexts.items() if c is not None and key in self._pending]
        context=contexts[0] if len(contexts)==1 else None
        token=current_effect_context.set(context)
        try:
            if context is None:raise EffectRejected("SDK I/O has no active central operation")
            context.checkpoint()
            await self._send({"jsonrpc":"2.0","id":msg["id"],"result":{"allowed":True}})
        except Exception:
            try:
                self.process.stdin.write(__import__("sentra_interop.mcp_stdio",fromlist=["_encode"])._encode(
                    {"jsonrpc":"2.0","id":msg["id"],"error":{"code":-32000,"message":"central fence denied"}}))
                await self.process.stdin.drain()
            except Exception:pass
        finally:current_effect_context.reset(token)


class MCPProviderSession:
    def __init__(self,client,*,configuration,store,content,interactions=None):
        self.client,self.config,self.store,self.content=client,configuration,store,content
        self.tools={};self.catalog_generation=0
        self.local_id=configuration["provider_id"]
        self.config_digest=digest(configuration)
        self._input_pending={}
        self.interactions=interactions

    def _capability(self,name):
        return "mcp:tool:"+name

    def _configured(self,field,key):
        if key not in self.config.get(field,[]):
            raise EffectRejected("MCP resource outside host allowlist")

    async def list(self,request,method,key):
        cursor=request.arguments.get("cursor")
        params={} if cursor is None else {"cursor":cursor}
        result=await self.client._call(method,params,30)
        rows=result.get(key)
        if not isinstance(rows,list) or len(rows)>256:
            raise ValueError("MCP list exceeds bound or lacks items")
        if method=="tools/list":
            tools={}
            for tool in rows:
                if not isinstance(tool,Mapping) or not isinstance(tool.get("inputSchema"),Mapping):
                    raise ValueError("invalid MCP tool schema")
                name=identifier(tool.get("name"))
                if name in tools:raise ValueError("duplicate MCP tool identity")
                tools[name]={**dict(tool),"fingerprint":digest(tool)}
            if cursor is None:self.tools.clear()
            self.tools.update(tools)
            selected=[]
            for name,tool in tools.items():
                if name not in self.config.get("tools",[]):continue
                probe=type(request)(request.operation_id,request.principal_id,request.machine_id,
                                    self._capability(name),request.work_item_id,request.idempotency_key,{})
                if (await self.client.gate.decision(probe)).allowed:
                    selected.append({**tool,"capability_id":self._capability(name)})
            rows=selected
        else:
            field="resources" if key=="resources" else "prompts" if key=="prompts" else "resource_templates"
            selector="uri" if key=="resources" else "name" if key=="prompts" else "uriTemplate"
            rows=[dict(r) for r in rows if isinstance(r,Mapping) and r.get(selector) in self.config.get(field,[])]
        next_cursor=result.get("nextCursor")
        if next_cursor is not None and (not isinstance(next_cursor,str) or len(next_cursor)>4096):
            raise ValueError("invalid MCP list cursor")
        return {"items":rows,"next_cursor":next_cursor,"generation":self.catalog_generation}

    async def notifications(self,request):
        rows=[]
        while len(rows)<request.arguments.get("limit",100):
            try:packet=self.client.notifications.get_nowait()
            except asyncio.QueueEmpty:break
            if packet["method"] in {"notifications/tools/list_changed","notifications/resources/list_changed",
                                    "notifications/prompts/list_changed"}:
                self.tools.clear();self.catalog_generation+=1
            # Notifications never launch tools or refresh automatically.
            rows.append(packet)
            binding=self.store.get(request,self.local_id,self.config_digest)
            if binding is not None:
                self.store.ingest(request,self.local_id,event_id=digest({"op":request.operation_id,
                    "index":len(rows),"packet":packet}),payload=packet)
        return {"items":rows,"catalog_generation":self.catalog_generation}

    async def handle(self,request):
        args=request.arguments;cap=request.capability_id
        if not self.client._initialized:
            raise EffectRejected("MCP protocol must be negotiated before session operations")
        if cap=="mcp:list":return await self.list(request,"tools/list","tools")
        if cap=="mcp:resources_list":return await self.list(request,"resources/list","resources")
        if cap=="mcp:templates_list":return await self.list(request,"resources/templates/list","resourceTemplates")
        if cap=="mcp:prompts_list":return await self.list(request,"prompts/list","prompts")
        if cap=="mcp:notifications":return await self.notifications(request)
        if cap=="mcp:resource_read":
            self._configured("resources",args["uri"])
            result=await self.client._call("resources/read",{"uri":args["uri"]},30)
            for item in result.get("contents",[]):
                if item.get("uri")!=args["uri"]:raise ValueError("MCP resource changed destination")
            return result
        if cap=="mcp:prompt_read":
            self._configured("prompts",args["name"])
            return await self.client._call("prompts/get",{"name":args["name"],
                "arguments":self.content.resolve_value(request,"arguments_sha256")},30)
        if cap in {"mcp:subscribe","mcp:unsubscribe"}:
            if self.client.protocol_version=="2026-07-28":
                raise EffectRejected("modern MCP uses subscriptions/listen")
            self._configured("resources",args["uri"])
            if self.client.server_capabilities.get("resources",{}).get("subscribe") is not True:
                raise EffectRejected("MCP server does not advertise subscriptions")
            return await self.client._call("resources/subscribe" if cap=="mcp:subscribe" else "resources/unsubscribe",
                                           {"uri":args["uri"]},30)
        if cap in {"mcp:listen","mcp:unlisten"}:
            if self.client.protocol_version!="2026-07-28" or not isinstance(self.client,MCPSDKProcessClient):
                raise EffectRejected("modern MCP subscription requires configured official SDK")
            filters=args.get("filter",{})
            for uri in filters.get("resourceSubscriptions",[]):self._configured("resources",uri)
            return await self.client._call("sentra/listen" if cap=="mcp:listen" else "sentra/unlisten",filters,30)
        if cap.startswith("mcp:tool:"):
            name=cap[len("mcp:tool:"):]
            self._configured("tools",name)
            # list_changed makes every old schema unusable; rediscovery is a
            # separate authorized read, never an implicit effect retry.
            await self.notifications(request)
            tool=self.tools.get(name)
            if tool is None or tool["fingerprint"]!=args["schema_sha256"]:
                raise EffectRejected("MCP tool schema stale; rediscover")
            protected=self.content.resolve_value(request,"payload_sha256")
            values=protected.get("arguments") if isinstance(protected,dict) else None
            from sentra_runtime.provider_content import text_digest
            if text_digest(values)!=args["arguments_sha256"]:raise EffectRejected("MCP argument digest mismatch")
            if not isinstance(values,dict):raise EffectRejected("MCP tool arguments must be an object")
            from jsonschema import Draft202012Validator
            Draft202012Validator(tool["inputSchema"]).validate(values)
            params={"name":name,"arguments":values}
            if args.get("input_operation_id"):
                if self.client.protocol_version!="2026-07-28":raise EffectRejected("MCP input continuation is revision gated")
                pending=self._input_pending.get(args["input_operation_id"])
                if pending is None:
                    pending=self.store.event(request,self.local_id,args["input_operation_id"])
                    if pending.get("kind")!="input_required":raise EffectRejected("MCP original operation did not require input")
                if pending is None or pending["name"]!=name or pending["arguments_sha256"]!=args["arguments_sha256"]:
                    raise EffectRejected("MCP interactive call not attached to original input request")
                responses=protected.get("input_responses")
                if not isinstance(responses,dict):raise EffectRejected("MCP input response must be an object")
                if set(responses)-set(pending["input_requests"]):raise EffectRejected("MCP response for an unknown input request")
                for key,answer in responses.items():
                    spec=pending["input_requests"][key]
                    if not isinstance(spec,dict) or spec.get("method")!="elicitation/create":
                        raise EffectRejected("MCP sampling/roots input cannot be fulfilled")
                    params_spec=spec.get("params",{})
                    if params_spec.get("mode","form")!="form" or not isinstance(answer,dict) or answer.get("action") not in {"accept","decline","cancel"}:
                        raise EffectRejected("MCP input answer is not a supported form decision")
                    if answer["action"]=="accept":
                        Draft202012Validator(params_spec["requestedSchema"]).validate(answer.get("content"))
                params.update(inputResponses=responses,requestState=pending["request_state"])
                if self.interactions is None:raise EffectRejected("MCP owner input service not configured")
                self.interactions.consume_embedded(request,args["input_operation_id"],responses)
                # The old continuation is consumed before I/O; a lost response
                # can only be reconciled using the new central Operation.
                self.store.claim_input(request,self.local_id,args["input_operation_id"])
                self._input_pending.pop(args["input_operation_id"],None)
            result=await self.client._call("tools/call",params,120)
            if result.get("resultType")=="input_required":
                if self.client.protocol_version!="2026-07-28":raise ValueError("unexpected MCP input_required on legacy revision")
                self._input_pending[request.operation_id]={"name":name,"arguments_sha256":args["arguments_sha256"],
                    "request_state":result.get("requestState"),"input_requests":copy.deepcopy(result.get("inputRequests",{}))}
                self.store.ingest(request,self.local_id,event_id=request.operation_id,payload={
                    "kind":"input_required","operation_id":request.operation_id,**self._input_pending[request.operation_id]})
                if self.interactions is None:raise EffectRejected("MCP owner input service not configured")
                interactions=self.interactions.register_embedded(request,result.get("inputRequests",{}))
                return {"status":"input_required","operation_id":request.operation_id,
                        "input_requests":result.get("inputRequests",{}),"interaction_ids":interactions,"automatic_retry":False}
            if result.get("isError") is True:
                return OperationResult(request.operation_id,"FAILED",{"payload":result},"MCP tool returned isError")
            if tool.get("outputSchema") and "structuredContent" in result:
                Draft202012Validator(tool["outputSchema"]).validate(result["structuredContent"])
            return result
        raise EffectRejected("unknown MCP session capability")

    async def close(self):
        await self.client.close()
