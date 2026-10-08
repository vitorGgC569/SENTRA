"""Durable ordered ingress for Remote/Edge/plugin event sources."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore


class IngressConflict(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class EventIngressService:
    """Deduplicates ordered source streams and exposes contiguous acknowledgements."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        store: ControlPlaneStore | None = None,
        clock=time.time,
    ) -> None:
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.path = self.store.path_for("event_ingress")
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_streams(
                    owner TEXT NOT NULL,
                    source_instance_id TEXT NOT NULL,
                    source_epoch TEXT NOT NULL,
                    highest_contiguous_seq INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner,source_instance_id,source_epoch)
                );
                CREATE TABLE IF NOT EXISTS source_events(
                    owner TEXT NOT NULL,
                    source_instance_id TEXT NOT NULL,
                    source_epoch TEXT NOT NULL,
                    source_seq INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    run_id TEXT,
                    operation_id TEXT,
                    idempotency_key TEXT,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(owner,source_instance_id,source_epoch,source_seq)
                );
                CREATE INDEX IF NOT EXISTS idx_source_events_run
                    ON source_events(owner,run_id,created_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return self.store.connect("event_ingress")

    @staticmethod
    def _required(name: str, value: Any, maximum: int = 256) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{name} is required")
        if len(text) > maximum:
            raise ValueError(f"{name} exceeds {maximum} characters")
        return text

    def ingest(
        self,
        owner: str,
        *,
        source_instance_id: str,
        source_epoch: str,
        source_seq: int,
        payload: dict[str, Any],
        event_id: str | None = None,
        run_id: str | None = None,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        source_instance_id = self._required("source_instance_id", source_instance_id)
        source_epoch = self._required("source_epoch", source_epoch)
        if type(source_seq) is not int or source_seq < 1:
            raise ValueError("source_seq must be an integer >= 1")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        raw = _json(payload)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        eid = self._required("event_id", event_id or f"src-{uuid.uuid4().hex}", 256)
        now = self.clock()

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM source_events WHERE owner=? AND source_instance_id=? "
                "AND source_epoch=? AND source_seq=?",
                (owner, source_instance_id, source_epoch, source_seq),
            ).fetchone()
            if existing is not None:
                same = (
                    existing["payload_sha256"] == digest
                    and (existing["idempotency_key"] or "") == (idempotency_key or "")
                    and (existing["run_id"] or "") == (run_id or "")
                    and (existing["operation_id"] or "") == (operation_id or "")
                )
                if not same:
                    raise IngressConflict(
                        "source sequence was reused with different event intent"
                    )
                stream = db.execute(
                    "SELECT highest_contiguous_seq FROM source_streams WHERE owner=? "
                    "AND source_instance_id=? AND source_epoch=?",
                    (owner, source_instance_id, source_epoch),
                ).fetchone()
                return {
                    "event_id": existing["event_id"],
                    "source_seq": source_seq,
                    "payload_sha256": digest,
                    "idempotent_replay": True,
                    "highest_contiguous_source_seq": int(stream[0]) if stream else 0,
                }

            try:
                db.execute(
                    "INSERT INTO source_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        owner, source_instance_id, source_epoch, source_seq, eid,
                        run_id, operation_id, idempotency_key, digest, raw, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IngressConflict("event_id already exists in another source position") from exc

            stream = db.execute(
                "SELECT highest_contiguous_seq FROM source_streams WHERE owner=? "
                "AND source_instance_id=? AND source_epoch=?",
                (owner, source_instance_id, source_epoch),
            ).fetchone()
            contiguous = int(stream[0]) if stream else 0
            while True:
                candidate = contiguous + 1
                exists = db.execute(
                    "SELECT 1 FROM source_events WHERE owner=? AND source_instance_id=? "
                    "AND source_epoch=? AND source_seq=?",
                    (owner, source_instance_id, source_epoch, candidate),
                ).fetchone()
                if exists is None:
                    break
                contiguous = candidate
            db.execute(
                "INSERT INTO source_streams(owner,source_instance_id,source_epoch,"
                "highest_contiguous_seq,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(owner,source_instance_id,source_epoch) DO UPDATE SET "
                "highest_contiguous_seq=excluded.highest_contiguous_seq,"
                "updated_at=excluded.updated_at",
                (owner, source_instance_id, source_epoch, contiguous, now),
            )
            db.commit()

        return {
            "event_id": eid,
            "source_seq": source_seq,
            "payload_sha256": digest,
            "idempotent_replay": False,
            "highest_contiguous_source_seq": contiguous,
        }

    def status(
        self, owner: str, *, source_instance_id: str, source_epoch: str,
    ) -> dict[str, Any]:
        with self._connect() as db:
            stream = db.execute(
                "SELECT * FROM source_streams WHERE owner=? AND source_instance_id=? "
                "AND source_epoch=?",
                (owner, source_instance_id, source_epoch),
            ).fetchone()
            total = int(db.execute(
                "SELECT COUNT(*) FROM source_events WHERE owner=? AND source_instance_id=? "
                "AND source_epoch=?",
                (owner, source_instance_id, source_epoch),
            ).fetchone()[0])
        return {
            "source_instance_id": source_instance_id,
            "source_epoch": source_epoch,
            "highest_contiguous_source_seq": int(stream["highest_contiguous_seq"]) if stream else 0,
            "received_events": total,
            "updated_at": float(stream["updated_at"]) if stream else None,
        }
