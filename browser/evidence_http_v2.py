"""SENTRA browser-evidence V2 schema adapter for an ALREADY authenticated relay.

This is NOT an HTTP server, authority, bearer validator or account attestation.
Call from the existing relay only after _authorized, exact extension origin,
source hash/build enrollment and worker binding checks. No Web send or grant.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sentra_mcp.services.browser_evidence import BrowserEvidenceService

CHALLENGE = "/browser-evidence/challenge"
OBSERVE = "/browser-evidence/observe"
INVALIDATE = "/browser-evidence/invalidate"

_ALLOWED = {
    CHALLENGE: frozenset({"source_sha256", "worker", "document_id", "identity_epoch"}),
    OBSERVE: frozenset({"source_sha256", "worker", "evidence"}),
    INVALIDATE: frozenset({"source_sha256", "worker", "document_id", "identity_epoch", "reason"}),
}
_EVIDENCE_KEYS = frozenset({
    "nonce", "document_id", "conversation_id", "route_conversation_id",
    "state", "requests", "identity_epoch",
})


def dispatch_authenticated_v2(*, service: BrowserEvidenceService, path: str,
                              payload: Mapping[str, Any],
                              extension_id: str, source_sha256: str,
                              worker: str,
                              authorized_worker: Callable[[str, str], bool]) -> dict[str, Any]:
    """Route a V2-only request; caller MUST prove collector BEFORE this call.

    Only the relay supplies extension_id/source_sha256/worker after validating
    origin, local bearer, registered source build and worker ownership.
    Untrusted payload is checked for exact equality; never use payload account,
    model, page DOM or a supplied extension_id for authentication.
    """
    if path not in _ALLOWED:
        raise ValueError("unsupported browser evidence V2 route")
    if not isinstance(payload, dict) or frozenset(payload) != _ALLOWED[path]:
        raise ValueError("exact browser evidence V2 envelope required")
    if payload["source_sha256"] != source_sha256 or payload["worker"] != worker:
        raise PermissionError("authenticated browser collector binding changed")
    # _browser_collector() alone reads the worker from CLIENT JSON in the
    # current relay. That is not proof of tab/lease ownership. Require an
    # independent host-side worker registration/ownership predicate.
    if not callable(authorized_worker) or (
            authorized_worker(extension_id, worker) is not True):
        raise PermissionError("browser worker has no verified host ownership")
    kwargs = {"extension_id": extension_id, "source_sha256": source_sha256,
              "worker": worker}
    if path == CHALLENGE:
        if not isinstance(payload["identity_epoch"], str):
            raise ValueError("V2 identity epoch required")
        return service.challenge(
            **kwargs, document_id=payload["document_id"],
            identity_epoch=payload["identity_epoch"])
    if path == OBSERVE:
        evidence = payload["evidence"]
        if not isinstance(evidence, dict) or frozenset(evidence) != _EVIDENCE_KEYS:
            raise ValueError("exact V2 browser observation required")
        if not isinstance(evidence["identity_epoch"], str):
            raise ValueError("V2 observation epoch required")
        return service.observe(**kwargs, evidence=evidence)
    if not isinstance(payload["identity_epoch"], str):
        raise ValueError("V2 invalidation epoch required")
    return service.invalidate_document(
        **kwargs, document_id=payload["document_id"],
        identity_epoch=payload["identity_epoch"], reason=payload["reason"])
