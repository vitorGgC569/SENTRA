from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .failure_summary import (
    GateAuditRefusal,
    accepted_identifier,
    bound_gate_audit,
)
from .models import TokenUsage


@dataclass
class MetricsCollector:
    """
    Collects execution metrics, latencies, and token accounting as specified in
    Sections 36-38 of OMA.
    """

    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_escalated: int = 0

    validation_attempts: int = 0
    validation_approvals: int = 0
    validation_abstentions: int = 0
    repair_rounds: int = 0

    master_calls: int = 0
    tokens_master: TokenUsage = field(default_factory=TokenUsage)
    tokens_secondary: TokenUsage = field(default_factory=TokenUsage)

    task_latencies: List[float] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    def record_task_completed(self, latency: float = 0.0) -> None:
        self.tasks_completed += 1
        if latency > 0:
            self.task_latencies.append(latency)

    def record_task_failed(self) -> None:
        self.tasks_failed += 1

    def record_task_escalated(self) -> None:
        self.tasks_escalated += 1

    def record_validation(self, approved: bool, ran: bool = True) -> None:
        # Abstenções (validador não executou) não entram na taxa de aprovação:
        # pass_rate mede evidência, não disponibilidade de infraestrutura.
        if not ran:
            self.validation_abstentions += 1
            return
        self.validation_attempts += 1
        if approved:
            self.validation_approvals += 1

    def record_repair_round(self) -> None:
        self.repair_rounds += 1

    def record_tokens(self, usage: TokenUsage, is_master: bool = False) -> None:
        if is_master:
            self.master_calls += 1
            self.tokens_master = self.tokens_master.add(usage)
        else:
            self.tokens_secondary = self.tokens_secondary.add(usage)

    @property
    def validation_pass_rate(self) -> float:
        # Zero attempts is absence of evidence, not a perfect pass rate.
        if self.validation_attempts == 0:
            return 0.0
        return self.validation_approvals / self.validation_attempts

    @property
    def escalation_rate(self) -> float:
        if self.tasks_total == 0:
            return 0.0
        return self.tasks_escalated / self.tasks_total

    def get_latency_percentiles(self) -> Dict[str, float]:
        if not self.task_latencies:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        sorted_lat = sorted(self.task_latencies)
        n = len(sorted_lat)
        return {
            "p50": sorted_lat[int(n * 0.50)],
            "p95": sorted_lat[min(int(n * 0.95), n - 1)],
            "p99": sorted_lat[min(int(n * 0.99), n - 1)],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": "current_process_attempt; use run_history for cumulative evidence",
            "tasks_total": self.tasks_total,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "tasks_escalated": self.tasks_escalated,
            "validation_attempts": self.validation_attempts,
            "validation_approvals": self.validation_approvals,
            "validation_abstentions": self.validation_abstentions,
            "validation_pass_rate": round(self.validation_pass_rate, 4) if self.validation_attempts else None,
            "repair_rounds": self.repair_rounds,
            "master_calls": self.master_calls,
            "tokens_master": self.tokens_master.to_dict(),
            "tokens_secondary": self.tokens_secondary.to_dict(),
            "latencies": self.get_latency_percentiles(),
            "elapsed_seconds": round(time.time() - self.start_time, 2),
        }

    def render_dashboard(self, current_confidence: float = 1.0) -> str:
        """
        Renders an operational ASCII Dashboard as specified in Section 75 of OMA.
        """
        total = self.tasks_total or 1
        pct = int((self.tasks_completed / total) * 100)
        bar_len = 20
        filled = int(bar_len * (self.tasks_completed / total))
        bar = "#" * filled + "-" * (bar_len - filled)

        master_tokens = self.tokens_master.input_tokens + self.tokens_master.output_tokens
        sec_tokens = self.tokens_secondary.input_tokens + self.tokens_secondary.output_tokens
        if self.validation_attempts:
            pass_rate = f"{self.validation_pass_rate * 100:5.1f}%"
        else:
            pass_rate = "   n/a"

        lines = [
            "+--------------------------------------------------------------+",
            "|                  OMA OPERATIONAL DASHBOARD                   |",
            "+--------------------------------------------------------------+",
            f"| Tasks Progress:   [{bar}] {pct:3d}% ({self.tasks_completed}/{self.tasks_total})",
            f"| Master Calls:     {self.master_calls:<10} Master Tokens:    {master_tokens:<12,}",
            f"| Repair Cycles:    {self.repair_rounds:<10} Secondary Tokens: {sec_tokens:<12,}",
            f"| Pass Rate:        {pass_rate}     Estimated Conf:   {current_confidence:5.2f}",
            f"| Failures/DLQ:     {self.tasks_failed:<10} Escalations:      {self.tasks_escalated:<10}",
            "+--------------------------------------------------------------+",
        ]
        return "\n".join(lines)


