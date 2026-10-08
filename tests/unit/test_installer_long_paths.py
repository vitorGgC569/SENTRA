"""Installer copying must work with the actual deep npm paths on Windows."""
import os
import shutil
import json
from types import SimpleNamespace
from pathlib import Path

import pytest
from sentra_remote import installer
from sentra_remote import update_helper


@pytest.mark.skipif(os.name != "nt", reason="Win32 extended paths")
def test_deep_runtime_files_copy_and_cleanup_without_global_os_changes(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "installed" / ("workspace-" + "x" * 35)
    relative = Path("resources/runtime/app/node_modules/@mixmark-io/domino/test/w3c/level1/core") / (
        "hc_characterdataindexsizeerrdeletedatacountnegative.js")
    file = Path(installer._filesystem_path(source / relative))
    file.parent.mkdir(parents=True)
    file.write_text("module.exports = 'deep runtime';", encoding="utf-8")
    assert len(str(destination / relative)) > 260
    shutil.copytree(installer._filesystem_path(source), installer._filesystem_path(destination))
    copied = Path(installer._filesystem_path(destination / relative))
    assert copied.read_text(encoding="utf-8") == "module.exports = 'deep runtime';"
    shutil.rmtree(installer._filesystem_path(destination))
    assert not destination.exists()


def test_silent_install_failure_returns_error_and_writes_redacted_diagnostic(tmp_path, monkeypatch):
    def fail(**kwargs):
        raise OSError("api_key=sk-private-test-secret-material")
    monkeypatch.setattr(installer, "install", fail)
    state = tmp_path / "state"
    assert installer.main(["--silent", "--state-dir", str(state),
                           "--install-dir", str(tmp_path / "Commander")]) == 2
    diagnostic = (state / "installer-error.json").read_text()
    assert "sk-private-test-secret-material" not in diagnostic
    assert "OSError" in diagnostic


@pytest.mark.skipif(os.name != "nt", reason="Win32 extended paths")
def test_failed_update_restores_deep_files_and_installation_identity(tmp_path, monkeypatch):
    root = tmp_path / ("installation-" + "x" * 35) / "Commander"
    root.mkdir(parents=True)
    marker = {"product": "SENTRA Desktop", "installation_id": "original-installation"}
    (root / update_helper.INSTALL_MARKER).write_text(json.dumps(marker))
    relative = Path("web-models/resources/runtime/app/node_modules/domino/test/w3c/level1/core") / ("file-" + "y" * 70 + ".js")
    deep = Path(installer._filesystem_path(root / relative))
    deep.parent.mkdir(parents=True)
    deep.write_bytes(b"original runtime")
    setup = tmp_path / "Setup.exe"
    setup.write_bytes(b"fixture executable")
    stopped = []
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda path: stopped.append(path))
    monkeypatch.setattr(update_helper.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=2))
    with pytest.raises(RuntimeError, match="setup exited"):
        update_helper.apply_update(setup, root, parent_pid=0, version="new", manifest_url="",
                                   restart_desktop=False)
    assert stopped == [root.resolve()]
    assert deep.read_bytes() == b"original runtime"
    assert json.loads((root / update_helper.INSTALL_MARKER).read_text()) == marker


def test_rollback_rejects_other_installation_before_mutation(tmp_path, monkeypatch):
    root = tmp_path / "Commander"
    backup = tmp_path / "Rollback/previous"
    state = tmp_path / "state"
    for folder in (root, backup, state):
        folder.mkdir(parents=True)
    marker = json.dumps({"product": "SENTRA Desktop"})
    for folder in (root, backup):
        (folder / update_helper.INSTALL_MARKER).write_text(marker)
    (root / "keep.txt").write_text("user installation")
    (state / "update-state.json").write_text(json.dumps({
        "previous_backup": str(backup), "install_dir": str(tmp_path / "OtherCommander"),
    }))
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    with pytest.raises(ValueError, match="another installation"):
        update_helper.rollback_update(root, parent_pid=0, restart_desktop=False)
    assert (root / "keep.txt").read_text() == "user installation"


@pytest.mark.skipif(os.name != "nt", reason="Windows external uninstall helper")
def test_new_setup_uninstall_uses_bundled_helper_after_rollback(tmp_path, monkeypatch):
    root = tmp_path / "Commander"
    payload = tmp_path / "payload"
    root.mkdir()
    payload.mkdir()
    (root / installer.INSTALL_MARKER).write_text(json.dumps({"product":"SENTRA Desktop"}))
    (root / "sentra-update-helper.exe").write_bytes(b"older helper")
    (payload / "sentra-update-helper.exe").write_bytes(b"current helper")
    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    monkeypatch.setattr(installer, "payload_root", lambda: payload)
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    seen = []
    def launch(command, **kwargs):
        seen.append(command)
        assert Path(command[0]).read_bytes() == b"current helper"
        return SimpleNamespace(pid=1)
    monkeypatch.setattr(installer.subprocess, "Popen", launch)
    result = installer.uninstall(root, keep_config=True, state_dir=tmp_path / "state", unregister_system=False)
    assert result["cleanup_scheduled"] and len(seen) == 1
