"""MachineHost adapter machines for subordinate runtimes + fenced terminal.

:func:`configure_runtime_machine` / :func:`configure_terminal_machine`
register into the host ``_inventory``/``_factories`` (plus
``configurations``) exactly like the existing provider machines, for root
HTTP configuration and the Nexo ``configure_runtime`` wrapper. No second
authority: policy (``BoundWorkItemPolicy``/``BudgetedMachinePolicy``),
registry (``CentralInteropAdapter`` per Run) and grants stay central.

- ``RuntimeProviderMachine`` (temporal/langgraph) exposes
  ``dispatch_request(...run_id/work_item_id/machine_id/capability_id/
  operation_id/arguments/key) -> OperationRequest`` and
  ``async submit(run_id, request) -> OperationResult``. Its handler calls
  ``RuntimeProviderHost.submit`` inside the fence with the **binding
  scope resolved server-side** (tenant/run/work/principal pinned at
  ``configure``); sensitive payloads travel via ``ProviderContentStore``
  (digests in journal args, values resolved only inside the active
  central scope).
- ``TerminalWriteMachine`` closes the user action the facade builder
  alone cannot: ``terminal:write`` is admitted as a central operation
  and executed by ``TerminalWriteGate.execute`` inside the fence, with
  run/work/principal re-resolved from the server ledger (never request
  fields). Vault/secret material never appears in machine configuration;
  SDK secret refs stay pinned in the provider host vault references.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Capability, Machine, OperationRequest
from sentra_runtime.executor import AuthorizationRequired
from sentra_runtime.machine_budget import BudgetedMachinePolicy
from sentra_runtime.provider_content import (
    ProviderContentStore, text_digest)
from .central import CentralInteropAdapter, is_interop_observation
from .workflow_contracts import digest, ident
from .workflow_runtime import RuntimeScope
from .workflow_runtime_host import RuntimeHostDenied, RuntimeProviderHost

TEMPORAL_OPERATIONS = ("start", "advance", "signal", "interrupt", "resume",
                       "cancel", "observe", "reconcile")
LANGGRAPH_OPERATIONS = TEMPORAL_OPERATIONS + ("fork",)

TERMINAL_CAPABILITIES = ("terminal:start", "terminal:read", "terminal:write", "terminal:close")


def _capabilities(provider: str) -> tuple[str, ...]:
    if provider == "temporal":
        return tuple("runtime:temporal:" + op for op in TEMPORAL_OPERATIONS)
    if provider == "langgraph":
        return tuple("runtime:langgraph:" + op for op in LANGGRAPH_OPERATIONS)
    raise RuntimeHostDenied("unknown runtime provider")


class RuntimeProviderMachine:
    """Subordinate runtime effects behind central admission (per binding)."""

    def __init__(self, control: Any, *, owner: str, agent_id: str,
                 machine_id: str, workspace_root: str, configuration: dict,
                 runtime_host: RuntimeProviderHost):
        if not isinstance(configuration, dict):
            raise ValueError("explicit runtime machine configuration required")
        provider = configuration.get("provider", "")
        binding_id = configuration.get("binding_id", "")
        workspace_id = configuration.get("workspace_id", "")
        if provider not in {"temporal", "langgraph"}:
            raise ValueError("unknown runtime provider")
        if not isinstance(binding_id, str) or not binding_id:
            raise ValueError("runtime provider binding required")
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ValueError("runtime machine workspace required")
        if runtime_host is None or runtime_host.control is not control or getattr(runtime_host, "owner", owner) != owner:
            raise ValueError("runtime provider host of this owner required")
        self.control, self.owner = control, owner
        self.agent_id, self.machine_id = agent_id, machine_id
        self.workspace_id, self.provider = workspace_id, provider
        self.runtime_host = runtime_host
        self.binding_id = binding_id
        adapter = runtime_host.restore(binding_id)
        config = adapter._config
        if config is None or config["owner"] != owner:
            raise AuthorizationRequired("runtime binding belongs to another owner")
        self.scope = RuntimeScope(owner=config["owner"], run_id=config["run_id"],
                                  work_item_id=config["work_item_id"],
                                  principal_id=config["principal_id"], machine_id=machine_id, workspace_id=workspace_id)
        if self.scope.principal_id != agent_id:
            raise AuthorizationRequired("runtime binding scoped to another agent")
        self.capabilities = _capabilities(provider)
        self.actions = {cap: [cap.split(":")[2]] for cap in self.capabilities}
        self.content = ProviderContentStore(control.store, owner)
        self.policy = BudgetedMachinePolicy(
            BoundWorkItemPolicy(owner=owner, principal_type="agent",
                                authorization=control.authorization,
                                governance=control.governance),
            control=control, owner=owner,
            observation_predicate=lambda request: is_interop_observation(
                request, "runtime"))
        self._bindings: dict[str, Any] = {}

    def catalog(self) -> dict[str, Any]:
        return {"kind": "runtime-" + self.provider, "provider": self.provider,
                "binding_id": self.binding_id,
                "workspace_id": self.workspace_id,
                "scope": {"run_id": self.scope.run_id,
                          "work_item_id": self.scope.work_item_id,
                          "principal_id": self.scope.principal_id},
                "capabilities": list(self.capabilities),
                "actions": dict(self.actions),
                "registered": True, "grant_created": False}

    def dispatch_request(self, *, run_id: str, work_item_id: str,
                         machine_id: str, capability_id: str,
                         operation_id: str, arguments: dict,
                         idempotency_key: str | None = None) -> OperationRequest:
        if machine_id != self.machine_id or capability_id not in self.capabilities \
                or not isinstance(arguments, dict):
            raise AuthorizationRequired("unknown runtime machine capability")
        operation = capability_id.split(":")[2]
        args = json.loads(json.dumps(arguments, allow_nan=False))
        workflow_id = args.pop("workflow_id", "")
        occurrence = args.pop("occurrence", "")
        ident(workflow_id)
        if not isinstance(occurrence, str) or not 1 <= len(occurrence) <= 256:
            raise ValueError("bounded runtime occurrence required")
        item = self.control.work_item_info(work_item_id, self.owner)
        if item["run_id"] != run_id or run_id != self.scope.run_id \
                or work_item_id != self.scope.work_item_id:
            raise AuthorizationRequired("runtime operation outside bound scope")
        staged: dict[str, Any] = {}
        if operation == "start":
            staged["inputs"] = self._take_payload(args, "inputs")
        elif operation == "signal":
            staged["payload"] = self._take_payload(args, "payload")
            signal_name = args.pop("name", "")
            ident(signal_name)
            args["name"] = signal_name
        elif operation == "resume":
            staged["values"] = self._take_payload(args, "values")
        elif operation == "advance":
            if isinstance(args.get("resume"), dict):
                staged["resume"] = self._take_payload(args, "resume")
        elif operation == "interrupt":
            reason = args.pop("reason", "")
            if not isinstance(reason, str) or not 1 <= len(reason) <= 512:
                raise ValueError("bounded interrupt reason required")
            staged["reason"] = reason
        elif operation == "fork":
            new_occurrence = args.pop("new_occurrence", "")
            if not isinstance(new_occurrence, str) or not 1 <= len(new_occurrence) <= 256:
                raise ValueError("bounded fork occurrence required")
            args["new_occurrence"] = new_occurrence
            if args.get("checkpoint_id") is not None:
                if not isinstance(args["checkpoint_id"], str) \
                        or not 1 <= len(args["checkpoint_id"]) <= 256:
                    raise ValueError("bounded checkpoint identity required")
        elif operation not in {"advance", "cancel", "observe", "reconcile"}:
            raise AuthorizationRequired("unknown runtime operation")
        allowed_remainder = {
            "start": set(), "advance": set(), "signal": {"name"},
            "interrupt": set(), "resume": set(), "cancel": set(),
            "observe": set(), "reconcile": set(),
            "fork": {"new_occurrence", "checkpoint_id"},
        }[operation]
        foreign = set(args) - allowed_remainder
        if foreign:
            raise ValueError("foreign runtime operation parameters: "
                             + ",".join(sorted(foreign)))
        args["binding_id"] = self.binding_id
        args["provider_config_sha256"] = self.runtime_host.binding_fingerprint(self.binding_id)
        args["workflow_id"] = workflow_id
        args["occurrence"] = occurrence
        for key, value in staged.items():
            args[key + "_sha256"] = text_digest(value)
        request = OperationRequest(operation_id, self.agent_id, machine_id,
                                   capability_id, work_item_id,
                                   idempotency_key or operation_id, args)
        if self.policy(request).allowed is not True:
            raise AuthorizationRequired("runtime task/grant unavailable")
        for value in staged.values():
            self.content.prepare_value(request, value)
        return request

    def _take_payload(self, args: dict, key: str) -> Any:
        value = args.pop(key, None)
        if not isinstance(value, dict):
            raise ValueError(f"runtime {key} must be a JSON mapping")
        digest(value)
        return value

    def _bind(self, run_id: str):
        if run_id in self._bindings:
            return self._bindings[run_id]
        central = CentralInteropAdapter(
            control=self.control, owner=self.owner, run_id=run_id,
            machine=Machine(self.machine_id, "runtime-" + self.provider,
                            self.owner, tuple(Capability(cap, cap, "high")
                                              for cap in self.capabilities)))
        scope = self.scope

        async def handler(request):
            if request.principal_id != self.agent_id:
                raise AuthorizationRequired("runtime agent mismatch")
            if request.arguments.get("binding_id") != self.binding_id or request.arguments.get("provider_config_sha256") != self.runtime_host.binding_fingerprint(self.binding_id):
                raise AuthorizationRequired("runtime provider pin changed")
            operation = request.capability_id.split(":")[2]
            workflow_id = request.arguments["workflow_id"]
            occurrence = request.arguments["occurrence"]
            payload = None
            for sha_key in ("inputs_sha256", "payload_sha256",
                            "values_sha256", "resume_sha256", "reason_sha256"):
                if sha_key in request.arguments:
                    payload = self.content.resolve_value(request, sha_key)
                    break
            kwargs: dict[str, Any] = {}
            if operation in {"start", "signal"} and payload is not None:
                kwargs["payload"] = payload
            if operation == "signal":
                kwargs["signal_name"] = request.arguments["name"]
            if operation == "resume" and payload is not None:
                kwargs["values"] = payload
            if operation == "advance" and "resume_sha256" in request.arguments:
                kwargs["values"] = payload
            if operation == "interrupt":
                kwargs["reason"] = payload
            if operation == "fork":
                kwargs["new_occurrence"] = request.arguments["new_occurrence"]
                if request.arguments.get("checkpoint_id") is not None:
                    kwargs["checkpoint_id"] = request.arguments["checkpoint_id"]
            outcome = await self.runtime_host.submit(
                self.binding_id, operation=operation, scope=scope,
                workflow_id=workflow_id, occurrence=occurrence, **kwargs)
            from sentra_runtime.contracts import OperationResult
            if outcome.get("status") == "UNCERTAIN":
                return OperationResult(request.operation_id, "UNCERTAIN", evidence=outcome,
                                       error=outcome.get("failure_type", "PROVIDER_UNCERTAIN"))
            return outcome

        for cap in self.capabilities:
            central.bind_provider(cap, handler)
        self._bindings[run_id] = central
        return central

    async def submit(self, *, run_id: str, request: Any):
        if self.control.durable.run_status(run_id, self.owner,
                                           include_details=False)["state"] != "RUNNING" and not is_interop_observation(request,"runtime"):
            raise AuthorizationRequired("runtime run not active")
        return await self._bind(run_id).start(request)

    async def shutdown(self):
        self._bindings.clear()


class TerminalWriteMachine:
    """Fenced ``terminal:write`` behind central admission (ledger-scoped)."""

    def __init__(self, control: Any, *, owner: str, agent_id: str,
                 machine_id: str, workspace_root: str, configuration: dict,
                 canvas: Any = None):
        if not isinstance(configuration, dict):
            raise ValueError("explicit terminal machine configuration required")
        workspace_id = configuration.get("workspace_id", "")
        canvas_principal = configuration.get("canvas_principal", "")
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ValueError("terminal machine workspace required")
        if not isinstance(canvas_principal, str) or not 1 <= len(canvas_principal) <= 128 \
                or any(c in canvas_principal for c in "\0\r\n"):
            raise ValueError("terminal machine canvas principal required")
        if canvas is None or getattr(getattr(canvas, "store", None),
                                     "principal", None) != canvas_principal:
            raise ValueError("terminal machine requires the Canvas host of its principal")
        self.control, self.owner = control, owner
        self.agent_id, self.machine_id = agent_id, machine_id
        self.workspace_id, self.canvas_principal = workspace_id, canvas_principal
        self.canvas = canvas
        self.capabilities = TERMINAL_CAPABILITIES
        self.actions = {cap: [cap.split(":")[1]] for cap in self.capabilities}
        self.content = ProviderContentStore(control.store, owner)
        self.policy = BudgetedMachinePolicy(
            BoundWorkItemPolicy(owner=owner, principal_type="agent",
                                authorization=control.authorization,
                                governance=control.governance),
            control=control, owner=owner,
            observation_predicate=lambda request: is_interop_observation(
                request, "terminal"))
        self._bindings: dict[str, Any] = {}

    def catalog(self) -> dict[str, Any]:
        return {"kind": "terminal", "workspace_id": self.workspace_id,
                "capabilities": list(self.capabilities),
                "actions": dict(self.actions),
                "registered": True, "grant_created": False}

    def _ledger_scope(self, terminal_id: str, *, require_open=True) -> dict[str, Any]:
        from sentra_executors.conpty_sessions import PersistentConPTYLedger
        try:
            binding = PersistentConPTYLedger(self.control).get(
                self.owner, self.workspace_id, terminal_id)
        except FileNotFoundError:
            raise AuthorizationRequired("terminal session not registered here")
        if require_open and binding["state"] != "OPEN":
            raise AuthorizationRequired("terminal session is not open")
        return binding

    def dispatch_request(self, *, run_id: str, work_item_id: str,
                         machine_id: str, capability_id: str,
                         operation_id: str, arguments: dict,
                         idempotency_key: str | None = None) -> OperationRequest:
        if machine_id != self.machine_id or capability_id not in self.capabilities \
                or not isinstance(arguments, dict):
            raise AuthorizationRequired("unknown terminal machine capability")
        args = json.loads(json.dumps(arguments, allow_nan=False))
        item = self.control.work_item_info(work_item_id, self.owner)
        if item["run_id"] != run_id or item.get("assignee_agent_id") != self.agent_id or item.get("metadata", {}).get("workspace_id") != self.workspace_id:
            raise AuthorizationRequired("terminal WorkItem outside assigned project/Run")
        data = None
        if capability_id == "terminal:start":
            import re
            if set(args) != {"name", "shell"} or args.get("shell") not in {"powershell", "cmd"} or not isinstance(args.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args["name"]):
                raise ValueError("vetted shell and terminal name required")
            fenced = {"workspace_id": self.workspace_id, **args}
        else:
            terminal_id = args.pop("terminal_id", "")
            binding = self._ledger_scope(terminal_id, require_open=capability_id != "terminal:read")
            if (binding["run_id"], binding["work_item_id"], binding["principal_id"]) != (run_id, work_item_id, self.agent_id):
                raise AuthorizationRequired("terminal scope mismatch")
            fenced = {"workspace_id": self.workspace_id, "terminal_id": terminal_id}
            if capability_id == "terminal:write":
                data = args.pop("data", None)
                if not isinstance(data, str) or not 1 <= len(data.encode()) <= 4096 or args:
                    raise ValueError("bounded terminal input required")
                fenced.update(action="write_stdin", payload_sha256=text_digest(data))
            elif capability_id == "terminal:read":
                for name, default, maximum in (("cursor", 0, 10**12), ("head_chars", 2048, 8192), ("tail_chars", 4096, 8192)):
                    value = args.pop(name, default)
                    if type(value) is not int or not 0 <= value <= maximum:
                        raise ValueError("bounded terminal read window required")
                    fenced[name] = value
                if args:
                    raise ValueError("foreign terminal read parameters")
            elif args:
                raise ValueError("foreign terminal close parameters")
        request = OperationRequest(operation_id, self.agent_id, machine_id, capability_id,
            work_item_id, idempotency_key or operation_id, fenced)
        if self.policy(request).allowed is not True:
            raise AuthorizationRequired("terminal task/grant unavailable")
        if data is not None:
            self.content.prepare(request, data)
        return request

    def _bind(self, run_id: str):
        if run_id in self._bindings:
            return self._bindings[run_id]
        central = CentralInteropAdapter(
            control=self.control, owner=self.owner, run_id=run_id,
            machine=Machine(self.machine_id, "terminal", self.owner,
                            tuple(Capability(cap, cap, "high")
                                  for cap in self.capabilities)))

        async def handler(request):
            from sentra_executors.conpty_sessions import TerminalWriteGate
            if request.principal_id != self.agent_id:
                raise AuthorizationRequired("terminal agent mismatch")
            if request.capability_id != "terminal:write":
                from sentra_executors.conpty_sessions import ExistingConPTYSession
                return ExistingConPTYSession(control=self.control,canvas=self.canvas).lifecycle(
                    request,owner=self.owner,run_id=run_id,workspace_id=self.workspace_id,
                    canvas_principal=self.canvas_principal)
            terminal_id = request.arguments["terminal_id"]
            binding = self._ledger_scope(terminal_id)
            if binding["run_id"] != run_id \
                    or binding["work_item_id"] != request.work_item_id:
                raise AuthorizationRequired("terminal scope changed")
            gate = TerminalWriteGate(control=self.control, canvas=self.canvas)
            data = self.content.resolve_value(request, "payload_sha256")
            if not isinstance(data, str):
                raise AuthorizationRequired("terminal input has invalid type")
            return gate.execute(
                request=request, data=data, owner=self.owner,
                run_id=binding["run_id"], work_item_id=binding["work_item_id"],
                principal_id=binding["principal_id"],
                workspace_id=self.workspace_id, terminal_id=terminal_id,
                principal=self.canvas_principal)

        for capability in self.capabilities:
            central.bind_provider(capability, handler)
        self._bindings[run_id] = central
        return central

    async def submit(self, *, run_id: str, request: Any):
        if self.control.durable.run_status(run_id, self.owner,
                                           include_details=False)["state"] != "RUNNING" and not is_interop_observation(request,"terminal"):
            raise AuthorizationRequired("terminal run not active")
        return await self._bind(run_id).start(request)

    async def shutdown(self):
        self._bindings.clear()


def configure_runtime_machine(machine_host: Any, *, workspace_id: str,
                              workspace_root: str, agent_id: str,
                              provider: str, binding_id: str,
                              runtime_host: Any) -> dict[str, Any]:
    """Register one runtime provider machine (root HTTP / Nexo wrapper).

    Tenant/run/work come from the server: owner is the host owner, the
    Run/WorkItem/principal from the bound provider scope, vault refs stay
    pinned in the provider host (never in machine configuration).
    """
    from pathlib import Path as _Path
    if provider not in {"temporal", "langgraph"}:
        raise ValueError("unknown runtime provider")
    if not isinstance(binding_id, str) or not binding_id:
        raise ValueError("runtime provider binding required")
    if runtime_host is None or runtime_host.control is not machine_host.control or getattr(runtime_host, "owner", None) != machine_host.owner:
        raise ValueError("runtime provider host of this owner required")
    root = _Path(workspace_root).resolve(strict=True)
    if not root.is_dir() or not workspace_id or not agent_id:
        raise ValueError("trusted workspace and agent required")
    kind = "runtime-" + provider
    machine_id = machine_host._machine_id(
        workspace_id, agent_id, kind + "-" + binding_id[-8:])
    if machine_id in machine_host._inventory:
        raise ValueError("runtime machine configuration is immutable")
    machine = RuntimeProviderMachine(
        machine_host.control, owner=machine_host.owner, agent_id=agent_id,
        machine_id=machine_id, workspace_root=str(root),
        configuration={"provider": provider, "binding_id": binding_id,
                       "workspace_id": workspace_id},
        runtime_host=runtime_host)
    inventory = {**machine.catalog(), "machine_id": machine_id,
                 "workspace_id": workspace_id, "agent_id": agent_id}
    machine_host.configurations.put(machine_id, {
        "kind": kind, "workspace_id": workspace_id,
        "workspace_root": str(root), "agent_id": agent_id,
        "provider": provider, "binding_id": binding_id})
    machine_host._factories[machine_id] = machine
    machine_host._inventory[machine_id] = inventory
    return dict(inventory)


def configure_terminal_machine(machine_host: Any, *, workspace_id: str,
                               workspace_root: str, agent_id: str,
                               canvas_principal: str, canvas: Any) -> dict[str, Any]:
    """Register the fenced terminal machine (root HTTP composition)."""
    from pathlib import Path as _Path
    root = _Path(workspace_root).resolve(strict=True)
    if not root.is_dir() or not workspace_id or not agent_id:
        raise ValueError("trusted workspace and agent required")
    machine_id = machine_host._machine_id(workspace_id, agent_id, "terminal")
    if machine_id in machine_host._inventory:
        raise ValueError("terminal machine configuration is immutable")
    machine = TerminalWriteMachine(
        machine_host.control, owner=machine_host.owner, agent_id=agent_id,
        machine_id=machine_id, workspace_root=str(root),
        configuration={"workspace_id": workspace_id,
                       "canvas_principal": canvas_principal},
        canvas=canvas)
    inventory = {**machine.catalog(), "machine_id": machine_id,
                 "workspace_id": workspace_id, "agent_id": agent_id}
    machine_host.configurations.put(machine_id, {
        "kind": "terminal", "workspace_id": workspace_id,
        "workspace_root": str(root), "agent_id": agent_id,
        "canvas_principal": canvas_principal})
    machine_host._factories[machine_id] = machine
    machine_host._inventory[machine_id] = inventory
    return dict(inventory)


async def aconfigure_runtime_machine(machine_host, **configuration):
    runtime_host = configuration["runtime_host"]
    if runtime_host.control is not machine_host.control:
        raise ValueError("runtime host must share configured control by identity")
    await runtime_host.arestore(configuration["binding_id"])
    return configure_runtime_machine(machine_host, **configuration)
