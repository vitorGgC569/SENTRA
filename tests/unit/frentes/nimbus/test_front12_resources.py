"""Frente 12: measure and admit CPU/RAM without killing or pinning the host."""
from __future__ import annotations

import json
import time

import pytest

from orchestrator.budgets import BudgetExceeded, HostResourceBudget
from orchestrator.compute_policy import ComputePolicy, HostPressure, clamp_for_pressure
from orchestrator.rate_governor import HostResourceGovernor
from orchestrator.resources import (
    ResourceCeiling,
    attribute_processes,
    classify_surface,
    cpu_percent_between,
    evaluate_admission,
    read_host_memory,
    read_host_snapshot,
    read_process_samples,
    sample_surfaces,
)
from sentra_executors.vm_resources import apply_plan, measure, measure_and_plan, plan_limits


class _Binding:
    def __init__(self, vm_id, marker):
        self.vm_id = vm_id
        self.marker = marker


class _Client:
    def __init__(self, info, metrics="CPU/Load/User:avg 3.5\nC:\\secret\\disk.vdi 1\n"):
        self.info = info
        self.metrics = metrics
        self.calls = []

    def status(self, binding):
        return dict(self.info)

    def run(self, *args, physical=True, **kwargs):
        self.calls.append((args, physical))
        if physical:
            raise AssertionError("metrics query must stay non-physical")
        if args[0] != "metrics":
            raise AssertionError(args)
        return self.metrics


def _info(**extra):
    base = {
        "UUID": "vm-1",
        "description": "marker-1",
        "VMState": "running",
        "cpus": "2",
        "memory": "4096",
        "CPUExecutionCap": "100",
    }
    base.update(extra)
    return base


def test_surface_classification_ignores_unrelated_processes():
    assert classify_surface("VBoxHeadless.exe") == "vm"
    assert classify_surface("VirtualBoxVM.exe") == "vm"
    assert classify_surface(
        "electron.exe", r"C:\Users\vitor\OneDrive\Desktop\SENTRA\sentra_electron\electron.exe",
    ) == "canvas"
    assert classify_surface("electron.exe", r"C:\Program Files\Slack\electron.exe") is None
    assert classify_surface(
        "python.exe", r"C:\Python\python.exe", "sentra-cli --terminal run",
    ) == "terminal"
    assert classify_surface("python.exe", r"C:\Python\python.exe", "unrelated script") is None
    assert classify_surface("chrome.exe", r"C:\chrome\chrome.exe", "sentra") is None
    surfaces = sample_surfaces([
        {"pid": 1, "name": "chrome.exe", "rss_bytes": 500_000_000, "cpu_time_s": 9},
        {"pid": 2, "name": "VBoxHeadless.exe", "rss_bytes": 1024 * 1024, "cpu_time_s": 1},
        {"pid": 3, "name": "electron.exe", "image_path": r"C:\SENTRA\electron.exe",
         "rss_bytes": 2 * 1024 * 1024, "cpu_time_s": 0.5},
    ])
    assert surfaces["vm"]["process_count"] == 1
    assert surfaces["canvas"]["process_count"] == 1
    assert surfaces["terminal"]["process_count"] == 0
    assert surfaces["vm"]["rss_mb"] == pytest.approx(1)


def test_admission_refuses_work_that_would_pin_the_host():
    ceiling = ResourceCeiling()
    host = {"total_mb": 16384, "available_mb": 12000, "cpu_percent": 20, "ram_percent": 27}
    surfaces = {"canvas": {"rss_mb": 0}, "terminal": {"rss_mb": 0}, "vm": {"rss_mb": 0}}
    allowed = evaluate_admission(
        ceiling=ceiling, host=host, surfaces=surfaces, surface="canvas", ram_mb=1024, cpu_percent=10,
    )
    assert allowed["allowed"] is True
    assert allowed["kills_processes"] is False
    assert allowed["changes_priority"] is False
    assert allowed["authorizes_effects"] is False
    tight = evaluate_admission(
        ceiling=ceiling, host=host, surfaces=surfaces, surface="vm", ram_mb=11000,
    )
    assert tight["allowed"] is False
    assert "host reserve" in tight["reasons"]
    crowded = evaluate_admission(
        ceiling=ceiling, host=host,
        surfaces={"canvas": {"rss_mb": 2000}, "terminal": {"rss_mb": 0}, "vm": {"rss_mb": 0}},
        surface="canvas", ram_mb=100,
    )
    assert crowded["allowed"] is False
    assert "canvas ram ceiling" in crowded["reasons"]
    hot_cpu = evaluate_admission(
        ceiling=ceiling,
        host={"total_mb": 16384, "available_mb": 12000, "cpu_percent": 90},
        surfaces=surfaces, surface="terminal", ram_mb=128,
    )
    assert hot_cpu["allowed"] is False
    assert "cpu ceiling" in hot_cpu["reasons"]
    assert cpu_percent_between(1, 2, elapsed_s=1, cpu_count=4) == pytest.approx(25)
    assert cpu_percent_between(0, 8, elapsed_s=1, cpu_count=4) == 100


