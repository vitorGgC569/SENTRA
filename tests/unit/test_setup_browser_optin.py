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


def test_existing_install_opens_browser_handoff_with_user_opt_in(
    tmp_path, monkeypatch
):
    install_dir = tmp_path / "sentra"
    install_dir.mkdir()
    (install_dir / "sentra-desktop.exe").write_bytes(b"stub")
    monkeypatch.setattr(
        installer, "_validate_sentra_install", lambda _: None
    )
    commands = []
    approvals = []
    monkeypatch.setattr(installer, "authorize_installer_enrollment", lambda paths: approvals.append(paths))
    monkeypatch.setattr(
        installer.subprocess, "Popen",
        lambda cmd, **kwargs: commands.append((cmd, kwargs)),
    )
    wizard = object.__new__(installer.InstallerWizard)
    wizard.browser_setup_var = Mock()
    wizard.browser_setup_var.get.return_value = True
    wizard.profile = Mock()
    wizard.profile.get.return_value = "Full"
    wizard.access_scope = Mock()
    wizard.access_scope.get.return_value = "computer"
    from sentra_remote.product import ProductPaths, ProductSettings
    paths = ProductPaths(install_dir, tmp_path / "state")
    monkeypatch.setattr(installer.ProductPaths, "default", lambda *_: paths)
    managed = Mock()
    monkeypatch.setattr(installer, "LocalRuntime", lambda *_: managed)
    wizard.root = Mock()
    wizard._open_existing_install(install_dir)
    assert len(commands) == 1
    assert len(approvals) == 1
    assert approvals[0].install_dir == install_dir.resolve()
    saved = ProductSettings.load(paths.settings)
    assert saved.profile == "Full" and saved.access_scope == "computer"
    assert saved.policy()["surfaces"] == ("all",)
    assert not saved.tool_allowlist
    managed.stop_all.assert_called_once()
    assert commands[0][0][-2:] == [
        "--open-url", "sentra://openai-enroll"
    ]
    wizard.root.destroy.assert_called_once_with()


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
    assert "consent" in wizard.connect_hint.configure.call_args.kwargs["text"].lower()
