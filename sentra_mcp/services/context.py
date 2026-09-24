"""Typed shared-context bus for SENTRA.

The context bus stores knowledge and coordination facts. It is deliberately not
authoritative for Run/Operation state: only the Control Plane may decide those.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .context_transport import ContextTransport, NullContextTransport

EVENT_TYPES = {
    "FACT", "HYPOTHESIS", "DECISION", "OBJECTION",
    "RESULT", "FAILURE", "ARTIFACT", "QUESTION",
}
_SYSTEM_EVENT_TYPES = EVENT_TYPES | {"CLAIM", "CHALLENGE", "MESSAGE", "CLAIM_RESOLUTION"}
CLAIM_STATUSES = {"PROPOSED", "CHALLENGED", "VERIFIED", "REJECTED"}
CLAIM_RESOLUTION_AUTHORITIES = {"quality_gate", "deterministic_validator", "control_plane"}
CONTEXT_GRANT_PERMISSIONS = {"read", "publish", "message", "claims"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _bounded_text(name: str, value: str | None, *, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return text


class ContextBusService:
    """Persistent append-only context events, subscriptions, cursors and claims."""

    def __init__(
        self,
        state_root: Path,
        *,
        clock=time.time,
        transport: ContextTransport | None = None,
    ) -> None:
        self.state_root = Path(state_root).resolve()
        self.root = self.state_root / "context"
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.transport: ContextTransport = transport or NullContextTransport()
        self.last_transport_error: str | None = None
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            str(self.root / "context.sqlite3"),
            check_same_thread=False,
            timeout=10,
        )
        self.db.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self.lock:
            self.db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;

                CREATE TABLE IF NOT EXISTS context_sequences(
                    run_id TEXT PRIMARY KEY,
                    last_seq INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_events(
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    task_id TEXT,
                    agent_id TEXT,
                    event_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    confidence REAL,
                    supersedes_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(run_id, seq),
                    UNIQUE(run_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS context_subscriptions(
                    run_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    consumer_id TEXT NOT NULL,
                    types_json TEXT NOT NULL,
                    subject_prefixes_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(run_id, consumer_id)
                );

                CREATE TABLE IF NOT EXISTS context_cursors(
                    run_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    consumer_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(run_id, consumer_id)
                );

                CREATE TABLE IF NOT EXISTS context_claims(
                    claim_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    task_id TEXT,
                    agent_id TEXT,
                    subject TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    confidence REAL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(run_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS context_claim_challenges(
                    challenge_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    agent_id TEXT,
                    reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(run_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS context_claim_resolutions(
                    resolution_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(run_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS context_grants(
                    grant_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_context_grants_run
                    ON context_grants(run_id, agent_id, expires_at);

                CREATE INDEX IF NOT EXISTS idx_context_events_run_seq
                    ON context_events(run_id, seq);
                CREATE INDEX IF NOT EXISTS idx_context_events_subject
                    ON context_events(run_id, subject, seq);
                CREATE INDEX IF NOT EXISTS idx_context_events_type
                    ON context_events(run_id, event_type, seq);
                CREATE INDEX IF NOT EXISTS idx_context_claims_run
                    ON context_claims(run_id, updated_at);
                """
            )
            self.db.commit()

    def close(self) -> None:
        with self.lock:
            self.db.close()
        try:
            self.transport.close()
        except Exception:
            pass

    def _fanout(self, event: dict[str, Any]) -> None:
        if event.get("idempotent_replay") is True:
            return
        try:
            self.transport.publish(event)
            self.last_transport_error = None
        except Exception as exc:
            # Transient fan-out is acceleration only; durable truth is already committed.
            self.last_transport_error = str(exc)[:500]

    @staticmethod
    def _grant_info(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "grant_id": row["grant_id"],
            "run_id": row["run_id"],
            "owner": row["owner"],
            "agent_id": row["agent_id"],
            "permissions": _load(row["permissions_json"], []),
            "expires_at": row["expires_at"],
            "revoked": bool(row["revoked"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_grant(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str,
        permissions: list[str],
        ttl_hours: float = 24.0,
    ) -> dict[str, Any]:
        agent = _bounded_text("agent_id", agent_id, maximum=128, required=True)
        normalized: list[str] = []
        for raw in permissions:
            permission = str(raw or "").strip().lower()
            if permission not in CONTEXT_GRANT_PERMISSIONS:
                raise ValueError(f"invalid context grant permission: {permission}")
            if permission not in normalized:
                normalized.append(permission)
        if not normalized:
            raise ValueError("context grant requires at least one permission")
        ttl = float(ttl_hours)
        if not 0.05 <= ttl <= 24 * 30:
            raise ValueError("ttl_hours must be between 0.05 and 720")

        now = self.clock()
        grant_id = "grant-" + uuid.uuid4().hex
        secret = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        expires_at = now + ttl * 3600
        with self.lock:
            self.db.execute(
                "INSERT INTO context_grants("
                "grant_id,run_id,owner,agent_id,permissions_json,token_hash,"
                "expires_at,revoked,created_at,updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    grant_id, run_id, owner, agent, _json(normalized), token_hash,
                    expires_at, 0, now, now,
                ),
            )
            self.db.commit()
            row = self.db.execute(
                "SELECT * FROM context_grants WHERE grant_id=?", (grant_id,)
            ).fetchone()
        data = self._grant_info(row)
        data["context_token"] = f"cg1.{grant_id}.{secret}"
        return data

    def authorize_grant(
        self,
        run_id: str,
        context_token: str,
        *,
        permission: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        raw = str(context_token or "")
        parts = raw.split(".")
        if len(parts) != 3 or parts[0] != "cg1":
            raise PermissionError("invalid context grant")
        _, grant_id, secret = parts
        if not grant_id.startswith("grant-") or not secret:
            raise PermissionError("invalid context grant")
        permission = str(permission or "").strip().lower()
        if permission not in CONTEXT_GRANT_PERMISSIONS:
            raise PermissionError("invalid context grant permission")

        with self.lock:
            row = self.db.execute(
                "SELECT * FROM context_grants WHERE grant_id=?", (grant_id,)
            ).fetchone()
            if row is None:
                raise PermissionError("invalid context grant")
            supplied_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(str(row["token_hash"]), supplied_hash):
                raise PermissionError("invalid context grant")
            if row["run_id"] != run_id:
                raise PermissionError("context grant belongs to another run")
            if bool(row["revoked"]):
                raise PermissionError("context grant is revoked")
            if float(row["expires_at"]) <= self.clock():
                raise PermissionError("context grant has expired")
            permissions = _load(row["permissions_json"], [])
            if permission not in permissions:
                raise PermissionError("context grant lacks required permission")
            if agent_id is not None and str(row["agent_id"]) != str(agent_id):
                raise PermissionError("context grant belongs to another agent")
            return self._grant_info(row)

    def revoke_grant(self, grant_id: str, owner: str) -> dict[str, Any]:
        grant = _bounded_text("grant_id", grant_id, maximum=128, required=True)
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM context_grants WHERE grant_id=?", (grant,)
            ).fetchone()
            if row is None:
                raise FileNotFoundError("context grant not found")
            if row["owner"] != owner:
                raise PermissionError("context grant belongs to another owner")
            now = self.clock()
            self.db.execute(
                "UPDATE context_grants SET revoked=1,updated_at=? WHERE grant_id=?",
                (now, grant),
            )
            self.db.commit()
            updated = self.db.execute(
                "SELECT * FROM context_grants WHERE grant_id=?", (grant,)
            ).fetchone()
            return self._grant_info(updated)

    def _next_seq_locked(self, run_id: str) -> int:
        row = self.db.execute(
            "SELECT last_seq FROM context_sequences WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            seq = 1
            self.db.execute(
                "INSERT INTO context_sequences(run_id,last_seq) VALUES(?,?)",
                (run_id, seq),
            )
        else:
            seq = int(row["last_seq"]) + 1
            self.db.execute(
                "UPDATE context_sequences SET last_seq=? WHERE run_id=?",
                (seq, run_id),
            )
        return seq

    @staticmethod
    def _normalize_types(types: list[str] | None, *, allow_system: bool = False) -> list[str]:
        allowed = _SYSTEM_EVENT_TYPES if allow_system else EVENT_TYPES
        normalized: list[str] = []
        for value in types or []:
            item = str(value or "").strip().upper()
            if item not in allowed:
                raise ValueError(f"invalid context event type: {item}")
            if item not in normalized:
                normalized.append(item)
        return normalized

    @staticmethod
    def _normalize_prefixes(prefixes: list[str] | None) -> list[str]:
        result: list[str] = []
        for value in prefixes or []:
            item = _bounded_text("subject prefix", value, maximum=240, required=True)
            if item not in result:
                result.append(item)
        return result

    @staticmethod
    def _normalize_evidence(evidence: list[str] | None) -> list[str]:
        result: list[str] = []
        for value in evidence or []:
            item = _bounded_text("evidence reference", value, maximum=240, required=True)
            if item not in result:
                result.append(item)
        if len(result) > 100:
            raise ValueError("evidence exceeds 100 references")
        return result

    @staticmethod
    def _confidence(value: float | None) -> float | None:
        if value is None:
            return None
        number = float(value)
        if not 0.0 <= number <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return number

    def _event_info(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "run_id": row["run_id"],
            "seq": int(row["seq"]),
            "task_id": row["task_id"],
            "agent_id": row["agent_id"],
            "type": row["event_type"],
            "subject": row["subject"],
            "payload": _load(row["payload_json"], {}),
            "evidence": _load(row["evidence_json"], []),
            "confidence": row["confidence"],
            "supersedes": _load(row["supersedes_json"], []),
            "created_at": row["created_at"],
        }

    def event_info(self, event_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM context_events WHERE event_id=? AND owner=?",
                (event_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("context event not found")
            return self._event_info(row)

    def _publish_locked(
        self,
        run_id: str,
        owner: str,
        *,
        event_type: str,
        subject: str,
        payload: dict[str, Any] | None,
        evidence: list[str] | None,
        confidence: float | None,
        supersedes: list[str] | None,
        task_id: str | None,
        agent_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        event_type = str(event_type or "").strip().upper()
        if event_type not in _SYSTEM_EVENT_TYPES:
            raise ValueError("invalid context event type")
        subject = _bounded_text("subject", subject, maximum=500, required=True)
        if payload is not None and not isinstance(payload, dict):
            raise TypeError("payload must be an object")
        payload_obj = payload or {}
        payload_json = _json(payload_obj)
        if len(payload_json.encode("utf-8")) > 256 * 1024:
            raise ValueError("context payload exceeds 256 KiB")
        refs = self._normalize_evidence(evidence)
        confidence = self._confidence(confidence)
        supersedes = list(dict.fromkeys(str(item) for item in (supersedes or [])))
        if len(supersedes) > 100:
            raise ValueError("supersedes exceeds 100 references")

        replay = self.db.execute(
            "SELECT * FROM context_events WHERE run_id=? AND idempotency_key=?",
            (run_id, idempotency_key),
        ).fetchone()
        if replay is not None:
            same_request = (
                replay["owner"] == owner
                and replay["event_type"] == event_type
                and replay["subject"] == subject
                and replay["payload_json"] == payload_json
                and replay["evidence_json"] == _json(refs)
                and replay["confidence"] == confidence
                and replay["supersedes_json"] == _json(supersedes)
                and replay["task_id"] == task_id
                and replay["agent_id"] == agent_id
            )
            if not same_request:
                raise FileExistsError(
                    "idempotency key reused with a different context event"
                )
            data = self._event_info(replay)
            data["idempotent_replay"] = True
            return data
        seq = self._next_seq_locked(run_id)
        now = self.clock()
        event_id = "ctx-" + uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO context_events("
            "event_id,run_id,owner,seq,task_id,agent_id,event_type,subject,payload_json,"
            "evidence_json,confidence,supersedes_json,idempotency_key,created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, run_id, owner, seq, task_id, agent_id, event_type, subject,
                payload_json, _json(refs), confidence, _json(supersedes),
                idempotency_key, now,
            ),
        )
        row = self.db.execute(
            "SELECT * FROM context_events WHERE event_id=?", (event_id,)
        ).fetchone()
        data = self._event_info(row)
        data["idempotent_replay"] = False
        return data

    def publish(
        self,
        run_id: str,
        owner: str,
        *,
        event_type: str,
        subject: str,
        payload: dict[str, Any] | None = None,
        evidence: list[str] | None = None,
        confidence: float | None = None,
        supersedes: list[str] | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        event_type = str(event_type or "").strip().upper()
        if event_type not in EVENT_TYPES:
            raise ValueError("agents may publish only typed knowledge events")
        key = _bounded_text("idempotency_key", idempotency_key, maximum=128, required=True)
        with self.lock:
            result = self._publish_locked(
                run_id, owner,
                event_type=event_type,
                subject=subject,
                payload=payload,
                evidence=evidence,
                confidence=confidence,
                supersedes=supersedes,
                task_id=task_id,
                agent_id=agent_id,
                idempotency_key=key,
            )
            self.db.commit()
        self._fanout(result)
        return result

    def subscribe(
        self,
        run_id: str,
        owner: str,
        consumer_id: str,
        *,
        types: list[str] | None = None,
        subject_prefixes: list[str] | None = None,
    ) -> dict[str, Any]:
        consumer = _bounded_text("consumer_id", consumer_id, maximum=128, required=True)
        normalized_types = self._normalize_types(types, allow_system=True)
        prefixes = self._normalize_prefixes(subject_prefixes)
        now = self.clock()
        with self.lock:
            self.db.execute(
                "INSERT INTO context_subscriptions("
                "run_id,owner,consumer_id,types_json,subject_prefixes_json,updated_at"
                ") VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(run_id,consumer_id) DO UPDATE SET "
                "owner=excluded.owner,types_json=excluded.types_json,"
                "subject_prefixes_json=excluded.subject_prefixes_json,"
                "updated_at=excluded.updated_at",
                (run_id, owner, consumer, _json(normalized_types), _json(prefixes), now),
            )
            self.db.execute(
                "INSERT OR IGNORE INTO context_cursors(run_id,owner,consumer_id,seq,updated_at) "
                "VALUES(?,?,?,?,?)",
                (run_id, owner, consumer, 0, now),
            )
            self.db.commit()
        return {
            "run_id": run_id,
            "consumer_id": consumer,
            "types": normalized_types,
            "subject_prefixes": prefixes,
        }

    def _subscription_locked(
        self, run_id: str, owner: str, consumer_id: str
    ) -> tuple[list[str], list[str]]:
        row = self.db.execute(
            "SELECT * FROM context_subscriptions "
            "WHERE run_id=? AND owner=? AND consumer_id=?",
            (run_id, owner, consumer_id),
        ).fetchone()
        if row is None:
            return [], []
        return (
            _load(row["types_json"], []),
            _load(row["subject_prefixes_json"], []),
        )

    def read_delta(
        self,
        run_id: str,
        owner: str,
        *,
        consumer_id: str | None = None,
        after_seq: int | None = None,
        types: list[str] | None = None,
        subject_prefixes: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        if not 1 <= int(limit) <= 500:
            raise ValueError("limit must be between 1 and 500")
        requested_types = self._normalize_types(types, allow_system=True)
        requested_prefixes = self._normalize_prefixes(subject_prefixes)
        with self.lock:
            base_seq = int(after_seq or 0)
            stored_types: list[str] = []
            stored_prefixes: list[str] = []
            if consumer_id:
                consumer = _bounded_text("consumer_id", consumer_id, maximum=128, required=True)
                if after_seq is None:
                    cursor = self.db.execute(
                        "SELECT seq FROM context_cursors "
                        "WHERE run_id=? AND owner=? AND consumer_id=?",
                        (run_id, owner, consumer),
                    ).fetchone()
                    base_seq = int(cursor["seq"]) if cursor else 0
                stored_types, stored_prefixes = self._subscription_locked(
                    run_id, owner, consumer
                )
            effective_types = requested_types or stored_types
            effective_prefixes = requested_prefixes or stored_prefixes

            params: list[Any] = [run_id, owner, base_seq]
            sql = (
                "SELECT * FROM context_events "
                "WHERE run_id=? AND owner=? AND seq>?"
            )
            if effective_types:
                placeholders = ",".join("?" for _ in effective_types)
                sql += f" AND event_type IN ({placeholders})"
                params.extend(effective_types)
            if effective_prefixes:
                clauses = []
                for prefix in effective_prefixes:
                    clauses.append("substr(subject,1,?)=?")
                    params.extend([len(prefix), prefix])
                sql += " AND (" + " OR ".join(clauses) + ")"
            sql += " ORDER BY seq ASC LIMIT ?"
            params.append(int(limit))
            rows = self.db.execute(sql, tuple(params)).fetchall()
            items = [self._event_info(row) for row in rows]

            last_seq = items[-1]["seq"] if items else base_seq
            return {
                "run_id": run_id,
                "consumer_id": consumer_id,
                "after_seq": base_seq,
                "items": items,
                "last_seq": last_seq,
                "filters": {
                    "types": effective_types,
                    "subject_prefixes": effective_prefixes,
                },
            }

    def acknowledge(
        self,
        run_id: str,
        owner: str,
        consumer_id: str,
        seq: int,
    ) -> dict[str, Any]:
        consumer = _bounded_text("consumer_id", consumer_id, maximum=128, required=True)
        target = int(seq)
        if target < 0:
            raise ValueError("seq must be non-negative")
        with self.lock:
            max_row = self.db.execute(
                "SELECT COALESCE(MAX(seq),0) AS seq FROM context_events "
                "WHERE run_id=? AND owner=?",
                (run_id, owner),
            ).fetchone()
            maximum = int(max_row["seq"])
            if target > maximum:
                raise ValueError("cannot acknowledge beyond the current context sequence")
            current = self.db.execute(
                "SELECT seq FROM context_cursors WHERE run_id=? AND owner=? AND consumer_id=?",
                (run_id, owner, consumer),
            ).fetchone()
            current_seq = int(current["seq"]) if current else 0
            if target < current_seq:
                raise ValueError("context cursor cannot move backwards")
            now = self.clock()
            self.db.execute(
                "INSERT INTO context_cursors(run_id,owner,consumer_id,seq,updated_at) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(run_id,consumer_id) DO UPDATE SET "
                "owner=excluded.owner,seq=excluded.seq,updated_at=excluded.updated_at",
                (run_id, owner, consumer, target, now),
            )
            self.db.commit()
            return {
                "run_id": run_id,
                "consumer_id": consumer,
                "seq": target,
                "previous_seq": current_seq,
            }

    def snapshot(
        self,
        run_id: str,
        owner: str,
        *,
        types: list[str] | None = None,
        subject_prefixes: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        normalized_types = self._normalize_types(types, allow_system=True)
        prefixes = self._normalize_prefixes(subject_prefixes)
        bounded_limit = max(1, min(int(limit), 200))

        def where_clause(alias: str = "") -> tuple[str, list[Any]]:
            prefix = f"{alias}." if alias else ""
            sql = f"{prefix}run_id=? AND {prefix}owner=?"
            params: list[Any] = [run_id, owner]
            if normalized_types:
                placeholders = ",".join("?" for _ in normalized_types)
                sql += f" AND {prefix}event_type IN ({placeholders})"
                params.extend(normalized_types)
            if prefixes:
                clauses = []
                for item in prefixes:
                    clauses.append(f"substr({prefix}subject,1,?)=?")
                    params.extend([len(item), item])
                sql += " AND (" + " OR ".join(clauses) + ")"
            return sql, params

        with self.lock:
            where, params = where_clause()
            counts_rows = self.db.execute(
                f"SELECT event_type,COUNT(*) AS count FROM context_events "
                f"WHERE {where} GROUP BY event_type",
                tuple(params),
            ).fetchall()
            counts = {
                str(row["event_type"]): int(row["count"])
                for row in counts_rows
            }

            ranked_where, ranked_params = where_clause("e")
            rows = self.db.execute(
                "SELECT * FROM ("
                "SELECT e.*,ROW_NUMBER() OVER (PARTITION BY e.subject ORDER BY e.seq DESC) AS rn "
                "FROM context_events e WHERE " + ranked_where +
                ") WHERE rn=1 ORDER BY seq DESC LIMIT ?",
                tuple(ranked_params + [bounded_limit]),
            ).fetchall()
            last_row = self.db.execute(
                f"SELECT COALESCE(MAX(seq),0) AS seq FROM context_events WHERE {where}",
                tuple(params),
            ).fetchone()
            return {
                "run_id": run_id,
                "latest_by_subject": [self._event_info(row) for row in rows],
                "counts": counts,
                "last_seq": int(last_row["seq"]),
            }

    def send_message(
        self,
        run_id: str,
        owner: str,
        *,
        from_agent_id: str,
        to_agent_id: str,
        body: str,
        idempotency_key: str,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        sender = _bounded_text("from_agent_id", from_agent_id, maximum=128, required=True)
        recipient = _bounded_text("to_agent_id", to_agent_id, maximum=128, required=True)
        body = _bounded_text("body", body, maximum=12000, required=True)
        key = _bounded_text("idempotency_key", idempotency_key, maximum=128, required=True)
        if reply_to is not None:
            reply_to = _bounded_text("reply_to", reply_to, maximum=128, required=True)
        with self.lock:
            result = self._publish_locked(
                run_id,
                owner,
                event_type="MESSAGE",
                subject=f"message.{recipient}",
                payload={
                    "from_agent_id": sender,
                    "to_agent_id": recipient,
                    "body": body,
                    "reply_to": reply_to,
                },
                evidence=[],
                confidence=None,
                supersedes=[],
                task_id=None,
                agent_id=sender,
                idempotency_key=key,
            )
            self.db.commit()
        self._fanout(result)
        return result

    def read_messages(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str,
        after_seq: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        agent = _bounded_text("agent_id", agent_id, maximum=128, required=True)
        delta = self.read_delta(
            run_id,
            owner,
            after_seq=after_seq,
            types=["MESSAGE"],
            limit=min(500, max(int(limit) * 4, int(limit))),
        )
        items = [
            item
            for item in delta["items"]
            if item.get("payload", {}).get("to_agent_id") in {agent, "*"}
        ][: max(1, min(int(limit), 500))]
        return {
            "run_id": run_id,
            "agent_id": agent,
            "after_seq": int(after_seq or 0),
            "items": items,
            "last_seq": items[-1]["seq"] if items else int(after_seq or 0),
        }

    def _claim_info(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "claim_id": row["claim_id"],
            "run_id": row["run_id"],
            "task_id": row["task_id"],
            "agent_id": row["agent_id"],
            "subject": row["subject"],
            "statement": row["statement"],
            "evidence": _load(row["evidence_json"], []),
            "confidence": row["confidence"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def propose_claim(
        self,
        run_id: str,
        owner: str,
        *,
        subject: str,
        statement: str,
        evidence: list[str],
        idempotency_key: str,
        confidence: float | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        key = _bounded_text("idempotency_key", idempotency_key, maximum=128, required=True)
        subject = _bounded_text("subject", subject, maximum=500, required=True)
        statement = _bounded_text("statement", statement, maximum=12000, required=True)
        refs = self._normalize_evidence(evidence)
        if not refs:
            raise ValueError("claim evidence is required")
        confidence = self._confidence(confidence)
        with self.lock:
            replay = self.db.execute(
                "SELECT * FROM context_claims WHERE run_id=? AND idempotency_key=?",
                (run_id, key),
            ).fetchone()
            if replay is not None:
                same_request = (
                    replay["owner"] == owner
                    and replay["subject"] == subject
                    and replay["statement"] == statement
                    and replay["evidence_json"] == _json(refs)
                    and replay["confidence"] == confidence
                    and replay["task_id"] == task_id
                    and replay["agent_id"] == agent_id
                )
                if not same_request:
                    raise FileExistsError(
                        "idempotency key reused with a different claim"
                    )
                data = self._claim_info(replay)
                data["idempotent_replay"] = True
                return data

            now = self.clock()
            claim_id = "claim-" + uuid.uuid4().hex
            self.db.execute(
                "INSERT INTO context_claims("
                "claim_id,run_id,owner,task_id,agent_id,subject,statement,evidence_json,"
                "confidence,status,idempotency_key,created_at,updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    claim_id, run_id, owner, task_id, agent_id, subject, statement,
                    _json(refs), confidence, "PROPOSED", key, now, now,
                ),
            )
            event = self._publish_locked(
                run_id, owner,
                event_type="CLAIM",
                subject=subject,
                payload={"claim_id": claim_id, "statement": statement, "status": "PROPOSED"},
                evidence=refs,
                confidence=confidence,
                supersedes=None,
                task_id=task_id,
                agent_id=agent_id,
                idempotency_key=f"claim-event:{claim_id}",
            )
            self.db.commit()
            row = self.db.execute(
                "SELECT * FROM context_claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            data = self._claim_info(row)
            data["event_id"] = event["event_id"]
            data["idempotent_replay"] = False
        self._fanout(event)
        return data

    def challenge_claim(
        self,
        claim_id: str,
        owner: str,
        *,
        reason: str,
        evidence: list[str] | None,
        idempotency_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        key = _bounded_text("idempotency_key", idempotency_key, maximum=128, required=True)
        reason = _bounded_text("reason", reason, maximum=12000, required=True)
        refs = self._normalize_evidence(evidence)
        with self.lock:
            claim = self.db.execute(
                "SELECT * FROM context_claims WHERE claim_id=? AND owner=?",
                (claim_id, owner),
            ).fetchone()
            if claim is None:
                raise FileNotFoundError("claim not found")
            if claim["status"] in {"VERIFIED", "REJECTED"}:
                raise ValueError("resolved claim cannot be challenged")
            replay = self.db.execute(
                "SELECT * FROM context_claim_challenges "
                "WHERE run_id=? AND idempotency_key=?",
                (claim["run_id"], key),
            ).fetchone()
            if replay is not None:
                same_request = (
                    replay["owner"] == owner
                    and replay["claim_id"] == claim_id
                    and replay["agent_id"] == agent_id
                    and replay["reason"] == reason
                    and replay["evidence_json"] == _json(refs)
                )
                if not same_request:
                    raise FileExistsError(
                        "idempotency key reused with a different claim challenge"
                    )
                return {
                    "challenge_id": replay["challenge_id"],
                    "claim": self._claim_info(claim),
                    "idempotent_replay": True,
                }
            now = self.clock()
            challenge_id = "challenge-" + uuid.uuid4().hex
            self.db.execute(
                "INSERT INTO context_claim_challenges("
                "challenge_id,claim_id,run_id,owner,agent_id,reason,evidence_json,"
                "idempotency_key,created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    challenge_id, claim_id, claim["run_id"], owner, agent_id,
                    reason, _json(refs), key, now,
                ),
            )
            self.db.execute(
                "UPDATE context_claims SET status='CHALLENGED',updated_at=? WHERE claim_id=?",
                (now, claim_id),
            )
            event = self._publish_locked(
                claim["run_id"], owner,
                event_type="CHALLENGE",
                subject=claim["subject"],
                payload={
                    "claim_id": claim_id,
                    "challenge_id": challenge_id,
                    "reason": reason,
                    "status": "CHALLENGED",
                },
                evidence=refs,
                confidence=None,
                supersedes=None,
                task_id=claim["task_id"],
                agent_id=agent_id,
                idempotency_key=f"challenge-event:{challenge_id}",
            )
            self.db.commit()
            updated = self.db.execute(
                "SELECT * FROM context_claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            result = {
                "challenge_id": challenge_id,
                "claim": self._claim_info(updated),
                "event_id": event["event_id"],
                "idempotent_replay": False,
            }
        self._fanout(event)
        return result

    def claim_info(self, claim_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM context_claims WHERE claim_id=? AND owner=?",
                (claim_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("claim not found")
            challenges = self.db.execute(
                "SELECT challenge_id,agent_id,reason,evidence_json,created_at "
                "FROM context_claim_challenges WHERE claim_id=? ORDER BY created_at ASC",
                (claim_id,),
            ).fetchall()
            resolutions = self.db.execute(
                "SELECT resolution_id,verdict,authority,reason,evidence_json,created_at "
                "FROM context_claim_resolutions WHERE claim_id=? ORDER BY created_at ASC",
                (claim_id,),
            ).fetchall()
            data = self._claim_info(row)
            data["challenges"] = [
                {
                    "challenge_id": item["challenge_id"],
                    "agent_id": item["agent_id"],
                    "reason": item["reason"],
                    "evidence": _load(item["evidence_json"], []),
                    "created_at": item["created_at"],
                }
                for item in challenges
            ]
            data["resolutions"] = [
                {
                    "resolution_id": item["resolution_id"],
                    "verdict": item["verdict"],
                    "authority": item["authority"],
                    "reason": item["reason"],
                    "evidence": _load(item["evidence_json"], []),
                    "created_at": item["created_at"],
                }
                for item in resolutions
            ]
            return data

    def resolve_claim(
        self,
        claim_id: str,
        owner: str,
        *,
        verdict: str,
        authority: str,
        reason: str,
        evidence: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        verdict = str(verdict or "").strip().upper()
        if verdict not in {"VERIFIED", "REJECTED"}:
            raise ValueError("claim verdict must be VERIFIED or REJECTED")
        authority = str(authority or "").strip().lower()
        if authority not in CLAIM_RESOLUTION_AUTHORITIES:
            raise PermissionError("claim resolution requires Control Plane authority")
        reason = _bounded_text("reason", reason, maximum=12000, required=True)
        refs = self._normalize_evidence(evidence)
        if not refs:
            raise ValueError("claim resolution evidence is required")
        key = _bounded_text("idempotency_key", idempotency_key, maximum=128, required=True)

        with self.lock:
            claim = self.db.execute(
                "SELECT * FROM context_claims WHERE claim_id=? AND owner=?",
                (claim_id, owner),
            ).fetchone()
            if claim is None:
                raise FileNotFoundError("claim not found")

            replay = self.db.execute(
                "SELECT * FROM context_claim_resolutions "
                "WHERE run_id=? AND idempotency_key=?",
                (claim["run_id"], key),
            ).fetchone()
            if replay is not None:
                same_request = (
                    replay["owner"] == owner
                    and replay["claim_id"] == claim_id
                    and replay["verdict"] == verdict
                    and replay["authority"] == authority
                    and replay["reason"] == reason
                    and replay["evidence_json"] == _json(refs)
                )
                if not same_request:
                    raise FileExistsError(
                        "idempotency key reused with a different claim resolution"
                    )
                return {
                    "resolution_id": replay["resolution_id"],
                    "claim": self._claim_info(claim),
                    "idempotent_replay": True,
                }

            if claim["status"] in {"VERIFIED", "REJECTED"}:
                raise ValueError("claim is already resolved")

            now = self.clock()
            resolution_id = "resolution-" + uuid.uuid4().hex
            self.db.execute(
                "INSERT INTO context_claim_resolutions("
                "resolution_id,claim_id,run_id,owner,verdict,authority,reason,"
                "evidence_json,idempotency_key,created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    resolution_id, claim_id, claim["run_id"], owner, verdict,
                    authority, reason, _json(refs), key, now,
                ),
            )
            self.db.execute(
                "UPDATE context_claims SET status=?,updated_at=? WHERE claim_id=?",
                (verdict, now, claim_id),
            )
            event = self._publish_locked(
                claim["run_id"], owner,
                event_type="CLAIM_RESOLUTION",
                subject=claim["subject"],
                payload={
                    "claim_id": claim_id,
                    "resolution_id": resolution_id,
                    "verdict": verdict,
                    "authority": authority,
                    "reason": reason,
                },
                evidence=refs,
                confidence=None,
                supersedes=None,
                task_id=claim["task_id"],
                agent_id=None,
                idempotency_key=f"claim-resolution-event:{resolution_id}",
            )
            self.db.commit()
            updated = self.db.execute(
                "SELECT * FROM context_claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            result = {
                "resolution_id": resolution_id,
                "claim": self._claim_info(updated),
                "event_id": event["event_id"],
                "idempotent_replay": False,
            }
        self._fanout(event)
        return result
