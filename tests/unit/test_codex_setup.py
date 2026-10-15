import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from sentra_remote import codex_setup as setup, installer


def test_owned_package_uses_actual_port_and_preserves_user_files(tmp_path):
    unrelated = tmp_path / "config.toml"
    unrelated.write_text("model = 'my-model'\n")
    root = setup.stage_plugin(tmp_path, 8123)
    config = root / "sentra-commander/.mcp.json"
    assert json.loads(config.read_text())["mcpServers"]["sentra"]["url"] == "http://127.0.0.1:8123/mcp"
    assert setup.stage_plugin(tmp_path, 8123) == root
    assert unrelated.read_text() == "model = 'my-model'\n"
    manifest = json.loads((root / ".agents/plugins/marketplace.json").read_text())
    assert manifest["plugins"][0]["source"]["path"] == "./sentra-commander"


def test_foreign_integration_directory_is_not_overwritten(tmp_path):
    target = tmp_path / "codex-integration"
    target.mkdir()
    (target / "private.txt").write_text("keep")
    with pytest.raises(ValueError, match="não pertencem"):
        setup.stage_plugin(tmp_path, 8000)
    assert (target / "private.txt").read_text() == "keep"


def test_missing_codex_stages_package_but_never_claims_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "find_codex", lambda: None)
    result = setup.configure_codex(tmp_path, 8000)
    assert not result["installed"] and not result["ready"]
    assert (tmp_path / "codex-integration/.agents/plugins/marketplace.json").is_file()


def installed_item(tmp_path, port=8000, enabled=True):
    root = setup.stage_plugin(tmp_path, port)
    return {"pluginId": setup.PLUGIN_ID, "installed": True, "enabled": enabled,
            "source": {"source": "local", "path": str(root / "sentra-commander")}}


@pytest.mark.parametrize("enabled,port", [(False, 8000), (True, 9000)])
def test_existing_disabled_or_different_endpoint_is_preserved(tmp_path, monkeypatch, enabled, port):
    item = installed_item(tmp_path, port, enabled)
    command = Mock(return_value={"installed": [item]})
    monkeypatch.setattr(setup, "_command", command)
    probe = Mock()
    monkeypatch.setattr(setup, "probe_mcp", probe)
    result = setup.configure_codex(tmp_path, 8000, cli=Path("codex.exe"))
    assert not result["ready"]
    assert command.call_count == 1
    probe.assert_not_called()


@pytest.mark.parametrize("healthy", [False, True])
def test_reuse_requires_real_protocol_health_without_reinstall(tmp_path, monkeypatch, healthy):
    item = installed_item(tmp_path)
    command = Mock(return_value={"installed": [item]})
    monkeypatch.setattr(setup, "_command", command)
    monkeypatch.setattr(setup, "probe_mcp", lambda _: healthy)
    result = setup.configure_codex(tmp_path, 8000, cli=Path("codex.exe"))
    assert result["ready"] is healthy
    assert result["installed"] and not result["host_reload_required"]
    assert result["chatgpt_authorization"] == "unverified"
    assert all(call.args[1:3] == ("plugin", "list") for call in command.call_args_list)


def test_cli_failure_does_not_echo_provider_output(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "_command", Mock(side_effect=RuntimeError("secret-do-not-log")))
    result = setup.configure_codex(tmp_path, 8000, cli=Path("codex.exe"))
    assert not result["ready"] and "secret-do-not-log" not in json.dumps(result)


def verified():
    return {"core_ready": True, "chatgpt_onboarding": {"ready": True},
            "status": {"mcp": {"ok": True}, "tunnel": {"ok": True}}, "codex_plugin": {"ready": True}}


@pytest.mark.parametrize("failure", ["missing_tunnel", "offline_tunnel", "invalid_key", "credentials", "mcp", "codex"])
def test_required_connection_cannot_complete_on_local_health_alone(failure):
    value = verified()
    if failure == "missing_tunnel":
        value["status"].pop("tunnel")
    elif failure == "offline_tunnel":
        value["status"]["tunnel"]["ok"] = False
    elif failure == "invalid_key":
        value["status"]["tunnel"]["reauth_required"] = True
    elif failure == "credentials":
        value["chatgpt_onboarding"]["ready"] = False
    elif failure == "mcp":
        value["status"]["mcp"]["ok"] = False
    else:
        value["codex_plugin"]["ready"] = False
    assert not installer._installation_ready(value)
    assert installer._installation_ready(value, openai_required=False)


def test_wizard_keeps_authorization_pending_after_verified_transport():
    wizard = object.__new__(installer.InstallerWizard)
    wizard.progress_value = Mock()
    wizard.status = Mock()
    wizard.connect_hint = Mock()
    wizard.install_button = Mock()
    wizard._show_tunnel_verified(verified())
    wizard.progress_value.set.assert_called_once_with(95)
    assert "pendente" in wizard.status.set.call_args.args[0]
    assert wizard.install_button.configure.call_args.kwargs["command"] == wizard._open_chatgpt_plugin


def test_browser_completion_is_polled_without_restarting_enrollment(monkeypatch):
    wizard = object.__new__(installer.InstallerWizard)
    wizard.root = Mock()
    wizard.root.after.return_value = "timer-1"
    wizard.install_button = Mock()
    wizard.install_button.cget.return_value = "normal"
    wizard._install = Mock()
    wizard._connection_deadline = 700
    monkeypatch.setattr(installer.time, "monotonic", lambda: 100)
    wizard._schedule_connection_check()
    wizard._schedule_connection_check()
    wizard.root.after.assert_called_once()
    delay, callback = wizard.root.after.call_args.args
    assert delay == 10000
    callback()
    wizard._install.assert_called_once_with(require_openai=False, verify_only=True, enroll=False)
    wizard._connection_deadline = 0
    wizard.root.after.reset_mock()
    wizard._schedule_connection_check()
    wizard.root.after.assert_not_called()
