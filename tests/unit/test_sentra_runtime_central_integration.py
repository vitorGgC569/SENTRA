"""End-to-end real SENTRA ControlPlaneService + authorization + durable core.

Uses real SQLite/WAL from the *existing* Control Plane, not an alternate DB or
fake grant authority. Physical action is deliberately low-risk read-only lab.
"""
from __future__ import annotations

import asyncio

import pytest

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService, DurableStateConflict
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.central_authority import CentralDurableIntentAuthority
from sentra_runtime.contracts import Capability, Machine, OperationRequest, OperationResult
from sentra_runtime.durable_admission import DurableOperationGate, DurableAdmissionUnavailable
from sentra_runtime.executor import AuthorizationRequired, DuplicateOperation, ExecutorRegistry


class LocalLabReader:
    def __init__(self):
        self.calls = []

    async def start(self, request):
        self.calls.append(request.operation_id)
        return OperationResult(request.operation_id, "SUCCEEDED",
                               {"read_only": True, "fixture": "read-safe-status"})

    async def reconcile(self, operation_id):
        return OperationResult(operation_id, "UNCERTAIN")


def request(op_id="op-lab-1", key="idem-lab-1", **changes):
    data = {
        "operation_id": op_id, "idempotency_key": key,
        "principal_id": "agent-1", "machine_id": "machine-1",
        "capability_id": "lab.read", "work_item_id": "WI-LAB",
        "arguments": {"read": "title"},
    }
    data.update(changes)
    return OperationRequest(**data)


@pytest.fixture
def center(tmp_path):
    durable = DurableRunService(tmp_path)
    context = ContextBusService(tmp_path)
    core = ControlPlaneService(durable, context)
    owner, run_id = "owner-one", "run-lab-1"
    created = core.durable.create_run(owner, run_id=run_id)
    if created["state"] != "RUNNING":
        core.durable.transition_run(run_id, owner, "RUNNING")
    created = core.governance.create_work_item(
        run_id, owner, objective="Read safe lab status",
        work_item_id="WI-LAB", assignee_agent_id="agent-1",
        required_capabilities=["lab.read"],
    )
    core.governance.transition_work_item("WI-LAB", owner, "RUNNING")
    grant = core.authorization.grant(
        owner, principal_type="agent", principal_id="agent-1",
        capability="lab.read", scope_type="work_item", scope_id="WI-LAB",
    )
    machine = Machine("machine-1", "read-only-lab", owner,
                      (Capability("lab.read", "Read local lab state"),))
    policy = BoundWorkItemPolicy(
        owner=owner, principal_type="agent",
        governance=core.governance, authorization=core.authorization,
    )
    worker = LocalLabReader()
    registry = ExecutorRegistry(policy)
    registry.register(machine, worker)
    authority = CentralDurableIntentAuthority(core.durable)
    gate = DurableOperationGate(authority, policy, machine=machine)
    try:
        yield core, owner, grant, machine, policy, worker, registry, gate
    finally:
        core.durable.close()


def run(gate, registry, req=None):
    return asyncio.run(gate.submit(
        run_id="run-lab-1", owner="owner-one",
        request=req or request(), effect=registry.submit,
    ))


def test_control_plane_real_grant_to_durable_reservation_to_executor(center):
    core, owner, grant, machine, policy, worker, registry, gate = center
    result = run(gate, registry)
    assert result.state == "SUCCEEDED"
    assert worker.calls == ["op-lab-1"]
    stored = core.durable.operation_status("op-lab-1", owner)
    assert stored["state"] == "SUCCEEDED"
    with core.durable.lock:
        row = core.durable._operation_row("op-lab-1", owner)
        assert len(row["intent_sha256"]) == 64
        assert row["resource_key"] == "machine:machine-1"
        assert row["fencing_token"] == 1
        lease = core.durable.db.execute(
            "SELECT fencing_token,operation_id FROM leases WHERE resource_key=?",
            ("machine:machine-1",),
        ).fetchone()
        assert (lease["fencing_token"], lease["operation_id"]) == (1, "op-lab-1")
    events = core.durable.events("run-lab-1", owner)["items"]
    assert any(ev["type"] == "MACHINE_INTENT_RESERVED" for ev in events)
    assert any(ev["type"] == "MACHINE_EFFECT_SUCCEEDED" for ev in events)


def test_durable_replay_across_new_runtime_instance_never_reexecutes(center):
    core, owner, grant, machine, policy, worker, registry, gate = center
    assert run(gate, registry).state == "SUCCEEDED"
    other = DurableOperationGate(CentralDurableIntentAuthority(core.durable),
                                 policy, machine=machine)
    assert run(other, registry).state == "UNCERTAIN"
    assert worker.calls == ["op-lab-1"]
    with pytest.raises(DuplicateOperation):
        run(other, registry, request(arguments={"read": "secrets"}))


def test_no_real_grant_and_revocation_block_both_new_and_replay(center):
    core, owner, grant, machine, policy, worker, registry, gate = center
    core.authorization.revoke(grant["grant_id"], owner)
    with pytest.raises(AuthorizationRequired):
        run(gate, registry)
    assert worker.calls == []
    with core.durable.lock:
        assert core.durable.db.execute(
            "SELECT count(*) FROM operations WHERE operation_id=?",
            ("op-lab-1",),
        ).fetchone()[0] == 0