def test_host_budget_persists_and_hides_other_dots(tmp_path):
    path = tmp_path / "budget.json"
    budget = HostResourceBudget(total_mb=8192, reserve_mb=2048, state_path=path)
    first = budget.reserve("dot-alpha", "vm", 2048, 40)
    budget.reserve("dot-bravo", "canvas", 512, 10)
    with pytest.raises(BudgetExceeded):
        budget.reserve("dot-bravo", "vm", 5000, 10)
    snap = budget.snapshot_for_dot("dot-alpha")
    assert [item["id"] for item in snap["reservations"]] == [first.id]
    assert "dot-bravo" not in json.dumps(snap)
    assert snap["host_ram_reserved_mb"] == 2560
    assert snap["kills_processes"] is False
    assert snap["authorizes_effects"] is False
    resumed = HostResourceBudget(total_mb=8192, reserve_mb=2048, state_path=path)
    assert resumed.snapshot_for_dot("dot-alpha")["host_ram_reserved_mb"] == 2560
    with pytest.raises(BudgetExceeded):
        resumed.reserve("dot-bravo", "canvas", 2048, 50)
    resumed.release(first.id)
    again = HostResourceBudget(total_mb=8192, reserve_mb=2048, state_path=path)
    created = again.reserve("dot-bravo", "canvas", 512, 10)
    bravo = again.snapshot_for_dot("dot-bravo")
    assert created.id in {item["id"] for item in bravo["reservations"]}
    assert "dot-alpha" not in json.dumps(bravo)
    assert again.snapshot_for_dot("dot-alpha")["reservations"] == []


def test_pressure_governor_delays_without_sleeping(tmp_path):
    path = tmp_path / "pressure.json"
    clock = {"now": 1000.0}
    governor = HostResourceGovernor(state_path=path, clock=lambda: clock["now"], max_delay_s=2)
    started = time.perf_counter()
    delay = governor.observe(ram_percent=96, cpu_percent=10, available_mb=8000)
    elapsed = time.perf_counter() - started
    assert delay == pytest.approx(2)
    assert elapsed < 0.5
    assert governor.snapshot()["sleeps_in_observe"] is False
    assert governor.snapshot()["changes_priority"] is False
    resumed = HostResourceGovernor(state_path=path, clock=lambda: clock["now"], max_delay_s=2)
    assert resumed.delay() == pytest.approx(2)
    clock["now"] = 1003
    assert resumed.delay() == 0
    with pytest.raises(ValueError):
        HostResourceGovernor(max_delay_s=30)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        HostResourceGovernor(state_path=path, clock=lambda: clock["now"])


def test_compute_policy_stops_escalation_while_the_host_is_hot():
    policy = ComputePolicy()
    hot = clamp_for_pressure(policy, HostPressure(ram_percent=90, available_mb=8000, cpu_percent=10))
    assert hot is not policy
    assert hot.disagreement_add == []
    assert policy.disagreement_add
    assert hot.expand(list(hot.initial_roles), list(policy.disagreement_add)) == list(hot.initial_roles)
    assert hot.max_agents == policy.agent_count(policy.initial_roles)
    cool = clamp_for_pressure(policy, HostPressure(ram_percent=20, available_mb=8000, cpu_percent=10))
    assert cool is policy
    starved = clamp_for_pressure(policy, HostPressure(ram_percent=10, available_mb=512, cpu_percent=None))
    assert starved.disagreement_add == []


