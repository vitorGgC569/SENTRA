"""Offline SQLite pre-upgrade snapshot and crash recovery gates.

Does not migrate the live central ControlPlane, does not read secrets, and
cannot authorize itself. The coordinator must supply a durable owner-auth
admission and prove that every database user has stopped.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Callable

MAX_DB_BYTES = 8 * 1024 * 1024 * 1024


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _admit(owner: str, operation: str, identity: str,
           authorize: Callable[[str, str, str], bool] | None,
           offline: Callable[[], bool] | None) -> None:
    # owner_id and operation_id are only routing keys; authority remains host.
    if not owner or not operation or not identity or authorize is None or offline is None:
        raise PermissionError("durable owner-auth and offline process gate required")
    if offline() is not True or authorize(owner, operation, identity) is not True:
        raise PermissionError("migration denied: owner or offline process proof missing")


def _check(root: Path, database: Path) -> tuple[Path, Path]:
    root = root.resolve(strict=True)
    database = database.absolute()
    if (not database.is_relative_to(root) or database.resolve() != database
        or database.is_symlink() or not database.is_file()):
        raise ValueError("database outside owned state root or missing")
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise PermissionError("SQLite sidecar exists; stop/checkpoint all writers before upgrade")
    if database.stat().st_size > MAX_DB_BYTES or database.stat().st_size == 0:
        raise ValueError("SQLite database violates size bound")
    return root, database


def _integrity(path: Path) -> int:
    # URI read-only, no schema upgrade and no journal mutation.
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("SQLite quick_check failed")
        return int(db.execute("PRAGMA user_version").fetchone()[0])


def prepare_sqlite_snapshot(
    state_root: Path, database: Path, stage_root: Path, *,
    installation_id: str, owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
) -> Path:
    """Offline copy to isolated stage; original database is NEVER changed."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root, source = _check(state_root, database)
    stage = stage_root.absolute()
    if (stage.exists() or stage.is_relative_to(root) or root.is_relative_to(stage)
        or stage.parent.resolve() != root.parent.resolve()):
        raise ValueError("snapshot stage must be new, private, and a sibling of live state root")
    version = _integrity(source)
    source_digest = _hash(source)
    stage.mkdir(parents=True, exist_ok=False)
    temp = stage / "control.sqlite.tmp"
    try:
        uri = source.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as src:
            with closing(sqlite3.connect(temp)) as dst:
                src.backup(dst, pages=64, sleep=0.01)
        clean_version = _integrity(temp)
        if clean_version != version or offline() is not True:
            raise PermissionError("database changed or offline gate revoked")
        target = stage / "control.sqlite"
        os.replace(temp, target)
        snapshot_digest = _hash(target)
        journal = {
            "schema": 1, "status": "prepared",
            "install_binding": hashlib.sha256(installation_id.encode()).hexdigest(),
            "state_binding": hashlib.sha256(str(root).encode()).hexdigest(),
            "database_name": source.name,
            "user_version": version,
            "source_sha256": source_digest,
            "snapshot_sha256": snapshot_digest,
            "operation_id": operation_id,
        }
        # No account/username, tokens or database contents included in journal.
        journal_file = stage / "journal.json"
        with journal_file.open("x", encoding="utf-8") as out:
            json.dump(journal, out, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        return stage
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def verify_sqlite_snapshot(
    stage_root: Path, *, installation_id: str, state_root: Path
) -> dict:
    stage = stage_root.resolve(strict=True)
    data = json.loads((stage / "journal.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("status") != "prepared":
        raise ValueError("invalid migration journal")
    if (data.get("install_binding") != hashlib.sha256(installation_id.encode()).hexdigest()
        or data.get("state_binding") != hashlib.sha256(str(state_root.resolve()).encode()).hexdigest()):
        raise PermissionError("migration snapshot installation/state mismatch")
    db = stage / "control.sqlite"
    if db.is_symlink() or not db.is_file() or db.stat().st_size > MAX_DB_BYTES or _hash(db) != data.get("snapshot_sha256"):
        raise ValueError("migration snapshot hash mismatch")
    if _integrity(db) != data.get("user_version"):
        raise ValueError("migration snapshot schema mismatch")
    return data


def restore_sqlite_snapshot(
    stage_root: Path, state_root: Path, database: Path, *,
    installation_id: str, owner_id: str, operation_id: str,
    expected_current_sha256: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
) -> None:
    """Offline rollback with compare-and-swap; never silently erase newer data."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root, target = _check(state_root, database)
    data = verify_sqlite_snapshot(stage_root, installation_id=installation_id, state_root=root)
    if data.get("database_name") != target.name or _hash(target) != expected_current_sha256:
        raise PermissionError("database changed; refusing unsafe rollback")
    # Only an offline, owner-auth host can deliberately restore a proven snapshot.
    stage = stage_root.resolve(strict=True)
    temp = target.with_name(target.name + ".restore-" + uuid.uuid4().hex)
    try:
        with closing(sqlite3.connect((stage / "control.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(temp)) as dst:
                src.backup(dst)
        if _hash(temp) != data["snapshot_sha256"] or offline() is not True:
            raise PermissionError("restore snapshot changed or offline gate revoked")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