def test_fence_and_work_item_are_required(center):
    core, owner, grant, machine, policy, worker, registry, gate = center
    with pytest.raises(AuthorizationRequired):
        run(gate, registry, request(work_item_id="WI-elsewhere"))
    core.governance.transition_work_item("WI-LAB", owner, "CANCELLED")
    with pytest.raises(AuthorizationRequired):
        run(gate, registry)
    assert worker.calls == []


def test_existing_legacy_operation_does_not_gain_machine_intent(center):
    core, owner, grant, machine, policy, worker, registry, gate = center
    core.durable.create_operation(
        "run-lab-1", owner, kind="sentra.machine",
        operation_id="op-lab-1", idempotency_key="idem-lab-1",
    )
    with pytest.raises(DuplicateOperation):
        run(gate, registry)
    assert worker.calls == []


def test_core_closed_resource_or_stale_fence_denies_side_effect(center):
    core, owner, grant, machine, policy, worker, registry, gate = center
    source = CentralDurableIntentAuthority(core.durable)
    original = source.fence_active
    def stale(receipt):
        with core.durable.lock:
            core.durable.db.execute(
                "DELETE FROM leases WHERE resource_key=?",
                ("machine:machine-1",),
            )
            core.durable.db.commit()
        return original(receipt)
    gate = DurableOperationGate(source, policy, machine=machine)
    source.fence_active = stale
    with pytest.raises(DurableAdmissionUnavailable):
        run(gate, registry)
    assert worker.calls == []


def test_idempotency_different_operation_id_same_key_rejected(center):
    core, owner, grant, machine, policy, worker, registry, gate = center
    assert run(gate, registry).state == "SUCCEEDED"
    with pytest.raises(DuplicateOperation):
        run(gate, registry, request(op_id="op-different"))
    assert worker.calls == ["op-lab-1"]


def test_atomic_machine_lease_with_two_real_core_connections(tmp_path):
    """Two independent DurableRunService objects contend on one SQLite WAL."""
    from concurrent.futures import ThreadPoolExecutor
    from sentra_runtime.executor import _request_snapshot
    a = DurableRunService(tmp_path)
    b = DurableRunService(tmp_path)
    owner, run_id = "owner-one", "run-concurrency"
    try:
        created = a.create_run(owner, run_id=run_id)
        if created["state"] != "RUNNING":
            a.transition_run(run_id, owner, "RUNNING")

        def reserve(service, oid):
            req = request(op_id=oid, key="idem-" + oid)
            return service.reserve_operation_intent(
                run_id, owner, operation_id=req.operation_id,
                idempotency_key=req.idempotency_key,
                intent_sha256=_request_snapshot(req)[1],
                resource_key="machine:machine-1",
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reserve, a, "op-conc-1"),
                       pool.submit(reserve, b, "op-conc-2")]
            results = []
            for future in futures:
                try:
                    results.append(future.result(timeout=10))
                except DurableStateConflict:
                    results.append(None)
        assert sum(row is not None for row in results) == 1
        winning = next(row for row in results if row is not None)
        assert winning["fencing_token"] == 1
        winner_id = winning["operation_id"]
        # Cross-instance ledger queries agree on the exact operation.
        assert a.operation_status(winner_id, owner)["state"] == "STARTING"
        assert b.operation_status(winner_id, owner)["state"] == "STARTING"
        a.release_lease("machine:machine-1", owner, 1)
        losing = "op-conc-2" if winner_id == "op-conc-1" else "op-conc-1"
        next_row = reserve(b, losing)
        assert next_row["fencing_token"] == 2
    finally:
        a.close()
        b.close()


def test_atomic_machine_intent_migration_preserves_legacy_rows(tmp_path):
    service = DurableRunService(tmp_path)
    owner, run_id = "owner-one", "run-existing"
    created = service.create_run(owner, run_id=run_id)
    if created["state"] != "RUNNING":
        service.transition_run(run_id, owner, "RUNNING")
    service.create_operation(
        run_id, owner, kind="sentra.machine",
        operation_id="op-legacy", idempotency_key="idem-legacy",
    )
    service.close()
    reopened = DurableRunService(tmp_path)
    try:
        info = reopened.operation_status("op-legacy", owner)
        assert info["operation_id"] == "op-legacy"
        with pytest.raises(DurableStateConflict, match="intent mismatch"):
            reopened.reserve_operation_intent(
                run_id, owner, operation_id="op-legacy",
                idempotency_key="idem-legacy",
                intent_sha256="a" * 64, resource_key="machine:machine-1",
            )
        with reopened.lock:
            assert reopened.db.execute(
                "SELECT intent_sha256 FROM operations WHERE operation_id='op-legacy'"
            ).fetchone()[0] is None
    finally:
        reopened.close()


def test_paused_run_denies_new_machine_reservation(tmp_path):
    service = DurableRunService(tmp_path)
    owner, run_id = "owner-one", "run-paused"
    try:
        service.create_run(owner, run_id=run_id)
        service.transition_run(run_id, owner, "PAUSED")
        with pytest.raises(DurableStateConflict, match="RUNNING"):
            service.reserve_operation_intent(
                run_id, owner, operation_id="op-paused",
                idempotency_key="idem-paused", intent_sha256="c" * 64,
                resource_key="machine:machine-1",
            )
        with service.lock:
            assert service.db.execute(
                "SELECT COUNT(*) FROM operations"
            ).fetchone()[0] == 0
    finally:
        service.close()
