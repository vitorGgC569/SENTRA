"""Opt-in fail-closed bridge from SENTRA WorkItems/grants to ExecutorRegistry.

Uses the EXISTING durable AuthorizationService and GovernanceService as the
authority. This is deliberately a small policy adapter, not a new grant store.

This check is only admission-time and is NOT sufficient for long-lived
revocation, atomic creation of external effects, leases, process sandboxing,
or cross-process idempotency. Production callers must also implement durable
operation reservation/fencing and reauthorization on later commands.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import math
from typing import Any, Protocol

from .contracts import OperationRequest, PolicyDecision


class _AuthorizationAuthority(Protocol):
    def authorize(
        self, owner: str, *, principal_type: str, principal_id: str,
        capability: str, scope_type: str, scope_id: str,
        context: dict[str, Any], local_owner: bool = False,
    ) -> Mapping[str, Any]: ...


class _GovernanceAuthority(Protocol):
    def work_item_info(self, work_item_id: str, owner: str) -> Mapping[str, Any]: ...


class BoundWorkItemPolicy:
    """Bind a trusted SENTRA owner/principal type to an executor admission.

    Never derive owner, principal type, cost or workspace ancestry from
    request.arguments (which an agent or tool could manufacture).
    """

    def __init__(
        self,
        *,
        owner: str,
        principal_type: str,
        authorization: _AuthorizationAuthority,
        governance: _GovernanceAuthority,
        trusted_context: Callable[[OperationRequest], Mapping[str, Any]] | None = None,
    ) -> None:
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("authenticated owner required")
        if principal_type not in {"agent", "user", "plugin", "device", "service"}:
            raise ValueError("trusted principal type required")
        self.owner = owner
        self.principal_type = principal_type
        self.authorization = authorization
        self.governance = governance
        self.trusted_context = trusted_context

    def __call__(self, request: OperationRequest) -> PolicyDecision:
        try:
            # The owner-scoped governance read is critical. An agent cannot
            # invent a work_item_id and inherit an instance-wide grant.
            item = self.governance.work_item_info(request.work_item_id, self.owner)
            if not isinstance(item, Mapping) or item.get("owner") != self.owner:
                return PolicyDecision(False, "work item owner mismatch")
            if str(item.get("state")) != "RUNNING":
                return PolicyDecision(False, "work item is not in RUNNING state")
            assigned_field = (
                "assignee_agent_id" if self.principal_type == "agent"
                else "assignee_user_id" if self.principal_type == "user" else None
            )
            if assigned_field and item.get(assigned_field) not in (None, "", request.principal_id):
                return PolicyDecision(False, "work item assigned to another principal")
            required = item.get("required_capabilities")
            if required:
                if not isinstance(required, (list, tuple)) or request.capability_id not in required:
                    return PolicyDecision(False, "capability not in work item requirements")

            # A missing cost estimate must never satisfy max_actual_cost by
            # being silently treated as zero. The existing evaluator checks
            # explicit cost constraints against actual_cost in the context.
            context: dict[str, Any] = {"actual_cost": float("inf")}
            if self.trusted_context is not None:
                trusted = self.trusted_context(request)
                if not isinstance(trusted, Mapping):
                    return PolicyDecision(False, "trusted context unavailable")
                context.update(dict(trusted))
            cost = context.get("actual_cost")
            if type(cost) not in (int, float) or math.isnan(cost) or cost < 0:
                return PolicyDecision(False, "invalid trusted cost estimate")
            # The existing AuthorizationService reads owner-scoped, persisted
            # ancestors and logs decisions. Never provide caller ancestors or
            # enable the convenient local_owner shortcut in an agent executor.
            result = self.authorization.authorize(
                self.owner,
                principal_type=self.principal_type,
                principal_id=request.principal_id,
                capability=request.capability_id,
                scope_type="work_item",
                scope_id=request.work_item_id,
                context=context,
                local_owner=False,
            )
            if not isinstance(result, Mapping) or result.get("allowed") is not True:
                return PolicyDecision(False, "SENTRA grant missing, expired, or revoked")
            return PolicyDecision(True, "SENTRA durable grant accepted")
        except Exception:
            # This is intentionally generic. Never leak conditions, principal
            # existence, identities, tokens or store details through errors.
            return PolicyDecision(False, "SENTRA authority unavailable")
