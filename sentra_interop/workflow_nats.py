"""NATS JetStream event ingestion as subordinate workflow signals.

NOT a second authority and NOT an execution callback. Broker delivery only
populates a local dedupe projection and builds an exact ``workflow:signal``
intent for the host to admit through its normal central operation journal.
The host remains the only committer; this bridge never reserves Operations,
Runs, WorkItems, Grants or leases.

Transport is injected: the host supplies a ``pull_events`` callable bound to
its real ``sentra_runtime/nats_jetstream.py`` consumer (or any equivalent
scoped inbox). When no transport is configured every pull fails explicitly
instead of simulating delivery.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .workflow_contracts import digest, ident
from .workflow_checkpoint import namespace

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
EVENT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


def _canonical(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     allow_nan=False, separators=(",", ":"))
    if len(raw.encode()) > 1_000_000:
        raise ValueError("NATS workflow event exceeds bound")
    return raw


class NATSTransportMissing(RuntimeError):
    pass


class NATSWorkflowSignalBridge:
    """Map scoped JetStream notifications to ``workflow:signal`` intents.

    ``pull_events`` is ``async (max_messages) -> list[dict]`` where each dict
    carries ``event_key``, ``signal_name``, ``payload`` (JSON mapping) and
    optional ``workflow_id``/``namespace`` hints. Delivery here stages a
    claim; the host admits the signal through ``CheckpointedWorkflowWorker``
    with its own central operation. Duplicate ``event_key`` reuses the staged
    claim and never builds a second signal identity.
    """

    def __init__(self, database: str, *, workspace: str,
                 workflow_id: str, default_namespace: str = "",
                 pull_events: Callable | None = None,
                 clock=time.time, control=None) -> None:
        ident(workflow_id)
        namespace(default_namespace)
        self.control = control
        root, target = Path(workspace).resolve(), Path(database).resolve()
        if target == root or not target.is_relative_to(root):
            raise ValueError("NATS workflow projection outside workspace")
        from .workflow_storage import projection_path
        projection_path(database, workspace, control=control)
        self.database, self.workspace = str(target), str(root)
        self.workflow_id, self.default_namespace = workflow_id, default_namespace
        self.pull_events, self.clock = pull_events, clock
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS nats_workflow_events(
                event_key TEXT PRIMARY KEY, signal_name TEXT NOT NULL,
                signal_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                protected_payload TEXT NOT NULL, workflow_id TEXT NOT NULL,
                namespace TEXT NOT NULL, received REAL NOT NULL,
                admitted_operation_id TEXT)""")

    @contextmanager
    def _db(self):
        from .workflow_storage import projection_db
        with projection_db(self.database, control=self.control) as conn:
            yield conn

    def _encode(self, payload: dict) -> str:
        from sentra_core.conversations import _encode
        return _encode(payload)

    def stage(self, *, event_key: str, signal_name: str,
              payload: dict, workflow_id: str | None = None,
              ns: str | None = None) -> dict:
        """Stage one broker event as a signal claim (idempotent)."""
        if not isinstance(event_key, str) or not EVENT_KEY.fullmatch(event_key):
            raise ValueError("bounded NATS event key required")
        ident(signal_name)
        if not isinstance(payload, dict):
            raise ValueError("NATS signal payload must be a JSON mapping")
        _canonical(payload)
        target_workflow = workflow_id or self.workflow_id
        target_ns = self.default_namespace if ns is None else ns
        ident(target_workflow)
        namespace(target_ns)
        if target_workflow != self.workflow_id or target_ns != self.default_namespace:
            raise PermissionError("broker cannot select an unconfigured workflow namespace")
        payload_sha = digest(payload)
        signal_id = "nats-" + hashlib.sha256(
            f"{target_workflow}|{target_ns}|{event_key}".encode()).hexdigest()[:32]
        protected = self._encode(payload)
        now = self.clock()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM nats_workflow_events WHERE event_key=?",
                             (event_key,)).fetchone()
            if old is not None:
                if (old["signal_name"], old["payload_sha256"], old["workflow_id"],
                        old["namespace"]) != (signal_name, payload_sha, target_workflow, target_ns):
                    raise ValueError("NATS event key bound to a different signal")
                return self._intent(dict(old))
            db.execute("INSERT INTO nats_workflow_events VALUES(?,?,?,?,?,?,?,?,NULL)",
                       (event_key, signal_name, signal_id, payload_sha, protected,
                        target_workflow, target_ns, now))
            row = db.execute("SELECT * FROM nats_workflow_events WHERE event_key=?",
                             (event_key,)).fetchone()
            return self._intent(dict(row))

    def _intent(self, row: dict) -> dict:
        return {"capability_id": "workflow:signal",
                "arguments": {"workflow_id": row["workflow_id"],
                              "namespace": row["namespace"],
                              "name": row["signal_name"],
                              "signal_id": row["signal_id"],
                              "payload_sha256": row["payload_sha256"]},
                "event_key": row["event_key"],
                "already_admitted": row["admitted_operation_id"] is not None}

    def mark_admitted(self, event_key: str, operation_id: str) -> None:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("central operation identity required")
        with self._db() as db:
            updated = db.execute(
                "UPDATE nats_workflow_events SET admitted_operation_id=? "
                "WHERE event_key=? AND (admitted_operation_id IS NULL "
                "OR admitted_operation_id=?)",
                (operation_id, event_key, operation_id)).rowcount
            if updated != 1:
                raise ValueError("unknown NATS event key or conflicting admission")

    def pending(self, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("pending limit must be 1..1000")
        with self._db() as db:
            rows = db.execute("SELECT * FROM nats_workflow_events "
                              "WHERE admitted_operation_id IS NULL "
                              "ORDER BY received LIMIT ?", (limit,)).fetchall()
        return [self._intent(dict(row)) for row in rows]

    async def drain(self, *, max_messages: int = 16) -> list[dict]:
        """Pull from the injected transport and stage each event.

        Fails explicitly when no real transport is configured. Transport
        errors propagate; nothing is marked delivered on ambiguity.
        """
        if self.pull_events is None:
            raise NATSTransportMissing(
                "no NATS JetStream consumer configured; configure a scoped "
                "TLS consumer before draining workflow events")
        if type(max_messages) is not int or not 1 <= max_messages <= 1000:
            raise ValueError("drain bound must be 1..1000")
        events = await self.pull_events(max_messages)
        if not isinstance(events, list):
            raise ValueError("NATS transport returned an invalid batch")
        staged = []
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("invalid NATS event envelope")
            staged.append(self.stage(
                event_key=event["event_key"], signal_name=event["signal_name"],
                payload=event["payload"], workflow_id=event.get("workflow_id"),
                ns=event.get("namespace", None)))
        return staged
