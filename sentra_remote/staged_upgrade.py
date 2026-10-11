"""Owner-authorized offline SQLite schema migration with crash-safe recovery.

Staging and commit occur on one filesystem. No service stops, Setup execution,
secret inspection or model-facing grants live here. The central host supplies
a single-use owner/Operation admission, offline proof and reviewed migrator.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Any

from .release_migration import (
    _admit, _check, _hash, _integrity,
    prepare_sqlite_snapshot, verify_sqlite_snapshot,
)

JOURNAL = "upgrade-stage.json"
MIGRATED = "migrated.sqlite"
OLD_LIVE = "previous-live.sqlite"


def _journal_path(stage: Path) -> Path:
    return stage / JOURNAL


def _write_journal(stage: Path, record: dict[str, Any]) -> None:
    target = _journal_path(stage)
    tmp = stage / (JOURNAL + ".tmp")
    # A leftover temp represents an interrupted journal write: never clobber it.
    with tmp.open("x", encoding="utf-8") as out:
        json.dump(record, out, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, target)


def _load(stage: Path, identity: str, state_root: Path, database: Path) -> dict[str, Any]:
    stage = stage.resolve(strict=True)
    root, db = _check_state_for_recovery(state_root, database)
    base = verify_sqlite_snapshot(stage, installation_id=identity, state_root=root)
    journal_file = _journal_path(stage)
    if not journal_file.is_file() or journal_file.is_symlink() or journal_file.stat().st_size > 8192:
        raise ValueError("staged upgrade journal missing")
    record = json.loads(journal_file.read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("schema") != 1
        or record.get("source_sha256") != base["source_sha256"]
        or record.get("database_name") != db.name
        or record.get("operation_id") != base["operation_id"]
        or record.get("phase") not in {"STAGED", "SWITCHING", "COMMITTED", "RECOVERED"}):
        raise ValueError("stage binding/phase mismatch")
    upgraded = stage / MIGRATED
    if upgraded.is_symlink() or not upgraded.is_file() or _hash(upgraded) != record.get("migrated_sha256"):
        raise ValueError("migrated DB tampered or missing")
    if _integrity(upgraded) != record.get("target_schema"):
        raise ValueError("target SQLite schema does not match stage")
    return record


def _check_state_for_recovery(root: Path, db: Path) -> tuple[Path, Path]:
    root = Path(root).resolve(strict=True)
    db = Path(db).absolute()
    if db.is_symlink() or db.resolve() != db or not db.is_relative_to(root):
        raise ValueError("unowned SQLite path")
    # A missing DB is allowed ONLY for crash recovery, never for admission.
    if any(Path(str(db) + ext).exists() for ext in ("-wal", "-shm", "-journal")):
        raise PermissionError("SQLite sidecars require offline checkpoint")
    return root, db


def prepare_staged_migration(
    state_root: Path, database: Path, stage_dir: Path, *,
    installation_id: str, owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
    migrate: Callable[[sqlite3.Connection], None] | None,
    target_schema: int,
) -> Path:
    """Migration callback executes ONLY on a standalone stage DB."""
    if migrate is None or not callable(migrate) or not 0 < target_schema < 2**31:
        raise ValueError("reviewed offline SQLite migrator and target schema required")
    stage = prepare_sqlite_snapshot(
        state_root, database, stage_dir, installation_id=installation_id,
        owner_id=owner_id, operation_id=operation_id,
        authorize=authorize, offline=offline,
    )
    record = verify_sqlite_snapshot(stage, installation_id=installation_id, state_root=state_root)
    if record["user_version"] >= target_schema:
        raise ValueError("target schema must increase monotonically")
    original = stage / "control.sqlite"
    migrated = stage / MIGRATED
    with original.open("rb") as source, migrated.open("xb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    with closing(sqlite3.connect(migrated, timeout=1)) as db:
        with db:
            migrate(db)
            db.execute(f"PRAGMA user_version={target_schema}")
    if _integrity(migrated) != target_schema or offline is None or offline() is not True:
        raise PermissionError("staged migration integrity or offline gate failed")
    _write_journal(stage, {
        "schema": 1, "phase": "STAGED",
        "database_name": Path(database).name,
        "source_sha256": record["source_sha256"],
        "migrated_sha256": _hash(migrated),
        "target_schema": target_schema,
        "operation_id": operation_id,
    })
    return stage


def commit_staged_migration(
    stage_dir: Path, state_root: Path, database: Path, *,
    installation_id: str, owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
) -> None:
    """No silent repeat after unknown commit: exact phase and CAS required."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root, db = _check(state_root, database)
    raw_stage = Path(stage_dir).absolute()
    if raw_stage.is_symlink() or raw_stage.parent.resolve() != root.parent.resolve():
        raise PermissionError("stage must be a private sibling of state root")
    stage = raw_stage.resolve(strict=True)
    if stage.stat().st_dev != db.stat().st_dev:
        raise PermissionError("staged switch requires same filesystem")
    record = _load(stage, installation_id, root, db)
    if record["phase"] != "STAGED" or record["operation_id"] != operation_id:
        raise PermissionError("staged operation already consumed or mismatched")
    if (stage / OLD_LIVE).exists():
        raise PermissionError("previous live DB exists; recovery required")
    if _hash(db) != record["source_sha256"]:
        raise PermissionError("live SQLite changed after snapshot")
    # Durable journal before the first irreversible rename.
    record["phase"] = "SWITCHING"
    _write_journal(stage, record)
    # Same-volume old DB is held; crash between renames leaves it recoverable.
    old = stage / OLD_LIVE
    os.replace(db, old)
    os.replace(stage / MIGRATED, db)
    if _integrity(db) != record["target_schema"]:
        raise RuntimeError("migrated live SQLite needs manual recovery")
    record["phase"] = "COMMITTED"
    _write_journal(stage, record)


