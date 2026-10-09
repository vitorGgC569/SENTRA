"""Real SQLite SENTRA AuthorizationService <-> universal executor bridge tests."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sentra_mcp.services.authorization import AuthorizationService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.governance import GovernanceService
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import Capability, Machine, OperationRequest, OperationResult
from sentra_runtime.executor import AuthorizationRequired, ExecutorRegistry


class ReadOnlyLab:
    def __init__(self):
        self.calls: list[str] = []

    async def start(self, req):
        self.calls.append(req.operation_id)
        return OperationResult(req.operation_id, "SUCCEEDED", {"lab": True})

    async def reconcile(self, op):
        return OperationResult(op, "UNCERTAIN")


@pytest.fixture
def authority(tmp_path: Path):
    state = tmp_path / ".sentra"
    authorization = AuthorizationService(state)
    durable = DurableRunService(state)
    governance = GovernanceService(state, durable=durable)
    owner = "owner-one"
    durable.create_run(owner, run_id="run-test")
    item = governance.create_work_item(
        "run-test", owner, work_item_id="WI-A", objective="Verify safe execution",
        assignee_agent_id="builder", required_capabilities=["lab.inspect"],
    )
    assert item["state"] == "PENDING"
    try:
        yield authorization, durable, governance, owner
    finally:
        durable.close()


def _req(op="operation-1", key="key-1", **kwargs):
    params = dict(
        operation_id=op, principal_id="builder",
        machine_id="lab-machine", capability_id="lab.inspect",
        work_item_id="WI-A", idempotency_key=key, arguments={"mode": "read"},
    )
    params.update(kwargs)
    return OperationRequest(**params)


def _registry(policy):
    adapter = ReadOnlyLab()
    registry = ExecutorRegistry(policy)
    registry.register(
        Machine("lab-machine", "read-only", "owner-one",
                (Capability("lab.inspect", "Read lab telemetry"),)),
        adapter,
    )
    return registry, adapter


def _grant(auth, owner, *, conditions=None):
    return auth.grant(
        owner, principal_type="agent", principal_id="builder",
        capability="lab.inspect", scope_type="work_item",
        scope_id="WI-A", conditions=conditions,
    )


def test_no_grant_no_effect_even_if_work_item_running(authority):
    auth, _durable, governance, owner = authority
    governance.transition_work_item("WI-A", owner, "RUNNING")
    registry, adapter = _registry(
        BoundWorkItemPolicy(owner=owner, principal_type="agent",
                            authorization=auth, governance=governance))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req()))
    assert adapter.calls == []


def test_real_persisted_grant_is_authority_and_revoke_blocks_new_effect(authority):
    auth, _durable, governance, owner = authority
    governance.transition_work_item("WI-A", owner, "RUNNING")
    grant = _grant(auth, owner)
    registry, adapter = _registry(
        BoundWorkItemPolicy(owner=owner, principal_type="agent",
                            authorization=auth, governance=governance))
    result = asyncio.run(registry.submit(_req()))
    assert result.state == "SUCCEEDED"
    assert adapter.calls == ["operation-1"]
    auth.revoke(grant["grant_id"], owner)
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req(op="operation-2", key="key-2")))
    assert adapter.calls == ["operation-1"]


def test_work_item_must_exist_be_owned_and_running(authority):
    auth, _durable, governance, owner = authority
    _grant(auth, owner)
    policy = BoundWorkItemPolicy(
        owner=owner, principal_type="agent", authorization=auth,
        governance=governance)
    registry, adapter = _registry(policy)
    for req in (_req(), _req(work_item_id="WI-not-owned")):
        with pytest.raises(AuthorizationRequired):
            asyncio.run(registry.submit(req))
    governance.transition_work_item("WI-A", owner, "RUNNING")
    assert asyncio.run(registry.submit(_req())).state == "SUCCEEDED"
    assert adapter.calls == ["operation-1"]


def test_no_owner_shortcut_and_no_spoofed_principal(authority):
    auth, _durable, governance, owner = authority
    governance.transition_work_item("WI-A", owner, "RUNNING")
    # Even the owner must have an explicit grant: local_owner=False.
    registry, adapter = _registry(
        BoundWorkItemPolicy(owner=owner, principal_type="user",
                            authorization=auth, governance=governance))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req(principal_id=owner)))
    grant = _grant(auth, owner)
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req(principal_id="other")))
    assert adapter.calls == []


def test_cost_condition_requires_trusted_estimate(authority):
    auth, _durable, governance, owner = authority
    governance.transition_work_item("WI-A", owner, "RUNNING")
    _grant(auth, owner, conditions={"max_actual_cost": 2.0})
    registry, adapter = _registry(
        BoundWorkItemPolicy(owner=owner, principal_type="agent",
                            authorization=auth, governance=governance))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req()))
    assert not adapter.calls
    approved, adapter_2 = _registry(
        BoundWorkItemPolicy(owner=owner, principal_type="agent", authorization=auth,
                            governance=governance,
                            trusted_context=lambda _: {"actual_cost": 1.0}))
    assert asyncio.run(approved.submit(_req())).state == "SUCCEEDED"
    assert adapter_2.calls == ["operation-1"]
    denied, adapter_3 = _registry(
        BoundWorkItemPolicy(owner=owner, principal_type="agent", authorization=auth,
                            governance=governance,
                            trusted_context=lambda _: {"actual_cost": 5.0}))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(denied.submit(_req()))
    assert adapter_3.calls == []


def test_bound_owner_prevents_cross_owner_work_item(authority):
    auth, _durable, governance, _owner = authority
    registry, adapter = _registry(
        BoundWorkItemPolicy(owner="someone-else", principal_type="agent",
                            authorization=auth, governance=governance))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req()))
    assert adapter.calls == []


def test_unknown_assignment_and_capability_are_denied(authority):
    auth, _durable, governance, owner = authority
    governance.transition_work_item("WI-A", owner, "RUNNING")
    _grant(auth, owner)
    policy = BoundWorkItemPolicy(owner=owner, principal_type="agent",
                                 authorization=auth, governance=governance)
    registry, adapter = _registry(policy)
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req(principal_id="other-agent")))
    assert adapter.calls == []


@pytest.mark.parametrize("value", [float("nan"), -1.0, "5.0", None])
def test_invalid_trusted_cost_fails_closed(authority, value):
    auth, _durable, governance, owner = authority
    governance.transition_work_item("WI-A", owner, "RUNNING")
    _grant(auth, owner, conditions={"max_actual_cost": 9.0})
    registry, adapter = _registry(
        BoundWorkItemPolicy(owner=owner, principal_type="agent", authorization=auth,
                            governance=governance,
                            trusted_context=lambda _: {"actual_cost": value}))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req()))
    assert adapter.calls == []


def test_revoke_denies_existing_operation_replay_and_reconcile(authority):
    """Same operation id must not bypass live policy after grant revocation."""
    auth, _durable, governance, owner = authority
    governance.transition_work_item("WI-A", owner, "RUNNING")
    grant = _grant(auth, owner)
    policy = BoundWorkItemPolicy(owner=owner, principal_type="agent",
                                authorization=auth, governance=governance)
    registry, adapter = _registry(policy)
    assert asyncio.run(registry.submit(_req())).state == "SUCCEEDED"
    auth.revoke(grant["grant_id"], owner)
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req()))
    assert adapter.calls == ["operation-1"]


def test_cancelled_work_item_denies_new_action_or_replay(authority):
    """A grant cannot resurrect an already-cancelled WorkItem."""
    auth, _durable, governance, owner = authority
    governance.transition_work_item("WI-A", owner, "RUNNING")
    _grant(auth, owner)
    registry, adapter = _registry(
        BoundWorkItemPolicy(owner=owner, principal_type="agent",
                            authorization=auth, governance=governance))
    assert asyncio.run(registry.submit(_req())).state == "SUCCEEDED"
    governance.transition_work_item("WI-A", owner, "CANCELLED")
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req()))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(registry.submit(_req(op="operation-2", key="key-2")))
    assert adapter.calls == ["operation-1"]
