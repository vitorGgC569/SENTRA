"""SENTRA Electron is only a display of the already authenticated Canvas."""
from __future__ import annotations
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sentra_canvas import electron_host
from sentra_canvas.__main__ import main
from test_sentra_runtime_canvas_center_http import running_canvas, request


def test_electron_launcher_uses_bounded_one_use_ticket_not_argv(tmp_path, monkeypatch):
    process = SimpleNamespace(pid=42422, wait=Mock(return_value=0))
    popen = Mock(return_value=process)
    monkeypatch.setattr(electron_host, "electron_binary", lambda: Path("C:/safe/electron.exe"))
    monkeypatch.setattr(electron_host.subprocess, "Popen", popen)
    monkeypatch.setattr(electron_host.tempfile, "gettempdir", lambda: str(tmp_path))
    timer = Mock()
    monkeypatch.setattr(electron_host.threading, "Timer", lambda *args: timer)
    pid = electron_host.launch_electron(SimpleNamespace(server_port=31212, secret="a" * 48))
    assert pid == 42422 and timer.start.called
    args = popen.call_args.args[0]
    assert args[:2] == [str(Path("C:/safe/electron.exe")), str(electron_host.SURFACE / "main.cjs")]
    assert args[2].startswith("--sentra-ticket=") and len(args[2]) == 48
    assert "secret" not in str(popen.call_args) and "aaaa" not in str(popen.call_args)
    tickets = list(tmp_path.glob("sentra-electron-*.json"))
    assert len(tickets) == 1
    payload = json.loads(tickets[0].read_text(encoding="utf-8"))
    assert payload["schema"] == 1 and payload["port"] == 31212
    assert payload["secret"] == "a" * 48 and payload["expires_at"] > 0
    assert not popen.call_args.kwargs["stdin"] is None


def test_electron_launcher_rejects_missing_runtime_and_bad_endpoint(monkeypatch):
    monkeypatch.setattr(electron_host, "electron_binary", lambda: None)
    with pytest.raises(FileNotFoundError):
        electron_host.launch_electron(SimpleNamespace(server_port=31212, secret="a" * 48))
    monkeypatch.setattr(electron_host, "electron_binary", lambda: Path("C:/safe/electron.exe"))
    with pytest.raises(ValueError):
        electron_host.launch_electron(SimpleNamespace(server_port=0, secret="a" * 48))
    with pytest.raises(PermissionError):
        electron_host.launch_electron(SimpleNamespace(server_port=31212, secret="weak"))


def test_canvas_electron_endpoint_requires_bearer_and_explicit_consent(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(electron_host, "electron_status", lambda: {"available": True})
    monkeypatch.setattr(electron_host, "launch_electron", lambda endpoint, wait=False: called.append(
        (endpoint.server_port, endpoint.secret, wait)) or 56565)
    with running_canvas(tmp_path) as (_app, server):
        status, body = request(server, "/api/desktop/surfaces")
        assert status == 200 and body["electron"]["available"]
        assert body["terminal"]["available"]
        status, _ = request(server, "/api/desktop/surfaces", authorized=False)
        assert status == 401
        status, _ = request(server, "/api/desktop/electron", json_body={"confirm": True}, authorized=False)
        assert status == 401
        status, _ = request(server, "/api/desktop/electron", json_body={"confirm": False})
        assert status == 403
        assert called == []
        status, body = request(server, "/api/desktop/electron", json_body={"confirm": True})
        assert status == 200 and body["pid"] == 56565
        assert called == [(server.server_port, server.secret, False)]


def test_canvas_ui_selection_routes_to_same_backend(tmp_path, monkeypatch):
    from sentra_canvas import broker
    monkeypatch.setattr(broker, "connect_or_start", lambda *args, **kwargs: SimpleNamespace(
        server_port=49900, secret="a" * 48))
    called = []
    monkeypatch.setattr(electron_host, "launch_electron", lambda endpoint, wait=False:
                        called.append((endpoint.server_port, wait)) or 0)
    assert main(["--root", str(tmp_path), "--ui", "electron"]) == 0
    assert called == [(49900, True)]