def recover_interrupted_migration(
    stage_dir: Path, state_root: Path, database: Path, *,
    installation_id: str, owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
) -> str:
    """Explicit owner-authorized compensation. No auto-retry of unknown effect."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root, db = _check_state_for_recovery(state_root, database)
    raw_stage = Path(stage_dir).absolute()
    if raw_stage.is_symlink() or raw_stage.parent.resolve() != root.parent.resolve():
        raise PermissionError("recovery stage root mismatch")
    stage = raw_stage.resolve(strict=True)
    if _journal_path(stage).is_symlink() or _journal_path(stage).stat().st_size > 8192:
        raise PermissionError("unsafe recovery journal")
    record = json.loads(_journal_path(stage).read_text(encoding="utf-8"))
    if record.get("phase") not in {"SWITCHING", "COMMITTED"}:
        raise PermissionError("no interrupted upgrade eligible for recovery")
    # Validate the original journal/snapshot; the migrated file may already
    # have moved to the live path, so don't use _load here.
    base = verify_sqlite_snapshot(stage, installation_id=installation_id, state_root=root)
    if base["operation_id"] != record.get("operation_id") or base["source_sha256"] != record.get("source_sha256"):
        raise PermissionError("upgrade journal does not belong to this operation")
    old = stage / OLD_LIVE
    if not old.exists() and record["phase"] == "SWITCHING":
        # Power loss after the durable switching journal but BEFORE the first
        # rename: original live bytes remain intact and no effect occurred.
        upgraded = stage / MIGRATED
        if (not db.is_file() or _hash(db) != base["source_sha256"] or
                not upgraded.is_file() or upgraded.is_symlink() or
                _hash(upgraded) != record.get("migrated_sha256")):
            raise PermissionError("ambiguous pre-rename crash; manual review required")
        record["phase"] = "RECOVERED"
        _write_journal(stage, record)
        return "RECOVERED"
    if old.is_symlink() or not old.is_file() or _hash(old) != base["source_sha256"]:
        raise PermissionError("previous-live DB is missing or modified")
    if db.exists():
        if not db.is_file() or db.is_symlink() or _hash(db) != record["migrated_sha256"]:
            raise PermissionError("live DB was changed after upgrade; do not erase")
        # Explicitly park only the verified migrated bytes.
        committed = stage / "failed-upgraded.sqlite"
        if committed.exists():
            raise PermissionError("recovery artifact already exists")
        os.replace(db, committed)
    os.replace(old, db)
    if _hash(db) != base["source_sha256"]:
        raise RuntimeError("recovery failed integrity; manual intervention required")
    record["phase"] = "RECOVERED"
    _write_journal(stage, record)
    return "RECOVERED"
