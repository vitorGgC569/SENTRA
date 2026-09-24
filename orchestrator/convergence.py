"""Deterministic convergence policy for autonomous SENTRA/OMA runs.

The policy decides when continued work is no longer justified by runtime
signals. It never asks an LLM whether a run should stop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConvergenceDecision:
    stop: bool
    code: str = "CONTINUE"
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class ConvergencePolicy:
    def __init__(
        self,
        *,
        max_rounds: int,
        no_progress_limit: int,
        min_marginal_gain: float = 0.0,
        low_gain_patience: int = 3,
        speculative_limit: int = 0,
        stop_on_human_required: bool = True,
        stop_on_budget_exhausted: bool = True,
    ) -> None:
        if max_rounds <= 0 or no_progress_limit <= 0:
            raise ValueError("convergence hard limits must be positive")
        if not 0.0 <= float(min_marginal_gain) <= 1.0:
            raise ValueError("min_marginal_gain must be between 0 and 1")
        if low_gain_patience <= 0:
            raise ValueError("low_gain_patience must be positive")
        if speculative_limit < 0:
            raise ValueError("speculative_limit must be non-negative")
        self.max_rounds = int(max_rounds)
        self.no_progress_limit = int(no_progress_limit)
        self.min_marginal_gain = float(min_marginal_gain)
        self.low_gain_patience = int(low_gain_patience)
        self.speculative_limit = int(speculative_limit)
        self.stop_on_human_required = bool(stop_on_human_required)
        self.stop_on_budget_exhausted = bool(stop_on_budget_exhausted)
        self.low_gain_rounds = 0
        self.speculative_rounds = 0

    def evaluate(
        self,
        *,
        objective_satisfied: bool,
        dispatched: int,
        pending_work: bool,
        ready_work: bool,
        in_flight: bool,
        no_progress_rounds: int,
        marginal_gain: float | None = None,
        budget_exhausted: bool = False,
        speculative_only: bool = False,
        requires_human: bool = False,
    ) -> ConvergenceDecision:
        details = {
            "dispatched": int(dispatched),
            "max_rounds": self.max_rounds,
            "no_progress_rounds": int(no_progress_rounds),
            "no_progress_limit": self.no_progress_limit,
            "in_flight": bool(in_flight),
            "marginal_gain": marginal_gain,
            "min_marginal_gain": self.min_marginal_gain,
            "budget_exhausted": bool(budget_exhausted),
            "speculative_only": bool(speculative_only),
            "requires_human": bool(requires_human),
        }

        if objective_satisfied:
            return ConvergenceDecision(
                True, "OBJECTIVE_SATISFIED",
                "all planned work completed under the runtime gates", details,
            )

        if self.stop_on_human_required and requires_human and not in_flight:
            return ConvergenceDecision(
                True, "HUMAN_DECISION_REQUIRED",
                "remaining work contains an explicit human-decision boundary", details,
            )

        if self.stop_on_budget_exhausted and budget_exhausted and pending_work and not in_flight:
            return ConvergenceDecision(
                True, "BUDGET_EXHAUSTED",
                "admission budget is exhausted while work remains", details,
            )

        if dispatched >= self.max_rounds and pending_work and not in_flight:
            return ConvergenceDecision(
                True, "DISPATCH_LIMIT",
                "maximum task dispatch attempts reached", details,
            )

        if no_progress_rounds >= self.no_progress_limit and not ready_work and not in_flight:
            return ConvergenceDecision(
                True, "NO_PROGRESS",
                "consecutive dispatch batches produced no terminal progress", details,
            )

        if speculative_only and pending_work and not in_flight:
            self.speculative_rounds += 1
        else:
            self.speculative_rounds = 0
        if self.speculative_limit and self.speculative_rounds >= self.speculative_limit:
            details["speculative_rounds"] = self.speculative_rounds
            return ConvergenceDecision(
                True, "SPECULATIVE_ONLY",
                "only explicitly speculative work remains beyond the configured patience",
                details,
            )

        if (
            self.min_marginal_gain > 0.0
            and marginal_gain is not None
            and pending_work
            and not in_flight
        ):
            if float(marginal_gain) < self.min_marginal_gain:
                self.low_gain_rounds += 1
            else:
                self.low_gain_rounds = 0
            if self.low_gain_rounds >= self.low_gain_patience:
                details["low_gain_rounds"] = self.low_gain_rounds
                return ConvergenceDecision(
                    True, "MARGINAL_GAIN_BELOW_THRESHOLD",
                    "measured progress stayed below the configured threshold",
                    details,
                )
        else:
            self.low_gain_rounds = 0

        return ConvergenceDecision(False, details=details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_rounds": self.max_rounds,
            "no_progress_limit": self.no_progress_limit,
            "min_marginal_gain": self.min_marginal_gain,
            "low_gain_patience": self.low_gain_patience,
            "speculative_limit": self.speculative_limit,
            "stop_on_human_required": self.stop_on_human_required,
            "stop_on_budget_exhausted": self.stop_on_budget_exhausted,
            "low_gain_rounds": self.low_gain_rounds,
            "speculative_rounds": self.speculative_rounds,
        }
