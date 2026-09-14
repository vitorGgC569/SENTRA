"""Token-economy benchmark (RNF-012) and context-compression measurement.

Measures, for a representative task set, the Master-token reduction of the OMA
path (planner -> secondary execution -> validation -> repair -> compressed
CandidatePackage -> master final) versus a Baseline-A path where the master
does the bulk work directly.

    MasterReduction = 1 - (MasterTokens_OMA / MasterTokens_Baseline)

Also measures raw_intermediate_context_tokens vs candidate_package_tokens
(compression_ratio) and verifies no critical information is dropped.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import Candidate, CandidatePackage, Task, ValidationReport


def estimate_tokens(text: str) -> int:
    return max(0, len(text or "") // 4)


def raw_intermediate_context_tokens(
    task: Task,
    candidates: List[Candidate],
    reports: List[ValidationReport],
    test_results: Optional[Dict[str, Any]] = None,
) -> int:
    parts = [task.objective, task.description]
    for c in candidates:
        parts += [c.summary, c.solution, c.patch, json.dumps(c.validation_commands)]
    for r in reports:
        parts += [r.summary, json.dumps([f.to_dict() for f in r.findings])]
    if test_results:
        parts.append(json.dumps(test_results))
    return estimate_tokens("\n".join(parts))


def package_tokens(package: CandidatePackage) -> int:
    return estimate_tokens(json.dumps(package.to_dict(), ensure_ascii=False))


def compression_ratio(raw_tokens: int, pkg_tokens: int) -> float:
    if raw_tokens <= 0:
        return 1.0
    return pkg_tokens / raw_tokens


def check_compression_preserves_critical(
    reports: List[ValidationReport],
    test_results: Optional[Dict[str, Any]],
    package: CandidatePackage,
) -> List[str]:
    """Return list of dropped critical items (empty = lossless for critical info)."""
    dropped: List[str] = []
    critical = [f.description for r in reports for f in r.findings if f.severity.value == "CRITICAL"]
    missing = [item for item in critical if item not in package.critical_risks]
    if missing:
        dropped.append(f"{len(missing)} critical findings missing from package: {missing}")
    if test_results and not test_results.get("all_passed", True):
        if package.tests_failed == 0:
            dropped.append("failed tests missing from package")
    # Requirements coverage must be explicit
    if package.requirements_coverage < 0 or package.requirements_coverage > 1:
        dropped.append("invalid requirements_coverage")
    return dropped


@dataclass
class ABResult:
    objective: str
    baseline_master_tokens: int
    oma_master_tokens: int
    oma_secondary_tokens: int
    raw_context_tokens: int
    package_tokens: int

    @property
    def master_reduction(self) -> float:
        if self.baseline_master_tokens <= 0:
            return 0.0
        return 1.0 - (self.oma_master_tokens / self.baseline_master_tokens)

    @property
    def compression(self) -> float:
        return compression_ratio(self.raw_context_tokens, self.package_tokens)


def summarize(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    s = sorted(values)
    n = len(s)
    return {
        "mean": round(statistics.mean(values), 4),
        "median": round(statistics.median(values), 4),
        "p50": round(s[int(n * 0.50)], 4),
        "p95": round(s[min(int(n * 0.95), n - 1)], 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def summarize_benchmark(results: List[ABResult]) -> Dict[str, Any]:
    return {
        "n": len(results),
        "master_reduction": summarize([r.master_reduction for r in results]),
        "compression_ratio": summarize([r.compression for r in results]),
        "total_baseline_master": sum(r.baseline_master_tokens for r in results),
        "total_oma_master": sum(r.oma_master_tokens for r in results),
        "total_oma_secondary": sum(r.oma_secondary_tokens for r in results),
        "details": [
            {
                "objective": r.objective[:80],
                "baseline_master": r.baseline_master_tokens,
                "oma_master": r.oma_master_tokens,
                "oma_secondary": r.oma_secondary_tokens,
                "reduction": round(r.master_reduction, 4),
                "compression": round(r.compression, 4),
            }
            for r in results
        ],
    }
