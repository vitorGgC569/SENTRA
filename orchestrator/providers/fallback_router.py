"""Honest degraded fallback for a dead Edge/extension path.

DegradedFallbackRouter wraps a primary provider (normally the browser
extension) and an optional weak fallback (normally a local model). On a
primary failure it consults orchestrator/providers/degradation.py:

- dead-path errors (exact DEAD_PATH_MARKERS list) may try the fallback
  AT MOST ONCE per execute() call, and the fallback answer is always
  labeled metadata {degraded: True, original_error} via mark_degraded;
- content/quality, uncertain-delivery, and blocked/quota errors never
  touch the fallback (returned as-is for repair/reconcile);
- a DeadPathBudget caps consecutive dead-path hits; once the ceiling is
  reached the router aborts fast with [DEAD_PATH_BUDGET] instead of
  attempting another fallback;
- asyncio.CancelledError always propagates (never swallowed).

No network or model calls here: this class only delegates to the injected
providers, so unit tests use fakes. Loopback availability probing lives in
LocalModelProvider.probe. Operator opt-in is allow_degrade (proposed
config: routing.degraded_fallback: null | "local"; default null preserves
today's no-unexpected-switch behavior).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from .base import AgentRequest, AgentResponse
from .degradation import (
    DEGRADE_ONCE,
    DeadPathBudget,
    decide,
    is_dead_path,
    mark_degraded,
)


class DegradedFallbackRouter:
    """Primary-then-at-most-one-degraded-attempt wrapper (not a ModelRouter)."""

    def __init__(
        self,
        primary: Any,
        fallback: Optional[Any] = None,
        budget: Optional[DeadPathBudget] = None,
        allow_degrade: bool = True,
    ):
        if primary is None:
            raise ValueError("primary provider is required")
        self.primary = primary
        self.fallback = fallback
        self.budget = budget if budget is not None else DeadPathBudget()
        self.allow_degrade = bool(allow_degrade)

    @property
    def consecutive_dead_path(self) -> int:
        return self.budget.consecutive_dead_path

    async def execute(self, request: AgentRequest) -> AgentResponse:
        try:
            primary_response = await self.primary.execute(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            primary_response = AgentResponse(
                content="",
                success=False,
                error=f"[PROVIDER_ERROR] primary: {exc}",
                metadata={},
            )

        if getattr(primary_response, "success", False):
            self.budget.record_success()
            return primary_response

        original_error = getattr(primary_response, "error", None) or ""
        metadata = getattr(primary_response, "metadata", None) or {}
        dead_signal = is_dead_path(original_error)

        action = decide(original_error, metadata)
        can_try_fallback = (
            action == DEGRADE_ONCE
            and self.allow_degrade
            and self.fallback is not None
            and self.fallback is not self.primary
        )
        if not can_try_fallback:
            if dead_signal:
                self.budget.record_dead_path()
            return primary_response

        if self.budget.should_abort():
            return AgentResponse(
                content="",
                success=False,
                error=f"[DEAD_PATH_BUDGET] consecutive dead-path ceiling "
                f"({self.budget.consecutive_dead_path}/"
                f"{self.budget.max_consecutive_dead_path}) reached; "
                f"operator reconcile required: {original_error}",
                metadata={
                    "degraded": False,
                    "degraded_attempt": "budget-ceiling",
                    "original_error": str(original_error),
                },
            )

        try:
            fallback_response = await self.fallback.execute(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.budget.record_dead_path()
            return AgentResponse(
                content="",
                success=False,
                error=str(original_error),
                metadata={
                    "degraded_attempt": "fallback-failed",
                    "fallback_error": f"{type(exc).__name__}: {exc}",
                    "original_error": str(original_error),
                },
            )

        if getattr(fallback_response, "success", False):
            # Weak-model success still means the Edge path is dead: count it
            # so endless degraded runs trip the ceiling and surface.
            mark_degraded(fallback_response, original_error)
            self.budget.record_degraded()
            return fallback_response

        # Fallback also failed: surface the primary dead-path error honestly
        # and keep both errors for forensics; never launder the fallback text.
        self.budget.record_dead_path()
        try:
            merged = dict(getattr(fallback_response, "metadata", None) or {})
        except Exception:
            merged = {}
        merged.update({
            "degraded_attempt": "fallback-failed",
            "fallback_error": str(getattr(fallback_response, "error", "")),
            "original_error": str(original_error),
        })
        return AgentResponse(
            content="",
            success=False,
            error=str(original_error),
            metadata=merged,
        )


__all__ = ["DegradedFallbackRouter"]
