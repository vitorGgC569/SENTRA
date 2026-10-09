from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sentra_remote.relay import RemoteRelayServer
from sentra_remote.store import RemoteAgentCompatibilityError, RemoteStore
from sentra_version import CAPABILITY_VERSION, PROTOCOL_VERSION, SERVER_VERSION


def test_pairing_device_tokens_permissions_and_rotation(tmp_path: Path) -> None:
    store = RemoteStore(tmp_path / "remote.sqlite3", online_window_s=10)
    pair = store.create_pairing("user-1", "PC", "windows", ["sentra_read_file", "sentra_start_process"])
    paired = store.pair_device(pair["pairing_code"])
    device_id = paired["device_id"]
    token = paired["device_token"]

    store.heartbeat(device_id, token, {"python": "3.12"})
    device = store.get_device("user-1", device_id)
    assert device["status"] == "ONLINE"
    assert device["capabilities"]["python"] == "3.12"

    job_id = store.submit_job("user-1", device_id, "sentra_read_file", {"path": "x.txt"})
    leased = store.poll_job(device_id, token)
    assert leased and leased.job_id == job_id
    store.progress(device_id, token, job_id, leased.lease_token, "executing")
    store.complete_job(device_id, token, job_id, leased.lease_token, {"ok": True})
    assert store.job_result("user-1", job_id)["state"] == "COMPLETED"

    with pytest.raises(PermissionError):
        store.submit_job("user-1", device_id, "sentra_write_pdf", {})

    rotated = store.rotate_device_token(device_id, token)
    # Old token remains valid briefly so a lost rotation response cannot brick the agent.
    store.heartbeat(device_id, token)
    store.heartbeat(device_id, rotated["device_token"])

    store.revoke_device("user-1", device_id)
    assert store.get_device("user-1", device_id)["status"] == "REVOKED"
    with pytest.raises(PermissionError):
        store.heartbeat(device_id, rotated["device_token"])
    with pytest.raises(PermissionError):
        store.heartbeat(device_id, token)


def test_invalid_pairing_attempts_are_rate_limited(tmp_path: Path) -> None:
    now = [1000.0]
    store = RemoteStore(tmp_path / "pairing-rate.sqlite3", clock=lambda: now[0])
    try:
        for _ in range(20):
            with pytest.raises(PermissionError, match="invalid or expired"):
                store.pair_device("BAD-CODE", rate_key="192.0.2.10")
        with pytest.raises(PermissionError, match="rate limited"):
            store.pair_device("BAD-CODE", rate_key="192.0.2.10")
        with pytest.raises(PermissionError, match="invalid or expired"):
            store.pair_device("BAD-CODE", rate_key="192.0.2.11")
        now[0] += 61
        with pytest.raises(PermissionError, match="invalid or expired"):
            store.pair_device("BAD-CODE", rate_key="192.0.2.10")
    finally:
        store.close()


def test_public_device_marks_broad_acl(tmp_path: Path) -> None:
    store = RemoteStore(tmp_path / "broad-acl.sqlite3")
    try:
        broad = store.create_pairing("u", "Broad", "win", ["sentra_repo_*"])
        broad_device = store.pair_device(broad["pairing_code"])
        assert store.get_device("u", broad_device["device_id"])["broad_acl"] is True

        narrow = store.create_pairing("u", "Narrow", "win", ["sentra_health"])
        narrow_device = store.pair_device(narrow["pairing_code"])
        assert store.get_device("u", narrow_device["device_id"])["broad_acl"] is False
    finally:
        store.close()


def test_rotation_grace_expires(tmp_path: Path) -> None:
    now = [1000.0]
    store = RemoteStore(tmp_path / "rotate.sqlite3", clock=lambda: now[0])
    code = store.create_pairing("u", "PC", "win", ["*"])["pairing_code"]
    paired = store.pair_device(code)
    did, old = paired["device_id"], paired["device_token"]
    rotated = store.rotate_device_token(did, old)
    store.heartbeat(did, old)
    now[0] += 121
    with pytest.raises(PermissionError):
        store.heartbeat(did, old)
    store.heartbeat(did, rotated["device_token"])


