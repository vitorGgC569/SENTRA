from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from sentra_remote.relay import RemoteRelayServer
from sentra_remote.store import RemoteStore


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