def test_vm_measure_is_read_only_and_plan_does_not_apply(tmp_path):
    del tmp_path
    client = _Client(_info())
    binding = _Binding("vm-1", "marker-1")
    host = {
        "available_mb": 16000, "total_mb": 32000, "ram_percent": 40,
        "cpu_percent": 20, "cpu_count": 8,
    }
    result = measure_and_plan(client, binding, host, ResourceCeiling().as_dict())
    assert result["mutated"] is False
    assert result["authorizes_effects"] is False
    assert result["measured"]["memory_mb"] == 4096
    assert result["measured"]["cpus"] == 2
    assert result["plan"]["memory_mb"] == 4096
    assert result["plan"]["cpus"] == 2
    assert result["plan"]["cpu_execution_cap"] == 100
    assert result["plan"]["memory_change_applied"] is False
    assert result["plan"]["cpu_count_change_applied"] is False
    assert result["measured"]["metrics"]["series"]["CPU/Load/User:avg"] == pytest.approx(3.5)
    assert "secret" not in json.dumps(result["measured"]["metrics"])
    assert client.calls
    assert all(physical is False and args[0] == "metrics" for args, physical in client.calls)

    hot = plan_limits(
        configured={"cpus": 4, "memory_mb": 8192, "cpu_execution_cap": 100},
        host={"available_mb": 1500, "ram_percent": 92, "cpu_percent": 96, "cpu_count": 4},
        ceiling=ResourceCeiling().as_dict(),
    )
    assert hot["cpu_execution_cap"] == 40
    assert hot["memory_mb"] == 8192
    assert hot["cpus"] == 4
    assert hot["memory_change_applied"] is False
    assert hot["admit_new_vm"] is False
    assert hot["mutated"] is False
    assert hot["cap_change_recommended"] is True

    stalled = plan_limits(
        configured={"cpus": 1, "memory_mb": 2048, "cpu_execution_cap": 0},
        host={"available_mb": 8000, "ram_percent": 20, "cpu_percent": 10, "cpu_count": 8},
    )
    assert stalled["cpu_execution_cap"] == 10
    assert stalled["mutated"] is False
    assert stalled["memory_change_applied"] is False


def test_plan_is_shown_and_apply_without_order_is_refused():
    class _Refuse:
        def run(self, *args, **kwargs):
            raise AssertionError(args)

    client = _Refuse()
    binding = _Binding("vm-1", "marker-1")
    plan = plan_limits(
        configured={"cpus": 4, "memory_mb": 8192, "cpu_execution_cap": 100},
        host={"available_mb": 1500, "ram_percent": 92, "cpu_percent": 96, "cpu_count": 4},
        ceiling=ResourceCeiling().as_dict(),
    )
    assert plan["cap_change_recommended"] is True
    assert plan["cpu_execution_cap"] == 40
    assert plan["memory_change_applied"] is False
    assert plan["mutated"] is False

    refusal = apply_plan(client, binding, plan, order=None)
    assert refusal["applied"] is False
    assert refusal["refused"] is True
    assert refusal["reason"] == "sem ordem"
    assert refusal["missing_order_fields"] == [
        "run_id", "work_item_id", "operation_id", "grant_id", "owner", "vm_id",
    ]
    assert refusal["plan"]["cpu_execution_cap"] == 40
    assert refusal["plan"]["memory_mb"] == 8192
    assert refusal["authorizes_effects"] is False
    assert refusal["mutated"] is False

    empty = apply_plan(client, binding, plan, order={})
    assert empty["applied"] is False
    assert empty["reason"] == "sem ordem"


def test_authorized_cap_calls_virtualbox_client_only_after_central_proof(tmp_path):
    from types import SimpleNamespace
    from sentra_executors.virtualbox_vm import VirtualBoxClient
    from sentra_executors.vm_resources import apply_authorized_cap
    from sentra_runtime.effect_boundary import current_effect_context

    vm_id = "fcd974cf-ccdc-5636-b7af-2f96024d5dde"
    marker = "sentra-marker"
    plan = {"cpus": 2, "memory_mb": 2048, "cpu_execution_cap": 40}
    host = {"total_mb": 32000, "available_mb": 16000, "cpu_percent": 96, "ram_percent": 40}
    surfaces = {"canvas": {"rss_mb": 0}, "terminal": {"rss_mb": 0}, "vm": {"rss_mb": 200}}
    ceiling = ResourceCeiling()
    order = {
        "run_id": "run-1", "work_item_id": "wi-1", "operation_id": "op-1",
        "grant_id": "grant-1", "owner": "owner-a", "vm_id": vm_id,
    }
    calls = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        verb = argv[1]
        if verb == "showvminfo":
            stdout = "\n".join([
                f'"UUID"="{vm_id}"',
                f'"description"="{marker}"',
                '"VMState"="running"',
                '"cpus"="2"',
                '"memory"="2048"',
                '"CPUExecutionCap"="100"',
            ])
            return SimpleNamespace(returncode=0, stdout=stdout)
        if verb == "controlvm":
            return SimpleNamespace(returncode=0, stdout="")
        raise AssertionError(argv)

    client = VirtualBoxClient(path="not-vboxmanage", runner=runner)
    binding = _Binding(vm_id, marker)
    strings_only = apply_plan(
        client, binding, plan, order=order, host=host, surfaces=surfaces,
        ceiling=ceiling, state_root=tmp_path,
    )
    assert strings_only["executed"] is False
    assert strings_only["reason"] == "autoridade central ausente"
    assert calls == []

    request = SimpleNamespace(
        principal_id="owner-a", capability_id="vm:manage", work_item_id="wi-1",
        machine_id=vm_id, operation_id="op-1",
        arguments={"action": "resource.cap", "vm_id": vm_id,
                   "workload_inspected": True, "controlled_proof": True},
    )
    receipt = SimpleNamespace(
        owner="owner-a", run_id="run-1", operation_id="op-1", fencing_token=7,
    )
    context = SimpleNamespace(request=request, receipt=receipt, checkpoint=lambda: None)
    token = current_effect_context.set(context)
    try:
        applied = apply_authorized_cap(
            client, binding, plan, host=host, surfaces=surfaces,
            ceiling=ceiling, state_root=tmp_path,
        )
    finally:
        current_effect_context.reset(token)
    assert applied["executed"] is True
    assert applied["applied"] is True
    assert applied["receipt"]["owner"] == "owner-a"
    assert applied["receipt"]["vm_id"] == vm_id
    assert applied["receipt"]["state"] == "running"
    assert applied["rollback"]["cpu_execution_cap"] == 100
    assert applied["receipt"]["fencing_token"] == 7
    verbs = [item[1] for item in calls]
    assert verbs == ["showvminfo", "controlvm"]
    assert calls[1][2:] == [vm_id, "cpuexecutioncap", "40"]
    stored = (tmp_path / "vm-cap-receipts" / "op-1.json").read_text(encoding="utf-8")
    assert '"executed": true' in stored
    assert "not-vboxmanage" in calls[0][0]


