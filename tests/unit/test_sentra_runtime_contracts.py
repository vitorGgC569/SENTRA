"""Tests for the optional fail-closed Machine/Executor integration boundary."""
import asyncio

import pytest

from sentra_runtime import (
    AuthorizationRequired, Capability, DuplicateOperation, ExecutorRegistry,
    InvalidOperation, Machine, OperationRequest, OperationResult, PolicyDecision,
)


class DummyExecutor:
    def __init__(self):
        self.started = []
        self.reconciled = []

    async def discover(self, machine):
        return machine.capabilities

    async def start(self, request):
        self.started.append(request.operation_id)
        return OperationResult(request.operation_id, "ACCEPTED")

    async def observe(self, operation_id):
        return OperationResult(operation_id, "RUNNING")

    async def cancel(self, operation_id):
        return OperationResult(operation_id, "CANCELLED")

    async def reconcile(self, operation_id):
        self.reconciled.append(operation_id)
        return OperationResult(operation_id, "UNCERTAIN")

    async def cleanup(self, operation_id):
        return None


def request(**kwargs):
    fields = dict(operation_id="op-1", principal_id="friend-1",
                  machine_id="machine-1", capability_id="window.inspect",
                  work_item_id="work-1", idempotency_key="idem-1",
                  arguments={"pid": 12})
    fields.update(kwargs)
    return OperationRequest(**fields)


def setup(check):
    registry = ExecutorRegistry(check)
    adapter = DummyExecutor()
    registry.register(Machine("machine-1", "windows", "friend-1",
                              (Capability("window.inspect", "Inspect window"),)),
                      adapter)
    return registry, adapter


def test_missing_policy_blocks_before_execution():
    registry, adapter = setup(None)
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(request()))
    assert adapter.started == []


def test_unknown_machine_or_capability_blocks_even_with_policy_allow():
    registry, adapter = setup(lambda _: PolicyDecision(True, "allowed"))
    for invalid in (request(machine_id="other"), request(capability_id="shell.root")):
        with pytest.raises(InvalidOperation):
            asyncio.run(registry.submit(invalid))
    assert adapter.started == []


def test_denied_and_broken_policy_fail_closed():
    def broken(_request):
        raise RuntimeError("unavailable")
    for check in (lambda _: PolicyDecision(False, "grant missing"), broken):
        registry, adapter = setup(check)
        with pytest.raises(AuthorizationRequired):
            asyncio.run(registry.submit(request()))
        assert adapter.started == []


def test_authorized_idempotent_reconciliation():
    registry, adapter = setup(lambda _: PolicyDecision(True, "test-grant"))
    assert asyncio.run(registry.submit(request())).state == "ACCEPTED"
    assert asyncio.run(registry.submit(request())).state == "UNCERTAIN"
    assert adapter.started == ["op-1"]
    assert adapter.reconciled == ["op-1"]
    with pytest.raises(DuplicateOperation):
        asyncio.run(registry.submit(request(operation_id="op-2")))
    with pytest.raises(DuplicateOperation):
        asyncio.run(registry.submit(request(arguments={"pid": 99})))


def test_uncertain_side_effect_is_not_resent():
    registry, adapter = setup(lambda _: PolicyDecision(True, "granted"))
    async def uncertain(req):
        adapter.started.append(req.operation_id)
        raise TimeoutError("response lost, effect unknown")
    adapter.start = uncertain
    with pytest.raises(TimeoutError):
        asyncio.run(registry.submit(request()))
    assert asyncio.run(registry.submit(request())).state == "UNCERTAIN"
    assert adapter.started == ["op-1"]


def test_invalid_contracts_and_duplicate_registration():
    registry, _ = setup(lambda _: PolicyDecision(True, "granted"))
    with pytest.raises(InvalidOperation):
        registry.register(Machine("machine-1", "windows", "friend-1"), DummyExecutor())
    with pytest.raises(ValueError):
        request(idempotency_key="")
    with pytest.raises(ValueError):
        Machine("m", "windows", "user", (Capability("a", "x"), Capability("a", "x")))
    with pytest.raises(ValueError):
        Capability("a", "cap", "dangerously-unknown")


def test_async_policy_and_lifecycle():
    async def policy(_):
        return PolicyDecision(True, "asynchronous grant")
    registry, _ = setup(policy)
    assert asyncio.run(registry.submit(request())).state == "ACCEPTED"
    assert asyncio.run(registry.observe("op-1")).state == "RUNNING"
    assert asyncio.run(registry.cancel("op-1")).state == "CANCELLED"
    asyncio.run(registry.cleanup("op-1"))
    with pytest.raises(InvalidOperation):
        asyncio.run(registry.reconcile("not-found"))


