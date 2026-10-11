"""Offline WAL-aware read-only source checkpoint into a private staged SQLite copy.

Never checkpoint the live database. Does not authorize moving staged content
back: the central ControlPlane must prove process quiescence and issue separate
single-use operations for migration/commit/recovery.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

from .release_migration import _admit, _hash, _integrity, MAX_DB_BYTES


def _root_paths(state_root: Path, database: Path, stage: Path) -> tuple[Path, Path, Path]:
    root = Path(state_root).resolve(strict=True)
    source = Path(database).absolute()
    target = Path(stage).absolute()
    if (source.is_symlink() or source.resolve() != source or
            not source.is_file() or not source.is_relative_to(root) or
            source.stat().st_size <= 0 or source.stat().st_size > MAX_DB_BYTES):
        raise ValueError("WAL source is missing or outside authorized state")
    if (target.exists() or target.is_symlink() or
            target.parent.resolve() != root.parent.resolve() or
            target.is_relative_to(root) or root.is_relative_to(target)):
        raise ValueError("WAL checkpoint requires new private sibling staging directory")
    if source.stat().st_dev != target.parent.stat().st_dev:
        raise PermissionError("offline stage must share the source filesystem")
    return root, source, target


def snapshot_offline_wal(
    state_root: Path, database: Path, stage_dir: Path, *,
    installation_id: str, owner_id: str, operation_id: str,
    authorize: Callable[[str, str, str], bool] | None,
    offline: Callable[[], bool] | None,
) -> Path:
    """Read/copy live DB+WAL exactly once; checkpoint only cloned files."""
    _admit(owner_id, operation_id, installation_id, authorize, offline)
    root, source, stage = _root_paths(state_root, database, stage_dir)
    wal = Path(str(source) + "-wal")
    shm = Path(str(source) + "-shm")
    journal = Path(str(source) + "-journal")
    if (not wal.is_file() or wal.is_symlink() or
        wal.stat().st_size == 0 or wal.stat().st_size > MAX_DB_BYTES or
        journal.exists() or (shm.exists() and (shm.is_symlink() or not shm.is_file()))):
        raise PermissionError("WAL is absent, unsafe, or rollback journal still active")
    source_hashes = {source: _hash(source), wal: _hash(wal)}
    if shm.exists():
        source_hashes[shm] = _hash(shm)
    stage.mkdir(mode=0o700, parents=False, exist_ok=False)
    copy_dir = stage / "source-copy"
    copy_dir.mkdir(mode=0o700)
    clone = copy_dir / source.name
    clone_wal = Path(str(clone) + "-wal")
    try:
        # Copy only DB + WAL; SQLite recreates -shm for the private clone.
        shutil.copyfile(source, clone)
        shutil.copyfile(wal, clone_wal)
        if (_hash(clone) != source_hashes[source] or
                _hash(clone_wal) != source_hashes[wal]):
            raise ValueError("WAL staging copy differs from original source")
        if offline is None or offline() is not True or any(
                not path.is_file() or path.is_symlink() or _hash(path) != digest
                for path, digest in source_hashes.items()):
            raise PermissionError("WAL source changed during offline snapshot")
        clean = stage / "checkpoint.sqlite"
        with closing(sqlite3.connect(clone, timeout=1)) as read_db:
            if read_db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError("WAL clone is corrupted")
            with closing(sqlite3.connect(clean)) as target_db:
                read_db.backup(target_db)
        schema = _integrity(clean)
        if (offline is None or offline() is not True or any(
                not path.is_file() or path.is_symlink() or _hash(path) != digest
                for path, digest in source_hashes.items())):
            raise PermissionError("WAL changed after private backup")
        record = {
            "schema": 1, "status": "STAGED_WAL_COPY",
            "install_binding": hashlib.sha256(installation_id.encode()).hexdigest(),
            "state_binding": hashlib.sha256(str(root).encode()).hexdigest(),
            "operation_id": operation_id,
            "source_name": source.name,
            "source_sha256": source_hashes[source],
            "wal_sha256": source_hashes[wal],
            "checkpoint_sha256": _hash(clean),
            "user_version": schema,
        }
        with (stage / "checkpoint.json").open("x", encoding="utf-8") as out:
            json.dump(record, out, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        return clean
    except BaseException:
        # An incomplete stage is never eligible for installation/promotion.
        raise
    finally:
        if copy_dir.exists():
            shutil.rmtree(copy_dir)


def verify_offline_wal_snapshot(stage_dir: Path, *, installation_id: str,
                                state_root: Path) -> dict:
    stage = Path(stage_dir).absolute()
    root = Path(state_root).resolve(strict=True)
    if stage.is_symlink() or stage.parent.resolve() != root.parent.resolve():
        raise PermissionError("unowned WAL stage")
    meta = stage / "checkpoint.json"
    clean = stage / "checkpoint.sqlite"
    if meta.is_symlink() or clean.is_symlink() or not meta.is_file() or not clean.is_file() or meta.stat().st_size > 8192:
        raise ValueError("incomplete offline WAL snapshot")
    record = json.loads(meta.read_text(encoding="utf-8"))
    if (record.get("schema") != 1 or record.get("status") != "STAGED_WAL_COPY" or
            record.get("install_binding") != hashlib.sha256(installation_id.encode()).hexdigest() or
            record.get("state_binding") != hashlib.sha256(str(root).encode()).hexdigest() or
            record.get("checkpoint_sha256") != _hash(clean)):
        raise PermissionError("WAL checkpoint identity or hash mismatch")
    if _integrity(clean) != record["user_version"]:
        raise PermissionError("WAL checkpoint schema mismatch")
    return record
