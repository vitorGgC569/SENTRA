"""Phase3 WinHCS: typed provider fixture, no actual Windows container HCS."""
from __future__ import annotations

import asyncio
import threading

import pytest
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.executor import ExecutorRegistry, AuthorizationRequired
from sentra_executors import HCSBinding, declare_winhcs_machine

DIGEST = "sha256:"+"a"*64
CID = "sentra-lab-winhcs-demo"


def go(c):
    return asyncio.run(c)


class Grant:
    allowed = True
    calls = 0
    def __call__(self, req):
        self.calls += 1
        return PolicyDecision(self.allowed, "lab policy")


class WinHCSFixture:
    def __init__(self):
        self.containers = {CID: "running"}
        self.calls = []

    def status(self, container_id):
        self.calls.append(("status", container_id))
        return self.containers[container_id]

    def terminate(self, container_id):
        self.calls.append(("terminate", container_id))
        self.containers[container_id] = "terminated"
        return "terminated"

    def create(self, container_id, image_digest):
        self.calls.append(("create", container_id, image_digest))
        self.containers[container_id] = "running"
        return "created"


def prepare(*, policy=None, provider=None, actions=("status", "terminate"),
            platform="win32", enable=False, approve=None):
    policy = policy or Grant()
    provider = provider if provider is not None else WinHCSFixture()
    binding = HCSBinding("hcs-lab", CID, DIGEST, actions)
    declaration = declare_winhcs_machine(
        machine_id="hcs-machine", owner_principal_id="lab",
        bindings=(binding,), policy=policy, provider=provider, platform=platform,
        allow_create=enable, approve_create=approve)
    registry = ExecutorRegistry(authorize=policy)
    declaration.register(registry)
    return registry, policy, provider, declaration


def req(action, op=None, cid=CID, digest=DIGEST):
    op = op or action + "-op"
    return OperationRequest(
        op, "lab", "hcs-machine", "hcs-lab", "work", op,
        {"action": action, "container_id": cid, "image_digest": digest})


def test_win_hcs_fixture_registry_status_kill_cleanup_idempotent():
    registry, grant, fixture, declaration = prepare()
    assert [x.capability_id for x in go(declaration.discover())] == ["hcs-lab"]
    assert go(registry.submit(req("status"))).evidence == {
        "container_id": CID, "state": "running"}
    killed = go(registry.submit(req("terminate")))
    assert killed.state == "SUCCEEDED" and killed.evidence["state"] == "terminated"
    replay = go(registry.submit(req("terminate")))
    another_key = go(registry.submit(req("terminate", op="terminate-again")))
    assert replay.state == another_key.state == "SUCCEEDED"
    assert fixture.calls.count(("terminate", CID)) == 1
    assert go(registry.submit(req("status", op="later-status"))).evidence["state"] == "terminated"
    grant.allowed = False
    with pytest.raises(AuthorizationRequired):
        go(registry.submit(req("status")))
    assert fixture.calls.count(("terminate", CID)) == 1


def test_hcs_create_disabled_by_default_even_if_action_is_advertised():
    registry, _, fixture, _ = prepare(actions=("status", "create", "terminate"))
    outcome = go(registry.submit(req("create")))
    assert outcome.state == "FAILED"
    assert not any(c[0] == "create" for c in fixture.calls)


def test_hcs_create_opt_in_needs_independent_approval():
    registry, _, fixture, _ = prepare(actions=("create",),
                                     enable=True, approve=lambda cid, digest: False)
    assert go(registry.submit(req("create"))).state == "FAILED"
    assert fixture.calls == []


def test_hcs_create_approved_but_only_pre_registered_id_and_digest():
    registry, _, fixture, _ = prepare(actions=("create", "status"),
                                     enable=True, approve=lambda cid, digest: (
                                         cid == CID and digest == DIGEST))
    result = go(registry.submit(req("create")))
    assert result.state == "SUCCEEDED"
    assert fixture.calls == [("create", CID, DIGEST)]
    repeated = go(registry.submit(req("create", op="create-again")))
    assert repeated.state == "SUCCEEDED"  # idempotent manager side
    assert fixture.calls == [("create", CID, DIGEST)]


@pytest.mark.parametrize("action,cid,digest", [
    ("exec", CID, DIGEST),
    ("kill_host", CID, DIGEST),
    ("terminate", "other-container", DIGEST),
    ("terminate", "../escape", DIGEST),
    ("terminate", CID, "sha256:"+"b"*64),
])
def test_hcs_rejects_unapproved_actions_image_and_container(action, cid, digest):
    registry, _, fixture, _ = prepare()
    result = go(registry.submit(req(action, cid=cid, digest=digest)))
    assert result.state == "FAILED" and result.error == "invalid_scope_or_capability"
    assert fixture.calls == []


def test_hcs_non_windows_fails_closed():
    registry, _, fixture, _ = prepare(platform="linux")
    result = go(registry.submit(req("status")))
    assert result.state == "FAILED" and fixture.calls == []


def test_hcs_absent_real_provider_denies_calls():
    registry, _, fixture, declaration = prepare()
    declaration.adapter.provider = None
    result = go(registry.submit(req("status")))
    assert result.state == "FAILED" and fixture.calls == []


def test_hcs_revocation_denied_before_container_operation():
    policy = Grant()
    policy.allowed = False
    registry, _, fixture, _ = prepare(policy=policy)
    with pytest.raises(AuthorizationRequired):
        go(registry.submit(req("terminate")))
    assert fixture.calls == []


def test_hcs_unknown_backend_status_fails_closed():
    registry, _, fixture, _ = prepare()
    fixture.containers[CID] = "RUNNING / HOST"
    result = go(registry.submit(req("status")))
    assert result.state == "FAILED" and result.evidence == {}


def test_hcs_timeout_or_fault_does_not_replay_uncertain_kill():
    class Ambiguous(WinHCSFixture):
        def terminate(self, container_id):
            self.calls.append(("terminate", container_id))
            raise TimeoutError("container could be terminated")
    fixture = Ambiguous()
    registry, _, _, _ = prepare(provider=fixture)
    first = go(registry.submit(req("terminate")))
    second = go(registry.submit(req("terminate", op="retry-new-id")))
    assert first.state == "UNCERTAIN"
    assert first.error == "timeout_may_have_executed"
    assert second.state == "FAILED"
    assert fixture.calls.count(("terminate", CID)) == 1


def test_hcs_binding_requires_explicit_lab_id_and_pinned_digest():
    with pytest.raises(ValueError):
        HCSBinding("hcs", "production", DIGEST)
    with pytest.raises(ValueError):
        HCSBinding("hcs", CID, "latest")
