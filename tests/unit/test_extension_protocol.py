"""Protocolo do bridge: validação de jobs/resultados + framing Native Messaging."""
import pytest

from native_bridge.protocol import ChatJob, ChatResult
from native_bridge.protocol import PRE_SEND_PHASES, PROGRESS_PHASES
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
    import shutil as _shutil
    import urllib.request as _url
    from native_bridge.relay import RelayServer
    from pathlib import Path as _P
    ext_source = _P(__file__).resolve().parent.parent.parent / "edge_extension"
    ext = tmp_path / "edge_extension"
    _shutil.copytree(ext_source, ext)
    server = RelayServer(port=18777, extension_dir=str(ext)).start()
    try:
        bootstrap = ext / "sentra-bootstrap.json"
        bootstrap.write_text('{"stale":true}\n', encoding="utf-8")

        with _url.urlopen("http://127.0.0.1:18777/extension/version") as r:
            data = _json.loads(r.read())

        manifest = _json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
        healed = _json.loads(bootstrap.read_text(encoding="utf-8"))
        assert data["version"] == manifest["version"]
        assert "service-worker.js" in data["files"]
        assert data["bootstrap_refreshed"] is True
        assert "token" not in data and "proof" not in data
        assert healed["extension_version"] == manifest["version"]
        assert healed["build_id"] == manifest["sentra_build_id"]
        assert healed["source_hash"] == manifest["sentra_source_hash"]
        assert len(healed["proof"]) == 64
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
        with _url.urlopen(_url.Request(
            base + f"/jobs/wait?job_id={job_id}&timeout_s=0.01",
            headers={"Authorization": "Bearer " + server.token},
        )) as r:
            queued = __import__("json").loads(r.read())
        assert queued["pending"] is True and queued["state"] == "QUEUED"
        with _url.urlopen(_url.Request(base + "/jobs/poll?worker=TAB-1", headers={"Authorization": "Bearer " + server.token})) as r:
            polled = __import__("json").loads(r.read())["job"]
        assert polled["job_id"] == job_id and polled["task_id"] == "T-1"
        with _url.urlopen(_url.Request(
            base + f"/jobs/wait?job_id={job_id}&timeout_s=0.01",
            headers={"Authorization": "Bearer " + server.token},
        )) as r:
            leased = __import__("json").loads(r.read())
        assert leased["pending"] is True and leased["state"] == "LEASED"
        assert leased["deadline"] == pytest.approx(polled["deadline"])
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


def test_extension_presence_heartbeat_is_independent_from_controller_workers():
    import json as _json
    import urllib.request as _url
    from native_bridge.relay import RelayServer

    server = RelayServer(port=18781).start()
    try:
        base = "http://127.0.0.1:18781"
        req = _url.Request(
            base + "/extension/heartbeat",
            data=_json.dumps({
                "status": {
                    "sw_version": "1.6.51",
                    "sw_build_id": "sentra-edge-1.6.51-durable-r26",
                }
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + server.token,
            },
            method="POST",
        )
        with _url.urlopen(req) as response:
            posted = _json.loads(response.read())

        assert posted["ok"] is True
        assert posted["extension"]["online"] is True

        with _url.urlopen(base + "/health") as response:
            health = _json.loads(response.read())

        assert health["workers_online"] == []
        assert health["extension"]["online"] is True
        assert health["extension"]["last_seen"] is not None
        assert health["extension"]["status"]["sw_version"] == "1.6.51"
    finally:
        server.stop()


def test_worker_release_removes_online_status_without_forgetting_seen_count():
    import json as _json
    import urllib.request as _url
    from native_bridge.relay import RelayServer

    server = RelayServer(port=18780).start()
    try:
        base = "http://127.0.0.1:18780"
        auth = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + server.token,
        }

        def post(path, payload):
            req = _url.Request(
                base + path,
                data=_json.dumps(payload).encode(),
                headers=dict(auth),
            )
            return _json.loads(_url.urlopen(req).read())

        for worker in ("TAB-1", "TAB-2"):
            req = _url.Request(
                base + f"/jobs/poll?worker={worker}",
                headers={"Authorization": "Bearer " + server.token},
            )
            with _url.urlopen(req) as response:
                _json.loads(response.read())

        with _url.urlopen(base + "/health") as response:
            before = _json.loads(response.read())
        assert set(before["workers_online"]) == {"TAB-1", "TAB-2"}
        assert before["workers_ever_seen"] == 2

        assert post("/workers/release", {"worker": "TAB-1"})["released"] is True

        with _url.urlopen(base + "/health") as response:
            after = _json.loads(response.read())
        assert after["workers_online"] == ["TAB-2"]
        assert after["workers_ever_seen"] == 2
    finally:
        server.stop()


