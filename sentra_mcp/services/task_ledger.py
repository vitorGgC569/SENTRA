"""Durable scheduler-task ledger shared by OMA and the Control Plane."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore

TASK_STATES = {
    "PENDING", "QUEUED", "RUNNING", "VALIDATING", "REJECTED", "REPAIRING",
    "READY", "DISPUTED", "QUALITY_GATE", "READY_FOR_MASTER", "MASTER_REVIEW",
    "COMPLETED", "FAILED", "RETRYING", "CANCELLED", "ESCALATED",
}
TERMINAL_TASK_STATES = {"COMPLETED", "CANCELLED"}
TASK_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
TASK_TRANSITIONS = {
    "PENDING": {"QUEUED", "RUNNING", "FAILED", "CANCELLED"},
    "QUEUED": {"RUNNING", "CANCELLED"},
    "RUNNING": {"VALIDATING", "COMPLETED", "FAILED", "CANCELLED"},
    "VALIDATING": {
        "READY", "QUALITY_GATE", "REJECTED", "DISPUTED", "FAILED", "CANCELLED",
    },
    "REJECTED": {"REPAIRING", "ESCALATED", "FAILED", "CANCELLED"},
    "REPAIRING": {"VALIDATING", "FAILED", "ESCALATED", "CANCELLED"},
    "READY": {"QUALITY_GATE", "READY_FOR_MASTER", "CANCELLED"},
    "DISPUTED": {"ESCALATED", "REPAIRING", "CANCELLED"},
    "QUALITY_GATE": {
        "READY_FOR_MASTER", "REPAIRING", "FAILED", "CANCELLED",
        "ESCALATED", "VALIDATING",
    },
    "READY_FOR_MASTER": {"MASTER_REVIEW", "COMPLETED", "CANCELLED"},
    "MASTER_REVIEW": {"COMPLETED", "REPAIRING", "FAILED", "CANCELLED"},
    "FAILED": {"RETRYING", "ESCALATED", "CANCELLED"},
    "RETRYING": {"QUEUED", "RUNNING", "FAILED", "CANCELLED"},
    "ESCALATED": {"MASTER_REVIEW", "FAILED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}
RECOVERABLE_TO_QUEUED = {
    "RUNNING", "VALIDATING", "REPAIRING", "QUALITY_GATE",
    "READY_FOR_MASTER", "MASTER_REVIEW", "RETRYING",
}


class TaskLedgerConflict(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _strings(name: str, value: Any, *, limit: int = 1000) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)) or len(value) > limit:
        raise ValueError(f"{name} must contain at most {limit} strings")
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text or len(text) > 4000:
            raise ValueError(f"{name} entries must be 1..4000 characters")
        if text not in out:
            out.append(text)
    return out


class DurableTaskLedger:
    """Cross-process task authority with an append-only transition journal.

    This is deliberately stored beside DurableRunService rather than in a Run's
    JSON checkpoint. The checkpoint remains useful for recovery, while this
    ledger provides cross-process visibility and state-transition fencing.
    """

    def __init__(
        self,
        state_root: Path | str,
        *,
        store: ControlPlaneStore | None = None,
    ) -> None:
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.path = self.store.path_for("task_ledger")
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks(
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    required_capabilities_json TEXT NOT NULL,
                    target_files_json TEXT NOT NULL,
                    resource_locks_json TEXT NOT NULL,
                    side_effect_scope TEXT NOT NULL,
                    assigned_node_id TEXT,
                    retry_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(run_id,task_id),
                    UNIQUE(run_id,idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_run_state
                    ON tasks(run_id,state,updated_at);
                CREATE TABLE IF NOT EXISTS task_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_run_seq
                    ON task_events(run_id,seq);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return self.store.connect("task_ledger")

    @staticmethod
    def _intent(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "objective": data["objective"],
            "idempotency_key": data["idempotency_key"],
            "priority": data["priority"],
            "dependencies": data["dependencies"],
            "required_capabilities": data["required_capabilities"],
            "target_files": data["target_files"],
            "resource_locks": data["resource_locks"],
            "side_effect_scope": data["side_effect_scope"],
        }

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "task_id": row["task_id"],
            "owner": row["owner"],
            "idempotency_key": row["idempotency_key"],
            "objective": row["objective"],
            "state": row["state"],
            "priority": row["priority"],
            "dependencies": _load(row["dependencies_json"], []),
            "required_capabilities": _load(
                row["required_capabilities_json"], []
            ),
            "target_files": _load(row["target_files_json"], []),
            "resource_locks": _load(row["resource_locks_json"], []),
            "side_effect_scope": row["side_effect_scope"],
            "assigned_node_id": row["assigned_node_id"],
            "retry_count": int(row["retry_count"]),
            "metadata": _load(row["metadata_json"], {}),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "terminal": row["state"] in TERMINAL_TASK_STATES,
        }

    @staticmethod
    def _normalize(task: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise TypeError("task must be an object")
        task_id = str(task.get("id") or task.get("task_id") or "").strip()
        if not task_id or len(task_id) > 128:
            raise ValueError("task_id must be 1..128 characters")
        objective = str(task.get("objective") or "").strip()
        if not objective or len(objective) > 100_000:
            raise ValueError("task objective must be 1..100000 characters")
        state = str(task.get("status") or task.get("state") or "PENDING").upper()
        if state not in TASK_STATES:
            raise ValueError("invalid task state")
        priority = str(task.get("priority") or "MEDIUM").upper()
        if priority not in TASK_PRIORITIES:
            raise ValueError("invalid task priority")
        idempotency_key = str(task.get("idempotency_key") or task_id).strip()
        if not idempotency_key or len(idempotency_key) > 512:
            raise ValueError("task idempotency_key must be 1..512 characters")
        metadata = task.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("task metadata must be an object")
        retry_count = int(task.get("retry_count") or 0)
        if retry_count < 0:
            raise ValueError("task retry_count must be non-negative")
        side_effect_scope = str(
            task.get("side_effect_scope") or "ISOLATED"
        ).strip().upper()
        if side_effect_scope not in {
            "ISOLATED", "WORKSPACE_WRITE", "EXTERNAL", "EXCLUSIVE"
        }:
            raise ValueError("invalid side_effect_scope")
        assigned = str(
            task.get("assigned_node_id")
            or metadata.get("assigned_node_id")
            or ""
        ).strip() or None
        return {
            "task_id": task_id,
            "objective": objective,
            "state": state,
            "priority": priority,
            "idempotency_key": idempotency_key,
            "dependencies": _strings(
                "task.dependencies", task.get("dependencies")
            ),
            "required_capabilities": _strings(
                "task.required_capabilities", task.get("required_capabilities")
            ),
            "target_files": _strings(
                "task.target_files", task.get("target_files")
            ),
            "resource_locks": _strings(
                "task.resource_locks", task.get("resource_locks")
            ),
            "side_effect_scope": side_effect_scope,
            "assigned_node_id": assigned,
            "retry_count": retry_count,
            "metadata": metadata,
        }

    def sync(
        self,
        run_id: str,
        owner: str,
        task: dict[str, Any],
        *,
        recovery: bool = False,
    ) -> dict[str, Any]:
        run_id = str(run_id or "").strip()
        owner = str(owner or "").strip()
        if not run_id or not owner:
            raise ValueError("run_id and owner are required")
        data = self._normalize(task)
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM tasks WHERE run_id=? AND task_id=?",
                (run_id, data["task_id"]),
            ).fetchone()
            by_key = db.execute(
                "SELECT * FROM tasks WHERE run_id=? AND idempotency_key=?",
                (run_id, data["idempotency_key"]),
            ).fetchone()
            if by_key is not None and (
                existing is None or by_key["task_id"] != existing["task_id"]
            ):
                raise TaskLedgerConflict(
                    "task idempotency key already belongs to another task"
                )
            if existing is None:
                db.execute(
                    "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, data["task_id"], owner, data["idempotency_key"],
                        data["objective"], data["state"], data["priority"],
                        _json(data["dependencies"]),
                        _json(data["required_capabilities"]),
                        _json(data["target_files"]),
                        _json(data["resource_locks"]),
                        data["side_effect_scope"], data["assigned_node_id"],
                        data["retry_count"], _json(data["metadata"]), now, now,
                    ),
                )
                from_state = None
                event_type = "TASK_REGISTERED"
            else:
                current = self._row(existing)
                if existing["owner"] != owner:
                    raise PermissionError("task belongs to another owner")
                if self._intent(current) != self._intent(data):
                    raise TaskLedgerConflict(
                        "task identity/idempotency key reused with different intent"
                    )
                from_state = current["state"]
                target = data["state"]
                allowed = target == from_state or target in TASK_TRANSITIONS.get(
                    from_state, set()
                )
                if (
                    not allowed
                    and recovery
                    and target == "QUEUED"
                    and from_state in RECOVERABLE_TO_QUEUED
                ):
                    allowed = True
                if not allowed:
                    raise TaskLedgerConflict(
                        f"invalid durable task transition {from_state} -> {target}"
                    )
                db.execute(
                    "UPDATE tasks SET state=?,assigned_node_id=?,retry_count=?,"
                    "metadata_json=?,updated_at=? WHERE run_id=? AND task_id=?",
                    (
                        target, data["assigned_node_id"], data["retry_count"],
                        _json(data["metadata"]), now, run_id, data["task_id"],
                    ),
                )
                event_type = (
                    "TASK_RECOVERED"
                    if recovery and target == "QUEUED" and from_state != target
                    else "TASK_STATE_CHANGED"
                    if from_state != target
                    else "TASK_SYNCED"
                )
            db.execute(
                "INSERT INTO task_events("
                "run_id,task_id,owner,event_type,from_state,to_state,payload_json,created_at"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (
                    run_id, data["task_id"], owner, event_type, from_state,
                    data["state"],
                    _json({
                        "assigned_node_id": data["assigned_node_id"],
                        "retry_count": data["retry_count"],
                    }),
                    now,
                ),
            )
            db.commit()
            row = db.execute(
                "SELECT * FROM tasks WHERE run_id=? AND task_id=?",
                (run_id, data["task_id"]),
            ).fetchone()
            return self._row(row)

    def task_info(self, run_id: str, owner: str, task_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM tasks WHERE run_id=? AND task_id=?",
                (str(run_id), str(task_id)),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("task not found")
        if row["owner"] != owner:
            raise PermissionError("task belongs to another owner")
        return self._row(row)

    def list_tasks(
        self,
        run_id: str,
        owner: str,
        *,
        states: list[str] | None = None,
    ) -> dict[str, Any]:
        wanted = None
        if states is not None:
            wanted = {str(item).upper() for item in states}
            if not wanted <= TASK_STATES:
                raise ValueError("invalid task state filter")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM tasks WHERE run_id=? ORDER BY created_at,task_id",
                (str(run_id),),
            ).fetchall()
        items = []
        for row in rows:
            if row["owner"] != owner:
                raise PermissionError("run tasks belong to another owner")
            item = self._row(row)
            if wanted is None or item["state"] in wanted:
                items.append(item)
        return {"run_id": str(run_id), "items": items, "count": len(items)}

    def events(
        self,
        run_id: str,
        owner: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        if after_seq < 0 or not 1 <= int(limit) <= 1000:
            raise ValueError("invalid task event cursor/limit")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM task_events WHERE run_id=? AND seq>? "
                "ORDER BY seq LIMIT ?",
                (str(run_id), int(after_seq), int(limit)),
            ).fetchall()
        items = []
        for row in rows:
            if row["owner"] != owner:
                raise PermissionError("task events belong to another owner")
            items.append({
                "seq": int(row["seq"]),
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "event_type": row["event_type"],
                "from_state": row["from_state"],
                "to_state": row["to_state"],
                "payload": _load(row["payload_json"], {}),
                "created_at": float(row["created_at"]),
            })
        return {
            "run_id": str(run_id),
            "after_seq": int(after_seq),
            "items": items,
            "count": len(items),
            "last_seq": items[-1]["seq"] if items else int(after_seq),
        }
