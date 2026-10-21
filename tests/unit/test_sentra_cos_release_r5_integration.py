"""Round 5 physical staged SQLite transitions and signed-payload provenance."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_remote import staged_upgrade, update_helper
from sentra_mcp.services.authorization import AuthorizationService
from scripts.commander import seal_payload


def _db(root: Path) -> tuple[Path, Path]:
    state = root / "state"
    state.mkdir()
    path = state / "authority.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("PRAGMA user_version=1")
            conn.execute("CREATE TABLE grants (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO grants VALUES ('test', 'preserved')")
    return state, path


def _schema(db: Path) -> tuple[int, list]:
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0], conn.execute("SELECT value FROM grants").fetchall()


def _migrator(db):
    db.execute("ALTER TABLE grants ADD COLUMN revision INTEGER DEFAULT 2")


def _prepare(tmp_path, *, authorize=lambda *_: True, offline=lambda: True):
    state, database = _db(tmp_path)
    stage = tmp_path / "migration-stage"
    staged_upgrade.prepare_staged_migration(
        state, database, stage, installation_id="sentra-identity",
        owner_id="owner", operation_id="prepare-workitem",
        authorize=authorize, offline=offline, migrate=_migrator, target_schema=2,
    )
    return state, database, stage


def test_real_sqlite_migration_is_staged_then_committed_without_data_loss(tmp_path):
    state, database, stage = _prepare(tmp_path)
    assert _schema(database) == (1, [("preserved",)])
    staged_upgrade.commit_staged_migration(
        stage, state, database, installation_id="sentra-identity",
        owner_id="owner", operation_id="prepare-workitem",
        authorize=lambda *_: True, offline=lambda: True,
    )
    assert _schema(database) == (2, [("preserved",)])
    assert json.loads((stage / "upgrade-stage.json").read_text())["phase"] == "COMMITTED"
    with pytest.raises((ValueError, PermissionError)):
        staged_upgrade.commit_staged_migration(
            stage, state, database, installation_id="sentra-identity",
            owner_id="owner", operation_id="prepare-workitem",
            authorize=lambda *_: True, offline=lambda: True,
        )


def test_crash_between_db_renames_stays_recoverable_without_retry(tmp_path, monkeypatch):
    state, db, stage = _prepare(tmp_path)
    real_replace = staged_upgrade.os.replace
    def simulated_crash(source, destination):
        if Path(source).name == "migrated.sqlite" and Path(destination) == db:
            raise OSError("simulated abrupt crash after old DB parked")
        return real_replace(source, destination)
    monkeypatch.setattr(staged_upgrade.os, "replace", simulated_crash)
    with pytest.raises(OSError, match="simulated"):
        staged_upgrade.commit_staged_migration(
            stage, state, db, installation_id="sentra-identity",
            owner_id="owner", operation_id="prepare-workitem",
            authorize=lambda *_: True, offline=lambda: True,
        )
    assert not db.exists()
    assert (stage / "previous-live.sqlite").is_file()
    assert json.loads((stage / "upgrade-stage.json").read_text())["phase"] == "SWITCHING"
    with pytest.raises(PermissionError, match="denied"):
        staged_upgrade.recover_interrupted_migration(
            stage, state, db, installation_id="sentra-identity",
            owner_id="owner", operation_id="recovery",
            authorize=lambda *_: False, offline=lambda: True,
        )
    staged_upgrade.recover_interrupted_migration(
        stage, state, db, installation_id="sentra-identity",
        owner_id="owner", operation_id="recovery",
        authorize=lambda *_: True, offline=lambda: True,
    )
    assert _schema(db) == (1, [("preserved",)])
    assert json.loads((stage / "upgrade-stage.json").read_text())["phase"] == "RECOVERED"


def test_real_sqlite_authorization_service_revocation_denies_migration(tmp_path):
    state, db = _db(tmp_path)
    auth = AuthorizationService(tmp_path / "auth-service")
    owner = "owner"
    admission = lambda o, op, ident: auth.authorize(
        o, principal_type="user", principal_id=o,
        capability="release.migrate", scope_type="device",
        scope_id=ident, context={"interactive": True}, local_owner=False
    )["allowed"]
    with pytest.raises(PermissionError):
        staged_upgrade.prepare_staged_migration(
            state, db, tmp_path / "migration-stage", installation_id="sentra-identity",
            owner_id=owner, operation_id="prepare-workitem",
            authorize=admission, offline=lambda: True, migrate=_migrator,
            target_schema=2,
        )
    grant = auth.grant(owner, principal_type="user", principal_id=owner,
                       capability="release.migrate", scope_type="device",
                       scope_id="sentra-identity", conditions={"requires_interactive": True})
    staged_upgrade.prepare_staged_migration(
        state, db, tmp_path / "migration-stage", installation_id="sentra-identity",
        owner_id=owner, operation_id="prepare-workitem",
        authorize=admission, offline=lambda: True, migrate=_migrator,
        target_schema=2,
    )
    auth.revoke(grant["grant_id"], owner)
    with pytest.raises(PermissionError):
        staged_upgrade.commit_staged_migration(
            tmp_path / "migration-stage", state, db,
            installation_id="sentra-identity", owner_id=owner,
            operation_id="prepare-workitem", authorize=admission,
            offline=lambda: True,
        )
    assert _schema(db)[0] == 1


def test_migration_rejects_wal_sidecars_and_tamper(tmp_path):
    state, db, stage = _prepare(tmp_path)
    (stage / "migrated.sqlite").write_bytes(b"bad")
    with pytest.raises(ValueError, match="tampered"):
        staged_upgrade.commit_staged_migration(
            stage, state, db, installation_id="sentra-identity",
            owner_id="owner", operation_id="prepare-workitem",
            authorize=lambda *_: True, offline=lambda: True,
        )
    assert _schema(db)[0] == 1


def test_release_helper_uses_custom_state_dir_for_update_and_rollback(tmp_path, monkeypatch):
    install = tmp_path / "Commander"
    state = tmp_path / "custom-state"
    install.mkdir(); state.mkdir()
    (install / ".sentra-install.json").write_text(json.dumps({
        "product": "SENTRA Desktop", "installation_id": "owned-identity",
        "owned_files": ["sentra-desktop.exe"],
    }))
    (install / "sentra-desktop.exe").write_bytes(b"previous")
    (install / "user.txt").write_text("KEEP")
    exe = tmp_path / "Setup.exe"
    exe.write_bytes(b"inert")
    from sentra_remote import installer
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    def mock_setup(cmd, **_):
        (install / "sentra-desktop.exe").write_bytes(b"updated")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(update_helper.subprocess, "run", mock_setup)
    update_helper.apply_update(exe, install, parent_pid=0, version="0.2.0",
        manifest_url="", state_dir=state, restart_desktop=False,
        register_system=False)
    assert (state / "update-state.json").is_file()
    assert (install / "sentra-desktop.exe").read_bytes() == b"updated"
    # Use explicit state registration for rollback (no mutation of unrelated HOME).
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    update_helper.rollback_update(install, parent_pid=0, restart_desktop=False)
    assert (install / "sentra-desktop.exe").read_bytes() == b"previous"
    assert (install / "user.txt").read_text() == "KEEP"


def test_payload_signature_seal_requires_matching_current_sources(tmp_path, monkeypatch):
    from scripts.commander import build_windows
    dist = tmp_path / "dist"
    dist.mkdir()
    names = tuple(build_windows.PAYLOAD_NAMES)
    payloads = {}
    for name in names:
        binary = dist / name
        binary.write_bytes(("unsigned:" + name).encode())
        payloads[name] = {"sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                          "bytes": binary.stat().st_size}
    sources = {"test.py": "stable"}
    proof = dist / "build-provenance-payload.json"
    proof.write_text(json.dumps({
        "schema_version": 1, "phase": "payload",
        "sources": sources, "executables": payloads,
    }))
    monkeypatch.setattr(seal_payload, "_source_fingerprint", lambda: sources)
    monkeypatch.setattr(seal_payload, "verify_authenticode", lambda path, signer: None)
    for name in names:
        (dist / name).write_bytes(("signed:" + name).encode())
    result = seal_payload.seal_signed_payload(dist, "A" * 40)
    assert result["signed_seal"]["signer_thumbprint"] == "A" * 40
    assert result["executables"][names[0]]["sha256"] == hashlib.sha256((dist / names[0]).read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="already sealed"):
        seal_payload.seal_signed_payload(dist, "A" * 40)


def test_second_upgrade_retains_first_immutable_rollback_snapshot(tmp_path, monkeypatch):
    install = tmp_path / "Commander"
    state = tmp_path / "state"
    install.mkdir(); state.mkdir()
    (install / ".sentra-install.json").write_text(json.dumps({
        "product": "SENTRA Desktop", "installation_id": "owned-id",
        "owned_files": ["sentra-desktop.exe"],
    }))
    (install / "sentra-desktop.exe").write_bytes(b"v1")
    exe = tmp_path / "Setup.exe"; exe.write_bytes(b"inert")
    from sentra_remote import installer
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    versions = iter((b"v2", b"v3"))
    def run(_cmd, **_):
        (install / "sentra-desktop.exe").write_bytes(next(versions))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(update_helper.subprocess, "run", run)
    for version in ("2.0.0", "3.0.0"):
        update_helper.apply_update(exe, install, parent_pid=0, version=version,
            manifest_url="", state_dir=state, register_system=False,
            restart_desktop=False)
    root = tmp_path / "Rollback" / hashlib.sha256(b"owned-id").hexdigest()
    assert (root / "previous" / "sentra-desktop.exe").read_bytes() == b"v1"
    state_data = json.loads((state / "update-state.json").read_text())
    newest = Path(state_data["previous_backup"])
    assert newest.name.startswith("previous-")
    from sentra_remote.windows_paths import filesystem_path
    assert Path(filesystem_path(newest / "sentra-desktop.exe")).read_bytes() == b"v2"
    assert (install / "sentra-desktop.exe").read_bytes() == b"v3"
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    assert update_helper.rollback_update(install, parent_pid=0, restart_desktop=False) == 0
    assert (install / "sentra-desktop.exe").read_bytes() == b"v2"
    assert (root / "previous" / "sentra-desktop.exe").read_bytes() == b"v1"


def test_interrupted_setup_journal_blocks_restart_before_process_stop(tmp_path, monkeypatch):
    from sentra_remote.program_stage import stage_program_backup, mark_program_stage
    install = tmp_path / "Commander"; install.mkdir()
    state = tmp_path / "state"; state.mkdir()
    (install / ".sentra-install.json").write_text(json.dumps({
        "product": "SENTRA Desktop", "installation_id": "id",
        "owned_files": ["sentra-desktop.exe"],
    }))
    (install / "sentra-desktop.exe").write_bytes(b"old")
    stage_dir = tmp_path / "Rollback" / hashlib.sha256(b"id").hexdigest()
    _, journal = stage_program_backup(install, stage_dir, "id")
    mark_program_stage(journal, "APPLYING", "id")
    exe = tmp_path / "Setup.exe"; exe.write_bytes(b"inert")
    called = []
    monkeypatch.setattr(update_helper, "_wait_pid", lambda *_: called.append("wait"))
    with pytest.raises(PermissionError, match="uncertain"):
        update_helper.apply_update(exe, install, parent_pid=0, version="9.0.0",
            manifest_url="", state_dir=state, restart_desktop=False)
    assert not called
    assert (install / "sentra-desktop.exe").read_bytes() == b"old"


def test_failed_setup_journal_is_restored_without_replaying(tmp_path, monkeypatch):
    install = tmp_path / "Commander"; install.mkdir()
    state = tmp_path / "state"; state.mkdir()
    (install / ".sentra-install.json").write_text(json.dumps({
        "product": "SENTRA Desktop", "installation_id": "id",
        "owned_files": ["sentra-desktop.exe"],
    }))
    (install / "sentra-desktop.exe").write_bytes(b"old")
    exe = tmp_path / "Setup.exe"; exe.write_bytes(b"inert")
    from sentra_remote import installer
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *_: None)
    monkeypatch.setattr(update_helper.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=2))
    with pytest.raises(RuntimeError, match="setup exited"):
        update_helper.apply_update(exe, install, parent_pid=0, version="2.0.0",
            manifest_url="", state_dir=state, restart_desktop=False)
    assert (install / "sentra-desktop.exe").read_bytes() == b"old"
    namespace = tmp_path / "Rollback" / hashlib.sha256(b"id").hexdigest()
    journals = list(namespace.glob("txn-*.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text())["phase"] == "RESTORED"
