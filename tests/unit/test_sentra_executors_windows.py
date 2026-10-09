"""Windows Machine Executor behavioral and safety contract tests."""
import asyncio
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from sentra_executors import WindowsUIABinding, WindowsUIAExecutor, PywinautoUIABackend
from sentra_runtime.contracts import Machine, Capability, PolicyDecision


@dataclass
class Request:
    operation_id: str = "op-1"
    idempotency_key: str = "key-1"
    work_item_id: str = "work-1"
    principal_id: str = "friend"
    machine_id: str = "local-win"
    capability_id: str = "button"
    arguments: dict = field(default_factory=lambda: {
        "pid": 4100, "hwnd": 9032, "action": "invoke",
        "automation_id": "confirm", "control_type": "Button"})


class FakeBackend:
    def __init__(self):
        self.calls = []
    def run(self, binding, arguments):
        self.calls.append((binding.pid, arguments["action"]))
        return {"pid": binding.pid, "action": arguments["action"]}


def executor(policy=lambda _req: PolicyDecision(True, "granted"), backend=None):
    return WindowsUIAExecutor(
        machine_id="local-win", owner_principal_id="friend",
        bindings=(WindowsUIABinding(
            capability_id="button", pid=4100, hwnd=9032, window_title="Test app",
            allowed_automation_ids=("confirm",),
            allowed_control_types=("Button",),
            allowed_actions=("invoke", "read_text"), timeout_seconds=0.12),),
        policy=policy, backend=backend or FakeBackend())


def run(coro):
    return asyncio.run(coro)


def test_success_and_discovery():
    backend = FakeBackend()
    e = executor(backend=backend)
    r = run(e.start(Request()))
    assert r.state == "SUCCEEDED"
    assert backend.calls == [(4100, "invoke")]
    machine = Machine("local-win", "windows_uia", "friend",
                      (Capability("button", "UIA action", risk_level="high"),))
    discovery = run(e.discover(machine))
    assert [cap.capability_id for cap in discovery] == ["button"]


@pytest.mark.parametrize("attr,value", [
    ("machine_id", "another-machine"),
    ("principal_id", "untrusted"),
    ("capability_id", "not-registered"),
])
def test_wrong_identity_or_capability_denied(attr, value):
    backend = FakeBackend()
    req = Request()
    setattr(req, attr, value)
    assert run(executor(backend=backend).start(req)).state == "FAILED"
    assert backend.calls == []


@pytest.mark.parametrize("bad_args", [
    {"pid": 4101, "hwnd": 9032, "action": "invoke", "automation_id": "confirm", "control_type": "Button"},
    {"pid": 4100, "hwnd": 9033, "action": "invoke", "automation_id": "confirm", "control_type": "Button"},
    {"pid": 4100, "hwnd": 9032, "action": "invoke", "automation_id": "other", "control_type": "Button"},
    {"pid": 4100, "hwnd": 9032, "action": "invoke", "automation_id": "confirm", "control_type": "Edit"},
    {"pid": 4100, "hwnd": 9032, "action": "type_keys", "automation_id": "confirm", "control_type": "Button"},
    {"pid": 4100, "hwnd": 9032, "action": "invoke", "automation_id": "confirm", "control_type": "Button", "extra": 1},
])
def test_window_selector_and_action_fail_closed(bad_args):
    backend = FakeBackend()
    req = Request(arguments=bad_args)
    assert run(executor(backend=backend).start(req)).state == "FAILED"
    assert backend.calls == []


@pytest.mark.parametrize("policy", [
    None,
    lambda _req: None,
    lambda _req: PolicyDecision(False, "denied"),
    lambda _req: SimpleNamespace(allowed=True, constraints={}),
    lambda _req: (_ for _ in ()).throw(RuntimeError("auth offline")),
    lambda _req: PolicyDecision(True, "restricted", {"allowed_pids": [99]}),
    lambda _req: PolicyDecision(True, "unknown-constraint", {"unknown": True}),
])
def test_no_policy_or_denial_never_executes(policy):
    backend = FakeBackend()
    assert run(executor(policy=policy, backend=backend).start(Request())).state == "FAILED"
    assert not backend.calls


def test_idempotency_both_operation_and_key():
    backend = FakeBackend()
    e = executor(backend=backend)
    async def scenario():
        first = await e.start(Request())
        second = await e.start(Request())
        conflict = await e.start(Request(operation_id="op-2"))
        return first, second, conflict, await e.reconcile("op-1")
    a, b, c, seen = run(scenario())
    assert (a.state, b.state, c.state, seen.state) == ("SUCCEEDED", "SUCCEEDED", "FAILED", "SUCCEEDED")
    assert len(backend.calls) == 1