def test_lease_loss_requeues_only_pre_execution_and_marks_uncertain_after_execution(tmp_path: Path) -> None:
    now = [1000.0]
    store = RemoteStore(
        tmp_path / "lease.sqlite3",
        clock=lambda: now[0],
        lease_window_s=5,
        online_window_s=10,
    )
    code = store.create_pairing("u", "PC", "win", ["*"])["pairing_code"]
    paired = store.pair_device(code)
    did, tok = paired["device_id"], paired["device_token"]

    first = store.submit_job("u", did, "sentra_health", {}, timeout_s=100)
    lease1 = store.poll_job(did, tok)
    assert lease1
    store.progress(did, tok, first, lease1.lease_token, "preparing")
    now[0] += 6
    lease2 = store.poll_job(did, tok)
    assert lease2 and lease2.job_id == first
    assert store.job_result("u", first)["requeues"] == 1
    store.complete_job(did, tok, first, lease2.lease_token, {"ok": True})

    second = store.submit_job("u", did, "sentra_health", {}, timeout_s=100)
    lease3 = store.poll_job(did, tok)
    assert lease3
    store.progress(did, tok, second, lease3.lease_token, "executing")
    now[0] += 6
    assert store.poll_job(did, tok) is None
    state = store.job_result("u", second)
    assert state["state"] == "UNCERTAIN"
    assert "not automatically replayed" in state["error"]


def test_chunked_result_is_hash_verified(tmp_path: Path) -> None:
    import hashlib
    store = RemoteStore(tmp_path / "chunks.sqlite3", max_result_bytes=2_000_000)
    pair = store.create_pairing("u", "PC", "win", ["*"])
    paired = store.pair_device(pair["pairing_code"])
    did, tok = paired["device_id"], paired["device_token"]
    jid = store.submit_job("u", did, "sentra_health", {})
    lease = store.poll_job(did, tok)
    assert lease
    raw = json.dumps({"ok": True, "data": {"value": "x" * 2000}}).encode()
    parts = [raw[:1000], raw[1000:]]
    for i, part in enumerate(parts):
        store.put_result_chunk(did, tok, jid, lease.lease_token, i, part, hashlib.sha256(part).hexdigest())
    store.finalize_chunks(did, tok, jid, lease.lease_token, len(parts), hashlib.sha256(raw).hexdigest())
    result = store.job_result("u", jid)
    assert result["state"] == "COMPLETED"
    assert result["result"]["data"]["value"].startswith("x")

    failed_id = store.submit_job("u", did, "sentra_health", {})
    failed_lease = store.poll_job(did, tok)
    assert failed_lease and failed_lease.job_id == failed_id
    failed_raw = json.dumps({"ok": False, "error": {"code": "boom", "message": "x" * 3000}}).encode()
    pieces = [failed_raw[:1500], failed_raw[1500:]]
    for i, part in enumerate(pieces):
        store.put_result_chunk(did, tok, failed_id, failed_lease.lease_token, i, part, hashlib.sha256(part).hexdigest())
    store.finalize_chunks(
        did,
        tok,
        failed_id,
        failed_lease.lease_token,
        len(pieces),
        hashlib.sha256(failed_raw).hexdigest(),
        failed=True,
    )
    failed = store.job_result("u", failed_id)
    assert failed["state"] == "FAILED"
    assert failed["result"]["error"]["code"] == "boom"


def test_relay_pair_heartbeat_poll_result_roundtrip(tmp_path: Path) -> None:
    store = RemoteStore(tmp_path / "relay.sqlite3")
    pairing = store.create_pairing("user", "Node", "windows", ["sentra_health"])
    relay = RemoteRelayServer(store, port=0)
    port = relay.server.server_port
    thread = threading.Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    try:
        def request(path: str, payload: dict | None = None, headers: dict | None = None):
            data = None if payload is None else json.dumps(payload).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=data,
                method="POST" if payload is not None else "GET",
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                return json.loads(response.read())

        paired = request("/v1/pair", {"pairing_code": pairing["pairing_code"], "name": "Node"})
        did, tok = paired["device_id"], paired["device_token"]
        auth = {"X-Sentra-Device": did, "Authorization": "Device " + tok}
        request("/v1/agent/heartbeat", {"capabilities": {"ok": True}}, auth)
        jid = store.submit_job("user", did, "sentra_health", {})
        polled = request("/v1/agent/jobs/poll", headers=auth)["job"]
        assert polled["job_id"] == jid
        request("/v1/agent/jobs/progress", {
            "job_id": jid, "lease_token": polled["lease_token"], "phase": "executing"
        }, auth)
        request("/v1/agent/jobs/result", {
            "job_id": jid,
            "lease_token": polled["lease_token"],
            "result": {"ok": True, "data": {"status": "ok"}},
        }, auth)
        assert store.job_result("user", jid)["result"]["data"]["status"] == "ok"
    finally:
        relay.stop()
        thread.join(timeout=3)



