"""Staged Postgres migration with crash-safe rollback (Vitra-owned).

SQLite migration lives in `staged_upgrade.py`; this module covers the
optional Postgres backend with the same discipline: offline snapshot via a
real `pg_dump` runner, monotonic schema versions, compare-and-swap apply
through a host-supplied SQL runner, and explicit owner-authorized rollback
from the snapshot. No auto-retry of unknown effects.

Contract note (C10): Nexo owns the Postgres store module when it lands.
This module never imports it and never claims the backend exists: without
a DSN plus dump/restore/SQL runners every operation fails explicitly as
unavailable. The central host supplies durable owner-auth admission and
the offline proof.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1
JOURNAL = "postgres-migration.json"


def _bind(value: str) -> str:
    if not value or len(value) > 512:
        raise ValueError("migration identity binding is required")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_journal(stage: Path, record: dict[str, Any]) -> None:
    target = stage / JOURNAL
    tmp = stage / (JOURNAL + ".tmp")
    with tmp.open("x", encoding="utf-8") as out:
        json.dump(record, out, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, target)


def _admit(owner_id: str, operation_id: str, installation_id: str,
           authorize: Callable[[str, str, str], bool] | None,
           offline: Callable[[], bool] | None) -> None:
    if not owner_id or not operation_id or not installation_id:
        raise PermissionError("durable owner-auth and installation binding required")
    if authorize is None or offline is None:
        raise PermissionError("durable owner-auth and offline process gate required")
    if offline() is not True or authorize(owner_id, operation_id, installation_id) is not True:
        raise PermissionError("postgres migration denied")


def _stage(state_root: Path, stage_dir: Path, *, must_exist: bool) -> tuple[Path, Path]:
    root = Path(state_root).resolve(strict=True)
    raw = Path(stage_dir).absolute()
    if raw.is_symlink() or raw.parent.resolve() != root.parent.resolve():
        raise PermissionError("migration stage must be a private sibling of state root")
    if must_exist:
        stage = raw.resolve(strict=True)
        if not stage.is_dir():
            raise PermissionError("unsafe migration stage")
        return root, stage
    if raw.exists():
        raise ValueError("migration stage already exists; recover or roll back first")
    return root, raw


def plan_postgres_migration(*, database: str, current_version: int, target_version: int,
                            statements_digest: str) -> dict[str, Any]:
    """Pure planner: monotonic schema move bound to reviewed SQL by digest."""
    name = (database or "").strip()
    if not name or len(name) > 64:
        raise ValueError("postgres database name required")
    if not isinstance(current_version, int) or not isinstance(target_version, int):
        raise ValueError("postgres schema versions must be integers")
    if target_version <= current_version:
        raise ValueError("postgres target schema must increase monotonically")
    digest = (statements_digest or "").lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("postgres migration requires the reviewed SQL digest")
    return {"schema": SCHEMA, "database": name, "from": current_version,
            "to": target_version, "statements_sha256": digest}


def prepare_postgres_migration(
    state_root: Path, stage_dir: Path, *, database: str, current_version: int,
    target_version: int, statements_digest: str, installation_id: str,
    owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
    dump_runner: Callable[..., Path] | None = None, dsn: str = "",
) -> Path:
    """Offline snapshot of the live database. The live DB is never migrated here."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root, raw_stage = _stage(state_root, stage_dir, must_exist=False)
    plan = plan_postgres_migration(database=database, current_version=current_version,
                                   target_version=target_version,
                                   statements_digest=statements_digest)
    if dump_runner is None or not callable(dump_runner):
        raise ValueError("postgres migration unavailable: no dump runner configured")
    raw_stage.mkdir(parents=True, exist_ok=False)
    try:
        dump_path = dump_runner(plan["database"], raw_stage / "snapshot", dsn=dsn)
        dump_resolved = Path(dump_path).resolve()
        if not dump_resolved.is_relative_to(raw_stage.resolve()) or not dump_resolved.is_file():
            raise ValueError("postgres dump escaped migration stage")
        digest = hashlib.sha256()
        with dump_resolved.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        _write_journal(raw_stage, {
            "schema": SCHEMA, "phase": "STAGED",
            "install_binding": _bind(installation_id),
            "state_binding": hashlib.sha256(str(root).encode()).hexdigest(),
            "operation_id": operation_id, **plan,
            "snapshot_sha256": digest.hexdigest(),
            "snapshot_file": str(dump_resolved.relative_to(raw_stage).as_posix()),
        })
        return raw_stage
    except BaseException:
        import shutil
        shutil.rmtree(raw_stage, ignore_errors=True)
        raise


