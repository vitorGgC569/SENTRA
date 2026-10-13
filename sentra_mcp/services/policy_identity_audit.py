"""Selo: Policy/Identity/Audit service facade for central composition.

Codex (owner of server.py / service.py composition) instantiates this with
the real AuthorizationService and host-provided veto callables bound to
sentra_runtime providers (OPA/OpenFGA/Keycloak/SPIRE). This module performs
no network I/O itself; vetos are injected callables so unit composition can
be tested without external services.

Audit anchors (Tessera/immudb) are tracked in AuditAnchorStore; provider
verification stays in sentra_runtime providers injected as callables.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sentra_quality.policy_veto_chain import (
    PolicyVetoChain, PolicyVetoRequest, PolicyVetoResult, build_veto_request,
)
from sentra_quality.identity_registry import IdentityRegistry
from sentra_quality.audit_anchor import AuditAnchorStore


def build_client(**trusted_host_configuration):
    """Configured real-client composition; legacy local projections stay separate."""
    from .selo_composition import build_client as compose
    return compose(**trusted_host_configuration)


class PolicyIdentityAuditService:
    def __init__(self, state_root: Path | str, *,
                 authorization=None,
                 vetos: list[tuple[str, Callable[[PolicyVetoRequest], PolicyVetoResult]]] | None = None) -> None:
        self.root = Path(state_root).resolve()
        self.authorization = authorization
        self.chain = PolicyVetoChain(vetos)
        self.identities = IdentityRegistry(self.root)
        self.anchors = AuditAnchorStore(self.root)

    def authorize(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        """CorePDP authorize + deny-only vetos. Fail-closed throughout."""
        if self.authorization is None:
            raise RuntimeError("authorization service not composed")
        return self.authorization.authorize_with_vetos(owner, vetos=self.chain, **{k: v for k, v in kwargs.items()
            if k in {"principal_type", "principal_id", "capability", "scope_type",
                     "scope_id", "ancestors", "context", "local_owner"}})

    def require(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        decision = self.authorize(owner, **kwargs)
        if not decision.get("allowed"):
            raise PermissionError("authorization denied: " + str(decision.get("reason", ""))[:300])
        return decision

    # Identity projections (never grants).
    def register_oidc(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.identities.register_oidc(owner, **kwargs)

    def register_spiffe(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.identities.register_spiffe(owner, **kwargs)

    def session_begin(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.identities.session_begin(owner, **kwargs)

    def session_invalidate(self, owner: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.identities.session_invalidate(owner, *args, **kwargs)

    def session_status(self, owner: str, session_id: str) -> dict[str, Any]:
        return self.identities.session_status(owner, session_id)

    # Audit anchors.
    def anchor_initialize(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.initialize_trust(owner, **kwargs)

    def anchor_head(self, owner: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.anchors.head(owner, **kwargs)

    def anchor_advance(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.advance(owner, **kwargs)

    def anchor_divergence(self, owner: str, **kwargs: Any) -> int:
        return self.anchors.record_divergence(owner, **kwargs)

    def anchor_divergences(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.divergences(owner, **kwargs)

    # Verifier trust, witnesses, effect coverage (REE-24/25).
    def trust_save(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.save_trust_state(owner, **kwargs)

    def trust_get(self, owner: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.anchors.trust_state(owner, **kwargs)

    def trust_verify(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.verify_against_trust(owner, **kwargs)

    def witness_set(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.witness_set(owner, **kwargs)

    def witness_check(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.witness_check(owner, **kwargs)

    def coverage_set(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.set_effect_coverage(owner, **kwargs)

    def coverage_report(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.anchors.coverage_report(owner, **kwargs)
