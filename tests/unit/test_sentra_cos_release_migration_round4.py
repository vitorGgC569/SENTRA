"""Real SQLite files for crash-stage and owner-auth migration gates."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from sentra_remote.release_migration import (
    prepare_sqlite_snapshot, restore_sqlite_snapshot, verify_sqlite_snapshot
)


@contextmanager
def _opened(path: Path):
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            yield conn


def _fixture(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    db = state / "control.sqlite"
    with _opened(db) as conn:
        conn.execute("PRAGMA user_version=7")
        conn.execute("CREATE TABLE operation (id TEXT PRIMARY KEY, receipt TEXT)")
        conn.execute("INSERT INTO operation VALUES ('op-1', 'committed')")
    return state, db, tmp_path / "staged"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare(state, db, stage, *, authorize=None, offline=None, identity="install-A"):
    return prepare_sqlite_snapshot(
        state, db, stage, installation_id=identity,
        owner_id="local-verified-owner", operation_id="op-preflight",
        authorize=authorize, offline=offline,
    )


def test_snapshot_requires_host_authorization_and_offline_machine(tmp_path):
    state, db, stage = _fixture(tmp_path)
    original = _digest(db)
    with pytest.raises(PermissionError):
        _prepare(state, db, stage, authorize=None, offline=lambda: True)
    with pytest.raises(PermissionError):
        _prepare(state, db, stage, authorize=lambda *_: True, offline=lambda: False)
    assert not stage.exists()
    assert _digest(db) == original


def test_real_sqlite_snapshot_and_recovery_binding(tmp_path):
    state, db, stage = _fixture(tmp_path)
    original = _digest(db)
    _prepare(state, db, stage, authorize=lambda *_: True, offline=lambda: True)
    journal = verify_sqlite_snapshot(stage, installation_id="install-A", state_root=state)
    assert journal["user_version"] == 7
    with _opened(stage / "control.sqlite") as conn:
        assert conn.execute("SELECT receipt FROM operation WHERE id='op-1'").fetchone() == ("committed",)
    assert _digest(db) == original
    with pytest.raises(PermissionError, match="mismatch"):
        verify_sqlite_snapshot(stage, installation_id="install-B", state_root=state)
    assert "local-verified-owner" not in json.dumps(journal)


def test_snapshot_corruption_and_incomplete_crash_stage_deny(tmp_path):
    state, db, stage = _fixture(tmp_path)
    _prepare(state, db, stage, authorize=lambda *_: True, offline=lambda: True)
    (stage / "control.sqlite").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_sqlite_snapshot(stage, installation_id="install-A", state_root=state)
    (stage / "journal.json").unlink()
    with pytest.raises(FileNotFoundError):
        verify_sqlite_snapshot(stage, installation_id="install-A", state_root=state)


def test_rollback_preserves_changed_live_db_on_sha_mismatch(tmp_path):
    state, db, stage = _fixture(tmp_path)
    _prepare(state, db, stage, authorize=lambda *_: True, offline=lambda: True)
    with _opened(db) as conn:
        conn.execute("UPDATE operation SET receipt='new-user-write'")
    changed = _digest(db)
    with pytest.raises(PermissionError, match="database changed"):
        restore_sqlite_snapshot(stage, state, db, installation_id="install-A",
            owner_id="owner", operation_id="rollback",
            expected_current_sha256="0" * 64,
            authorize=lambda *_: True, offline=lambda: True)
    assert _digest(db) == changed


def test_explicit_offline_owner_rollback_to_verified_snapshot(tmp_path):
    state, db, stage = _fixture(tmp_path)
    _prepare(state, db, stage, authorize=lambda *_: True, offline=lambda: True)
    with _opened(db) as conn:
        conn.execute("UPDATE operation SET receipt='unwanted-upgrade'")
    changed = _digest(db)
    restore_sqlite_snapshot(stage, state, db, installation_id="install-A",
        owner_id="verified-owner", operation_id="rollback-once",
        expected_current_sha256=changed,
        authorize=lambda owner, operation, identity: (owner, operation, identity) ==
            ("verified-owner", "rollback-once", "install-A"),
        offline=lambda: True)
    with _opened(db) as conn:
        assert conn.execute("SELECT receipt FROM operation").fetchone() == ("committed",)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7


def test_snapshot_cannot_target_database_outside_state_root(tmp_path):
    state, db, stage = _fixture(tmp_path)
    foreign = tmp_path / "foreign.sqlite"
    foreign.write_bytes(db.read_bytes())
    with pytest.raises(ValueError, match="outside"):
        _prepare(state, foreign, stage, authorize=lambda *_: True, offline=lambda: True)


def test_migration_denies_sqlite_wal_sidecar_before_owner_stage(tmp_path):
    state, db, stage = _fixture(tmp_path)
    wal = Path(str(db) + "-wal")
    wal.write_bytes(b"possibly-uncheckpointed")
    with pytest.raises(PermissionError, match="sidecar"):
        _prepare(state, db, stage, authorize=lambda *_: True, offline=lambda: True)
    assert not stage.exists()


def test_physical_updater_denies_unstaged_db_before_stopping_processes(tmp_path, monkeypatch):
    from sentra_remote import update_helper
    state, db, stage = _fixture(tmp_path)
    install = tmp_path / "Commander"
    install.mkdir()
    marker = install / update_helper.INSTALL_MARKER
    marker.write_text(json.dumps({
        "product": "SENTRA Desktop", "installation_id": "known-identity",
        "owned_files": ["sentra-cli.exe"],
    }))
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"synthetic-inert")
    stopped = []
    monkeypatch.setattr(update_helper, "_wait_pid", lambda *_: stopped.append("wait"))
    with pytest.raises(PermissionError, match="durable owner-auth"):
        update_helper.apply_update(installer, install, parent_pid=0,
            version="1.0.1", manifest_url="", state_dir=state,
            register_system=False, restart_desktop=False)
    assert not stopped
    assert marker.is_file()
    with _opened(db) as conn:
        assert conn.execute("SELECT receipt FROM operation").fetchone() == ("committed",)
