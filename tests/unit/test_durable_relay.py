import json
import urllib.error
import urllib.request

import pytest

from native_bridge.job_store import JobStore
from native_bridge.protocol import ChatJob, ChatResult
from native_bridge.relay import RelayServer


def test_restart_leases_correlation_duplicate_and_ack(tmp_path):
    path = tmp_path / "jobs.sqlite"
    store = JobStore(path)
    jid = store.submit(ChatJob(task_id="T", prompt="read code"))
    leased = store.poll("TAB-1")
    store.close()
    store = JobStore(path)
    assert store.poll("TAB-2") is None
    result = ChatResult(job_id=jid, task_id="T", worker="TAB-1", result="ok")
    with pytest.raises(ValueError, match="FOREIGN"):
        store.store_result(result, "forged")
    result.task_id = "other"
    with pytest.raises(ValueError, match="TASK_MISMATCH"):
        store.store_result(result, leased["lease_token"])
    result.task_id = "T"
    store.lease(jid, "TAB-1", leased["lease_token"])
    store.store_result(result, leased["lease_token"])
    store.store_result(result, leased["lease_token"])
    assert store.counts()["completed"] == 1
    assert store.result(jid) == store.result(jid)
    store.acknowledge(jid)
    assert store.result(jid)["result"] == "ok"
    store.close()


def test_expired_lease_fails_without_duplicate_remote_execution():
    now = [100.0]
    store = JobStore(clock=lambda: now[0])
    jid = store.submit(ChatJob(task_id="T", prompt="hi"))
    job = store.poll("TAB-1")
    now[0] += 31
    assert store.poll("TAB-2") is None
    assert store.result(jid)["status"] == "FAILED"
    with pytest.raises(ValueError, match="STALE"):
        store.store_result(ChatResult(job_id=jid, task_id="T", worker="TAB-1", result="late"), job['lease_token'])
    store.close()


def test_auth_origin_bounds_and_loopback():
    with pytest.raises(ValueError):
        RelayServer(host="0.0.0.0")
    server = RelayServer(port=0).start()
    base = f"http://127.0.0.1:{server.server.server_port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + "/jobs/poll?worker=TAB-1")
        assert error.value.code == 401
        req = urllib.request.Request(base + "/auth/check", headers={"Authorization": "Bearer " + server.token,
                                                                    "Origin": "https://malicious.example"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        assert error.value.code == 403
        req = urllib.request.Request(base + "/auth/check", headers={"Authorization": "Bearer " + server.token})
        with urllib.request.urlopen(req) as response:
            assert json.load(response)["ok"]
    finally:
        server.stop()


def test_progress_extends_lease_past_heartbeat_window():
    now = [1000.0]
    store = JobStore(clock=lambda: now[0])
    jid = store.submit(ChatJob(task_id="T", prompt="hi", timeout_s=300))
    job = store.poll("TAB-1")
    assert job["lease_until"] == pytest.approx(1030.0)
    now[0] = 1010.0
    info = store.progress(jid, "TAB-1", job["lease_token"], "waiting")
    assert info["lease_until"] == pytest.approx(1130.0)
    now[0] = 1060.0  # 30s alem do lease original de 1030
    assert store.result(jid) is None
    assert store.counts()["leased"] == 1
    assert store.poll("TAB-2") is None
    store.close()


def test_progress_respects_absolute_cap():
    now = [2000.0]
    store = JobStore(clock=lambda: now[0])
    jid = store.submit(ChatJob(task_id="T", prompt="hi", timeout_s=100))
    job = store.poll("TAB-1")
    assert job["deadline"] == pytest.approx(2100.0)
    now[0] = 2025.0
    store.progress(jid, "TAB-1", job["lease_token"], "waiting")
    now[0] = 2090.0
    info = store.progress(jid, "TAB-1", job["lease_token"], "waiting")
    assert info["deadline"] == pytest.approx(2100.0)
    assert info["lease_until"] <= 2100.0
    assert job["deadline"] == pytest.approx(2100.0)
    now[0] = 2101.0
    res = store.result(jid)
    assert res["status"] == "FAILED"
    assert "DELIVERY_SLOW" in (res["error"] or "")
    store.close()


def test_orphan_safe_requeues_once_then_fails():
    now = [3000.0]
    store = JobStore(clock=lambda: now[0])
    jid = store.submit(ChatJob(task_id="T", prompt="hi", timeout_s=300))
    first = store.poll("TAB-1")
    now[0] = 3010.0
    store.progress(jid, "TAB-1", first["lease_token"], "navigating")
    now[0] = 3131.0  # lease (3130) + progresso (120s) ambos vencidos, deadline futuro
    counts = store.counts()
    assert counts["queued"] == 1 and counts["failed"] == 0 and counts["leased"] == 0
    second = store.poll("TAB-2")
    assert second is not None and second["requeues"] == 1
    now[0] += 31  # lease do segundo dono expira sem nenhum progresso: prova ausente
    assert store.poll("TAB-3") is None
    res = store.result(jid)
    assert res["status"] == "FAILED"
    assert "WORKER_LOST" in (res["error"] or "")
    assert store.counts()["failed"] == 1
    store.close()


def test_unsafe_phase_never_requeues_and_errors_differ():
    now = [4000.0]
    store = JobStore(clock=lambda: now[0])
    jid = store.submit(ChatJob(task_id="T", prompt="hi", timeout_s=300))
    job = store.poll("TAB-1")
    now[0] = 4010.0
    store.progress(jid, "TAB-1", job["lease_token"], "sent")
    now[0] = 4131.0
    assert store.counts()["failed"] == 1
    assert store.counts()["queued"] == 0
    lost = store.result(jid)
    assert "WORKER_LOST" in (lost["error"] or "")
    store.close()

    now2 = [5000.0]
    slow = JobStore(clock=lambda: now2[0])
    jid2 = slow.submit(ChatJob(task_id="T2", prompt="hi", timeout_s=60))
    job2 = slow.poll("TAB-1")
    now2[0] = 5020.0
    slow.progress(jid2, "TAB-1", job2["lease_token"], "waiting")
    now2[0] = 5050.0
    slow.progress(jid2, "TAB-1", job2["lease_token"], "waiting")
    now2[0] = 5061.0  # deadline 5060 estourou com progresso recente
    res2 = slow.result(jid2)
    assert res2["status"] == "FAILED"
    assert "DELIVERY_SLOW" in (res2["error"] or "")
    assert "WORKER_LOST" not in (res2["error"] or "")
    assert lost["error"] != res2["error"]
    slow.close()


def test_progress_validation_and_lease_binding():
    now = [6000.0]
    store = JobStore(clock=lambda: now[0])
    jid = store.submit(ChatJob(task_id="T", prompt="hi", timeout_s=120))
    job = store.poll("TAB-1")
    with pytest.raises(ValueError, match="unknown phase"):
        store.progress(jid, "TAB-1", job["lease_token"], "flying")
    with pytest.raises(ValueError, match="STALE_OR_FOREIGN_LEASE"):
        store.progress(jid, "TAB-2", job["lease_token"], "waiting")
    with pytest.raises(ValueError, match="STALE_OR_FOREIGN_LEASE"):
        store.progress(jid, "TAB-1", "forged", "waiting")
    assert store.result(jid) is None
    store.close()
