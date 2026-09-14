"""Promotion — fronteira anti auto-promoção irrestrita."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class PromotionDecision:
    verdict: Literal["PROMOTE", "HOLD", "REJECT"]
    reason: str
    needs_external_approval: bool = False


def decide(touches_protected: bool, tests_passed: bool, approvals: int,
           min_approvals: int = 2, score_positive: bool = True,
           external_approval: bool = False) -> PromotionDecision:
    if not tests_passed:
        return PromotionDecision("REJECT", "tests failed", False)
    if approvals < min_approvals:
        return PromotionDecision("HOLD", f"quorum {approvals}/{min_approvals}", touches_protected)
    if not score_positive:
        return PromotionDecision("HOLD", "score not positive", touches_protected)
    if touches_protected and not external_approval:
        return PromotionDecision("HOLD", "protected component requires external approval", True)
    return PromotionDecision("PROMOTE", "gates passed", False)
