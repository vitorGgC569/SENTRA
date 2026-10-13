"""Selo: fail-closed composition of CorePDP with external policy/identity vetos.

CorePDP (AuthorizationService) is the single authority. OPA, OpenFGA,
Keycloak session and SPIRE workload checks are *deny-only vetos*: they are
consulted only after a CorePDP allow, they preserve CorePDP constraints, and
any veto error, revision mismatch or unavailable provider denies.

This module defines no network clients. Concrete veto callables are injected
by the host (which owns sentra_runtime providers) with the signature::

    veto(request: PolicyVetoRequest) -> PolicyVetoResult

Identity authentication never creates grants. ListObjects-style discovery
never authorizes effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass(frozen=True, slots=True)
class PolicyVetoRequest:
    owner: str
    principal_type: str
    principal_id: str
    capability: str
    scope_type: str = "instance"
    scope_id: str | None = None
    operation_id: str | None = None
    work_item_id: str | None = None
    workspace_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyVetoResult:
    allowed: bool
    provider: str
    reason: str
    revision: str | None = None
    decision_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise ValueError("veto allowed must be a boolean")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("veto provider name required")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("veto reason required")
        if self.revision is not None and (
            not isinstance(self.revision, str) or not self.revision.strip()
        ):
            raise ValueError("invalid veto revision")


VetoCallable = Callable[[PolicyVetoRequest], PolicyVetoResult]


def _sanitize_reason(reason: str) -> str:
    from sentra_core.telemetry import safe_text
    text = safe_text(str(reason or ""), 500).replace("\r", " ").replace("\n", " ")
    return text[:500] if text else "veto decision"


class PolicyVetoChain:
    """Ordered deny-only veto chain over a prior CorePDP allow."""

    def __init__(self, vetos: Sequence[tuple[str, VetoCallable]] | None = None) -> None:
        self._vetos: list[tuple[str, VetoCallable]] = []
        for entry in vetos or []:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 2
                or not isinstance(entry[0], str)
                or not entry[0].strip()
                or not callable(entry[1])
            ):
                raise ValueError("veto chain entries must be (name, callable)")
            self._vetos.append((entry[0].strip(), entry[1]))

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._vetos)

    def evaluate(
        self,
        request: PolicyVetoRequest,
        *,
        core_allowed: bool,
        core_reason: str = "",
        core_constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate vetos after a CorePDP decision. Fail-closed on any doubt."""
        if not isinstance(request, PolicyVetoRequest):
            raise ValueError("typed veto request required")
        constraints = dict(core_constraints or {})
        if core_allowed is not True:
            return {
                "allowed": False,
                "source": "core_pdp",
                "reason": str(core_reason or "core policy denied")[:500],
                "vetos": [],
                "constraints": constraints,
            }
        evaluated: list[dict[str, Any]] = []
        for name, veto in self._vetos:
            try:
                result = veto(request)
            except Exception as exc:  # fail closed: veto failure denies
                return {
                    "allowed": False,
                    "source": "veto:" + name,
                    "reason": f"veto {name} unavailable",
                    "vetos": evaluated,
                    "constraints": constraints,
                }
            if not isinstance(result, PolicyVetoResult) or result.provider != name:
                return {
                    "allowed": False,
                    "source": "veto:" + name,
                    "reason": f"veto {name} returned untyped result",
                    "vetos": evaluated,
                    "constraints": constraints,
                }
            evaluated.append({
                "provider": result.provider,
                "allowed": bool(result.allowed),
                "reason": _sanitize_reason(result.reason),
                "revision": result.revision,
                "decision_id": result.decision_id,
            })
            if not result.allowed:
                return {
                    "allowed": False,
                    "source": "veto:" + name,
                    "reason": _sanitize_reason(result.reason),
                    "vetos": evaluated,
                    "constraints": constraints,
                }
        return {
            "allowed": True,
            "source": "core_pdp+vetos",
            "reason": str(core_reason or "core allow, vetos passed")[:500],
            "vetos": evaluated,
            "constraints": constraints,
        }


def build_veto_request(
    owner: str,
    *,
    principal_type: str,
    principal_id: str,
    capability: str,
    scope_type: str = "instance",
    scope_id: str | None = None,
    operation_id: str | None = None,
    work_item_id: str | None = None,
    workspace_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> PolicyVetoRequest:
    if not str(owner or "").strip():
        raise ValueError("owner is required")
    if not str(principal_id or "").strip():
        raise ValueError("principal_id is required")
    if not str(capability or "").strip():
        raise ValueError("capability is required")
    return PolicyVetoRequest(
        owner=str(owner),
        principal_type=str(principal_type or "").lower() or "agent",
        principal_id=str(principal_id),
        capability=str(capability),
        scope_type=str(scope_type or "instance").lower(),
        scope_id=scope_id,
        operation_id=operation_id,
        work_item_id=work_item_id,
        workspace_id=workspace_id,
        context=dict(context or {}),
    )
