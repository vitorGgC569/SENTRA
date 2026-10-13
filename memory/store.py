"""Selo: durable memory projection with CAS, digest and retention."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class MemoryStore:
    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        root = Path(state_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "selo_memory.sqlite3"
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_entries(
                    owner TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    body_json TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    run_id TEXT,
                    work_item_id TEXT,
                    operation_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL,
                    PRIMARY KEY(owner, namespace, key)
                );
                CREATE TABLE IF NOT EXISTS memory_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _check(owner: str, namespace: str, key: str) -> None:
        if not str(owner or "").strip():
            raise ValueError("owner is required")
        if not isinstance(namespace, str) or not _NAMESPACE.fullmatch(namespace):
            raise ValueError("invalid memory namespace")
        if not isinstance(key, str) or not 1 <= len(key) <= 256:
            raise ValueError("invalid memory key")

    def put(self, owner: str, *, namespace: str, key: str, body: dict[str, Any],
            run_id: str | None = None, work_item_id: str | None = None,
            operation_id: str | None = None,
            expected_revision: int | None = None,
            ttl_s: float | None = None) -> dict[str, Any]:
        self._check(owner, namespace, key)
        if not isinstance(body, dict) or not body:
            raise ValueError("memory body must be a non-empty object")
        sealed = _canonical(body)
        if len(sealed.encode("utf-8")) > 65536:
            raise ValueError("memory body exceeds 64 KiB")
        digest = hashlib.sha256(sealed.encode()).hexdigest()
        expires_at = None
        if ttl_s is not None:
            if not isinstance(ttl_s, (int, float)) or not 1 <= float(ttl_s) <= 31_536_000:
                raise ValueError("ttl_s must be 1..31536000")
            expires_at = self.clock() + float(ttl_s)
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision,created_at FROM memory_entries WHERE owner=? AND namespace=? AND key=?",
                (owner, namespace, key),
            ).fetchone()
            current = int(row["revision"]) if row else 0
            if expected_revision is not None and expected_revision != current:
                raise ValueError("memory revision conflict: reconcile with current revision")
            revision = current + 1
            created_at = float(row["created_at"]) if row else now
            db.execute(
                "INSERT INTO memory_entries VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(owner,namespace,key) DO UPDATE SET body_json=excluded.body_json,"
                "body_sha256=excluded.body_sha256,revision=excluded.revision,run_id=excluded.run_id,"
                "work_item_id=excluded.work_item_id,operation_id=excluded.operation_id,"
                "updated_at=excluded.updated_at,expires_at=excluded.expires_at",
                (owner, namespace, key, sealed, digest, revision, run_id,
                 work_item_id, operation_id, created_at,
                 now, expires_at),
            )
            db.execute(
                "INSERT INTO memory_events(owner,namespace,key,action,revision,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (owner, namespace, key, "put", revision, now),
            )
        return {"owner": owner, "namespace": namespace, "key": key,
                "revision": revision, "body_sha256": digest,
                "authorizes_effects": False}

    def get(self, owner: str, *, namespace: str, key: str) -> dict[str, Any]:
        self._check(owner, namespace, key)
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM memory_entries WHERE owner=? AND namespace=? AND key=?",
                (owner, namespace, key),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("memory entry not found")
        if row["expires_at"] is not None and float(row["expires_at"]) <= self.clock():
            raise FileNotFoundError("memory entry expired")
        body = json.loads(row["body_json"])
        if hashlib.sha256(row["body_json"].encode()).hexdigest() != row["body_sha256"]:
            raise ValueError("memory integrity failure")
        return {
            "owner": owner, "namespace": namespace, "key": key,
            "body": body, "body_sha256": row["body_sha256"],
            "revision": row["revision"], "run_id": row["run_id"],
            "work_item_id": row["work_item_id"], "operation_id": row["operation_id"],
            "authorizes_effects": False,
        }

    def delete(self, owner: str, *, namespace: str, key: str,
               expected_revision: int | None = None) -> dict[str, Any]:
        self._check(owner, namespace, key)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM memory_entries WHERE owner=? AND namespace=? AND key=?",
                (owner, namespace, key),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("memory entry not found")
            if expected_revision is not None and int(row["revision"]) != expected_revision:
                raise ValueError("memory revision conflict")
            db.execute("DELETE FROM memory_entries WHERE owner=? AND namespace=? AND key=?",
                       (owner, namespace, key))
            db.execute(
                "INSERT INTO memory_events(owner,namespace,key,action,revision,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (owner, namespace, key, "delete", int(row["revision"]), self.clock()),
            )
        return {"deleted": True, "key": key}

    def list(self, owner: str, *, namespace: str, limit: int = 100,
             offset: int = 0) -> dict[str, Any]:
        self._check(owner, namespace, "placeholder-key")
        if type(limit) is not int or not 1 <= limit <= 500 \
                or type(offset) is not int or offset < 0:
            raise ValueError("invalid memory page")
        with self._connect() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM memory_entries WHERE owner=? AND namespace=?",
                (owner, namespace),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT namespace,key,body_sha256,revision,run_id,work_item_id,operation_id,"
                "updated_at,expires_at FROM memory_entries "
                "WHERE owner=? AND namespace=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (owner, namespace, limit, offset),
            ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total,
                "offset": offset, "limit": limit}

    def prune_expired(self, owner: str) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM memory_entries WHERE owner=? AND expires_at IS NOT NULL "
                "AND expires_at<=?",
                (owner, self.clock()),
            )
            return cursor.rowcount
