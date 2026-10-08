"""Hierarchical cost/quota budget policies for SENTRA governance."""
from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore

BUDGET_SCOPE_TYPES = {
    "instance", "workspace", "goal", "work_item", "run", "operation", "agent", "provider",
}
BUDGET_MODES = {"hard_stop", "warn"}
BUDGET_METRICS = {
    "actual_cost", "market_cost", "quota_usage",
    "input_tokens", "output_tokens", "reasoning_tokens", "total_tokens",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class BudgetExceeded(PermissionError):
    pass


class BudgetPolicyService:
    """Evaluates all applicable budgets; no role/cost source is inferred."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        governance: Any,
        store: ControlPlaneStore | None = None,
        clock=time.time,
    ) -> None:
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.path = self.store.path_for("budget_policy")
        self.governance = governance
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS budget_policies(
                    budget_policy_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT,
                    mode TEXT NOT NULL,
                    limits_json TEXT NOT NULL,
                    window_seconds REAL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_budget_policies_scope
                    ON budget_policies(owner,scope_type,scope_id,enabled);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return self.store.connect("budget_policy")

    @staticmethod
    def _normalize_limits(limits: dict[str, Any]) -> dict[str, float]:
        if not isinstance(limits, dict) or not limits:
            raise ValueError("budget limits must be a non-empty object")
        out: dict[str, float] = {}
        for key, raw in limits.items():
            name = str(key)
            if name not in BUDGET_METRICS:
                raise ValueError(f"unsupported budget metric: {name}")
            if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)) or float(raw) < 0:
                raise ValueError(f"budget limit {name} must be finite and non-negative")
            out[name] = float(raw)
        return out

    def set_policy(
        self,
        owner: str,
        *,
        scope_type: str,
        scope_id: str | None = None,
        limits: dict[str, Any],
        mode: str = "hard_stop",
        window_seconds: float | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope_type = str(scope_type or "").lower()
        mode = str(mode or "").lower()
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if scope_type not in BUDGET_SCOPE_TYPES:
            raise ValueError("invalid budget scope_type")
        if scope_type != "instance" and not str(scope_id or "").strip():
            raise ValueError("budget scope_id is required outside instance scope")
        if mode not in BUDGET_MODES:
            raise ValueError("budget mode must be hard_stop or warn")
        normalized = self._normalize_limits(limits)
        if window_seconds is not None:
            if not isinstance(window_seconds, (int, float)) or not 60 <= float(window_seconds) <= 31_536_000:
                raise ValueError("window_seconds must be 60..31536000")
            window_seconds = float(window_seconds)
        policy_id = "budget-" + uuid.uuid4().hex
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO budget_policies VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    policy_id, owner, scope_type,
                    str(scope_id).strip() if scope_id is not None else None,
                    mode, _json(normalized), window_seconds,
                    1 if enabled else 0, _json(dict(metadata or {})), now, now,
                ),
            )
        return self.info(policy_id, owner)

    def info(self, policy_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM budget_policies WHERE budget_policy_id=? AND owner=?",
                (policy_id, owner),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("budget policy not found")
        item = dict(row)
        item["limits"] = _load(item.pop("limits_json"), {})
        item["metadata"] = _load(item.pop("metadata_json"), {})
        item["enabled"] = bool(item["enabled"])
        return item

    def list_policies(self, owner: str, *, enabled_only: bool = False) -> dict[str, Any]:
        where = "owner=? AND enabled=1" if enabled_only else "owner=?"
        with self._connect() as db:
            rows = db.execute(
                f"SELECT budget_policy_id FROM budget_policies WHERE {where} ORDER BY created_at",
                (owner,),
            ).fetchall()
        return {"items": [self.info(str(row[0]), owner) for row in rows]}

    def set_enabled(self, policy_id: str, owner: str, *, enabled: bool) -> dict[str, Any]:
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        with self._connect() as db:
            changed = db.execute(
                "UPDATE budget_policies SET enabled=?,updated_at=? WHERE budget_policy_id=? AND owner=?",
                (int(enabled), self.clock(), policy_id, owner),
            ).rowcount
            if not changed:
                raise FileNotFoundError("budget policy not found")
        return self.info(policy_id, owner)

    @staticmethod
    def _policy_applies(policy: dict[str, Any], context: dict[str, Any]) -> bool:
        scope_type = policy["scope_type"]
        if scope_type == "instance":
            return True
        mapping = {
            "workspace": "workspace",
            "goal": "goal_id",
            "work_item": "work_item_id",
            "run": "run_id",
            "operation": "operation_id",
            "agent": "agent_id",
            "provider": "provider",
        }
        return str(context.get(mapping[scope_type]) or "") == str(policy.get("scope_id") or "")

    @staticmethod
    def _metric_value(summary: dict[str, Any], metric: str) -> float:
        if metric == "total_tokens":
            if "total_tokens" in summary:
                return float(summary["total_tokens"] or 0)
            return float(summary.get("input_tokens", 0) or 0) + float(
                summary.get("output_tokens", 0) or 0
            ) + float(summary.get("reasoning_tokens", 0) or 0)
        return float(summary.get(metric, 0) or 0)

    def _summary_for(self, owner: str, policy: dict[str, Any]) -> dict[str, Any]:
        where = ["owner=?"]
        params: list[Any] = [owner]
        mapping = {
            "workspace": "workspace",
            "goal": "goal_id",
            "work_item": "work_item_id",
            "run": "run_id",
            "operation": "operation_id",
            "agent": "agent_id",
            "provider": "provider",
        }
        if policy["scope_type"] != "instance":
            column = mapping[policy["scope_type"]]
            where.append(f"{column}=?")
            params.append(policy["scope_id"])
        if policy.get("window_seconds") is not None:
            where.append("created_at>=?")
            params.append(self.clock() - float(policy["window_seconds"]))
        clause = " AND ".join(where)
        with self.governance._connect() as db:
            row = db.execute(
                f"SELECT COALESCE(SUM(actual_cost),0) actual_cost,"
                f"COALESCE(SUM(market_cost),0) market_cost,"
                f"COALESCE(SUM(quota_usage),0) quota_usage,"
                f"COALESCE(SUM(input_tokens),0) input_tokens,"
                f"COALESCE(SUM(output_tokens),0) output_tokens,"
                f"COALESCE(SUM(reasoning_tokens),0) reasoning_tokens "
                f",COALESCE(SUM(input_tokens+output_tokens+CASE WHEN "
                f"json_extract(metadata_json,'$.reasoning_in_output')=1 THEN 0 ELSE reasoning_tokens END),0) total_tokens "
                f"FROM cost_events WHERE {clause}",
                tuple(params),
            ).fetchone()
        return {key: row[key] for key in row.keys()}

    def check(
        self,
        owner: str,
        *,
        workspace: str | None = None,
        goal_id: str | None = None,
        work_item_id: str | None = None,
        run_id: str | None = None,
        operation_id: str | None = None,
        agent_id: str | None = None,
        provider: str | None = None,
        proposed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = {
            "workspace": workspace,
            "goal_id": goal_id,
            "work_item_id": work_item_id,
            "run_id": run_id,
            "operation_id": operation_id,
            "agent_id": agent_id,
            "provider": provider,
        }
        proposed_values = {key: 0.0 for key in BUDGET_METRICS}
        for key, raw in dict(proposed or {}).items():
            if key not in BUDGET_METRICS:
                raise ValueError(f"unsupported proposed budget metric: {key}")
            if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)) or float(raw) < 0:
                raise ValueError("proposed budget values must be finite and non-negative")
            proposed_values[key] = float(raw)
        if proposed_values["total_tokens"] == 0:
            proposed_values["total_tokens"] = (
                proposed_values["input_tokens"]
                + proposed_values["output_tokens"]
                + proposed_values["reasoning_tokens"]
            )

        evaluations: list[dict[str, Any]] = []
        with self._connect() as db:
            rows = db.execute(
                "SELECT budget_policy_id FROM budget_policies "
                "WHERE owner=? AND enabled=1 ORDER BY created_at",
                (owner,),
            ).fetchall()
        for row in rows:
            policy = self.info(str(row["budget_policy_id"]), owner)
            if not self._policy_applies(policy, context):
                continue
            summary = self._summary_for(owner, policy)
            exceeded: dict[str, dict[str, float]] = {}
            remaining: dict[str, float] = {}
            for metric, limit in policy["limits"].items():
                current = self._metric_value(summary, metric)
                projected = current + proposed_values.get(metric, 0.0)
                remaining[metric] = max(0.0, float(limit) - current)
                if projected > float(limit):
                    exceeded[metric] = {
                        "current": current,
                        "proposed": proposed_values.get(metric, 0.0),
                        "projected": projected,
                        "limit": float(limit),
                    }
            evaluations.append({
                "budget_policy_id": policy["budget_policy_id"],
                "scope_type": policy["scope_type"],
                "scope_id": policy.get("scope_id"),
                "mode": policy["mode"],
                "limits": policy["limits"],
                "usage": {
                    **summary,
                    "total_tokens": self._metric_value(summary, "total_tokens"),
                },
                "remaining": remaining,
                "exceeded": exceeded,
            })
        blocking = [
            item for item in evaluations
            if item["mode"] == "hard_stop" and item["exceeded"]
        ]
        warnings = [
            item for item in evaluations
            if item["mode"] == "warn" and item["exceeded"]
        ]
        return {
            "allowed": not blocking,
            "blocking": blocking,
            "warnings": warnings,
            "evaluations": evaluations,
        }

    def require(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        decision = self.check(owner, **kwargs)
        if not decision["allowed"]:
            scopes = ", ".join(
                f"{item['scope_type']}:{item.get('scope_id') or '*'}"
                for item in decision["blocking"]
            )
            raise BudgetExceeded(f"budget hard-stop exceeded ({scopes})")
        return decision

    def reserve_quota(self, owner: str, *, event_id: str, **context: Any) -> dict[str, Any]:
        """Atomically admit one execution attempt against the shared cost ledger.

        The caller supplies a stable attempt identity. A reservation survives a
        crash and is never refunded implicitly, even if spawning subsequently
        fails. Zero monetary amounts mean unpriced admission, not free inference.
        """
        return self._quota_admission(owner,event_id=event_id,reserve=True,**context)

    def check_quota(self, owner: str, *, event_id: str, **context: Any) -> dict[str, Any]:
        """Inspect admission without counting an already reserved attempt twice."""
        return self._quota_admission(owner,event_id=event_id,reserve=False,**context)

    def _quota_admission(self, owner: str, *, event_id: str, reserve: bool,
                         **context: Any) -> dict[str, Any]:
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
            raise ValueError("invalid quota event identity")
        fields = ("workspace", "goal_id", "work_item_id", "run_id", "operation_id",
                  "agent_id", "provider")
        if set(context) - set(fields):
            raise ValueError("unsupported quota context")
        with self.governance._connect() as db:
            # All competing reservations serialize on the ledger writer, before
            # reading usage. check() reads committed usage through WAL.
            db.execute("BEGIN IMMEDIATE" if reserve else "BEGIN")
            previous = db.execute("SELECT * FROM cost_events WHERE cost_event_id=?",
                                  (event_id,)).fetchone()
            if previous is not None:
                if (previous["owner"] != owner or previous["quota_usage"] != 1 or
                        any(previous[key] != context.get(key) for key in fields)):
                    raise ValueError("quota event identity collision")
                return {**self.check(owner, **context), "idempotent_replay": True,
                        "cost_event_id": event_id}
            decision = self.check(owner, proposed={"quota_usage": 1}, **context)
            if not decision["allowed"] or not reserve:
                return decision
            db.execute(
                "INSERT INTO cost_events(cost_event_id,owner,created_at,workspace,goal_id,"
                "work_item_id,run_id,operation_id,agent_id,provider,model,currency,actual_cost,"
                "market_cost,quota_usage,input_tokens,output_tokens,reasoning_tokens,metadata_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,NULL,'USD',0,0,1,0,0,0,?)",
                (event_id, owner, self.clock(), *(context.get(key) for key in fields),
                 _json({"kind": "execution_admission", "pricing_known": False})),
            )
            db.commit()
        return {**decision, "idempotent_replay": False, "cost_event_id": event_id}
