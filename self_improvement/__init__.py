"""Self-Improvement Engine — amplia o OMA, não o substitui."""
from .engine import SelfImprovementEngine, SwarmResult
from .evaluator import ScoreInput, ImprovementScore, compute
from .promotion import PromotionDecision, decide
from .sandbox import isolated_copy

__all__ = ["SelfImprovementEngine", "SwarmResult", "ScoreInput", "ImprovementScore",
           "compute", "PromotionDecision", "decide", "isolated_copy"]
