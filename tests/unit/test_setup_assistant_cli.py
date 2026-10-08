"""Consent and credential-redaction contract for the agent-facing setup entrypoint."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.commander import setup_assistant_cli as cli
from sentra_remote.product import ProductPaths, ProductSettings


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    monkeypatch.setattr(cli.ProductSettings, "load", lambda _: ProductSettings())
    runtime = Mock()
    assistant = Mock()
    monkeypatch.setattr(cli, "LocalRuntime", lambda *_args: runtime)
    monkeypatch.setattr(cli, "SetupAssistant", lambda *_args: assistant)
    return paths, assistant


def test_doctor_returns_real_report(prepared):
    paths, assistant = prepared
    assistant.doctor.return_value = {"ready": True, "capabilities": []}
    result = cli.execute("doctor", paths=paths)
    assert result["ok"] is True
    assistant.doctor.assert_called_once_with()


def test_start_local_requires_explicit_approval(prepared):
    paths, assistant = prepared
    result = cli.execute("start-local", paths=paths)
    assert result["reason"] == "approval_required_to_start_services"
    assistant.start_local.assert_not_called()
    assistant.start_local.return_value = {"ok": True}
    assert cli.execute("start-local", paths=paths, approved=True)["ok"]


def test_tunnel_key_not_returned_from_entrypoint(prepared):
    paths, assistant = prepared
    assistant.connect_openai.return_value = {"ok": True}
    secret = "sk-not-a-real-runtime-key-this-is-test-data"
    result = cli.execute(
        "connect-openai", paths=paths, approved=True,
        tunnel_id="tunnel_example-id123", runtime_key=secret,
    )
    assert result == {"ok": True}
    assistant.connect_openai.assert_called_once_with(
        "tunnel_example-id123", secret, approved=True
    )
    assert secret not in json.dumps(result)


def test_optional_package_needs_exact_request(prepared):
    paths, assistant = prepared
    assistant.install_optional.return_value = {"ok": True}
    result = cli.execute(
        "install-optional", paths=paths, approved=True, optional="git"
    )
    assert result["ok"]
    assistant.install_optional.assert_called_once_with("git", approved=True)


def test_external_workspace_requires_approval(prepared, tmp_path):
    paths, assistant = prepared
    external = tmp_path / "project"
    external.mkdir()
    blocked = cli.execute("workspace", paths=paths, workspace=external)
    assert blocked["reason"] == "approval_required_for_workspace"
    assistant.prepare_workspace.assert_not_called()
    assistant.prepare_workspace.return_value = str(external)
    allowed = cli.execute(
        "workspace", paths=paths, approved=True,
        workspace=external, permissions=("read", "write"),
    )
    assert allowed["workspace"] == str(external)
    assert allowed["permissions"] == ["read", "write"]


def test_cli_missing_runtime_key_does_not_contact_openai(
    prepared, monkeypatch, tmp_path, capsys
):
    _, assistant = prepared
    monkeypatch.delenv("CONTROL_PLANE_API_KEY", raising=False)
    report = tmp_path / "state"
    install = tmp_path / "install"
    code = cli.main([
        "connect-openai", "--approve",
        "--install-dir", str(install), "--state-dir", str(report),
        "--tunnel-id", "tunnel_example-id123",
    ])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["reason"] == (
        "provide_tunnel_id_and_runtime_api_key_env"
    )
    assistant.connect_openai.assert_not_called()
