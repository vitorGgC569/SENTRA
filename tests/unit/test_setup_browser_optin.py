"""Installer/desktop handoff: browser automation is opt-in and starts after install."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from sentra_remote import desktop, installer


def test_installer_does_not_report_openai_ready_from_local_health_only():
    verdict = {"core_ready": True, "onboarding_required": False,
               "chatgpt_onboarding": {"ready": False},
               "status": {"mcp": {"ok": True}, "tunnel": {"ok": False}}}
    assert installer._installation_ready(verdict, openai_required=False)
    assert not installer._installation_ready(verdict, openai_required=True)
    verdict["status"]["tunnel"]["ok"] = True
    verdict["chatgpt_onboarding"]["ready"] = True
    assert installer._installation_ready(verdict, openai_required=True)


def test_deep_link_allowlist_exposes_only_local_browser_onboarding():
    assert desktop._internal_deep_link_target(
        "sentra://openai-enroll"
    ) == "openai_enroll"
    assert desktop._internal_deep_link_target(
        "https://platform.openai.com/settings/organization/api-keys"
    ) is None
    assert desktop._internal_deep_link_target(
        "sentra://openai-enroll.attacker.invalid"
    ) is None


def test_existing_install_reuses_verification_without_stopping_sessions(tmp_path):
    wizard = object.__new__(installer.InstallerWizard)
    wizard._install = Mock()
    wizard._open_existing_install(tmp_path)
    wizard._install.assert_called_once_with(require_openai=False, verify_only=True)


def test_fresh_installer_first_install_then_opens_consent_wizard(
    tmp_path, monkeypatch
):
    install_dir = tmp_path / "sentra"
    install_dir.mkdir()
    (install_dir / "sentra-desktop.exe").write_bytes(b"stub")
    wizard = object.__new__(installer.InstallerWizard)
    def variable(value):
        obj = Mock()
        obj.get.return_value = value
        return obj
    wizard.tunnel_id = variable("")
    wizard.runtime_key = variable("")
    wizard.install_dir = variable(str(install_dir))
    wizard.workspace = variable("")
    wizard.profile = variable("Developer")
    wizard.access_scope = variable("workspace")
    wizard.git_var = variable(False)
    wizard.docker_var = variable(False)
    wizard.browser_setup_var = variable(True)
    wizard.install_button = Mock()
    wizard.status = Mock()
    wizard.progress_value = Mock()
    wizard.connect_hint = Mock()
    wizard.root = Mock()
    wizard.root.after.side_effect = lambda _delay, callback: callback()
    wizard._installed = False
    wizard._schedule_connection_check = Mock()

    provided = []
    approvals = []
    monkeypatch.setattr(installer, "authorize_installer_enrollment", lambda paths: approvals.append(paths))
    monkeypatch.setattr(
        installer, "install",
        lambda **kwargs: provided.append(kwargs) or {
            "connect_verify": {"core_ready": True}
        },
    )
    commands = []
    monkeypatch.setattr(
        installer.subprocess, "Popen",
        lambda cmd, **kw: commands.append(cmd),
    )

    class InlineThread:
        def __init__(self, target, daemon):
            self.target = target
            assert daemon
        def start(self):
            self.target()

    monkeypatch.setattr(
        threading, "Thread", InlineThread
    )
    wizard._install(require_openai=False)
    assert provided and provided[0]["launch"] is False
    assert len(approvals) == 1
    assert len(commands) == 1
    assert commands[0][-2:] == [
        "--open-url", "sentra://openai-enroll"
    ]
    assert wizard._installed is True
    assert "Edge" in wizard.connect_hint.configure.call_args.kwargs["text"]
    wizard._schedule_connection_check.assert_called_once()
    wizard.root.destroy.assert_not_called()
    assert 100 not in [call.args[0] for call in wizard.progress_value.set.call_args_list]