_AUDIT_EVENTS = (
    "chains_opened",
    "uncertain_held",
    "injection_refused",
    "isolation_refused",
    "resend_refused",
    "gate_below_bar",
    "approval_withheld",
)


@dataclass
class AuditSpanRecorder:
    """In-process counts for the decision-to-receipt audit.

    Counting a refusal does not grant a capability and does not resend an
    UNCERTAIN operation.
    """

    chains_opened: int = 0
    uncertain_held: int = 0
    injection_refused: int = 0
    isolation_refused: int = 0
    resend_refused: int = 0
    gate_below_bar: int = 0
    approval_withheld: int = 0

    def record(self, event: str) -> None:
        if event not in _AUDIT_EVENTS:
            raise ValueError("unknown audit span")
        setattr(self, event, int(getattr(self, event)) + 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chains_opened": self.chains_opened,
            "uncertain_held": self.uncertain_held,
            "injection_refused": self.injection_refused,
            "isolation_refused": self.isolation_refused,
            "resend_refused": self.resend_refused,
            "gate_below_bar": self.gate_below_bar,
            "approval_withheld": self.approval_withheld,
            "authorizes_effect": False,
            "resend_uncertain": False,
        }


_REVIEWER = re.compile(r"[A-Za-z0-9_.:-]{2,128}")


class DecisionEffectRegistry:
    """In-process chain from a gate decision through review to a withheld effect.

    A decision below the bar is an audit event. It does not promote.
    An approval without evidence is withheld instead of emitted.
    Review can note or reject the chain. It does not execute an effect.
    """

    def __init__(self, spans: Optional[AuditSpanRecorder] = None) -> None:
        self.spans = spans if spans is not None else AuditSpanRecorder()
        self.chains: List[Dict[str, Any]] = []

    def record_decision(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        try:
            body = bound_gate_audit(observation)
        except GateAuditRefusal as refusal:
            if refusal.code != "evidence":
                raise
            return self.record_withheld(observation.get("candidate_id") if isinstance(observation, dict) else None)
        kind = "gate_below_bar" if body["passed"] is not True else "gate_observed"
        if kind == "gate_below_bar":
            self.spans.record("gate_below_bar")
        decision = {"stage": "decision", "kind": kind, **body}
        return self._seal(decision)

    def record_withheld(self, candidate_id: Any = None) -> Dict[str, Any]:
        """Absence of evidence is an audit event, not an emitted approval."""
        self.spans.record("approval_withheld")
        decision = {
            "stage": "decision",
            "kind": "approval_withheld",
            "passed": False,
            "reason": "approved gate requires evidence",
            "candidate_id": accepted_identifier(candidate_id),
            "status": None,
            "evidence_ids": [],
            "authorizes_effect": False,
            "promotion": False,
            "effects_executed": 0,
            "may_resend": False,
        }
        return self._seal(decision)

    def review(self, chain_index: int, *, reviewer_id: str, verdict: str) -> Dict[str, Any]:
        if type(chain_index) is not int or not -len(self.chains) <= chain_index < len(self.chains):
            raise ValueError("invalid chain")
        if verdict not in {"noted", "rejected"}:
            raise ValueError("review does not grant or approve an effect")
        if not isinstance(reviewer_id, str) or _REVIEWER.fullmatch(reviewer_id) is None:
            raise ValueError("invalid reviewer_id")
        chain = self.chains[chain_index]
        decision = chain["decision"]
        if decision.get("passed") is True and not decision.get("evidence_ids"):
            raise GateAuditRefusal("approved gate requires evidence", code="evidence")
        chain["review"]["reviewer_id"] = reviewer_id
        chain["review"]["verdict"] = verdict
        chain["review"]["authorizes_effect"] = False
        chain["review"]["promotion"] = False
        chain["effect"]["promotion"] = False
        chain["effect"]["executed"] = False
        chain["effect"]["effects_executed"] = 0
        chain["effect"]["authorizes_effect"] = False
        chain["authorizes_effect"] = False
        return chain

    def _seal(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        review = {
            "stage": "review",
            "verdict": "pending",
            "authorizes_effect": False,
            "promotion": False,
        }
        effect = {
            "stage": "effect",
            "promotion": False,
            "executed": False,
            "effects_executed": 0,
            "authorizes_effect": False,
        }
        chain = {
            "authorizes_effect": False,
            "decision": decision,
            "review": review,
            "effect": effect,
            "events": [decision, review, effect],
        }
        self.chains.append(chain)
        return chain
