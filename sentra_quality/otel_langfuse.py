"""Selo: OpenTelemetry + Langfuse export over sanitized telemetry only.

- Source of records is the durable EventJournal (sentra_core.telemetry).
- Only SafeTelemetryEvent allowlist (name/state + operation digest) is ever
  exported. Prompts, contents, arguments, tokens and audit payloads never
  leave the host through this path.
- OTLP endpoint must be explicit HTTP loopback /v1/traces (LocalOtlpExporter).
- Langfuse export is explicit opt-in HTTPS with public/secret keys from a host
  credential provider; failures are reported, never raised into central paths.
- Bounded queue with dedupe, retention and counters. Sink failure never
  changes central operation results.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
import urllib.request


_ALLOWED_NAMES = frozenset({"sentra.operation", "sentra.policy",
                            "sentra.machine", "sentra.collab"})
_ALLOWED_STATES = frozenset({"ACCEPTED", "RUNNING", "SUCCEEDED",
                             "FAILED", "CANCELLED", "UNCERTAIN"})


@dataclass(frozen=True, slots=True)
class LangfuseConfig:
    base_url: str
    timeout_s: float = 5.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ValueError("Langfuse base_url must be explicit https without credentials")
        if not 0 < float(self.timeout_s) <= 30:
            raise ValueError("invalid Langfuse timeout")


class SeloTelemetryExporter:
    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        root = Path(state_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "selo_telemetry.sqlite3"
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS selo_telemetry_queue(
                    owner TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    operation_sha256 TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    created REAL NOT NULL,
                    attempts INTEGER NOT NULL,
                    PRIMARY KEY(owner, event_key)
                );
                CREATE TABLE IF NOT EXISTS selo_telemetry_stats(
                    owner TEXT PRIMARY KEY,
                    enqueued INTEGER NOT NULL DEFAULT 0,
                    delivered_otlp INTEGER NOT NULL DEFAULT 0,
                    delivered_langfuse INTEGER NOT NULL DEFAULT 0,
                    dropped INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0
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

    def _stat(self, db, owner: str, column: str, count: int = 1) -> None:
        if column not in {"enqueued", "delivered_otlp", "delivered_langfuse",
                          "dropped", "errors"}:
            raise ValueError("unknown telemetry counter")
        db.execute("INSERT OR IGNORE INTO selo_telemetry_stats(owner) VALUES(?)", (owner,))
        db.execute(f"UPDATE selo_telemetry_stats SET {column}={column}+? WHERE owner=?",
                   (count, owner))

    @staticmethod
    def sanitize_event(name: str, state: str, operation_id: str) -> dict[str, str]:
        if name not in _ALLOWED_NAMES:
            raise ValueError("unsupported telemetry event name")
        if state not in _ALLOWED_STATES:
            raise ValueError("unsupported telemetry state")
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 256:
            raise ValueError("invalid operation identity")
        operation_sha = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        return {"name": name, "state": state, "operation_sha256": operation_sha}

    def enqueue(self, owner: str, *, name: str, state: str, operation_id: str,
                max_pending: int = 2000) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("owner is required")
        if type(max_pending) is not int or not 1 <= max_pending <= 10000:
            raise ValueError("invalid queue bound")
        event = self.sanitize_event(name, state, operation_id)
        event_key = hashlib.sha256(
            (name + "\0" + state + "\0" + event["operation_sha256"]).encode()
        ).hexdigest()
        trace_id = hashlib.sha256((owner + "\0" + operation_id).encode()).hexdigest()[:32]
        span_id = event_key[:16]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM selo_telemetry_queue WHERE owner=? AND event_key=?",
                          (owner, event_key)).fetchone():
                return {"deduped": True, "event_key": event_key}
            count = db.execute("SELECT COUNT(*) FROM selo_telemetry_queue WHERE owner=?",
                               (owner,)).fetchone()[0]
            if count >= max_pending:
                self._stat(db, owner, "dropped")
                return {"dropped": True, "reason": "queue full"}
            db.execute(
                "INSERT INTO selo_telemetry_queue VALUES(?,?,?,?,?,?,?,?,?)",
                (owner, event_key, name, state, event["operation_sha256"],
                 trace_id, span_id, self.clock(), 0),
            )
            self._stat(db, owner, "enqueued")
        return {"enqueued": True, "event_key": event_key, "trace_id": trace_id}

    def pending(self, owner: str, *, limit: int = 64) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM selo_telemetry_queue WHERE owner=? ORDER BY created LIMIT ?",
                (owner, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def _complete(self, owner: str, keys: list[str], *, delivered: str) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for key in keys:
                db.execute("DELETE FROM selo_telemetry_queue WHERE owner=? AND event_key=?",
                           (owner, key))
            if keys:
                self._stat(db, owner, delivered, len(keys))

    def _fail(self, owner: str, keys: list[str], *, max_attempts: int = 6) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for key in keys:
                row = db.execute(
                    "SELECT attempts FROM selo_telemetry_queue WHERE owner=? AND event_key=?",
                    (owner, key),
                ).fetchone()
                if row is None:
                    continue
                if int(row["attempts"]) + 1 >= max_attempts:
                    db.execute("DELETE FROM selo_telemetry_queue WHERE owner=? AND event_key=?",
                               (owner, key))
                    self._stat(db, owner, "dropped")
                else:
                    db.execute("UPDATE selo_telemetry_queue SET attempts=attempts+1 "
                               "WHERE owner=? AND event_key=?", (owner, key))
            self._stat(db, owner, "errors")

    @staticmethod
    def to_otlp_document(row: dict[str, Any], *, service: str = "sentra-os") -> dict[str, Any]:
        now_ns = str(time.time_ns())
        return {
            "resourceSpans": [{
                "resource": {"attributes": [{"key": "service.name",
                                             "value": {"stringValue": service}}]},
                "scopeSpans": [{
                    "scope": {"name": "sentra.runtime"},
                    "spans": [{
                        "traceId": row["trace_id"],
                        "spanId": row["span_id"],
                        "name": row["name"],
                        "startTimeUnixNano": now_ns,
                        "endTimeUnixNano": now_ns,
                        "attributes": [
                            {"key": "sentra.operation_sha256",
                             "value": {"stringValue": row["operation_sha256"]}},
                            {"key": "sentra.operation_state",
                             "value": {"stringValue": row["state"]}},
                        ],
                    }],
                }],
            }]
        }

    def flush_otlp(self, owner: str, *, endpoint: str, limit: int = 32) -> dict[str, Any]:
        """Best-effort OTLP push to explicit loopback collector. Never raises."""
        try:
            from sentra_runtime.otlp_sink import LocalOtlpExporter, SafeTelemetryEvent
        except Exception as exc:
            return {"delivered": 0, "error": "telemetry provider unavailable: " + str(exc)[:150]}
        try:
            exporter = LocalOtlpExporter(endpoint, timeout_s=2)
        except Exception as exc:
            return {"delivered": 0, "error": str(exc)[:300]}
        rows = self.pending(owner, limit=limit)
        delivered: list[str] = []
        for row in rows:
            try:
                # Single-hash binding: the queue already stores operation_sha256.
                # Send exactly one allowlisted OTLP document per event.
                document = self.to_otlp_document(row)
                payload = json.dumps(document, separators=(",", ":")).encode()
                exporter._send(payload)
                delivered.append(row["event_key"])
            except Exception:
                continue
        if delivered:
            self._complete(owner, delivered, delivered="delivered_otlp")
        if len(delivered) != len(rows):
            remaining = [r["event_key"] for r in rows if r["event_key"] not in set(delivered)]
            if remaining:
                self._fail(owner, remaining)
        return {"delivered": len(delivered), "attempted": len(rows)}

    def flush_langfuse(self, owner: str, *, config: LangfuseConfig,
                       credential_provider, limit: int = 32) -> dict[str, Any]:
        """Best-effort Langfuse ingestion of sanitized spans. Never raises."""
        rows = self.pending(owner, limit=limit)
        if not rows:
            return {"delivered": 0, "attempted": 0}
        try:
            credentials = credential_provider("langfuse")
            if hasattr(credentials, "__await__"):
                return {"delivered": 0, "error": "async credential provider not supported here"}
        except Exception as exc:
            self._fail(owner, [r["event_key"] for r in rows])
            return {"delivered": 0, "error": "credential unavailable"}
        if not isinstance(credentials, dict) or set(credentials) != {"public_key", "secret_key"}:
            return {"delivered": 0, "error": "Langfuse public/secret key pair not configured"}
        try:
            from sentra_runtime.effect_boundary import current_effect_context
            from .provider_clients import ScopedJSONHTTP, send_otlp
            context = current_effect_context.get()
            if context is None or context.receipt.owner != owner:
                return {"delivered": 0, "error": "central owner-scoped effect context required"}
            http = ScopedJSONHTTP(base=config.base_url, credential=credentials, auth="basic",
                                  timeout_s=config.timeout_s, checkpoint=context.checkpoint)
            document = {"resourceSpans": [span for row in rows for span in self.to_otlp_document(row)["resourceSpans"]]}
            send_otlp(http, "/api/public/otel/v1/traces", document)
        except Exception:
            self._fail(owner, [r["event_key"] for r in rows])
            return {"delivered": 0, "error": "langfuse unavailable or response uncertain",
                    "completion_uncertain": True, "operation_results_changed": False}
        keys = [r["event_key"] for r in rows]
        self._complete(owner, keys, delivered="delivered_langfuse")
        return {"delivered": len(keys), "attempted": len(rows)}

    def stats(self, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM selo_telemetry_stats WHERE owner=?",
                             (owner,)).fetchone()
            pending = db.execute("SELECT COUNT(*) FROM selo_telemetry_queue WHERE owner=?",
                                 (owner,)).fetchone()[0]
        counters = dict(row) if row else {}
        counters.pop("owner", None)
        return {**counters, "pending": pending, "diagnostics_only": True,
                "audit_complete": False}


@dataclass(frozen=True, slots=True)
class OTelPipelineConfig:
    """Batch/size/time + bounds mirroring batchprocessor/queuebatch semantics.

    - send_batch_size: events per batch before flush.
    - send_batch_max_size: split bound; 0 means no split.
    - timeout_s: flush interval even when the batch is incomplete.
    - cardinality_limit: distinct (name, state) series kept; overflows drop.
    - memory_limit_bytes: queued payload estimate cap; overflows drop.
    - max_pending / retention_s / max_attempts: queue bounds and loss policy.
    """

    send_batch_size: int = 32
    send_batch_max_size: int = 0
    timeout_s: float = 1.0
    cardinality_limit: int = 64
    memory_limit_bytes: int = 4 * 1024 * 1024
    max_pending: int = 2000
    retention_s: int = 3600
    max_attempts: int = 6

    def __post_init__(self) -> None:
        if type(self.send_batch_size) is not int or not 1 <= self.send_batch_size <= 512:
            raise ValueError("send_batch_size must be 1..512")
        if type(self.send_batch_max_size) is not int or not 0 <= self.send_batch_max_size <= 2048:
            raise ValueError("send_batch_max_size must be 0..2048")
        if self.send_batch_max_size and self.send_batch_max_size < self.send_batch_size:
            raise ValueError("send_batch_max_size must cover send_batch_size")
        if not 0.1 <= float(self.timeout_s) <= 60:
            raise ValueError("timeout_s must be 0.1..60")
        if type(self.cardinality_limit) is not int or not 1 <= self.cardinality_limit <= 1024:
            raise ValueError("cardinality_limit must be 1..1024")
        if type(self.memory_limit_bytes) is not int \
                or not 65536 <= self.memory_limit_bytes <= 256 * 1024 * 1024:
            raise ValueError("memory_limit_bytes out of bounds")
        if type(self.max_pending) is not int or not 1 <= self.max_pending <= 10000:
            raise ValueError("max_pending must be 1..10000")
        if type(self.retention_s) is not int or not 60 <= self.retention_s <= 86400:
            raise ValueError("retention_s must be 60..86400")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 20:
            raise ValueError("max_attempts must be 1..20")


class OTelPipeline:
    """Persistent batching queue with explicit loss accounting.

    Backed by the same SQLite file as SeloTelemetryExporter. Events stay
    allowlisted digests; redaction applies to diagnostic payloads only.
    Export failure never raises into central paths; every drop is counted
    with its reason and the snapshot always reports loss explicitly.
    """

    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        self.exporter = SeloTelemetryExporter(state_root, clock=clock)
        self.clock = clock
        with self.exporter._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS otel_pipeline_config(
                    owner TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS otel_pipeline_loss(
                    owner TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(owner, reason)
                );
                CREATE TABLE IF NOT EXISTS otel_pipeline_state(
                    owner TEXT PRIMARY KEY,
                    last_flush REAL NOT NULL DEFAULT 0
                );
                """
            )

    def configure(self, owner: str, config: OTelPipelineConfig) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner or not isinstance(config, OTelPipelineConfig):
            raise ValueError("owner and typed pipeline config required")
        document = json.dumps({
            "send_batch_size": config.send_batch_size,
            "send_batch_max_size": config.send_batch_max_size,
            "timeout_s": config.timeout_s,
            "cardinality_limit": config.cardinality_limit,
            "memory_limit_bytes": config.memory_limit_bytes,
            "max_pending": config.max_pending,
            "retention_s": config.retention_s,
            "max_attempts": config.max_attempts,
        }, separators=(",", ":"))
        with self.exporter._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO otel_pipeline_config VALUES(?,?,?) "
                "ON CONFLICT(owner) DO UPDATE SET config_json=excluded.config_json,"
                "updated_at=excluded.updated_at",
                (owner, document, self.clock()),
            )
        return {"owner": owner, "configured": True,
                "config": json.loads(document)}

    def config(self, owner: str) -> OTelPipelineConfig:
        with self.exporter._connect() as db:
            row = db.execute("SELECT config_json FROM otel_pipeline_config WHERE owner=?",
                             (owner,)).fetchone()
        if row is None:
            return OTelPipelineConfig()
        try:
            document = json.loads(row["config_json"])
            return OTelPipelineConfig(**document)
        except (ValueError, TypeError):
            return OTelPipelineConfig()

    def _loss(self, db, owner: str, reason: str, count: int = 1) -> None:
        db.execute("INSERT OR IGNORE INTO otel_pipeline_loss VALUES(?,?,0)",
                   (owner, reason))
        db.execute("UPDATE otel_pipeline_loss SET count=count+? WHERE owner=? AND reason=?",
                   (count, owner, reason))

    def enqueue(self, owner: str, *, name: str, state: str,
                operation_id: str) -> dict[str, Any]:
        """Enqueue with cardinality + memory-limiter + retention enforcement."""
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("owner is required")
        config = self.config(owner)
        pruned = self.prune_expired(owner)
        with self.exporter._connect() as db:
            series = db.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT name,state FROM selo_telemetry_queue "
                "WHERE owner=?)", (owner,),
            ).fetchone()[0]
            known = db.execute(
                "SELECT 1 FROM selo_telemetry_queue WHERE owner=? AND name=? AND state=? LIMIT 1",
                (owner, name, state),
            ).fetchone()
            if known is None and series >= config.cardinality_limit:
                db.execute("BEGIN IMMEDIATE")
                self._loss(db, owner, "cardinality")
                return {"dropped": True, "reason": "cardinality limit"}
            pending = db.execute("SELECT COUNT(*) FROM selo_telemetry_queue WHERE owner=?",
                                 (owner,)).fetchone()[0]
            # Payload estimate: one OTLP document per queued event (~512 B).
            if (pending + 1) * 512 > config.memory_limit_bytes:
                db.execute("BEGIN IMMEDIATE")
                self._loss(db, owner, "memory_limiter")
                return {"dropped": True, "reason": "memory limiter"}
        outcome = self.exporter.enqueue(owner, name=name, state=state,
                                        operation_id=operation_id,
                                        max_pending=config.max_pending)
        if outcome.get("dropped"):
            with self.exporter._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._loss(db, owner, "queue_full")
        return {**outcome, "expired_pruned": pruned}

    def prune_expired(self, owner: str) -> int:
        config = self.config(owner)
        cutoff = self.clock() - config.retention_s
        with self.exporter._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            expired = db.execute(
                "DELETE FROM selo_telemetry_queue WHERE owner=? AND created<?",
                (owner, cutoff),
            ).rowcount
            if expired:
                self._loss(db, owner, "retention", expired)
        return expired or 0

    def batch_plan(self, owner: str) -> dict[str, Any]:
        """Describe due batches without sending (size/time splitting)."""
        config = self.config(owner)
        rows = self.exporter.pending(owner, limit=config.max_pending)
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for row in rows:
            current.append(row)
            width = config.send_batch_max_size or config.send_batch_size
            if len(current) >= config.send_batch_size and len(current) >= width:
                batches.append(current)
                current = []
            elif len(current) >= config.send_batch_size and not config.send_batch_max_size:
                batches.append(current)
                current = []
        partial = current
        with self.exporter._connect() as db:
            state = db.execute("SELECT last_flush FROM otel_pipeline_state WHERE owner=?",
                               (owner,)).fetchone()
        last_flush = float(state["last_flush"]) if state else 0.0
        timeout_due = (self.clock() - last_flush) >= config.timeout_s
        return {"complete_batches": len(batches),
                "batched_events": sum(len(b) for b in batches),
                "partial_events": len(partial),
                "timeout_due": timeout_due,
                "pending": len(rows)}

    def mark_flushed(self, owner: str) -> None:
        with self.exporter._connect() as db:
            db.execute("INSERT INTO otel_pipeline_state VALUES(?,?) "
                       "ON CONFLICT(owner) DO UPDATE SET last_flush=excluded.last_flush",
                       (owner, self.clock()))

    def stats(self, owner: str) -> dict[str, Any]:
        base = self.exporter.stats(owner)
        with self.exporter._connect() as db:
            loss = db.execute("SELECT reason,count FROM otel_pipeline_loss WHERE owner=?",
                              (owner,)).fetchall()
        losses = {row["reason"]: row["count"] for row in loss}
        return {**base, "config": {
                    "send_batch_size": self.config(owner).send_batch_size,
                    "send_batch_max_size": self.config(owner).send_batch_max_size,
                    "timeout_s": self.config(owner).timeout_s,
                    "cardinality_limit": self.config(owner).cardinality_limit,
                    "memory_limit_bytes": self.config(owner).memory_limit_bytes,
                    "max_pending": self.config(owner).max_pending,
                    "retention_s": self.config(owner).retention_s,
                    "max_attempts": self.config(owner).max_attempts},
                "loss": losses,
                "loss_total": sum(losses.values())}

    @staticmethod
    def redact_diagnostic(payload: dict[str, Any]) -> dict[str, Any]:
        """Redact a diagnostic payload for snapshots/logs. OTLP path stays allowlist."""
        try:
            from sentra_core.telemetry import redact
            cleaned = redact(dict(payload))
            return cleaned if isinstance(cleaned, dict) else {"value": cleaned}
        except Exception:
            return {"unredactable": True}