def test_chat_start_and_collect_protocol_contract():
    start = ChatJob(
        task_id="T-start",
        prompt="research this",
        kind="CHAT_START",
        new_chat=False,
    )
    start.validate()
    assert start.new_chat is True
    assert start.conversation_url is None

    collect = ChatJob(
        task_id="T-collect",
        prompt="",
        kind="CHAT_COLLECT",
        new_chat=True,
        conversation_url="https://chatgpt.com/c/abc-123",
    )
    collect.validate()
    assert collect.new_chat is False
    assert collect.conversation_url == "https://chatgpt.com/c/abc-123"

    with pytest.raises(ValueError, match="requires conversation_url"):
        ChatJob(task_id="T-collect", prompt="", kind="CHAT_COLLECT").validate()
    with pytest.raises(ValueError, match="does not accept prompt"):
        ChatJob(
            task_id="T-collect",
            prompt="must not send",
            kind="CHAT_COLLECT",
            conversation_url="https://chatgpt.com/c/abc-123",
        ).validate()


    peek = ChatJob(
        task_id="T-peek",
        prompt="",
        kind="CHAT_PEEK",
        conversation_url="https://chatgpt.com/c/abc-123",
        timeout_s=15,
    )
    peek.validate()
    assert peek.new_chat is False
    assert "peeking" in PROGRESS_PHASES
    assert "peeking" in PRE_SEND_PHASES


def test_browser_action_can_bootstrap_without_target_worker():
    from native_bridge.protocol import ChatJob

    job = ChatJob(
        task_id="T-browser-bootstrap",
        kind="BROWSER_ACTION",
        new_chat=False,
        browser_action="navigate",
        browser_args={"url": "https://chatgpt.com/"},
    )
    job.validate()
    assert job.target_worker == ""

    targeted = ChatJob(
        task_id="T-browser-targeted",
        kind="BROWSER_ACTION",
        new_chat=False,
        browser_action="extract",
        browser_args={"selector": "body"},
        target_worker="TAB-123",
    )
    targeted.validate()
    assert targeted.target_worker == "TAB-123"

    screenshot = ChatJob(
        task_id="T-browser-screenshot",
        kind="BROWSER_ACTION",
        new_chat=False,
        browser_action="screenshot",
        browser_args={"full_page": False},
        target_worker="TAB-123",
    )
    screenshot.validate()
    assert screenshot.browser_action == "screenshot"


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


def test_gemini_job_contract_and_conversation_urls():
    job = ChatJob(
        task_id="T-gemini",
        prompt="hello",
        provider="gemini",
        model="pro",
        timeout_s=60,
    )
    job.validate()
    assert job.provider == "gemini"
    assert job.model == "pro"

    followup = ChatJob(
        task_id="T-gemini-follow",
        prompt="continue",
        provider="gemini",
        model="flash",
        new_chat=False,
        conversation_url="https://gemini.google.com/app/abc_DEF-123",
        timeout_s=60,
    )
    followup.validate()
    assert followup.conversation_url == "https://gemini.google.com/app/abc_DEF-123"

    result = ChatResult(
        job_id="job_gemini",
        task_id="T-gemini",
        status="COMPLETED",
        result="ok",
        conversation_url="https://gemini.google.com/app/abc_DEF-123",
    )
    result.validate()
    assert result.conversation_id == "abc_DEF-123"

    with pytest.raises(ValueError, match="Gemini model"):
        ChatJob(task_id="T", prompt="x", provider="gemini", model="unknown").validate()
    with pytest.raises(ValueError, match="DELETE_CHAT"):
        ChatJob(
            task_id="T",
            prompt="abc",
            provider="gemini",
            kind="DELETE_CHAT",
            new_chat=False,
        ).validate()
    with pytest.raises(ValueError, match="ChatGPT conversation"):
        ChatJob(
            task_id="T",
            prompt="x",
            provider="chatgpt",
            new_chat=False,
            conversation_url="https://gemini.google.com/app/abc",
        ).validate()


def test_content_script_accepts_only_whitespace_normalization_for_prompt_match():
    from pathlib import Path
    source = (
        Path(__file__).resolve().parent.parent.parent
        / "edge_extension"
        / "content-script.js"
    ).read_text(encoding="utf-8")
    start = source.index("function omaTextsMatch")
    body = source[start: source.index("\n}", start) + 2]
    assert 'replace(/\\s+/g, "")' in body
    assert "nonWhitespace(a) === nonWhitespace(b)" in body
    assert "non-whitespace" in body
