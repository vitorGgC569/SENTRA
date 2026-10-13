"""Canvas composition of QuickJS Code Mode as a centrally admitted machine."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re

from sentra_core.conversations import _encode, _decode
from sentra_code_mode import CodeModeUnavailable, QuickJSArtifact, ResourceLimits
from sentra_code_mode.dispatcher import CodeModeDispatcher
from sentra_interop.central import CentralInteropAdapter
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Capability, Machine, OperationRequest
from sentra_runtime.executor import AuthorizationRequired
from sentra_runtime.machine_budget import BudgetedMachinePolicy
from sentra_runtime.provider_content import ProviderContentStore, text_digest

CODE_ACTIONS = {"code_propose": "code:propose", "code_execute": "code:execute",
    "code_status": "code:status", "code_cancel": "code:cancel", "code_discovery": "code:discovery"}
_CAPS = tuple(CODE_ACTIONS.values())
_TOOLS = frozenset({"machine_inventory", "project_file_list", "project_file_preview"})
_PROPOSAL = re.compile(r"code-[0-9a-f]{32}\Z")


class CanvasCodeMachine:
    def __init__(self, control, *, owner, agent_id, machine_id, workspace_id,
                 workspace_root, configuration, canvas):
        if not isinstance(configuration, dict) or configuration.get("enabled") is not True:
            raise ValueError("explicit enabled Code Mode configuration required")
        if set(configuration) - {"enabled", "artifact", "limits", "tools"}:
            raise ValueError("unknown Code Mode configuration field")
        tools = configuration.get("tools", [])
        if not isinstance(tools, list) or len(set(tools)) != len(tools) or not set(tools) <= _TOOLS:
            raise ValueError("host-selected Code Mode tool allowlist required")
        self.control, self.owner, self.agent_id = control, owner, agent_id
        self.machine_id, self.workspace_id = machine_id, workspace_id
        self.workspace_root = Path(workspace_root).resolve(strict=True)
        self.canvas, self.tool_names = canvas, tuple(tools)
        artifact = configuration.get("artifact")
        if artifact is not None:
            if not isinstance(artifact, dict):
                raise ValueError("reviewed QuickJS artifact pins required")
            artifact = QuickJSArtifact(**artifact)
        else:
            from sentra_code_mode.artifact_config import load_artifact_from_env
            try:
                artifact = load_artifact_from_env()
            except CodeModeUnavailable:
                artifact = None
        limits = ResourceLimits(**configuration.get("limits", {}))
        self.dispatcher = CodeModeDispatcher(control, artifact=artifact, limits=limits, engine="quickjs-wasm")
        self.content = ProviderContentStore(control.store, owner)
        self.capabilities = _CAPS + tuple("code-tool:" + name for name in tools)
        self.actions = {cap: [cap.split(":", 1)[1]] for cap in self.capabilities}
        self.policy = BudgetedMachinePolicy(BoundWorkItemPolicy(owner=owner, principal_type="agent",
            authorization=control.authorization, governance=control.governance), control=control, owner=owner,
            observation_predicate=lambda r: r.capability_id in {"code:status", "code:discovery"})
        self._bindings = {}
        self._declarations = {}
        self._running = set()
        with closing(control.store.connect("provider_content")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS canvas_code_sources("
                "owner TEXT NOT NULL,project_id TEXT NOT NULL,proposal_id TEXT NOT NULL,"
                "protected_source TEXT NOT NULL,PRIMARY KEY(owner,proposal_id))")
            db.execute("CREATE TABLE IF NOT EXISTS canvas_code_results("
                "owner TEXT NOT NULL,project_id TEXT NOT NULL,operation_id TEXT NOT NULL,"
                "protected_result TEXT NOT NULL,PRIMARY KEY(owner,operation_id))")

    def catalog(self):
        readiness = self.dispatcher.discovery()["admission"]
        return {"kind": "code-mode", "machine_id": self.machine_id,
            "workspace_id": self.workspace_id, "agent_id": self.agent_id,
            "capabilities": list(self.capabilities), "actions": self.actions,
            "tools": list(self.tool_names), "engine": "quickjs-wasm", "availability": readiness,
            "registered": True, "grant_created": False, "execution_verified": False}

    def _item(self, run_id, work_item_id):
        item = self.control.work_item_info(work_item_id, self.owner)
        run = self.control.durable.run_status(run_id, self.owner, include_details=False)
        if (item["run_id"] != run_id or item.get("assignee_agent_id") != self.agent_id
                or item.get("metadata", {}).get("workspace_id") != self.workspace_id
                or item.get("metadata", {}).get("machine_id") != self.machine_id
                or Path(run["workspace"]).resolve() != self.workspace_root):
            raise AuthorizationRequired("Code Mode WorkItem/project/machine scope changed")
        return item

    def _proposal(self, proposal_id, run_id, work_item_id):
        if not isinstance(proposal_id, str) or not _PROPOSAL.fullmatch(proposal_id):
            raise ValueError("stable Code Mode proposal identity required")
        proposal = self.dispatcher._get_proposal(self.owner, proposal_id)
        if (proposal["run_id"], proposal["work_item_id"], proposal["agent_id"],
                Path(proposal["workspace"]).resolve()) != (run_id, work_item_id, self.agent_id, self.workspace_root):
            raise AuthorizationRequired("Code Mode proposal is outside the assigned WorkItem")
        return proposal

    def status(self, proposal_id):
        proposal = self.dispatcher._get_proposal(self.owner, proposal_id)
        self._item(proposal["run_id"], proposal["work_item_id"])
        self._proposal(proposal_id, proposal["run_id"], proposal["work_item_id"])
        value = self.dispatcher.status(self.owner, proposal_id)
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        authority = CentralDurableIntentAuthority(self.control.durable)
        verified = False
        for execution in value.get("executions", []):
            if execution["state"] != "SUCCEEDED" or execution["engine"] != "quickjs-wasm":
                continue
            op = self.control.durable.operation_status(execution["operation_id"], self.owner)
            if op["run_id"] != proposal["run_id"] or op["state"] != "SUCCEEDED":
                continue
            progress = op.get("progress") or {}
            if (progress.get("work_item_id"), progress.get("machine_id")) != (proposal["work_item_id"], self.machine_id):
                continue
            committed = authority.result_for_receipt(authority.receipt_for_operation(op["operation_id"], self.owner))
            if (committed is not None and committed.evidence.get("proposal_id") == proposal_id
                    and committed.evidence.get("a08_satisfied") is True
                    and committed.evidence.get("execution_verified") is True):
                verified = True
        return {**{k:v for k,v in value.items() if k not in {"owner", "workspace"}},
            "a08_satisfied": verified, "execution_verified": verified}

    def dispatch_request(self, *, run_id, work_item_id, machine_id, capability_id,
                         operation_id, arguments, idempotency_key=None):
        if machine_id != self.machine_id or capability_id not in _CAPS or not isinstance(arguments, dict):
            raise AuthorizationRequired("unknown Code Mode machine capability")
        self._item(run_id, work_item_id)
        args = json.loads(json.dumps(arguments, allow_nan=False))
        allowed = {"source"} if capability_id == "code:propose" else {
            "code:execute": {"proposal_id"}, "code:cancel": {"proposal_id"},
            "code:status": {"proposal_id"}, "code:discovery": set()}[capability_id]
        if set(args) - allowed:
            raise ValueError("unknown Code Mode arguments")
        payload = None
        if capability_id == "code:propose":
            source = args.pop("source", None)
            if not isinstance(source, str) or not 1 <= len(source.encode()) <= self.dispatcher.limits.max_source_bytes:
                raise ValueError("Code Mode source exceeds configured bounds")
            payload = {"source": source}
            args["source_sha256"] = text_digest(payload)
        elif capability_id != "code:discovery":
            self._proposal(args.get("proposal_id"), run_id, work_item_id)
        request = OperationRequest(operation_id, self.agent_id, machine_id, capability_id,
            work_item_id, idempotency_key or operation_id, args)
        if self.policy(request).allowed is not True:
            raise AuthorizationRequired("Code Mode requires an existing capability grant")
        if payload is not None:
            self.content.prepare_value(request, payload)
        return request

    def _tool(self, name, args):
        if not isinstance(args, dict):
            raise ValueError("Code Mode tool arguments must be an object")
        if name == "machine_inventory":
            if args:
                raise ValueError("inventory takes no selectors")
            return {"machines": self.canvas._machine_service().inventory(self.workspace_id)}
        from .project_review import ProjectReviewService
        action = name
        allowed = {"path"} if name == "project_file_preview" else {"path", "limit"}
        if set(args) - allowed:
            raise ValueError("unknown scoped project read arguments")
        return ProjectReviewService(lambda pid: self.canvas.store.workspace(pid)["path"]).dispatch(
            action, args, project_id=self.workspace_id)

    async def _effect(self, request, run_id):
        from sentra_runtime.effect_boundary import current_effect_context
        context = current_effect_context.get()
        if context is None:
            raise AuthorizationRequired("Code Mode requires central physical admission")
        context.checkpoint()
        self._item(run_id, request.work_item_id)
        cap = request.capability_id
        if cap == "code:propose":
            source = self.content.resolve_value(request, "source_sha256")["source"]
            value = self.dispatcher.propose(owner=self.owner, workspace=str(self.workspace_root),
                run_id=run_id, work_item_id=request.work_item_id, agent_id=self.agent_id,
                source=source, engine="quickjs-wasm")
            with closing(self.control.store.connect("provider_content")) as db, db:
                db.execute("INSERT INTO canvas_code_sources VALUES(?,?,?,?)",
                    (self.owner, self.workspace_id, value["proposal_id"], _encode(source)))
            value = {**value, "a08_satisfied": False, "execution_verified": False}
        elif cap == "code:discovery":
            value = {**self.dispatcher.discovery(), "execution_verified": False}
        else:
            pid = request.arguments["proposal_id"]
            self._proposal(pid, run_id, request.work_item_id)
            if cap == "code:execute":
                with closing(self.control.store.connect("provider_content")) as db:
                    row = db.execute("SELECT protected_source FROM canvas_code_sources "
                        "WHERE owner=? AND project_id=? AND proposal_id=?",
                        (self.owner, self.workspace_id, pid)).fetchone()
                if row is None:
                    raise AuthorizationRequired("protected admitted source unavailable")
                self._running.add(pid)
                try:
                    value = await self.dispatcher.execute(owner=self.owner, proposal_id=pid,
                        operation_id=request.operation_id, idempotency_key=request.idempotency_key,
                        source=_decode(row["protected_source"]),
                        tools={name: (lambda args, name=name: self._tool(name, args)) for name in self.tool_names})
                finally:
                    self._running.discard(pid)
            elif cap == "code:cancel":
                value = self.dispatcher.cancel(self.owner, pid)
            else:
                value = self.status(pid)
        context.checkpoint()
        with closing(self.control.store.connect("provider_content")) as db, db:
            db.execute("INSERT INTO canvas_code_results VALUES(?,?,?,?) ON CONFLICT(owner,operation_id) "
                "DO UPDATE SET protected_result=excluded.protected_result",
                (self.owner, self.workspace_id, request.operation_id, _encode(value)))
        return {"operation_id": request.operation_id, "result_sha256": text_digest(value),
            "protected_result": True, "proposal_id": value.get("proposal_id"), "engine": "quickjs-wasm",
            "a08_satisfied": cap == "code:execute" and value.get("ok") is True
                and value.get("a08_satisfied") is True and value.get("execution_verified") is True,
            "execution_verified": cap == "code:execute" and value.get("ok") is True
                and value.get("a08_satisfied") is True and value.get("execution_verified") is True,
            "receipt_id": "code-receipt:" + request.operation_id}

    async def submit(self, *, run_id, request):
        self._item(run_id, request.work_item_id)
        if self.control.durable.run_status(run_id, self.owner, include_details=False)["state"] != "RUNNING":
            raise AuthorizationRequired("Code Mode Run is not running")
        key = (run_id, request.work_item_id)
        center = self._bindings.get(key)
        if center is None:
            machine = Machine(self.machine_id, "code-mode", self.owner,
                tuple(Capability(cap, cap) for cap in _CAPS))
            center = CentralInteropAdapter(control=self.control, run_id=run_id, owner=self.owner, machine=machine)
            for cap in _CAPS:
                center.bind_provider(cap, lambda req, run_id=run_id: self._effect(req, run_id))
            self._bindings[key] = center
        return await center.start(request)

    def result(self, operation_id):
        op = self.control.durable.operation_status(operation_id, self.owner)
        if op["state"] != "SUCCEEDED":
            return None
        with closing(self.control.store.connect("provider_content")) as db:
            row = db.execute("SELECT protected_result FROM canvas_code_results WHERE "
                "owner=? AND project_id=? AND operation_id=?", (self.owner, self.workspace_id, operation_id)).fetchone()
        if row is None:
            return None
        value = _decode(row["protected_result"])
        # MachineHost's result receipt is authoritative; the private result is
        # returned only after that operation committed, never from a partial run.
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        authority = CentralDurableIntentAuthority(self.control.durable)
        receipt = authority.receipt_for_operation(operation_id, self.owner)
        committed = authority.result_for_receipt(receipt)
        expected = committed.evidence.get("result_sha256") if committed is not None else None
        if not isinstance(expected, str) or text_digest(value) != expected:
            raise AuthorizationRequired("Code Mode result differs from its central receipt")
        return value

    async def shutdown(self):
        for pid in list(self._running):
            self.dispatcher.cancel(self.owner, pid)


def configure_code_machine(host, *, workspace_id, workspace_root, agent_id, provider_config, canvas):
    async def configure():
        machine_id = host._machine_id(workspace_id, agent_id, "code-mode")
        if machine_id in host._inventory:
            raise ValueError("Code Mode machine configuration is immutable")
        config = json.loads(json.dumps(provider_config, allow_nan=False))
        factory = CanvasCodeMachine(host.control, owner=host.owner, agent_id=agent_id, machine_id=machine_id,
            workspace_id=workspace_id, workspace_root=workspace_root, configuration=config, canvas=canvas)
        value = factory.catalog()
        host.configurations.put(machine_id, {"kind": "code-mode", "workspace_id": workspace_id,
            "workspace_root": str(factory.workspace_root), "agent_id": agent_id, "provider_config": config})
        host._factories[machine_id] = factory
        host._inventory[machine_id] = value
        return value
    return host._call(configure())
