"""MachineHost ACP registry discovery, plans and staged authorized installs."""
import json
from dataclasses import asdict

from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Capability,Machine,OperationRequest
from sentra_runtime.executor import AuthorizationRequired
from sentra_runtime.machine_budget import BudgetedMachinePolicy
from .central import CentralInteropAdapter,is_interop_observation
from .registry import ACPVersionedCatalog
from .registry_runtime import ACPDistributionInstaller
from .provider_store import identifier,digest
from .gate import EffectRejected

REGISTRY_CAPABILITIES=("acp:catalog","acp:plan","acp:install","acp:installed")


class RegistryProviderMachine:
    def __init__(self,control,*,owner,agent_id,machine_id,workspace_root,configuration):
        if not isinstance(configuration,dict) or configuration.get("enabled") is not True:
            raise ValueError("explicitly enabled registry configuration required")
        self.control,self.owner,self.agent_id,self.machine_id=control,owner,agent_id,machine_id
        self.configuration=json.loads(json.dumps(configuration,allow_nan=False))
        self.provider_id=identifier(configuration.get("provider_id","acp-registry"))
        self.catalog_snapshot=ACPVersionedCatalog.from_index(configuration["catalog"],
            schema_version=configuration["schema_version"],pinned_versions=configuration["pinned_versions"],
            channels=configuration.get("channels"))
        self.installations=self.configuration.get("installations",{})
        if not isinstance(self.installations,dict) or set(self.installations)-set(configuration["pinned_versions"]):
            raise ValueError("registry installation must select pinned catalog providers")
        self.capabilities=REGISTRY_CAPABILITIES
        self.actions={cap:[cap.split(":")[1]] for cap in self.capabilities}
        self.policy=BudgetedMachinePolicy(BoundWorkItemPolicy(owner=owner,principal_type="agent",
            authorization=control.authorization,governance=control.governance),control=control,owner=owner,
            observation_predicate=lambda request:is_interop_observation(request,"acp_registry"))
        self.installer=ACPDistributionInstaller(control=control,owner=owner,
            install_root=str(control.durable.root/"interop-installed"/machine_id))
        self._bindings={}

    def catalog(self):
        return {"kind":"acp_registry","provider_id":self.provider_id,"capabilities":list(self.capabilities),
                "actions":dict(self.actions),"catalog_sha256":self.catalog_snapshot.snapshot_sha256,
                "registered":True,"grant_created":False,"validation_status":"pending"}

    def plan(self,agent_id):
        config=self.installations.get(agent_id)
        if not isinstance(config,dict):raise EffectRejected("selected registry distribution is not configured for installation")
        entry=self.catalog_snapshot.select(agent_id,version=self.configuration["pinned_versions"][agent_id])
        plan=entry.installation_plan(system=config["system"],architecture=config["architecture"],kind=config["kind"])
        if config.get("expected_plan_sha256") and config["expected_plan_sha256"]!=plan.fingerprint:
            raise EffectRejected("registry installation plan revision changed")
        return plan,config

    def dispatch_request(self,*,run_id,work_item_id,machine_id,capability_id,operation_id,arguments,idempotency_key=None):
        if machine_id!=self.machine_id or capability_id not in self.capabilities or not isinstance(arguments,dict):
            raise AuthorizationRequired("registry machine capability mismatch")
        item=self.control.work_item_info(work_item_id,self.owner)
        if item["run_id"]!=run_id:raise AuthorizationRequired("registry WorkItem Run mismatch")
        args=json.loads(json.dumps(arguments,allow_nan=False))
        if capability_id=="acp:catalog":
            args.setdefault("offset",0);args.setdefault("limit",100)
            if set(args)!={"offset","limit"} or type(args["offset"]) is not int or args["offset"]<0 or type(args["limit"]) is not int or not 1<=args["limit"]<=100:
                raise ValueError("invalid registry catalog page")
        else:
            if set(args)!={"agent_id"}:raise ValueError("registry action accepts only pinned agent_id")
            identifier(args["agent_id"])
            plan,config=self.plan(args["agent_id"])
            if capability_id=="acp:install":
                args=self.installer.request_arguments(plan,executable_sha256=config["executable_sha256"],
                    lock_sha256=digest(config["lock_text"]) if config.get("lock_text") is not None else None,
                    runner_sha256=config.get("runner",{}).get("sha256"))
        request=OperationRequest(operation_id,self.agent_id,machine_id,capability_id,work_item_id,idempotency_key or operation_id,args)
        if self.policy(request).allowed is not True:raise AuthorizationRequired("registry grant denied")
        return request

    def _bind(self,run_id):
        if run_id in self._bindings:return self._bindings[run_id]
        central=CentralInteropAdapter(control=self.control,owner=self.owner,run_id=run_id,machine=Machine(
            self.machine_id,"acp_registry",self.owner,tuple(Capability(cap,cap,"high") for cap in self.capabilities)))
        async def handler(request):
            if request.principal_id!=self.agent_id:raise AuthorizationRequired("registry principal mismatch")
            args=request.arguments
            if request.capability_id=="acp:catalog":
                rows=self.catalog_snapshot.entries;offset=args["offset"];limit=args["limit"]
                return {"items":[asdict(e) for e in rows[offset:offset+limit]],"next_offset":offset+limit if offset+limit<len(rows) else None,
                        "snapshot_sha256":self.catalog_snapshot.snapshot_sha256,"launch_authorized":False}
            plan,config=self.plan(args["agent_id"])
            if request.capability_id=="acp:plan":
                return {"plan":asdict(plan),"plan_sha256":plan.fingerprint,"launch_authorized":False}
            if request.capability_id=="acp:installed":
                return self.installer.reconcile(plan=plan,executable_sha256=config["executable_sha256"])
            return await self.installer.install(request,plan=plan,**{k:config[k] for k in (
                "executable_sha256","lock_text","runner","entrypoint","archive_sha256") if k in config})
        for cap in self.capabilities:central.bind_provider(cap,handler)
        self._bindings[run_id]=central
        return central

    async def submit(self,*,run_id,request):
        if self.control.durable.run_status(run_id,self.owner,include_details=False)["state"]!="RUNNING":
            raise AuthorizationRequired("registry Run not active")
        return await self._bind(run_id).start(request)

    async def shutdown(self):
        return None  # Install subprocesses are scoped and collected per operation.
