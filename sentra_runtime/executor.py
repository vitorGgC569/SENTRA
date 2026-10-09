"""Fail-closed universal ExecutorRegistry; no default privilege.

This registry provides a safe in-process adapter boundary. Durable idempotency,
leases/fencing and policy freshness remain the existing SENTRA ControlStore's
responsibility for multi-process/distributed production usage.
"""
from __future__ import annotations
import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol
from .contracts import Capability, Machine, OperationRequest, OperationResult, PolicyDecision


class AuthorizationRequired(PermissionError):
    pass


class InvalidOperation(ValueError):
    pass


class DuplicateOperation(RuntimeError):
    pass


class ExecutorAdapter(Protocol):
    async def discover(self, machine: Machine) -> tuple[Capability, ...]: ...
    async def start(self, request: OperationRequest) -> OperationResult: ...
    async def observe(self, operation_id: str) -> OperationResult: ...
    async def cancel(self, operation_id: str) -> OperationResult: ...
    async def reconcile(self, operation_id: str) -> OperationResult: ...
    async def cleanup(self, operation_id: str) -> None: ...


PolicyChecker = Callable[[OperationRequest], PolicyDecision | Awaitable[PolicyDecision]]


def _request_snapshot(request: OperationRequest) -> tuple[OperationRequest, str]:
    """Fingerprint the original intent and copy all caller-owned arguments.

    OperationRequest is frozen but nested dictionaries are not. Reusing the
    caller's reference would allow an old result to be reconciled against an
    altered request. Only canonical JSON data is accepted across this boundary.
    """
    if not isinstance(request, OperationRequest):
        raise InvalidOperation("invalid operation request")
    try:
        fields = [
            request.operation_id, request.principal_id, request.machine_id,
            request.capability_id, request.work_item_id, request.idempotency_key,
            dict(request.arguments),
        ]
        data = json.dumps(fields, ensure_ascii=False, sort_keys=True,
                          allow_nan=False, separators=(",", ":"))
        if len(data.encode("utf-8")) > 1_048_576:
            raise ValueError("operation payload exceeds admission limit")
        values = json.loads(data)
        if any(not isinstance(v, str) for v in values[:6]):
            raise ValueError("operation identity must be string")
        if not isinstance(values[6], dict):
            raise ValueError("operation arguments must be an object")
        clone = OperationRequest(
            operation_id=values[0], principal_id=values[1],
            machine_id=values[2], capability_id=values[3],
            work_item_id=values[4], idempotency_key=values[5],
            arguments=values[6],
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise InvalidOperation("operation intent cannot be serialized safely") from exc
    fingerprint = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return clone, fingerprint


@dataclass(slots=True)
class _Record:
    request: OperationRequest
    fingerprint: str
    executor: ExecutorAdapter


class ExecutorRegistry:
    """Requires an external AuthorizationService; never allows implicitly."""

    def __init__(self, authorize: PolicyChecker | None = None):
        self._authorize = authorize
        self._machines: dict[str, Machine] = {}
        self._executors: dict[str, ExecutorAdapter] = {}
        self._operations: dict[str, _Record] = {}
        self._idempotency_keys: dict[str, str] = {}
        # Serializes admission in a single process. Distributed deployments
        # additionally need durable ControlStore locks/leases.
        self._submit_lock = asyncio.Lock()

    def register(self, machine: Machine, executor: ExecutorAdapter) -> None:
        if machine.machine_id in self._machines:
            raise InvalidOperation("machine already registered")
        self._machines[machine.machine_id] = machine
        self._executors[machine.machine_id] = executor

    def machines(self) -> tuple[Machine, ...]:
        return tuple(self._machines.values())

    def get_machine(self, machine_id: str) -> Machine:
        if machine_id not in self._machines:
            raise InvalidOperation("unknown machine")
        return self._machines[machine_id]

    async def submit(self, request: OperationRequest) -> OperationResult:
        # A per-registry admission lock prevents concurrent duplicate sends.
        # Remote, multi-process execution still needs durable SENTRA fencing.
        async with self._submit_lock:
            trusted_request, fingerprint = _request_snapshot(request)
            machine = self.get_machine(trusted_request.machine_id)
            if trusted_request.capability_id not in {c.capability_id for c in machine.capabilities}:
                raise InvalidOperation("machine does not advertise this capability")
            previous = self._operations.get(trusted_request.operation_id)
            if previous is not None and previous.fingerprint != fingerprint:
                raise DuplicateOperation("operation_id reused with different payload")
            if previous is None and request.idempotency_key in self._idempotency_keys:
                raise DuplicateOperation("idempotency_key already consumed")
            # Idempotent status lookups must also pass live authorization.
            # A revoked agent may not consult the old provider by replay.
            if self._authorize is None:
                raise AuthorizationRequired("SENTRA authorization authority not configured")
            # Never share the policy callback's mutable request with an
            # executor: policy code may retain and mutate it after approval.
            policy_request, _ = _request_snapshot(trusted_request)
            try:
                decision = self._authorize(policy_request)
                if inspect.isawaitable(decision):
                    decision = await decision
            except Exception as exc:
                raise AuthorizationRequired("policy evaluation failed closed") from exc
            if not isinstance(decision, PolicyDecision) or not decision.allowed:
                reason = decision.reason if isinstance(decision, PolicyDecision) else "invalid policy decision"
                raise AuthorizationRequired(f"policy denied: {reason}")
            # The generic adapter cannot yet enforce a restrictive policy
            # constraint, so deny it rather than silently dropping it.
            if decision.constraints:
                raise AuthorizationRequired("constrained grants require a validated policy-bound adapter")
            # A policy callback must not rewrite the authorized request.
            if _request_snapshot(policy_request)[1] != fingerprint:
                raise AuthorizationRequired("policy altered operation intent")
            if previous is not None:
                # Authorized reconciliation only; never repeat a side effect.
                return await previous.executor.reconcile(trusted_request.operation_id)
            adapter = self._executors[trusted_request.machine_id]
            self._idempotency_keys[trusted_request.idempotency_key] = trusted_request.operation_id
            # Store an independently copied snapshot, not the adapter's mutable input.
            durable_view, _ = _request_snapshot(trusted_request)
            self._operations[trusted_request.operation_id] = _Record(durable_view, fingerprint, adapter)
            # Reserve BEFORE side effect; any downstream error is UNCERTAIN.
            adapter_request, _ = _request_snapshot(trusted_request)
            result = await adapter.start(adapter_request)
            if result.operation_id != trusted_request.operation_id:
                raise InvalidOperation("executor returned another operation_id")
            return result

    def operation_request(self, operation_id: str) -> OperationRequest:
        """Internal lookup for an authenticated control-plane adapter.

        Callers MUST authenticate before exposing any details from the result.
        """
        if operation_id not in self._operations:
            raise InvalidOperation("unknown operation_id")
        # Return a copy: external users cannot mutate our internal history.
        original = self._operations[operation_id].request
        return _request_snapshot(original)[0]

    def _existing(self, operation_id: str) -> ExecutorAdapter:
        if operation_id not in self._operations:
            raise InvalidOperation("unknown operation_id")
        return self._operations[operation_id].executor

    async def observe(self, operation_id: str) -> OperationResult:
        return await self._existing(operation_id).observe(operation_id)

    async def cancel(self, operation_id: str) -> OperationResult:
        return await self._existing(operation_id).cancel(operation_id)

    async def reconcile(self, operation_id: str) -> OperationResult:
        return await self._existing(operation_id).reconcile(operation_id)

    async def cleanup(self, operation_id: str) -> None:
        await self._existing(operation_id).cleanup(operation_id)
