"""Real SQLite fixture verifies a ControlStore-shaped intent reservation protocol.

The fixture DB exists only in tmp_path for test. Production never uses this
as a second, competing authority. Legacy DurableRunService must be denied.
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import Capability, Machine, OperationRequest, OperationResult, PolicyDecision
from sentra_runtime.durable_admission import (
    DurableAdmissionUnavailable, DurableOperationGate, IntentReceipt,
)
from sentra_runtime.executor import AuthorizationRequired, DuplicateOperation


class SqliteFixtureAuthority:
    def __init__(self, path):
        self.path = path
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS operations("
                "operation_id TEXT UNIQUE NOT NULL,run_id TEXT,owner TEXT,"
                "idempotency_key TEXT, intent_sha256 TEXT,fence INTEGER,"
                "active INTEGER DEFAULT 1,result TEXT,"
                "UNIQUE(run_id,idempotency_key))"
            )

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def reserve_intent(self, *, run_id, owner, request, intent_sha256):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT operation_id,run_id,owner,intent_sha256,fence FROM operations "
                "WHERE run_id=? AND idempotency_key=?",
                (run_id, request.idempotency_key),
            ).fetchone()
            if row:
                if row[:4] != (request.operation_id, run_id, owner, intent_sha256):
                    raise DuplicateOperation("durable fingerprint mismatch")
                return IntentReceipt(request.operation_id, intent_sha256,
                                     run_id, owner, row[4], "EXISTING")
            db.execute(
                "INSERT INTO operations(operation_id,run_id,owner,idempotency_key,"
                "intent_sha256,fence) VALUES(?,?,?,?,?,1)",
                (request.operation_id, run_id, owner,
                 request.idempotency_key, intent_sha256),
            )
        return IntentReceipt(request.operation_id, intent_sha256,
                             run_id, owner, 1, "RESERVED")

    def fence_active(self, receipt):
        with self._connect() as db:
            row = db.execute(
                "SELECT active,fence FROM operations WHERE operation_id=?",
                (receipt.operation_id,),
            ).fetchone()
            return bool(row and row == (1, receipt.fencing_token))

    def record_result(self, receipt, result):
        with self._connect() as db:
            row = db.execute(
                "UPDATE operations SET result=? WHERE operation_id=? AND fence=?"
                " AND active=1",
                (result.state, receipt.operation_id, receipt.fencing_token),
            )
            return row.rowcount == 1

    def revoke(self, operation_id):
        with self._connect() as db:
            db.execute("UPDATE operations SET active=0 WHERE operation_id=?",
                       (operation_id,))


def req(**changes):
    values = dict(operation_id="op-1", principal_id="agent-1", machine_id="lab",
                  capability_id="lab.read", work_item_id="WI-1",
                  idempotency_key="idem-1", arguments={"x": 1})
    values.update(changes)
    return OperationRequest(**values)


def machine():
    return Machine("lab", "lab", "owner", (Capability("lab.read", "read lab"),))


def gate(authority, policy=lambda _: PolicyDecision(True, "lab grant")):
    return DurableOperationGate(authority, policy, machine=machine())


def execute(run, request, backend):
    return asyncio.run(run.submit(run_id="run-1", owner="owner",
                                  request=request, effect=backend))


def success(calls):
    async def backend(request):
        calls.append(request.operation_id)
        return OperationResult(request.operation_id, "SUCCEEDED")
    return backend


def test_legacy_durable_run_service_is_rejected(tmp_path):
    legacy = DurableRunService(tmp_path / "state")
    try:
        with pytest.raises(DurableAdmissionUnavailable, match="missing"):
            gate(legacy)
    finally:
        legacy.close()


def test_actual_sqlite_reservation_replay_does_not_resend(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "test.db")
    calls = []
    g = gate(authority)
    assert execute(g, req(), success(calls)).state == "SUCCEEDED"
    replay = execute(gate(SqliteFixtureAuthority(tmp_path / "test.db")),
                     req(), success(calls))
    assert replay.state == "UNCERTAIN"
    assert calls == ["op-1"]
    with pytest.raises(DuplicateOperation):
        execute(g, req(arguments={"x": 2}), success(calls))
    assert calls == ["op-1"]


def test_duplicate_key_for_different_operation_denied(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "test.db")
    calls = []
    execute(gate(authority), req(), success(calls))
    with pytest.raises(DuplicateOperation):
        execute(gate(authority), req(operation_id="op-2"), success(calls))
    assert calls == ["op-1"]


def test_policy_denied_before_reservation(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "db")
    calls = []
    g = gate(authority, lambda _: PolicyDecision(False, "not granted"))
    with pytest.raises(AuthorizationRequired):
        execute(g, req(), success(calls))
    with authority._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
    assert not calls


def test_stale_fence_denied_before_effect(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "db")
    calls = []
    old = authority.fence_active
    def revoke_before_effect(receipt):
        authority.revoke(receipt.operation_id)
        return old(receipt)
    authority.fence_active = revoke_before_effect
    with pytest.raises(DurableAdmissionUnavailable, match="stale"):
        execute(gate(authority), req(), success(calls))
    assert not calls


def test_revocation_between_reservation_and_effect_denied(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "db")
    allowed = [True]
    calls = []
    def policy(_):
        answer = allowed[0]
        allowed[0] = False
        return PolicyDecision(answer, "grant")
    with pytest.raises(AuthorizationRequired, match="revoked"):
        execute(gate(authority, policy), req(), success(calls))
    assert calls == []


def test_ambiguous_effect_is_never_automatically_retried(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "db")
    calls = []
    async def failing(req):
        calls.append(req.operation_id)
        raise TimeoutError("backend may already have executed")
    res = execute(gate(authority), req(), failing)
    assert res.state == "UNCERTAIN"
    res2 = execute(gate(authority), req(), failing)
    assert res2.state == "UNCERTAIN"
    assert calls == ["op-1"]


def test_policy_cannot_rewrite_intent(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "db")
    calls = []
    def bad(intent):
        intent.arguments["x"] = 333
        return PolicyDecision(True, "bad")
    with pytest.raises(AuthorizationRequired, match="altered"):
        execute(gate(authority, bad), req(), success(calls))
    assert not calls


def test_authority_receipt_mismatch_denied(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "db")
    original = authority.reserve_intent
    def bad(**kwargs):
        prior = original(**kwargs)
        return IntentReceipt("another-id", prior.intent_sha256, prior.run_id,
                             prior.owner, prior.fencing_token, prior.status)
    authority.reserve_intent = bad
    with pytest.raises(DurableAdmissionUnavailable, match="mismatch"):
        execute(gate(authority), req(), success([]))


def test_durable_result_acknowledgement_failure_uncertain(tmp_path):
    authority = SqliteFixtureAuthority(tmp_path / "db")
    authority.record_result = lambda *_: False
    calls = []
    assert execute(gate(authority), req(), success(calls)).state == "UNCERTAIN"
    assert calls == ["op-1"]
