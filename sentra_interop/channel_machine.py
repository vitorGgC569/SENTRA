"""MachineHost-compatible channel effects; webhooks remain ingress only."""
import json

from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Machine,Capability,OperationRequest
from sentra_runtime.executor import AuthorizationRequired
from sentra_runtime.machine_budget import BudgetedMachinePolicy
from sentra_runtime.provider_content import ProviderContentStore,text_digest
from .central import CentralInteropAdapter,is_interop_observation
from .channels import ChannelService,CHANNEL_CAPABILITIES
from .provider_store import identifier


class ChannelProviderMachine:
    def __init__(self,control,*,owner,agent_id,machine_id,workspace_root,configuration):
        self.control,self.owner,self.agent_id,self.machine_id=control,owner,agent_id,machine_id
        self.channels=ChannelService(control,owner=owner)
        self.connector_id=identifier(configuration.get("connector_id"))
        config=self.channels.configuration(self.connector_id)
        if config["agent_id"]!=agent_id:raise AuthorizationRequired("channel configured for another agent")
        self.configuration=config
        self.project_id=config["project_id"]
        self.capabilities=CHANNEL_CAPABILITIES
        self.actions={cap:[cap.split(":")[1]] for cap in self.capabilities}
        self.content=ProviderContentStore(control.store,owner)
        self.policy=BudgetedMachinePolicy(BoundWorkItemPolicy(owner=owner,principal_type="agent",
            authorization=control.authorization,governance=control.governance),control=control,owner=owner,
            observation_predicate=lambda request:is_interop_observation(request,"channels"))
        self._bindings={}

    def catalog(self):
        return {"kind":"channels","connector_id":self.connector_id,"provider_id":self.configuration["kind"],
            "project_id":self.project_id,"capabilities":list(self.capabilities),"actions":dict(self.actions),
            "registered":True,"grant_created":False,"chat_trust_inherited":False,"validation_status":"pending"}

    def dispatch_request(self,*,run_id,work_item_id,machine_id,capability_id,operation_id,arguments,idempotency_key=None):
        if machine_id!=self.machine_id or capability_id not in self.capabilities or not isinstance(arguments,dict):
            raise AuthorizationRequired("unknown channel machine capability")
        item=self.control.work_item_info(work_item_id,self.owner)
        if item["run_id"]!=run_id or item.get("metadata",{}).get("workspace_id")!=self.project_id:
            raise AuthorizationRequired("channel WorkItem belongs to another project")
        args=json.loads(json.dumps(arguments,allow_nan=False));message=None
        if capability_id=="channel:send":
            if set(args)!={"recipient","message"}:raise ValueError("channel send requires recipient and message")
            message=args.pop("message");identifier(args["recipient"])
            if not isinstance(message,str) or not 0<len(message.encode())<=16000:raise ValueError("invalid channel message")
            args["text_sha256"]=text_digest(message)
        elif capability_id=="channel:receipt":
            if set(args)!={"operation_id"}:raise ValueError("channel receipt requires original operation_id")
            identifier(args["operation_id"])
        elif capability_id=="channel:inbox":
            args.setdefault("limit",100)
            if set(args)!={"limit"} or type(args["limit"]) is not int or not 1<=args["limit"]<=100:raise ValueError("invalid inbox page")
        elif args:raise ValueError("channel lifecycle has no renderer-supplied parameters")
        args["connector_id"]=self.connector_id
        request=OperationRequest(operation_id,self.agent_id,machine_id,capability_id,work_item_id,idempotency_key or operation_id,args)
        if self.policy(request).allowed is not True:raise AuthorizationRequired("channel task/grant unavailable")
        if message is not None:self.content.prepare(request,message)
        return request

    def _bind(self,run_id):
        if run_id in self._bindings:return self._bindings[run_id]
        central=CentralInteropAdapter(control=self.control,owner=self.owner,run_id=run_id,
            machine=Machine(self.machine_id,"channels",self.owner,tuple(Capability(cap,cap,"high") for cap in self.capabilities)))
        async def handler(request):
            if request.principal_id!=self.agent_id:raise AuthorizationRequired("channel agent mismatch")
            if request.capability_id=="channel:send":
                return await self.channels.send(request,connector_id=self.connector_id,recipient=request.arguments["recipient"],
                                                text=self.content.resolve(request))
            if request.capability_id=="channel:receipt":
                return self.channels.receipt(request,connector_id=self.connector_id,operation_id=request.arguments["operation_id"])
            if request.capability_id=="channel:inbox":
                return {"items":self.channels.pending_inbound(connector_id=self.connector_id,project_id=self.project_id,
                                                              limit=request.arguments["limit"])}
            return await self.channels.lifecycle(request,connector_id=self.connector_id,action=request.capability_id.split(":")[1])
        for cap in self.capabilities:central.bind_provider(cap,handler)
        self._bindings[run_id]=central
        return central

    async def submit(self,*,run_id,request):
        if self.control.durable.run_status(run_id,self.owner,include_details=False)["state"]!="RUNNING":
            raise AuthorizationRequired("channel run not active")
        return await self._bind(run_id).start(request)

    async def shutdown(self):
        await self.channels.close()