def test_vm_measure_refuses_identity_mismatch_and_survives_metrics_failure():
    class _Loose:
        def status(self, binding):
            return {
                "UUID": "other-vm", "description": binding.marker,
                "cpus": 1, "memory": 1024, "VMState": "running",
            }

        def run(self, *args, **kwargs):
            raise AssertionError("metrics must not run after an identity mismatch")

    with pytest.raises(ValueError, match="identity"):
        measure(_Loose(), _Binding("vm-1", "marker-1"))

    class _MetricsDown:
        def __init__(self):
            self.physical = None

        def status(self, binding):
            return _info(CPUExecutionCap="80", VMState="poweroff")

        def run(self, *args, physical=True, **kwargs):
            self.physical = physical
            raise RuntimeError("metrics unavailable")

    client = _MetricsDown()
    measured = measure(client, _Binding("vm-1", "marker-1"))
    assert measured["cpu_execution_cap"] == 80
    assert measured["metrics"]["available"] is False
    assert measured["mutated"] is False
    assert client.physical is False


def test_attributed_measurement_names_canvas_terminal_and_vm():
    rows = attribute_processes([
        {
            "pid": 11, "name": "electron.exe",
            "image_path": r"C:\SENTRA\sentra_electron\electron.exe",
            "rss_bytes": 1024, "command_line": "",
        },
        {
            "pid": 12, "name": "python.exe", "image_path": r"C:\Python\python.exe",
            "command_line": "python -m sentra-cli --terminal",
            "rss_bytes": 2048,
        },
        {
            "pid": 13, "name": "VBoxHeadless.exe", "image_path": r"C:\VirtualBox\VBoxHeadless.exe",
            "command_line": "VBoxHeadless --startvm fcd974cf-ccdc-5636-b7af-2f96024d5dde",
            "rss_bytes": 4096,
        },
        {"pid": 14, "name": "chrome.exe", "command_line": "sentra", "rss_bytes": 9},
    ])
    by_surface = {row["surface"]: row for row in rows}
    assert set(by_surface) == {"canvas", "terminal", "vm"}
    assert by_surface["vm"]["vm_id"] == "fcd974cf-ccdc-5636-b7af-2f96024d5dde"
    assert by_surface["canvas"]["vm_id"] is None
    assert by_surface["terminal"]["pid"] == 12
    assert "command_line" not in by_surface["vm"]


def test_live_host_sample_is_read_only():
    sample = read_host_memory()
    assert sample["total_mb"] > 512
    assert 0 <= sample["available_mb"] <= sample["total_mb"]
    assert 0 <= sample["ram_percent"] <= 100
    assert sample["cpu_percent"] is None
    assert sample["authorizes_effects"] is False
    processes = read_process_samples()
    assert isinstance(processes, list)
    for proc in processes:
        assert proc["pid"] > 0
        assert proc["rss_bytes"] >= 0
    snapshot = read_host_snapshot()
    assert set(snapshot["surfaces"]) == {"canvas", "terminal", "vm"}
    assert snapshot["kills_processes"] is False
    assert snapshot["changes_priority"] is False
    assert snapshot["authorizes_effects"] is False
    started = time.perf_counter()
    read_host_snapshot()
    assert time.perf_counter() - started < 5
