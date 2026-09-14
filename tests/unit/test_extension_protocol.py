"""Protocolo do bridge: validação de jobs/resultados + framing Native Messaging."""
import pytest

from native_bridge.protocol import ChatJob, ChatResult
from native_bridge.host import encode_message, decode_messages


def test_job_validation_ok_and_limits():
    j = ChatJob(task_id="T-1", prompt="hello", timeout_s=60)
    j.validate()
    with pytest.raises(ValueError):
        ChatJob(task_id="", prompt="x").validate()
    with pytest.raises(ValueError):
        ChatJob(task_id="T", prompt="x" * 20001).validate()
    with pytest.raises(ValueError):
        ChatJob(task_id="T", prompt="x", timeout_s=3600).validate()


def test_result_validation_rejects_unknown_status():
    r = ChatResult(job_id="job_1", task_id="T-1", status="COMPLETED", result="ok")
    r.validate()
    with pytest.raises(ValueError):
        ChatResult(job_id="job_1", status="MAYBE").validate()
    with pytest.raises(ValueError):
        ChatResult(job_id="", status="FAILED").validate()


def test_continuation_requires_explicit_trusted_conversation_url():
    with pytest.raises(ValueError):
        ChatJob(task_id="T", prompt="code", new_chat=False).validate()
    with pytest.raises(ValueError):
        ChatJob(task_id="T", prompt="code", new_chat=False,
                conversation_url="https://attacker.example/c/123").validate()
    ChatJob(task_id="T", prompt="code", new_chat=False,
            conversation_url="https://chatgpt.com/c/123-abc").validate()


def test_relay_extension_version_endpoint(tmp_path):
    import json as _json
    import urllib.request as _url
    from native_bridge.relay import RelayServer
    from pathlib import Path as _P
    ext = _P(__file__).resolve().parent.parent.parent / "edge_extension"
    server = RelayServer(port=18777, extension_dir=str(ext)).start()
    try:
        with _url.urlopen("http://127.0.0.1:18777/extension/version") as r:
            data = _json.loads(r.read())
        manifest = _json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
        assert data["version"] == manifest["version"]
        assert "service-worker.js" in data["files"]
    finally:
        server.stop()


def test_relay_submit_poll_result_wait_roundtrip():
    import urllib.request as _url
    import urllib.parse as _up
    from native_bridge.relay import RelayServer

    server = RelayServer(port=18778).start()
    try:
        base = "http://127.0.0.1:18778"

        def post(path, payload):
            req = _url.Request(base + path, data=__import__("json").dumps(payload).encode(),
                               headers={"Content-Type": "application/json", "Authorization": "Bearer " + server.token})
            return __import__("json").loads(_url.urlopen(req).read())

        job_id = post("/jobs/submit", {"task_id": "T-1", "prompt": "hi", "timeout_s": 60})["job_id"]
        assert job_id.startswith("job_")
        with _url.urlopen(_url.Request(base + "/jobs/poll?worker=TAB-1", headers={"Authorization": "Bearer " + server.token})) as r:
            polled = __import__("json").loads(r.read())["job"]
        assert polled["job_id"] == job_id and polled["task_id"] == "T-1"
        post("/jobs/result", {"job_id": job_id, "task_id": "T-1", "status": "COMPLETED",
                              "result": "ok", "worker": "TAB-1", "lease_token": polled["lease_token"]})
        with _url.urlopen(_url.Request(base + f"/jobs/wait?job_id={job_id}&timeout_s=5", headers={"Authorization": "Bearer " + server.token})) as r:
            done = __import__("json").loads(r.read())
        assert done["status"] == "COMPLETED" and done["result"] == "ok"
        with _url.urlopen(base + "/health") as r:
            h = __import__("json").loads(r.read())
        assert h["submitted"] == 1 and h["completed"] == 1 and "TAB-1" in h["workers_online"]
    finally:
        server.stop()


def test_probe_kind_validates_and_queues():
    import urllib.request as _url
    import urllib.error as _ue
    from native_bridge.relay import RelayServer
    from native_bridge.protocol import ChatJob

    ChatJob(task_id="T-p", kind="STATUS_PROBE", new_chat=False).validate()
    try:
        ChatJob(task_id="T-p", kind="NOPE").validate()
        raise AssertionError("invalid kind accepted")
    except ValueError:
        pass

    server = RelayServer(port=18779).start()
    try:
        import json as _j
        auth = {"Content-Type": "application/json", "Authorization": "Bearer " + server.token}

        def post(payload):
            req = _url.Request("http://127.0.0.1:18779/jobs/submit",
                               data=_j.dumps(payload).encode(), headers=dict(auth))
            return _j.loads(_url.urlopen(req).read())

        ok = post({"task_id": "T-p", "timeout_s": 60, "new_chat": False, "kind": "STATUS_PROBE"})
        assert ok["job_id"].startswith("job_")
        try:
            post({"task_id": "T-p", "timeout_s": 60, "kind": "NOPE"})
            raise AssertionError("relay accepted invalid kind")
        except _ue.HTTPError as e:
            assert e.code == 400
    finally:
        server.stop()


def test_native_framing_roundtrip_and_partial():
    m1 = {"operation": "CREATE_CHAT", "task_id": "T-1"}
    m2 = {"operation": "SEND_MESSAGE", "text": "hi"}
    buf = encode_message(m1) + encode_message(m2)
    msgs, rest = decode_messages(buf)
    assert msgs == [m1, m2] and rest == b""
    # parcial: prefixo sem corpo completo fica no restante
    partial = encode_message(m1)[:6]
    msgs, rest = decode_messages(partial)
    assert msgs == [] and rest == partial
