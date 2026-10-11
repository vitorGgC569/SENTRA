"""R6 VM physical-effect refusal, SQLite pre-rename crash and release seals."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scripts.commander import isolated_vm_smoke
from scripts.commander.release_publish_gate import check_publication
from sentra_remote import staged_upgrade


def _files(root):
    state = root / "state"
    state.mkdir()
    db = state / "control.sqlite"
    with closing(sqlite3.connect(db)) as conn:
        with conn:
            conn.execute("PRAGMA user_version=1")
            conn.execute("CREATE TABLE grant (id TEXT)")
            conn.execute("INSERT INTO grant VALUES ('retained')")
    return state, db


def test_power_loss_before_first_database_rename_recovers_without_replaying(tmp_path, monkeypatch):
    state, db = _files(tmp_path)
    stage = tmp_path / "migration-stage"
    staged_upgrade.prepare_staged_migration(
        state, db, stage, installation_id="device-owner", owner_id="owner",
        operation_id="op-committed-intent", offline=lambda: True,
        authorize=lambda *_: True,
        migrate=lambda conn: conn.execute("ALTER TABLE grant ADD COLUMN seq INTEGER DEFAULT 2"),
        target_schema=2)
    real_replace = staged_upgrade.os.replace
    calls = []
    def crashed(src, dst):
        if Path(src) == db and Path(dst).name == "previous-live.sqlite":
            calls.append("pre-rename-crash")
            raise OSError("synthetic abrupt power loss")
        return real_replace(src, dst)
    monkeypatch.setattr(staged_upgrade.os, "replace", crashed)
    with pytest.raises(OSError, match="power loss"):
        staged_upgrade.commit_staged_migration(
            stage, state, db, installation_id="device-owner",
            owner_id="owner", operation_id="op-committed-intent",
            offline=lambda: True, authorize=lambda *_: True)
    assert calls == ["pre-rename-crash"]
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (1,)
        assert conn.execute("SELECT id FROM grant").fetchone() == ("retained",)
    monkeypatch.setattr(staged_upgrade.os, "replace", real_replace)
    assert staged_upgrade.recover_interrupted_migration(
        stage, state, db, installation_id="device-owner",
        owner_id="owner", operation_id="host-recovery-operation",
        offline=lambda: True, authorize=lambda *_: True) == "RECOVERED"
    assert json.loads((stage / "upgrade-stage.json").read_text())["phase"] == "RECOVERED"
    with pytest.raises(PermissionError):
        staged_upgrade.commit_staged_migration(
            stage, state, db, installation_id="device-owner",
            owner_id="owner", operation_id="op-committed-intent",
            offline=lambda: True, authorize=lambda *_: True)


def test_vm_smoke_blocks_before_any_setup_or_msiexec_without_authorization(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(isolated_vm_smoke.subprocess, "run",
                        lambda *args, **kwargs: commands.append(args) or None)
    with pytest.raises(PermissionError, match="DRY RUN"):
        isolated_vm_smoke.run_vm_smoke(
            tmp_path / "release", tmp_path / "tunnel.zip",
            version="1.0.0", trusted_signer="A" * 40,
            execute=False, acknowledged=False)
    with pytest.raises(PermissionError, match="DRY RUN"):
        isolated_vm_smoke._msi_vm_roundtrip(
            tmp_path / "fake.msi", tmp_path / "Commander",
            execute=False, acknowledged=False, trusted_signer="A" * 40)
    assert not commands


def test_vm_smoke_denies_non_vm_without_execution(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(isolated_vm_smoke, "vm_evidence", lambda: False)
    monkeypatch.setattr(isolated_vm_smoke.subprocess, "run",
                        lambda *args, **kwargs: calls.append(args) or None)
    with pytest.raises(PermissionError, match="disposable Windows VM"):
        isolated_vm_smoke.run_vm_smoke(
            tmp_path / "release", tmp_path / "tunnel.zip",
            version="1.0.0", trusted_signer="A" * 40,
            execute=True, acknowledged=True)
    assert calls == []


def test_publication_denies_vm_report_bound_to_wrong_msi(tmp_path):
    from scripts.commander.release_publish_gate import REQUIRED_PROOFS
    release = tmp_path / "release"
    release.mkdir()
    (release / "SENTRA-Setup-1.2.3.exe").write_bytes(b"setup")
    (release / "SENTRA-Desktop-1.2.3-x64.msi").write_bytes(b"msi")
    (release / "release-manifest.json").write_text(
        json.dumps({"version": "1.2.3", "setup": "SENTRA-Setup-1.2.3.exe"}))
    qa = tmp_path / "qa.json"
    qa.write_text(json.dumps({
        "schema": 1, "version": "1.2.3",
        "setup_sha256": hashlib.sha256(b"setup").hexdigest(),
        "msi_sha256": hashlib.sha256(b"another MSI").hexdigest(),
        **{key: True for key in REQUIRED_PROOFS},
    }))
    with pytest.raises(PermissionError, match="different MSI"):
        check_publication(release, qa,
            expected_sha256=hashlib.sha256(qa.read_bytes()).hexdigest(),
            version="1.2.3")


def test_repair_owner_auth_does_not_allow_same_identity_marker_swap(tmp_path):
    from sentra_remote.install_doctor import request_owner_repair
    root = tmp_path / "Commander"
    root.mkdir()
    marker = root / ".sentra-install.json"
    marker.write_text(json.dumps({
        "product": "SENTRA Desktop", "installation_id": "stable-id",
        "owned_files": ["sentra-canvas.exe"],
    }))
    dispatched = []
    def change_owned_list(owner, op, identity):
        record = json.loads(marker.read_text())
        assert identity == "stable-id"
        record["owned_files"] = ["sentra-cli.exe"]
        marker.write_text(json.dumps(record))
        return True
    with pytest.raises(PermissionError, match="installation changed"):
        request_owner_repair(root, owner_id="host-owner", operation_id="durable-id",
            authorize=change_owned_list,
            dispatch=lambda *_: dispatched.append(True))
    assert dispatched == []
