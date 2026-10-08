"""Persistent local broker identity and real process lifecycle checks."""
from __future__ import annotations

import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from sentra_canvas.broker import Endpoint, connect_or_start, read_endpoint


def api(endpoint, path, body=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{endpoint.server_port}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + endpoint.secret,
                 "Content-Type": "application/json"},
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
        return json.loads(response.read())


def stop(endpoint, state):
    try:
        endpoint.request("/api/runtime/shutdown", {"confirm": True})
    except (OSError, urllib.error.URLError):
        pass
    deadline = time.monotonic() + 10
    while (state / "broker.json").exists() and time.monotonic() < deadline:
        time.sleep(.05)
    assert not (state / "broker.json").exists(), "owned broker did not shut down"


@pytest.mark.parametrize("payload", [[], {}, {"schema_version": 88}, {"schema_version": 1, "port": "invalid"}])
def test_invalid_endpoint_record_cannot_be_used(tmp_path, payload):
    (tmp_path / "broker.json").write_text(json.dumps(payload), encoding="utf-8")
    assert read_endpoint(tmp_path) is None


def test_endpoint_representation_never_exposes_bearer_token():
    endpoint = Endpoint(1234, "private_broker_bearer_token", "a" * 32, 1234)
    assert endpoint.secret not in repr(endpoint)


def test_frozen_mcp_launcher_selects_canvas_sibling_not_the_mcp_binary(tmp_path,monkeypatch):
    from sentra_canvas.broker import broker_command
    canvas=tmp_path/"sentra-canvas.exe";canvas.write_bytes(b"owned launch fixture")
    monkeypatch.setattr(sys,"frozen",True,raising=False)
    monkeypatch.setattr(sys,"executable",str(tmp_path/"sentra-mcp.exe"))
    args=["--broker","--root",str(tmp_path)]
    assert broker_command(args)==[str(canvas),*args]
    canvas.unlink()
    with pytest.raises(FileNotFoundError,match="Canvas executable"):
        broker_command(args)


def test_native_window_can_detach_without_owning_broker_lifecycle(monkeypatch):
    from sentra_canvas.native_app import launch_native, WindowControls
    assert {name for name in dir(WindowControls()) if not name.startswith("_")} == {
        "minimize", "toggle_maximize", "close"}
    controls = []
    window = SimpleNamespace(destroy=lambda: controls.append("closed"))
    def create_window(*args, **kwargs):
        controls.append(kwargs["js_api"])
        return window
    def start(**kwargs):
        controls[0].close()
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=create_window, start=start))
    # Endpoint intentionally has no serve_forever or shutdown methods.
    launch_native(Endpoint(1234, "local-token", "a" * 32, 1234), serve=False)
    assert controls[-1] == "closed"


@pytest.mark.skipif(os.name != "nt", reason="real hidden Windows broker, ConPTY and DPAPI")
def test_concurrent_attach_reuses_owner_and_survives_client_detachment(tmp_path):
    state = tmp_path / "state"
    with ThreadPoolExecutor(max_workers=2) as pool:
        endpoints = list(pool.map(lambda _: connect_or_start(tmp_path, state), range(2)))
    first, second = endpoints
    try:
        assert first.pid == second.pid and first.runtime_id == second.runtime_id
        ws = api(first, "/api/workspaces", {"name": "durable_owner"})["id"]
        terminal = api(first, "/api/terminals", {"ws": ws, "name": "live", "shell": "cmd"})
        api(first, "/api/terminal/input", {"ws": ws, "id": terminal["id"], "data": "echo BROKER_REATTACH_OK\r"})
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            output = api(second, f"/api/terminal/output?ws={ws}&id={terminal['id']}")
            if "BROKER_REATTACH_OK" in output["text"]:
                break
            time.sleep(.05)
        assert "BROKER_REATTACH_OK" in output["text"]
        assert output["status"] == "running" and output["persisted"]
        # Recreating the client after its window detached retains the same PTY.
        reopened = connect_or_start(tmp_path, state)
        detail = api(reopened, "/api/workspace?ws=" + ws)
        assert reopened.pid == first.pid
        assert detail["terminals"][0]["pid"] == terminal["pid"]
        encrypted = (state / "broker.json").read_text(encoding="utf-8")
        assert first.secret not in encrypted and "dpapi:" in encrypted
        with pytest.raises(urllib.error.HTTPError) as denied:
            first.request("/api/runtime/shutdown", {"confirm": False})
        assert denied.value.code == 400
        assert read_endpoint(state).pid == first.pid
    finally:
        stop(first, state)


@pytest.mark.skipif(os.name != "nt", reason="real Windows broker restart")
def test_dead_owner_recovers_history_without_automatic_command_replay(tmp_path):
    state = tmp_path / "state"
    endpoint = connect_or_start(tmp_path, state)
    replacement = None
    try:
        ws = api(endpoint, "/api/workspaces", {"name": "crash"})["id"]
        terminal = api(endpoint, "/api/terminals", {"ws": ws, "name": "shell", "shell": "cmd"})
        api(endpoint, "/api/terminal/input", {"ws": ws, "id": terminal["id"], "data": "echo BROKER_CRASH_HISTORY\r"})
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            output = api(endpoint, f"/api/terminal/output?ws={ws}&id={terminal['id']}")
            if "BROKER_CRASH_HISTORY" in output["text"]:
                break
            time.sleep(.05)
        assert "BROKER_CRASH_HISTORY" in output["text"]
        # This PID was just created in this test's isolated state directory.
        os.kill(endpoint.pid, signal.SIGTERM)
        replacement = connect_or_start(tmp_path, state)
        assert replacement.runtime_id != endpoint.runtime_id
        recovered = api(replacement, f"/api/terminal/output?ws={ws}&id={terminal['id']}")
        assert "BROKER_CRASH_HISTORY" in recovered["text"]
        assert recovered["status"] == "interrupted" and not recovered["recoverable"]
        assert recovered["persisted"]
    finally:
        if replacement:
            stop(replacement, state)
        elif read_endpoint(state):
            stop(endpoint, state)
