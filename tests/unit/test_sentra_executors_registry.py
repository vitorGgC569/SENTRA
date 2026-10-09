"""Cross-module contract tests: real SENTRA registry, policy and operation types.

The only mocked component is the platform side effect. There is no registry
bypass and no substituted implementation of sentra_runtime.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sentra_runtime.contracts import (
    Capability, Machine, OperationRequest, OperationResult, PolicyDecision,
)
from sentra_runtime.executor import (
    AuthorizationRequired, DuplicateOperation, ExecutorRegistry, InvalidOperation,
)
from sentra_executors import (
    DaytonaBinding, DaytonaExecutor, DaytonaSDKBackend,
    WindowsUIABinding, WindowsUIAExecutor,
)


class MutablePolicy:
    def __init__(self, *, allowed=True, constraints=None):
        self.allowed = allowed
        self.constraints = {} if constraints is None else constraints
        self.calls: list[str] = []

    async def __call__(self, request: OperationRequest) -> PolicyDecision:
        self.calls.append(request.operation_id)
        await asyncio.sleep(0)
        return PolicyDecision(self.allowed, "live-grant" if self.allowed else "revoked",
                              self.constraints)


class WindowBackend:
    def __init__(self, *, blocking=False):
        self.calls: list[dict] = []
        self.blocking = blocking
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, binding, args):
        self.entered.set()
        if self.blocking and not self.release.wait(5):
            raise TimeoutError("lab backend was not released")
        self.calls.append(dict(args))
        return {"pid": binding.pid, "hwnd": binding.hwnd, "action": args["action"]}


def window_setup(policy, backend):
    machine = Machine(
        machine_id="lab-windows", kind="windows_uia",
        owner_principal_id="lab-principal",
        capabilities=(Capability("lab-button", "test-only Windows UIA", "high"),),
    )
    adapter = WindowsUIAExecutor(
        machine_id=machine.machine_id, owner_principal_id=machine.owner_principal_id,
        bindings=(WindowsUIABinding(
            capability_id="lab-button", pid=10051, hwnd=10052, window_title="SENTRA lab",
            allowed_automation_ids=("lab_button",), allowed_control_types=("Button",),
            allowed_actions=("invoke",), timeout_seconds=4.0,
        ),),
        policy=policy,
        backend=backend,
    )
    registry = ExecutorRegistry(authorize=policy)
    registry.register(machine, adapter)
    request = OperationRequest(
        operation_id="lab-op", principal_id="lab-principal",
        machine_id="lab-windows", capability_id="lab-button",
        work_item_id="lab-work", idempotency_key="lab-key",
        arguments={"pid": 10051, "hwnd": 10052, "action": "invoke",
                   "automation_id": "lab_button", "control_type": "Button"},
    )
    return machine, adapter, registry, request


def run(coro):
    return asyncio.run(coro)


def test_registry_accepts_real_window_adapter_and_canonical_decision():
    policy, backend = MutablePolicy(), WindowBackend()
    machine, adapter, registry, req = window_setup(policy, backend)

    async def scenario():
        advertised = await adapter.discover(machine)
        first = await registry.submit(req)
        observed = await registry.observe(req.operation_id)
        cleanup_return = await registry.cleanup(req.operation_id)
        return advertised, first, observed, cleanup_return

    advertised, first, observed, cleanup_return = run(scenario())
    assert isinstance(advertised[0], Capability)
    assert advertised[0].risk_level == "high"
    assert type(first) is OperationResult
    assert first.state == observed.state == "SUCCEEDED"
    assert first.operation_id == req.operation_id
    assert cleanup_return is None
    assert len(backend.calls) == 1
    assert len(policy.calls) >= 4  # registry + adapter pre/pre/post checks


@pytest.mark.parametrize("mode", ("no-registry-auth", "no-adapter-auth", "revoked",
                                  "restricted-by-registry"))
def test_registry_never_bypasses_either_policy_boundary(mode):
    policy, backend = MutablePolicy(), WindowBackend()
    machine, adapter, registry, req = window_setup(policy, backend)
    if mode == "no-registry-auth":
        registry = ExecutorRegistry(authorize=None)
        registry.register(machine, adapter)
    elif mode == "no-adapter-auth":
        adapter.policy = None
    elif mode == "revoked":
        policy.allowed = False
    else:
        policy.constraints = {"allowed_pids": [10051]}
    async def scenario():
        if mode == "no-adapter-auth":
            return await registry.submit(req)
        with pytest.raises(AuthorizationRequired):
            await registry.submit(req)
    result = run(scenario())
    if mode == "no-adapter-auth":
        assert type(result) is OperationResult
        assert result.state == "FAILED"
        assert result.error == "policy_denied"
    assert backend.calls == []


def test_registry_rejects_unknown_capability_and_machine_before_side_effect():
    policy, backend = MutablePolicy(), WindowBackend()
    _machine, _adapter, registry, req = window_setup(policy, backend)
    async def scenario():
        with pytest.raises(InvalidOperation):
            await registry.submit(replace(req, capability_id="unregistered"))
        with pytest.raises(InvalidOperation):
            await registry.submit(replace(req, machine_id="unregistered"))
    run(scenario())
    assert backend.calls == []
    assert policy.calls == []


def test_registry_rejects_same_operation_changed_arguments_and_reused_key():
    policy, backend = MutablePolicy(), WindowBackend()
    _machine, _adapter, registry, req = window_setup(policy, backend)
    async def scenario():
        good = await registry.submit(req)
        with pytest.raises(DuplicateOperation):
            await registry.submit(replace(
                req, arguments={**req.arguments, "automation_id": "different"}))
        with pytest.raises(DuplicateOperation):
            await registry.submit(replace(
                req, operation_id="another-op"))
        return good, await registry.reconcile(req.operation_id)
    a, observed = run(scenario())
    assert a.state == observed.state == "SUCCEEDED"
    assert len(backend.calls) == 1


def test_adapter_direct_replay_changed_payload_is_not_false_success():
    # A second caller must not obtain the first result with a changed payload,
    # even if it invokes the adapter directly without the registry.
    policy, backend = MutablePolicy(), WindowBackend()
    _, adapter, _, req = window_setup(policy, backend)
    async def scenario():
        first = await adapter.start(req)
        impostor = await adapter.start(replace(req, work_item_id="other-work"))
        return first, impostor
    first, impostor = run(scenario())
    assert first.state == "SUCCEEDED"
    assert impostor.state == "FAILED"
    assert impostor.error == "idempotency_conflict"
    assert len(backend.calls) == 1


def test_registry_concurrent_duplicate_is_single_side_effect():
    policy, backend = MutablePolicy(), WindowBackend(blocking=True)
    _machine, _adapter, registry, req = window_setup(policy, backend)

    async def scenario():
        first = asyncio.create_task(registry.submit(req))
        try:
            assert await asyncio.to_thread(backend.entered.wait, 2)
            duplicate = asyncio.create_task(registry.submit(req))
            await asyncio.sleep(0)
        finally:
            backend.release.set()
        return await asyncio.gather(first, duplicate)
    a, b = run(scenario())
    assert a.state == b.state == "SUCCEEDED"
    assert len(backend.calls) == 1
    assert policy.calls.count("lab-op") >= 4


def test_registry_revocation_during_inflight_and_queued_operation():
    policy, backend = MutablePolicy(), WindowBackend(blocking=True)
    _machine, _adapter, registry, req = window_setup(policy, backend)

    async def scenario():
        inflight = asyncio.create_task(registry.submit(req))
        try:
            assert await asyncio.to_thread(backend.entered.wait, 2)
            queued = asyncio.create_task(registry.submit(replace(
                req, operation_id="queued-op", idempotency_key="queued-key")))
            await asyncio.sleep(0)
            policy.allowed = False
        finally:
            backend.release.set()
        completed = await inflight
        with pytest.raises(AuthorizationRequired):
            await queued
        # The registry must reauthorize EVERY submit, including the same
        # operation_id/idempotency_key. Revocation closes the replay path.
        with pytest.raises(AuthorizationRequired, match="revoked"):
            await registry.submit(req)
        return completed

    completed = run(scenario())
    assert completed.state == "UNCERTAIN"
    assert completed.error == "policy_revoked_after_dispatch"
    assert completed.evidence == {}
    assert len(backend.calls) == 1
    assert "queued-op" in policy.calls
    assert policy.calls.count("lab-op") >= 5


def test_registry_cancel_inflight_remains_uncertain():
    policy, backend = MutablePolicy(), WindowBackend(blocking=True)
    _, _, registry, req = window_setup(policy, backend)

    async def scenario():
        task = asyncio.create_task(registry.submit(req))
        try:
            assert await asyncio.to_thread(backend.entered.wait, 2)
            cancelled = await registry.cancel(req.operation_id)
        finally:
            backend.release.set()
        completed = await task
        observed = await registry.observe(req.operation_id)
        return cancelled, completed, observed

    a, b, c = run(scenario())
    assert a.state == b.state == c.state == "UNCERTAIN"
    assert len(backend.calls) == 1


def test_registry_daytona_sdk_boundary_without_real_daemon():
    policy = MutablePolicy()

    class Sandbox:
        id = "lab-sandbox"
        public = False
        network_block_all = True
        state = "started"

        def __init__(self):
            self.commands = []
            self.process = self

        def exec(self, command, timeout):
            self.commands.append((command, timeout))
            return SimpleNamespace(exit_code=0, result="lab output")

    class SDK:
        def __init__(self):
            self.sandbox = Sandbox()
            self.lookups = []

        def get(self, sandbox_id):
            self.lookups.append(sandbox_id)
            return self.sandbox

    sdk = SDK()
    machine = Machine("lab-daytona", "daytona", "lab-principal",
                      (Capability("sandbox-command", "Sandbox check", "high"),))
    adapter = DaytonaExecutor(
        machine_id="lab-daytona", owner_principal_id="lab-principal",
        bindings=(DaytonaBinding("sandbox-command", "lab-sandbox",
                                 ("echo lab",), timeout_seconds=5),),
        policy=policy, backend=DaytonaSDKBackend(client=sdk),
    )
    registry = ExecutorRegistry(authorize=policy)
    registry.register(machine, adapter)
    req = OperationRequest("daytona-op", "lab-principal", "lab-daytona",
                           "sandbox-command", "lab-work", "daytona-key",
                           {"action": "exec", "sandbox_id": "lab-sandbox",
                            "command": "echo lab"})

    async def scenario():
        advertised = await adapter.discover(machine)
        actual = await registry.submit(req)
        return advertised, actual, await registry.observe("daytona-op")

    caps, actual, observed = run(scenario())
    assert caps[0].capability_id == "sandbox-command"
    assert type(actual) is OperationResult
    assert actual.state == observed.state == "SUCCEEDED"
    assert sdk.lookups == ["lab-sandbox"]
    assert sdk.sandbox.commands == [("echo lab", 5)]
    assert "lab output" not in str(actual.evidence)
