"""GATE-3: real control-plane registry and policies with deterministic mock effects.

A mock backend tests the authorization *boundary*, not OS isolation, UIA
behavior, Daytona network policy enforcement, or remote sandbox existence.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import threading
from types import SimpleNamespace

import pytest

from sentra_executors import (
    DaytonaBinding, DaytonaExecutor, DaytonaSDKBackend,
    WindowsUIABinding, WindowsUIAExecutor,
)
from sentra_runtime.contracts import (
    Capability, Machine, OperationRequest, OperationResult, PolicyDecision,
)
from sentra_runtime.executor import AuthorizationRequired, DuplicateOperation, ExecutorRegistry


class Grant:
    def __init__(self):
        self.allowed = True
        self.fail = False
        self.calls = []
        self.max_allowed_checks = None

    async def __call__(self, request):
        self.calls.append(request.operation_id)
        await asyncio.sleep(0)
        if self.fail:
            raise RuntimeError("policy service unavailable")
        permitted = self.allowed and (
            self.max_allowed_checks is None or
            len(self.calls) <= self.max_allowed_checks
        )
        return PolicyDecision(permitted, "live authorization" if permitted else "revoked")


class HeldEffect:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()
        self.calls = 0

    def run(self, binding, arguments):
        self.calls += 1
        self.entered.set()
        try:
            if not self.release.wait(2):
                raise TimeoutError("backend remained blocked")
            return {"marker": "lab-result"}
        finally:
            self.completed.set()


class Sandbox:
    id = "owned-lab"
    public = False
    network_block_all = True
    state = "started"

    def __init__(self, effect):
        self.effect = effect
        self.process = self

    def exec(self, command, timeout):
        result = self.effect.run(self, {"command": command, "timeout": timeout})
        return SimpleNamespace(exit_code=0, result=result["marker"])


class SDK:
    def __init__(self, effect):
        self.sandbox = Sandbox(effect)
        self.lookups = 0

    def get(self, sandbox_id):
        self.lookups += 1
        return self.sandbox


def setup(kind, *, timeout=0.08):
    policy = Grant()
    effect = HeldEffect()
    sdk = None
    if kind == "windows":
        machine = Machine("lab-win", "windows_uia", "lab",
                          (Capability("lab-uia", "lab window", "high"),))
        adapter = WindowsUIAExecutor(
            machine_id="lab-win", owner_principal_id="lab",
            bindings=(WindowsUIABinding(
                capability_id="lab-uia", pid=10505, hwnd=20505,
                window_title="SENTRA-TK-LAB", allowed_automation_ids=("test",),
                allowed_control_types=("Button",), allowed_actions=("invoke",),
                timeout_seconds=timeout,
            ),),
            policy=policy, backend=effect,
        )
        request = OperationRequest(
            operation_id="op-1", principal_id="lab", machine_id="lab-win",
            capability_id="lab-uia", work_item_id="work-1", idempotency_key="key-1",
            arguments={"pid": 10505, "hwnd": 20505, "action": "invoke",
                       "automation_id": "test", "control_type": "Button"},
        )
    elif kind == "daytona":
        machine = Machine("lab-daytona", "daytona", "lab",
                          (Capability("lab-command", "approved sandbox command", "high"),))
        sdk = SDK(effect)
        adapter = DaytonaExecutor(
            machine_id="lab-daytona", owner_principal_id="lab",
            bindings=(DaytonaBinding(
                "lab-command", "owned-lab", ("echo gate3",), timeout_seconds=timeout,
            ),),
            policy=policy, backend=DaytonaSDKBackend(client=sdk),
        )
        request = OperationRequest(
            operation_id="op-1", principal_id="lab", machine_id="lab-daytona",
            capability_id="lab-command", work_item_id="work-1", idempotency_key="key-1",
            arguments={"action": "exec", "sandbox_id": "owned-lab",
                       "command": "echo gate3"},
        )
    else:
        raise ValueError(kind)
    registry = ExecutorRegistry(authorize=policy)
    registry.register(machine, adapter)
    return registry, adapter, policy, effect, sdk, request


@pytest.mark.parametrize("kind", ["windows", "daytona"])
def test_gate3_registry_policy_failure_is_closed(kind):
    registry, _adapter, policy, effect, sdk, request = setup(kind)
    policy.fail = True

    async def scenario():
        with pytest.raises(AuthorizationRequired):
            await registry.submit(request)
    asyncio.run(scenario())
    assert effect.calls == 0
    assert policy.calls == ["op-1"]
    if sdk is not None:
        assert sdk.lookups == 0


@pytest.mark.parametrize("kind", ["windows", "daytona"])
def test_gate3_registry_adapter_policy_absence_is_not_a_bypass(kind):
    registry, adapter, policy, effect, sdk, request = setup(kind)
    adapter.policy = None

    async def scenario():
        return await registry.submit(request)
    result = asyncio.run(scenario())
    assert type(result) is OperationResult
    assert result.state == "FAILED"
    assert result.error == "policy_denied"
    assert effect.calls == 0
    assert policy.calls == ["op-1"]
    if sdk is not None:
        assert sdk.lookups == 0


@pytest.mark.parametrize("kind", ["windows", "daytona"])
def test_gate3_revocation_midflight_and_concurrent_queued_denial(kind):
    registry, _adapter, policy, effect, sdk, request = setup(kind, timeout=1.5)

    async def scenario():
        first = asyncio.create_task(registry.submit(request))
        try:
            assert await asyncio.to_thread(effect.entered.wait, 1)
            second = asyncio.create_task(registry.submit(replace(
                request, operation_id="op-2", idempotency_key="key-2")))
            await asyncio.sleep(0)
            policy.allowed = False
        finally:
            effect.release.set()
        first_result = await first
        with pytest.raises(AuthorizationRequired):
            await second
        # The revoked principal may not fetch a previous result by
        # submitting its old request. No unguarded observe/reconcile.
        with pytest.raises(AuthorizationRequired, match="revoked"):
            await registry.submit(request)
        return first_result

    result = asyncio.run(scenario())
    assert result.state == "UNCERTAIN"
    assert not result.evidence
    assert result.error == "policy_revoked_after_dispatch"
    assert effect.calls == 1
    assert "op-2" in policy.calls
    assert policy.calls.count("op-1") >= 5
    if sdk is not None:
        assert sdk.lookups == 1


@pytest.mark.parametrize("kind", ["windows", "daytona"])
def test_gate3_timeout_is_uncertain_and_never_replayed(kind):
    registry, _adapter, policy, effect, sdk, request = setup(kind, timeout=0.06)

    async def scenario():
        first = asyncio.create_task(registry.submit(request))
        try:
            assert await asyncio.to_thread(effect.entered.wait, 1)
            timed_out = await first
            before_release = await registry.reconcile("op-1")
            repeated = await registry.submit(request)
        finally:
            effect.release.set()
        assert await asyncio.to_thread(effect.completed.wait, 1)
        after_completion = await registry.observe("op-1")
        return timed_out, before_release, repeated, after_completion

    results = asyncio.run(scenario())
    assert all(result.state == "UNCERTAIN" for result in results)
    assert all(result.error == "timeout_may_have_executed" for result in results)
    assert effect.calls == 1
    assert len(policy.calls) >= 3
    if sdk is not None:
        assert sdk.lookups == 1


@pytest.mark.parametrize("kind", ["windows", "daytona"])
def test_gate3_concurrent_duplicate_exactly_once(kind):
    registry, _adapter, policy, effect, sdk, request = setup(kind, timeout=1.5)

    async def scenario():
        first = asyncio.create_task(registry.submit(request))
        try:
            assert await asyncio.to_thread(effect.entered.wait, 1)
            second = asyncio.create_task(registry.submit(request))
            await asyncio.sleep(0)
        finally:
            effect.release.set()
        return await asyncio.gather(first, second)

    results = asyncio.run(scenario())
    assert all(result.state == "SUCCEEDED" for result in results)
    assert effect.calls == 1
    assert len(policy.calls) >= 4
    if sdk is not None:
        assert sdk.lookups == 1


@pytest.mark.parametrize("kind", ["windows", "daytona"])
def test_gate3_revoked_between_adapter_checks_never_dispatches(kind):
    registry, adapter, policy, effect, sdk, request = setup(kind)
    policy.max_allowed_checks = 2
    # The same trusted callback is registered via the public registry API.
    result = asyncio.run(registry.submit(request))
    assert result.state == "FAILED"
    assert result.error == "policy_revoked"
    assert len(policy.calls) == 3
    assert effect.calls == 0
    if sdk is not None:
        assert sdk.lookups == 0


@pytest.mark.parametrize("kind", ["windows", "daytona"])
def test_gate3_fake_policy_decision_never_authorizes(kind):
    registry, adapter, _policy, effect, sdk, request = setup(kind)
    fake = lambda _request: SimpleNamespace(allowed=True, constraints={})
    registered_machine = registry.get_machine(request.machine_id)
    registry = ExecutorRegistry(authorize=fake)
    registry.register(registered_machine, adapter)
    adapter.policy = fake

    async def scenario():
        with pytest.raises(AuthorizationRequired, match="invalid policy decision"):
            await registry.submit(request)

    asyncio.run(scenario())
    assert effect.calls == 0
    if sdk is not None:
        assert sdk.lookups == 0


def test_gate3_registry_should_reject_mutation_of_submitted_arguments():
    # GATE-5 regression proof: the core snapshots/fingerprints admission intent.
    # OperationRequest.arguments can be caller-owned and mutated later; reusing
    # the operation ID with altered intent MUST raise DuplicateOperation.
    # The prior SUCCEEDED result must not be returned for altered input.
    # No additional external effect is permitted.
    registry, _adapter, _policy, effect, _sdk, request = setup("windows")
    effect.release.set()

    async def scenario():
        first = await registry.submit(request)
        assert first.state == "SUCCEEDED"
        request.arguments["action"] = "unregistered_action"
        with pytest.raises(DuplicateOperation):
            await registry.submit(request)
        assert effect.calls == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["windows", "daytona"])
@pytest.mark.parametrize("completed_state", ["SUCCEEDED", "UNCERTAIN"])
def test_gate4_replay_renews_authorization_after_success_or_timeout(kind, completed_state):
    """No replay of historical results once policy is revoked/offline.

    Exercise the *actual* Registry.submit path, not a direct, unguarded
    adapter.observe/reconcile call. The only fake is the external effect.
    """
    timeout = 0.06 if completed_state == "UNCERTAIN" else 1.0
    registry, _adapter, policy, effect, sdk, request = setup(kind, timeout=timeout)

    async def scenario():
        if completed_state == "SUCCEEDED":
            effect.release.set()
            first = await registry.submit(request)
        else:
            pending = asyncio.create_task(registry.submit(request))
            try:
                assert await asyncio.to_thread(effect.entered.wait, 1)
                first = await pending
            finally:
                effect.release.set()
            assert await asyncio.to_thread(effect.completed.wait, 1)
        assert first.state == completed_state
        count_before_replays = len(policy.calls)
        policy.allowed = False
        with pytest.raises(AuthorizationRequired, match="revoked"):
            await registry.submit(request)
        policy.fail = True
        with pytest.raises(AuthorizationRequired, match="policy evaluation failed closed"):
            await registry.submit(request)
        assert len(policy.calls) == count_before_replays + 2
        return first

    first = asyncio.run(scenario())
    assert first.state == completed_state
    if completed_state == "UNCERTAIN":
        assert first.error == "timeout_may_have_executed"
    assert effect.calls == 1
    if sdk is not None:
        assert sdk.lookups == 1
