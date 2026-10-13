"""Configured ACP/A2A/MCP machines for the existing SENTRA MachineHost.

Only the host supplies configuration, owner, workspace and agent. Requests are
mapped to immutable intents and protected payloads before central submission.
This factory issues no WorkItems or Grants and never implicitly starts agents.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Capability,Machine,OperationRequest
from sentra_runtime.executor import AuthorizationRequired
from sentra_runtime.machine_budget import BudgetedMachinePolicy
from sentra_runtime.provider_content import ProviderContentStore,text_digest
from .central import CentralInteropAdapter,is_interop_observation
from .host_scope import HostScopedInteropGate
from .gate import EffectRejected
from .interactions import ProtocolInteractionService
from .provider_store import ProviderProjectionStore,digest,identifier


INTEROP_CAPABILITIES={
    "acp":("acp:launch","acp:session","acp:resume","acp:load","acp:list","acp:close","acp:delete",
           "acp:config","acp:mode","acp:prompt","acp:cancel","acp:events","acp:state"),
    "a2a":("a2a:discover","a2a:send","a2a:continue","a2a:get","a2a:subscribe","a2a:cancel",
           "a2a:events","a2a:artifact","a2a:callback","a2a:push_set","a2a:push_delete","a2a:extended_card"),
    "mcp":("mcp:launch","mcp:connect","mcp:list","mcp:resources_list","mcp:templates_list",
           "mcp:resource_read","mcp:prompts_list","mcp:prompt_read","mcp:subscribe","mcp:unsubscribe",
           "mcp:listen","mcp:unlisten","mcp:notifications","mcp:close")}


class InteropProviderMachine:
    def __init__(self,control,*,owner,agent_id,machine_id,workspace_root,kind,configuration):
        if kind not in INTEROP_CAPABILITIES or not isinstance(configuration,dict) or configuration.get("enabled") is not True:
            raise ValueError("explicit enabled interop provider configuration required")
        self.control,self.owner,self.agent_id,self.machine_id,self.kind=control,owner,agent_id,machine_id,kind
        self.workspace=Path(workspace_root).resolve(strict=True)
        if not self.workspace.is_dir():raise ValueError("interop workspace is not a directory")
        self.configuration=json.loads(json.dumps(configuration,allow_nan=False))
        config=self.configuration
        self.provider_id=identifier(config.get("provider_id"))
        self._bindings={};self._sessions={};self._launching=set()
        self.content=ProviderContentStore(control.store,owner)
        self.projections=ProviderProjectionStore(control.store,owner)
        self.interactions=ProtocolInteractionService(control,owner=owner)
        self.policy=BudgetedMachinePolicy(BoundWorkItemPolicy(owner=owner,principal_type="agent",
            authorization=control.authorization,governance=control.governance),control=control,owner=owner,
            observation_predicate=lambda request:is_interop_observation(request,kind))
        self.capabilities=INTEROP_CAPABILITIES[kind]
        if kind=="acp":self.capabilities+=("acp:transport_close",)
        if kind in {"acp","mcp"}:
            from .registry_install import validate_agent_env,is_reserved_agent_env_name,ENV_NAME
            environment=config.get("environment",{})
            if not isinstance(environment,dict) or set(environment)-{"values","secret_refs"}:
                raise ValueError("interop environment requires explicit host values/secret_refs")
            values=dict(validate_agent_env(environment.get("values",{})))
            refs=environment.get("secret_refs",{})
            if not isinstance(refs,dict) or len(refs)>64 or set(values)&set(refs):raise ValueError("ambiguous interop environment")
            for name,ref in refs.items():
                if not ENV_NAME.fullmatch(name) or is_reserved_agent_env_name(name):raise ValueError("reserved interop environment name")
                control.secret_info(ref,owner)
                control.bind_secret(ref,owner,target_type="agent",target_id=agent_id,purpose="interop-env:"+machine_id+":"+name)
            config["environment"]={"values":values,"secret_refs":dict(refs)}
            executable=Path(config.get("executable","")).resolve(strict=True)
            checksum=config.get("executable_sha256")
            if (not executable.is_file() or not isinstance(checksum,str) or not re.fullmatch(r"[a-f0-9]{64}",checksum)
                    or config.get("host_process_consent") is not True):
                raise ValueError("interop process requires approved absolute executable pin and explicit local-process consent")
            args=config.get("args",[])
            if not isinstance(args,list) or len(args)>64 or any(not isinstance(x,str) or "\0" in x for x in args):
                raise ValueError("invalid configured interop argv")
            with executable.open("rb") as source:
                if hashlib.file_digest(source,"sha256").hexdigest()!=checksum:
                    raise ValueError("configured interop executable digest differs")
            config["executable"]=str(executable)
            config["args"]=list(args)
            pins=config.get("argument_file_pins",{})
            if not isinstance(pins,dict) or len(pins)>64:raise ValueError("invalid configured argument file pins")
            for path,sha in pins.items():
                target=Path(path)
                if not target.is_absolute() or not target.is_file() or not isinstance(sha,str) or not re.fullmatch(r"[a-f0-9]{64}",sha):
                    raise ValueError("argument files require absolute content pins")
                with target.open("rb") as source:
                    if hashlib.file_digest(source,"sha256").hexdigest()!=sha:raise ValueError("configured argument file pin differs")
            config["argument_file_pins"]=pins
            if kind=="acp":
                versions=config.get("supported_versions",[1])
                if not isinstance(versions,list) or not versions or any(type(v) is not int or v not in (1,2) for v in versions):
                    raise ValueError("ACP revision must be explicitly supported")
                config["supported_versions"]=versions
            else:
                if config.get("transport","stdio") not in {"stdio","sdk_http"}:raise ValueError("unsupported MCP transport")
                version=config.get("protocol_version","2025-06-18")
                if version not in {"2025-06-18","2025-11-25","2026-07-28"}:raise ValueError("unsupported MCP revision")
                if version=="2026-07-28" and config.get("transport")!="sdk_http":
                    raise ValueError("modern MCP requires official TypeScript SDK host")
                config["protocol_version"]=version
                if config.get("transport")=="sdk_http":
                    from .a2a_provider import approved_url
                    approved_url(config.get("endpoint",""))
                    host=Path(__file__).parent/"sdk"/"mcp_host.mjs"
                    if config["args"]!=[str(host.resolve())]:
                        raise ValueError("MCP SDK process must launch SENTRA pinned SDK host")
                    with host.open("rb") as source:config["argument_file_pins"][str(host.resolve())]=hashlib.file_digest(source,"sha256").hexdigest()
                for field in ("tools","resources","prompts","resource_templates"):
                    values=config.get(field,[])
                    if not isinstance(values,list) or len(values)>256 or len(set(values))!=len(values):
                        raise ValueError("explicit MCP provider resource allowlists required")
                    for value in values:identifier(value)
                if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",name) for name in config.get("tools",[])):
                    raise ValueError("MCP tool name cannot form an ambiguous capability")
                self.capabilities+=tuple("mcp:tool:"+name for name in sorted(config.get("tools",[])))
        else:
            from .a2a_provider import A2AProviderConfig
            allowed={"endpoint","provider_id","trust_domain","card_sha256","enabled","card_url","timeout","tenant","callback_url"}
            self.a2a_config=A2AProviderConfig(**{k:v for k,v in config.items() if k in allowed})
        # The configuration persisted by MachineHost contains only references,
        # never plaintext secrets. The governance vault resolves every use.
        if any(key in config for key in {"token","password","api_key","credential","callback_token","env"}):
            raise ValueError("interop configuration accepts vault references only")
        for key in ("secret_ref","callback_secret_ref"):
            if config.get(key):
                control.secret_info(config[key],owner)
                control.bind_secret(config[key],owner,target_type="agent",target_id=agent_id,
                                    purpose="interop:"+machine_id+":"+key)
        self.actions={cap:[cap.split(":",1)[1]] for cap in self.capabilities}
        if kind=="a2a":
            from .a2a_push import A2APushIngress
            self.push_ingress=A2APushIngress(control,owner=owner,machine_id=machine_id,
                config=self.a2a_config,credential=self.credential("callback_secret_ref"))

    def receive_callback(self,*,raw_body,headers):
        if self.kind!="a2a":raise ValueError("only configured A2A machines have push ingress")
        return self.push_ingress.receive(raw_body=raw_body,headers=headers)

    def catalog(self):
        return {"kind":self.kind,"provider_id":self.provider_id,"capabilities":list(self.capabilities),
                "actions":dict(self.actions),"registered":True,"grant_created":False,
                "protocol":self.configuration.get("protocol_version",self.configuration.get("supported_versions","a2a-pinned")),
                "isolation":"configured_local_process" if self.kind in {"acp","mcp"} else "external_peer",
                "transport_ready":"unverified","validation_status":"pending"}

    def credential(self,key="secret_ref"):
        ref=self.configuration.get(key)
        if not ref:return None
        return lambda:self.control.governance.resolve_secret_for_runtime(ref,self.owner,
            actor_type="agent",actor_id=self.agent_id,purpose="interop:"+self.machine_id+":"+key)

    def environment(self):
        configured=self.configuration.get("environment",{})
        values=dict(configured.get("values",{}))
        for name,ref in configured.get("secret_refs",{}).items():
            values[name]=self.control.governance.resolve_secret_for_runtime(ref,self.owner,actor_type="agent",actor_id=self.agent_id,
                purpose="interop-env:"+self.machine_id+":"+name)
        from .registry_install import validate_agent_env
        return dict(validate_agent_env(values))

    def dispatch_request(self,*,run_id,work_item_id,machine_id,capability_id,operation_id,arguments,idempotency_key=None):
        if machine_id!=self.machine_id or capability_id not in self.capabilities or not isinstance(arguments,dict):
            raise AuthorizationRequired("interop machine/capability mismatch")
        probe=OperationRequest(operation_id,self.agent_id,machine_id,capability_id,work_item_id,idempotency_key or operation_id,{})
        item=self.control.work_item_info(work_item_id,self.owner)
        if item["run_id"]!=run_id or self.policy(probe).allowed is not True:
            raise AuthorizationRequired("interop WorkItem/grant unavailable")
        args=json.loads(json.dumps(arguments,allow_nan=False));protected=None
        cap=capability_id;config=self.configuration
        if set(args)&{"owner","principal","principal_id","grant","cwd","executable","args","endpoint","token","server_id"}:
            raise AuthorizationRequired("interop destination, identity and process belong to host configuration")
        if cap.startswith("acp:"):
            local=identifier(args.get("local_id"))
            if cap=="acp:launch":
                self._keys(args,{"local_id"})
                args.update(executable=config["executable"],args=config["args"],cwd=str(self.workspace),
                            executable_sha256=config["executable_sha256"],argument_file_pins=config["argument_file_pins"])
                protected=self.environment();args["environment_sha256"]=text_digest(protected)
            elif cap=="acp:prompt":
                self._keys(args,{"local_id","message"})
                protected=args.pop("message");self._text(protected);args["text_sha256"]=text_digest(protected)
            elif cap=="acp:config":
                self._keys(args,{"local_id","config_id","value"})
                identifier(args["config_id"]);protected=args.pop("value");args["value_sha256"]=text_digest(protected)
            elif cap=="acp:events":self._page(args,{"local_id"})
            elif cap=="acp:list":
                args.setdefault("cursor",None);self._keys(args,{"local_id","cursor"})
            elif cap=="acp:mode":self._keys(args,{"local_id","mode_id"});identifier(args["mode_id"])
            else:self._keys(args,{"local_id"})
        elif cap.startswith("a2a:"):
            if cap in {"a2a:discover","a2a:extended_card"}:self._keys(args,set())
            else:
                identifier(args.get("local_id"))
                if cap in {"a2a:send","a2a:continue"}:
                    self._keys(args,{"local_id","message"});protected=args.pop("message");self._text(protected)
                    args["text_sha256"]=text_digest(protected)
                    args["message_id"]=self.content.resource_id(machine_id=machine_id,work_item_id=work_item_id,
                                                               local_id="message:"+operation_id)
                elif cap=="a2a:events":self._page(args,{"local_id"})
                elif cap=="a2a:artifact":self._keys(args,{"local_id","artifact_id"});identifier(args["artifact_id"])
                elif cap in {"a2a:push_set","a2a:push_delete"}:
                    self._keys(args,{"local_id","config_id"});identifier(args["config_id"])
                elif cap=="a2a:subscribe":
                    args.setdefault("limit",100);self._keys(args,{"local_id","limit"});self._limit(args["limit"])
                elif cap=="a2a:callback":
                    self._keys(args,{"local_id","event_id"});identifier(args["event_id"])
                else:self._keys(args,{"local_id"})
        else:
            if cap=="mcp:launch":
                self._keys(args,set());args={"server_id":self.provider_id,"executable":config["executable"],
                    "args":config["args"],"cwd":str(self.workspace),"executable_sha256":config["executable_sha256"],
                    "argument_file_pins":config["argument_file_pins"]}
                protected=self.environment();args["environment_sha256"]=text_digest(protected)
            elif cap in {"mcp:connect","mcp:close","mcp:unlisten"}:self._keys(args,set())
            elif cap in {"mcp:list","mcp:resources_list","mcp:templates_list","mcp:prompts_list"}:
                args.setdefault("cursor",None);self._keys(args,{"cursor"})
            elif cap=="mcp:notifications":
                args.setdefault("limit",100);self._keys(args,{"limit"});self._limit(args["limit"])
            elif cap in {"mcp:resource_read","mcp:subscribe","mcp:unsubscribe"}:self._keys(args,{"uri"});identifier(args["uri"])
            elif cap=="mcp:listen":
                self._keys(args,{"filter"})
                if not isinstance(args["filter"],dict) or set(args["filter"])-{
                    "toolsListChanged","promptsListChanged","resourcesListChanged","resourceSubscriptions"}:
                    raise ValueError("invalid MCP subscription filter")
            elif cap=="mcp:prompt_read":
                args.setdefault("arguments",{});self._keys(args,{"name","arguments"})
                protected=args.pop("arguments");args["arguments_sha256"]=text_digest(protected)
            elif cap.startswith("mcp:tool:"):
                allowed={"arguments","schema_sha256"}
                if "input_operation_id" in args:allowed|={"input_operation_id","input_responses"}
                self._keys(args,allowed)
                protected={"arguments":args.pop("arguments")}
                args["arguments_sha256"]=text_digest(protected["arguments"])
                if "input_operation_id" in args:protected["input_responses"]=args.pop("input_responses")
                args["payload_sha256"]=text_digest(protected)
            else:raise ValueError("unknown MCP action")
        request=OperationRequest(operation_id,self.agent_id,machine_id,cap,work_item_id,idempotency_key or operation_id,args)
        if self.policy(request).allowed is not True:raise AuthorizationRequired("interop canonical intent denied")
        if protected is not None:self.content.prepare_value(request,protected)
        return request

    @staticmethod
    def _keys(args,allowed):
        if set(args)!=allowed:raise ValueError("interop action arguments do not match contract")
    @staticmethod
    def _text(value):
        if not isinstance(value,str) or not value.strip() or len(value.encode())>32768:raise ValueError("invalid provider message")
    @staticmethod
    def _limit(value):
        if type(value) is not int or not 1<=value<=100:raise ValueError("invalid protocol page size")
    def _page(self,args,required):
        args.setdefault("after",-1);args.setdefault("limit",100);self._keys(args,required|{"after","limit"})
        self._limit(args["limit"])
        if type(args["after"]) is not int or args["after"]<-1:raise ValueError("invalid protocol cursor")

    def _bind(self,run_id):
        if run_id in self._bindings:return self._bindings[run_id]
        machine=Machine(self.machine_id,self.kind,self.owner,tuple(Capability(cap,cap,"high") for cap in self.capabilities))
        central=CentralInteropAdapter(control=self.control,run_id=run_id,owner=self.owner,machine=machine)
        constraints={}
        if self.kind in {"acp","mcp"}:
            config=self.configuration
            constraints[self.kind+":launch"]={"executable_paths":[config["executable"]],"cwd_roots":[str(self.workspace)],
                "argv_sha256":hashlib.sha256(json.dumps(config["args"],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()}
        gate=HostScopedInteropGate(central.protocol_gate(constraints=constraints))
        async def handler(request):
            if request.principal_id!=self.agent_id:raise AuthorizationRequired("interop agent mismatch")
            return await self._handle(request,gate)
        for cap in self.capabilities:central.bind_provider(cap,handler,constraints=constraints.get(cap))
        self._bindings[run_id]=central
        return central

    async def _handle(self,request,gate):
        key=(request.work_item_id,request.arguments.get("local_id",self.provider_id))
        cap=request.capability_id;session=self._sessions.get(key)
        if self.kind=="acp" and cap in {"acp:events","acp:state"} and session is None:
            binding=self.projections.get(request,key[1],digest(self.configuration))
            if binding is None:raise EffectRejected("ACP association not found")
            if cap=="acp:events":return self.projections.events(request,key[1],after=request.arguments["after"],limit=request.arguments["limit"])
            return {"session_id":binding["remote_id"],"state":binding["state"],"attached":False,
                    "usage":None,"usage_known":False,"next_action":"explicit launch and resume existing session"}
        if self.kind=="a2a":
            from .a2a_provider import A2AProvider,A2AHTTPTransport
            if session is None:
                session=A2AProvider(self.a2a_config,self.projections,A2AHTTPTransport(self.a2a_config,self.credential()),
                                    self.content,self.credential("callback_secret_ref"),self.push_ingress)
                self._sessions[key]=session
            return await session.handle(request)
        if cap in {"acp:launch","mcp:launch"}:
            if session is not None or key in self._launching:raise EffectRejected("interop process already owned; do not relaunch")
            self._launching.add(key)
            try:
                config=self.configuration
                if self.kind=="acp":
                    from .acp import ACPStdioTransport
                    from .acp_provider import ACPProviderSession
                    transport=await ACPStdioTransport.launch(config["executable"],tuple(config["args"]),
                        cwd=str(self.workspace),gate=gate,request=request,
                        env=self.content.resolve_value(request,"environment_sha256"))
                    session=ACPProviderSession(transport,gate,configuration=config,workspace=str(self.workspace),
                        store=self.projections,content=self.content,local_id=key[1])
                    if config.get("elicitation") is True:session.adapter.client_capabilities={"elicitation":{"form":{}}}
                else:
                    from .mcp_stdio import MCPStdioClient
                    from .mcp_session import MCPSDKProcessClient,MCPProviderSession
                    client_type=MCPSDKProcessClient if config.get("transport")=="sdk_http" else MCPStdioClient
                    transport=await client_type.launch(executable=config["executable"],argv=tuple(config["args"]),
                        cwd=str(self.workspace),server_id=self.provider_id,gate=gate,request=request,
                        env=self.content.resolve_value(request,"environment_sha256"))
                    session=MCPProviderSession(transport,configuration=config,store=self.projections,content=self.content,interactions=self.interactions)
                async def reverse_request(packet,original):
                    if packet.get("method")=="elicitation/create" and config.get("elicitation") is not True:
                        raise EffectRejected("protocol elicitation was not enabled")
                    if self.kind=="acp":
                        if packet.get("params",{}).get("sessionId")!=session.binding(original)["remote_id"]:
                            raise EffectRejected("ACP interaction belongs to another session")
                    return await self.interactions.ask(packet,original,self.policy)
                transport.request_handler=reverse_request
                self._sessions[key]=session
                return {"provider_id":self.provider_id,"local_id":key[1],"process_started":True,"session_created":False}
            finally:self._launching.discard(key)
        if session is None:raise EffectRejected("interop process is not running; explicitly authorize launch")
        if cap=="acp:transport_close":
            await session.close();self._sessions.pop(key,None)
            binding=self.projections.get(request,key[1],session.config_digest)
            if binding:self.projections.state(request,key[1],"DETACHED")
            return {"transport_closed":True,"remote_session_deleted":False,"effects_rolled_back":False}
        if cap=="mcp:connect":
            binding=self.projections.get(request,self.provider_id,session.config_digest)
            if binding is None:self.projections.prepare(request,self.provider_id,session.config_digest)
            transport=session.client
            session_id=None
            discovery=None
            if binding and self.configuration.get("transport")=="sdk_http":
                try:previous=self.projections.event(request,self.provider_id,"connection")
                except FileNotFoundError:raise EffectRejected("MCP previous connection is uncertain; do not replace its remote session")
                session_id=previous.get("sessionId")
                discovery=previous.get("discovery")
                if session_id and self.configuration["protocol_version"]!="2026-07-28":
                    raise EffectRejected("legacy SDK restart requires provider reconciliation; existing session will not be replaced")
            if self.configuration.get("transport")=="sdk_http":
                credential=self.credential()
                result=await transport.connect_sdk(endpoint=self.configuration["endpoint"],
                    protocol_version=self.configuration["protocol_version"],token=credential() if credential else None,
                    elicitation=self.configuration.get("elicitation") is True,session_id=session_id,discovery=discovery)
            else:
                await transport.initialize(timeout=30,supported_versions=(self.configuration["protocol_version"],),
                                           elicitation=self.configuration.get("elicitation") is True)
                result={"protocolVersion":transport.protocol_version,"capabilities":dict(transport.server_capabilities)}
            self.projections.bind(request,self.provider_id,session.config_digest,self.provider_id)
            if binding is None:self.projections.ingest(request,self.provider_id,event_id="connection",payload=result)
            return result
        if cap=="mcp:close":
            await session.close();self._sessions.pop(key,None)
            return {"closed":True,"remote_effects_rolled_back":False}
        return await session.handle(request)

    async def submit(self,*,run_id,request):
        if self.control.durable.run_status(run_id,self.owner,include_details=False)["state"]!="RUNNING":
            raise AuthorizationRequired("interop Run is not active")
        return await self._bind(run_id).start(request)

    async def shutdown(self):
        for session in list(self._sessions.values()):await session.close()
        self._sessions.clear()