def _load(stage: Path, root: Path, installation_id: str) -> dict[str, Any]:
    journal = stage / JOURNAL
    if journal.is_symlink() or not journal.is_file() or journal.stat().st_size > 16384:
        raise ValueError("postgres migration journal missing or unsafe")
    record = json.loads(journal.read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("schema") != SCHEMA
            or record.get("install_binding") != _bind(installation_id)
            or record.get("state_binding") != hashlib.sha256(str(root).encode()).hexdigest()):
        raise PermissionError("postgres migration stage binding mismatch")
    return record


def commit_postgres_migration(
    stage_dir: Path, state_root: Path, *, installation_id: str, owner_id: str,
    operation_id: str, authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
    sql_runner: Callable[..., int] | None = None,
    statements: str = "", dsn: str = "",
) -> dict[str, Any]:
    """Apply reviewed SQL once with CAS on the live schema version. No silent repeat."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root, stage = _stage(state_root, stage_dir, must_exist=True)
    record = _load(stage, root, installation_id)
    if record.get("phase") != "STAGED" or record.get("operation_id") != operation_id:
        raise PermissionError("postgres migration already consumed or mismatched")
    if sql_runner is None or not callable(sql_runner):
        raise ValueError("postgres migration unavailable: no SQL runner configured")
    if not statements or len(statements.encode("utf-8")) > 1024 * 1024:
        raise ValueError("postgres migration requires the reviewed SQL text (<=1 MiB)")
    if hashlib.sha256(statements.encode("utf-8")).hexdigest() != record.get("statements_sha256"):
        raise PermissionError("postgres migration SQL does not match the reviewed digest")
    record["phase"] = "SWITCHING"
    _write_journal(stage, record)
    live_version = sql_runner("version", {"database": record["database"], "dsn": dsn})
    if not isinstance(live_version, int) or live_version != record.get("from"):
        raise PermissionError("live postgres schema changed after snapshot; refusing apply")
    applied = sql_runner("migrate", {"database": record["database"], "dsn": dsn,
                                     "statements": statements,
                                     "from": record["from"], "to": record["to"]})
    if applied != record.get("to"):
        raise RuntimeError("postgres migration needs manual recovery: uncertain effect")
    record["phase"] = "COMMITTED"
    _write_journal(stage, record)
    return {"operation_id": operation_id, "phase": "COMMITTED",
            "database": record["database"], "to": record["to"]}


def rollback_postgres_migration(
    stage_dir: Path, state_root: Path, *, installation_id: str, owner_id: str,
    operation_id: str, authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
    restore_runner: Callable[..., None] | None = None, dsn: str = "",
) -> dict[str, Any]:
    """Explicit owner-authorized rollback from the staged snapshot."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root, stage = _stage(state_root, stage_dir, must_exist=True)
    record = _load(stage, root, installation_id)
    if record.get("phase") not in {"SWITCHING", "COMMITTED"}:
        raise PermissionError("no interrupted/committed postgres migration eligible for rollback")
    if restore_runner is None or not callable(restore_runner):
        raise ValueError("postgres rollback unavailable: no restore runner configured")
    snapshot = stage / str(record.get("snapshot_file") or "")
    if snapshot.is_symlink() or not snapshot.is_file():
        raise ValueError("postgres snapshot missing")
    digest = hashlib.sha256()
    with snapshot.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != record.get("snapshot_sha256"):
        raise ValueError("postgres snapshot tampered or missing")
    restore_runner(record["database"], snapshot, dsn=dsn)
    record["phase"] = "ROLLED_BACK"
    record["rollback_operation_id"] = operation_id
    _write_journal(stage, record)
    return {"operation_id": operation_id, "phase": "ROLLED_BACK",
            "database": record["database"]}


def postgres_migration_status(stage_dir: Path) -> dict[str, Any]:
    stage = Path(stage_dir).resolve(strict=True)
    journal = stage / JOURNAL
    if not journal.is_file():
        return {"schema": SCHEMA, "phase": "absent"}
    record = json.loads(journal.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        return {"schema": SCHEMA, "phase": "invalid"}
    return {"schema": SCHEMA, "phase": str(record.get("phase") or "unknown"),
            "database": str(record.get("database") or ""),
            "from": record.get("from"), "to": record.get("to")}
