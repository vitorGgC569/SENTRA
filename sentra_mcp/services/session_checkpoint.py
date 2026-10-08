"""Durable logical-session checkpoints for replaceable provider conversations."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore


SENSITIVE_CHECKPOINT_KEYS = {
    "api_key", "authorization", "cookie", "password", "protected_value",
    "secret", "secret_value", "session_token", "token",
}


class SessionCheckpointConflict(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _text(name: str, value: Any, maximum: int, *, required: bool = False) -> str:
    out = str(value or "").strip()
    if required and not out:
        raise ValueError(f"{name} is required")
    if len(out) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return out


def _reject_sensitive(value: Any, path: str = "checkpoint") -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower()
            if key in SENSITIVE_CHECKPOINT_KEYS or key.endswith("_password"):
                raise ValueError(
                    f"{path}.{raw_key} looks like plaintext secret material; store a secret reference instead"
                )
            _reject_sensitive(item, f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive(item, f"{path}[{index}]")


class SessionCheckpointService:
    """Stores replay-safe provider/session checkpoints without owning execution."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        store: ControlPlaneStore | None = None,
        clock=time.time,
    ) -> None:
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.path = self.store.path_for("session_checkpoint")
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS session_checkpoints(
                    checkpoint_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    agent_id TEXT,
                    chat_id TEXT NOT NULL,
                    provider TEXT,
                    conversation_id TEXT,
                    source_instance_id TEXT NOT NULL,
                    source_epoch TEXT NOT NULL,
                    source_seq INTEGER NOT NULL,
                    cursor_json TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(owner,chat_id,source_instance_id,source_epoch,source_seq)
                );
                CREATE INDEX IF NOT EXISTS idx_session_checkpoints_latest
                    ON session_checkpoints(
                        owner,chat_id,source_instance_id,source_epoch,
                        source_seq DESC,created_at DESC
                    );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return self.store.connect("session_checkpoint")

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["cursor"] = _load(item.pop("cursor_json"), {})
        item["checkpoint"] = _load(item.pop("checkpoint_json"), {})
        return item

    def write(
        self,
        owner: str,
        *,
        run_id: str,
        chat_id: str,
        source_instance_id: str,
        source_epoch: str,
        source_seq: int,
        checkpoint: dict[str, Any],
        cursor: dict[str, Any] | None = None,
        agent_id: str | None = None,
        provider: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if type(source_seq) is not int or source_seq < 0:
            raise ValueError("source_seq must be a non-negative integer")
        if not isinstance(checkpoint, dict):
            raise ValueError("checkpoint must be an object")
        if cursor is not None and not isinstance(cursor, dict):
            raise ValueError("cursor must be an object")
        _reject_sensitive(checkpoint)
        _reject_sensitive(cursor or {}, "cursor")

        run_id = _text("run_id", run_id, 256, required=True)
        chat_id = _text("chat_id", chat_id, 256, required=True)
        source_instance_id = _text(
            "source_instance_id", source_instance_id, 256, required=True
        )
        source_epoch = _text("source_epoch", source_epoch, 256, required=True)
        agent_id = _text("agent_id", agent_id, 256) or None
        provider = _text("provider", provider, 128) or None
        conversation_id = _text("conversation_id", conversation_id, 1024) or None

        cursor_value = dict(cursor or {})
        checkpoint_value = dict(checkpoint)
        canonical = _json({
            "run_id": run_id,
            "agent_id": agent_id,
            "chat_id": chat_id,
            "provider": provider,
            "conversation_id": conversation_id,
            "source_instance_id": source_instance_id,
            "source_epoch": source_epoch,
            "source_seq": source_seq,
            "cursor": cursor_value,
            "checkpoint": checkpoint_value,
        })
        if len(canonical.encode("utf-8")) > 2_000_000:
            raise ValueError("session checkpoint exceeds 2 MB")
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        now = self.clock()

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM session_checkpoints WHERE owner=? AND chat_id=? "
                "AND source_instance_id=? AND source_epoch=? AND source_seq=?",
                (owner, chat_id, source_instance_id, source_epoch, source_seq),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_sha256"]) != digest:
                    raise SessionCheckpointConflict(
                        "checkpoint sequence already exists with different payload"
                    )
                db.commit()
                return self._row(existing)

            previous = db.execute(
                "SELECT source_seq FROM session_checkpoints WHERE owner=? AND chat_id=? "
                "AND source_instance_id=? AND source_epoch=? ORDER BY source_seq DESC LIMIT 1",
                (owner, chat_id, source_instance_id, source_epoch),
            ).fetchone()
            if previous is not None and source_seq < int(previous["source_seq"]):
                raise SessionCheckpointConflict(
                    "checkpoint sequence cannot move backwards within a source epoch"
                )

            checkpoint_id = "session-checkpoint-" + uuid.uuid4().hex
            db.execute(
                "INSERT INTO session_checkpoints VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    checkpoint_id, owner, run_id, agent_id, chat_id, provider,
                    conversation_id, source_instance_id, source_epoch, source_seq,
                    _json(cursor_value), _json(checkpoint_value), digest, now,
                ),
            )
            row = db.execute(
                "SELECT * FROM session_checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            db.commit()
        return self._row(row)

    def latest(
        self,
        owner: str,
        *,
        chat_id: str,
        source_instance_id: str | None = None,
        source_epoch: str | None = None,
    ) -> dict[str, Any]:
        chat_id = _text("chat_id", chat_id, 256, required=True)
        where = ["owner=?", "chat_id=?"]
        params: list[Any] = [owner, chat_id]
        if source_instance_id is not None:
            where.append("source_instance_id=?")
            params.append(_text("source_instance_id", source_instance_id, 256, required=True))
        if source_epoch is not None:
            where.append("source_epoch=?")
            params.append(_text("source_epoch", source_epoch, 256, required=True))
        clause = " AND ".join(where)
        with self._connect() as db:
            row = db.execute(
                f"SELECT * FROM session_checkpoints WHERE {clause} "
                "ORDER BY created_at DESC,source_seq DESC LIMIT 1",
                tuple(params),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("session checkpoint not found")
        return self._row(row)
