"""ImprovementScore objetivo — nunca 'melhor porque o modelo declarou'."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScoreInput:
    tests_passed: int = 0
    tests_total: int = 1
    regressions: int = 0
    latency_s: float = 0.0
    baseline_latency_s: float = 0.0
    tokens: int = 0
    baseline_tokens: int = 1
    quality: float = 0.0  # 0..1 (ex: confidence do gate)
    failures: int = 0
    complexity_delta: int = 0  # linhas adicionadas aprox


@dataclass
class ImprovementScore:
    score: float
    breakdown: dict

    @property
    def is_improvement(self) -> bool:
        return self.score > 0


def compute(inp: ScoreInput) -> ImprovementScore:
    quality_gain = inp.quality
    reliability_gain = (inp.tests_passed / max(1, inp.tests_total)) - (inp.failures * 0.2)
    perf_gain = 0.0
    if inp.baseline_latency_s > 0:
        perf_gain = max(-1.0, (inp.baseline_latency_s - inp.latency_s) / inp.baseline_latency_s)
    token_gain = max(-1.0, (inp.baseline_tokens - inp.tokens) / max(1, inp.baseline_tokens))
    regression_penalty = inp.regressions * 0.5
    complexity_penalty = max(0.0, inp.complexity_delta / 1000.0)
    score = quality_gain + reliability_gain + perf_gain * 0.5 + token_gain * 0.5 - regression_penalty - complexity_penalty
    return ImprovementScore(score=round(score, 4), breakdown={
        "quality_gain": round(quality_gain, 4),
        "reliability_gain": round(reliability_gain, 4),
        "performance_gain": round(perf_gain, 4),
        "token_gain": round(token_gain, 4),
        "regression_penalty": regression_penalty,
        "complexity_penalty": round(complexity_penalty, 4),
    })
