"""Bind configured protocol providers to SENTRA's existing central authority.

Providers are registered by the trusted host. Without a provider binding the
legacy denial-only behavior remains; with a binding every dispatch reserves
intent, takes physical resource exclusion, rechecks grants/fence, and persists
recoverable evidence. No second control database or implicit service startup.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable, Any, Mapping

from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Machine, Capability, OperationRequest, OperationResult, PolicyDecision
from sentra_runtime.durable_admission import DurableAdmissionUnavailable, DurableOperationGate
from sentra_runtime.executor import ExecutorRegistry, _request_snapshot, InvalidOperation
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.central_authority import CentralDurableIntentAuthority
from .central_gate import DurableInteropGate, PinnedCentralPolicy


BLOCKED_CODE = "MISSING_ATOMIC_INTENT_RESERVATION_AND_EFFECT_FENCE"


class CentralInteropBlocked(PermissionError):
    """No external execution is allowed without the SENTRA durable authority."""


@dataclass(frozen=True, slots=True)
class CentralAuditReceipt:
    operation_id: str
    run_id: str
    work_item_id: str
    state: str
    reason: str


class CentralInteropAdapter:
    """One binding for a SENTRA-owned WorkItem and a registered Machine.

    No fallback to in-memory OperationJournal, independent SQLite ledger,
    fake grant, or untrusted agent arguments. The only approval source is
    BoundWorkItemPolicy backed by the ControlPlaneService's real SQLite DBs.
    """

    def __init__(
        self, *, control: ControlPlaneService, run_id: str,
        owner: str, machine: Machine, principal_type: str = "agent",
    ) -> None:
        if not isinstance(control, ControlPlaneService) or not isinstance(machine, Machine):
            raise TypeError("real SENTRA ControlPlaneService and Machine required")
        if not owner or not run_id or machine.owner_principal_id != owner:
            raise ValueError("trusted owner and run required")
        self.control, self.run_id, self.owner = control, run_id, owner
        self.machine = machine
        self.policy = BoundWorkItemPolicy(
            owner=owner, principal_type=principal_type,
            authorization=control.authorization, governance=control.governance,
        )
        self._blocked: dict[str, OperationResult] = {}
        self._providers: dict[str, Callable] = {}
        self._provider_constraints: dict[str, dict] = {}
        self._transport_gate: DurableInteropGate | None = None
        self.durable_gate = None

    def protocol_gate(self, *, capabilities: frozenset[str] | None = None,
                      constraints: Mapping | None = None) -> DurableInteropGate:
        """Host-only injection into ACP/A2A/MCP/connector transport adapters."""
        selected = capabilities or frozenset(c.capability_id for c in self.machine.capabilities)
        known = {c.capability_id for c in self.machine.capabilities}
        if not isinstance(selected, frozenset) or not selected or not selected <= known:
            raise ValueError("unadvertised central protocol capability")
        machine = Machine(self.machine.machine_id, self.machine.kind, self.owner,
                          tuple(c for c in self.machine.capabilities if c.capability_id in selected))
        from sentra_runtime.observations import is_observation
        authority = CentralDurableIntentAuthority(self.control.durable, release_on_terminal=True,budgets=self.control.budgets,
            observation_predicate=lambda request:is_observation(request,self.machine.kind))
        policy = PinnedCentralPolicy(self.decision, constraints)
        return DurableInteropGate(machine, policy, authority=authority,
                                  run_id=self.run_id, owner=self.owner,
                                  status_policy=self.decision)

    def bind_provider(self, capability_id: str, handler: Callable,
                      *, constraints: Mapping | None = None) -> None:
        """Register a host-configured transport operation; inventory never grants it."""
        if (capability_id not in {c.capability_id for c in self.machine.capabilities}
                or not callable(handler) or capability_id in self._providers):
            raise ValueError("invalid or duplicate central provider binding")
        self._providers[capability_id] = handler
        from sentra_runtime.machine_budget import BudgetedMachinePolicy
        if not isinstance(self.policy,BudgetedMachinePolicy):
            from sentra_runtime.observations import is_observation
            self.policy=BudgetedMachinePolicy(self.policy,control=self.control,owner=self.owner,
                observation_predicate=lambda request:is_observation(request,self.machine.kind))
        if constraints:
            self._provider_constraints[capability_id] = dict(constraints)
        self._transport_gate = self.protocol_gate(constraints=self._provider_constraints)
        self.durable_gate = DurableOperationGate(
            self._transport_gate.authority, self.decision, machine=self.machine)

    def decision(self, request: OperationRequest) -> PolicyDecision:
        if (not isinstance(request, OperationRequest)
            or request.machine_id != self.machine.machine_id
            or request.capability_id not in {c.capability_id for c in self.machine.capabilities}):
            return PolicyDecision(False,"interop machine/capability mismatch")
        try:
            current = self.control.work_item_info(request.work_item_id, self.owner)
            if current.get("run_id") != self.run_id:
                return PolicyDecision(False,"WorkItem outside authoritative Run")
            status = self.control.durable.run_status(self.run_id,self.owner,include_details=False)
            if status.get("state") not in {"CREATED","RUNNING"}:
                return PolicyDecision(False,"Run is not executable")
            return self.policy(request)
        except Exception:
            return PolicyDecision(False,"SENTRA Control Plane unavailable")

    def register(self, registry: ExecutorRegistry) -> None:
        """Host wiring: register with an already-authorized SENTRA registry."""
        if not isinstance(registry, ExecutorRegistry):
            raise TypeError("SENTRA ExecutorRegistry required")
        registry.register(self.machine,self)

    def registry(self) -> ExecutorRegistry:
        """Opt-in local registry for tests; host should call register(existing)."""
        registry=ExecutorRegistry(self.decision)
        self.register(registry)
        return registry

    async def discover(self, machine: Machine) -> tuple[Capability,...]:
        return self.machine.capabilities if machine.machine_id==self.machine.machine_id else ()

    def _record_blocked(self, request: OperationRequest) -> CentralAuditReceipt:
        """Existing SENTRA operations table stores DENIAL evidence, not intent reservations."""
        intent, fingerprint = _request_snapshot(request)
        kind="interop.blocked."+intent.capability_id.replace(":","_")
        if len(kind)>120:
            raise CentralInteropBlocked("unsupported capability")
        op=self.control.durable.create_operation(
            self.run_id, self.owner, kind=kind,
            operation_id=intent.operation_id, idempotency_key=intent.idempotency_key,
            cleanup_policy="manual",
        )
        if op.get("idempotent_replay"):
            # create_operation does NOT fingerprint intent. Never update or run
            # an existing operation from this legacy idempotency API.
            raise CentralInteropBlocked("legacy operation replay is not an intent reservation")
        if op["operation_id"]!=intent.operation_id or op["kind"]!=kind:
            raise CentralInteropBlocked("central audit operation identity mismatch")
        result=self.control.durable.update_operation(
            intent.operation_id,self.owner,state="FAILED",
            progress={"work_item_id":intent.work_item_id,
                      "intent_sha256":fingerprint,
                      "capability":intent.capability_id,
                      "interop_dispatch":"BLOCKED"},
            error={"code":BLOCKED_CODE,"safe_to_retry":False},
        )
        return CentralAuditReceipt(intent.operation_id,self.run_id,intent.work_item_id,
                                   result["state"],BLOCKED_CODE)

    async def start(self, request: OperationRequest) -> OperationResult:
        trusted,_=_request_snapshot(request)
        if not self.decision(trusted).allowed:
            result=OperationResult(trusted.operation_id,"FAILED",
                                   error="SENTRA WorkItem grant denied")
            self._blocked[trusted.operation_id]=result
            return result
        handler = self._providers.get(trusted.capability_id)
        if handler is not None and self._transport_gate is not None:
            outcome = await self._transport_gate.execute(trusted, lambda: handler(trusted))
            return outcome.operation
        if self.durable_gate is None:
            try:
                self._record_blocked(trusted)
            except Exception:
                # Missing/contended/broken durable audit writes MUST NEVER
                # accidentally enable dispatch or leak database internals.
                pass  # Still deny, never replay the remote effect.
            result=OperationResult(trusted.operation_id,"FAILED",error=BLOCKED_CODE)
            self._blocked[trusted.operation_id]=result
            return result
        # Without host-installed, physically enforced fencing at the I/O
        # boundary no remote effect may be called, even with newer APIs.
        result=OperationResult(trusted.operation_id,"FAILED",
                               error="PHYSICAL_FENCING_NOT_BOUND_TO_PROVIDER")
        self._blocked[trusted.operation_id]=result
        return result

    async def observe(self, operation_id: str) -> OperationResult:
        return await self.reconcile(operation_id)

    async def reconcile(self, operation_id: str) -> OperationResult:
        # No operation access to clients without authenticated WorkItem scope:
        # this adapter serves only its trusted host's registry.
        if operation_id in self._blocked:
            return self._blocked[operation_id]
        try:
            row=self.control.durable.operation_status(operation_id,self.owner)
            if row.get("run_id") == self.run_id and row.get("kind") in {"sentra.machine","sentra.machine.observation"}:
                gate = self._transport_gate or self.protocol_gate()
                result = await gate.journal.get(operation_id)
                if result is not None:
                    return result
            if row.get("run_id")==self.run_id and str(row.get("kind","")).startswith("interop.blocked."):
                return OperationResult(operation_id,"FAILED",error=BLOCKED_CODE)
        except Exception:
            pass
        return OperationResult(operation_id,"UNCERTAIN",
                               error="central operation not reconciled")

    async def cancel(self, operation_id: str) -> OperationResult:
        observed = await self.reconcile(operation_id)
        if observed.state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return observed
        try:
            row = self.control.durable.operation_status(operation_id, self.owner)
            if row["run_id"] != self.run_id or row["kind"] != "sentra.machine":
                return observed
            # Reconcile performs live status authorization before this request.
            progress = row.get("progress") or {}
            check = OperationRequest(operation_id, progress["principal_id"],
                progress["machine_id"], progress["capability_id"], progress["work_item_id"],
                row["idempotency_key"], {})
            if not self.decision(check).allowed:
                return OperationResult(operation_id, "FAILED", error="cancel grant denied")
            self.control.durable.request_cancel(operation_id, self.owner,
                                                side_effect_may_have_started=True)
            return OperationResult(operation_id, "UNCERTAIN",
                                   error="cancel requested; provider completion must be observed")
        except Exception:
            return observed

    async def cleanup(self, operation_id: str) -> None:
        # No external process or server may be owned by the central adapter.
        return None
