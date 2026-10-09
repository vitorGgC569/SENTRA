"""Deny-by-default authorization and in-process idempotency for interop boundaries.

The coordinator's sentra_runtime contracts are the sole authoritative types.
The journal prevents repeat effects within this adapter instance; process restart
requires a SENTRA durable operation journal before enabling remote dispatch.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from sentra_runtime.contracts import Machine, OperationRequest, OperationResult, PolicyDecision

PolicyEvaluator = Callable[[OperationRequest], PolicyDecision | Awaitable[PolicyDecision]]
Effect = Callable[[], Any | Awaitable[Any]]


class InteropDenied(PermissionError):
    """An operation was rejected before invoking a backend."""


class EffectRejected(ValueError):
    """A locally validated action was rejected without any side effect."""


def _fingerprint(request: OperationRequest) -> str:
    # Reject non-JSON/cyclic values, not accidentally stringify arbitrary objects.
    data = json.dumps(
        [request.operation_id, request.idempotency_key, request.principal_id,
         request.machine_id, request.capability_id, request.work_item_id,
         request.arguments],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )
    if len(data.encode("utf-8")) > 65536:
        raise ValueError("operation payload too large")
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    operation: OperationResult
    payload: Any = None
    duplicate: bool = False


class OperationJournal:
    """Lock-protected, process-local admission/dedupe: NEVER retry uncertain effects."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_operation: dict[str, tuple[str, str, OperationResult]] = {}
        self._by_key: dict[str, str] = {}

    async def reserve(self, request: OperationRequest) -> OperationResult | None:
        signature = _fingerprint(request)
        async with self._lock:
            existing = self._by_operation.get(request.operation_id)
            key_owner = self._by_key.get(request.idempotency_key)
            if existing:
                old_key, old_signature, old_result = existing
                if old_key != request.idempotency_key or old_signature != signature:
                    return OperationResult(request.operation_id, "FAILED", error="operation identity conflict")
                return old_result
            if key_owner is not None:
                return OperationResult(request.operation_id, "FAILED", error="idempotency key already used")
            result = OperationResult(request.operation_id, "ACCEPTED")
            self._by_operation[request.operation_id] = (request.idempotency_key, signature, result)
            self._by_key[request.idempotency_key] = request.operation_id
            return None

    async def finish(self, request: OperationRequest, result: OperationResult) -> None:
        async with self._lock:
            entry = self._by_operation.get(request.operation_id)
            if entry is None or entry[0] != request.idempotency_key:
                raise RuntimeError("operation was not reserved")
            self._by_operation[request.operation_id] = (entry[0], entry[1], result)

    async def get(self, operation_id: str) -> OperationResult | None:
        async with self._lock:
            entry = self._by_operation.get(operation_id)
            return entry[2] if entry else None


