"""Configured document workflows bound to the existing central authority."""
import json
from pathlib import Path

from sentra_interop.central import CentralInteropAdapter
from sentra_interop.workflow_contracts import ActivitySpec,WorkflowDefinition,RetryPolicy,ActivityReceipt,digest
from sentra_interop.workflow_worker import WorkflowActivityBinding
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Machine,Capability,OperationRequest
from sentra_runtime.executor import AuthorizationRequired
from .machine_budget import BudgetedMachinePolicy
from .provider_content import ProviderContentStore

WORKER_VERSION="sentra-documents-v1"
WORKFLOW_CAPABILITIES=("workflow:create","workflow:advance","workflow:resume","workflow:signal",
    "workflow:cancel","workflow:observe","workflow:output","workflow:memory","workflow:document")


def parse_definitions(values):
    if not isinstance(values,list) or not 1<=len(values)<=32:raise ValueError("bounded workflow definition catalog required")
    definitions=[]
    for value in values:
        if not isinstance(value,dict) or set(value)-{"definition_id","version","steps"}:raise ValueError("invalid workflow definition")
        steps=[]
        if not isinstance(value.get("steps"),list) or not 1<=len(value["steps"])<=1000:
            raise ValueError("bounded workflow steps required")
        for raw in value["steps"]:
            if not isinstance(raw,dict):raise ValueError("workflow step must be a mapping")
            row=dict(raw)
            if "inputs" in row:
                row["inputs_json"]=json.dumps(row.pop("inputs"),ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(",",":"))
            if "dependencies" in row:row["dependencies"]=tuple(row["dependencies"])
            if "retry" in row:
                retry=dict(row["retry"])
                if "retryable_types" in retry:retry["retryable_types"]=tuple(retry["retryable_types"])
                row["retry"]=RetryPolicy(**retry)
            if row.get("kind","activity")=="activity":
                row.setdefault("handler_id","documents");row.setdefault("handler_version","1")
                if (row["handler_id"],row["handler_version"])!=("documents","1"):
                    raise ValueError("workflow references an unconfigured activity provider")
            steps.append(ActivitySpec(**row))
        definitions.append(WorkflowDefinition(value["definition_id"],value["version"],WORKER_VERSION,tuple(steps)))
    if len({(d.definition_id,d.version) for d in definitions})!=len(definitions):raise ValueError("duplicate workflow definition version")
    catalog={(d.definition_id,d.version):d for d in definitions};visiting=set();visited=set()
    def check(key):
        if key in visiting:raise ValueError("recursive workflow subflow")
        if key in visited:return
        if key not in catalog:raise ValueError("missing pinned subflow definition")
        visiting.add(key)
        for step in catalog[key].steps:
            if step.kind=="subflow":check((step.subflow_id,step.subflow_version))
        visiting.remove(key);visited.add(key)
    for key in catalog:check(key)
    return tuple(definitions)


