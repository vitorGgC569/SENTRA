"""Coordinated backup/restore for SENTRA state (Vitra-owned).

Covers SQLite databases, optional Postgres, config files, product
artifacts and protected key inventory in one owner-authorized offline
operation. Live stores are never mutated during backup; restore uses
compare-and-swap and refuses to erase newer data silently.

Keys are NEVER copied as plaintext. Only OS-protected blobs (DPAPI /
keyring envelopes) are inventoried, and their bytes are only handled by
host-injected callbacks. Postgres is optional: without a host-supplied
dump/restore runner the plan fails explicitly as unavailable.

The central host (Codex/Nexo composition) supplies durable owner-auth
admission, the offline proof and the reviewed runners. No service is
stopped here, no grant is issued, and no secret is inspected.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1
JOURNAL = "coordinated-backup.json"
MAX_CONFIG_BYTES = 4 * 1024 * 1024
MAX_SQLITE_BYTES = 8 * 1024 * 1024 * 1024


def _bind(value: str) -> str:
    if not value or len(value) > 512:
        raise ValueError("backup identity binding is required")
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
        raise PermissionError("coordinated backup denied")


def _check_state_root(state_root: Path) -> Path:
    root = Path(state_root).resolve(strict=True)
    if root.is_symlink():
        raise PermissionError("unsafe state root")
    return root


def _owned_relative(root: Path, candidate: Path, *, must_exist: bool = True) -> Path:
    raw = Path(candidate)
    if raw.is_absolute():
        raise ValueError("backup scope entries must be state-relative paths")
    if any(part in {"..", ""} for part in raw.parts) or ":" in str(raw):
        raise ValueError("unsafe backup scope entry")
    target = (root / raw).absolute()
    if target.is_symlink() or target.resolve() != target or not target.is_relative_to(root):
        raise ValueError("backup scope entry escapes owned state root")
    if must_exist and not target.exists():
        raise FileNotFoundError("backup scope entry is missing: " + raw.as_posix())
    return target


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_user_version(path: Path) -> int:
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("SQLite quick_check failed: " + path.name)
        return int(db.execute("PRAGMA user_version").fetchone()[0])


def plan_coordinated_backup(scope: dict[str, Any]) -> dict[str, Any]:
    """Pure planner: normalize a backup scope without touching the filesystem.

    scope keys (all optional lists of state-relative paths, except postgres
    which is a list of database names and keys which is an inventory-only
    list of protected blob paths):
      sqlite: ["control.sqlite", ...]
      postgres: ["sentra", ...]  (dumped via host runner, never via files)
      config: ["desktop.json", "tunnel.json", ...]
      artifacts: ["snapshots/", "shell-migration/", ...]
      keys: ["tunnel/runtime-key.dpapi", ...]  (protected blobs only)
    """
    if not isinstance(scope, dict):
        raise ValueError("backup scope must be an object")
    plan: dict[str, list[str]] = {}
    for key in ("sqlite", "config", "artifacts", "keys"):
        items = scope.get(key, [])
        if items is None:
            items = []
        if not isinstance(items, list) or not all(isinstance(x, str) and x.strip() for x in items):
            raise ValueError(f"backup scope '{key}' must be a list of relative paths")
        seen: set[str] = set()
        normalized: list[str] = []
        for entry in items:
            text = entry.strip().replace("\\", "/").strip("/")
            if not text or text in seen or len(text) > 256:
                continue
            seen.add(text)
            normalized.append(text)
        plan[key] = normalized
    pg = scope.get("postgres", [])
    if pg is None:
        pg = []
    if not isinstance(pg, list) or not all(isinstance(x, str) and x.strip() for x in pg):
        raise ValueError("backup scope 'postgres' must be a list of database names")
    plan["postgres"] = sorted({name.strip() for name in pg if len(name.strip()) <= 64})
    if not any(plan.values()):
        raise ValueError("backup scope is empty")
    return {"schema": SCHEMA, "scope": plan}


def prepare_coordinated_backup(
    state_root: Path, stage_dir: Path, scope: dict[str, Any], *,
    installation_id: str, owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
    pg_dump: Callable[[str, Path], Path] | None = None,
) -> Path:
    """Copy owned state into an isolated sibling stage. Live files are read-only sources."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root = _check_state_root(state_root)
    plan = plan_coordinated_backup(scope)
    raw_stage = Path(stage_dir).absolute()
    if raw_stage.is_symlink() or raw_stage.parent.resolve() != root.parent.resolve() or raw_stage.exists():
        raise PermissionError("backup stage must be a new private sibling of state root")
    if plan["scope"]["postgres"] and (pg_dump is None or not callable(pg_dump)):
        raise ValueError("postgres backup unavailable: no dump runner configured")
    raw_stage.mkdir(parents=True, exist_ok=False)
    try:
        record: dict[str, Any] = {
            "schema": SCHEMA,
            "phase": "BACKED_UP",
            "install_binding": _bind(installation_id),
            "state_binding": hashlib.sha256(str(root).encode()).hexdigest(),
            "operation_id": operation_id,
            "scope": plan["scope"],
            "sqlite": [],
            "postgres": [],
            "config": [],
            "artifacts": [],
            "keys": [],
        }
        payload = raw_stage / "payload"
        payload.mkdir(exist_ok=False)
        for relative in plan["scope"]["sqlite"]:
            source = _owned_relative(root, Path(relative))
            if source.stat().st_size == 0 or source.stat().st_size > MAX_SQLITE_BYTES:
                raise ValueError("SQLite backup violates size bound: " + relative)
            if any(Path(str(source) + ext).exists() for ext in ("-wal", "-shm", "-journal")):
                raise PermissionError("SQLite sidecar exists; stop/checkpoint all writers before backup")
            version = _sqlite_user_version(source)
            digest = _hash_file(source)
            destination = payload / "sqlite" / (relative.replace("/", "__") + ".bak")
            destination.parent.mkdir(parents=True, exist_ok=True)
            uri = source.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=1)) as src:
                with closing(sqlite3.connect(destination)) as dst:
                    src.backup(dst, pages=64, sleep=0.01)
            if _hash_file(destination) == "":
                raise RuntimeError("sqlite backup failed")
            record["sqlite"].append({
                "path": relative, "source_sha256": digest,
                "backup_sha256": _hash_file(destination),
                "user_version": version,
                "file": str(destination.relative_to(raw_stage).as_posix()),
            })
        for relative in plan["scope"]["config"]:
            source = _owned_relative(root, Path(relative))
            if not source.is_file() or source.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError("config backup violates bound: " + relative)
            # Never back up plaintext secrets: tunnel.json-style files carry
            # protected envelopes; refuse blobs that look like raw keys.
            head = source.read_bytes()[:4096]
            lowered = head.lower()
            if b"runtime_key" in lowered and b"dpapi" not in lowered and b"keyring" not in lowered:
                raise PermissionError("refusing config backup with unprotected secret: " + relative)
            destination = payload / "config" / (relative.replace("/", "__") + ".bak")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            record["config"].append({
                "path": relative, "sha256": _hash_file(destination),
                "file": str(destination.relative_to(raw_stage).as_posix()),
            })
        for relative in plan["scope"]["artifacts"]:
            source = _owned_relative(root, Path(relative))
            destination = payload / "artifacts" / relative.replace("/", "__")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=False,
                                ignore=lambda d, names: [n for n in names if (Path(d) / n).is_symlink()])
            elif source.is_file():
                shutil.copy2(source, destination)
            record["artifacts"].append({"path": relative})
        for relative in plan["scope"]["keys"]:
            source = _owned_relative(root, Path(relative))
            if not source.is_file():
                raise ValueError("key inventory entry is not a file: " + relative)
            name = relative.lower()
            if not any(tag in name for tag in ("dpapi", "protected", "keyring", "token-metadata")):
                raise PermissionError("key backup accepts only OS-protected blobs, never plaintext: " + relative)
            destination = payload / "keys" / (relative.replace("/", "__") + ".bak")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            record["keys"].append({
                "path": relative, "sha256": _hash_file(destination),
                "file": str(destination.relative_to(raw_stage).as_posix()),
                "plaintext_copied": False,
            })
        for dbname in plan["scope"]["postgres"]:
            assert pg_dump is not None
            dump_path = pg_dump(dbname, payload / "postgres")
            dump_resolved = Path(dump_path).resolve()
            if not dump_resolved.is_relative_to(raw_stage.resolve()) or not dump_resolved.is_file():
                raise ValueError("postgres dump escaped backup stage")
            record["postgres"].append({
                "database": dbname, "sha256": _hash_file(dump_resolved),
                "file": str(dump_resolved.relative_to(raw_stage).as_posix()),
            })
        if offline() is not True:
            raise PermissionError("backup offline gate revoked before journal seal")
        _write_journal(raw_stage, record)
        return raw_stage
    except BaseException:
        shutil.rmtree(raw_stage, ignore_errors=True)
        raise