class InteropGate:
    """Common no-side-effect-before-policy boundary for ACP/A2A/MCP actions.

    Machine capabilities are a second admission gate. Unknown policy constraints
    are denied so they cannot silently weaken a PDP's conditions.
    """

    def __init__(
        self,
        machine: Machine,
        policy: PolicyEvaluator | None,
        journal: OperationJournal | None = None,
    ) -> None:
        self.machine = machine
        self.policy = policy
        self.journal = journal or OperationJournal()

    async def decision(self, request: OperationRequest) -> PolicyDecision:
        if not isinstance(request, OperationRequest):
            return PolicyDecision(False, "invalid request type")
        if request.machine_id != self.machine.machine_id:
            return PolicyDecision(False, "unknown machine")
        if request.capability_id not in {c.capability_id for c in self.machine.capabilities}:
            return PolicyDecision(False, "capability not advertised")
        try:
            _fingerprint(request)
        except (TypeError, ValueError, OverflowError, RecursionError):
            return PolicyDecision(False, "invalid payload")
        if self.policy is None:
            return PolicyDecision(False, "policy unavailable")
        try:
            decision = self.policy(request)
            if inspect.isawaitable(decision):
                decision = await decision
            if not isinstance(decision, PolicyDecision) or decision.allowed is not True:
                return PolicyDecision(False, "policy denied")
            if not isinstance(decision.constraints, Mapping):
                return PolicyDecision(False, "invalid constraints")
            allowed_keys = {"principal_ids", "work_item_ids", "machine_ids", "capability_ids",
                            "max_payload_bytes", "executable_paths", "cwd_roots", "argv_sha256"}
            if set(decision.constraints) - allowed_keys:
                return PolicyDecision(False, "unsupported policy constraint")
            for key, value in (
                ("principal_ids", request.principal_id),
                ("work_item_ids", request.work_item_id),
                ("machine_ids", request.machine_id),
                ("capability_ids", request.capability_id),
            ):
                if key in decision.constraints:
                    allowed = decision.constraints[key]
                    if not isinstance(allowed, (list, tuple, set, frozenset)) or value not in allowed:
                        return PolicyDecision(False, "constraint mismatch")
            if request.capability_id in {"acp:launch", "mcp:launch", "openhands:launch"}:
                executable = request.arguments.get("executable")
                cwd = request.arguments.get("cwd")
                argv = request.arguments.get("args")
                approved_argv_hash = decision.constraints.get("argv_sha256")
                allowed_paths = decision.constraints.get("executable_paths")
                allowed_roots = decision.constraints.get("cwd_roots")
                if (not isinstance(executable, str) or not isinstance(cwd, str)
                    or not isinstance(argv, list)
                    or any(not isinstance(arg, str) for arg in argv)
                    or not isinstance(approved_argv_hash, str)
                    or not isinstance(allowed_paths, (list, tuple, set, frozenset))
                    or not isinstance(allowed_roots, (list, tuple, set, frozenset))
                    or not allowed_paths or not allowed_roots
                    or any(not isinstance(item, str) for item in (*allowed_paths, *allowed_roots))):
                    return PolicyDecision(False, "launch requires pinned paths")
                resolved_executable = Path(executable).resolve()
                resolved_cwd = Path(cwd).resolve()
                if (resolved_executable not in {Path(p).resolve() for p in allowed_paths}
                    or not any(resolved_cwd.is_relative_to(Path(p).resolve()) for p in allowed_roots)):
                    return PolicyDecision(False, "launch path outside policy")
                actual_argv_hash = hashlib.sha256(json.dumps(
                    argv, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
                if actual_argv_hash != approved_argv_hash:
                    return PolicyDecision(False, "launch argv does not match policy")
            if "max_payload_bytes" in decision.constraints:
                size = decision.constraints["max_payload_bytes"]
                if type(size) is not int or size < 0:
                    return PolicyDecision(False, "invalid payload limit")
                if len(json.dumps(request.arguments, ensure_ascii=False).encode("utf-8")) > size:
                    return PolicyDecision(False, "payload limit exceeded")
            return decision
        except Exception:
            return PolicyDecision(False, "policy evaluation failed")

    async def execute(
        self,
        request: OperationRequest,
        effect: Effect,
        *,
        timeout: float | None = None,
    ) -> DispatchOutcome:
        decision = await self.decision(request)
        if not decision.allowed:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error=decision.reason))
        duplicate = await self.journal.reserve(request)
        if duplicate is not None:
            return DispatchOutcome(duplicate, duplicate=True)
        try:
            invoked = effect()
            if inspect.isawaitable(invoked):
                payload = await asyncio.wait_for(invoked, timeout) if timeout is not None else await invoked
            else:
                payload = invoked
            # A grant revoked while the backend was active must not become a
            # trusted success. The remote effect may have happened: UNCERTAIN,
            # never FAILED/retry-safe or SUCCEEDED.
            final_decision = await self.decision(request)
            if not final_decision.allowed:
                result = OperationResult(request.operation_id, "UNCERTAIN",
                                         error="policy revoked or unavailable after dispatch")
                await self.journal.finish(request, result)
                return DispatchOutcome(result)
            # MCP errors are normal protocol responses, not successful executions.
            is_error = isinstance(payload, Mapping) and payload.get("isError") is True
            result = OperationResult(request.operation_id, "FAILED" if is_error else "SUCCEEDED",
                                     error="backend returned an error" if is_error else None)
            await self.journal.finish(request, result)
            return DispatchOutcome(result, payload)
        except asyncio.CancelledError:
            await self.journal.finish(request, OperationResult(request.operation_id, "UNCERTAIN",
                                                              error="request cancelled; remote effect unknown"))
            raise
        except EffectRejected:
            result = OperationResult(request.operation_id, "FAILED", error="local admission rejected")
        except (asyncio.TimeoutError, TimeoutError):
            result = OperationResult(request.operation_id, "UNCERTAIN", error="backend timeout; reconcile before retry")
        except Exception:
            result = OperationResult(request.operation_id, "UNCERTAIN", error="backend failed; effect unknown")
        await self.journal.finish(request, result)
        return DispatchOutcome(result)
