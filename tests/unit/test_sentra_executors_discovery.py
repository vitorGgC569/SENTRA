"""GATE-5: explicit Machine/Capability inventory without host/SDK discovery."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from sentra_runtime.contracts import Machine, OperationRequest, PolicyDecision
from sentra_runtime.executor import ExecutorRegistry, AuthorizationRequired
from sentra_executors import (
    WindowsUIABinding, DaytonaBinding, declare_daytona_machine,
    declare_windows_machine, plan_read_only_tk_lab,
)


def run(coro):
    return asyncio.run(coro)


def policy(_req):
    return PolicyDecision(True, "lab granted")


class LabTitleBackend:
    def __init__(self):
        self.calls = []

    def run(self, binding, args):
        self.calls.append((binding.pid, binding.hwnd, args.copy()))
        return {"pid": binding.pid, "hwnd": binding.hwnd,
                "window_title_sha256": "synthetic-lab-title-hash"}


def test_declarative_windows_inventory_does_not_perform_uia_actions():
    backend = LabTitleBackend()
    binding = WindowsUIABinding(
        "lab-title", 101, 201, "SENTRA-UIA-LAB-ABC",
        allowed_automation_ids=("_unused",),
        allowed_actions=("read_window_title",))
    declaration = declare_windows_machine(
        machine_id="win-1", owner_principal_id="lab",
        bindings=(binding,), policy=policy, backend=backend)
    capabilities = run(declaration.discover())
    assert isinstance(declaration.machine, Machine)
    assert declaration.machine.kind == "windows_uia"
    assert [c.capability_id for c in capabilities] == ["lab-title"]
    assert capabilities[0].risk_level == "high"
    assert backend.calls == []  # NO application/window enumeration
    registry = ExecutorRegistry(authorize=policy)
    declaration.register(registry)
    assert registry.machines() == (declaration.machine,)


def test_declarative_daytona_inventory_never_initializes_sdk():
    class ForbiddenBackend:
        def run(self, *_args):
            pytest.fail("remote invocation during discovery")
    declaration = declare_daytona_machine(
        machine_id="daytona-1", owner_principal_id="lab",
        bindings=(DaytonaBinding(
            "allowlist-check", "already-owned-sandbox", ("echo check",)),),
        policy=policy, backend=ForbiddenBackend())
    caps = run(declaration.discover())
    assert [c.capability_id for c in caps] == ["allowlist-check"]
    assert declaration.machine.kind == "daytona"
    assert caps[0].risk_level == "high"


@pytest.mark.parametrize("target", ["notebook personal", "SENTRA-SOME-OTHER-WINDOW", ""])
def test_lab_rejects_unapproved_window_title(target):
    with pytest.raises(ValueError, match="only_sentra_laboratory_window_permitted"):
        plan_read_only_tk_lab(
            machine_id="lab", owner_principal_id="lab",
            pid=10, hwnd=20, window_title=target, policy=policy)


@pytest.mark.parametrize("pid,hwnd", [(0, 20), (10, 0), (True, 20), (10, False)])
def test_lab_requires_exact_positive_integer_pid_and_hwnd(pid, hwnd):
    with pytest.raises(ValueError, match="invalid_lab_target"):
        plan_read_only_tk_lab(
            machine_id="lab", owner_principal_id="lab", pid=pid, hwnd=hwnd,
            window_title="SENTRA-UIA-LAB-ABC", policy=policy)


def test_lab_fails_without_trusted_callback():
    with pytest.raises(ValueError, match="lab_requires_trusted_policy_callback"):
        plan_read_only_tk_lab(
            machine_id="lab", owner_principal_id="lab",
            pid=10, hwnd=20, window_title="SENTRA-UIA-LAB-ABC",
            policy=None)


def test_lab_read_only_request_through_actual_registry():
    backend = LabTitleBackend()
    plan = plan_read_only_tk_lab(
        machine_id="lab", owner_principal_id="friend",
        pid=10, hwnd=20, window_title="SENTRA-UIA-LAB-ABC",
        policy=policy, backend=backend)
    assert plan.binding.allowed_actions == ("read_window_title",)
    assert plan.binding.allowed_control_types == ("Text",)
    registry = ExecutorRegistry(authorize=policy)
    plan.declaration.register(registry)
    request = plan.request(
        operation_id="read-1", idempotency_key="key-1", work_item_id="work-1")
    assert isinstance(request, OperationRequest)
    assert request.arguments == {"pid": 10, "hwnd": 20, "action": "read_window_title"}
    result = run(registry.submit(request))
    assert result.state == "SUCCEEDED"
    assert len(backend.calls) == 1
    assert backend.calls[0][2] == dict(request.arguments)


def test_lab_cannot_request_invoke_or_other_window():
    backend = LabTitleBackend()
    plan = plan_read_only_tk_lab(
        machine_id="lab", owner_principal_id="friend",
        pid=10, hwnd=20, window_title="SENTRA-UIA-LAB-ABC",
        policy=policy, backend=backend)
    registry = ExecutorRegistry(authorize=policy)
    plan.declaration.register(registry)
    base = plan.request(operation_id="lab-1", idempotency_key="key-1",
                        work_item_id="work-1")
    async def scenario():
        for op, args in (
            ("invoke", {"pid": 10, "hwnd": 20, "action": "invoke"}),
            ("wrong-window", {"pid": 10, "hwnd": 21,
                              "action": "read_window_title"}),
        ):
            attempted = OperationRequest(
                operation_id=op, principal_id=base.principal_id,
                machine_id=base.machine_id, capability_id=base.capability_id,
                work_item_id=base.work_item_id, idempotency_key="key-" + op,
                arguments=args)
            result = await registry.submit(attempted)
            assert result.state == "FAILED"
            assert result.error == "invalid_scope_or_capability"
    run(scenario())
    assert backend.calls == []


def test_lab_denies_without_registry_policy():
    backend = LabTitleBackend()
    plan = plan_read_only_tk_lab(
        machine_id="lab", owner_principal_id="friend",
        pid=10, hwnd=20, window_title="SENTRA-UIA-LAB-ABC",
        policy=policy, backend=backend)
    registry = ExecutorRegistry(authorize=None)
    plan.declaration.register(registry)
    with pytest.raises(AuthorizationRequired):
        run(registry.submit(plan.request(
            operation_id="lab-1", idempotency_key="lab-key",
            work_item_id="lab-work")))
    assert backend.calls == []


def test_duplicate_capabilities_fail_before_advertising():
    a = WindowsUIABinding("dup", 1, 2, "lab", ("id",))
    b = WindowsUIABinding("dup", 1, 3, "lab", ("id",))
    with pytest.raises(ValueError, match="missing_or_duplicate_capabilities"):
        declare_windows_machine(machine_id="win", owner_principal_id="friend",
                                bindings=(a, b), policy=policy)
