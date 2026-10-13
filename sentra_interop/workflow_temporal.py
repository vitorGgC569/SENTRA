"""Temporal retry/update semantics mapped onto SENTRA subordinate workflows.

NOT a Temporal server, worker deployment or operations authority. This module
ports the exact retry classification, backoff, expiration and
admitted-versus-completed update semantics inspected in the pinned Temporal
clone (``service/history/workflow/retry.go``,
``common/retrypolicy/retry_policy.go``,
``service/history/workflow/update/registry.go``) onto
:class:`RetryPolicy`/:class:`ActivityReceipt` from ``workflow_contracts``.

Every effect still requires a distinct admitted central operation through
``CheckpointedWorkflowWorker``; UNCERTAIN outcomes never produce another
attempt of the effect.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .workflow_contracts import ActivityReceipt, RetryPolicy

# Failure types that Temporal treats as non-retryable application outcomes.
# Mapped here so a confirmed terminal provider result cannot be re-driven
# into a new attempt by the worker.
TERMINAL_APPLICATION_TYPES = frozenset({
    "APPLICATION_PERMANENT",
    "ACCEPTANCE_FAILED",
    "VALIDATION_FAILED",
    "SIGNAL_EXPIRED",
    "SUBFLOW_STOPPED",
    "WORKFLOW_STOPPED",
})

# Timeout types observed while the effect state is still UNKNOWN. These mark
# the attempt UNCERTAIN (loss of observation) instead of FAILED+NOT_STARTED,
# so no automatic attempt follows.
AMBIGUOUS_TIMEOUT_TYPES = frozenset({
    "HEARTBEAT_TIMEOUT_UNKNOWN_EFFECT",
    "TRANSPORT_LOST_AFTER_DISPATCH",
    "SCHEDULE_TO_CLOSE_UNKNOWN",
})


def classify_temporal_failure(*, failure_type: str | None,
                              effect_state: str) -> str:
    """Return one of RETRYABLE / TERMINAL / UNCERTAIN for a provider outcome."""
    if effect_state == "UNKNOWN":
        return "UNCERTAIN"
    if not isinstance(failure_type, str) or not failure_type:
        return "TERMINAL"
    if failure_type in AMBIGUOUS_TIMEOUT_TYPES:
        return "UNCERTAIN"
    if failure_type in TERMINAL_APPLICATION_TYPES:
        return "TERMINAL"
    return "RETRYABLE"


@dataclass(frozen=True)
class TemporalRetryPolicy:
    """Bounded Temporal-style retry envelope around :class:`RetryPolicy`.

    ``max_attempts`` includes the first attempt. ``expiration_seconds`` caps
    the schedule measured from the first attempt start. Backoff is
    ``initial * coefficient**(n-1)`` capped at ``maximum_seconds``.
    """

    max_attempts: int = 3
    initial_seconds: float = 1.0
    maximum_seconds: float = 60.0
    coefficient: float = 2.0
    expiration_seconds: float = 3600.0
    non_retryable_types: tuple[str, ...] = tuple(sorted(TERMINAL_APPLICATION_TYPES))

    def __post_init__(self):
        if (type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100
                or any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0
                       for x in (self.initial_seconds, self.maximum_seconds,
                                 self.coefficient, self.expiration_seconds))
                or self.coefficient < 1
                or self.initial_seconds > self.maximum_seconds):
            raise ValueError("invalid bounded Temporal retry envelope")
        object.__setattr__(self, "non_retryable_types", tuple(self.non_retryable_types))

    def to_retry_policy(self) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=self.max_attempts,
            initial_seconds=self.initial_seconds,
            maximum_seconds=self.maximum_seconds,
            coefficient=self.coefficient,
            expiration_seconds=self.expiration_seconds,
            retryable_types=("DEPENDENCY_UNAVAILABLE", "RESOURCE_BUSY_BEFORE_START",
                             "RATE_LIMITED_BEFORE_START", "TEMPORAL_RETRYABLE"),
        )

    def next_attempt_at(self, receipt: ActivityReceipt, *, attempt: int,
                        first_started: float, now: float) -> float | None:
        """Schedule the next attempt or return None when it must not run."""
        if (receipt.status != "FAILED" or receipt.effect_state != "NOT_STARTED"):
            return None
        verdict = classify_temporal_failure(
            failure_type=receipt.failure_type, effect_state=receipt.effect_state)
        if verdict != "RETRYABLE":
            return None
        if (receipt.failure_type in self.non_retryable_types
                or not receipt.retryable or attempt >= self.max_attempts):
            return None
        delay = self.initial_seconds
        for _ in range(attempt - 1):
            delay = min(self.maximum_seconds, delay * self.coefficient)
        scheduled = now + delay
        if scheduled > first_started + self.expiration_seconds:
            return None
        return scheduled


class TemporalUpdateLedger:
    """Admitted-versus-completed update tracking as a local projection.

    Mirrors the Temporal update registry distinction: an update (signal with
    response, activity re-drive decision) is ADMITTED when the central
    operation journal accepts it and COMPLETED only after the acknowledged
    receipt. This ledger references central operation IDs; it cannot admit,
    complete or replay an operation itself.
    """

    def __init__(self) -> None:
        self._updates: dict[str, dict[str, Any]] = {}

    def admit(self, *, update_id: str, operation_id: str,
              workflow_id: str, ns: str = "") -> dict[str, Any]:
        if not isinstance(update_id, str) or not update_id:
            raise ValueError("bounded update identity required")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("central operation identity required")
        existing = self._updates.get(update_id)
        if existing is not None:
            if existing["operation_id"] != operation_id:
                raise ValueError("update already admitted under another operation")
            return dict(existing)
        record = {"update_id": update_id, "operation_id": operation_id,
                  "workflow_id": workflow_id, "namespace": ns,
                  "phase": "ADMITTED"}
        self._updates[update_id] = record
        return dict(record)

    def complete(self, update_id: str, *, operation_id: str,
                 outcome: str) -> dict[str, Any]:
        record = self._updates.get(update_id)
        if record is None:
            raise FileNotFoundError("unknown Temporal-style update")
        if record["operation_id"] != operation_id:
            raise ValueError("completion references another operation")
        if record["phase"] != "ADMITTED":
            raise ValueError("update is not in an admitted phase")
        if outcome not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ValueError("invalid update outcome")
        record = {**record, "phase": "COMPLETED", "outcome": outcome}
        self._updates[update_id] = record
        return dict(record)

    def get(self, update_id: str) -> dict[str, Any] | None:
        record = self._updates.get(update_id)
        return dict(record) if record is not None else None
