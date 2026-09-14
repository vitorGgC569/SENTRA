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