def test_concurrent_duplicate_is_never_dispatched_twice():
    class BlockingBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()
        def run(self, binding, arguments):
            self.entered.set()
            assert self.release.wait(2)
            return super().run(binding, arguments)
    backend = BlockingBackend()
    e = executor(backend=backend)
    async def scenario():
        task = asyncio.create_task(e.start(Request()))
        await asyncio.to_thread(backend.entered.wait, 1)
        duplicate = await e.start(Request())
        backend.release.set()
        return duplicate, await task
    duplicate, original = run(scenario())
    assert duplicate.state == "RUNNING"
    assert original.state == "SUCCEEDED"
    assert len(backend.calls) == 1


def test_policy_revocation_before_dispatch():
    count = 0
    def policy(_request):
        nonlocal count
        count += 1
        return PolicyDecision(count == 1, "changing-grant")
    backend = FakeBackend()
    result = run(executor(policy=policy, backend=backend).start(Request()))
    assert result.state == "FAILED"
    assert backend.calls == []


def test_cancel_does_not_turn_ambiguous_effect_into_success():
    class BlockingBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()
        def run(self, binding, arguments):
            self.entered.set()
            assert self.release.wait(2)
            return super().run(binding, arguments)
    backend = BlockingBackend()
    e = executor(backend=backend)
    async def scenario():
        task = asyncio.create_task(e.start(Request()))
        await asyncio.to_thread(backend.entered.wait, 1)
        cancelled = await e.cancel("op-1")
        backend.release.set()
        return cancelled, await task, await e.reconcile("op-1")
    a, b, c = run(scenario())
    assert a.state == b.state == c.state == "UNCERTAIN"
    assert len(backend.calls) == 1


def test_backend_timeout_is_uncertain_not_retryable():
    class SlowBackend(FakeBackend):
        def run(self, binding, arguments):
            import time
            time.sleep(0.3)
            return super().run(binding, arguments)
    e = executor(backend=SlowBackend())
    async def scenario():
        timed = await e.start(Request())
        duplicated = await e.start(Request())
        return timed, duplicated
    timed, duplicated = run(scenario())
    assert timed.state == duplicated.state == "UNCERTAIN"
    assert timed.error == "timeout_may_have_executed"


def test_backend_failure_is_not_success():
    class Broken:
        def run(self, binding, arguments):
            raise RuntimeError("do not leak secrets")
    result = run(executor(backend=Broken()).start(Request()))
    assert result.state == "FAILED"
    assert result.error == "backend_error"


def test_real_pywin_uia_adapter_path_with_mocked_window(monkeypatch):
    import sys
    original_platform = sys.platform
    class Control:
        element_info = SimpleNamespace(process_id=4100, automation_id="confirm", control_type="Button")
        def top_level_parent(self):
            return SimpleNamespace(handle=9032)
        def is_enabled(self):
            return True
        def is_visible(self):
            return True
        def invoke(self):
            events.append("invoke")
    class Window:
        element_info = SimpleNamespace(process_id=4100, handle=9032)
        def window_text(self):
            return "Test app"
        def child_window(self, **kwargs):
            assert kwargs == {"auto_id": "confirm", "control_type": "Button"}
            return SimpleNamespace(wrapper_object=lambda: Control())
    events = []
    class Application:
        def __init__(self, backend):
            assert backend == "uia"
        def connect(self, **kwargs):
            assert kwargs == {"process": 4100}
            return self
        def window(self, **kwargs):
            assert kwargs == {"handle": 9032}
            return SimpleNamespace(wrapper_object=lambda: Window())
    import types
    stub = types.ModuleType("pywinauto")
    appmod = types.ModuleType("pywinauto.application")
    appmod.Application = Application
    monkeypatch.setitem(sys.modules, "pywinauto", stub)
    monkeypatch.setitem(sys.modules, "pywinauto.application", appmod)
    monkeypatch.setattr(sys, "platform", "win32")
    binding = executor().bindings["button"]
    result = PywinautoUIABackend().run(binding, Request().arguments)
    assert result["action"] == "invoke"
    assert events == ["invoke"]


def test_revocation_during_backend_execution_is_uncertain():
    backend = FakeBackend()
    grant_checks = 0

    def changing_policy(_request):
        nonlocal grant_checks
        grant_checks += 1
        return PolicyDecision(grant_checks <= 2, "changing-grant")

    e = executor(policy=changing_policy, backend=backend)
    result = run(e.start(Request()))
    assert result.state == "UNCERTAIN"
    assert result.error == "policy_revoked_after_dispatch"
    assert result.evidence == {}
    assert len(backend.calls) == 1
    assert run(e.reconcile("op-1")).state == "UNCERTAIN"
