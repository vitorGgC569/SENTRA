"""Secondary, deny-by-default authorization for reading/controlling an operation.

Intended for integration into the SENTRA HTTP/MCP/Web gateways; the low-level
ExecutorRegistry methods remain INTERNAL and must not be bound to public routes.
The existing durable AuthorizationService is the authority, injected here.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from typing import Awaitable, Callable

from .contracts import OperationResult, PolicyDecision
from .executor import AuthorizationRequired, ExecutorRegistry, InvalidOperation


@dataclass(frozen=True, slots=True)
class OperationAccess:
    """Authenticated caller intent plus scope of the original operation."""

    principal_id: str
    action: str
    operation_id: str
    machine_id: str
    owner_principal_id: str
    work_item_id: str
    capability_id: str

    def __post_init__(self) -> None:
        if self.action not in {"observe", "reconcile", "cancel", "cleanup"}:
            raise InvalidOperation("unsupported operation access action")
        for key in ("principal_id", "operation_id", "machine_id",
                    "owner_principal_id", "work_item_id", "capability_id"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise InvalidOperation(f"invalid operation access identity: {key}")


AccessChecker = Callable[[OperationAccess], PolicyDecision | Awaitable[PolicyDecision]]


class AuthorizedOperationGateway:
    """Public-facing adapter: grant is revalidated for *each* operation action."""

    def __init__(self, registry: ExecutorRegistry,
                 authorize_access: AccessChecker | None,
                 *, policy_timeout_s: float = 5.0) -> None:
        if not 0 < policy_timeout_s <= 60:
            raise ValueError("invalid policy timeout")
        self._registry = registry
        self._authorize = authorize_access
        self._policy_timeout = policy_timeout_s

    async def perform(self, *, principal_id: str, operation_id: str,
                      action: str) -> OperationResult | None:
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise AuthorizationRequired("authenticated principal required")
        if action not in {"observe", "reconcile", "cancel", "cleanup"}:
            raise InvalidOperation("invalid operation access action")
        # Original request is ONLY used inside the trusted adapter to build
        # the policy input; no field is returned until fresh authorization.
        original = self._registry.operation_request(operation_id)
        grant = OperationAccess(
            principal_id=principal_id,
            action=action,
            operation_id=operation_id,
            machine_id=original.machine_id,
            owner_principal_id=original.principal_id,
            work_item_id=original.work_item_id,
            capability_id=original.capability_id,
        )
        if self._authorize is None:
            raise AuthorizationRequired("operation access policy missing")
        try:
            decision = self._authorize(grant)
            if inspect.isawaitable(decision):
                decision = await asyncio.wait_for(decision, self._policy_timeout)
        except Exception as exc:
            raise AuthorizationRequired("operation access policy failed closed") from exc
        if not isinstance(decision, PolicyDecision) or not decision.allowed:
            raise AuthorizationRequired("operation access denied")
        # This generic gateway has no implementation for narrowing e.g.
        # redacted output fields or partial cancellation; reject constraints.
        if decision.constraints:
            raise AuthorizationRequired("constrained operation access is unsupported")
        method = getattr(self._registry, action)
        return await method(operation_id)
