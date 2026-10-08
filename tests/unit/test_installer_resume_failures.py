"""A partially installed payload and a failed scheduled handoff stay recoverable."""
import json
import threading
from unittest.mock import Mock

import pytest

from sentra_remote import installer


@pytest.mark.parametrize("missing", ["sentra-desktop.exe", "sentra-cli.exe", "tunnel-client.exe"])
def test_marker_with_partial_payload_repairs_instead_of_reopening(tmp_path, missing):
    folder = tmp_path / "Commander"
    folder.mkdir()
    (folder / installer.INSTALL_MARKER).write_text(json.dumps({"product": "SENTRA Desktop"}))
    for name in (*installer.PRODUCTS, "tunnel-client.exe"):
        if name != missing:
            (folder / name).write_bytes(b"installed")
    wizard = object.__new__(installer.InstallerWizard)
    wizard.install_dir = Mock(get=lambda: str(folder))
    wizard.tunnel_id = Mock(get=lambda: "")
    wizard.runtime_key = Mock(get=lambda: "")
    wizard._installed = True  # A previous destination must not leak its state.
    wizard._open_existing_install = Mock()
    wizard._install = Mock()
    wizard._primary_action()
    wizard._open_existing_install.assert_not_called()
    wizard._install.assert_called_once_with(require_openai=False)
    assert wizard._installed is False


@pytest.mark.parametrize("failure", ["authorization", "launch", "missing_desktop"])
def test_scheduled_handoff_failure_unlocks_and_offers_retry(tmp_path, monkeypatch, failure):
    folder = tmp_path / "Commander"
    folder.mkdir()
    if failure != "missing_desktop":
        (folder / "sentra-desktop.exe").write_bytes(b"installed")
    wizard = object.__new__(installer.InstallerWizard)
    for name, value in {"install_dir": str(folder), "workspace": "", "profile": "Full",
                        "access_scope": "computer", "tunnel_id": "", "runtime_key": "",
                        "git_var": False, "docker_var": False, "browser_setup_var": True}.items():
        setattr(wizard, name, Mock(get=lambda selected=value: selected))
    wizard._installed = False
    wizard.install_button = Mock()
    wizard.status = Mock()
    wizard.progress_value = Mock()
    wizard.connect_hint = Mock()
    wizard.root = Mock()
    callbacks = []
    wizard.root.after.side_effect = lambda _delay, callback: callbacks.append(callback)
    monkeypatch.setattr(installer, "install", lambda **_: {"connect_verify": {"core_ready": True}})
    authorize = Mock(side_effect=PermissionError("authorization file locked") if failure == "authorization" else None)
    launch = Mock(side_effect=OSError("desktop launch failed") if failure == "launch" else None)
    monkeypatch.setattr(installer, "authorize_installer_enrollment", authorize)
    monkeypatch.setattr(installer.subprocess, "Popen", launch)
    from tkinter import messagebox
    error = Mock()
    monkeypatch.setattr(messagebox, "showerror", error)

    class InlineThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            self.target()

    monkeypatch.setattr(threading, "Thread", InlineThread)
    wizard._install(require_openai=False)
    # Reproduce the Tk callback running outside the completed worker's try.
    assert callbacks
    for callback in callbacks:
        callback()
    assert wizard.install_button.configure.call_args.kwargs["state"] == "normal"
    assert wizard.install_button.configure.call_args.kwargs["command"] == wizard._primary_action
    error.assert_called_once()
    wizard.root.destroy.assert_not_called()
    if failure == "authorization":
        launch.assert_not_called()
