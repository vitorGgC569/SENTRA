"""Durable logical-session checkpoints for replaceable provider conversations."""
from __future__ import annotations

from .postgres_store import PostgresConnection

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from sentra_remote.secrets import protect_secret, unprotect_secret
from .control_store import ControlPlaneStore, create_control_plane_store


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
        self.store = store or create_control_plane_store(state_root)
        # Native PG has no file namespace. Do not even resolve path_for there.
        self.path = (None if getattr(self.store, "backend", "sqlite") == "postgres"
                     else self.store.path_for("session_checkpoint"))
        self.clock = clock
        with self._connect() as db:
            if getattr(self.store, "backend", "sqlite") != "postgres":
                db.execute("PRAGMA secure_delete=ON")
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
                CREATE TABLE IF NOT EXISTS session_continuations(
                    continuation_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    source_conversation_id TEXT NOT NULL,
                    target_conversation_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(owner,chat_id,request_key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_session_continuation_open
                    ON session_continuations(owner,chat_id)
                    WHERE state IN ('PREPARED','REBINDING','UNCERTAIN');
                """
            )
            self._migrate_protected_checkpoints(db)


    @staticmethod
    def _protect(value: dict[str, Any], checkpoint_id: str, field: str) -> str:
        """Bind owner-visible checkpoint/cursor content to its immutable row ID."""
        if field not in {"cursor", "checkpoint"} or not isinstance(value, dict):
            raise RuntimeError("invalid session checkpoint payload")
        raw = _json({"version": 1, "checkpoint_id": checkpoint_id,
                     "field": field, "value": value})
        ciphertext = protect_secret(raw)
        if not isinstance(ciphertext, str) or not ciphertext.startswith(("dpapi:", "keyring:")):
            raise RuntimeError("OS-protected session checkpoint storage required")
        return ciphertext

    @staticmethod
    def _open_protected(raw: str, checkpoint_id: str, field: str) -> dict[str, Any]:
        if not isinstance(raw, str) or not raw.startswith(("dpapi:", "keyring:")):
            raise RuntimeError("unprotected session checkpoint rejected")
        try:
            envelope = json.loads(unprotect_secret(raw))
        except Exception as exc:
            raise RuntimeError("session checkpoint OS decryption failed") from exc
        if (not isinstance(envelope, dict)
                or envelope.get("version") != 1
                or envelope.get("checkpoint_id") != checkpoint_id
                or envelope.get("field") != field
                or not isinstance(envelope.get("value"), dict)):
            raise RuntimeError("session checkpoint ciphertext binding mismatch")
        return envelope["value"]

    def _migrate_protected_checkpoints(self, db) -> None:
        """Fail-closed transaction for legacy plaintext checkpoint/cursor fields.

        SQLite file backend: the cleanup marker survives a crash between
        durable UPDATE and VACUUM; VACUUM + WAL truncation then rewrite SQLite
        free pages. This cannot scrub OS snapshots, cloud backups or SSD
        historical pages.
        PostgreSQL backend: MVCC row versions and backups are NOT forensic
        erasure. Any legacy plaintext row (or a pending cleanup marker) fails
        closed here and requires an explicit administrator retention purge;
        the marker is never cleared and no erasure is claimed.
        """
        pg = getattr(self.store, "backend", "sqlite") == "postgres"
        db.execute("CREATE TABLE IF NOT EXISTS session_checkpoint_storage_security "
                   "(key TEXT PRIMARY KEY, cleanup_pending INTEGER NOT NULL)")
        db.commit()
        try:
            db.execute("BEGIN IMMEDIATE")
            migrated = False
            rows = db.execute(
                "SELECT checkpoint_id,cursor_json,checkpoint_json FROM session_checkpoints"
            ).fetchall()
            for row in rows:
                ident = row["checkpoint_id"]
                updates = []
                for field, column in (("cursor", "cursor_json"),
                                      ("checkpoint", "checkpoint_json")):
                    raw = row[column]
                    if isinstance(raw, str) and raw.startswith(("dpapi:", "keyring:")):
                        self._open_protected(raw, ident, field)
                        updates.append(raw)
                        continue
                    if pg:
                        raise RuntimeError(
                            "legacy plaintext session checkpoint requires an explicit "
                            "administrator retention purge in PostgreSQL; refusing "
                            "silent migration (MVCC/backups are not erasure)")
                    try:
                        value = json.loads(raw)
                    except (ValueError, TypeError) as exc:
                        raise RuntimeError("invalid legacy checkpoint storage") from exc
                    if not isinstance(value, dict):
                        raise RuntimeError("invalid legacy checkpoint object")
                    updates.append(self._protect(value, ident, field))
                    migrated = True
                if updates != [row["cursor_json"], row["checkpoint_json"]]:
                    db.execute(
                        "UPDATE session_checkpoints SET cursor_json=?,checkpoint_json=? "
                        "WHERE checkpoint_id=?", (*updates, ident))
            if migrated:
                db.execute("INSERT INTO session_checkpoint_storage_security VALUES('os_crypto',1) "
                           "ON CONFLICT(key) DO UPDATE SET cleanup_pending=1")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        pending = db.execute(
            "SELECT cleanup_pending FROM session_checkpoint_storage_security "
            "WHERE key='os_crypto'").fetchone()
        if pending and pending[0]:
            if pg:
                raise RuntimeError(
                    "pending session checkpoint storage cleanup requires an explicit "
                    "administrator retention purge in PostgreSQL; refusing to clear "
                    "the marker (MVCC/backups are not erasure)")
            db.execute("VACUUM")
            checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and checkpoint[0]:
                raise RuntimeError("session checkpoint WAL cleanup incomplete")
            db.execute("UPDATE session_checkpoint_storage_security SET cleanup_pending=0 "
                       "WHERE key='os_crypto'")
            db.commit()

    def _connect(self) -> sqlite3.Connection | PostgresConnection:
        return self.store.connect("session_checkpoint")

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        ident = item["checkpoint_id"]
        item["cursor"] = self._open_protected(item.pop("cursor_json"), ident, "cursor")
        item["checkpoint"] = self._open_protected(
            item.pop("checkpoint_json"), ident, "checkpoint")
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
                    self._protect(cursor_value, checkpoint_id, "cursor"),
                    self._protect(checkpoint_value, checkpoint_id, "checkpoint"),
                    digest, now,
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

    @staticmethod
    def _continuation_row(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def history(self, owner: str, *, chat_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Bounded checkpoint lineage for Compact&Resume/Home projections (read-only)."""
        chat_id = _text("chat_id", chat_id, 256, required=True)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be 1..200")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM session_checkpoints WHERE owner=? AND chat_id=? "
                "ORDER BY created_at DESC,source_seq DESC LIMIT ?",
                (owner, chat_id, limit)).fetchall()
        return [self._row(row) for row in rows]

    def latest_summary(self, owner: str, *, chat_id: str) -> dict[str, Any]:
        """Latest pinned summary + cursor for continuity handshakes (read-only)."""
        item = self.latest(owner, chat_id=chat_id)
        checkpoint = item.get("checkpoint") or {}
        return {"checkpoint_id": item["checkpoint_id"], "run_id": item["run_id"],
                "chat_id": item["chat_id"], "summary": checkpoint.get("summary"),
                "payload_sha256": item.get("payload_sha256"),
                "conversation_id": item.get("conversation_id"),
                "created_at": item.get("created_at")}

    def continuation(self, owner: str, continuation_id: str) -> dict[str, Any]:
        ident = _text("continuation_id", continuation_id, 120, required=True)
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM session_continuations WHERE owner=? AND continuation_id=?",
                (owner, ident),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("session continuation not found")
        return self._continuation_row(row)

    def prepare_continuation(
        self, owner: str, *, run_id: str, chat_id: str,
        checkpoint_id: str, source_conversation_id: str,
        target_conversation_id: str, request_key: str,
    ) -> dict[str, Any]:
        """Pin an immutable checkpoint; never dispatch a model turn or grant access.

        Exactly one unresolved handoff per logical chat. Replaying the request
        key is safe only with identical source, target, run and checkpoint.
        """
        run_id = _text("run_id", run_id, 256, required=True)
        chat_id = _text("chat_id", chat_id, 256, required=True)
        checkpoint_id = _text("checkpoint_id", checkpoint_id, 120, required=True)
        source = _text("source_conversation_id", source_conversation_id, 1024, required=True)
        target = _text("target_conversation_id", target_conversation_id, 1024, required=True)
        request_key = _text("request_key", request_key, 128, required=True)
        if target == source:
            raise ValueError("continuation requires a different target conversation")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM session_continuations "
                "WHERE owner=? AND chat_id=? AND request_key=?",
                (owner, chat_id, request_key),
            ).fetchone()
            if existing:
                current = self._continuation_row(existing)
                if (current["run_id"], current["checkpoint_id"],
                    current["source_conversation_id"], current["target_conversation_id"]) != (
                    run_id, checkpoint_id, source, target
                ):
                    raise SessionCheckpointConflict("continuation request identity collision")
                return current
            checkpoint = db.execute(
                "SELECT run_id,chat_id,conversation_id FROM session_checkpoints "
                "WHERE owner=? AND checkpoint_id=?",
                (owner, checkpoint_id),
            ).fetchone()
            if checkpoint is None or (checkpoint["run_id"],checkpoint["chat_id"],
                checkpoint["conversation_id"]) != (run_id,chat_id,source):
                raise SessionCheckpointConflict("checkpoint is not bound to source chat")
            open_row = db.execute(
                "SELECT continuation_id FROM session_continuations "
                "WHERE owner=? AND chat_id=? AND state IN ('PREPARED','REBINDING','UNCERTAIN')",
                (owner,chat_id),
            ).fetchone()
            if open_row:
                raise SessionCheckpointConflict("logical chat already has unresolved continuation")
            now = self.clock()
            ident = "continuation-" + uuid.uuid4().hex
            db.execute(
                "INSERT INTO session_continuations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (ident,owner,run_id,chat_id,checkpoint_id,source,target,
                 request_key,"PREPARED",now,now),
            )
            return self._continuation_row(db.execute(
                "SELECT * FROM session_continuations WHERE continuation_id=?", (ident,)
            ).fetchone())

    def transition_continuation(
        self, owner: str, continuation_id: str, *, expected: str, state: str,
    ) -> dict[str, Any]:
        allowed = {
            ("PREPARED","REBINDING"),
            ("REBINDING","COMMITTED"),
            ("REBINDING","UNCERTAIN"),
            ("UNCERTAIN","COMMITTED"),
            ("PREPARED","CANCELLED"),
            ("UNCERTAIN","CANCELLED"),
        }
        if (expected,state) not in allowed:
            raise ValueError("invalid continuation transition")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM session_continuations WHERE owner=? AND continuation_id=?",
                (owner,continuation_id),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("session continuation not found")
            if row["state"] == state:
                return self._continuation_row(row)
            if row["state"] != expected:
                raise SessionCheckpointConflict("continuation state changed; reconcile first")
            db.execute(
                "UPDATE session_continuations SET state=?,updated_at=? "
                "WHERE continuation_id=? AND owner=?",
                (state,self.clock(),continuation_id,owner),
            )
            return self._continuation_row(db.execute(
                "SELECT * FROM session_continuations WHERE continuation_id=?",
                (continuation_id,),
            ).fetchone())
