"""Durable execution-workspace abstraction over sandbox/worktree/remote backends."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore


EXECUTION_WORKSPACE_STATES = {
    "PROVISIONING", "READY", "LEASED", "DIRTY", "VALIDATING",
    "PROMOTING", "PROMOTED", "DISCARDED", "FAILED",
}
EXECUTION_WORKSPACE_TRANSITIONS = {
    "PROVISIONING": {"READY", "FAILED", "DISCARDED"},
    "READY": {"LEASED", "DISCARDED", "FAILED"},
    "LEASED": {"READY", "DIRTY", "VALIDATING", "FAILED", "DISCARDED"},
    "DIRTY": {"LEASED", "VALIDATING", "DISCARDED", "FAILED"},
    "VALIDATING": {"DIRTY", "PROMOTING", "FAILED", "DISCARDED"},
    "PROMOTING": {"PROMOTED", "DIRTY", "FAILED"},
    "PROMOTED": set(),
    "DISCARDED": set(),
    "FAILED": {"DISCARDED"},
}


class ExecutionWorkspaceConflict(RuntimeError):
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


class ExecutionWorkspaceService:
    """Tracks logical workspaces while DurableRunService fences physical ownership."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        durable: Any,
        store: ControlPlaneStore | None = None,
        clock=time.time,
    ) -> None:
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.path = self.store.path_for("execution_workspace")
        self.durable = durable
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS execution_workspaces(
                    execution_workspace_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    authority_run_id TEXT NOT NULL,
                    work_item_id TEXT,
                    backend TEXT NOT NULL,
                    state TEXT NOT NULL,
                    physical_ref TEXT,
                    device_id TEXT,
                    base_revision TEXT,
                    current_revision TEXT,
                    lease_run_id TEXT,
                    fencing_token INTEGER,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_workspaces_work
                    ON execution_workspaces(owner,work_item_id,state);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return self.store.connect("execution_workspace")

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = _load(item.pop("metadata_json"), {})
        return item

    def create(
        self,
        owner: str,
        *,
        authority_run_id: str,
        work_item_id: str | None = None,
        backend: str,
        physical_ref: str | None = None,
        device_id: str | None = None,
        base_revision: str | None = None,
        metadata: dict[str, Any] | None = None,
        execution_workspace_id: str | None = None,
        initial_state: str = "PROVISIONING",
    ) -> dict[str, Any]:
        self.durable.run_status(authority_run_id, owner)
        state = str(initial_state or "").upper()
        if state not in EXECUTION_WORKSPACE_STATES:
            raise ValueError("invalid execution workspace state")
        backend = str(backend or "").strip().lower()
        if backend not in {"sandbox", "worktree", "workspace", "remote", "vm", "container"}:
            raise ValueError("unsupported execution workspace backend")
        wid = str(execution_workspace_id or f"xws-{uuid.uuid4().hex}")
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO execution_workspaces VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    wid, owner, authority_run_id, work_item_id, backend, state,
                    physical_ref, device_id, base_revision, base_revision,
                    None, None, _json(dict(metadata or {})), now, now,
                ),
            )
        return self.info(wid, owner)

    def info(self, execution_workspace_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM execution_workspaces WHERE execution_workspace_id=? AND owner=?",
                (execution_workspace_id, owner),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("execution workspace not found")
        return self._row(row)

    def transition(
        self,
        execution_workspace_id: str,
        owner: str,
        state: str,
        *,
        current_revision: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = str(state or "").upper()
        if target not in EXECUTION_WORKSPACE_STATES:
            raise ValueError("invalid execution workspace state")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM execution_workspaces WHERE execution_workspace_id=? AND owner=?",
                (execution_workspace_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("execution workspace not found")
            current = str(row["state"])
            if target != current and target not in EXECUTION_WORKSPACE_TRANSITIONS.get(current, set()):
                raise ExecutionWorkspaceConflict(
                    f"invalid execution workspace transition {current} -> {target}"
                )
            merged = _load(row["metadata_json"], {})
            merged.update(dict(metadata or {}))
            db.execute(
                "UPDATE execution_workspaces SET state=?,current_revision=COALESCE(?,current_revision),"
                "metadata_json=?,updated_at=? WHERE execution_workspace_id=?",
                (target, current_revision, _json(merged), self.clock(), execution_workspace_id),
            )
            db.commit()
        return self.info(execution_workspace_id, owner)

    def acquire(
        self,
        execution_workspace_id: str,
        owner: str,
        *,
        execution_run_id: str,
        operation_id: str | None = None,
        ttl_s: float = 300.0,
    ) -> dict[str, Any]:
        self.durable.run_status(execution_run_id, owner)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM execution_workspaces WHERE execution_workspace_id=? AND owner=?",
                (execution_workspace_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("execution workspace not found")
            if row["state"] not in {"READY", "DIRTY", "LEASED"}:
                raise ExecutionWorkspaceConflict(
                    f"workspace state {row['state']} cannot be leased"
                )
            if row["lease_run_id"] and row["lease_run_id"] != execution_run_id:
                # Durable lease remains the final arbiter; stale materialized ownership
                # is cleared only after the referenced run is terminal.
                try:
                    previous = self.durable.run_status(str(row["lease_run_id"]), owner)
                    terminal = previous.get("state") in {"SUCCEEDED", "FAILED", "CANCELLED"}
                except FileNotFoundError:
                    terminal = True
                if not terminal:
                    raise ExecutionWorkspaceConflict(
                        f"workspace is leased by live run {row['lease_run_id']}"
                    )
                db.execute(
                    "UPDATE execution_workspaces SET lease_run_id=NULL,fencing_token=NULL "
                    "WHERE execution_workspace_id=?",
                    (execution_workspace_id,),
                )
            lease = self.durable.acquire_lease(
                execution_run_id,
                owner,
                f"execution-workspace:{execution_workspace_id}",
                operation_id=operation_id,
                ttl_s=ttl_s,
            )
            db.execute(
                "UPDATE execution_workspaces SET state='LEASED',lease_run_id=?,"
                "fencing_token=?,updated_at=? WHERE execution_workspace_id=?",
                (
                    execution_run_id, int(lease["fencing_token"]), self.clock(),
                    execution_workspace_id,
                ),
            )
            db.commit()
        return {"workspace": self.info(execution_workspace_id, owner), "lease": lease}

    def renew(
        self,
        execution_workspace_id: str,
        owner: str,
        *,
        fencing_token: int,
        ttl_s: float = 300.0,
    ) -> dict[str, Any]:
        item = self.info(execution_workspace_id, owner)
        if item.get("fencing_token") != fencing_token:
            raise ExecutionWorkspaceConflict("stale execution-workspace fencing token")
        lease = self.durable.renew_lease(
            f"execution-workspace:{execution_workspace_id}",
            owner,
            fencing_token,
            ttl_s=ttl_s,
        )
        return {"workspace": self.info(execution_workspace_id, owner), "lease": lease}

    def release(
        self,
        execution_workspace_id: str,
        owner: str,
        *,
        fencing_token: int,
        dirty: bool = False,
    ) -> dict[str, Any]:
        item = self.info(execution_workspace_id, owner)
        if item.get("fencing_token") != fencing_token:
            raise ExecutionWorkspaceConflict("stale execution-workspace fencing token")
        self.durable.release_lease(
            f"execution-workspace:{execution_workspace_id}", owner, fencing_token
        )
        target = "DIRTY" if dirty else "READY"
        with self._connect() as db:
            db.execute(
                "UPDATE execution_workspaces SET state=?,lease_run_id=NULL,fencing_token=NULL,"
                "updated_at=? WHERE execution_workspace_id=? AND fencing_token=?",
                (target, self.clock(), execution_workspace_id, fencing_token),
            )
        return self.info(execution_workspace_id, owner)
