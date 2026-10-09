"""Deterministic, versioned own-Tk read-only benchmark, inspired by OSWorld.

No OSWorld/WindowsWorld/WindowsAgentArena benchmark runner is invoked.
Only exact approved Tk title requests via live SENTRA ExecutorRegistry.
Measurements can use an injected monotonic clock for deterministic fixtures.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass

from sentra_runtime.executor import AuthorizationRequired, DuplicateOperation, InvalidOperation
from .discovery import ReadOnlyLabPlan

BASELINE_VERSION = "sentra-tk-lab-v1"


def _digest(value) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True,
                           ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BenchCase:
    case_id: str
    """A single approved read_window_title task."""

    def __post_init__(self):
        if type(self.case_id) is not str or not re.fullmatch("[a-z0-9_-]{2,48}", self.case_id):
            raise ValueError("invalid_benchmark_case")


@dataclass(frozen=True)
class TkBaseline:
    baseline_id: str
    case_ids: tuple[str, ...]
    version: str = BASELINE_VERSION

    def __post_init__(self):
        if (self.version != BASELINE_VERSION or not self.baseline_id
                or not re.fullmatch("[a-z0-9_-]{2,48}", self.baseline_id)
                or not self.case_ids
                or len(set(self.case_ids)) != len(self.case_ids)
                or not all(isinstance(case, str) and
                           re.fullmatch("[a-z0-9_-]{2,48}", case)
                           for case in self.case_ids)):
            raise ValueError("invalid_or_unsupported_tk_baseline")

    @property
    def sha256(self):
        return _digest({"version": self.version, "baseline_id": self.baseline_id,
                        "case_ids": self.case_ids})


@dataclass(frozen=True)
class BenchmarkStep:
    case_id: str
    state: str
    latency_ms: float
    evidence_sha256: str | None
    repeated_state: str | None = None


@dataclass(frozen=True)
class BenchmarkReport:
    baseline_version: str
    baseline_sha256: str
    run_id: str
    total: int
    successes: int
    policy_denials: int
    uncertain: int
    success_rate: float
    mean_latency_ms: float
    idempotent_replays: int
    steps: tuple[BenchmarkStep, ...]

    def export_json(self) -> str:
        data = {
            "baseline_version": self.baseline_version,
            "baseline_sha256": self.baseline_sha256,
            "run_id": self.run_id,
            "total": self.total,
            "successes": self.successes,
            "policy_denials": self.policy_denials,
            "uncertain": self.uncertain,
            "success_rate": self.success_rate,
            "mean_latency_ms": self.mean_latency_ms,
            "idempotent_replays": self.idempotent_replays,
            "steps": [step.__dict__ for step in self.steps],
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


class OwnTkBenchmark:
    def __init__(self, *, plan: ReadOnlyLabPlan, registry, clock=None):
        if (not isinstance(plan, ReadOnlyLabPlan)
                or not plan.binding.window_title.startswith("SENTRA-UIA-LAB-")
                or plan.binding.allowed_actions != ("read_window_title",)):
            raise ValueError("benchmark_only_owned_tk_read")
        self.plan = plan
        self.registry = registry
        self.clock = clock if clock is not None else time.perf_counter

    async def run(self, *, baseline: TkBaseline, run_id: str,
                  cases: tuple[BenchCase, ...], replay: bool = True) -> BenchmarkReport:
        if (not isinstance(baseline, TkBaseline) or
                type(run_id) is not str or not re.fullmatch("[a-z0-9_-]{2,48}", run_id)
                or tuple(case.case_id for case in cases) != baseline.case_ids):
            raise ValueError("benchmark_baseline_case_mismatch")
        steps = []
        successes = denials = uncertain = repeats = 0
        for case in cases:
            req = self.plan.request(
                operation_id=f"{run_id}:tk:{case.case_id}",
                idempotency_key=f"{run_id}:tk:{case.case_id}",
                work_item_id=f"{baseline.baseline_id}:{case.case_id}")
            started = self.clock()
            try:
                result = await self.registry.submit(req)
                state = result.state
                digest = _digest(dict(result.evidence)) if result.evidence else None
            except AuthorizationRequired:
                state, digest = "DENIED", None
            except (DuplicateOperation, InvalidOperation):
                state, digest = "FAILED", None
            elapsed = self.clock() - started
            if elapsed < 0:
                raise ValueError("benchmark_clock_moved_backwards")
            repeat_state = None
            if replay and state == "SUCCEEDED":
                try:
                    repeated = await self.registry.submit(req)
                    repeat_state = repeated.state
                except AuthorizationRequired:
                    repeat_state = "DENIED"
                except (DuplicateOperation, InvalidOperation):
                    repeat_state = "FAILED"
                if repeat_state == "SUCCEEDED":
                    repeats += 1
            successes += state == "SUCCEEDED"
            denials += state == "DENIED"
            uncertain += state == "UNCERTAIN"
            steps.append(BenchmarkStep(case.case_id, state, round(elapsed * 1000, 3),
                                       digest, repeat_state))
        n = len(steps)
        return BenchmarkReport(baseline.version, baseline.sha256, run_id, n,
                               successes, denials, uncertain,
                               round(successes / n, 6),
                               round(sum(s.latency_ms for s in steps) / n, 3),
                               repeats, tuple(steps))
