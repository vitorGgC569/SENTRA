"""Durable Run/Operation runtime for SENTRA.

This module is intentionally protocol-independent.  It provides the persistent
state that survives MCP/chat timeouts and lets another conversation resume work
without replaying side effects.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
RUN_STATES = {
    "CREATED", "RUNNING", "PAUSED", "RECOVERING", "BLOCKED",
    "SUCCEEDED", "FAILED", "CANCELLED",
}
OPERATION_STATES = {
    "QUEUED", "STARTING", "RUNNING", "WAITING_EXTERNAL",
    "SUCCEEDED", "FAILED", "UNCERTAIN", "CANCEL_REQUESTED", "CANCELLED",
}
AGENT_STATES = {
    "AVAILABLE", "ACTIVE", "WAITING", "SUSPECTED_STALL",
    "RECOVERING", "ORPHANED", "DEAD",
}
CHAT_STATES = {
    "READY", "GENERATING", "TOOL_WAIT", "PLATFORM_HOLD",
    "WAITING_USER", "IDLE", "DISCONNECTED",
}
TERMINAL_RUN_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}
TERMINAL_OPERATION_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}
READINESS_STATES = {
    "UNKNOWN", "PROCESS_STARTED", "PORT_LISTENING", "TRANSPORT_CONNECTED",
    "PLUGIN_HANDSHAKE", "CAPABILITY_NEGOTIATED", "SESSION_READY", "PRODUCT_READY",
}
RUN_TRANSITIONS = {
    "CREATED": {"RUNNING", "PAUSED", "BLOCKED", "FAILED", "CANCELLED"},
    "RUNNING": {"PAUSED", "RECOVERING", "BLOCKED", "SUCCEEDED", "FAILED", "CANCELLED"},
    "PAUSED": {"RUNNING", "RECOVERING", "BLOCKED", "FAILED", "CANCELLED"},
    "RECOVERING": {"RUNNING", "BLOCKED", "FAILED", "CANCELLED"},
    "BLOCKED": {"RUNNING", "RECOVERING", "FAILED", "CANCELLED"},
    "SUCCEEDED": set(), "FAILED": set(), "CANCELLED": set(),
}
OPERATION_TRANSITIONS = {
    "QUEUED": {"STARTING", "RUNNING", "FAILED", "CANCELLED"},
    "STARTING": {"RUNNING", "WAITING_EXTERNAL", "FAILED", "UNCERTAIN", "CANCEL_REQUESTED", "CANCELLED"},
    "RUNNING": {"WAITING_EXTERNAL", "SUCCEEDED", "FAILED", "UNCERTAIN", "CANCEL_REQUESTED", "CANCELLED"},
    "WAITING_EXTERNAL": {"RUNNING", "SUCCEEDED", "FAILED", "UNCERTAIN", "CANCEL_REQUESTED", "CANCELLED"},
    "CANCEL_REQUESTED": {"CANCELLED", "FAILED", "UNCERTAIN", "SUCCEEDED"},
    "UNCERTAIN": {"SUCCEEDED", "FAILED", "CANCELLED"},
    "SUCCEEDED": set(), "FAILED": set(), "CANCELLED": set(),
}
AGENT_TRANSITIONS = {
    "AVAILABLE": {"ACTIVE", "DEAD"},
    "ACTIVE": {"WAITING", "SUSPECTED_STALL", "RECOVERING", "ORPHANED", "DEAD", "AVAILABLE"},
    "WAITING": {"ACTIVE", "SUSPECTED_STALL", "RECOVERING", "ORPHANED", "DEAD", "AVAILABLE"},
    "SUSPECTED_STALL": {"RECOVERING", "ACTIVE", "ORPHANED", "DEAD"},
    "RECOVERING": {"ACTIVE", "WAITING", "ORPHANED", "DEAD"},
    "ORPHANED": {"RECOVERING", "DEAD"},
    "DEAD": set(),
}
CHAT_TRANSITIONS = {
    "READY": {"GENERATING", "TOOL_WAIT", "PLATFORM_HOLD", "WAITING_USER", "IDLE", "DISCONNECTED"},
    "GENERATING": {"READY", "TOOL_WAIT", "PLATFORM_HOLD", "WAITING_USER", "IDLE", "DISCONNECTED"},
    "TOOL_WAIT": {"GENERATING", "READY", "PLATFORM_HOLD", "WAITING_USER", "IDLE", "DISCONNECTED"},
    "PLATFORM_HOLD": {"READY", "GENERATING", "WAITING_USER", "IDLE", "DISCONNECTED"},
    "WAITING_USER": {"READY", "GENERATING", "IDLE", "DISCONNECTED"},
    "IDLE": {"READY", "GENERATING", "DISCONNECTED"},
    "DISCONNECTED": {"READY", "IDLE"},
}


def _now() -> float:
    return time.time()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _validate_id(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{name} must be 1..128 safe identifier characters")
    return text


class DurableStateConflict(RuntimeError):
    pass


class StaleFenceError(PermissionError):
    pass


class DurableRunService:
    """Persistent universal runs, operations, events, leases and artifacts."""

    def __init__(self, state_root: Path, *, clock=_now) -> None:
        self.state_root = Path(state_root).resolve()
        self.root = self.state_root / "durable"
        self.run_root = self.root / "runs"
        self.artifact_root = self.root / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            str(self.root / "durable.sqlite3"),
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
                CREATE TABLE IF NOT EXISTS runs(
                    run_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    workspace TEXT,
                    idempotency_key TEXT,
                    state TEXT NOT NULL,
                    desired_state TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    result_json TEXT,
                    rollback_json TEXT,
                    required_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    capability_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    capabilities_used_json TEXT NOT NULL DEFAULT '[]',
                    last_seq INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(owner,idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS agents(
                    agent_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    owner TEXT NOT NULL,
                    role TEXT NOT NULL,
                    task_id TEXT,
                    state TEXT NOT NULL,
                    desired_state TEXT NOT NULL,
                    chat_id TEXT,
                    heartbeat_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS chats(
                    chat_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    owner TEXT NOT NULL,
                    agent_id TEXT,
                    state TEXT NOT NULL,
                    desired_state TEXT NOT NULL,
                    provider TEXT,
                    conversation_id TEXT,
                    conversation_url TEXT,
                    project_id TEXT,
                    project_url TEXT,
                    title TEXT,
                    heartbeat_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS operations(
                    operation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    owner TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    readiness TEXT NOT NULL,
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    rollback_json TEXT,
                    cleanup_policy TEXT NOT NULL,
                    UNIQUE(run_id,idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS resources(
                    resource_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    operation_id TEXT,
                    owner TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts(
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    operation_id TEXT,
                    owner TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS leases(
                    resource_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    operation_id TEXT,
                    owner TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    lease_until REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events(
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    operation_id TEXT,
                    event_type TEXT NOT NULL,
                    state TEXT,
                    ts REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(run_id,seq)
                );
                CREATE INDEX IF NOT EXISTS idx_agents_run ON agents(run_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_chats_run ON chats(run_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_operations_run ON operations(run_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id,seq);
                CREATE INDEX IF NOT EXISTS idx_resources_run ON resources(run_id,updated_at);
                """
            )
            # Forward-compatible migration for durable DBs created before
            # capabilities_used became a first-class Run field.
            run_columns = {
                str(row["name"])
                for row in self.db.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "capabilities_used_json" not in run_columns:
                self.db.execute(
                    "ALTER TABLE runs ADD COLUMN capabilities_used_json "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
            self.db.commit()

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def _run_row(self, run_id: str, owner: str | None = None) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("run not found")
        if owner is not None and row["owner"] != owner:
            raise PermissionError("run belongs to another owner")
        return row

    def _operation_row(self, operation_id: str, owner: str | None = None) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if row is None:
            raise FileNotFoundError("operation not found")
        if owner is not None and row["owner"] != owner:
            raise PermissionError("operation belongs to another owner")
        return row

    def _agent_row(self, agent_id: str, owner: str | None = None) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT * FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if row is None:
            raise FileNotFoundError("agent not found")
        if owner is not None and row["owner"] != owner:
            raise PermissionError("agent belongs to another owner")
        return row

    def _chat_row(self, chat_id: str, owner: str | None = None) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT * FROM chats WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None:
            raise FileNotFoundError("chat not found")
        if owner is not None and row["owner"] != owner:
            raise PermissionError("chat belongs to another owner")
        return row

    def _event_path(self, run_id: str) -> Path:
        path = self.run_root / _validate_id("run_id", run_id)
        path.mkdir(parents=True, exist_ok=True)
        return path / "events.jsonl"

    def _state_path(self, run_id: str) -> Path:
        path = self.run_root / _validate_id("run_id", run_id)
        path.mkdir(parents=True, exist_ok=True)
        return path / "state.json"

    def _append_event_locked(
        self,
        run_id: str,
        event_type: str,
        *,
        operation_id: str | None = None,
        state: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self._run_row(run_id)
        seq = int(row["last_seq"]) + 1
        event = {
            "event_id": str(uuid.uuid4()),
            "run_id": run_id,
            "seq": seq,
            "operation_id": operation_id,
            "type": str(event_type),
            "state": state,
            "ts": self.clock(),
            "payload": dict(payload or {}),
        }
        self.db.execute(
            "INSERT INTO events(event_id,run_id,seq,operation_id,event_type,state,ts,payload_json)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                event["event_id"], run_id, seq, operation_id,
                event["type"], state, event["ts"], _json(event["payload"]),
            ),
        )
        self.db.execute(
            "UPDATE runs SET last_seq=?,updated_at=? WHERE run_id=?",
            (seq, event["ts"], run_id),
        )
        with self._event_path(run_id).open("a", encoding="utf-8") as handle:
            handle.write(_json(event) + "\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        return event

    def _project_locked(self, run_id: str) -> dict[str, Any]:
        snapshot = self._run_info_locked(self._run_row(run_id), include_details=True)
        target = self._state_path(run_id)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, target)
        return snapshot

    def create_run(
        self,
        owner: str,
        *,
        workspace: str | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
        required_capabilities: list[str] | None = None,
        capability_snapshot: dict[str, Any] | None = None,
        desired_state: str = "RUNNING",
    ) -> dict[str, Any]:
        if desired_state not in RUN_STATES:
            raise ValueError("invalid desired run state")
        if desired_state in TERMINAL_RUN_STATES:
            raise ValueError("new run cannot desire a terminal state")
        key = str(idempotency_key or "").strip() or None
        now = self.clock()
        with self.lock:
            if key:
                existing = self.db.execute(
                    "SELECT * FROM runs WHERE owner=? AND idempotency_key=?",
                    (owner, key),
                ).fetchone()
                if existing is not None:
                    info = self._run_info_locked(existing, include_details=True)
                    info["idempotent_replay"] = True
                    return info
            rid = _validate_id("run_id", run_id or ("run-" + uuid.uuid4().hex))
            if self.db.execute("SELECT 1 FROM runs WHERE run_id=?", (rid,)).fetchone():
                raise FileExistsError("run_id already exists")
            self.db.execute(
                "INSERT INTO runs(run_id,owner,workspace,idempotency_key,state,desired_state,"
                "started_at,updated_at,required_capabilities_json,capability_snapshot_json)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    rid, owner, workspace, key, "CREATED", desired_state, now, now,
                    _json(required_capabilities or []), _json(capability_snapshot or {}),
                ),
            )
            self._append_event_locked(
                rid, "RUN_CREATED", state="CREATED",
                payload={
                    "owner": owner, "workspace": workspace,
                    "desired_state": desired_state,
                    "required_capabilities": required_capabilities or [],
                },
            )
            if desired_state == "RUNNING":
                self.db.execute(
                    "UPDATE runs SET state='RUNNING',updated_at=? WHERE run_id=?",
                    (now, rid),
                )
                self._append_event_locked(rid, "RUN_STARTED", state="RUNNING")
            self.db.commit()
            return self._project_locked(rid)

    def ensure_implicit_run(self, owner: str, *, workspace: str | None = None) -> dict[str, Any]:
        digest = hashlib.sha256(f"{owner}|{workspace or ''}".encode()).hexdigest()[:24]
        return self.create_run(
            owner,
            workspace=workspace,
            idempotency_key=f"implicit:{digest}",
            required_capabilities=[],
        )

    def transition_run(
        self,
        run_id: str,
        owner: str,
        state: str,
        *,
        reason: str = "",
        result: dict[str, Any] | None = None,
        rollback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if state not in RUN_STATES:
            raise ValueError("invalid run state")
        with self.lock:
            row = self._run_row(run_id, owner)
            current = row["state"]
            if state != current and state not in RUN_TRANSITIONS.get(current, set()):
                raise DurableStateConflict(f"invalid run transition {current} -> {state}")
            now = self.clock()
            self.db.execute(
                "UPDATE runs SET state=?,updated_at=?,result_json=COALESCE(?,result_json),"
                "rollback_json=COALESCE(?,rollback_json) WHERE run_id=?",
                (state, now, _json(result) if result is not None else None,
                 _json(rollback) if rollback is not None else None, run_id),
            )
            self._append_event_locked(
                run_id, "RUN_STATE_CHANGED", state=state,
                payload={"from": current, "to": state, "reason": reason},
            )
            self.db.commit()
            return self._project_locked(run_id)

    def record_capabilities_used(
        self,
        run_id: str,
        owner: str,
        capabilities: list[str],
    ) -> dict[str, Any]:
        """Merge capabilities actually consumed by a Run."""
        normalized = sorted({
            str(item).strip()
            for item in capabilities
            if str(item).strip()
        })
        with self.lock:
            row = self._run_row(run_id, owner)
            current = set(_load(row["capabilities_used_json"], []))
            current.update(normalized)
            merged = sorted(current)
            self.db.execute(
                "UPDATE runs SET capabilities_used_json=?,updated_at=? WHERE run_id=?",
                (_json(merged), self.clock(), run_id),
            )
            self._append_event_locked(
                run_id,
                "CAPABILITIES_USED",
                payload={"capabilities": normalized, "all": merged},
            )
            self.db.commit()
            return self._project_locked(run_id)

    def assign_agent(
        self,
        run_id: str,
        owner: str,
        *,
        role: str,
        task_id: str | None = None,
        agent_id: str | None = None,
        state: str = "ACTIVE",
        desired_state: str = "ACTIVE",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if state not in AGENT_STATES or desired_state not in AGENT_STATES:
            raise ValueError("invalid agent state")
        role = str(role or "").strip()
        if not role or len(role) > 120:
            raise ValueError("agent role is required")
        aid = _validate_id("agent_id", agent_id or ("agent-" + uuid.uuid4().hex))
        now = self.clock()
        with self.lock:
            self._run_row(run_id, owner)
            existing = self.db.execute(
                "SELECT * FROM agents WHERE agent_id=?", (aid,)
            ).fetchone()
            if existing is not None:
                if existing["owner"] != owner or existing["run_id"] != run_id:
                    raise FileExistsError("agent_id already belongs to another run")
                return self._agent_info_locked(existing)
            self.db.execute(
                "INSERT INTO agents(agent_id,run_id,owner,role,task_id,state,desired_state,"
                "heartbeat_at,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    aid, run_id, owner, role, task_id, state, desired_state,
                    now, now, now, _json(metadata or {}),
                ),
            )
            self._append_event_locked(
                run_id,
                "AGENT_ASSIGNED",
                state=state,
                payload={
                    "agent_id": aid,
                    "role": role,
                    "task_id": task_id,
                    "desired_state": desired_state,
                },
            )
            self.db.commit()
            self._project_locked(run_id)
            return self._agent_info_locked(self._agent_row(aid))

    def update_agent(
        self,
        agent_id: str,
        owner: str,
        *,
        state: str | None = None,
        desired_state: str | None = None,
        task_id: str | None = None,
        chat_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        heartbeat: bool = True,
        event_type: str = "AGENT_STATE_CHANGED",
    ) -> dict[str, Any]:
        if state is not None and state not in AGENT_STATES:
            raise ValueError("invalid agent state")
        if desired_state is not None and desired_state not in AGENT_STATES:
            raise ValueError("invalid desired agent state")
        with self.lock:
            row = self._agent_row(agent_id, owner)
            current = str(row["state"])
            target = state or current
            if target != current and target not in AGENT_TRANSITIONS.get(current, set()):
                raise DurableStateConflict(
                    f"invalid agent transition {current} -> {target}"
                )
            if chat_id is not None:
                chat = self._chat_row(chat_id, owner)
                if chat["run_id"] != row["run_id"]:
                    raise ValueError("chat belongs to another run")
            merged_meta = _load(row["metadata_json"], {})
            if metadata:
                merged_meta.update(metadata)
            now = self.clock()
            self.db.execute(
                "UPDATE agents SET state=?,desired_state=?,task_id=COALESCE(?,task_id),"
                "chat_id=COALESCE(?,chat_id),metadata_json=?,heartbeat_at=?,updated_at=? "
                "WHERE agent_id=?",
                (
                    target,
                    desired_state or row["desired_state"],
                    task_id,
                    chat_id,
                    _json(merged_meta),
                    now if heartbeat else row["heartbeat_at"],
                    now,
                    agent_id,
                ),
            )
            self._append_event_locked(
                row["run_id"],
                event_type,
                state=target,
                payload={
                    "agent_id": agent_id,
                    "from": current,
                    "to": target,
                    "desired_state": desired_state or row["desired_state"],
                    "task_id": task_id if task_id is not None else row["task_id"],
                    "chat_id": chat_id if chat_id is not None else row["chat_id"],
                },
            )
            self.db.commit()
            self._project_locked(row["run_id"])
            return self._agent_info_locked(self._agent_row(agent_id))

    def bind_chat(
        self,
        run_id: str,
        owner: str,
        *,
        agent_id: str | None = None,
        provider: str | None = None,
        conversation_id: str | None = None,
        conversation_url: str | None = None,
        project_id: str | None = None,
        project_url: str | None = None,
        title: str | None = None,
        chat_id: str | None = None,
        state: str = "READY",
        desired_state: str = "READY",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if state not in CHAT_STATES or desired_state not in CHAT_STATES:
            raise ValueError("invalid chat state")
        cid = _validate_id("chat_id", chat_id or ("chat-" + uuid.uuid4().hex))
        role = "chat"
        with self.lock:
            self._run_row(run_id, owner)
            if agent_id:
                agent = self._agent_row(agent_id, owner)
                if agent["run_id"] != run_id:
                    raise ValueError("agent belongs to another run")
                role = str(agent["role"])
            existing = self.db.execute(
                "SELECT * FROM chats WHERE chat_id=?", (cid,)
            ).fetchone()
            if existing is not None:
                if existing["owner"] != owner or existing["run_id"] != run_id:
                    raise FileExistsError("chat_id already belongs to another run")
                return self._chat_info_locked(existing)
            now = self.clock()
            effective_title = title or f"[SENTRA] {run_id} - {role}"
            self.db.execute(
                "INSERT INTO chats(chat_id,run_id,owner,agent_id,state,desired_state,provider,"
                "conversation_id,conversation_url,project_id,project_url,title,heartbeat_at,"
                "created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cid, run_id, owner, agent_id, state, desired_state, provider,
                    conversation_id, conversation_url, project_id, project_url,
                    effective_title, now, now, now, _json(metadata or {}),
                ),
            )
            if agent_id:
                self.db.execute(
                    "UPDATE agents SET chat_id=?,updated_at=? WHERE agent_id=?",
                    (cid, now, agent_id),
                )
            self._append_event_locked(
                run_id,
                "CHAT_BOUND",
                state=state,
                payload={
                    "chat_id": cid,
                    "agent_id": agent_id,
                    "provider": provider,
                    "conversation_id": conversation_id,
                    "conversation_url": conversation_url,
                    "project_id": project_id,
                    "project_url": project_url,
                    "title": effective_title,
                },
            )
            self.db.commit()
            self._project_locked(run_id)
            return self._chat_info_locked(self._chat_row(cid))

    def update_chat(
        self,
        chat_id: str,
        owner: str,
        *,
        state: str | None = None,
        desired_state: str | None = None,
        metadata: dict[str, Any] | None = None,
        heartbeat: bool = True,
        event_type: str = "CHAT_STATE_CHANGED",
    ) -> dict[str, Any]:
        if state is not None and state not in CHAT_STATES:
            raise ValueError("invalid chat state")
        if desired_state is not None and desired_state not in CHAT_STATES:
            raise ValueError("invalid desired chat state")
        with self.lock:
            row = self._chat_row(chat_id, owner)
            current = str(row["state"])
            target = state or current
            if target != current and target not in CHAT_TRANSITIONS.get(current, set()):
                raise DurableStateConflict(
                    f"invalid chat transition {current} -> {target}"
                )
            merged_meta = _load(row["metadata_json"], {})
            if metadata:
                merged_meta.update(metadata)
            now = self.clock()
            self.db.execute(
                "UPDATE chats SET state=?,desired_state=?,metadata_json=?,heartbeat_at=?,"
                "updated_at=? WHERE chat_id=?",
                (
                    target,
                    desired_state or row["desired_state"],
                    _json(merged_meta),
                    now if heartbeat else row["heartbeat_at"],
                    now,
                    chat_id,
                ),
            )
            self._append_event_locked(
                row["run_id"],
                event_type,
                state=target,
                payload={
                    "chat_id": chat_id,
                    "from": current,
                    "to": target,
                    "desired_state": desired_state or row["desired_state"],
                },
            )
            self.db.commit()
            self._project_locked(row["run_id"])
            return self._chat_info_locked(self._chat_row(chat_id))

    def rebind_chat(
        self,
        chat_id: str,
        owner: str,
        *,
        conversation_id: str | None,
        conversation_url: str | None,
        provider: str | None = None,
        project_id: str | None = None,
        project_url: str | None = None,
        reason: str = "recovery",
    ) -> dict[str, Any]:
        """Replace the physical chat while preserving logical Run/Agent identity."""
        with self.lock:
            row = self._chat_row(chat_id, owner)
            previous = {
                "conversation_id": row["conversation_id"],
                "conversation_url": row["conversation_url"],
                "provider": row["provider"],
            }
            now = self.clock()
            self.db.execute(
                "UPDATE chats SET state='READY',desired_state='READY',provider=?,"
                "conversation_id=?,conversation_url=?,project_id=COALESCE(?,project_id),"
                "project_url=COALESCE(?,project_url),heartbeat_at=?,updated_at=? WHERE chat_id=?",
                (
                    provider or row["provider"],
                    conversation_id,
                    conversation_url,
                    project_id,
                    project_url,
                    now,
                    now,
                    chat_id,
                ),
            )
            self._append_event_locked(
                row["run_id"],
                "CHAT_REBOUND",
                state="READY",
                payload={
                    "chat_id": chat_id,
                    "agent_id": row["agent_id"],
                    "previous": previous,
                    "conversation_id": conversation_id,
                    "conversation_url": conversation_url,
                    "provider": provider or row["provider"],
                    "reason": reason,
                },
            )
            self.db.commit()
            self._project_locked(row["run_id"])
            return self._chat_info_locked(self._chat_row(chat_id))

    def create_operation(
        self,
        run_id: str,
        owner: str,
        *,
        kind: str,
        idempotency_key: str,
        operation_id: str | None = None,
        cleanup_policy: str = "terminate_on_run_end",
        initial_state: str = "QUEUED",
    ) -> dict[str, Any]:
        if initial_state not in OPERATION_STATES:
            raise ValueError("invalid operation state")
        kind = str(kind or "").strip()
        key = str(idempotency_key or "").strip()
        if not kind or len(kind) > 120:
            raise ValueError("operation kind is required")
        if not key or len(key) > 240:
            raise ValueError("idempotency_key is required and must be <= 240 characters")
        if cleanup_policy not in {"terminate_on_run_end", "preserve", "manual"}:
            raise ValueError("invalid cleanup_policy")
        now = self.clock()
        with self.lock:
            self._run_row(run_id, owner)
            existing = self.db.execute(
                "SELECT * FROM operations WHERE run_id=? AND idempotency_key=?",
                (run_id, key),
            ).fetchone()
            if existing is not None:
                info = self._operation_info_locked(existing)
                info["idempotent_replay"] = True
                return info
            oid = _validate_id("operation_id", operation_id or ("op-" + uuid.uuid4().hex))
            self.db.execute(
                "INSERT INTO operations(operation_id,run_id,owner,idempotency_key,kind,state,"
                "readiness,progress_json,started_at,updated_at,heartbeat_at,cleanup_policy)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    oid, run_id, owner, key, kind, initial_state, "UNKNOWN", "{}",
                    now, now, now, cleanup_policy,
                ),
            )
            self._append_event_locked(
                run_id, "OPERATION_CREATED", operation_id=oid, state=initial_state,
                payload={"kind": kind, "idempotency_key": key, "cleanup_policy": cleanup_policy},
            )
            self.db.commit()
            self._project_locked(run_id)
            return self._operation_info_locked(self._operation_row(oid))

    def _verify_fence_locked(self, resource_key: str | None, fencing_token: int | None) -> None:
        if resource_key is None and fencing_token is None:
            return
        if not resource_key or fencing_token is None:
            raise ValueError("resource_key and fencing_token must be supplied together")
        lease = self.db.execute(
            "SELECT fencing_token,lease_until FROM leases WHERE resource_key=?",
            (resource_key,),
        ).fetchone()
        if lease is None:
            raise StaleFenceError("lease no longer exists")
        if int(fencing_token) != int(lease["fencing_token"]):
            raise StaleFenceError("stale fencing token")
        if float(lease["lease_until"]) <= self.clock():
            raise StaleFenceError("lease expired")

    def update_operation(
        self,
        operation_id: str,
        owner: str,
        *,
        state: str | None = None,
        readiness: str | None = None,
        progress: dict[str, Any] | None = None,
        event_type: str = "OPERATION_UPDATED",
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        rollback: dict[str, Any] | None = None,
        resource_key: str | None = None,
        fencing_token: int | None = None,
    ) -> dict[str, Any]:
        if state is not None and state not in OPERATION_STATES:
            raise ValueError("invalid operation state")
        if readiness is not None and readiness not in READINESS_STATES:
            raise ValueError("invalid readiness state")
        with self.lock:
            self._verify_fence_locked(resource_key, fencing_token)
            row = self._operation_row(operation_id, owner)
            current = row["state"]
            target = state or current
            if target != current and target not in OPERATION_TRANSITIONS.get(current, set()):
                raise DurableStateConflict(f"invalid operation transition {current} -> {target}")
            now = self.clock()
            current_progress = _load(row["progress_json"], {})
            if progress:
                current_progress.update(progress)
            self.db.execute(
                "UPDATE operations SET state=?,readiness=?,progress_json=?,updated_at=?,heartbeat_at=?,"
                "result_json=COALESCE(?,result_json),error_json=COALESCE(?,error_json),"
                "rollback_json=COALESCE(?,rollback_json) WHERE operation_id=?",
                (
                    target, readiness or row["readiness"], _json(current_progress), now, now,
                    _json(result) if result is not None else None,
                    _json(error) if error is not None else None,
                    _json(rollback) if rollback is not None else None,
                    operation_id,
                ),
            )
            payload = {
                "from": current, "to": target,
                "readiness": readiness or row["readiness"],
                "progress": current_progress,
            }
            self._append_event_locked(
                row["run_id"], event_type, operation_id=operation_id,
                state=target, payload=payload,
            )
            self.db.commit()
            self._project_locked(row["run_id"])
            return self._operation_info_locked(self._operation_row(operation_id))
    def heartbeat(
        self,
        operation_id: str,
        owner: str,
        *,
        progress: dict[str, Any] | None = None,
        readiness: str | None = None,
        resource_key: str | None = None,
        fencing_token: int | None = None,
    ) -> dict[str, Any]:
        return self.update_operation(
            operation_id, owner,
            progress=progress, readiness=readiness,
            event_type="OPERATION_HEARTBEAT",
            resource_key=resource_key, fencing_token=fencing_token,
        )

    def request_cancel(
        self,
        operation_id: str,
        owner: str,
        *,
        side_effect_may_have_started: bool = True,
    ) -> dict[str, Any]:
        target = "CANCEL_REQUESTED" if side_effect_may_have_started else "CANCELLED"
        return self.update_operation(
            operation_id, owner, state=target,
            event_type="OPERATION_CANCEL_REQUESTED",
            progress={"side_effect_may_have_started": bool(side_effect_may_have_started)},
        )

    def operation_status(self, operation_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            return self._operation_info_locked(self._operation_row(operation_id, owner))

    def wait_operation(
        self,
        operation_id: str,
        owner: str,
        *,
        timeout_s: float = 5.0,
        poll_s: float = 0.1,
    ) -> dict[str, Any]:
        if not 0 < timeout_s <= 25:
            raise ValueError("timeout_s must be in (0, 25]")
        deadline = time.monotonic() + timeout_s
        while True:
            info = self.operation_status(operation_id, owner)
            if info["state"] in TERMINAL_OPERATION_STATES | {"UNCERTAIN"}:
                info["wait_timed_out"] = False
                return info
            if time.monotonic() >= deadline:
                info["wait_timed_out"] = True
                return info
            time.sleep(min(poll_s, max(0.01, deadline - time.monotonic())))

    def attach_resource(
        self,
        run_id: str,
        owner: str,
        *,
        resource_type: str,
        resource_id: str,
        state: str,
        operation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rid = _validate_id("resource_id", resource_id)
        if not resource_type or len(resource_type) > 80:
            raise ValueError("resource_type is required")
        with self.lock:
            self._run_row(run_id, owner)
            if operation_id:
                operation = self._operation_row(operation_id, owner)
                if operation["run_id"] != run_id:
                    raise ValueError("operation belongs to another run")
            now = self.clock()
            self.db.execute(
                "INSERT INTO resources(resource_id,run_id,operation_id,owner,resource_type,state,"
                "metadata_json,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(resource_id) DO UPDATE SET state=excluded.state,"
                "metadata_json=excluded.metadata_json,updated_at=excluded.updated_at",
                (rid, run_id, operation_id, owner, resource_type, state, _json(metadata or {}), now),
            )
            self._append_event_locked(
                run_id, "RESOURCE_OBSERVED", operation_id=operation_id, state=state,
                payload={"resource_id": rid, "resource_type": resource_type, "metadata": metadata or {}},
            )
            self.db.commit()
            self._project_locked(run_id)
            return {
                "resource_id": rid, "run_id": run_id, "operation_id": operation_id,
                "type": resource_type, "state": state, "metadata": metadata or {},
                "updated_at": now,
            }

    def register_artifact(
        self,
        run_id: str,
        owner: str,
        path: Path,
        *,
        operation_id: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = Path(path).resolve()
        if not target.is_file():
            raise FileNotFoundError("artifact file does not exist")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        size = target.stat().st_size
        aid = "artifact-" + uuid.uuid4().hex
        mime = mime_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        with self.lock:
            self._run_row(run_id, owner)
            if operation_id:
                op = self._operation_row(operation_id, owner)
                if op["run_id"] != run_id:
                    raise ValueError("operation belongs to another run")
            now = self.clock()
            self.db.execute(
                "INSERT INTO artifacts(artifact_id,run_id,operation_id,owner,path,mime_type,"
                "sha256,size_bytes,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (aid, run_id, operation_id, owner, str(target), mime, digest, size, _json(metadata or {}), now),
            )
            self._append_event_locked(
                run_id, "ARTIFACT_WRITTEN", operation_id=operation_id,
                payload={"artifact_id": aid, "path": str(target), "mime_type": mime,
                         "sha256": digest, "size_bytes": size},
            )
            self.db.commit()
            self._project_locked(run_id)
            return {
                "artifact_id": aid, "run_id": run_id, "operation_id": operation_id,
                "path": str(target), "mime_type": mime, "sha256": digest,
                "size_bytes": size, "resource_uri": f"sentra://artifact/{aid}",
                "metadata": metadata or {},
            }
    def artifact_info(self, artifact_id: str, owner: str | None = None) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
            if row is None:
                raise FileNotFoundError("artifact not found")
            if owner is not None and row["owner"] != owner:
                raise PermissionError("artifact belongs to another owner")
            return {
                "artifact_id": row["artifact_id"], "run_id": row["run_id"],
                "operation_id": row["operation_id"], "path": row["path"],
                "mime_type": row["mime_type"], "sha256": row["sha256"],
                "size_bytes": row["size_bytes"], "metadata": _load(row["metadata_json"], {}),
                "created_at": row["created_at"], "resource_uri": f"sentra://artifact/{artifact_id}",
            }

    def read_artifact(self, artifact_id: str, *, max_bytes: int) -> bytes:
        info = self.artifact_info(artifact_id)
        if int(info["size_bytes"]) > max_bytes:
            raise ValueError("artifact exceeds configured read limit")
        path = Path(str(info["path"])).resolve()
        if not path.is_file():
            raise FileNotFoundError("artifact file is no longer available")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != info["sha256"]:
            raise RuntimeError("artifact content hash changed after registration")
        return payload

    def acquire_lease(
        self,
        run_id: str,
        owner: str,
        resource_key: str,
        *,
        operation_id: str | None = None,
        ttl_s: float = 60.0,
    ) -> dict[str, Any]:
        if not 1 <= ttl_s <= 3600:
            raise ValueError("ttl_s must be between 1 and 3600")
        key = _validate_id("resource_key", resource_key)
        now = self.clock()
        with self.lock:
            self._run_row(run_id, owner)
            row = self.db.execute(
                "SELECT * FROM leases WHERE resource_key=?", (key,)
            ).fetchone()
            if row is not None and float(row["lease_until"]) > now:
                same_holder = (
                    row["owner"] == owner
                    and row["run_id"] == run_id
                    and row["operation_id"] == operation_id
                )
                if same_holder:
                    return {
                        "resource_key": key,
                        "run_id": row["run_id"],
                        "operation_id": row["operation_id"],
                        "owner": row["owner"],
                        "fencing_token": int(row["fencing_token"]),
                        "lease_until": float(row["lease_until"]),
                        "idempotent_replay": True,
                    }
                raise DurableStateConflict("resource lease is already held")
            token = (int(row["fencing_token"]) + 1) if row is not None else 1
            until = now + ttl_s
            self.db.execute(
                "INSERT INTO leases(resource_key,run_id,operation_id,owner,fencing_token,lease_until,updated_at)"
                " VALUES(?,?,?,?,?,?,?) ON CONFLICT(resource_key) DO UPDATE SET "
                "run_id=excluded.run_id,operation_id=excluded.operation_id,owner=excluded.owner,"
                "fencing_token=excluded.fencing_token,lease_until=excluded.lease_until,updated_at=excluded.updated_at",
                (key, run_id, operation_id, owner, token, until, now),
            )
            self._append_event_locked(
                run_id, "LEASE_ACQUIRED", operation_id=operation_id,
                payload={"resource_key": key, "fencing_token": token, "lease_until": until},
            )
            self.db.commit()
            self._project_locked(run_id)
            return {
                "resource_key": key, "run_id": run_id, "operation_id": operation_id,
                "owner": owner, "fencing_token": token, "lease_until": until,
            }

    def renew_lease(
        self,
        resource_key: str,
        owner: str,
        fencing_token: int,
        *,
        ttl_s: float = 60.0,
    ) -> dict[str, Any]:
        if not 1 <= ttl_s <= 3600:
            raise ValueError("ttl_s must be between 1 and 3600")
        now = self.clock()
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM leases WHERE resource_key=?", (resource_key,)
            ).fetchone()
            if row is None or row["owner"] != owner:
                raise StaleFenceError("lease no longer belongs to caller")
            if int(row["fencing_token"]) != int(fencing_token):
                raise StaleFenceError("stale fencing token")
            if float(row["lease_until"]) <= now:
                raise StaleFenceError("lease expired")
            until = now + ttl_s
            self.db.execute(
                "UPDATE leases SET lease_until=?,updated_at=? WHERE resource_key=?",
                (until, now, resource_key),
            )
            self._append_event_locked(
                row["run_id"], "LEASE_RENEWED", operation_id=row["operation_id"],
                payload={"resource_key": resource_key, "fencing_token": fencing_token,
                         "lease_until": until},
            )
            self.db.commit()
            return {
                "resource_key": resource_key, "fencing_token": int(fencing_token),
                "lease_until": until,
            }

    def release_lease(self, resource_key: str, owner: str, fencing_token: int) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM leases WHERE resource_key=?", (resource_key,)
            ).fetchone()
            if row is None:
                return {"resource_key": resource_key, "released": False, "already_absent": True}
            if row["owner"] != owner or int(row["fencing_token"]) != int(fencing_token):
                raise StaleFenceError("stale fencing token")
            self.db.execute("DELETE FROM leases WHERE resource_key=?", (resource_key,))
            self._append_event_locked(
                row["run_id"], "LEASE_RELEASED", operation_id=row["operation_id"],
                payload={"resource_key": resource_key, "fencing_token": fencing_token},
            )
            self.db.commit()
            self._project_locked(row["run_id"])
            return {"resource_key": resource_key, "released": True}

    def checkpoint(
        self,
        run_id: str,
        owner: str,
        data: dict[str, Any],
        *,
        label: str = "checkpoint",
    ) -> dict[str, Any]:
        if len(_json(data).encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("checkpoint exceeds 2 MiB")
        with self.lock:
            self._run_row(run_id, owner)
            event = self._append_event_locked(
                run_id, "CHECKPOINT", payload={"label": label, "data": data},
            )
            self.db.commit()
            self._project_locked(run_id)
            return event
    def events(
        self,
        run_id: str,
        owner: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid event page")
        with self.lock:
            self._run_row(run_id, owner)
            total = int(self.db.execute(
                "SELECT COUNT(*) FROM events WHERE run_id=?", (run_id,)
            ).fetchone()[0])
            rows = self.db.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY seq LIMIT ? OFFSET ?",
                (run_id, limit, offset),
            ).fetchall()
            items = [
                {
                    "event_id": row["event_id"], "run_id": row["run_id"],
                    "seq": row["seq"], "operation_id": row["operation_id"],
                    "type": row["event_type"], "state": row["state"], "ts": row["ts"],
                    "payload": _load(row["payload_json"], {}),
                }
                for row in rows
            ]
            next_offset = offset + len(items)
            return {
                "items": items,
                "page": {
                    "offset": offset, "limit": limit, "returned": len(items),
                    "total": total, "next_offset": next_offset if next_offset < total else None,
                },
            }

    def events_after(
        self,
        run_id: str,
        owner: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        if after_seq < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid event cursor")
        with self.lock:
            self._run_row(run_id, owner)
            rows = self.db.execute(
                "SELECT * FROM events WHERE run_id=? AND seq>? "
                "ORDER BY seq LIMIT ?",
                (run_id, after_seq, limit),
            ).fetchall()
            items = [
                {
                    "event_id": row["event_id"],
                    "run_id": row["run_id"],
                    "seq": row["seq"],
                    "operation_id": row["operation_id"],
                    "type": row["event_type"],
                    "state": row["state"],
                    "ts": row["ts"],
                    "payload": _load(row["payload_json"], {}),
                }
                for row in rows
            ]
            last_seq = int(self._run_row(run_id)["last_seq"])
            cursor = items[-1]["seq"] if items else after_seq
            return {
                "items": items,
                "cursor": {
                    "after_seq": after_seq,
                    "returned": len(items),
                    "next_after_seq": cursor,
                    "last_event_seq": last_seq,
                    "caught_up": cursor >= last_seq,
                },
            }

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                proc = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=3,
                    check=False,
                    shell=False,
                )
            except (OSError, subprocess.SubprocessError):
                return False
            text = proc.stdout.strip()
            return proc.returncode == 0 and str(pid) in text and "No tasks" not in text
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _resource_alive(
        self,
        resource: sqlite3.Row,
        *,
        now: float,
        stale_after_s: float,
    ) -> bool:
        state = str(resource["state"]).upper()
        if state not in {"RUNNING", "READY", "CONNECTED", "PRODUCT_READY"}:
            return False
        if str(resource["resource_type"]).lower() == "process":
            metadata = _load(resource["metadata_json"], {})
            try:
                pid = int(metadata.get("pid") or 0)
            except (TypeError, ValueError):
                return False
            return self._pid_exists(pid)
        return now - float(resource["updated_at"]) <= stale_after_s

    def reconcile(
        self,
        run_id: str,
        owner: str,
        *,
        stale_after_s: float = 120.0,
    ) -> dict[str, Any]:
        """Reconcile desired vs observed state without replaying ambiguous effects."""
        if not 5 <= stale_after_s <= 86400:
            raise ValueError("stale_after_s must be between 5 and 86400")
        now = self.clock()
        with self.lock:
            run = self._run_row(run_id, owner)
            operations = self.db.execute(
                "SELECT * FROM operations WHERE run_id=?", (run_id,)
            ).fetchall()
            agents = self.db.execute(
                "SELECT * FROM agents WHERE run_id=?", (run_id,)
            ).fetchall()
            chats = self.db.execute(
                "SELECT * FROM chats WHERE run_id=?", (run_id,)
            ).fetchall()
            actions: list[dict[str, Any]] = []

            for operation in operations:
                if operation["state"] in TERMINAL_OPERATION_STATES | {"UNCERTAIN"}:
                    continue
                age = now - float(operation["heartbeat_at"])
                if age <= stale_after_s:
                    continue

                resources = self.db.execute(
                    "SELECT * FROM resources WHERE operation_id=?",
                    (operation["operation_id"],),
                ).fetchall()
                alive_resources = [
                    resource
                    for resource in resources
                    if self._resource_alive(
                        resource, now=now, stale_after_s=stale_after_s
                    )
                ]
                for resource in resources:
                    if (
                        str(resource["resource_type"]).lower() == "process"
                        and str(resource["state"]).upper()
                        in {"RUNNING", "READY", "CONNECTED", "PRODUCT_READY"}
                        and resource not in alive_resources
                    ):
                        self.db.execute(
                            "UPDATE resources SET state='EXITED',updated_at=? "
                            "WHERE resource_id=?",
                            (now, resource["resource_id"]),
                        )
                        self._append_event_locked(
                            run_id,
                            "RESOURCE_RECONCILED",
                            operation_id=operation["operation_id"],
                            state="EXITED",
                            payload={
                                "resource_id": resource["resource_id"],
                                "resource_type": "process",
                                "reason": "persisted process resource is no longer alive",
                            },
                        )

                recent_artifact = self.db.execute(
                    "SELECT 1 FROM artifacts WHERE operation_id=? AND created_at>=? LIMIT 1",
                    (operation["operation_id"], now - stale_after_s),
                ).fetchone()
                fresh_lease = self.db.execute(
                    "SELECT 1 FROM leases WHERE operation_id=? AND lease_until>? "
                    "AND updated_at>=? LIMIT 1",
                    (
                        operation["operation_id"],
                        now,
                        now - stale_after_s,
                    ),
                ).fetchone()

                progress = _load(operation["progress_json"], {})
                linked_agent_id = (
                    str(progress.get("agent_id"))
                    if progress.get("agent_id")
                    else None
                )
                linked_chat_id = (
                    str(progress.get("chat_id"))
                    if progress.get("chat_id")
                    else None
                )
                linked_agent = (
                    next(
                        (item for item in agents if item["agent_id"] == linked_agent_id),
                        None,
                    )
                    if linked_agent_id else None
                )
                linked_chat = (
                    next(
                        (item for item in chats if item["chat_id"] == linked_chat_id),
                        None,
                    )
                    if linked_chat_id else None
                )
                agent_fresh = bool(
                    linked_agent
                    and now - float(linked_agent["heartbeat_at"]) <= stale_after_s
                    and linked_agent["state"] in {
                        "ACTIVE", "WAITING", "RECOVERING"
                    }
                )
                chat_fresh = bool(
                    linked_chat
                    and now - float(linked_chat["heartbeat_at"]) <= stale_after_s
                    and linked_chat["state"] != "DISCONNECTED"
                )

                evidence: list[str] = []
                if alive_resources:
                    evidence.append("live_resource")
                if recent_artifact is not None:
                    evidence.append("recent_artifact")
                if fresh_lease is not None:
                    evidence.append("fresh_lease")
                if agent_fresh:
                    evidence.append("fresh_agent")
                if chat_fresh:
                    evidence.append("fresh_chat")
                if evidence:
                    actions.append({
                        "operation_id": operation["operation_id"],
                        "action": "NO_ACTION",
                        "reason": "observed progress/liveness still exists",
                        "evidence": evidence,
                        "heartbeat_age_s": round(age, 3),
                    })
                    continue

                self.db.execute(
                    "UPDATE operations SET state='UNCERTAIN',updated_at=? WHERE operation_id=?",
                    (now, operation["operation_id"]),
                )
                self._append_event_locked(
                    run_id,
                    "OPERATION_SUSPECTED_STALL",
                    operation_id=operation["operation_id"],
                    state="UNCERTAIN",
                    payload={
                        "heartbeat_age_s": age,
                        "action": "FAIL_CLOSED_NO_REPLAY",
                        "desired_state": run["desired_state"],
                    },
                )

                if linked_chat is not None:
                    chat_age = now - float(linked_chat["heartbeat_at"])
                    if chat_age > stale_after_s and linked_chat["state"] != "DISCONNECTED":
                        self.db.execute(
                            "UPDATE chats SET state='DISCONNECTED',updated_at=? "
                            "WHERE chat_id=?",
                            (now, linked_chat["chat_id"]),
                        )
                        self._append_event_locked(
                            run_id,
                            "CHAT_STATE_CHANGED",
                            state="DISCONNECTED",
                            payload={
                                "chat_id": linked_chat["chat_id"],
                                "from": linked_chat["state"],
                                "to": "DISCONNECTED",
                                "reason": "stale chat heartbeat during reconciliation",
                            },
                        )
                if linked_agent is not None:
                    agent_state = str(linked_agent["state"])
                    if (
                        agent_state not in {"SUSPECTED_STALL", "ORPHANED", "DEAD"}
                        and "SUSPECTED_STALL"
                        in AGENT_TRANSITIONS.get(agent_state, set())
                    ):
                        self.db.execute(
                            "UPDATE agents SET state='SUSPECTED_STALL',updated_at=? "
                            "WHERE agent_id=?",
                            (now, linked_agent["agent_id"]),
                        )
                        self._append_event_locked(
                            run_id,
                            "AGENT_SUSPECTED_STALL",
                            state="SUSPECTED_STALL",
                            payload={
                                "agent_id": linked_agent["agent_id"],
                                "operation_id": operation["operation_id"],
                            },
                        )

                actions.append({
                    "operation_id": operation["operation_id"],
                    "action": "MARK_UNCERTAIN",
                    "reason": (
                        "stale operation with no live process/resource, recent artifact, "
                        "fresh lease, agent heartbeat, or chat heartbeat"
                    ),
                    "heartbeat_age_s": round(age, 3),
                    "next": "SOFT_RECOVERY",
                })

            stalled_agents = self.db.execute(
                "SELECT * FROM agents WHERE run_id=? AND state='SUSPECTED_STALL'",
                (run_id,),
            ).fetchall()
            for agent in stalled_agents:
                actions.append({
                    "agent_id": agent["agent_id"],
                    "chat_id": agent["chat_id"],
                    "action": "SOFT_RECOVERY_REQUIRED",
                    "reason": (
                        "agent is suspected stalled; inspect operation/chat before continuation"
                    ),
                    "automatic_chat_replacement": False,
                })

            if any(
                item.get("action") in {"MARK_UNCERTAIN", "SOFT_RECOVERY_REQUIRED"}
                for item in actions
            ):
                current = run["state"]
                target = (
                    "RECOVERING"
                    if current in {"RUNNING", "PAUSED"}
                    else current
                )
                if target != current:
                    self.db.execute(
                        "UPDATE runs SET state=?,updated_at=? WHERE run_id=?",
                        (target, now, run_id),
                    )
                    self._append_event_locked(
                        run_id,
                        "RECOVERY_STARTED",
                        state=target,
                        payload={
                            "reason": "desired and observed execution state diverged",
                            "automatic_replay": False,
                        },
                    )
            self.db.commit()
            snapshot = self._project_locked(run_id)
            return {
                "run": snapshot,
                "actions": actions,
                "auto_replay": False,
                "policy": (
                    "timeout alone never aborts or replays; recovery is evidence-driven"
                ),
            }

    def resume(self, run_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            row = self._run_row(run_id, owner)
            snapshot = self._run_info_locked(row, include_details=True)
            snapshot["resume"] = {
                "safe_to_continue": row["state"] not in TERMINAL_RUN_STATES,
                "instruction": (
                    "Inspect UNCERTAIN/BLOCKED operations before issuing any side-effecting retry."
                ),
                "state_path": str(self._state_path(run_id)),
                "events_path": str(self._event_path(run_id)),
            }
            return snapshot

    def list_runs(self, owner: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid run page")
        with self.lock:
            total = int(self.db.execute(
                "SELECT COUNT(*) FROM runs WHERE owner=?", (owner,)
            ).fetchone()[0])
            rows = self.db.execute(
                "SELECT * FROM runs WHERE owner=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (owner, limit, offset),
            ).fetchall()
            items = [self._run_info_locked(row, include_details=False) for row in rows]
            next_offset = offset + len(items)
            return {
                "items": items,
                "page": {
                    "offset": offset, "limit": limit, "returned": len(items),
                    "total": total, "next_offset": next_offset if next_offset < total else None,
                },
            }

    def run_status(self, run_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            return self._run_info_locked(self._run_row(run_id, owner), include_details=True)

    def _agent_info_locked(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "agent_id": row["agent_id"],
            "run_id": row["run_id"],
            "owner": row["owner"],
            "role": row["role"],
            "task_id": row["task_id"],
            "state": row["state"],
            "desired_state": row["desired_state"],
            "chat_id": row["chat_id"],
            "heartbeat_at": row["heartbeat_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": _load(row["metadata_json"], {}),
        }

    def _chat_info_locked(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "chat_id": row["chat_id"],
            "run_id": row["run_id"],
            "owner": row["owner"],
            "agent_id": row["agent_id"],
            "state": row["state"],
            "desired_state": row["desired_state"],
            "provider": row["provider"],
            "conversation_id": row["conversation_id"],
            "conversation_url": row["conversation_url"],
            "project_id": row["project_id"],
            "project_url": row["project_url"],
            "title": row["title"],
            "heartbeat_at": row["heartbeat_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": _load(row["metadata_json"], {}),
        }

    def _operation_info_locked(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "operation_id": row["operation_id"], "run_id": row["run_id"],
            "owner": row["owner"], "idempotency_key": row["idempotency_key"],
            "kind": row["kind"], "state": row["state"], "readiness": row["readiness"],
            "progress": _load(row["progress_json"], {}),
            "started_at": row["started_at"], "updated_at": row["updated_at"],
            "heartbeat_at": row["heartbeat_at"],
            "result": _load(row["result_json"], None),
            "error": _load(row["error_json"], None),
            "rollback": _load(row["rollback_json"], None),
            "cleanup_policy": row["cleanup_policy"],
            "terminal": row["state"] in TERMINAL_OPERATION_STATES,
        }

    def _run_info_locked(self, row: sqlite3.Row, *, include_details: bool) -> dict[str, Any]:
        data: dict[str, Any] = {
            "run_id": row["run_id"], "owner": row["owner"], "workspace": row["workspace"],
            "state": row["state"], "desired_state": row["desired_state"],
            "started_at": row["started_at"], "updated_at": row["updated_at"],
            "result": _load(row["result_json"], None),
            "rollback": _load(row["rollback_json"], None),
            "required_capabilities": _load(row["required_capabilities_json"], []),
            "capability_snapshot": _load(row["capability_snapshot_json"], {}),
            "capabilities_used": _load(row["capabilities_used_json"], []),
            "last_event_seq": row["last_seq"],
            "terminal": row["state"] in TERMINAL_RUN_STATES,
        }
        if not include_details:
            return data
        agents = self.db.execute(
            "SELECT * FROM agents WHERE run_id=? ORDER BY created_at",
            (row["run_id"],),
        ).fetchall()
        chats = self.db.execute(
            "SELECT * FROM chats WHERE run_id=? ORDER BY created_at",
            (row["run_id"],),
        ).fetchall()
        operations = self.db.execute(
            "SELECT * FROM operations WHERE run_id=? ORDER BY started_at",
            (row["run_id"],),
        ).fetchall()
        resources = self.db.execute(
            "SELECT * FROM resources WHERE run_id=? ORDER BY updated_at",
            (row["run_id"],),
        ).fetchall()
        artifacts = self.db.execute(
            "SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at",
            (row["run_id"],),
        ).fetchall()
        leases = self.db.execute(
            "SELECT * FROM leases WHERE run_id=? ORDER BY updated_at",
            (row["run_id"],),
        ).fetchall()
        data["agents"] = [self._agent_info_locked(item) for item in agents]
        data["chats"] = [self._chat_info_locked(item) for item in chats]
        data["operations"] = [self._operation_info_locked(item) for item in operations]
        resource_views = [
            {
                "resource_id": item["resource_id"], "operation_id": item["operation_id"],
                "type": item["resource_type"], "state": item["state"],
                "metadata": _load(item["metadata_json"], {}),
                "updated_at": item["updated_at"],
            }
            for item in resources
        ]
        data["resources"] = resource_views
        data["processes"] = [
            {
                "resource_id": item["resource_id"],
                "operation_id": item["operation_id"],
                "state": item["state"],
                "updated_at": item["updated_at"],
                **dict(item["metadata"]),
            }
            for item in resource_views
            if item["type"] == "process"
        ]
        data["progress"] = [
            {
                "operation_id": item["operation_id"],
                "kind": item["kind"],
                "state": item["state"],
                "readiness": item["readiness"],
                "progress": item["progress"],
                "heartbeat_at": item["heartbeat_at"],
                "updated_at": item["updated_at"],
            }
            for item in data["operations"]
        ]
        data["artifacts"] = [
            {
                "artifact_id": item["artifact_id"], "operation_id": item["operation_id"],
                "path": item["path"], "mime_type": item["mime_type"],
                "sha256": item["sha256"], "size_bytes": item["size_bytes"],
                "resource_uri": f"sentra://artifact/{item['artifact_id']}",
            }
            for item in artifacts
        ]
        data["leases"] = [
            {
                "resource_key": item["resource_key"], "operation_id": item["operation_id"],
                "fencing_token": item["fencing_token"], "lease_until": item["lease_until"],
                "updated_at": item["updated_at"],
            }
            for item in leases
        ]
        return data
