"""Shared fail-closed operation gate for Machine executors.

No infrastructure is started here. Records are process-local: reconciliation after
a restart MUST use the control plane journal, not automatic replay.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class LocalOperationResult:
    operation_id: str
    state: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class _Record:
    key: str
    signature: tuple[str, ...]
    state: str = "running"
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    cancel_requested: bool = False


def _result(operation_id: str, state: str, evidence: Mapping[str, Any] | None = None,
            error: str | None = None) -> Any:
    # The coordinator owns this contract; use it when present, without writing it.
    try:
        from sentra_runtime.contracts import OperationResult
    except ImportError:
        OperationResult = LocalOperationResult
    # Core v1 accepts six uppercase states; authorization denial is FAILED.
    states = {"running": "RUNNING", "succeeded": "SUCCEEDED",
              "failed": "FAILED", "denied": "FAILED",
              "uncertain": "UNCERTAIN", "unknown": "UNCERTAIN",
              "cancelled": "CANCELLED"}
    return OperationResult(operation_id=operation_id or "invalid-operation",
                           state=states.get(state, state),
                           evidence=dict(evidence or {}), error=error)


class GuardedExecutor:
    """Reusable gate. A trusted policy callback is mandatory for every operation.

    The callback receives an OperationRequest and returns a PolicyDecision (or a
    shape with allowed/constraints). A raw caller-provided 'allowed' flag is
    NEVER treated as authorization.
    """

    kind = ""

    def __init__(self, *, machine_id: str, owner_principal_id: str,
                 bindings: Mapping[str, Any],
                 policy: Callable[[Any], Any] | None = None):
        if not machine_id or not owner_principal_id or not bindings:
            raise ValueError("machine, principal and capabilities are required")
        self.machine_id = machine_id
        self.owner_principal_id = owner_principal_id
        self.bindings = dict(bindings)
        self.policy = policy
        self._records: dict[str, _Record] = {}
        self._keys: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def _validate(self, request: Any, binding: Any) -> dict[str, Any]:
        raise NotImplementedError

    def _execute(self, binding: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """Blocking backend execution. Must return sanitized evidence only."""
        raise NotImplementedError

    async def discover(self, machine: Any) -> tuple[Any, ...]:
        """Core ExecutorAdapter protocol: discover(Machine) -> capabilities."""
        if (machine.machine_id != self.machine_id or machine.kind != self.kind or
                machine.owner_principal_id != self.owner_principal_id):
            raise ValueError("machine_registration_scope_mismatch")
        from sentra_runtime.contracts import Capability
        if {c.capability_id for c in machine.capabilities} != set(self.bindings):
            raise ValueError("registered_capability_mismatch")
        return tuple(Capability(capability_id=k, description=self.kind,
                                risk_level=self._risk(k)) for k in self.bindings)

    def _risk(self, capability_id: str) -> str:
        return "high"

    def _check_request(self, request: Any) -> tuple[Any, dict[str, Any]]:
        if (getattr(request, "machine_id", None) != self.machine_id or
                getattr(request, "principal_id", None) != self.owner_principal_id):
            raise ValueError("machine_or_principal_scope")
        if not all(isinstance(getattr(request, k, None), str) and
                   getattr(request, k).strip()
                   for k in ("operation_id", "idempotency_key", "work_item_id", "capability_id")):
            raise ValueError("invalid_operation_identity")
        binding = self.bindings.get(request.capability_id)
        if binding is None:
            raise ValueError("unknown_capability")
        arguments = getattr(request, "arguments", None)
        if not isinstance(arguments, Mapping):
            raise ValueError("invalid_arguments")
        return binding, self._validate(request, binding)

    async def _allowed(self, request: Any, args: dict[str, Any]) -> bool:
        if self.policy is None:
            return False
        try:
            decision = self.policy(request)
            if inspect.isawaitable(decision):
                decision = await decision
            from sentra_runtime.contracts import PolicyDecision
            if not isinstance(decision, PolicyDecision) or decision.allowed is not True:
                return False
            constraints = decision.constraints
            if not isinstance(constraints, Mapping):
                return False
            permitted = {
                "allowed_actions": "action",
                "allowed_pids": "pid",
                "allowed_hwnds": "hwnd",
                "allowed_sandbox_ids": "sandbox_id",
            }
            for name, permitted_field in permitted.items():
                if name in constraints:
                    allowlist = constraints[name]
                    if (not isinstance(allowlist, (list, tuple, set, frozenset)) or
                            args.get(permitted_field) not in allowlist):
                        return False
            if set(constraints).difference(permitted):
                return False
            return True
        except Exception:
            return False

    async def start(self, request: Any) -> Any:
        op = getattr(request, "operation_id", "")
        if not isinstance(op, str) or not op:
            return _result("", "denied", error="invalid_operation_identity")
        try:
            binding, args = self._check_request(request)
        except (ValueError, TypeError):
            return _result(op, "denied", error="invalid_scope_or_capability")
        key = request.idempotency_key
        try:
            # Bind a repeated operation ID to the same validated immutable intent.
            # Otherwise a caller could replay a previous success for a new action.
            signature = (request.principal_id, request.machine_id,
                         request.work_item_id, request.capability_id,
                         json.dumps(args, sort_keys=True, allow_nan=False))
        except (TypeError, ValueError):
            return _result(op, "denied", error="invalid_arguments")
        async with self._lock:
            existing = self._records.get(op)
            owner = self._keys.get(key)
            if existing:
                if existing.key != key or existing.signature != signature:
                    return _result(op, "denied", error="idempotency_conflict")
                return _result(op, existing.state, existing.evidence, existing.error)
            if owner is not None:
                return _result(op, "denied", error="idempotency_conflict")
            record = _Record(key, signature)
            self._records[op] = record
            self._keys[key] = op

        if not await self._allowed(request, args):
            return await self._finish(op, "denied", error="policy_denied")
        # Re-evaluate immediately before dispatch to catch pre-dispatch revocation.
        if not await self._allowed(request, args):
            return await self._finish(op, "denied", error="policy_revoked")
        async with self._lock:
            if record.cancel_requested:
                return self._snapshot(op, record)
        try:
            # asyncio.to_thread propagates this trusted host context. The OS
            # resource lock belongs to the worker, not the timing-out waiter.
            from sentra_runtime.effect_boundary import current_effect_context
            context = current_effect_context.get()
            def execute_at_boundary():
                if context is not None:
                    return context.run_sync(self._execute, binding, args)
                return self._execute(binding, args)
            evidence = await asyncio.wait_for(
                asyncio.to_thread(execute_at_boundary),
                timeout=float(binding.timeout_seconds))
        except asyncio.TimeoutError:
            # Thread/remote action may still finish. Never imply safe rollback.
            return await self._finish(op, "uncertain", error="timeout_may_have_executed")
        except asyncio.CancelledError:
            await self._finish(op, "uncertain", error="task_cancelled_may_have_executed")
            raise
        except Exception:
            if context is not None:
                return await self._finish(op, "uncertain", error="physical_effect_error_requires_reconciliation")
            return await self._finish(op, "failed", error="backend_error")
        # A grant may be revoked while the blocking UIA/SDK call is in flight.
        # No rollback or successful completion can be asserted in that case.
        if not await self._allowed(request, args):
            return await self._finish(op, "uncertain",
                                      error="policy_revoked_after_dispatch")
        return await self._finish(op, "succeeded", evidence=evidence)

    def _snapshot(self, op: str, record: _Record) -> Any:
        return _result(op, record.state, record.evidence, record.error)

    async def _finish(self, op: str, state: str, *, evidence: dict[str, Any] | None = None,
                      error: str | None = None) -> Any:
        async with self._lock:
            record = self._records[op]
            if record.cancel_requested or record.state == "uncertain":
                record.state = "uncertain"
                record.error = record.error or "cancelled_or_ambiguous"
                record.evidence = {}
            else:
                record.state, record.error = state, error
                record.evidence = evidence or {}
            return self._snapshot(op, record)

    async def observe(self, operation_id: str) -> Any:
        op = getattr(operation_id, "operation_id", operation_id)
        async with self._lock:
            record = self._records.get(op)
            return (self._snapshot(op, record) if record else
                    _result(op, "unknown", error="not_in_local_journal"))

    async def cancel(self, operation_id: str) -> Any:
        op = getattr(operation_id, "operation_id", operation_id)
        async with self._lock:
            record = self._records.get(op)
            if record is None:
                return _result(op, "unknown", error="not_in_local_journal")
            if record.state == "running":
                record.cancel_requested = True
                record.state = "uncertain"
                record.error = "cancel_requested_execution_uncertain"
            return self._snapshot(op, record)

    async def reconcile(self, operation_id: str) -> Any:
        # Deliberately no re-submission on restart or uncertain result.
        return await self.observe(operation_id)

    async def cleanup(self, operation_id: str) -> None:
        # Owns no sandbox/server/process. Cleanup is non-destructive by design.
        await self.observe(operation_id)
        return None
