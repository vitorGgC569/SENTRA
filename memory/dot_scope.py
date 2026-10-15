"""Dot-scoped durable memory, plan, and context.

Records live in one SQLite file and are keyed by owner, Dot, kind, and key.
A new process that opens the same root sees the same rows. A read for one Dot
never returns another Dot's body. This store recalls notes; it does not create
runs, grants, leases, or effects.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_KINDS = {"memory", "plan", "context"}
_PLAN_STATUS = {"draft", "active", "blocked", "done", "abandoned"}
_STEP_STATUS = {"pending", "active", "blocked", "done"}
_MAX_BODY_BYTES = 65536


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ident(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _ref(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or "\x00" in value:
        raise ValueError(f"invalid {name}")
    return value


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("context variable is not finite")
        return value
    if isinstance(value, str):
        if len(value) > 500:
            raise ValueError("context variable is too long")
        return value
    raise ValueError("context variables must be scalars")


def _validate_body(kind: str, body: Any, dot_id: str) -> None:
    if not isinstance(body, dict) or not body:
        raise ValueError("memory body must be a non-empty object")
    embedded = body.get("dot_id")
    if embedded is not None and embedded != dot_id:
        raise ValueError("body dot_id does not match the record")
    if kind == "memory":
        return
    if kind == "plan":
        allowed = {"objective", "status", "steps"}
        if set(body) - allowed:
            raise ValueError("plan has unsupported fields")
        objective = body.get("objective")
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 4000:
            raise ValueError("invalid plan objective")
        if body.get("status") not in _PLAN_STATUS:
            raise ValueError("invalid plan status")
        steps = body.get("steps")
        if not isinstance(steps, list) or len(steps) > 100:
            raise ValueError("invalid plan steps")
        seen: set[str] = set()
        for step in steps:
            if not isinstance(step, dict) or set(step) - {"id", "title", "status"}:
                raise ValueError("invalid plan step")
            step_id = step.get("id")
            title = step.get("title")
            if not isinstance(step_id, str) or not _ID.fullmatch(step_id):
                raise ValueError("invalid plan step id")
            if step_id in seen:
                raise ValueError("duplicate plan step id")
            seen.add(step_id)
            if not isinstance(title, str) or not title.strip() or len(title) > 400:
                raise ValueError("invalid plan step title")
            if step.get("status") not in _STEP_STATUS:
                raise ValueError("invalid plan step status")
        return
    if kind == "context":
        if set(body) - {"summary", "variables", "conversation_ids"}:
            raise ValueError("context has unsupported fields")
        summary = body.get("summary")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
            raise ValueError("invalid context summary")
        variables = body.get("variables", {})
        if not isinstance(variables, dict) or len(variables) > 50:
            raise ValueError("invalid context variables")
        for key, value in variables.items():
            if not isinstance(key, str) or not _ID.fullmatch(key):
                raise ValueError("invalid context variable name")
            _scalar(value)
        conversations = body.get("conversation_ids", [])
        if not isinstance(conversations, list) or len(conversations) > 50:
            raise ValueError("invalid context conversations")
        seen_conversations: set[str] = set()
        for item in conversations:
            if not isinstance(item, str) or not _ID.fullmatch(item):
                raise ValueError("invalid conversation id")
            if item in seen_conversations:
                raise ValueError("duplicate conversation id")
            seen_conversations.add(item)
        return
    raise ValueError("invalid memory kind")


class DotScopedStore:
    """SQLite memory partitioned by owner and Dot id."""

    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        root = Path(state_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "dot_memory.sqlite3"
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS dot_records(
                    owner TEXT NOT NULL,
                    dot_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    body_json TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    run_id TEXT,
                    work_item_id TEXT,
                    operation_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner, dot_id, kind, key)
                );
                CREATE INDEX IF NOT EXISTS dot_records_owner_dot
                    ON dot_records(owner, dot_id, kind);
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

    def put(
        self,
        owner: str,
        *,
        dot_id: str,
        kind: str,
        key: str,
        body: dict[str, Any],
        run_id: str | None = None,
        work_item_id: str | None = None,
        operation_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        owner = _ident(owner, "owner")
        dot_id = _ident(dot_id, "dot_id")
        key = _ident(key, "key")
        if kind not in _KINDS:
            raise ValueError("invalid memory kind")
        _validate_body(kind, body, dot_id)
        sealed = _canonical(body)
        if len(sealed.encode("utf-8")) > _MAX_BODY_BYTES:
            raise ValueError("memory body exceeds 64 KiB")
        digest = hashlib.sha256(sealed.encode()).hexdigest()
        run_id = _ref("run_id", run_id)
        work_item_id = _ref("work_item_id", work_item_id)
        operation_id = _ref("operation_id", operation_id)
        now = float(self.clock())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision, created_at FROM dot_records "
                "WHERE owner=? AND dot_id=? AND kind=? AND key=?",
                (owner, dot_id, kind, key),
            ).fetchone()
            current = int(row["revision"]) if row else 0
            if expected_revision is not None and expected_revision != current:
                raise ValueError("memory revision conflict: reconcile with current revision")
            revision = current + 1
            created_at = float(row["created_at"]) if row else now
            db.execute(
                "INSERT INTO dot_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(owner, dot_id, kind, key) DO UPDATE SET "
                "body_json=excluded.body_json, body_sha256=excluded.body_sha256, "
                "revision=excluded.revision, run_id=excluded.run_id, "
                "work_item_id=excluded.work_item_id, operation_id=excluded.operation_id, "
                "updated_at=excluded.updated_at",
                (owner, dot_id, kind, key, sealed, digest, revision, run_id,
                 work_item_id, operation_id, created_at, now),
            )
        return {
            "owner": owner,
            "dot_id": dot_id,
            "kind": kind,
            "key": key,
            "revision": revision,
            "body_sha256": digest,
            "authorizes_effects": False,
        }

    def get(self, owner: str, *, dot_id: str, kind: str, key: str) -> dict[str, Any]:
        owner = _ident(owner, "owner")
        dot_id = _ident(dot_id, "dot_id")
        key = _ident(key, "key")
        if kind not in _KINDS:
            raise ValueError("invalid memory kind")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM dot_records WHERE owner=? AND dot_id=? AND kind=? AND key=?",
                (owner, dot_id, kind, key),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("memory entry not found")
        if hashlib.sha256(row["body_json"].encode()).hexdigest() != row["body_sha256"]:
            raise ValueError("memory integrity failure")
        body = json.loads(row["body_json"])
        if row["owner"] != owner or row["dot_id"] != dot_id:
            raise FileNotFoundError("memory entry not found")
        return {
            "owner": owner,
            "dot_id": dot_id,
            "kind": kind,
            "key": key,
            "body": body,
            "body_sha256": row["body_sha256"],
            "revision": int(row["revision"]),
            "run_id": row["run_id"],
            "work_item_id": row["work_item_id"],
            "operation_id": row["operation_id"],
            "authorizes_effects": False,
        }

    def delete(
        self,
        owner: str,
        *,
        dot_id: str,
        kind: str,
        key: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        owner = _ident(owner, "owner")
        dot_id = _ident(dot_id, "dot_id")
        key = _ident(key, "key")
        if kind not in _KINDS:
            raise ValueError("invalid memory kind")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM dot_records WHERE owner=? AND dot_id=? AND kind=? AND key=?",
                (owner, dot_id, kind, key),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("memory entry not found")
            if expected_revision is not None and int(row["revision"]) != expected_revision:
                raise ValueError("memory revision conflict")
            db.execute(
                "DELETE FROM dot_records WHERE owner=? AND dot_id=? AND kind=? AND key=?",
                (owner, dot_id, kind, key),
            )
        return {"deleted": True, "key": key, "dot_id": dot_id, "authorizes_effects": False}

    def list_keys(self, owner: str, *, dot_id: str, kind: str) -> dict[str, Any]:
        owner = _ident(owner, "owner")
        dot_id = _ident(dot_id, "dot_id")
        if kind not in _KINDS:
            raise ValueError("invalid memory kind")
        with self._connect() as db:
            rows = db.execute(
                "SELECT key, body_sha256, revision, updated_at FROM dot_records "
                "WHERE owner=? AND dot_id=? AND kind=? ORDER BY key",
                (owner, dot_id, kind),
            ).fetchall()
        items = [
            {
                "key": row["key"],
                "body_sha256": row["body_sha256"],
                "revision": int(row["revision"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return {
            "owner": owner,
            "dot_id": dot_id,
            "kind": kind,
            "items": items,
            "total": len(items),
            "authorizes_effects": False,
        }
