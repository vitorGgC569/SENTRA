"""Dead-path decision matrix and budget clock for Edge/extension outages.

When the Edge/extension path dies (tabs drop, lease expires, no worker
ever polls), a live run must not die silently nor burn budget forever.
This module is the single source of truth for:

- which extension errors mean "dead path" (infra, safe to degrade once)
  versus "normal failure" (content/quality/uncertain, never degrade);
- what to do per error: retry / reconcile / abort / degrade_once;
- how many consecutive dead-path hits are tolerated before aborting
  fast (DeadPathBudget);
- how to label a weak-model answer honestly (mark_degraded).

Pure logic only: no network, no Edge, no ChatGPT, no local-model calls.
Live availability is probed elsewhere (LocalModelProvider.probe, read-only
GET of a local version endpoint). Tests inject fake providers only.

Dead-path markers (exact substrings, case-insensitive):
  - "no extension connected": ExtensionTransport._wait_first_worker,
    raised BEFORE submit when workers_ever_seen == 0 and no worker is
    online. Nothing was sent. Proof: browser/extension_transport.py.
  - "LEASE_LOST": edge_extension/service-worker.js pre-send check
    (leaseLost before SEND_MESSAGE). Degradable only when delivery
    metadata does not say UNCERTAIN/BLOCKED.
  - "LEASE_EXPIRED": relay lease expiry (native_bridge/job_store.py).
    Same metadata guard as LEASE_LOST.
  - "TAB_STALE": content-script obsolete, tab must be recycled
    (edge_extension/service-worker.js). Single tab; N in a row with the
    budget clock means the whole path is dead.
  - "TAB_ERROR": tab vanished / navigation never completed / composer
    never answered (service-worker.js). Same N-in-a-row rule.

NEVER degrade on content/quality or uncertain delivery. A weak model
labeled as strong is a hard failure of this solution. See VALIDATOR_RULE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


# Action vocabulary returned by decide(). Stable strings, never renamed.
RETRY = "retry"
RECONCILE = "reconcile"
ABORT = "abort"
DEGRADE_ONCE = "degrade_once"

ACTIONS = (RETRY, RECONCILE, ABORT, DEGRADE_ONCE)

# Exact dead-path signal list. Keep narrow: adding a marker here authorizes
# a degraded local attempt, so every entry needs a code reference above.
DEAD_PATH_MARKERS = (
    "no extension connected",
    "LEASE_LOST",
    "LEASE_EXPIRED",
    "TAB_STALE",
    "TAB_ERROR",
)

# Uncertain delivery: a send may already have happened. Never replay and
# never degrade silently; the operator reconciles (orchestrator/reconcile.py).
UNCERTAIN_MARKERS = (
    "DELIVERY_UNCERTAIN",
    "SUBMISSION_UNCERTAIN",
    "DELIVERY_EXPIRED",
)

# Blocked/quota/pairing: another account or operator action is required.
# Retrying or degrading would burn budget to fail identically.
BLOCKED_MARKERS = (
    "ACCOUNT_LIMIT",
    "RATE_LIMIT",
    "QUOTA_EXCEEDED",
    "CONVERSATION_BLOCKED",
    "PAIRING_REQUIRED",
    "relay pairing required",
    "pairing token required",
    "RELAY_HTTP_401",
    "RELAY_HTTP_403",
    "forbidden origin",
    "invalid host",
)

# Content / integrity / quality failures: the model or prompt is at fault,
# not the transport. They go to the normal repair/validator path (abort
# here means "return the primary error, no fallback, no infra retry").
# This list is illustrative, not exhaustive: unknown errors also abort.
CONTENT_MARKERS = (
    "CONVERSATION_MISMATCH",
    "PROMPT_MISMATCH",
    "FILL_FAILED",
    "CLEAR_FAILED",
    "STALE_DRAFT",
    "IMAGE_ERROR",
    "IMAGE_VERSION",
    "CONTEXT_BUDGET",
    "DEPENDENCY_ERROR",
    "MODEL_INCOMPLETE",
    "PATCH_SYNTAX",
    "BUDGET_EXCEEDED",
    "POLICY_ERROR",
    "OPENAI_ERROR",
)

# Generic transient delivery markers that deserve the engine's existing
# exponential-backoff retry, not a degraded fallback.
TRANSIENT_RETRY_MARKERS = (
    "TIMEOUT",
    "TIMED OUT",
    "IN_FLIGHT",
    "SUBMIT_FAILED",
    "STALE_CONVERSATION",
)

# Suggested validator rule for degraded evidence (spec, not enforcement here;
# validators live in another workstream). A degraded answer is weak evidence:
# cap confidence/score, never let it satisfy quorum alone, require objective
# test output, and surface the degraded flag in reports.
VALIDATOR_RULE = (
    "Treat response.metadata['degraded'] is True as weak evidence: "
    "cap confidence at 0.5 and critic score at 6.0, exclude it from "
    "minimum_approvals quorum by itself, require at least one passing "
    "objective test ([[TEST|all]] or profile) for promotion, and record "
    "original_error in the ValidationReport summary. Never present a "
    "degraded answer as a strong-model verdict."
)


def _upper(text: Any) -> str:
    return str(text or "").upper()


def _contains_any(error: Any, markers) -> bool:
    text = _upper(error)
    return any(m.upper() in text for m in markers)


def is_dead_path(error: Any) -> bool:
    """Raw dead-path signal: True when error carries a DEAD_PATH_MARKERS code.

    No metadata guard here; use decide() for the guarded action. Content or
    quality prose without one of these exact codes is never dead-path.
    """
    return _contains_any(error, DEAD_PATH_MARKERS)


def _metadata_forbids_replay(metadata: Optional[Mapping[str, Any]]) -> bool:
    """True when metadata marks an uncertain/blocked external side effect.

    Mirrors orchestrator/agents/router.py: retry_safe is False or
    delivery_state in {UNCERTAIN, BLOCKED} means a replay (including a
    degraded fallback that re-asks) could double-send or hide a delivery.
    """
    if not metadata:
        return False
    try:
        if metadata.get("retry_safe") is False:
            return True
        if metadata.get("delivery_state") in {"UNCERTAIN", "BLOCKED"}:
            return True
    except Exception:
        return False
    return False


def decide(error: Any, metadata: Optional[Mapping[str, Any]] = None) -> str:
    """Map an extension failure to one action: retry/reconcile/abort/degrade_once.

    Order is load-bearing:
      1. "no extension connected" degrades once even though its metadata is
         UNCERTAIN/retry_safe False (browser/outcomes.py misclassifies this
         pre-submit failure; transport raises before any submit, so nothing
         was sent and degrading cannot double-send).
      2. Blocked/quota/pairing aborts fast (operator must fix).
      3. Unsafe metadata or uncertain-delivery markers reconcile (operator
         discards the ambiguous intent; never auto-replay, never degrade).
      4. Dead-path markers degrade once (single local attempt, honestly labeled).
      5. Transient markers retry via the engine backoff path.
      6. Everything else (content/quality/unknown) aborts to the normal
         repair/validator path without fallback.
    """
    text = str(error or "")
    upper = text.upper()

    # 1. Explicit pre-submit override: safe to degrade, cannot double-send.
    if "NO EXTENSION CONNECTED" in upper:
        return DEGRADE_ONCE

    # 2. Blocked/quota/pairing: diagnosis, not another account.
    if _contains_any(text, BLOCKED_MARKERS):
        return ABORT

    # 3. Uncertain external side effect: reconcile, never replay/degrade.
    if _metadata_forbids_replay(metadata):
        return RECONCILE
    if _contains_any(text, UNCERTAIN_MARKERS):
        return RECONCILE
    if "SUBMISSION_UNCERTAIN" in upper or "DELIVERY_EXPIRED" in upper:
        return RECONCILE

    # 4. Dead path: one honest degraded attempt at most (caller enforces).
    if _contains_any(text, DEAD_PATH_MARKERS):
        return DEGRADE_ONCE

    # 5. Transient delivery: engine retries with backoff.
    if _contains_any(text, TRANSIENT_RETRY_MARKERS):
        return RETRY

    # 6. Content/quality/unknown: fail fast to repair/validators, no fallback.
    return ABORT


@dataclass
class DeadPathBudget:
    """Consecutive dead-path counter with a ceiling.

    Increment on every raw dead-path hit (is_dead_path), reset only on a
    primary-path success. A degraded local success still counts as a
    dead-path hit: the Edge path is still dead and must not burn forever.
    When consecutive hits reach max_consecutive, the caller must abort fast
    and ask the operator to reconcile instead of attempting another fallback.
    """

    max_consecutive_dead_path: int = 3
    consecutive_dead_path: int = 0
    total_dead_path: int = 0
    total_degraded: int = 0

    def __post_init__(self) -> None:
        if (type(self.max_consecutive_dead_path) is not int
                or not 1 <= self.max_consecutive_dead_path <= 10):
            raise ValueError("max_consecutive_dead_path must be an int 1..10")

    def record_dead_path(self) -> bool:
        """Record one dead-path hit. Returns True when the ceiling is reached."""
        self.consecutive_dead_path += 1
        self.total_dead_path += 1
        return self.should_abort()

    def record_degraded(self) -> bool:
        """Record a degraded fallback success (path still dead)."""
        self.total_degraded += 1
        return self.record_dead_path()

    def record_success(self) -> None:
        """Primary-path success: the path healed, reset the streak."""
        self.consecutive_dead_path = 0

    def should_abort(self) -> bool:
        return self.consecutive_dead_path >= self.max_consecutive_dead_path

    def reset(self) -> None:
        self.consecutive_dead_path = 0
        self.total_dead_path = 0
        self.total_degraded = 0


def mark_degraded(response: Any, original_error: Any) -> Any:
    """Label a fallback answer as weak evidence, in place, and return it.

    Sets metadata {degraded: True, original_error, degraded_reason} without
    touching content/model, so engine and validators can see the answer came
    from a weak model. First original_error wins when already degraded.
    """
    try:
        metadata = dict(getattr(response, "metadata", None) or {})
    except Exception:
        metadata = {}
    metadata["degraded"] = True
    if "original_error" not in metadata:
        metadata["original_error"] = str(original_error or "")
    metadata.setdefault("degraded_reason", "dead-path-fallback")
    try:
        response.metadata = metadata
    except Exception:
        pass
    return response
