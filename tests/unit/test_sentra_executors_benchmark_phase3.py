"""Phase3: deterministic Tk-only benchmark with real Registry/PolicyDecision."""
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from sentra_runtime.contracts import PolicyDecision
from sentra_runtime.executor import ExecutorRegistry
from sentra_executors import (
    BASELINE_VERSION, BenchCase, TkBaseline, OwnTkBenchmark,
    plan_read_only_tk_lab,
)


class Grant:
    def __init__(self, deny=()):
        self.deny = set(deny)
        self.calls = []
    def __call__(self, request):
        self.calls.append(request.operation_id)
        return PolicyDecision(request.operation_id not in self.deny, "lab policy")


class ReadOwnedTkFixture:
    """Never reads or launches real apps; models exact owned Tk title."""
    def __init__(self):
        self.calls = []
        self.fail_for = set()
    def run(self, binding, arguments):
        assert binding.window_title.startswith("SENTRA-UIA-LAB-")
        assert arguments == {"action": "read_window_title", "pid": 101, "hwnd": 202}
        self.calls.append(arguments.copy())
        if len(self.calls) in self.fail_for:
            raise RuntimeError("lab fixture error")
        return {"pid": 101, "hwnd": 202,
                "window_title_sha256": hashlib.sha256(
                    binding.window_title.encode()).hexdigest()}


class Clock:
    def __init__(self):
        self.now = 0.
    def __call__(self):
        current = self.now
        self.now += .01
        return current


def make_bench(*, denied=()):
    grant = Grant(denied)
    backend = ReadOwnedTkFixture()
    plan = plan_read_only_tk_lab(
        machine_id="bench-win", owner_principal_id="lab",
        pid=101, hwnd=202, window_title="SENTRA-UIA-LAB-12345678",
        policy=grant, backend=backend)
    registry = ExecutorRegistry(authorize=grant)
    plan.declaration.register(registry)
    return OwnTkBenchmark(plan=plan, registry=registry, clock=Clock()), grant, backend


def cases(*ids):
    return tuple(BenchCase(x) for x in ids)


def run(coro):
    return asyncio.run(coro)


def test_benchmark_deterministic_versioned_fixture_end_to_end():
    bm, grant, backend = make_bench()
    baseline = TkBaseline("tk-read", ("read_1", "read_2"))
    report = run(bm.run(baseline=baseline, run_id="round_01",
                        cases=cases("read_1", "read_2")))
    assert report.baseline_version == BASELINE_VERSION
    assert report.baseline_sha256 == baseline.sha256
    assert report.total == 2 and report.successes == 2
    assert report.policy_denials == 0
    assert report.success_rate == 1.0
    assert report.mean_latency_ms == 10.0
    assert report.idempotent_replays == 2
    assert len(backend.calls) == 2  # no second effect for retry
    assert all(s.state == "SUCCEEDED" and s.repeated_state == "SUCCEEDED"
               and len(s.evidence_sha256) == 64 and s.latency_ms == 10
               for s in report.steps)
    export = json.loads(report.export_json())
    assert export["steps"][0]["case_id"] == "read_1"
    assert "SENTRA-UIA-LAB" not in report.export_json()
    assert "text" not in export["steps"][0]


def test_benchmark_policy_denials_and_success_rate_with_live_authority():
    bm, grant, backend = make_bench(denied={"round_02:tk:denied_case"})
    baseline = TkBaseline("tk-three", ("read_1", "denied_case", "read_2"))
    report = run(bm.run(baseline=baseline, run_id="round_02",
                        cases=cases(*baseline.case_ids)))
    assert report.successes == 2 and report.policy_denials == 1
    assert report.success_rate == round(2 / 3, 6)
    assert report.idempotent_replays == 2
    assert report.steps[1].state == "DENIED"
    assert report.steps[1].evidence_sha256 is None
    assert len(backend.calls) == 2
    assert "round_02:tk:denied_case" in grant.calls


def test_benchmark_same_run_never_reexecutes_lab_effects():
    bm, grant, backend = make_bench()
    baseline = TkBaseline("tk-one", ("case_01",))
    first = run(bm.run(baseline=baseline, run_id="round_03",
                       cases=cases("case_01")))
    second = run(bm.run(baseline=baseline, run_id="round_03",
                        cases=cases("case_01")))
    assert first.steps[0].evidence_sha256 == second.steps[0].evidence_sha256
    assert len(backend.calls) == 1
    assert len(grant.calls) >= 4
    grant.deny.add("round_03:tk:case_01")
    third = run(bm.run(baseline=baseline, run_id="round_03",
                       cases=cases("case_01")))
    assert third.policy_denials == 1 and third.successes == 0
    assert len(backend.calls) == 1


def test_benchmark_backend_failure_changes_metrics_no_replay():
    bm, _, backend = make_bench()
    backend.fail_for = {1}
    baseline = TkBaseline("tk-one", ("read_1", "read_2"))
    report = run(bm.run(baseline=baseline, run_id="round_04",
                        cases=cases(*baseline.case_ids)))
    assert report.success_rate == .5
    assert [step.state for step in report.steps] == ["FAILED", "SUCCEEDED"]
    assert report.idempotent_replays == 1


@pytest.mark.parametrize("bad_case", ["HOME", "../../app", "", "a", "with spaces"])
def test_benchmark_deny_unapproved_task_ids(bad_case):
    with pytest.raises(ValueError):
        BenchCase(bad_case)


def test_benchmark_baseline_digest_version_and_reordered_case_rejected():
    baseline = TkBaseline("tk-two", ("a1", "b2"))
    assert baseline.sha256 != TkBaseline("tk-two", ("b2", "a1")).sha256
    with pytest.raises(ValueError):
        TkBaseline("tk-two", ("a1",), version="unreviewed-v2")
    bm, _, backend = make_bench()
    with pytest.raises(ValueError, match="benchmark_baseline_case_mismatch"):
        run(bm.run(baseline=baseline, run_id="round_05",
                   cases=cases("b2", "a1")))
    assert backend.calls == []


def test_benchmark_only_own_lab_title_no_personal_app():
    bm, _, backend = make_bench()
    from sentra_executors import WindowsUIABinding, declare_windows_machine
    binding = WindowsUIABinding(
        "read-title", 101, 202, "PersonalApp", ("_unused",),
        allowed_actions=("read_window_title",))
    policy = Grant()
    declaration = declare_windows_machine(
        machine_id="foreign", owner_principal_id="lab",
        bindings=(binding,), policy=policy, backend=backend)
    registry = ExecutorRegistry(authorize=policy)
    with pytest.raises(ValueError, match="benchmark_only_owned_tk_read"):
        OwnTkBenchmark(plan=type("P", (), {"binding": binding,
                                          "declaration": declaration})(),
                       registry=registry)
