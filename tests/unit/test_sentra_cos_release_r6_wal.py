"""Crash-persisted SQLite WAL source -> private read-only release staging."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from sentra_remote.wal_checkpoint import (
    snapshot_offline_wal, verify_offline_wal_snapshot,
)


def _crashed_wal(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    db = state / "control.sqlite"
    script = (
        "import os,sqlite3,sys\n"
        "db=sqlite3.connect(sys.argv[1]); "
        "db.execute('PRAGMA journal_mode=WAL');"
        "db.execute('PRAGMA wal_autocheckpoint=0');"
        "db.execute('CREATE TABLE receipts(id TEXT, phase TEXT)');"
        "db.execute('INSERT INTO receipts VALUES (?, ?)',('one','UNCERTAIN'));"
        "db.commit();os._exit(0)\n"
    )
    cp = subprocess.run([sys.executable, "-c", script, str(db)], capture_output=True, timeout=12)
    assert cp.returncode == 0, cp.stderr
    wal = Path(str(db) + "-wal")
    assert wal.is_file() and wal.stat().st_size > 0
    return state, db, wal


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_crashed_writer_wal_recovers_in_private_clone_without_mutating_live(tmp_path):
    state, db, wal = _crashed_wal(tmp_path)
    expected = (_sha(db), _sha(wal))
    target = tmp_path / "wal-stage"
    snapshot = snapshot_offline_wal(
        state, db, target, installation_id="install-1",
        owner_id="verified-host-owner", operation_id="durable-op",
        authorize=lambda *_: True, offline=lambda: True,
    )
    with closing(sqlite3.connect(snapshot)) as conn:
        assert conn.execute("SELECT id,phase FROM receipts").fetchone() == ("one", "UNCERTAIN")
    assert expected == (_sha(db), _sha(wal))
    assert verify_offline_wal_snapshot(target, installation_id="install-1", state_root=state)["status"] == "STAGED_WAL_COPY"
    assert not (target / "source-copy").exists()
    with pytest.raises(PermissionError, match="mismatch"):
        verify_offline_wal_snapshot(target, installation_id="another", state_root=state)


def test_wal_needs_host_owner_and_true_offline_admission(tmp_path):
    state, db, wal = _crashed_wal(tmp_path)
    for auth, offline in ((None, lambda: True), (lambda *_: True, lambda: False)):
        with pytest.raises(PermissionError):
            snapshot_offline_wal(state, db, tmp_path / "wal-stage",
                installation_id="install-1", owner_id="owner", operation_id="operation",
                authorize=auth, offline=offline)
    assert not (tmp_path / "wal-stage").exists()


def test_crashed_wal_tampered_stage_never_promoted(tmp_path):
    state, db, wal = _crashed_wal(tmp_path)
    stage = tmp_path / "wal-stage"
    snapshot = snapshot_offline_wal(state, db, stage,
        installation_id="install-1", owner_id="owner", operation_id="operation",
        authorize=lambda *_: True, offline=lambda: True)
    snapshot.write_bytes(b"tampered")
    with pytest.raises(PermissionError, match="mismatch"):
        verify_offline_wal_snapshot(stage, installation_id="install-1", state_root=state)


def test_wal_is_not_allowed_to_replace_program_upgrade_migration_gate(tmp_path):
    from sentra_remote.release_migration import prepare_sqlite_snapshot
    state, db, wal = _crashed_wal(tmp_path)
    with pytest.raises(PermissionError, match="sidecar"):
        prepare_sqlite_snapshot(
            state, db, tmp_path / "normal-stage", installation_id="install-1",
            owner_id="owner", operation_id="operation",
            authorize=lambda *_: True, offline=lambda: True)
    assert not (tmp_path / "normal-stage").exists()