def backup_status(stage_dir: Path) -> dict[str, Any]:
    stage = Path(stage_dir).resolve(strict=True)
    journal = stage / JOURNAL
    if not journal.is_file():
        return {"schema": SCHEMA, "phase": "absent"}
    record = json.loads(journal.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        return {"schema": SCHEMA, "phase": "invalid"}
    return {
        "schema": SCHEMA,
        "phase": str(record.get("phase") or "unknown"),
        "operation_id": str(record.get("operation_id") or ""),
        "sqlite": len(record.get("sqlite") or []),
        "postgres": len(record.get("postgres") or []),
        "config": len(record.get("config") or []),
        "artifacts": len(record.get("artifacts") or []),
        "keys": len(record.get("keys") or []),
    }


def restore_coordinated_backup(
    stage_dir: Path, state_root: Path, *, installation_id: str,
    owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
    pg_restore: Callable[[str, Path], None] | None = None,
    expected_current: dict[str, str] | None = None,
) -> dict[str, Any]:
    """CAS restore from a sealed backup stage. Newer live data is never erased silently."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root = _check_state_root(state_root)
    stage = Path(stage_dir).resolve(strict=True)
    journal_file = stage / JOURNAL
    if journal_file.is_symlink() or not journal_file.is_file() or journal_file.stat().st_size > 65536:
        raise ValueError("backup journal missing or unsafe")
    record = json.loads(journal_file.read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("schema") != SCHEMA
            or record.get("phase") not in {"BACKED_UP", "RESTORED"}
            or record.get("install_binding") != _bind(installation_id)
            or record.get("state_binding") != hashlib.sha256(str(root).encode()).hexdigest()):
        raise PermissionError("backup stage binding/phase mismatch")
    if record.get("phase") == "RESTORED" and record.get("operation_id") == operation_id:
        raise PermissionError("backup restore already consumed by this operation")
    expected = expected_current or {}
    for entry in record.get("sqlite", []):
        relative = str(entry.get("path") or "")
        live = _owned_relative(root, Path(relative), must_exist=False)
        staged_file = stage / str(entry.get("file") or "")
        if staged_file.is_symlink() or not staged_file.is_file():
            raise ValueError("backup payload missing: " + relative)
        if _hash_file(staged_file) != entry.get("backup_sha256"):
            raise ValueError("backup payload tampered: " + relative)
        want = expected.get(relative)
        if want and live.is_file() and _hash_file(live) != want:
            raise PermissionError("live SQLite changed; refusing unsafe restore: " + relative)
        if live.exists() and any(Path(str(live) + ext).exists() for ext in ("-wal", "-shm", "-journal")):
            raise PermissionError("SQLite sidecar exists; stop/checkpoint writers before restore")
        tmp = live.with_name(live.name + ".restore-" + uuid.uuid4().hex)
        try:
            with closing(sqlite3.connect(staged_file.resolve().as_uri() + "?mode=ro", uri=True)) as src:
                with closing(sqlite3.connect(tmp)) as dst:
                    src.backup(dst)
            if _hash_file(tmp) != entry.get("backup_sha256") or offline() is not True:
                raise PermissionError("restore integrity or offline gate failed: " + relative)
            os.replace(tmp, live)
        finally:
            tmp.unlink(missing_ok=True)
    for entry in record.get("config", []):
        relative = str(entry.get("path") or "")
        live = _owned_relative(root, Path(relative), must_exist=False)
        staged_file = stage / str(entry.get("file") or "")
        if _hash_file(staged_file) != entry.get("sha256"):
            raise ValueError("config payload tampered: " + relative)
        want = expected.get(relative)
        if want and live.is_file() and _hash_file(live) != want:
            raise PermissionError("live config changed; refusing unsafe restore: " + relative)
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_file, live)
    for entry in record.get("postgres", []):
        if pg_restore is None or not callable(pg_restore):
            raise ValueError("postgres restore unavailable: no restore runner configured")
        staged_file = stage / str(entry.get("file") or "")
        if _hash_file(staged_file) != entry.get("sha256"):
            raise ValueError("postgres payload tampered")
        pg_restore(str(entry.get("database") or ""), staged_file)
    # Artifacts restore is explicit per path via host file operations; keys
    # are re-protected by the host and never written as plaintext here.
    record["phase"] = "RESTORED"
    record["restored_operation_id"] = operation_id
    _write_journal(stage, record)
    return {"operation_id": operation_id, "phase": "RESTORED",
            "sqlite": len(record.get("sqlite") or []),
            "config": len(record.get("config") or []),
            "postgres": len(record.get("postgres") or [])}
