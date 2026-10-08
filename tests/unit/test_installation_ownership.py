import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from sentra_remote import installer, update_helper
from sentra_remote.installation_lock import installation_lock

def test_populated_unowned_install_rejected_before_copy(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir(); (root / "user.txt").write_text("KEEP")
    copied = []
    monkeypatch.setattr(installer, "_copy_product_files", lambda *_: copied.append(True))
    with pytest.raises(ValueError, match="empty install directory"):
        installer.install(install_dir=root, state_dir=tmp_path / "state", launch=False)
    assert not copied and (root / "user.txt").read_text() == "KEEP"
    assert not (root / installer.INSTALL_MARKER).exists()

def test_cleanup_preserves_unowned_files_and_nested_install(tmp_path, monkeypatch):
    root = tmp_path / "Commander"; root.mkdir()
    (root / "owned.exe").write_bytes(b"product")
    (root / "user.txt").write_text("KEEP")
    nested = root / "nested"; nested.mkdir()
    (nested / installer.INSTALL_MARKER).write_text(json.dumps({"product": "SENTRA Desktop"}))
    (nested / "owned.exe").write_bytes(b"OTHER")
    installer._write_install_marker(root, ["owned.exe", "nested/owned.exe"])
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    assert update_helper.cleanup_install(root, parent_pid=0) == 0
    assert not (root / "owned.exe").exists()
    assert (root / "user.txt").read_text() == "KEEP"
    assert (nested / "owned.exe").read_bytes() == b"OTHER"

def test_uninstall_preserves_unproven_shared_state(tmp_path, monkeypatch):
    root = tmp_path / "Commander"; root.mkdir()
    installer._write_install_marker(root, ["owned.exe"])
    state = tmp_path / "shared-state"; state.mkdir()
    (state / "history").write_bytes(b"OTHER INSTALL HISTORY")
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    result = installer.uninstall(root, state_dir=state, keep_config=False, unregister_system=False)
    assert result["kept_config"] and (state / "history").read_bytes() == b"OTHER INSTALL HISTORY"

def test_installation_lock_excludes_live_owner(tmp_path):
    root = tmp_path / "Commander"
    with installation_lock(root):
        with pytest.raises(RuntimeError, match="another installation"):
            with installation_lock(root): pass
    with installation_lock(root): pass

def test_owned_manifest_and_cleanup_cover_deep_paths(tmp_path, monkeypatch):
    root = tmp_path / "Commander"; root.mkdir()
    relative = Path("web-models/resources/runtime/app/node_modules") / ("a" * 60) / ("b" * 60) / ("c" * 60) / "module.js"
    file = Path(installer._filesystem_path(root / relative))
    file.parent.mkdir(parents=True); file.write_bytes(b"payload")
    owned = installer._owned_tree_files(root / "web-models", "web-models")
    assert relative.as_posix() in owned
    installer._write_install_marker(root, owned)
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    update_helper.cleanup_install(root, parent_pid=0)
    assert not root.exists()

def test_sibling_updates_keep_separate_backups_and_refuse_foreign_identity(tmp_path, monkeypatch):
    state = tmp_path / "state"; state.mkdir()
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    setup = tmp_path / "Setup.exe"; setup.write_bytes(b"fixture")
    roots = [tmp_path / "First", tmp_path / "Second"]
    for i, root in enumerate(roots):
        root.mkdir()
        (root / installer.INSTALL_MARKER).write_text(json.dumps({"product":"SENTRA Desktop", "installation_id":str(i)}))
        (root / "old.txt").write_text(str(i))
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    def run(command, **kwargs):
        root = Path(command[command.index("--install-dir") + 1])
        (root / "sentra-desktop.exe").write_bytes(b"new")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(update_helper.subprocess, "run", run)
    for root in roots:
        update_helper.apply_update(setup, root, parent_pid=0, version="new", manifest_url="", restart_desktop=False)
    first_backup = tmp_path / "Rollback" / hashlib.sha256(b"0").hexdigest() / "previous"
    second_backup = tmp_path / "Rollback" / hashlib.sha256(b"1").hexdigest() / "previous"
    assert (first_backup / "old.txt").read_text() == "0"
    assert (second_backup / "old.txt").read_text() == "1"
    # Even a corrupted marker inside the correctly namespaced backup is refused.
    (state / "update-state.json").write_text(json.dumps({"install_dir":str(roots[0]),"previous_backup":str(first_backup)}))
    (first_backup / installer.INSTALL_MARKER).write_text((second_backup / installer.INSTALL_MARKER).read_text())
    with pytest.raises(ValueError, match="another installation identity"):
        update_helper.rollback_update(roots[0], parent_pid=0, restart_desktop=False)
    assert (roots[0] / "old.txt").read_text() == "0"

def test_rollback_keeps_new_user_files_and_removes_owned_new_release(tmp_path, monkeypatch):
    root = tmp_path / "Commander"; root.mkdir()
    backup = tmp_path / "Rollback" / hashlib.sha256(b"identity").hexdigest() / "previous"
    backup.mkdir(parents=True)
    for folder, owned in ((root, ["new.exe"]), (backup, ["old.exe"])):
        (folder / installer.INSTALL_MARKER).write_text(json.dumps({"product":"SENTRA Desktop", "installation_id":"identity", "owned_files":owned}))
    (root / "new.exe").write_bytes(b"NEW")
    (backup / "old.exe").write_bytes(b"OLD")
    (root / "user-added.txt").write_text("KEEP AFTER ROLLBACK")
    state = tmp_path / "state"; state.mkdir()
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    (state / "update-state.json").write_text(json.dumps({"install_dir":str(root),"previous_backup":str(backup)}))
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    update_helper.rollback_update(root, parent_pid=0, restart_desktop=False)
    assert not (root / "new.exe").exists()
    assert (root / "old.exe").read_bytes() == b"OLD"
    assert (root / "user-added.txt").read_text() == "KEEP AFTER ROLLBACK"

def test_failed_rollback_rename_does_not_delete_original(tmp_path, monkeypatch):
    root = tmp_path / "Commander"; root.mkdir()
    backup = tmp_path / "Rollback" / hashlib.sha256(b"identity").hexdigest() / "previous"
    backup.mkdir(parents=True)
    for folder in (root, backup):
        (folder / installer.INSTALL_MARKER).write_text(json.dumps({"product":"SENTRA Desktop", "installation_id":"identity"}))
    (root / "user.txt").write_text("ORIGINAL SAFE")
    state = tmp_path / "state"; state.mkdir()
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    (state / "update-state.json").write_text(json.dumps({"install_dir":str(root),"previous_backup":str(backup)}))
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    def denied(*_): raise PermissionError("rollback namespace is read-only")
    monkeypatch.setattr(update_helper.os, "rename", denied)
    with pytest.raises(PermissionError):
        update_helper.rollback_update(root, parent_pid=0, restart_desktop=False)
    assert (root / "user.txt").read_text() == "ORIGINAL SAFE"
    assert (root / installer.INSTALL_MARKER).is_file()

def test_first_copy_interruption_keeps_recoverable_ownership(tmp_path, monkeypatch):
    root = tmp_path / "Commander"
    state = tmp_path / "state"
    def interrupted(path):
        (path / "sentra-cli.exe").write_bytes(b"partial")
        raise OSError("disk full")
    monkeypatch.setattr(installer, "_copy_product_files", interrupted)
    with pytest.raises(OSError, match="disk full"):
        installer.install(install_dir=root, state_dir=state, launch=False)
    identity = installer._validate_sentra_install(root)["installation_id"]
    # A second attempt reaches the component-copy phase, rather than rejecting
    # its own partial destination as a foreign populated directory.
    stopped=[]
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda path:stopped.append(path))
    with pytest.raises(OSError, match="disk full"):
        installer.install(install_dir=root, state_dir=state, launch=False)
    assert stopped == [root.resolve()]
    assert installer._validate_sentra_install(root)["installation_id"] == identity