def test_constraints_fail_closed_before_any_side_effect():
    registry, adapter = setup(
        lambda _: PolicyDecision(True, "restricted grant", {"allowed_pid": 12})
    )
    with pytest.raises(AuthorizationRequired, match="constrained grants"):
        asyncio.run(registry.submit(request()))
    assert adapter.started == []


def test_concurrent_duplicate_submission_does_not_double_execute():
    registry, adapter = setup(lambda _: PolicyDecision(True, "granted"))
    async def delayed(request):
        await asyncio.sleep(.03)
        adapter.started.append(request.operation_id)
        return OperationResult(request.operation_id, "ACCEPTED")
    adapter.start = delayed
    async def both():
        return await asyncio.gather(
            registry.submit(request()), registry.submit(request())
        )
    first, second = asyncio.run(both())
    assert first.state == "ACCEPTED"
    assert second.state == "UNCERTAIN"
    assert adapter.started == ["op-1"]


def test_submitted_operation_freezes_caller_owned_nested_intent():
    """A caller cannot reuse success evidence after mutating argument dictionaries."""
    r, adapter = setup(lambda _: PolicyDecision(True, "approved"))
    mutable = {"pid": 123, "selector": {"id": "original"}}
    req = request(arguments=mutable)
    assert asyncio.run(r.submit(req)).state == "ACCEPTED"
    mutable["selector"]["id"] = "new-unauthorized-selector"
    with pytest.raises(DuplicateOperation, match="payload"):
        asyncio.run(r.submit(req))
    original = r.operation_request("op-1")
    assert original.arguments == {"pid": 123, "selector": {"id": "original"}}
    original.arguments["selector"]["id"] = "changed-through-lookup"
    assert r.operation_request("op-1").arguments["selector"]["id"] == "original"
    assert adapter.started == ["op-1"]


@pytest.mark.parametrize("value", [
    object(), float("nan"), {1, 2}, {"cyclic": object()},
])
def test_noncanonical_request_rejected_before_policy(value):
    called = []
    r, adapter = setup(lambda req: called.append(req) or PolicyDecision(True, "allow"))
    with pytest.raises(InvalidOperation, match="serialized"):
        asyncio.run(r.submit(request(arguments={"object": value})))
    assert called == []
    assert adapter.started == []


def test_policy_cannot_mutate_its_own_authorized_request():
    async def policy(request):
        request.arguments["pid"] = 999
        return PolicyDecision(True, "unsafe mutation")
    r, adapter = setup(policy)
    with pytest.raises(AuthorizationRequired, match="altered"):
        asyncio.run(r.submit(request()))
    assert adapter.started == []


def test_equal_intent_with_different_dict_insertion_order_reconciles():
    registry, adapter = setup(lambda _: PolicyDecision(True, "approved"))
    req = request(arguments={"pid": 123, "role": "readonly"})
    assert asyncio.run(registry.submit(req)).state == "ACCEPTED"
    identical = request(arguments={"role": "readonly", "pid": 123})
    assert asyncio.run(registry.submit(identical)).state == "UNCERTAIN"
    assert adapter.started == ["op-1"]

def test_async_policy_cannot_mutate_request_after_admission():
    """The policy's reference must not be the request observed by the executor."""
    retained = []

    def policy(intent):
        retained.append(intent)
        return PolicyDecision(True, "authorized")

    registry = ExecutorRegistry(policy)
    entered = asyncio.Event()
    release = asyncio.Event()

    class DelayedExecutor(DummyExecutor):
        observed_pid = None

        async def start(self, intent):
            entered.set()
            await release.wait()
            self.observed_pid = intent.arguments["pid"]
            self.started.append(intent.operation_id)
            return OperationResult(intent.operation_id, "ACCEPTED")

    adapter = DelayedExecutor()
    registry.register(
        Machine("machine-1", "windows", "friend-1",
                (Capability("window.inspect", "Inspect window"),)), adapter,
    )

    async def scenario():
        task = asyncio.create_task(registry.submit(request()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        retained[0].arguments["pid"] = 999
        release.set()
        assert (await task).state == "ACCEPTED"

    asyncio.run(scenario())
    assert adapter.observed_pid == 12
    assert registry.operation_request("op-1").arguments["pid"] == 12
    assert adapter.started == ["op-1"]
