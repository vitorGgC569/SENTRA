"""Opt-in central SENTRA executor registration and durable-admission binding.

Consumes the REAL ControlPlaneService, AuthorizationService, GovernanceService,
ExecutorRegistry and DurableOperationGate. DOES NOT own grants, SQLite journals
or scheduling. Live dispatch DENIED without coordinator-supplied atomic
full-intent/fencing authority. Never auto-registers with Canvas host.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Machine, OperationRequest, OperationResult
from sentra_runtime.durable_admission import (
    DurableAdmissionUnavailable, DurableOperationGate,
)
from sentra_runtime.executor import (
    ExecutorRegistry, AuthorizationRequired, _request_snapshot,
)
from sentra_runtime.central_authority import CentralDurableIntentAuthority
from sentra_runtime.effect_boundary import CentralEffectContext, current_effect_context

from .browser_lab import (
    BrowserReadBinding, BrowserLabExecutor, declare_browser_lab_machine,
)
from ._base import GuardedExecutor
from .discovery import MachineDeclaration


@dataclass(frozen=True)
class CentralRegisteredMachine:
    machine: Machine
    capability_ids: tuple[str, ...]


class CentralExecutorFactory:
    """Central-service-consumed factory, NOT an alternate control plane.

    The owner/principal are trusted constructor data, never request arguments.
    Only exact browser lab read-only is dispatchable by this version. Other
    executor declarations remain discoverable but NOT auto-authorized.
    """

    def __init__(self, *, control: ControlPlaneService, owner: str,
                 agent_id: str, durable_intent_authority: Any = None):
        if (not isinstance(control, ControlPlaneService)
                or not isinstance(owner, str) or not owner.strip()
                or not isinstance(agent_id, str) or not agent_id.strip()):
            raise ValueError("trusted_central_control_owner_agent_required")
        self.control = control
        self.owner = owner
        self.agent_id = agent_id
        self.policy = BoundWorkItemPolicy(
            owner=owner, principal_type="agent",
            authorization=control.authorization, governance=control.governance,
        )
        # Policy is NOT enough to invoke a backend directly: require a
        # dispatch scope activated only after durable gate approval.
        self._dispatch_fingerprint = ContextVar(
            "sentra_central_effect_fingerprint", default=None)
        self.registry = ExecutorRegistry(authorize=self._registry_policy)
        # No fallback to DurableRunService.create_operation: it lacks full
        # intent fingerprint+atomic reserve+physical-effect fencing.
        self.durable_intent_authority = durable_intent_authority
        self._declarations: dict[str, Any] = {}
        self._read_only_bindings: dict[str, BrowserReadBinding] = {}
        self._execution_machines: set[str] = set()

    def _registry_policy(self, request: OperationRequest):
        from sentra_runtime.contracts import PolicyDecision
        _, digest = _request_snapshot(request)
        if self._dispatch_fingerprint.get() != digest:
            return PolicyDecision(False, "central durable admission required")
        return self.policy(request)

    def register_lab_browser(self, *, machine_id: str, binding: BrowserReadBinding,
                             backend: Any = None) -> CentralRegisteredMachine:
        """Called by trusted host only; inventory never grants permissions."""
        if machine_id in self._declarations:
            raise ValueError("machine_already_registered")
        if (not isinstance(binding, BrowserReadBinding)
                or not callable(getattr(backend, "run", None))):
            # A backend must be explicitly injected: do not auto-launch Chromium
            # or open the user's profile in this central factory.
            raise ValueError("explicit_readonly_lab_backend_required")
        declaration = declare_browser_lab_machine(
            machine_id=machine_id, owner_principal_id=self.agent_id,
            bindings=(binding,), policy=self._registry_policy, backend=backend,
        )
        declaration.register(self.registry)
        self._declarations[machine_id] = declaration
        self._read_only_bindings[machine_id] = binding
        return CentralRegisteredMachine(declaration.machine, (binding.capability_id,))

    def register_inventory(self, declaration: MachineDeclaration) -> CentralRegisteredMachine:
        """Register an existing trusted SENTRA adapter as discover-only.

        No grant, no dispatch route and no backend launch. In particular,
        a caller cannot execute UIA/Daytona by submitting to this factory.
        """
        if (not isinstance(declaration, MachineDeclaration)
                or not isinstance(declaration.adapter, GuardedExecutor)
                or declaration.machine.owner_principal_id != self.agent_id
                or declaration.machine.kind != declaration.adapter.kind
                or declaration.machine.machine_id != declaration.adapter.machine_id
                or declaration.machine.machine_id in self._declarations):
            raise ValueError("untrusted_or_duplicate_machine_inventory")
        # Replace caller-configured policy with the trusted central policy.
        # Registry direct-submit still fails without durable dispatch scope.
        declaration.adapter.policy = self._registry_policy
        declaration.register(self.registry)
        self._declarations[declaration.machine.machine_id] = declaration
        return CentralRegisteredMachine(
            declaration.machine,
            tuple(cap.capability_id for cap in declaration.machine.capabilities),
        )

    def register_execution(self, declaration: MachineDeclaration) -> CentralRegisteredMachine:
        """Bind a configured real executor to central physical-effect admission.

        Host-only registration, never catalog-driven installation or a grant.
        Direct registry submission remains denied without this factory's scope.
        The OS lock wraps the worker itself via GuardedExecutor, so a timed-out
        caller cannot release physical ownership while its I/O is still running.
        """
        if self.durable_intent_authority is None:
            self.durable_intent_authority = CentralDurableIntentAuthority(
                self.control.durable, release_on_terminal=True,budgets=self.control.budgets)
        if (not isinstance(self.durable_intent_authority, CentralDurableIntentAuthority)
                or self.durable_intent_authority.durable is not self.control.durable):
            raise DurableAdmissionUnavailable("live executor requires this central durable authority")
        if self.durable_intent_authority.budgets is None:
            self.durable_intent_authority.budgets=self.control.budgets
        from sentra_runtime.machine_budget import BudgetedMachinePolicy
        from sentra_runtime.observations import is_observation
        if self.durable_intent_authority.observation_predicate is None:
            self.durable_intent_authority.observation_predicate=lambda request:is_observation(request,
                self._declarations[request.machine_id].machine.kind) if request.machine_id in self._declarations else False
        if not isinstance(self.policy,BudgetedMachinePolicy):
            self.policy=BudgetedMachinePolicy(self.policy,control=self.control,owner=self.owner,
                observation_predicate=self.durable_intent_authority.observation_predicate)
        registered = self.register_inventory(declaration)
        self._execution_machines.add(registered.machine.machine_id)
        return registered

    def dispatch_request(self, *, run_id: str, work_item_id: str,
                         machine_id: str, capability_id: str, operation_id: str,
                         arguments: dict, idempotency_key: str | None = None) -> OperationRequest:
        """Construct a host-bound request for a registered live capability."""
        if machine_id not in self._execution_machines or not run_id:
            raise AuthorizationRequired("live machine is not centrally registered")
        machine = self._declarations[machine_id].machine
        if capability_id not in {cap.capability_id for cap in machine.capabilities}:
            raise AuthorizationRequired("unregistered live capability")
        request = OperationRequest(
            operation_id, self.agent_id, machine_id, capability_id, work_item_id,
            idempotency_key or operation_id, arguments,
        )
        self._validate_link(run_id=run_id, request=request)
        return _request_snapshot(request)[0]

    async def discover(self, machine_id: str):
        """Use the actual ExecutorAdapter discover protocol from the registry."""
        if machine_id not in self._declarations:
            raise ValueError("machine_not_registered")
        return await self._declarations[machine_id].discover()

    def request(self, *, run_id: str, work_item_id: str,
                machine_id: str, operation_id: str, url: str) -> OperationRequest:
        # run_id is checked again against authoritative SQLite when submitted.
        if not run_id or not work_item_id or not operation_id:
            raise ValueError("run_work_item_operation_required")
        binding = self._read_only_bindings.get(machine_id)
        if binding is None or url not in binding.allowed_urls:
            raise ValueError("unregistered_machine_or_lab_url")
        return OperationRequest(
            operation_id=operation_id, principal_id=self.agent_id,
            machine_id=machine_id, capability_id=binding.capability_id,
            work_item_id=work_item_id, idempotency_key=operation_id,
            arguments={"action": "read_page", "url": url},
        )

    def _validate_link(self, *, run_id: str, request: OperationRequest) -> None:
        if (request.principal_id != self.agent_id or
                request.machine_id not in self._read_only_bindings
                and request.machine_id not in self._execution_machines):
            raise AuthorizationRequired("principal or machine not centrally registered")
        run = self.control.durable.run_status(run_id, self.owner, include_details=False)
        item = self.control.work_item_info(request.work_item_id, self.owner)
        if (run["state"] != "RUNNING"
                or item["run_id"] != run_id or item["state"] != "RUNNING"
                or item.get("assignee_agent_id") != self.agent_id
                or request.capability_id not in (item.get("required_capabilities") or [])):
            raise AuthorizationRequired("run/work_item/capability binding not active")

    async def submit(self, *, run_id: str, request: OperationRequest) -> OperationResult:
        """Only durable reservation can admit effect; no legacy unsafe fallback."""
        self._validate_link(run_id=run_id, request=request)
        if self.policy(request).allowed is not True:
            raise AuthorizationRequired("SENTRA live grant denied")
        declaration = self._declarations[request.machine_id]
        # Legacy central durable service must be denied unless the coordinator
        # supplies the exact newer DurableIntentAuthority contract.
        if self.durable_intent_authority is None:
            raise DurableAdmissionUnavailable(
                "ControlStore lacks atomic full-intent/fencing authority")
        # DurableOperationGate's machine is owner-scoped; the registry machine
        # is the agent-scoped execution target. Same machine_id/capabilities,
        # no change to either authoritative representation.
        admission_machine = Machine(
            machine_id=declaration.machine.machine_id,
            kind=declaration.machine.kind, owner_principal_id=self.owner,
            capabilities=declaration.machine.capabilities,
        )
        gate = DurableOperationGate(
            self.durable_intent_authority, self.policy,
            machine=admission_machine,
        )

        async def effect(trusted_request: OperationRequest, receipt) -> OperationResult:
            self._validate_link(run_id=run_id, request=trusted_request)
            _, digest = _request_snapshot(trusted_request)
            token = self._dispatch_fingerprint.set(digest)
            physical_token = None
            if request.machine_id in self._execution_machines:
                physical_token = current_effect_context.set(CentralEffectContext(
                    self.durable_intent_authority, receipt, trusted_request, self.policy))
            try:
                return await self.registry.submit(trusted_request)
            finally:
                if physical_token is not None:
                    current_effect_context.reset(physical_token)
                self._dispatch_fingerprint.reset(token)

        return await gate.submit(
            run_id=run_id, owner=self.owner, request=request, fenced_effect=effect,
            recover_existing=request.machine_id in self._execution_machines,
        )

    async def reconcile(self, *, run_id: str, request: OperationRequest) -> OperationResult:
        """Reauth + durable lookup; EXISTS must return UNCERTAIN, never replay."""
        return await self.submit(run_id=run_id, request=request)

    def cancel_from_control(self, *, run_id: str, operation_id: str,
                            work_item_id: str) -> dict:
        """Trusted host control only: record cancel in durable center, no replay."""
        item = self.control.work_item_info(work_item_id, self.owner)
        record = self.control.durable.operation_status(operation_id, self.owner)
        progress = record.get("progress") or {}
        if (item["run_id"] != run_id or record["run_id"] != run_id
                or progress.get("work_item_id") != work_item_id):
            raise AuthorizationRequired("operation is not linked to this WorkItem")
        return self.control.durable.request_cancel(
            operation_id, self.owner, side_effect_may_have_started=True,
        )

    async def cleanup(self, *, request: OperationRequest) -> None:
        """Read-only browser owns its own context teardown; forbid unauthed cleanup."""
        if self.policy(request).allowed is not True:
            raise AuthorizationRequired("cleanup requires live SENTRA grant")
        record = self.control.durable.operation_status(
            request.operation_id, self.owner)
        progress = record.get("progress") or {}
        if (record.get("operation_id") != request.operation_id
                or progress.get("work_item_id") != request.work_item_id
                or progress.get("capability_id") != request.capability_id):
            raise AuthorizationRequired("operation not linked to authorized WorkItem")
        # The registry cleans only an already completed local read-only call.
        await self.registry.cleanup(request.operation_id)
