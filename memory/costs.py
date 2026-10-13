"""Selo: cost attribution ledger (accounting only, never admission).

Records observed token/cost usage linked to existing Run/WorkItem/Operation
ids. Budget enforcement stays with BudgetPolicyService / central authority;
this ledger only reports spend vs configured limits so hosts and diagnostics
can reconcile. All values are non-negative finite numbers.
"""
from __future__ import annotations

import math
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def _amount(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"{name} must be a non-negative finite number")
    return float(value)


class CostLedger:
    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        root = Path(state_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "selo_costs.sqlite3"
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cost_records(
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    workspace_id TEXT,
                    run_id TEXT,
                    work_item_id TEXT,
                    operation_id TEXT,
                    agent_id TEXT,
                    model TEXT NOT NULL,
                    input_tokens REAL NOT NULL,
                    output_tokens REAL NOT NULL,
                    cost REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS cost_owner_run ON cost_records(owner, run_id);
                CREATE INDEX IF NOT EXISTS cost_owner_agent ON cost_records(owner, agent_id);
                CREATE TABLE IF NOT EXISTS cost_budgets(
                    owner TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    limit_cost REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner, scope, scope_id)
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

    def record(self, owner: str, *, model: str, input_tokens: float = 0,
               output_tokens: float = 0, cost: float = 0,
               workspace_id: str | None = None, run_id: str | None = None,
               work_item_id: str | None = None, operation_id: str | None = None,
               agent_id: str | None = None) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("owner is required")
        model = str(model or "").strip()
        if not model or len(model) > 256:
            raise ValueError("model is required")
        if agent_id is not None and not _AGENT.fullmatch(str(agent_id)):
            raise ValueError("invalid agent_id")
        entry = {
            "input_tokens": _amount(input_tokens, "input_tokens"),
            "output_tokens": _amount(output_tokens, "output_tokens"),
            "cost": _amount(cost, "cost"),
        }
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO cost_records(owner,workspace_id,run_id,work_item_id,operation_id,"
                "agent_id,model,input_tokens,output_tokens,cost,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (owner, workspace_id, run_id, work_item_id, operation_id,
                 agent_id, model, entry["input_tokens"], entry["output_tokens"],
                 entry["cost"], self.clock()),
            )
            record_id = int(cursor.lastrowid)
        return {"record_id": record_id, **entry, "model": model,
                "authorizes_effects": False}

    def set_budget(self, owner: str, *, scope: str, scope_id: str, limit_cost: float) -> dict[str, Any]:
        if str(scope) not in {"owner", "workspace", "run", "agent"}:
            raise ValueError("invalid budget scope")
        if not str(scope_id or "").strip():
            raise ValueError("scope_id is required")
        limit = _amount(limit_cost, "limit_cost")
        with self._connect() as db:
            db.execute(
                "INSERT INTO cost_budgets VALUES(?,?,?,?,?) "
                "ON CONFLICT(owner,scope,scope_id) DO UPDATE SET limit_cost=excluded.limit_cost,"
                "updated_at=excluded.updated_at",
                (owner, scope, scope_id, limit, self.clock()),
            )
        return {"owner": owner, "scope": scope, "scope_id": scope_id, "limit_cost": limit}

    def totals(self, owner: str, *, run_id: str | None = None,
               agent_id: str | None = None,
               workspace_id: str | None = None) -> dict[str, Any]:
        where = ["owner=?"]
        params: list[Any] = [owner]
        for column, value in (("run_id", run_id), ("agent_id", agent_id),
                              ("workspace_id", workspace_id)):
            if value is not None:
                where.append(column + "=?")
                params.append(value)
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS records,COALESCE(SUM(input_tokens),0) AS input_tokens,"
                "COALESCE(SUM(output_tokens),0) AS output_tokens,COALESCE(SUM(cost),0) AS cost"
                " FROM cost_records WHERE " + " AND ".join(where), tuple(params),
            ).fetchone()
            budgets = db.execute("SELECT * FROM cost_budgets WHERE owner=?", (owner,)).fetchall()
        result = dict(row)
        over: list[dict[str, Any]] = []
        for budget in budgets:
            spent = result["cost"] if budget["scope"] == "owner" else None
            if spent is None:
                continue
            if spent > float(budget["limit_cost"]):
                over.append({"scope": budget["scope"], "scope_id": budget["scope_id"],
                             "limit_cost": budget["limit_cost"], "spent": spent})
        # Ledger reports; it never denies. Host consults BudgetPolicyService.
        return {**result, "budgets": [dict(b) for b in budgets],
                "over_budget": over, "enforces_admission": False}
