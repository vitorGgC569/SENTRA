"""Locally durable and hash-linked SENTRA audit ledger (not an operation store).

Compared to the in-memory AuditChain, events survive process restarts. This
SQLite ledger is an auxiliary evidence sink: it does NOT reserve Operations,
own grants, implement Tessera, or independently witness/checkpoint its head.
Truncation of the final rows cannot be proven without an externally trusted
expected_head. The host must enforce filesystem access controls.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from .audit_chain import AuditChain, AuditEntry, GENESIS, canonical, _hash


class AuditIntegrityError(RuntimeError):
    """Stored audit evidence was corrupted or is not canonical."""


class AuditHeadConflict(RuntimeError):
    """Another writer has changed the audit head since the caller checked."""


class SQLiteAuditLedger:
    """Append-only API with atomic SQLite transactions and hash verification.

    Concurrent writers are serialized by BEGIN IMMEDIATE (even across local
    processes); the supplied expected_head provides optimistic concurrency.
    For distributed trust, anchor head externally and compare on verification.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path == Path(":memory:"):
            raise ValueError("durable ledger requires an on-disk SQLite path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS audit_events("
                "seq INTEGER PRIMARY KEY, event_json TEXT NOT NULL, "
                "previous TEXT NOT NULL, digest TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=8, isolation_level=None)
        db.execute("PRAGMA busy_timeout=8000")
        return db

    @staticmethod
    def _validate(db: sqlite3.Connection) -> tuple[tuple[AuditEntry, ...], str]:
        rows = db.execute(
            "SELECT seq,event_json,previous,digest FROM audit_events ORDER BY seq ASC"
        ).fetchall()
        prev = GENESIS
        entries: list[AuditEntry] = []
        for expected_seq, (seq, raw, parent, digest) in enumerate(rows, 1):
            try:
                event = json.loads(raw)
                expected_raw = canonical(event).decode("utf-8")
                expected_digest = _hash(prev, canonical(event))
            except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
                raise AuditIntegrityError("corrupt audit event encoding") from exc
            if (seq != expected_seq or raw != expected_raw or parent != prev
                    or digest != expected_digest):
                raise AuditIntegrityError("audit history integrity mismatch")
            entries.append(AuditEntry(seq, event, parent, digest))
            prev = digest
        return tuple(entries), prev

    def append(self, event: Mapping[str, Any], *,
               expected_head: str | None = None) -> AuditEntry:
        payload = canonical(event)
        if len(payload) > 65_536:
            raise ValueError("audit event too large")
        event_json = payload.decode("utf-8")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            entries, head = self._validate(db)
            if expected_head is not None and head != expected_head:
                raise AuditHeadConflict("trusted audit head changed")
            row = AuditEntry(len(entries) + 1, json.loads(event_json),
                             head, _hash(head, payload))
            db.execute(
                "INSERT INTO audit_events(seq,event_json,previous,digest) "
                "VALUES(?,?,?,?)",
                (row.seq, event_json, row.previous, row.digest),
            )
            db.commit()
            return row
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def entries(self, *, expected_head: str | None = None) -> tuple[AuditEntry, ...]:
        with self._connect() as db:
            entries, current = self._validate(db)
        if expected_head is not None and expected_head != current:
            raise AuditIntegrityError("audit head differs from trusted checkpoint")
        return entries

    def verify(self, *, expected_head: str | None = None) -> bool:
        try:
            return AuditChain.verify(self.entries(expected_head=expected_head),
                                     expected_head=expected_head)
        except (AuditIntegrityError, sqlite3.DatabaseError):
            return False

    @property
    def head(self) -> str:
        entries = self.entries()
        return entries[-1].digest if entries else GENESIS