def _valid_remote_contract(*tools: str) -> dict:
    tool_names = list(tools or ("sentra_health",))
    tool_names_hash = hashlib.sha256(
        json.dumps(
            tool_names,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "sentra": {
            "server": {
                "name": "sentra-mcp",
                "version": SERVER_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "capability_version": CAPABILITY_VERSION,
                "build_id": "test-build",
                "fingerprint": "f" * 64,
                "source_hash": "a" * 64,
                "executable_sha256": None,
            },
            "contract": {
                "schema_hash": "b" * 64,
                "tool_schema_hash": "b" * 64,
                "tool_names_hash": tool_names_hash,
                "tool_count": len(tool_names),
                "tool_names": tool_names,
            },
            "capabilities": {
                "durable_run": True,
                "durable_operation": True,
            },
        },
        "agent_version": SERVER_VERSION,
    }


def test_contract_required_remote_job_fails_closed_and_recovers_without_replay(
    tmp_path: Path,
) -> None:
    store = RemoteStore(tmp_path / "contract.sqlite3", online_window_s=10)
    pair = store.create_pairing("u", "PC", "win", ["sentra_health"])
    paired = store.pair_device(pair["pairing_code"])
    did, tok = paired["device_id"], paired["device_token"]

    store.heartbeat(did, tok, {"python": "3.12"})
    with pytest.raises(RemoteAgentCompatibilityError):
        store.submit_job(
            "u",
            did,
            "sentra_health",
            {},
            require_compatible_agent=True,
        )

    valid = _valid_remote_contract("sentra_health")
    heartbeat = store.heartbeat(did, tok, valid)
    assert heartbeat["compatibility"]["compatible"] is True
    job_id = store.submit_job(
        "u",
        did,
        "sentra_health",
        {},
        run_id="run-contract",
        operation_id="op-contract",
        idempotency_key="remote-once",
        require_compatible_agent=True,
    )
    assert store.job_result("u", job_id)["contract_required"] is True

    stale = _valid_remote_contract("sentra_health")
    stale["sentra"]["server"]["protocol_version"] = "stale-protocol"
    store.heartbeat(did, tok, stale)
    assert store.poll_job(did, tok) is None
    assert store.job_result("u", job_id)["state"] == "QUEUED"

    store.heartbeat(did, tok, valid)
    leased = store.poll_job(did, tok)
    assert leased is not None
    assert leased.job_id == job_id


def test_remote_store_idempotency_reuses_same_job(tmp_path: Path) -> None:
    store = RemoteStore(tmp_path / "idempotent.sqlite3", online_window_s=10)
    pair = store.create_pairing("u", "PC", "win", ["sentra_health"])
    paired = store.pair_device(pair["pairing_code"])
    did = paired["device_id"]

    first = store.submit_job(
        "u", did, "sentra_health", {"probe": 1},
        idempotency_key="same-request",
    )
    second = store.submit_job(
        "u", did, "sentra_health", {"probe": 1},
        idempotency_key="same-request",
    )

    assert second == first
    replay = store.job_for_idempotency(
        "u", did, "same-request",
        tool="sentra_health", arguments={"probe": 1},
    )
    assert replay is not None
    assert replay["job_id"] == first


def test_remote_store_idempotency_rejects_payload_collision(tmp_path: Path) -> None:
    store = RemoteStore(tmp_path / "idempotent-collision.sqlite3", online_window_s=10)
    pair = store.create_pairing("u", "PC", "win", ["sentra_health"])
    paired = store.pair_device(pair["pairing_code"])
    did = paired["device_id"]

    store.submit_job(
        "u", did, "sentra_health", {"probe": 1},
        idempotency_key="collision",
    )

    with pytest.raises(ValueError, match="different remote request"):
        store.submit_job(
            "u", did, "sentra_health", {"probe": 2},
            idempotency_key="collision",
        )


@pytest.mark.parametrize(
    ("association", "expected_message"),
    [("run_id", "different run"), ("operation_id", "different operation")],
)
def test_remote_store_idempotency_rejects_new_association_on_replay(
    tmp_path: Path, association: str, expected_message: str
) -> None:
    store = RemoteStore(tmp_path / f"idempotent-{association}.sqlite3")
    pair = store.create_pairing("u", "PC", "win", ["sentra_health"])
    did = store.pair_device(pair["pairing_code"])["device_id"]
    store.submit_job("u", did, "sentra_health", {}, idempotency_key="association")

    with pytest.raises(ValueError, match=expected_message):
        store.submit_job(
            "u", did, "sentra_health", {}, idempotency_key="association",
            **{association: f"new-{association}"},
        )


def test_remote_store_concurrent_idempotency_is_unique_across_connections(
    tmp_path: Path,
) -> None:
    database = tmp_path / "idempotent-concurrent.sqlite3"
    first_store = RemoteStore(database)
    pair = first_store.create_pairing("u", "PC", "win", ["sentra_health"])
    did = first_store.pair_device(pair["pairing_code"])["device_id"]
    second_store = RemoteStore(database)
    stores = [first_store, second_store] * 8
    barrier = threading.Barrier(len(stores))

    def submit(store: RemoteStore) -> str:
        barrier.wait()
        return store.submit_job(
            "u", did, "sentra_health", {"probe": "concurrent"},
            idempotency_key="one-job",
        )

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        job_ids = list(pool.map(submit, stores))

    assert len(set(job_ids)) == 1
    assert first_store.db.execute(
        "SELECT COUNT(*) FROM jobs WHERE user_id=? AND device_id=? AND idempotency_key=?",
        ("u", did, "one-job"),
    ).fetchone()[0] == 1
    second_store.close()
    first_store.close()


def test_remote_store_migrates_duplicate_legacy_idempotency_keys(
    tmp_path: Path,
) -> None:
    database = tmp_path / "idempotent-legacy.sqlite3"
    store = RemoteStore(database)
    pair = store.create_pairing("u", "PC", "win", ["sentra_health"])
    did = store.pair_device(pair["pairing_code"])["device_id"]
    job_ids = [
        store.submit_job("u", did, "sentra_health", {"job": i})
        for i in range(2)
    ]
    store.db.execute("DROP INDEX idx_jobs_idempotency")
    store.db.execute(
        "CREATE INDEX idx_jobs_idempotency "
        "ON jobs(user_id,device_id,idempotency_key)"
    )
    store.db.execute(
        "UPDATE jobs SET idempotency_key='legacy-duplicate' WHERE id IN (?,?)",
        job_ids,
    )
    store.db.commit()
    store.close()

    migrated = RemoteStore(database)
    rows = migrated.db.execute(
        "SELECT id,idempotency_key FROM jobs WHERE id IN (?,?) ORDER BY created,id",
        job_ids,
    ).fetchall()
    assert len(rows) == 2
    assert sum(row["idempotency_key"] == "legacy-duplicate" for row in rows) == 1
    assert sum(row["idempotency_key"] is None for row in rows) == 1
    canonical = next(row for row in rows if row["idempotency_key"] == "legacy-duplicate")
    canonical_arguments = json.loads(
        migrated.db.execute("SELECT arguments FROM jobs WHERE id=?", (canonical["id"],)).fetchone()[0]
    )
    replay_id = migrated.submit_job(
        "u", did, "sentra_health", canonical_arguments,
        idempotency_key="legacy-duplicate",
    )
    assert replay_id == canonical["id"]
    index = next(
        row for row in migrated.db.execute("PRAGMA index_list(jobs)")
        if row["name"] == "idx_jobs_idempotency"
    )
    assert index["unique"] == 1
    migrated.close()
