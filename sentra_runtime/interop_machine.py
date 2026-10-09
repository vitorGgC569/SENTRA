"""Application binding of configured protocol providers to central WorkItems."""
import json
from pathlib import Path

from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Capability,Machine,OperationRequest
from sentra_runtime.executor import AuthorizationRequired
from sentra_interop.central import CentralInteropAdapter
from sentra_interop.host_scope import HostScopedInteropGate
from .provider_content import ProviderContentStore,text_digest

OPENHANDS_CAPABILITIES=("openhands:create","openhands:message","openhands:read","openhands:events",
                       "openhands:evidence","openhands:run","openhands:cancel")


class OpenHandsMachine:
    def __init__(self,control,*,owner,agent_id,machine_id,configuration):
        from sentra_interop.openhands_provider import OpenHandsServerConfig
        self.control,self.owner,self.agent_id,self.machine_id=control,owner,agent_id,machine_id
        config=dict(configuration);self.secret_ref=config.pop("secret_ref",None)
        self.config=OpenHandsServerConfig(**config)
        from .machine_budget import BudgetedMachinePolicy
        from .observations import is_observation
        self.policy=BudgetedMachinePolicy(BoundWorkItemPolicy(owner=owner,principal_type="agent",
            authorization=control.authorization,governance=control.governance),control=control,owner=owner,
            observation_predicate=lambda request:is_observation(request,"openhands"))
        self.content=ProviderContentStore(control.store,owner)
        self._bindings={};self._declarations={}
        if self.secret_ref:
            control.secret_info(self.secret_ref,owner)
            control.bind_secret(self.secret_ref,owner,target_type="agent",target_id=agent_id,purpose="openhands:"+machine_id)

    def dispatch_request(self,*,run_id,work_item_id,machine_id,capability_id,operation_id,arguments,idempotency_key=None):
        if machine_id!=self.machine_id or capability_id not in OPENHANDS_CAPABILITIES or not isinstance(arguments,dict):
            raise AuthorizationRequired("unknown OpenHands machine capability")
        args=json.loads(json.dumps(arguments,allow_nan=False));text=args.pop("message",None)
        probe=OperationRequest(operation_id,self.agent_id,machine_id,capability_id,work_item_id,
                               idempotency_key or operation_id,{})
        if self.policy(probe).allowed is not True:raise AuthorizationRequired("OpenHands task/grant unavailable")
        if text is not None:
            if capability_id not in {"openhands:create","openhands:message"}:raise ValueError("text not accepted by this capability")
            digest_key="initial_message_sha256" if capability_id=="openhands:create" else "text_sha256"
            if digest_key in args and args[digest_key]!=text_digest(text):raise ValueError("provider message digest conflict")
            args[digest_key]=text_digest(text)
        if capability_id=="openhands:create":
            if "conversation_id" in args:raise ValueError("remote identity belongs to the host; use the stable local conversation identity")
            args["conversation_id"]=self.content.resource_id(machine_id=machine_id,work_item_id=work_item_id,local_id=args.get("local_id"))
            args.setdefault("initial_message_sha256",None);args.setdefault("parent_local_id",None)
        if capability_id=="openhands:message":args.setdefault("run",False)
        request=OperationRequest(operation_id,self.agent_id,machine_id,capability_id,work_item_id,
                                 idempotency_key or operation_id,args)
        item=self.control.work_item_info(work_item_id,self.owner)
        if item["run_id"]!=run_id or self.policy(request).allowed is not True:
            raise AuthorizationRequired("OpenHands task/grant unavailable")
        if text is not None:self.content.prepare(request,text)
        return request

    def _bind(self,run_id):
        from sentra_interop.openhands_provider import (OpenHandsHTTPTransport,OpenHandsIdentityStore,
                                                       OpenHandsAgentServerProvider)
        if run_id in self._bindings:return self._bindings[run_id]
        machine=Machine(self.machine_id,"openhands",self.owner,tuple(Capability(cap,cap) for cap in OPENHANDS_CAPABILITIES))
        central=CentralInteropAdapter(control=self.control,run_id=run_id,owner=self.owner,machine=machine)
        gate=HostScopedInteropGate(central.protocol_gate())
        root=self.control.durable.root/"provider-state"/self.machine_id
        root.mkdir(parents=True,exist_ok=True)
        transport=OpenHandsHTTPTransport(self.config)
        identities=OpenHandsIdentityStore(str(root/"openhands.sqlite3"),workspace=str(root))
        provider=OpenHandsAgentServerProvider(gate,config=self.config,identity_store=identities,
            transport=transport,message_resolver=self.content.resolve)
        async def handler(request):
            if request.principal_id!=self.agent_id:raise AuthorizationRequired("OpenHands agent identity mismatch")
            if self.secret_ref:
                transport._key=self.control.governance.resolve_secret_for_runtime(self.secret_ref,self.owner,
                    actor_type="agent",actor_id=self.agent_id,purpose="openhands:"+self.machine_id)
            return await provider.host_handler(request)
        for capability in OPENHANDS_CAPABILITIES:central.bind_provider(capability,handler)
        self._bindings[run_id]=(central,provider)
        return central,provider

    async def submit(self,*,run_id,request):
        if self.control.durable.run_status(run_id,self.owner,include_details=False)["state"]!="RUNNING":
            raise AuthorizationRequired("OpenHands run is not active")
        central,_=self._bind(run_id)
        return await central.start(request)

    async def shutdown(self):
        for _,provider in self._bindings.values():await provider.close()
