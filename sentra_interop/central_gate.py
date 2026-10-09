"""InteropGate backed by the existing central Run/Operation/Artifact stores.

Protocol adapters can use the same reserve/finish or execute interfaces without
an independent operation database. Transport effects take the central physical
lock, live grant and durable fence. A replay returns stored evidence or UNCERTAIN;
it never restarts the transport or sends the request again.
"""
from __future__ import annotations

import asyncio
import inspect
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from sentra_runtime.central_authority import CentralDurableIntentAuthority
from sentra_runtime.contracts import OperationRequest, OperationResult, PolicyDecision
from sentra_runtime.durable_admission import IntentReceipt, DurableAdmissionUnavailable
from sentra_runtime.effect_boundary import CentralEffectContext
from sentra_runtime.executor import AuthorizationRequired, DuplicateOperation, _request_snapshot

from .gate import DispatchOutcome, EffectRejected, InteropGate


class PinnedCentralPolicy:
    """Trusted configuration adds constraints; it cannot override a central denial."""
    def __init__(self, authorize, constraints=None):
        self.authorize = authorize
        self.constraints = json.loads(json.dumps(constraints or {}, allow_nan=False))

    def __call__(self, request):
        decision = self.authorize(request)
        if not isinstance(decision, PolicyDecision) or decision.allowed is not True:
            return decision
        pinned = self.constraints.get(request.capability_id, {})
        return PolicyDecision(True, decision.reason, pinned)

    @staticmethod
    def validate_constraints(request, constraints) -> bool:
        supported = {"principal_ids", "work_item_ids", "machine_ids", "capability_ids",
                     "max_payload_bytes", "executable_paths", "cwd_roots", "argv_sha256"}
        if set(constraints) - supported:
            return False
        for key, field in (("principal_ids", "principal_id"),
                           ("work_item_ids", "work_item_id"),
                           ("machine_ids", "machine_id"),
                           ("capability_ids", "capability_id")):
            if key in constraints and (not isinstance(constraints[key], (list, tuple))
                                       or getattr(request, field) not in constraints[key]):
                return False
        args = request.arguments
        if request.capability_id in {"acp:launch", "mcp:launch", "openhands:launch"}:
            if (not isinstance(args.get("executable"), str) or not isinstance(args.get("cwd"), str)
                    or not isinstance(args.get("args"), list)
                    or any(not isinstance(x, str) for x in args["args"])
                    or not constraints.get("executable_paths") or not constraints.get("cwd_roots")):
                return False
            try:
                if (Path(args["executable"]).resolve() not in
                        {Path(p).resolve() for p in constraints["executable_paths"]}
                        or not any(Path(args["cwd"]).resolve().is_relative_to(Path(p).resolve())
                                   for p in constraints["cwd_roots"])):
                    return False
                argv_hash = hashlib.sha256(json.dumps(
                    args["args"], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                if argv_hash != constraints.get("argv_sha256"):
                    return False
            except (TypeError, ValueError, OSError):
                return False
        if "max_payload_bytes" in constraints:
            limit = constraints["max_payload_bytes"]
            if type(limit) is not int or limit < 0 or len(json.dumps(args).encode()) > limit:
                return False
        return True


class _CentralJournal:
    def __init__(self, gate: "DurableInteropGate"):
        self.gate = gate
        self._receipts: dict[str, IntentReceipt] = {}

    async def reserve(self, request: OperationRequest) -> OperationResult | None:
        decision = await self.gate.decision(request)
        if not decision.allowed:
            raise AuthorizationRequired(decision.reason)
        intent, digest = _request_snapshot(request)
        receipt = self.gate.authority.reserve_intent(
            run_id=self.gate.run_id, owner=self.gate.owner,
            request=intent, intent_sha256=digest,
        )
        self._receipts[intent.operation_id] = receipt
        if receipt.status == "EXISTING":
            try:
                recovered = self.gate.authority.result_for_receipt(receipt)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError):
                return OperationResult(intent.operation_id, "UNCERTAIN",
                                       error="stored evidence is unavailable or does not verify")
            return recovered or OperationResult(intent.operation_id, "UNCERTAIN",
                                                  error="existing effect requires reconciliation")
        if not self.gate.authority.fence_active(receipt):
            raise DurableAdmissionUnavailable("central transport lease is not active")
        return None

    async def finish(self, request: OperationRequest, result: OperationResult) -> None:
        receipt = self.receipt(request)
        if not self.gate.authority.record_result(receipt, result):
            raise DurableAdmissionUnavailable("central transport result not acknowledged")

    def receipt(self, request: OperationRequest) -> IntentReceipt:
        receipt = self._receipts.get(request.operation_id)
        if (receipt is None or receipt.intent_sha256 != _request_snapshot(request)[1]
                or receipt.operation_id != request.operation_id):
            raise DurableAdmissionUnavailable("transport has no bound central reservation")
        return receipt

    async def get(self, operation_id: str) -> OperationResult | None:
        authority = self.gate.authority
        durable = authority.durable
        try:
            row = durable.operation_status(operation_id, self.gate.owner)
        except FileNotFoundError:
            return None
        progress = row.get("progress") or {}
        if row["run_id"] != self.gate.run_id or row["kind"] not in {"sentra.machine","sentra.machine.observation"}:
            return None
        request = OperationRequest(
            operation_id, progress["principal_id"], progress["machine_id"],
            progress["capability_id"], progress["work_item_id"], row["idempotency_key"], {},
        )
        # Status reads need a live owner/work-item grant, but do not repeat
        # transport launch's executable/argv validation with an invented payload.
        decision = self.gate.status_policy(request)
        if inspect.isawaitable(decision):
            decision = await decision
        if not isinstance(decision, PolicyDecision) or decision.allowed is not True:
            raise AuthorizationRequired("transport status grant revoked or unavailable")
        receipt = authority.receipt_for_operation(operation_id, self.gate.owner)
        recovered = authority.result_for_receipt(receipt)
        return recovered or OperationResult(operation_id, "UNCERTAIN",
                                              error="central result requires provider reconciliation")


class DurableInteropGate(InteropGate):
    def __init__(self, machine, policy, *, authority: CentralDurableIntentAuthority,
                 run_id: str, owner: str, status_policy=None):
        if (not isinstance(authority, CentralDurableIntentAuthority)
                or machine.owner_principal_id != owner or not run_id or not owner):
            raise ValueError("trusted central transport binding required")
        self.authority, self.run_id, self.owner = authority, run_id, owner
        self.status_policy = status_policy or policy
        super().__init__(machine, policy)
        self.journal = _CentralJournal(self)

    async def decision(self, request):
        try:
            candidate, digest = _request_snapshot(request)
        except (TypeError, ValueError, RecursionError):
            return PolicyDecision(False, "invalid central transport intent")
        decision = await super().decision(candidate)
        if _request_snapshot(candidate)[1] != digest:
            return PolicyDecision(False, "policy altered central transport intent")
        return decision

    def physical_context(self, request: OperationRequest) -> CentralEffectContext:
        return CentralEffectContext(self.authority, self.journal.receipt(request),
                                    request, self._physical_policy)

    def _physical_policy(self, request: OperationRequest) -> PolicyDecision:
        # The real central policy is synchronous. Launch constraints are
        # validated by InteropGate.decision before reservation and are pinned
        # again by the host policy on each boundary; they must not disappear.
        decision = self.policy(request)
        if inspect.isawaitable(decision):
            raise TypeError("central physical policy must be synchronous")
        if not isinstance(decision, PolicyDecision) or decision.allowed is not True:
            return PolicyDecision(False, "central transport authorization denied")
        if decision.constraints:
            # Full constraint evaluation is async but contains no I/O except
            # the policy call. The trusted host checks the pinned launch data
            # synchronously; only then strip constraints at the physical layer.
            validate = getattr(self.policy, "validate_constraints", None)
            if not callable(validate) or validate(request, decision.constraints) is not True:
                return PolicyDecision(False, "physical policy constraints not bound")
        return PolicyDecision(True, "central transport physical grant verified")

    async def execute(self, request, effect, *, timeout=None) -> DispatchOutcome:
        intent, digest = _request_snapshot(request)
        decision = await self.decision(intent)
        if not decision.allowed or _request_snapshot(intent)[1] != digest:
            return DispatchOutcome(OperationResult(intent.operation_id, "FAILED",
                                                     error=decision.reason))
        try:
            previous = await self.journal.reserve(intent)
        except (ValueError, DuplicateOperation, AuthorizationRequired, DurableAdmissionUnavailable) as exc:
            return DispatchOutcome(OperationResult(intent.operation_id, "FAILED",
                                                     error=type(exc).__name__))
        if previous is not None:
            return DispatchOutcome(previous, previous.evidence.get("payload"), duplicate=True)
        context = self.physical_context(intent)
        payload: Any = None
        try:
            invocation = context.run_async(effect)
            payload = await asyncio.wait_for(invocation, timeout) if timeout is not None else await invocation
            final = await self.decision(intent)
            if not final.allowed:
                result = OperationResult(intent.operation_id, "UNCERTAIN",
                                         error="grant revoked after transport dispatch")
                payload = None
            elif isinstance(payload, OperationResult):
                if payload.operation_id != intent.operation_id:
                    raise ValueError("provider result identity mismatch")
                result = payload
                payload = dict(result.evidence)
            else:
                failed = isinstance(payload, Mapping) and payload.get("isError") is True
                result = OperationResult(intent.operation_id, "FAILED" if failed else "SUCCEEDED",
                                         {"payload": payload},
                                         "provider returned error" if failed else None)
        except asyncio.CancelledError:
            try:
                await self.journal.finish(intent, OperationResult(
                    intent.operation_id, "UNCERTAIN", error="transport cancelled; completion unknown"))
            finally:
                raise
        except EffectRejected:
            result = OperationResult(intent.operation_id, "FAILED", error="local provider admission rejected")
        except Exception:
            result = OperationResult(intent.operation_id, "UNCERTAIN",
                                     error="transport completion requires reconciliation")
        try:
            await self.journal.finish(intent, result)
        except Exception:
            return DispatchOutcome(OperationResult(intent.operation_id, "UNCERTAIN",
                                                     error="central result acknowledgement unavailable"))
        return DispatchOutcome(result, payload)
