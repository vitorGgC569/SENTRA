"""Explicit fail-closed reservation boundary for SENTRA Machine Operations.

Requires a newer ControlStore implementing atomic full-intent reservation and
fencing. The LEGACY DurableRunService.create_operation method lacks an intent
fingerprint and is therefore NOT accepted as an authority. This adapter does
NOT invent a second control database or start services automatically.

This protocol can be validated using a real SQLite test provider, but it
must not be enabled for real remote effects until the core ControlStore owner
supplies and verifies the implementation, fencing-at-effect and crash recovery.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from typing import Awaitable, Callable, Protocol

from .contracts import Machine, OperationRequest, OperationResult, PolicyDecision
from .executor import (
    AuthorizationRequired, DuplicateOperation, InvalidOperation, _request_snapshot,
)


class DurableAdmissionUnavailable(PermissionError):
    """Required durable intent/fencing authority is absent or unavailable."""


@dataclass(frozen=True, slots=True)
class IntentReceipt:
    operation_id: str
    intent_sha256: str
    run_id: str
    owner: str
    fencing_token: int
    status: str

    def __post_init__(self):
        if (self.status not in {"RESERVED", "EXISTING"}
                or type(self.fencing_token) is not int or self.fencing_token <= 0):
            raise ValueError("invalid authoritative reservation receipt")


class DurableIntentAuthority(Protocol):
    """Must implement reservation and state changes atomically in ControlStore."""

    def reserve_intent(
        self, *, run_id: str, owner: str, request: OperationRequest,
        intent_sha256: str,
    ) -> IntentReceipt | Awaitable[IntentReceipt]: ...

    def fence_active(self, receipt: IntentReceipt) -> bool | Awaitable[bool]: ...

    def record_result(
        self, receipt: IntentReceipt, result: OperationResult,
    ) -> bool | Awaitable[bool]: ...


async def _await(result):
    return await result if inspect.isawaitable(result) else result


class DurableOperationGate:
    """Local guarded dispatch protocol. External authority owns all durability."""

    def __init__(
        self, authority: DurableIntentAuthority,
        authorize: Callable[[OperationRequest],
                            PolicyDecision | Awaitable[PolicyDecision]],
        *,
        machine: Machine,
    ):
        for method in ("reserve_intent", "fence_active", "record_result"):
            if not callable(getattr(authority, method, None)):
                raise DurableAdmissionUnavailable(
                    "ControlStore missing atomic intent reservation/fencing API")
        if not callable(authorize):
            raise DurableAdmissionUnavailable("authorization policy unavailable")
        if not isinstance(machine, Machine):
            raise InvalidOperation("trusted machine declaration required")
        self.authority = authority
        self.authorize = authorize
        self.machine = machine

    async def _decision(self, request: OperationRequest) -> bool:
        try:
            decision = await _await(self.authorize(request))
        except Exception:
            return False
        return (
            isinstance(decision, PolicyDecision)
            and decision.allowed is True and not decision.constraints
        )

    async def submit(
        self, *, run_id: str, owner: str, request: OperationRequest,
        effect: Callable[[OperationRequest], Awaitable[OperationResult]] | None = None,
        fenced_effect: Callable[[OperationRequest, IntentReceipt], Awaitable[OperationResult]] | None = None,
        recover_existing: bool = False,
    ) -> OperationResult:
        if not isinstance(run_id, str) or not run_id.strip():
            raise InvalidOperation("run_id required")
        if not isinstance(owner, str) or not owner.strip():
            raise InvalidOperation("authenticated owner required")
        if (callable(effect) == callable(fenced_effect)):
            raise InvalidOperation("effect is not callable")
        intent, digest = _request_snapshot(request)
        if (intent.machine_id != self.machine.machine_id
                or intent.capability_id not in {c.capability_id for c in self.machine.capabilities}
                or self.machine.owner_principal_id != owner):
            raise InvalidOperation("machine owner or capability mismatch")
        decision_input, _ = _request_snapshot(intent)
        if not await self._decision(decision_input):
            raise AuthorizationRequired("SENTRA grant denied before reservation")
        if _request_snapshot(decision_input)[1] != digest:
            raise AuthorizationRequired("policy altered reservation intent")
        try:
            receipt = await _await(self.authority.reserve_intent(
                run_id=run_id, owner=owner,
                request=_request_snapshot(intent)[0], intent_sha256=digest,
            ))
        except (ValueError, DuplicateOperation):
            raise DuplicateOperation("conflicting persistent operation identity")
        except Exception as exc:
            raise DurableAdmissionUnavailable("persistent reservation uncertain") from exc
        if not isinstance(receipt, IntentReceipt):
            raise DurableAdmissionUnavailable("invalid persistent receipt")
        if (receipt.operation_id != intent.operation_id
                or receipt.run_id != run_id
                or receipt.owner != owner
                or receipt.intent_sha256 != digest):
            raise DurableAdmissionUnavailable("persistent receipt identity mismatch")
        if receipt.status != "RESERVED":
            if recover_existing:
                recover = getattr(self.authority, "result_for_receipt", None)
                if callable(recover):
                    try:
                        recorded = await _await(recover(receipt))
                    except Exception:
                        recorded = None
                    if (isinstance(recorded, OperationResult)
                            and recorded.operation_id == intent.operation_id):
                        return recorded
            # Existing reservations never constitute an invitation to resend.
            return OperationResult(intent.operation_id, "UNCERTAIN",
                                   error="existing reservation needs reconciliation")
        if not await self._decision(_request_snapshot(intent)[0]):
            raise AuthorizationRequired("SENTRA grant revoked after reservation")
        try:
            fenced = await _await(self.authority.fence_active(receipt))
        except Exception as exc:
            raise DurableAdmissionUnavailable("fencing authority unavailable") from exc
        if fenced is not True:
            raise DurableAdmissionUnavailable("stale or absent lease fencing")
        # The caller-provided executor MUST also enforce the fencing token at
        # its physical effect boundary; checking here alone has a TOCTOU race.
        try:
            result = await (fenced_effect(_request_snapshot(intent)[0], receipt)
                            if fenced_effect is not None
                            else effect(_request_snapshot(intent)[0]))
            if (not isinstance(result, OperationResult)
                    or result.operation_id != intent.operation_id):
                raise RuntimeError("invalid external effect receipt")
        except asyncio.CancelledError:
            result = OperationResult(intent.operation_id, "UNCERTAIN",
                                     error="caller cancelled; effect completion unknown")
            try:
                await _await(self.authority.record_result(receipt, result))
            finally:
                raise
        except Exception:
            result = OperationResult(intent.operation_id, "UNCERTAIN",
                                     error="effect completion uncertain")
            # A cancellation must never convert unknown side effects to FAILED.
        if not await self._decision(_request_snapshot(intent)[0]):
            result = OperationResult(intent.operation_id, "UNCERTAIN",
                                     error="grant revoked after external dispatch")
        try:
            confirmed = await _await(self.authority.record_result(receipt, result))
        except Exception:
            confirmed = False
        if confirmed is not True:
            return OperationResult(intent.operation_id, "UNCERTAIN",
                                   error="durable result acknowledgement unavailable")
        return result
