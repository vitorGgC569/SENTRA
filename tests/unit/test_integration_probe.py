"""Safe, falsifiable integration diagnostics without external account access."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.commander import integration_probe as probe


def test_absent_tool_reports_not_ready(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda _: None)
    result = probe._command("ollama", ["--version"])
    assert result["installed"] is False
    assert result["ready"] is False


def test_tool_installed_but_daemon_unavailable_is_not_ready(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda _: "docker.exe")
    monkeypatch.setattr(
        probe.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, stdout="secret-marker", stderr="sensitive"),
    )
    result = probe._command("docker", ["info"])
    assert result["installed"] is True
    assert result["ready"] is False
    assert "secret-marker" not in json.dumps(result)
    assert "sensitive" not in json.dumps(result)


def test_full_integration_requires_every_surface(monkeypatch, tmp_path):
    from sentra_remote import setup_assistant
    from sentra_remote import desktop
    from sentra_remote import product
    from sentra_remote import local_runtime

    monkeypatch.setattr(
        product.ProductPaths,
        "default",
        classmethod(lambda _cls, _dir: product.ProductPaths(
            tmp_path / "install", tmp_path / "state"
        )),
    )
    monkeypatch.setattr(
        probe, "_command",
        lambda name, args, timeout=8: {"installed": True, "ready": name != "docker"},
    )
    monkeypatch.setattr(
        probe, "_http",
        lambda url, timeout=2: {"online": False},
    )
    monkeypatch.setattr(
        setup_assistant, "local_model_status",
        lambda: {"ready": False, "models": []},
    )
    monkeypatch.setattr(desktop, "_codex_route_points_to_sentra", lambda: False)
    monkeypatch.setattr(
        local_runtime, "LocalRuntime",
        lambda *_args: type("Stub", (), {"status": lambda _self: {"tunnel": {"ok": False}}})(),
    )
    result = probe.probe(tmp_path / "install")
    assert result["ok"]
    assert not result["full_integration_ready"]
    assert result["checks"]["docker"]["ready"] is False
    assert result["checks"]["codex"]["model_route_to_sentra"] is False
    assert result["checks"]["chatgpt_plugin"]["requires_account_authorization"] is True


def test_probe_cli_is_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        probe, "probe",
        lambda _dir: {"ok": True, "checks": {}, "privacy": "no secrets"},
    )
    code = probe.main(["--install-dir", str(tmp_path)])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["privacy"] == "no secrets"
