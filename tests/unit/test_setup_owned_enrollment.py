"""Setup owns enrollment and verifies protected storage before account effects."""
from unittest.mock import Mock

import pytest

from sentra_remote import openai_auto_setup as auto, installer
from sentra_remote.product import ProductPaths


def test_storage_failure_prevents_any_browser_or_account_change(tmp_path, monkeypatch):
    from sentra_remote import openai_browser_enrollment as browser
    start = Mock(side_effect=AssertionError("no browser effects before secure storage"))
    monkeypatch.setattr(browser, "OpenAIConsentBrowser", start)
    monkeypatch.setattr(auto, "protect_secret", Mock(side_effect=OSError("DPAPI unavailable")))
    result = auto.run_setup_enrollment(ProductPaths(tmp_path / "install", tmp_path / "state"), Mock())
    assert result == {"ok": False, "reason": "credential_protection_unavailable"}
    start.assert_not_called()


@pytest.mark.parametrize("outcome", ["ready", "attention", "timeout", "recovered"])
def test_setup_enrollment_recovery_and_completion_are_observed(tmp_path, monkeypatch, outcome):
    from sentra_remote import openai_browser_enrollment as browser, local_runtime
    monkeypatch.setattr(auto, "protect_secret", lambda value: value)
    monkeypatch.setattr(auto, "unprotect_secret", lambda value: value)
    monkeypatch.setattr(local_runtime, "LocalRuntime", Mock())
    monkeypatch.setattr(auto, "recover_enrollment", lambda *_: {"ok": True} if outcome == "recovered" else {"enrollment_needed": True})
    sessions = []
    class Session:
        def __init__(self, paths, notify, runtime, **options):
            self.notify = notify
            self.options = options
            self.close = Mock()
            sessions.append(self)
        def start(self, *, approved, automatic):
            assert approved and automatic
            if outcome != "timeout":
                self.notify("tunnel", "not needed by the UI")
                self.notify("tunnel_ready" if outcome == "recovered" else outcome, "fixed status")
                self.notify("closed", "")
    monkeypatch.setattr(browser, "OpenAIConsentBrowser", Session)
    notify = Mock()
    result = auto.run_setup_enrollment(ProductPaths(tmp_path / "install", tmp_path / "state"), notify, timeout_s=0)
    assert result.get("ok") == (outcome == "ready")
    assert all(call.args[0] != "tunnel" for call in notify.call_args_list)
    if outcome == "recovered":
        assert sessions[0].options["tunnel_verified"] is True
        assert result["tunnel_verified"] is True
    elif outcome == "timeout":
        sessions[0].close.assert_called_once()
        assert result["reason"] == "browser_enrollment_timeout"


@pytest.mark.parametrize("ok", [True, False])
def test_installer_unlocks_after_browser_completion_and_verifies_before_success(tmp_path, monkeypatch, ok):
    monkeypatch.setattr(auto, "run_setup_enrollment", lambda *_: {"ok": ok, "reason": "credential_protection_unavailable"})
    wizard = object.__new__(installer.InstallerWizard)
    wizard.install_dir = Mock(get=lambda: str(tmp_path / "install"))
    for name in ("root", "install_button", "status", "connect_hint", "_install"):
        setattr(wizard, name, Mock())
    callbacks = []
    wizard.root.after.side_effect = lambda _, callback: callbacks.append(callback)
    import threading
    class InlineThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(threading, "Thread", InlineThread)
    wizard._start_browser_setup()
    for callback in callbacks:
        callback()
    assert wizard._browser_setup_running is False
    if ok:
        wizard._install.assert_called_once_with(require_openai=False, verify_only=True, enroll=False)
    else:
        wizard._install.assert_not_called()
        assert wizard.install_button.configure.call_args.kwargs["state"] == "normal"


@pytest.mark.parametrize("ok", [True, False])
def test_silent_browser_setup_owns_enrollment_and_reports_the_verified_result(tmp_path, monkeypatch, ok):
    import json
    install = Mock(return_value={"connect_verify": {"core_ready": True, "onboarding_required": True},
                                "preflight": {"ok": True, "verified": True}})
    monkeypatch.setattr(installer, "install", install)
    enroll = Mock(return_value={"ok": ok, "reason": "tunnel_verified" if ok else "credential_protection_unavailable"})
    monkeypatch.setattr(auto, "run_setup_enrollment", enroll)
    verification = {"core_ready": True, "chatgpt_onboarding": {"ready": True},
                    "status": {"mcp": {"ok": True}, "tunnel": {"ok": True}}}
    verify = Mock(return_value={"connect_verify": verification})
    monkeypatch.setattr(installer, "verify_installed_local", verify)
    report = tmp_path / "report.json"
    state = tmp_path / "state"
    assert installer.main(["--silent", "--browser-setup", "--install-dir", str(tmp_path / "install"),
                           "--state-dir", str(state), "--report-file", str(report),
                           "--no-launch", "--stop-after-doctor"]) == (0 if ok else 2)
    assert install.call_args.kwargs["launch"] is False
    assert enroll.call_args.args[0].state_dir == state
    result = json.loads(report.read_text())
    assert result["ready"] == ok and result["browser_enrollment"]["ok"] == ok
    if ok:
        assert verify.call_args.kwargs["state_dir"] == state
        assert verify.call_args.kwargs["stop_after_doctor"] is True
    else:
        verify.assert_not_called()
        assert result["browser_enrollment"]["reason"] == "credential_protection_unavailable"
