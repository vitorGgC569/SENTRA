"""Protected retention uses disposable SQLite stores, never installed user data."""
from contextlib import closing
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock
from types import SimpleNamespace

import pytest

import sentra_canvas.shell_requests as module
from sentra_canvas.shell_requests import HostRequestCapacityError, HostRequestRetentionPolicy, ShellHostRequests
from sentra_core.conversations import _decode, _encode
from sentra_mcp.services.shell_coordinator import ShellConflict


class Store:
    def __init__(self, path):
        self.path = path

    def connect(self, name):
        assert name == "shell"
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db


@pytest.fixture
def host(tmp_path):
    control = SimpleNamespace(store=Store(tmp_path / "requests.sqlite3"))
    policy = HostRequestRetentionPolicy(retain_after_ack_seconds=0)
    return ShellHostRequests(control, "owner-a", retention_policy=policy)


def input_record(host, *, key="input-request-01", data="SECRET-input" * 100, project="project-a", terminal="terminal-a"):
    payload = {"terminal_id": terminal, "input_target": "a" * 32, "data": data}
    result = {"ok": True, "status": "delivered", "delivery_stage": "delivered_to_process", "request_key": key,
        "terminal_id": terminal, "input_target": "a" * 32, "bytes": len(data.encode()), "task_completion_verified": False}
    value = host.invoke(project, "terminal_input", payload, key, lambda: result)
    fp = hashlib.sha256(json.dumps(["terminal_input", payload], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return key, payload, value, fp


def acknowledge(host, key, fp, project="project-a"):
    with closing(host.control.store.connect("shell")) as db, db:
        db.execute("BEGIN IMMEDIATE")
        return host.acknowledge_terminal_input(db, project, key, fp)


def test_acknowledged_content_retires_but_original_key_cannot_execute_again(host):
    key, payload, result, fp = input_record(host)
    before = host.retention_status()
    assert acknowledge(host, key, fp)
    assert host.compact_acknowledged("project-a")["retired"] == 1
    assert host.retention_status()["protected_bytes"] < before["protected_bytes"]
    restored = ShellHostRequests(host.control, host.owner)
    replay = restored.invoke("project-a", "terminal_input", payload, key, lambda: pytest.fail("replayed input"))
    assert replay["payload_retired"] and replay["delivery_stage"] == "delivered_to_process"
    assert not replay["task_completion_verified"] and not replay["automatic_retry"] and not replay["may_resend"]
    selected = restored.intent("project-a", key, fp)
    assert selected["payload_retired"] and "data" not in selected["payload"]
    observed = restored.inspect_retired_input("project-a", key, fp, "terminal-a")
    assert observed["found"] and observed["resolved"] and observed["payload_retired"]
    assert restored.inspect("project-a", "terminal_input", payload, key)["resolved"]
    with closing(host.control.store.connect("shell")) as db:
        row = db.execute("SELECT * FROM canvas_shell_host_requests").fetchone()
        assert row["protected_intent"].startswith(("dpapi:", "keyring:"))
        assert "SECRET-input" not in str(dict(row))
        assert "SECRET-input" not in json.dumps(_decode(row["protected_intent"]))
        # Compatible schema-v2 rollback still sees a result, not an absent claim.
        assert db.execute("SELECT version FROM canvas_shell_request_schema").fetchone()[0] == 2
        assert _decode(row["protected_result"])["payload_retired"]
    with pytest.raises(ShellConflict):
        restored.invoke("project-a", "terminal_input", {**payload, "data": "other"}, key, lambda: pytest.fail("changed intent ran"))


def test_unacknowledged_and_uncertain_contents_never_retire(host):
    key, payload, _, fp = input_record(host)
    assert host.compact_acknowledged("project-a")["retired"] == 0
    assert host.intent("project-a", key, fp)["payload"]["data"] == payload["data"]
    uncertain_key = "uncertain-request-01"
    def uncertain():
        host.note_effect_possible("project-a", uncertain_key)
        raise OSError("lost delivery")
    with pytest.raises(OSError):
        host.invoke("project-a", "terminal_input", payload, uncertain_key, uncertain)
    uncertain_fp = fp
    assert not acknowledge(host, uncertain_key, uncertain_fp)
    assert host.compact_acknowledged("project-a")["retired"] == 0
    assert host.intent("project-a", uncertain_key, uncertain_fp)["payload"]["data"] == payload["data"]


@pytest.mark.parametrize("state", ["RUNNING", "WAITING_EXTERNAL", "RESERVED", "FUTURE_STATE"])
def test_ack_refuses_async_outer_committed_results(host, state):
    payload = {"terminal_id": "terminal-a", "input_target": "a" * 32, "data": "secret"}
    key = "async-operation-01"
    host.invoke("project-a", "terminal_input", payload, key, lambda: {"status": "delivered", "operation_state": state})
    fp = hashlib.sha256(json.dumps(["terminal_input", payload], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert not acknowledge(host, key, fp)
    assert host.compact_acknowledged("project-a")["retired"] == 0


def test_retention_age_uses_first_ack_not_claim_or_outer_commit(host, monkeypatch):
    policy = HostRequestRetentionPolicy(retain_after_ack_seconds=60)
    host = ShellHostRequests(host.control, host.owner, retention_policy=policy)
    now = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    key, _, _, fp = input_record(host)
    now[0] = 2000.0
    assert acknowledge(host, key, fp)
    now[0] = 2059.0
    assert host.compact_acknowledged("project-a")["retired"] == 0
    assert acknowledge(host, key, fp)  # A repeat ACK cannot silently extend retention.
    now[0] = 2060.0
    assert host.compact_acknowledged("project-a")["retired"] == 1


def test_pending_cross_device_selector_blocks_retirement_even_after_ack(host):
    key, _, _, fp = input_record(host)
    with closing(host.control.store.connect("shell")) as db, db:
        db.execute("CREATE TABLE canvas_terminal_input_pending(owner,project_id,request_key)")
        db.execute("INSERT INTO canvas_terminal_input_pending VALUES(?,?,?)", (host.owner, "project-a", key))
    assert acknowledge(host, key, fp)
    assert host.compact_acknowledged("project-a")["retired"] == 0
    with closing(host.control.store.connect("shell")) as db, db:
        db.execute("DELETE FROM canvas_terminal_input_pending WHERE request_key=?", (key,))
    assert host.compact_acknowledged("project-a")["retired"] == 1


def test_tombstone_is_bound_to_owner_project_terminal_and_exact_fingerprint(host):
    key, _, _, fp = input_record(host)
    assert acknowledge(host, key, fp)
    host.compact_acknowledged("project-a")
    assert ShellHostRequests(host.control, "other-owner").intent("project-a", key, fp) is None
    assert host.intent("other-project", key, fp) is None
    with pytest.raises(PermissionError):
        host.inspect_retired_input("project-a", key, fp, "other-terminal")
    with pytest.raises(ShellConflict):
        host.inspect_retired_input("project-a", key, "0" * 64, "terminal-a")


def test_metadata_limit_rejects_only_new_claims_and_never_evicts_existing_keys(host):
    limited = ShellHostRequests(host.control, host.owner, retention_policy=HostRequestRetentionPolicy(max_records=1))
    key, payload, _, _ = input_record(limited)
    with pytest.raises(HostRequestCapacityError, match="before admission"):
        limited.invoke("project-b", "any_action", {}, "new-request-02", lambda: pytest.fail("over-budget effect ran"))
    assert limited.invoke("project-a", "terminal_input", payload, key, lambda: pytest.fail("old key replayed"))["status"] == "delivered"
    assert limited.retention_status()["record_count"] == 1


def test_inflight_result_reservation_prevents_concurrent_budget_overcommit(host):
    policy = HostRequestRetentionPolicy(max_protected_bytes=8192, result_reservation_bytes=4096)
    limited = ShellHostRequests(host.control, host.owner, retention_policy=policy)
    def first():
        with pytest.raises(HostRequestCapacityError):
            limited.invoke("project-a", "second", {}, "second-request", lambda: pytest.fail("overcommit"))
        assert limited.retention_status()["reserved_bytes"] == 5120
        return {"status": "applied"}
    assert limited.invoke("project-a", "first", {}, "first-request", first)["status"] == "applied"
    assert limited.retention_status()["reserved_bytes"] == 1024
    assert limited.retention_status()["protected_bytes"] <= 8192


def test_oversized_post_effect_projection_becomes_uncertain_without_replay(host):
    policy = HostRequestRetentionPolicy(max_protected_bytes=16384, result_reservation_bytes=4096)
    limited = ShellHostRequests(host.control, host.owner, retention_policy=policy)
    calls = []
    def effect():
        calls.append("effect")
        limited.note_effect_possible("project-a", "large-result-01")
        return {"status": "applied", "output": "x" * 8192}
    with pytest.raises(ValueError, match="reservation"):
        limited.invoke("project-a", "large", {}, "large-result-01", effect)
    assert limited.invoke("project-a", "large", {}, "large-result-01", effect)["effect_uncertain"]
    assert calls == ["effect"]
    assert limited.retention_status()["reserved_bytes"] == 1024


def test_compatible_old_writes_are_counted_and_cannot_change_request_identity(host):
    key, _, _, _ = input_record(host)
    with closing(host.control.store.connect("shell")) as db, db:
        db.execute("UPDATE canvas_shell_host_requests SET protected_result=? WHERE request_key=?", (_encode({"status": "applied"}), key))
        expected = db.execute("SELECT SUM(LENGTH(COALESCE(protected_intent,''))+LENGTH(COALESCE(protected_result,''))) FROM canvas_shell_host_requests").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE canvas_shell_host_requests SET project_id='another-project' WHERE request_key=?", (key,))
    assert host.retention_status()["protected_bytes"] == expected


def test_retention_extension_future_version_fails_closed_without_changing_v2(host):
    with closing(host.control.store.connect("shell")) as db, db:
        db.execute("UPDATE canvas_shell_request_retention_schema SET version=999")
    with pytest.raises(RuntimeError, match="newer"):
        ShellHostRequests(host.control, host.owner)
    with closing(host.control.store.connect("shell")) as db:
        assert db.execute("SELECT version FROM canvas_shell_request_schema").fetchone()[0] == 2


def test_two_journal_instances_share_the_same_inflight_byte_budget(host):
    policy = HostRequestRetentionPolicy(max_protected_bytes=8192, result_reservation_bytes=4096)
    first = ShellHostRequests(host.control, host.owner, retention_policy=policy)
    second = ShellHostRequests(host.control, host.owner, retention_policy=policy)
    entered, release = Event(), Event()
    def callback():
        entered.set()
        assert release.wait(5)
        return {"status": "applied"}
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first.invoke, "project-a", "first", {}, "parallel-first", callback)
        try:
            assert entered.wait(5)
            with pytest.raises(HostRequestCapacityError):
                second.invoke("project-b", "second", {}, "parallel-second", lambda: pytest.fail("second effect ran"))
            assert second.retention_status()["reserved_bytes"] == 5120
        finally:
            release.set()
        assert future.result(timeout=5)["status"] == "applied"


def test_failed_additive_migration_rolls_back_columns_and_preserves_legacy_receipt(tmp_path):
    store = Store(tmp_path / "legacy.sqlite3")
    with closing(store.connect("shell")) as db, db:
        db.execute("CREATE TABLE canvas_shell_request_schema(id INTEGER PRIMARY KEY,version INTEGER NOT NULL)")
        db.execute("INSERT INTO canvas_shell_request_schema VALUES(1,2)")
        db.execute("CREATE TABLE canvas_shell_host_requests(owner TEXT,project_id TEXT,request_key TEXT,fingerprint TEXT,"
            "state TEXT,protected_result TEXT,created_at REAL,updated_at REAL,PRIMARY KEY(owner,project_id,request_key))")
        result = _encode({"status": "applied", "marker": "legacy-protected"})
        db.execute("INSERT INTO canvas_shell_host_requests VALUES(?,?,?,?,?,?,?,?)", ("owner-a", "project-a", "legacy-key", "f" * 64, "applied", result, 1, 1))
    original_connect = store.connect
    def deny_trigger_creation(name):
        db = original_connect(name)
        db.set_authorizer(lambda action, *_args: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TRIGGER else sqlite3.SQLITE_OK)
        return db
    store.connect = deny_trigger_creation
    with pytest.raises(sqlite3.DatabaseError):
        ShellHostRequests(SimpleNamespace(store=store), "owner-a")
    store.connect = original_connect
    with closing(store.connect("shell")) as db:
        assert len(list(db.execute("PRAGMA table_info(canvas_shell_host_requests)"))) == 8
        assert db.execute("SELECT protected_result FROM canvas_shell_host_requests").fetchone()[0] == result
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_shell_request_retention_schema'").fetchone()
    restored = ShellHostRequests(SimpleNamespace(store=store), "owner-a")
    assert restored.retention_status()["record_count"] == 1
    assert restored.retention_status()["protected_bytes"] == len(result.encode())


def test_tiny_acknowledged_inputs_cannot_overrun_budget_when_tombstones_are_larger(host):
    policy = HostRequestRetentionPolicy(max_protected_bytes=32768, result_reservation_bytes=4096, retain_after_ack_seconds=0)
    limited = ShellHostRequests(host.control, host.owner, retention_policy=policy)
    admitted = []
    for number in range(30):
        try:
            key, payload, _, fp = input_record(limited, key=f"small-input-{number:03}", data="x")
        except HostRequestCapacityError:
            break
        assert acknowledge(limited, key, fp)
        assert limited.compact_acknowledged("project-a")["retired"] == 1
        usage = limited.retention_status()
        assert usage["protected_bytes"] + usage["reserved_bytes"] <= usage["max_protected_bytes"]
        admitted.append((key, payload))
    assert admitted
    for key, payload in admitted:
        assert limited.invoke("project-a", "terminal_input", payload, key, lambda: pytest.fail("retired key replayed"))["payload_retired"]


def test_inspection_started_before_other_instance_compacts_keeps_original_fingerprint(host, monkeypatch):
    from sentra_canvas.terminal_input_receipts import inspect
    key, _, _, fp = input_record(host)
    assert acknowledge(host, key, fp)
    other = ShellHostRequests(host.control, host.owner, retention_policy=host.retention_policy)
    read_original = host.intent
    def retire_between_reads(project, request_key, fingerprint):
        original = read_original(project, request_key, fingerprint)
        assert other.compact_acknowledged(project)["retired"] == 1
        return original
    monkeypatch.setattr(host, "intent", retire_between_reads)
    def resource(kind, terminal, project):
        assert (kind, terminal, project) == ("terminals", "terminal-a", "project-a")
    canvas = SimpleNamespace(_lock=RLock(), _terminal_input_requests=host, store=SimpleNamespace(resource=resource))
    result = inspect(canvas, "project-a", "terminal-a", key, fp)
    assert result["resolved"] and result["payload_retired"] and result["result"]["payload_retired"]
    assert result["input_target"] == "a" * 32


def test_ack_transaction_and_other_instance_compaction_cannot_cross_pending_selector(host):
    key, _, _, fp = input_record(host)
    other = ShellHostRequests(host.control, host.owner, retention_policy=host.retention_policy)
    started = Event()
    with closing(host.control.store.connect("shell")) as db, db:
        db.execute("CREATE TABLE canvas_terminal_input_pending(owner,project_id,request_key)")
        db.execute("INSERT INTO canvas_terminal_input_pending VALUES(?,?,?)", (host.owner, "project-a", key))
    def compact():
        started.set()
        return other.compact_acknowledged("project-a")
    with ThreadPoolExecutor(max_workers=1) as executor:
        with closing(host.control.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            assert host.acknowledge_terminal_input(db, "project-a", key, fp)
            future = executor.submit(compact)
            assert started.wait(5)
            # The competing writer cannot observe half of this transaction.
            assert not future.done()
            db.execute("DELETE FROM canvas_terminal_input_pending WHERE owner=? AND project_id=? AND request_key=?", (host.owner, "project-a", key))
        assert future.result(timeout=5)["retired"] == 1
    assert host.inspect_retired_input("project-a", key, fp, "terminal-a")["resolved"]