class DocumentWorkflowMachine:
    def __init__(self,control,*,owner,agent_id,machine_id,workspace_root,definitions):
        self.control,self.owner,self.agent_id,self.machine_id=control,owner,agent_id,machine_id
        self.workspace_root=Path(workspace_root).resolve(strict=True)
        digest(definitions)  # Reuse the bounded canonical value contract before persistence.
        self.definitions=parse_definitions(definitions)
        self._bindings={};self._declarations={}
        self.content=ProviderContentStore(control.store,owner)
        self.policy=BudgetedMachinePolicy(BoundWorkItemPolicy(owner=owner,principal_type="agent",
            authorization=control.authorization,governance=control.governance),control=control,owner=owner,
            observation_predicate=lambda request:request.capability_id in {"workflow:observe","workflow:output"})

    def catalog(self):
        return [{"definition_id":d.definition_id,"version":d.version,"sha256":d.fingerprint,
                 "steps":[{"step_id":s.step_id,"kind":s.kind,"dependencies":list(s.dependencies),
                    "signal_name":s.signal_name,
                    "input_fields":[{"argument":name,"path":value.get("path",[])}
                        for name,value in json.loads(s.inputs_json).items()
                        if isinstance(value,dict) and value.get("source")=="input"]} for s in d.steps]}
                for d in self.definitions]

    def dispatch_request(self,*,run_id,work_item_id,machine_id,capability_id,operation_id,arguments,idempotency_key=None):
        if machine_id!=self.machine_id or capability_id not in WORKFLOW_CAPABILITIES or not isinstance(arguments,dict):
            raise AuthorizationRequired("workflow machine/capability mismatch")
        args=json.loads(json.dumps(arguments,allow_nan=False));payload=None;has_payload=False
        payload_fields={"workflow:create":("inputs","input_sha256"),"workflow:signal":("payload","payload_sha256"),
                        "workflow:memory":("value","value_sha256")}
        if capability_id in payload_fields:
            source,key=payload_fields[capability_id]
            if source in args:
                payload=args.pop(source);has_payload=True
                if key in args and args[key]!=digest(payload):raise ValueError("workflow input digest conflict")
                args[key]=digest(payload)
        if capability_id=="workflow:create":
            if not has_payload:payload={};has_payload=True;args.setdefault("input_sha256",digest(payload))
            definition=next((d for d in self.definitions if (d.definition_id,d.version)==(args.get("definition_id"),args.get("definition_version"))),None)
            if definition is None:raise ValueError("unknown configured workflow definition")
            args.setdefault("definition_sha256",definition.fingerprint)
        elif capability_id!="workflow:document":
            args.setdefault("namespace","")
        if capability_id=="workflow:observe":args.setdefault("checkpoint_id",None)
        if capability_id=="workflow:signal" and not has_payload:
            payload=None;has_payload=True;args.setdefault("payload_sha256",digest(payload))
        if capability_id=="workflow:memory":
            for name,default in {"key":None,"value_sha256":None,"query":"","limit":20,"ttl_seconds":None}.items():
                args.setdefault(name,default)
            if args.get("action")=="put" and not has_payload:
                payload=None;has_payload=True;args["value_sha256"]=digest(payload)
        request=OperationRequest(operation_id,self.agent_id,machine_id,capability_id,work_item_id,
                                 idempotency_key or operation_id,args)
        item=self.control.work_item_info(work_item_id,self.owner)
        if item["run_id"]!=run_id or self.policy(request).allowed is not True:raise AuthorizationRequired("workflow task/grant unavailable")
        if has_payload:self.content.prepare_value(request,payload)
        return request

    def _bind(self,run_id,work_item_id,workflow_id):
        from sentra_executors.documents import DocumentBinding,DocumentExecutor
        from .workspace_paths import workspace_paths
        from sentra_interop.workflow_bridge import SubagentWorkflowBridge
        from sentra_runtime.effect_boundary import current_effect_context
        key=(run_id,work_item_id,workflow_id)
        if key in self._bindings:return self._bindings[key]
        machine=Machine(self.machine_id,"workflow",self.owner,tuple(Capability(cap,cap) for cap in WORKFLOW_CAPABILITIES))
        center=CentralInteropAdapter(control=self.control,run_id=run_id,owner=self.owner,machine=machine)
        private=self.control.durable.root/"provider-state"/self.machine_id
        private.mkdir(parents=True,exist_ok=True)
        import hashlib
        file_id=hashlib.sha256((work_item_id+"\0"+workflow_id).encode()).hexdigest()
        bridge=SubagentWorkflowBridge(center.protocol_gate(),database=str(private/(file_id+".sqlite3")),
            workspace_root=str(private),workflow_id=workflow_id,work_item_id=work_item_id,principal_id=self.agent_id)
        paths=workspace_paths(self.workspace_root,self.control.durable.root)
        binding=DocumentBinding("workflow:document",paths,actions=("excel.inspect","excel.transform","table.inspect",
            "table.transform","pdf.inspect","pdf.text","pdf.extract_pages","artifact.verify","acceptance.evaluate"))
        executor=DocumentExecutor(machine_id=self.machine_id,owner_principal_id=self.agent_id,bindings=(binding,))
        def arguments(inputs,reference):return {**inputs,"workflow":reference}
        async def invoke(request,inputs,reference,heartbeat):
            heartbeat();context=current_effect_context.get()
            if context is None:raise AuthorizationRequired("workflow activity outside central physical admission")
            direct=OperationRequest(request.operation_id,request.principal_id,request.machine_id,request.capability_id,
                request.work_item_id,request.idempotency_key,dict(inputs))
            try:document_binding,validated=executor._check_request(direct)
            except (ValueError,TypeError,OSError):return ActivityReceipt("FAILED","NOT_STARTED",failure_type="INVALID_DOCUMENT_INPUT")
            try:result=await context.run_blocking(executor._execute,document_binding,validated)
            except Exception as exc:return ActivityReceipt("UNCERTAIN","UNKNOWN",failure_type=type(exc).__name__)
            heartbeat()
            artifacts=(result["artifact"],) if isinstance(result,dict) and isinstance(result.get("artifact"),dict) else ()
            if inputs.get("action") in {"artifact.verify","acceptance.evaluate"} and result.get("passed") is not True:
                return ActivityReceipt("FAILED","COMPLETED",output=result,artifacts=artifacts,failure_type="ACCEPTANCE_FAILED")
            return ActivityReceipt("SUCCEEDED","COMPLETED",output=result,artifacts=artifacts)
        worker=bridge.bind_worker(definitions=self.definitions,
            bindings=(WorkflowActivityBinding("documents","1","workflow:document",arguments,invoke),),
            worker_version=WORKER_VERSION,payload_resolver=self.content.resolve_value)
        for cap in WORKFLOW_CAPABILITIES:center.bind_provider(cap,worker.host_handler)
        self._bindings[key]=(center,worker)
        return center,worker

    async def submit(self,*,run_id,request):
        if self.control.durable.run_status(run_id,self.owner,include_details=False)["state"]!="RUNNING":raise AuthorizationRequired("workflow run inactive")
        args=request.arguments;workflow_id=args.get("workflow_id") or (args.get("workflow") or {}).get("workflow_id")
        if not isinstance(workflow_id,str) or not 1<=len(workflow_id)<=128:raise ValueError("stable workflow identity required")
        center,_=self._bind(run_id,request.work_item_id,workflow_id)
        return await center.start(request)

    async def shutdown(self):pass  # This binding does not start a global scheduler or process.
