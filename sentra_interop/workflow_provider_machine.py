"""General versioned workflow bindings, including real Activepieces activities."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from sentra_runtime.workflow_machine import DocumentWorkflowMachine
from sentra_runtime.contracts import Capability, Machine, OperationRequest
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.machine_budget import BudgetedMachinePolicy
from sentra_runtime.provider_content import ProviderContentStore
from .central import CentralInteropAdapter, is_interop_observation
from .workflow_contracts import WorkflowDefinition, ActivitySpec, RetryPolicy, digest, ident


CONTROLS = ("workflow:create", "workflow:advance", "workflow:resume", "workflow:signal",
            "workflow:cancel", "workflow:observe", "workflow:output", "workflow:memory")


class WorkflowProviderMachine(DocumentWorkflowMachine):
    def __init__(self, control, *, owner, agent_id, machine_id, workspace_root, configuration):
        self.control, self.owner, self.agent_id, self.machine_id = control, owner, agent_id, machine_id
        self.workspace_root = Path(workspace_root).resolve(strict=True)
        digest(configuration)
        self.configuration = json.loads(json.dumps(configuration, allow_nan=False))
        self.workspace_id = configuration["workspace_id"]
        self.worker_version = ident(configuration["worker_version"])
        raw_definitions = configuration["definitions"]
        if not isinstance(raw_definitions, list) or not 1 <= len(raw_definitions) <= 32:
            raise ValueError("bounded immutable workflow catalog required")
        definitions = []
        for raw in raw_definitions:
            if set(raw) != {"definition_id", "version", "steps"}:
                raise ValueError("unknown workflow definition fields")
            steps = []
            for values in raw["steps"]:
                values = dict(values)
                if "inputs" in values:
                    values["inputs_json"] = json.dumps(values.pop("inputs"), allow_nan=False, sort_keys=True, separators=(",", ":"))
                if "dependencies" in values:
                    values["dependencies"] = tuple(values["dependencies"])
                if "retry" in values:
                    retry = dict(values["retry"])
                    if "retryable_types" in retry:
                        retry["retryable_types"] = tuple(retry["retryable_types"])
                    values["retry"] = RetryPolicy(**retry)
                steps.append(ActivitySpec(**values))
            definitions.append(WorkflowDefinition(raw["definition_id"], raw["version"], self.worker_version, tuple(steps)))
        self.definitions = tuple(definitions)
        self.capabilities = tuple(dict.fromkeys((*CONTROLS, *configuration.get("activity_capabilities", ()))))
        if any(not isinstance(cap, str) or ":" not in cap for cap in self.capabilities):
            raise ValueError("configured activity capability pins required")
        self.actions = {cap: [cap.split(":")[-1]] for cap in self.capabilities}
        self.content = ProviderContentStore(control.store, owner)
        self.policy = BudgetedMachinePolicy(BoundWorkItemPolicy(owner=owner, principal_type="agent",
            authorization=control.authorization, governance=control.governance), control=control, owner=owner,
            observation_predicate=lambda request: is_interop_observation(request, "workflow-provider"))
        self._bindings, self._declarations = {}, {}
        from .workflow_sdk import source_module
        self.module = source_module(SimpleNamespace(workspace=str(self.workspace_root)),
                                    {"definition_source": configuration["binding_source"]})
        from .workflow_runtime_host import _clean_options
        _clean_options(configuration.get("binding_options",{}))
        self.binding_builder = getattr(self.module, configuration.get("binding_factory", "build_bindings"), None)
        if not callable(self.binding_builder):
            raise ValueError("pinned workflow binding factory unavailable")

    def catalog(self):
        return {"kind": "workflow-provider", "workspace_id": self.workspace_id,
                "definitions": super().catalog(), "worker_version": self.worker_version,
                "capabilities": list(self.capabilities), "actions": self.actions,
                "binding_source_sha256": self.configuration["binding_source"]["sha256"]}

    def dispatch_request(self, *, run_id, work_item_id, machine_id, capability_id, operation_id, arguments, idempotency_key=None):
        if capability_id in CONTROLS:
            return super().dispatch_request(run_id=run_id, work_item_id=work_item_id, machine_id=machine_id,
                capability_id=capability_id, operation_id=operation_id, arguments=arguments, idempotency_key=idempotency_key)
        if machine_id != self.machine_id or capability_id not in self.capabilities or not isinstance(arguments, dict):
            raise PermissionError("unconfigured workflow activity")
        request = OperationRequest(operation_id, self.agent_id, machine_id, capability_id, work_item_id,
            idempotency_key or operation_id, json.loads(json.dumps(arguments, allow_nan=False)))
        if self.control.work_item_info(work_item_id, self.owner)["run_id"] != run_id or not self.policy(request).allowed:
            raise PermissionError("workflow activity outside admitted task")
        return request

    def _bind(self, run_id, work_item_id, workflow_id):
        key = run_id, work_item_id, workflow_id
        if key in self._bindings:
            return self._bindings[key]
        center = CentralInteropAdapter(control=self.control, owner=self.owner, run_id=run_id,
            machine=Machine(self.machine_id, "workflow-provider", self.owner,
                            tuple(Capability(cap, cap, "high") for cap in self.capabilities)))
        gate = center.protocol_gate()
        scope = {"owner": self.owner, "run_id": run_id, "work_item_id": work_item_id,
                 "agent_id": self.agent_id, "machine_id": self.machine_id, "workspace_id": self.workspace_id}
        bindings = tuple(self.binding_builder(gate=gate, control=self.control, scope=scope,
            options=self.configuration.get("binding_options", {})))
        for binding in bindings:
            if binding.capability_id not in self.capabilities or binding.observe_capability is not None and binding.observe_capability not in self.capabilities:
                raise PermissionError("binding capability differs from configured catalog")
        from .workflow_bridge import SubagentWorkflowBridge
        private = self.control.durable.root / "provider-state" / self.machine_id
        # This path is only the stable logical projection partition on PG.
        file_id = hashlib.sha256((work_item_id + "\0" + workflow_id).encode()).hexdigest()
        private.mkdir(parents=True, exist_ok=True)
        bridge = SubagentWorkflowBridge(gate, database=str(private / (file_id + ".sqlite3")),
            workspace_root=str(private), workflow_id=workflow_id, work_item_id=work_item_id, principal_id=self.agent_id)
        worker = bridge.bind_worker(definitions=self.definitions, bindings=bindings, worker_version=self.worker_version,
            compatible_worker_versions=frozenset(self.configuration.get("compatible_worker_versions", ())),
            payload_resolver=self.content.resolve_value)
        for cap in self.capabilities:
            center.bind_provider(cap, worker.host_handler)
        self._bindings[key] = center, worker
        return center, worker

    async def submit(self,*,run_id,request):
        if self.control.durable.run_status(run_id,self.owner,include_details=False)["state"]!="RUNNING" and not is_interop_observation(request,"workflow-provider"):
            raise PermissionError("workflow Run inactive")
        args=request.arguments
        workflow_id=args.get("workflow_id") or (args.get("workflow") or {}).get("workflow_id")
        ident(workflow_id)
        center,_=self._bind(run_id,request.work_item_id,workflow_id)
        return await center.start(request)

    async def shutdown(self):
        self._bindings.clear()


def configure_workflow_machine(machine_host, *, workspace_id, workspace_root, agent_id, configuration):
    kind = "workflow-provider"
    machine_id = machine_host._machine_id(workspace_id, agent_id, kind)
    if machine_id in machine_host._inventory:
        raise ValueError("workflow machine configuration immutable")
    config = {**configuration, "workspace_id": workspace_id}
    machine = WorkflowProviderMachine(machine_host.control, owner=machine_host.owner, agent_id=agent_id,
        machine_id=machine_id, workspace_root=workspace_root, configuration=config)
    inventory = {**machine.catalog(), "machine_id": machine_id, "agent_id": agent_id}
    machine_host.configurations.put(machine_id, {"kind": kind, "workspace_id": workspace_id,
        "workspace_root": str(Path(workspace_root).resolve()), "agent_id": agent_id, "configuration": config})
    machine_host._factories[machine_id], machine_host._inventory[machine_id] = machine, inventory
    return inventory
