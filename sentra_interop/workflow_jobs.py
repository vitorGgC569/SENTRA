"""Configured registered repository jobs on the existing MachineHost."""
from sentra_runtime.contracts import Machine, Capability, OperationRequest
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.machine_budget import BudgetedMachinePolicy
from .central import CentralInteropAdapter


class RepositoryJobMachine:
    capabilities = ("repository:operate",)
    actions = {"repository:operate": ["TEST", "BUILD", "LINT", "TYPECHECK", "BENCH"]}

    def __init__(self, control, *, owner, agent_id, machine_id, workspace_root, configuration, job_service):
        if job_service.control is not control:
            raise ValueError("repository jobs must use the same configured authority")
        from pathlib import Path
        self.root = Path(workspace_root).resolve(strict=True)
        self.control, self.owner, self.agent_id, self.machine_id = control, owner, agent_id, machine_id
        self.workspace_id, self.service = configuration["workspace_id"], job_service
        self.operations = frozenset(configuration.get("operations", self.actions["repository:operate"]))
        if not self.operations or not self.operations <= set(self.actions["repository:operate"]):
            raise ValueError("registered repository operation allowlist required")
        self.policy = BudgetedMachinePolicy(BoundWorkItemPolicy(owner=owner,
            principal_type="agent", authorization=control.authorization, governance=control.governance),
            control=control, owner=owner)
        self.bindings = {}

    def catalog(self):
        return {"kind": "repository-jobs", "workspace_id": self.workspace_id,
                "capabilities": list(self.capabilities), "actions": {"repository:operate": sorted(self.operations)}}

    def dispatch_request(self, *, run_id, work_item_id, machine_id, capability_id,
                         operation_id, arguments, idempotency_key=None):
        if machine_id != self.machine_id or capability_id != "repository:operate" or not isinstance(arguments, dict):
            raise PermissionError("unknown registered job machine")
        args = dict(arguments)
        operation, target = args.get("operation"), args.get("target", "")
        if set(args) - {"operation", "target"} or operation not in self.operations or not isinstance(target, str) or len(target) > 256 or any(char in target for char in "\0\r\n") or operation != "TEST" and target:
            raise ValueError("registered operation/target required")
        item = self.control.work_item_info(work_item_id, self.owner)
        if item["run_id"] != run_id or item.get("metadata", {}).get("workspace_id") != self.workspace_id or item.get("assignee_agent_id") != self.agent_id:
            raise PermissionError("repository job outside assigned scope")
        request = OperationRequest(operation_id, self.agent_id, machine_id, capability_id,
            work_item_id, idempotency_key or operation_id, {"operation": operation, "target": target})
        if not self.policy(request).allowed:
            raise PermissionError("repository job policy denied")
        return request

    async def submit(self, *, run_id, request):
        central = self.bindings.get(run_id)
        if central is None:
            central = CentralInteropAdapter(control=self.control, owner=self.owner, run_id=run_id,
                machine=Machine(self.machine_id, "repository-jobs", self.owner,
                                (Capability("repository:operate", "Registered repository operation", "high"),)))
            central.bind_provider("repository:operate", self.service.execute_admitted)
            self.bindings[run_id] = central
        return await central.start(request)

    async def shutdown(self):
        self.bindings.clear()
