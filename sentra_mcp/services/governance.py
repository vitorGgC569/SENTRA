"""Governance and operational control primitives for SENTRA.

This module intentionally complements DurableRunService rather than replacing it.
Durable Run/Operation state remains the execution authority; governance adds the
product/control-plane objects needed to operate many agents safely: universal
work items, compare-and-clear checkout/execution ownership, review/approval
policies, retry/recovery policy, activity/cost ledgers, routines, versioned
secrets, work products, skills and plugin capability manifests.
"""
from __future__ import annotations

import hashlib
import json
import math
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from sentra_remote.secrets import protect_secret, unprotect_secret

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore


WORK_ITEM_STATES = {
    "PENDING", "QUEUED", "RUNNING", "VALIDATING", "REPAIRING",
    "IN_REVIEW", "APPROVAL_REQUIRED", "CHANGES_REQUESTED",
    "READY_FOR_PROMOTION", "RECOVERING", "BLOCKED",
    "COMPLETED", "FAILED", "CANCELLED",
}
TERMINAL_WORK_ITEM_STATES = {"COMPLETED", "FAILED", "CANCELLED"}
WORK_ITEM_TRANSITIONS = {
    "PENDING": {"QUEUED", "RUNNING", "BLOCKED", "CANCELLED"},
    "QUEUED": {"RUNNING", "BLOCKED", "FAILED", "CANCELLED"},
    "RUNNING": {"VALIDATING", "REPAIRING", "RECOVERING", "BLOCKED", "FAILED", "CANCELLED"},
    "VALIDATING": {"REPAIRING", "IN_REVIEW", "APPROVAL_REQUIRED", "READY_FOR_PROMOTION", "FAILED", "CANCELLED"},
    "REPAIRING": {"RUNNING", "VALIDATING", "BLOCKED", "FAILED", "CANCELLED"},
    "IN_REVIEW": {"CHANGES_REQUESTED", "APPROVAL_REQUIRED", "READY_FOR_PROMOTION", "FAILED", "CANCELLED"},
    "APPROVAL_REQUIRED": {"CHANGES_REQUESTED", "READY_FOR_PROMOTION", "FAILED", "CANCELLED"},
    "CHANGES_REQUESTED": {"RUNNING", "VALIDATING", "CANCELLED"},
    "READY_FOR_PROMOTION": {"COMPLETED", "REPAIRING", "FAILED", "CANCELLED"},
    "RECOVERING": {"QUEUED", "RUNNING", "BLOCKED", "FAILED", "CANCELLED"},
    "BLOCKED": {"QUEUED", "RUNNING", "RECOVERING", "FAILED", "CANCELLED"},
    "COMPLETED": set(), "FAILED": set(), "CANCELLED": set(),
}
RECOVERY_CLASSES = {
    "OBSERVE_ONLY", "STATUS_REPAIR", "RESOURCE_CLEANUP",
    "CONVERSATION_REATTACH", "SOURCE_CONTINUATION", "SIDE_EFFECT_RETRY",
}
RECOVERY_CAPABILITIES = {
    "OBSERVE_ONLY": frozenset({"read"}),
    "STATUS_REPAIR": frozenset({"read", "status"}),
    "RESOURCE_CLEANUP": frozenset({"read", "status", "cleanup"}),
    "CONVERSATION_REATTACH": frozenset({"read", "status", "chat_rebind"}),
    "SOURCE_CONTINUATION": frozenset({"read", "status", "chat_rebind", "source_write"}),
    "SIDE_EFFECT_RETRY": frozenset({"read", "status", "chat_rebind", "source_write", "side_effect"}),
}
ROUTINE_ACTIVE_POLICIES = {"coalesce_if_active", "skip_if_active", "always_enqueue"}
ROUTINE_MISSED_POLICIES = {"skip_missed", "enqueue_missed_with_cap"}
DECISIONS = {"approved", "changes_requested", "rejected"}
SCOPE_TYPES = {"instance", "workspace", "project", "goal", "agent", "user"}
PLUGIN_STATES = {"REGISTERED", "VERIFIED", "DISABLED", "FAILED"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _text(name: str, value: Any, maximum: int, *, required: bool = False) -> str:
    out = str(value or "").strip()
    if required and not out:
        raise ValueError(f"{name} is required")
    if len(out) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return out


def _strings(name: str, value: Any, *, maximum: int = 1000) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)) or len(value) > maximum:
        raise ValueError(f"{name} must contain at most {maximum} strings")
    out: list[str] = []
    for raw in value:
        item = _text(name, raw, 4000, required=True)
        if item not in out:
            out.append(item)
    return out


def _dict(name: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return dict(value)


class GovernanceConflict(RuntimeError):
    """Raised when an ownership/policy transition conflicts with live authority."""


class GovernanceService:
    """Persistent governance state colocated with SENTRA durable state."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        durable: Any | None = None,
        store: ControlPlaneStore | None = None,
        clock=time.time,
    ) -> None:
        self.state_root = Path(state_root).resolve()
        self.root = self.state_root / "durable"
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store or SQLiteControlPlaneStore(self.state_root)
        self.path = self.store.path_for("governance")
        self.durable = durable
        self.clock = clock
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return self.store.connect("governance")

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_items(
                    work_item_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    goal_id TEXT,
                    external_key TEXT,
                    parent_work_item_id TEXT,
                    objective TEXT NOT NULL,
                    acceptance_criteria_json TEXT NOT NULL,
                    blockers_json TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    assignee_agent_id TEXT,
                    assignee_user_id TEXT,
                    required_capabilities_json TEXT NOT NULL,
                    target_files_json TEXT NOT NULL,
                    resource_locks_json TEXT NOT NULL,
                    side_effect_scope TEXT NOT NULL,
                    execution_policy_json TEXT NOT NULL,
                    execution_state_json TEXT NOT NULL,
                    retry_policy_json TEXT NOT NULL,
                    recovery_class TEXT,
                    state TEXT NOT NULL,
                    checkout_run_id TEXT,
                    execution_run_id TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    failure_chain_id TEXT,
                    budget_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(owner, external_key)
                );
                CREATE INDEX IF NOT EXISTS idx_work_items_run_state
                    ON work_items(run_id,state,updated_at);
                CREATE INDEX IF NOT EXISTS idx_work_items_assignee
                    ON work_items(owner,assignee_agent_id,state);

                CREATE TABLE IF NOT EXISTS work_item_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    owner TEXT NOT NULL,
                    work_item_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_work_item_events_item
                    ON work_item_events(work_item_id,seq);

                CREATE TABLE IF NOT EXISTS review_decisions(
                    decision_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    work_item_id TEXT NOT NULL,
                    stage_id TEXT NOT NULL,
                    stage_type TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS activity_events(
                    event_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT,
                    workspace TEXT,
                    goal_id TEXT,
                    work_item_id TEXT,
                    run_id TEXT,
                    operation_id TEXT,
                    agent_id TEXT,
                    chat_id TEXT,
                    device_id TEXT,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    causation_id TEXT,
                    correlation_id TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_activity_owner_time
                    ON activity_events(owner,created_at DESC);

                CREATE TABLE IF NOT EXISTS cost_events(
                    cost_event_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    workspace TEXT,
                    goal_id TEXT,
                    work_item_id TEXT,
                    run_id TEXT,
                    operation_id TEXT,
                    agent_id TEXT,
                    provider TEXT,
                    model TEXT,
                    currency TEXT NOT NULL,
                    actual_cost REAL NOT NULL,
                    market_cost REAL NOT NULL,
                    quota_usage REAL NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    reasoning_tokens INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cost_owner_time
                    ON cost_events(owner,created_at DESC);

                CREATE TABLE IF NOT EXISTS routines(
                    routine_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    trigger_kind TEXT NOT NULL,
                    trigger_spec_json TEXT NOT NULL,
                    active_policy TEXT NOT NULL,
                    missed_policy TEXT NOT NULL,
                    missed_cap INTEGER NOT NULL,
                    work_template_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    next_due_at REAL,
                    last_fired_at REAL,
                    active_work_item_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(owner,name)
                );

                CREATE TABLE IF NOT EXISTS secret_entries(
                    secret_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT,
                    current_version INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(owner,name,scope_type,scope_id)
                );
                CREATE TABLE IF NOT EXISTS secret_versions(
                    secret_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    protected_value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(secret_id,version)
                );
                CREATE TABLE IF NOT EXISTS secret_bindings(
                    binding_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    secret_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    env_name TEXT,
                    purpose TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS secret_access_events(
                    access_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    secret_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT,
                    purpose TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_products(
                    work_product_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    work_item_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(work_item_id,artifact_id,kind)
                );

                CREATE TABLE IF NOT EXISTS skills(
                    skill_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    source TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(owner,name,version)
                );

                CREATE TABLE IF NOT EXISTS plugins(
                    plugin_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    declared_capabilities_json TEXT NOT NULL,
                    verified_methods_json TEXT NOT NULL,
                    narrowed_capabilities_json TEXT NOT NULL,
                    effective_capabilities_json TEXT NOT NULL,
                    trusted_ui INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(owner,name,version)
                );
                """
            )

    def _run_terminal(self, run_id: str | None, owner: str) -> bool:
        if not run_id:
            return True
        if self.durable is None:
            return False
        try:
            item = self.durable.run_status(str(run_id), owner)
        except FileNotFoundError:
            return True
        return str(item.get("state")) in {"SUCCEEDED", "FAILED", "CANCELLED"}

    def _append_work_event(
        self, db: sqlite3.Connection, owner: str, work_item_id: str,
        event_type: str, payload: dict[str, Any],
    ) -> str:
        event_id = _id("wie")
        db.execute(
            "INSERT INTO work_item_events VALUES(?,?,?,?,?,?,?)",
            (None, event_id, owner, work_item_id, event_type, _json(payload), self.clock()),
        )
        return event_id

    def activity(
        self, owner: str, action: str, outcome: str, *,
        actor_type: str = "system", actor_id: str | None = None,
        workspace: str | None = None, goal_id: str | None = None,
        work_item_id: str | None = None, run_id: str | None = None,
        operation_id: str | None = None, agent_id: str | None = None,
        chat_id: str | None = None, device_id: str | None = None,
        evidence: list[str] | None = None, causation_id: str | None = None,
        correlation_id: str | None = None, payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = _id("act")
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO activity_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id, owner, now, _text("actor_type", actor_type, 80, required=True),
                    _text("actor_id", actor_id, 256), workspace, goal_id, work_item_id,
                    run_id, operation_id, agent_id, chat_id, device_id,
                    _text("action", action, 160, required=True),
                    _text("outcome", outcome, 80, required=True),
                    _json(_strings("evidence", evidence)), causation_id, correlation_id,
                    _json(_dict("payload", payload)),
                ),
            )
        return {"event_id": event_id, "created_at": now, "action": action, "outcome": outcome}

    def list_activity(self, owner: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid activity page")
        with self._connect() as db:
            total = int(db.execute(
                "SELECT COUNT(*) FROM activity_events WHERE owner=?", (owner,)
            ).fetchone()[0])
            rows = db.execute(
                "SELECT * FROM activity_events WHERE owner=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (owner, limit, offset),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = _load(item.pop("evidence_json"), [])
            item["payload"] = _load(item.pop("payload_json"), {})
            items.append(item)
        next_offset = offset + len(items)
        return {"items": items, "page": {"offset": offset, "limit": limit, "returned": len(items),
                "total": total, "next_offset": next_offset if next_offset < total else None}}

    @staticmethod
    def _default_retry_policy() -> dict[str, Any]:
        return {
            "max_attempts": 3,
            "backoff": {"kind": "exponential", "initial_s": 5.0, "max_s": 300.0},
            "retryable_error_classes": ["dependency", "transport", "rate_limit"],
            "requires_same_agent": False,
            "requires_same_session": False,
            "side_effect_replay_policy": "RECONCILE_FIRST",
            "exhausted_action": "REQUIRE_OPERATOR",
        }

    @staticmethod
    def _validate_retry_policy(value: dict[str, Any] | None) -> dict[str, Any]:
        policy = GovernanceService._default_retry_policy()
        policy.update(_dict("retry_policy", value))
        attempts = policy.get("max_attempts")
        if type(attempts) is not int or not 0 <= attempts <= 100:
            raise ValueError("retry_policy.max_attempts must be 0..100")
        exhausted = str(policy.get("exhausted_action") or "").upper()
        if exhausted not in {"BLOCK", "ESCALATE", "RECONCILE", "NEW_WORK_ITEM", "REQUIRE_OPERATOR"}:
            raise ValueError("invalid retry_policy.exhausted_action")
        policy["exhausted_action"] = exhausted
        replay = str(policy.get("side_effect_replay_policy") or "").upper()
        if replay not in {"NEVER", "RECONCILE_FIRST", "SAFE_ONLY"}:
            raise ValueError("invalid retry_policy.side_effect_replay_policy")
        policy["side_effect_replay_policy"] = replay
        policy["retryable_error_classes"] = _strings(
            "retryable_error_classes", policy.get("retryable_error_classes")
        )
        return policy

    @staticmethod
    def _validate_execution_policy(value: dict[str, Any] | None) -> dict[str, Any]:
        policy = _dict("execution_policy", value)
        stages = policy.get("stages") or []
        if not isinstance(stages, list) or len(stages) > 20:
            raise ValueError("execution_policy.stages must be a list of at most 20 stages")
        normalized = []
        seen: set[str] = set()
        for raw in stages:
            if not isinstance(raw, dict):
                raise ValueError("execution policy stage must be an object")
            stage_id = _text("stage.id", raw.get("id"), 128, required=True)
            if stage_id in seen:
                raise ValueError("execution policy stage ids must be unique")
            seen.add(stage_id)
            stage_type = str(raw.get("type") or "").lower()
            if stage_type not in {"review", "approval"}:
                raise ValueError("execution policy stage type must be review or approval")
            normalized.append({
                "id": stage_id,
                "type": stage_type,
                "actor_agent_id": _text("actor_agent_id", raw.get("actor_agent_id"), 128) or None,
                "actor_user_id": _text("actor_user_id", raw.get("actor_user_id"), 256) or None,
                "allow_any_authorized": bool(raw.get("allow_any_authorized", False)),
            })
        require_quality_gate = policy.get("require_quality_gate", True)
        if type(require_quality_gate) is not bool:
            raise ValueError("execution_policy.require_quality_gate must be boolean")
        return {
            "stages": normalized,
            "require_quality_gate": require_quality_gate,
        }

    @staticmethod
    def _require_quality_validation(
        policy: dict[str, Any], execution_state: dict[str, Any]
    ) -> None:
        if not policy.get("require_quality_gate", True):
            return
        gate = dict(execution_state.get("quality_gate") or {})
        if gate.get("status") != "passed" or gate.get("passed") is not True:
            raise GovernanceConflict(
                "deterministic quality validation has not passed"
            )

    @staticmethod
    def _work_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in (
            "acceptance_criteria_json", "blockers_json", "dependencies_json",
            "required_capabilities_json", "target_files_json", "resource_locks_json",
            "execution_policy_json", "execution_state_json", "retry_policy_json",
            "budget_json", "metadata_json",
        ):
            item[key[:-5]] = _load(item.pop(key), [] if key.endswith((
                "criteria_json", "blockers_json", "dependencies_json", "capabilities_json",
                "files_json", "locks_json"
            )) else {})
        item["terminal"] = item["state"] in TERMINAL_WORK_ITEM_STATES
        return item

    def create_work_item(
        self, run_id: str, owner: str, *, objective: str,
        goal_id: str | None = None, external_key: str | None = None,
        parent_work_item_id: str | None = None, acceptance_criteria: list[str] | None = None,
        blockers: list[str] | None = None, dependencies: list[str] | None = None,
        assignee_agent_id: str | None = None, assignee_user_id: str | None = None,
        required_capabilities: list[str] | None = None, target_files: list[str] | None = None,
        resource_locks: list[str] | None = None, side_effect_scope: str = "workspace",
        execution_policy: dict[str, Any] | None = None,
        retry_policy: dict[str, Any] | None = None, budget: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None, work_item_id: str | None = None,
    ) -> dict[str, Any]:
        wid = _text("work_item_id", work_item_id or _id("work"), 128, required=True)
        now = self.clock()
        ep = self._validate_execution_policy(execution_policy)
        rp = self._validate_retry_policy(retry_policy)
        with self._connect() as db:
            if parent_work_item_id:
                parent = db.execute(
                    "SELECT owner,run_id FROM work_items WHERE work_item_id=?", (parent_work_item_id,)
                ).fetchone()
                if parent is None or parent["owner"] != owner or parent["run_id"] != run_id:
                    raise ValueError("parent work item must belong to the same owner/run")
            try:
                db.execute(
                    "INSERT INTO work_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        wid, owner, run_id, goal_id, external_key, parent_work_item_id,
                        _text("objective", objective, 100000, required=True),
                        _json(_strings("acceptance_criteria", acceptance_criteria)),
                        _json(_strings("blockers", blockers)),
                        _json(_strings("dependencies", dependencies)),
                        assignee_agent_id, assignee_user_id,
                        _json(_strings("required_capabilities", required_capabilities)),
                        _json(_strings("target_files", target_files)),
                        _json(_strings("resource_locks", resource_locks)),
                        _text("side_effect_scope", side_effect_scope, 80, required=True),
                        _json(ep), _json({}), _json(rp), None, "PENDING", None, None, 0, None,
                        _json(_dict("budget", budget)), _json(_dict("metadata", metadata)), now, now,
                    ),
                )
            except sqlite3.IntegrityError:
                if external_key:
                    row = db.execute(
                        "SELECT * FROM work_items WHERE owner=? AND external_key=?",
                        (owner, external_key),
                    ).fetchone()
                    if row is not None:
                        return self._work_row(row)
                raise
            self._append_work_event(db, owner, wid, "WORK_ITEM_CREATED", {"state": "PENDING"})
        self.activity(owner, "work_item.create", "ok", work_item_id=wid, run_id=run_id,
                      goal_id=goal_id, agent_id=assignee_agent_id)
        return self.work_item_info(wid, owner)

    def work_item_info(self, work_item_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("work item not found")
        return self._work_row(row)

    def list_work_items(
        self, owner: str, *, run_id: str | None = None, states: list[str] | None = None,
        limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid work item page")
        params: list[Any] = [owner]
        where = ["owner=?"]
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        normalized_states = [str(x).upper() for x in (states or [])]
        if normalized_states:
            if any(x not in WORK_ITEM_STATES for x in normalized_states):
                raise ValueError("invalid work item state filter")
            where.append("state IN (" + ",".join("?" for _ in normalized_states) + ")")
            params.extend(normalized_states)
        clause = " AND ".join(where)
        with self._connect() as db:
            total = int(db.execute(
                f"SELECT COUNT(*) FROM work_items WHERE {clause}", tuple(params)
            ).fetchone()[0])
            rows = db.execute(
                f"SELECT * FROM work_items WHERE {clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        items = [self._work_row(row) for row in rows]
        next_offset = offset + len(items)
        return {"items": items, "page": {"offset": offset, "limit": limit, "returned": len(items),
                "total": total, "next_offset": next_offset if next_offset < total else None}}

    def transition_work_item(
        self, work_item_id: str, owner: str, state: str, *,
        reason: str = "", metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = str(state or "").upper()
        if target not in WORK_ITEM_STATES:
            raise ValueError("invalid work item state")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            current = str(row["state"])
            if current == "RECOVERING" and target in {"QUEUED", "RUNNING"}:
                raise GovernanceConflict(
                    "recovery handoff must use complete_recovery before normal execution resumes"
                )
            if target != current and target not in WORK_ITEM_TRANSITIONS.get(current, set()):
                raise GovernanceConflict(f"invalid work item transition {current} -> {target}")
            policy = self._validate_execution_policy(
                _load(row["execution_policy_json"], {})
            )
            execution_state = _load(row["execution_state_json"], {})
            quality_gate = dict(execution_state.get("quality_gate") or {})
            if (
                target in {"IN_REVIEW", "APPROVAL_REQUIRED", "READY_FOR_PROMOTION"}
                and policy["require_quality_gate"]
                and (
                    quality_gate.get("status") != "passed"
                    or quality_gate.get("passed") is not True
                )
            ):
                raise GovernanceConflict(
                    "deterministic Quality Gate must pass before review, approval or promotion"
                )
            now = self.clock()
            if (
                target in {"RUNNING", "REPAIRING"}
                and target != current
                and quality_gate
            ):
                quality_gate.update({
                    "passed": False,
                    "status": "stale",
                    "invalidated_at": now,
                    "invalidated_by_transition": f"{current}->{target}",
                })
                execution_state["quality_gate"] = quality_gate
            merged = _load(row["metadata_json"], {})
            merged.update(_dict("metadata", metadata))
            db.execute(
                "UPDATE work_items SET state=?,metadata_json=?,execution_state_json=?,updated_at=? "
                "WHERE work_item_id=?",
                (target, _json(merged), _json(execution_state), now, work_item_id),
            )
            self._append_work_event(
                db, owner, work_item_id, "WORK_ITEM_STATE_CHANGED",
                {"from": current, "to": target, "reason": _text("reason", reason, 4000)},
            )
        self.activity(owner, "work_item.transition", "ok", work_item_id=work_item_id,
                      run_id=str(row["run_id"]), payload={"from": current, "to": target, "reason": reason})
        return self.work_item_info(work_item_id, owner)

    def _self_heal_lock(
        self, db: sqlite3.Connection, row: sqlite3.Row, owner: str, column: str,
    ) -> sqlite3.Row:
        existing = row[column]
        if existing and self._run_terminal(str(existing), owner):
            db.execute(
                f"UPDATE work_items SET {column}=NULL,updated_at=? WHERE work_item_id=? AND {column}=?",
                (self.clock(), row["work_item_id"], existing),
            )
            self._append_work_event(
                db, owner, row["work_item_id"], "STALE_WORK_LOCK_CLEARED",
                {"column": column, "run_id": existing},
            )
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=?", (row["work_item_id"],)
            ).fetchone()
        return row

    def checkout(
        self, work_item_id: str, owner: str, *, run_id: str, agent_id: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            row = self._self_heal_lock(db, row, owner, "checkout_run_id")
            current = row["checkout_run_id"]
            if current and current != run_id:
                raise GovernanceConflict(f"work item is checked out by live run {current}")
            db.execute(
                "UPDATE work_items SET checkout_run_id=?,assignee_agent_id=COALESCE(?,assignee_agent_id),"
                "updated_at=? WHERE work_item_id=?",
                (run_id, agent_id, self.clock(), work_item_id),
            )
            self._append_work_event(db, owner, work_item_id, "WORK_ITEM_CHECKED_OUT",
                                    {"run_id": run_id, "agent_id": agent_id})
            db.commit()
        self.activity(owner, "work_item.checkout", "ok", work_item_id=work_item_id,
                      run_id=run_id, agent_id=agent_id)
        return self.work_item_info(work_item_id, owner)

    def start_execution(
        self, work_item_id: str, owner: str, *, run_id: str, agent_id: str | None = None,
        expected_state: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            if expected_state is not None:
                if row["state"] != expected_state or _load(row["blockers_json"], []):
                    raise GovernanceConflict("work item admission state changed or is blocked")
                for dependency in _load(row["dependencies_json"], []):
                    dependency_row = db.execute(
                        "SELECT state FROM work_items WHERE work_item_id=? AND owner=?",
                        (dependency, owner),
                    ).fetchone()
                    if dependency_row is None or dependency_row["state"] != "COMPLETED":
                        raise GovernanceConflict("work item dependency is not completed")
            if str(row["state"]) == "RECOVERING":
                raise GovernanceConflict(
                    "complete recovery handoff before normal execution resumes"
                )
            row = self._self_heal_lock(db, row, owner, "execution_run_id")
            current = row["execution_run_id"]
            if current and current != run_id:
                raise GovernanceConflict(f"work item execution is owned by live run {current}")
            checkout = row["checkout_run_id"]
            if checkout and checkout != run_id and not self._run_terminal(str(checkout), owner):
                raise GovernanceConflict(f"checkout belongs to different live run {checkout}")
            now = self.clock()
            execution_state = _load(row["execution_state_json"], {})
            quality_gate = dict(execution_state.get("quality_gate") or {})
            if quality_gate:
                quality_gate.update({
                    "passed": False,
                    "status": "stale",
                    "invalidated_at": now,
                    "invalidated_by_transition": f"{row['state']}->RUNNING",
                })
                execution_state["quality_gate"] = quality_gate
            db.execute(
                "UPDATE work_items SET checkout_run_id=?,execution_run_id=?,"
                "assignee_agent_id=COALESCE(?,assignee_agent_id),state='RUNNING',"
                "execution_state_json=?,updated_at=? WHERE work_item_id=?",
                (run_id, run_id, agent_id, _json(execution_state), now, work_item_id),
            )
            self._append_work_event(db, owner, work_item_id, "WORK_ITEM_EXECUTION_STARTED",
                                    {"run_id": run_id, "agent_id": agent_id})
            db.commit()
        self.activity(owner, "work_item.execution.start", "ok", work_item_id=work_item_id,
                      run_id=run_id, agent_id=agent_id)
        return self.work_item_info(work_item_id, owner)

    def release_run_locks(self, work_item_id: str, owner: str, *, run_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            cleared = []
            for column in ("checkout_run_id", "execution_run_id"):
                cur = db.execute(
                    f"UPDATE work_items SET {column}=NULL,updated_at=? "
                    f"WHERE work_item_id=? AND {column}=?",
                    (self.clock(), work_item_id, run_id),
                )
                if cur.rowcount:
                    cleared.append(column)
            self._append_work_event(db, owner, work_item_id, "WORK_ITEM_LOCKS_RELEASED",
                                    {"run_id": run_id, "cleared": cleared})
        self.activity(owner, "work_item.locks.release", "ok", work_item_id=work_item_id,
                      run_id=run_id, payload={"cleared": cleared})
        return {"work_item": self.work_item_info(work_item_id, owner), "cleared": cleared}

    def record_failure(
        self, work_item_id: str, owner: str, *, error_class: str,
        side_effect_may_have_started: bool, failure_chain_id: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            policy = self._validate_retry_policy(_load(row["retry_policy_json"], {}))
            chain = failure_chain_id or row["failure_chain_id"] or _id("failchain")
            count = int(row["retry_count"]) + 1
            retryable = error_class in set(policy["retryable_error_classes"])
            replay_policy = policy["side_effect_replay_policy"]
            replay_safe = not side_effect_may_have_started or replay_policy == "SAFE_ONLY"
            if side_effect_may_have_started and replay_policy == "NEVER":
                retryable = False
            if side_effect_may_have_started and replay_policy == "RECONCILE_FIRST":
                next_action = "RECONCILE"
            elif retryable and count <= int(policy["max_attempts"]):
                next_action = "RETRY"
            else:
                next_action = policy["exhausted_action"]
            target = "RECOVERING" if next_action in {"RECONCILE", "RETRY"} else "BLOCKED"
            db.execute(
                "UPDATE work_items SET retry_count=?,failure_chain_id=?,state=?,updated_at=? "
                "WHERE work_item_id=?",
                (count, chain, target, self.clock(), work_item_id),
            )
            self._append_work_event(
                db, owner, work_item_id, "WORK_ITEM_FAILURE_RECORDED",
                {"error_class": error_class, "attempt": count, "failure_chain_id": chain,
                 "side_effect_may_have_started": side_effect_may_have_started,
                 "replay_safe": replay_safe, "next_action": next_action},
            )
        return {"work_item": self.work_item_info(work_item_id, owner), "next_action": next_action,
                "attempt": count, "failure_chain_id": chain, "replay_safe": replay_safe}

    def begin_recovery(
        self, work_item_id: str, owner: str, *, recovery_class: str,
        run_id: str | None = None, agent_id: str | None = None,
    ) -> dict[str, Any]:
        rc = str(recovery_class or "").upper()
        if rc not in RECOVERY_CLASSES:
            raise ValueError("invalid recovery class")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            db.execute(
                "UPDATE work_items SET recovery_class=?,state='RECOVERING',updated_at=? "
                "WHERE work_item_id=?",
                (rc, self.clock(), work_item_id),
            )
            self._append_work_event(
                db, owner, work_item_id, "WORK_ITEM_RECOVERY_STARTED",
                {"recovery_class": rc, "run_id": run_id, "agent_id": agent_id,
                 "capabilities": sorted(RECOVERY_CAPABILITIES[rc])},
            )
        self.activity(owner, "work_item.recovery.start", "ok", work_item_id=work_item_id,
                      run_id=run_id, agent_id=agent_id, payload={"recovery_class": rc})
        return {"work_item": self.work_item_info(work_item_id, owner),
                "recovery_capabilities": sorted(RECOVERY_CAPABILITIES[rc])}

    def complete_recovery(
        self,
        work_item_id: str,
        owner: str,
        *,
        outcome: str = "resume",
        reason: str = "",
    ) -> dict[str, Any]:
        normalized = str(outcome or "").lower()
        targets = {"resume": "QUEUED", "blocked": "BLOCKED", "failed": "FAILED"}
        if normalized not in targets:
            raise ValueError("recovery outcome must be resume, blocked or failed")
        target = targets[normalized]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            if str(row["state"]) != "RECOVERING":
                raise GovernanceConflict("work item is not in recovery")
            rc = row["recovery_class"]
            now = self.clock()
            db.execute(
                "UPDATE work_items SET state=?,recovery_class=NULL,updated_at=? "
                "WHERE work_item_id=?",
                (target, now, work_item_id),
            )
            self._append_work_event(
                db,
                owner,
                work_item_id,
                "WORK_ITEM_RECOVERY_COMPLETED",
                {
                    "recovery_class": rc,
                    "outcome": normalized,
                    "target": target,
                    "reason": _text("reason", reason, 4000),
                },
            )
            db.commit()
        self.activity(
            owner,
            "work_item.recovery.complete",
            normalized,
            work_item_id=work_item_id,
            run_id=str(row["run_id"]),
            payload={
                "recovery_class": rc,
                "target": target,
                "reason": reason,
            },
        )
        return self.work_item_info(work_item_id, owner)

    def assert_recovery_capability(self, work_item_id: str, owner: str, capability: str) -> None:
        item = self.work_item_info(work_item_id, owner)
        rc = item.get("recovery_class")
        if rc and capability not in RECOVERY_CAPABILITIES.get(str(rc), frozenset()):
            raise PermissionError(
                f"recovery class {rc} does not grant capability {capability}"
            )

    def record_quality_gate(
        self,
        work_item_id: str,
        owner: str,
        *,
        passed: bool,
        reason: str = "",
        evidence: list[str] | None = None,
        candidate_revision: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if type(passed) is not bool:
            raise TypeError("passed must be boolean")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            current = str(row["state"])
            if current not in {"RUNNING", "VALIDATING", "REPAIRING"}:
                raise GovernanceConflict(
                    "Quality Gate can only be recorded while work is running, validating or repairing"
                )
            target = "VALIDATING" if passed else "REPAIRING"
            now = self.clock()
            execution_state = _load(row["execution_state_json"], {})
            gate = {
                "authority": "quality_gate",
                "deterministic": True,
                "passed": passed,
                "status": "passed" if passed else "failed",
                "reason": _text("reason", reason, 10000),
                "evidence": _strings("evidence", evidence),
                "candidate_revision": _text("candidate_revision", candidate_revision, 512) or None,
                "metadata": _dict("metadata", metadata),
                "recorded_at": now,
            }
            execution_state["quality_gate"] = gate
            db.execute(
                "UPDATE work_items SET state=?,execution_state_json=?,updated_at=? WHERE work_item_id=?",
                (target, _json(execution_state), now, work_item_id),
            )
            self._append_work_event(
                db, owner, work_item_id, "WORK_ITEM_QUALITY_GATE_RECORDED",
                {"from": current, "to": target, "passed": passed, "reason": gate["reason"]},
            )
            db.commit()
        self.activity(
            owner,
            "work_item.quality_gate",
            "passed" if passed else "failed",
            work_item_id=work_item_id,
            run_id=str(row["run_id"]),
            payload={"reason": gate["reason"], "candidate_revision": gate["candidate_revision"]},
        )
        return self.work_item_info(work_item_id, owner)

    @staticmethod
    def _stage_target(stage: dict[str, Any] | None) -> str:
        if stage is None:
            return "READY_FOR_PROMOTION"
        return "IN_REVIEW" if stage["type"] == "review" else "APPROVAL_REQUIRED"

    def submit_for_policy(self, work_item_id: str, owner: str, *, evidence: list[str] | None = None) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            policy = self._validate_execution_policy(_load(row["execution_policy_json"], {}))
            stages = policy["stages"]
            state = _load(row["execution_state_json"], {})
            self._require_quality_validation(policy, state)
            index = int(state.get("current_stage_index", 0)) if state.get("status") == "changes_requested" else 0
            stage = stages[index] if index < len(stages) else None
            new_state = {
                "current_stage_index": index,
                "current_stage_id": stage["id"] if stage else None,
                "current_stage_type": stage["type"] if stage else None,
                "status": "pending" if stage else "passed",
                "completed_stage_ids": state.get("completed_stage_ids", []),
                "return_assignee": row["assignee_agent_id"],
                "evidence": _strings("evidence", evidence),
                "quality_gate": state.get("quality_gate"),
            }
            target = self._stage_target(stage)
            db.execute(
                "UPDATE work_items SET state=?,execution_state_json=?,updated_at=? WHERE work_item_id=?",
                (target, _json(new_state), self.clock(), work_item_id),
            )
            self._append_work_event(db, owner, work_item_id, "WORK_ITEM_POLICY_SUBMITTED",
                                    {"target": target, "stage": stage, "evidence": new_state["evidence"]})
        return self.work_item_info(work_item_id, owner)

    def decide_policy_stage(
        self, work_item_id: str, owner: str, *, actor_type: str, actor_id: str,
        decision: str, comment: str = "", evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        decision = str(decision or "").lower()
        if decision not in DECISIONS:
            raise ValueError("decision must be approved, changes_requested or rejected")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM work_items WHERE work_item_id=? AND owner=?",
                (work_item_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("work item not found")
            policy = self._validate_execution_policy(_load(row["execution_policy_json"], {}))
            state = _load(row["execution_state_json"], {})
            self._require_quality_validation(policy, state)
            index = int(state.get("current_stage_index", 0))
            if index >= len(policy["stages"]):
                raise GovernanceConflict("work item has no pending execution-policy stage")
            stage = policy["stages"][index]
            expected_agent = stage.get("actor_agent_id")
            expected_user = stage.get("actor_user_id")
            allowed = bool(stage.get("allow_any_authorized"))
            if expected_agent and actor_type == "agent" and actor_id == expected_agent:
                allowed = True
            if expected_user and actor_type == "user" and actor_id == expected_user:
                allowed = True
            if not expected_agent and not expected_user:
                allowed = True
            if not allowed:
                raise PermissionError("actor is not authorized for the active execution-policy stage")
            now = self.clock()
            decision_id = _id("decision")
            db.execute(
                "INSERT INTO review_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    decision_id, owner, work_item_id, stage["id"], stage["type"],
                    actor_type, actor_id, decision, _text("comment", comment, 10000),
                    _json(_strings("evidence", evidence)), now,
                ),
            )
            completed = list(state.get("completed_stage_ids") or [])
            if decision == "changes_requested":
                target = "CHANGES_REQUESTED"
                state["status"] = "changes_requested"
            elif decision == "rejected":
                target = "FAILED"
                state["status"] = "rejected"
            else:
                if stage["id"] not in completed:
                    completed.append(stage["id"])
                next_index = index + 1
                next_stage = policy["stages"][next_index] if next_index < len(policy["stages"]) else None
                target = self._stage_target(next_stage)
                state.update({
                    "current_stage_index": next_index,
                    "current_stage_id": next_stage["id"] if next_stage else None,
                    "current_stage_type": next_stage["type"] if next_stage else None,
                    "status": "pending" if next_stage else "passed",
                    "completed_stage_ids": completed,
                })
            db.execute(
                "UPDATE work_items SET state=?,execution_state_json=?,updated_at=? WHERE work_item_id=?",
                (target, _json(state), now, work_item_id),
            )
            self._append_work_event(
                db, owner, work_item_id, "WORK_ITEM_POLICY_DECISION",
                {"decision_id": decision_id, "stage_id": stage["id"], "decision": decision,
                 "actor_type": actor_type, "actor_id": actor_id, "target": target},
            )
            db.commit()
        self.activity(owner, "work_item.policy.decision", decision, actor_type=actor_type,
                      actor_id=actor_id, work_item_id=work_item_id,
                      payload={"stage_id": stage["id"], "decision_id": decision_id})
        return {"decision_id": decision_id, "work_item": self.work_item_info(work_item_id, owner)}

    def record_cost(
        self, owner: str, *, actual_cost: float = 0.0, market_cost: float = 0.0,
        quota_usage: float = 0.0, currency: str = "USD", input_tokens: int = 0,
        output_tokens: int = 0, reasoning_tokens: int = 0, workspace: str | None = None,
        goal_id: str | None = None, work_item_id: str | None = None, run_id: str | None = None,
        operation_id: str | None = None, agent_id: str | None = None,
        provider: str | None = None, model: str | None = None,
        metadata: dict[str, Any] | None = None,
        cost_event_id: str | None = None,
    ) -> dict[str, Any]:
        values = [actual_cost, market_cost, quota_usage]
        if any(not isinstance(x, (int, float)) or not math.isfinite(float(x)) or float(x) < 0 for x in values):
            raise ValueError("cost/quota values must be finite and non-negative")
        tokens = [input_tokens, output_tokens, reasoning_tokens]
        if any(type(x) is not int or x < 0 for x in tokens):
            raise ValueError("token counts must be non-negative integers")
        event_id = _text("cost_event_id", cost_event_id, 128, required=True) if cost_event_id else _id("cost")
        now = self.clock()
        record=(event_id, owner, now, workspace, goal_id, work_item_id, run_id,
                operation_id, agent_id, provider, model, _text("currency", currency, 16, required=True),
                float(actual_cost), float(market_cost), float(quota_usage),
                input_tokens, output_tokens, reasoning_tokens, _json(_dict("metadata", metadata)))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous=db.execute("SELECT * FROM cost_events WHERE cost_event_id=?",(event_id,)).fetchone()
            if previous is not None:
                stored=tuple(previous)
                if stored[:2]!=record[:2] or stored[3:]!=record[3:]:
                    raise GovernanceConflict("cost event identity collision")
                return {"cost_event_id":event_id,"created_at":previous["created_at"],"idempotent_replay":True}
            db.execute(
                "INSERT INTO cost_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                record,
            )
        self.activity(owner, "cost.record", "ok", workspace=workspace, goal_id=goal_id,
                      work_item_id=work_item_id, run_id=run_id, operation_id=operation_id,
                      agent_id=agent_id, payload={"cost_event_id": event_id, "actual_cost": actual_cost,
                      "market_cost": market_cost, "quota_usage": quota_usage})
        return {"cost_event_id": event_id, "created_at": now}

    def cost_summary(
        self, owner: str, *, work_item_id: str | None = None, run_id: str | None = None,
        goal_id: str | None = None, agent_id: str | None = None,
    ) -> dict[str, Any]:
        where = ["owner=?"]
        params: list[Any] = [owner]
        for column, value in (
            ("work_item_id", work_item_id), ("run_id", run_id),
            ("goal_id", goal_id), ("agent_id", agent_id),
        ):
            if value:
                where.append(f"{column}=?")
                params.append(value)
        clause = " AND ".join(where)
        with self._connect() as db:
            row = db.execute(
                f"SELECT COUNT(*) count,COALESCE(SUM(actual_cost),0) actual,"
                f"COALESCE(SUM(market_cost),0) market,COALESCE(SUM(quota_usage),0) quota,"
                f"COALESCE(SUM(input_tokens),0) input_tokens,"
                f"COALESCE(SUM(output_tokens),0) output_tokens,"
                f"COALESCE(SUM(reasoning_tokens),0) reasoning_tokens "
                f",COALESCE(SUM(input_tokens+output_tokens+CASE WHEN "
                f"json_extract(metadata_json,'$.reasoning_in_output')=1 THEN 0 ELSE reasoning_tokens END),0) total_tokens "
                f"FROM cost_events WHERE {clause}", tuple(params),
            ).fetchone()
        return {key: row[key] for key in row.keys()}

    def create_routine(
        self, owner: str, *, name: str, trigger_kind: str,
        trigger_spec: dict[str, Any], work_template: dict[str, Any],
        active_policy: str = "coalesce_if_active", missed_policy: str = "skip_missed",
        missed_cap: int = 1, enabled: bool = True, next_due_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        active_policy = str(active_policy)
        missed_policy = str(missed_policy)
        if active_policy not in ROUTINE_ACTIVE_POLICIES:
            raise ValueError("invalid routine active_policy")
        if missed_policy not in ROUTINE_MISSED_POLICIES:
            raise ValueError("invalid routine missed_policy")
        if type(missed_cap) is not int or not 1 <= missed_cap <= 100:
            raise ValueError("missed_cap must be 1..100")
        kind = str(trigger_kind or "").lower()
        if kind not in {"schedule", "webhook", "api"}:
            raise ValueError("routine trigger_kind must be schedule, webhook or api")
        rid = _id("routine")
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO routines VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid, owner, _text("name", name, 200, required=True), kind,
                    _json(_dict("trigger_spec", trigger_spec)), active_policy, missed_policy,
                    missed_cap, _json(_dict("work_template", work_template)),
                    1 if enabled else 0, next_due_at, None, None,
                    _json(_dict("metadata", metadata)), now, now,
                ),
            )
        self.activity(owner, "routine.create", "ok", payload={"routine_id": rid, "name": name})
        return self.routine_info(rid, owner)

    def routine_info(self, routine_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM routines WHERE routine_id=? AND owner=?", (routine_id, owner)
            ).fetchone()
        if row is None:
            raise FileNotFoundError("routine not found")
        item = dict(row)
        item["trigger_spec"] = _load(item.pop("trigger_spec_json"), {})
        item["work_template"] = _load(item.pop("work_template_json"), {})
        item["metadata"] = _load(item.pop("metadata_json"), {})
        item["enabled"] = bool(item["enabled"])
        return item

    def fire_routine(
        self, routine_id: str, owner: str, *, run_id: str, goal_id: str | None = None,
        source: str = "manual", occurrence_key: str | None = None,
    ) -> dict[str, Any]:
        routine = self.routine_info(routine_id, owner)
        if not routine["enabled"]:
            return {"status": "SKIPPED_DISABLED", "routine": routine}
        active_id = routine.get("active_work_item_id")
        active = None
        if active_id:
            try:
                active = self.work_item_info(str(active_id), owner)
            except FileNotFoundError:
                active = None
        if active and not active["terminal"]:
            if routine["active_policy"] == "skip_if_active":
                return {"status": "SKIPPED_ACTIVE", "work_item": active}
            if routine["active_policy"] == "coalesce_if_active":
                return {"status": "COALESCED", "work_item": active}
        template = dict(routine["work_template"])
        objective = _text("routine work_template.objective", template.pop("objective", ""), 100000, required=True)
        item = self.create_work_item(
            run_id, owner, objective=objective, goal_id=goal_id or template.pop("goal_id", None),
            external_key=(
                f"routine:{routine_id}:{occurrence_key}" if occurrence_key else None
            ), metadata={**_dict("metadata", template.pop("metadata", {})),
            "routine_id": routine_id, "routine_source": source,
            "routine_occurrence_key": occurrence_key}, **template,
        )
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "UPDATE routines SET last_fired_at=?,active_work_item_id=?,updated_at=? WHERE routine_id=?",
                (now, item["work_item_id"], now, routine_id),
            )
        self.activity(owner, "routine.fire", "ok", work_item_id=item["work_item_id"],
                      run_id=run_id, payload={"routine_id": routine_id, "source": source})
        return {"status": "ENQUEUED", "work_item": item}

    def create_secret(
        self, owner: str, *, name: str, value: str, scope_type: str = "instance",
        scope_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope_type = str(scope_type or "").lower()
        if scope_type not in SCOPE_TYPES:
            raise ValueError("invalid secret scope_type")
        secret_id = _id("secret")
        now = self.clock()
        protected = protect_secret(_text("secret value", value, 1_000_000, required=True))
        with self._connect() as db:
            db.execute(
                "INSERT INTO secret_entries VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    secret_id, owner, _text("secret name", name, 200, required=True),
                    scope_type, scope_id, 1, _json(_dict("metadata", metadata)), now, now,
                ),
            )
            db.execute(
                "INSERT INTO secret_versions VALUES(?,?,?,?)", (secret_id, 1, protected, now)
            )
        self.activity(owner, "secret.create", "ok", payload={"secret_id": secret_id,
                      "name": name, "scope_type": scope_type, "scope_id": scope_id})
        return self.secret_info(secret_id, owner)

    def secret_info(self, secret_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM secret_entries WHERE secret_id=? AND owner=?", (secret_id, owner)
            ).fetchone()
        if row is None:
            raise FileNotFoundError("secret not found")
        item = dict(row)
        item["metadata"] = _load(item.pop("metadata_json"), {})
        return item

    def rotate_secret(self, secret_id: str, owner: str, *, value: str) -> dict[str, Any]:
        protected = protect_secret(_text("secret value", value, 1_000_000, required=True))
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT current_version FROM secret_entries WHERE secret_id=? AND owner=?",
                (secret_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("secret not found")
            version = int(row["current_version"]) + 1
            db.execute(
                "INSERT INTO secret_versions VALUES(?,?,?,?)", (secret_id, version, protected, now)
            )
            db.execute(
                "UPDATE secret_entries SET current_version=?,updated_at=? WHERE secret_id=?",
                (version, now, secret_id),
            )
            db.commit()
        self.activity(owner, "secret.rotate", "ok", payload={"secret_id": secret_id, "version": version})
        return self.secret_info(secret_id, owner)

    def bind_secret(
        self, secret_id: str, owner: str, *, target_type: str, target_id: str,
        env_name: str | None = None, purpose: str = "runtime",
    ) -> dict[str, Any]:
        self.secret_info(secret_id, owner)
        binding_id = _id("binding")
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO secret_bindings VALUES(?,?,?,?,?,?,?,?)",
                (
                    binding_id, owner, secret_id,
                    _text("target_type", target_type, 80, required=True),
                    _text("target_id", target_id, 256, required=True),
                    _text("env_name", env_name, 256) or None,
                    _text("purpose", purpose, 512, required=True), now,
                ),
            )
        return {"binding_id": binding_id, "secret_id": secret_id, "target_type": target_type,
                "target_id": target_id, "env_name": env_name, "purpose": purpose}

    def resolve_secret_for_runtime(
        self, secret_id: str, owner: str, *, actor_type: str, actor_id: str | None,
        purpose: str,
    ) -> str:
        info = self.secret_info(secret_id, owner)
        version = int(info["current_version"])
        normalized_actor_type = _text(
            "actor_type", actor_type, 80, required=True
        )
        normalized_actor_id = _text(
            "actor_id", actor_id, 256, required=True
        )
        normalized_purpose = _text(
            "purpose", purpose, 512, required=True
        )
        with self._connect() as db:
            binding = db.execute(
                "SELECT binding_id FROM secret_bindings "
                "WHERE owner=? AND secret_id=? AND target_type=? AND target_id=? "
                "AND purpose=? ORDER BY created_at DESC LIMIT 1",
                (
                    owner,
                    secret_id,
                    normalized_actor_type,
                    normalized_actor_id,
                    normalized_purpose,
                ),
            ).fetchone()
            if binding is None:
                self.activity(
                    owner,
                    "secret.access",
                    "denied",
                    actor_type=normalized_actor_type,
                    actor_id=normalized_actor_id,
                    payload={
                        "secret_id": secret_id,
                        "version": version,
                        "purpose": normalized_purpose,
                        "reason": "no matching secret binding",
                    },
                )
                raise PermissionError(
                    "secret is not bound to the requesting runtime actor"
                )

            row = db.execute(
                "SELECT protected_value FROM secret_versions WHERE secret_id=? AND version=?",
                (secret_id, version),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("secret version not found")
            access_id = _id("secret-access")
            db.execute(
                "INSERT INTO secret_access_events VALUES(?,?,?,?,?,?,?,?)",
                (
                    access_id, owner, secret_id, version,
                    normalized_actor_type,
                    normalized_actor_id,
                    normalized_purpose,
                    self.clock(),
                ),
            )
        self.activity(
            owner,
            "secret.access",
            "ok",
            actor_type=normalized_actor_type,
            actor_id=normalized_actor_id,
            payload={
                "secret_id": secret_id,
                "version": version,
                "purpose": normalized_purpose,
                "binding_id": binding["binding_id"],
            },
        )
        return unprotect_secret(str(row["protected_value"]))

    def register_work_product(
        self, work_item_id: str, owner: str, *, artifact_id: str,
        kind: str = "artifact", title: str = "", metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.work_item_info(work_item_id, owner)
        product_id = _id("product")
        now = self.clock()
        with self._connect() as db:
            try:
                db.execute(
                    "INSERT INTO work_products VALUES(?,?,?,?,?,?,?,?)",
                    (
                        product_id, owner, work_item_id,
                        _text("artifact_id", artifact_id, 256, required=True),
                        _text("kind", kind, 80, required=True),
                        _text("title", title, 500), _json(_dict("metadata", metadata)), now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = db.execute(
                    "SELECT * FROM work_products WHERE work_item_id=? AND artifact_id=? AND kind=?",
                    (work_item_id, artifact_id, kind),
                ).fetchone()
                return {**dict(row), "metadata": _load(row["metadata_json"], {})}
        self.activity(owner, "work_product.register", "ok", work_item_id=work_item_id,
                      evidence=[artifact_id], payload={"work_product_id": product_id, "kind": kind})
        return {"work_product_id": product_id, "work_item_id": work_item_id,
                "artifact_id": artifact_id, "kind": kind, "title": title,
                "metadata": _dict("metadata", metadata), "created_at": now}

    def install_skill(
        self, owner: str, *, name: str, version: str, content: str,
        source: str = "local", metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = str(content)
        if not body or len(body) > 1_000_000:
            raise ValueError("skill content must be 1..1000000 characters")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        skill_id = _id("skill")
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO skills VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    skill_id, owner, _text("skill name", name, 200, required=True),
                    _text("skill version", version, 80, required=True), body, digest,
                    _text("skill source", source, 512, required=True),
                    _json(_dict("metadata", metadata)), now,
                ),
            )
        return {"skill_id": skill_id, "name": name, "version": version,
                "content_sha256": digest, "source": source, "created_at": now}

    def register_plugin(
        self, owner: str, *, manifest: dict[str, Any], verified_methods: list[str] | None = None,
        narrowed_capabilities: list[str] | None = None, trusted_ui: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = _dict("manifest", manifest)
        name = _text("plugin name", manifest.get("name"), 200, required=True)
        version = _text("plugin version", manifest.get("version"), 80, required=True)
        declared = _strings("plugin capabilities", manifest.get("capabilities"))
        verified = _strings("verified_methods", verified_methods)
        narrowed = _strings("narrowed_capabilities", narrowed_capabilities) or declared
        # Declaration is a request, never a grant. Effective authority is an
        # intersection of declared capability, live verified method and host narrowing.
        verified_caps = {
            item.split(":", 1)[1] if item.startswith("capability:") else item
            for item in verified
        }
        effective = sorted(set(declared) & set(narrowed) & verified_caps)
        plugin_id = _id("plugin")
        state = "VERIFIED" if verified else "REGISTERED"
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO plugins VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plugin_id, owner, name, version, state, _json(manifest),
                    _json(declared), _json(verified), _json(narrowed), _json(effective),
                    1 if trusted_ui else 0, _json(_dict("metadata", metadata)), now, now,
                ),
            )
        self.activity(owner, "plugin.register", "ok", payload={"plugin_id": plugin_id,
                      "name": name, "version": version, "effective_capabilities": effective,
                      "trusted_ui": trusted_ui})
        return {"plugin_id": plugin_id, "name": name, "version": version, "state": state,
                "declared_capabilities": declared, "verified_methods": verified,
                "narrowed_capabilities": narrowed, "effective_capabilities": effective,
                "trusted_ui": trusted_ui}

    def portable_snapshot(self, owner: str, *, run_id: str | None = None) -> dict[str, Any]:
        """Return a secret-free, machine-neutral governance blueprint."""
        work = self.list_work_items(owner, run_id=run_id, limit=1000)["items"]
        with self._connect() as db:
            routines = [dict(row) for row in db.execute(
                "SELECT * FROM routines WHERE owner=? ORDER BY name", (owner,)
            ).fetchall()]
            skills = [dict(row) for row in db.execute(
                "SELECT skill_id,name,version,content,content_sha256,source,metadata_json,created_at "
                "FROM skills WHERE owner=? ORDER BY name,version", (owner,)
            ).fetchall()]
            plugins = [dict(row) for row in db.execute(
                "SELECT plugin_id,name,version,state,manifest_json,declared_capabilities_json,"
                "narrowed_capabilities_json,trusted_ui,metadata_json FROM plugins WHERE owner=? "
                "ORDER BY name,version", (owner,)
            ).fetchall()]
            secrets_meta = [dict(row) for row in db.execute(
                "SELECT secret_id,name,scope_type,scope_id,current_version,metadata_json "
                "FROM secret_entries WHERE owner=? ORDER BY name", (owner,)
            ).fetchall()]
        for item in work:
            for key in (
                "owner", "run_id", "checkout_run_id", "execution_run_id",
                "failure_chain_id", "retry_count", "recovery_class", "state",
                "terminal", "created_at", "updated_at", "assignee_user_id",
            ):
                item.pop(key, None)
        for item in routines:
            item["trigger_spec"] = _load(item.pop("trigger_spec_json"), {})
            item["work_template"] = _load(item.pop("work_template_json"), {})
            item["metadata"] = {
                key: value
                for key, value in _load(item.pop("metadata_json"), {}).items()
                if not str(key).startswith("_runtime_")
            }
            for key in (
                "routine_id", "owner", "active_work_item_id", "last_fired_at",
                "next_due_at", "created_at", "updated_at",
            ):
                item.pop(key, None)
        for item in skills:
            item["metadata"] = _load(item.pop("metadata_json"), {})
            for key in ("skill_id", "owner", "created_at"):
                item.pop(key, None)
        for item in plugins:
            item["manifest"] = _load(item.pop("manifest_json"), {})
            item["declared_capabilities"] = _load(item.pop("declared_capabilities_json"), [])
            item["narrowed_capabilities"] = _load(item.pop("narrowed_capabilities_json"), [])
            item["metadata"] = _load(item.pop("metadata_json"), {})
            for key in ("plugin_id", "owner", "state", "trusted_ui"):
                item.pop(key, None)
        for item in secrets_meta:
            item["metadata"] = _load(item.pop("metadata_json"), {})
            item["required_value"] = True
            item.pop("secret_id", None)
            item.pop("current_version", None)
        return {
            "schema_version": 1,
            "kind": "sentra-governance-blueprint",
            "run_id": run_id,
            "work_items": work,
            "routines": routines,
            "skills": skills,
            "plugins": plugins,
            "secret_requirements": secrets_meta,
            "contains_secret_values": False,
        }


    def list_routines(
        self, owner: str, *, enabled_only: bool = False,
    ) -> dict[str, Any]:
        where = "owner=? AND enabled=1" if enabled_only else "owner=?"
        with self._connect() as db:
            rows = db.execute(
                f"SELECT routine_id FROM routines WHERE {where} ORDER BY name",
                (owner,),
            ).fetchall()
        return {"items": [self.routine_info(str(row["routine_id"]), owner) for row in rows]}

    def bind_routine_runtime(
        self,
        routine_id: str,
        owner: str,
        *,
        authority_run_id: str,
        goal_id: str | None = None,
    ) -> dict[str, Any]:
        routine = self.routine_info(routine_id, owner)
        metadata = dict(routine.get("metadata") or {})
        metadata["_runtime_authority_run_id"] = str(authority_run_id)
        if goal_id:
            metadata["_runtime_goal_id"] = str(goal_id)
        else:
            metadata.pop("_runtime_goal_id", None)
        with self._connect() as db:
            db.execute(
                "UPDATE routines SET metadata_json=?,updated_at=? "
                "WHERE routine_id=? AND owner=?",
                (_json(metadata), self.clock(), routine_id, owner),
            )
        return self.routine_info(routine_id, owner)

    def update_routine_clock(
        self,
        routine_id: str,
        owner: str,
        *,
        next_due_at: float | None,
        last_fired_at: float | None = None,
    ) -> dict[str, Any]:
        self.routine_info(routine_id, owner)
        with self._connect() as db:
            if last_fired_at is None:
                db.execute(
                    "UPDATE routines SET next_due_at=?,updated_at=? "
                    "WHERE routine_id=? AND owner=?",
                    (next_due_at, self.clock(), routine_id, owner),
                )
            else:
                db.execute(
                    "UPDATE routines SET next_due_at=?,last_fired_at=?,updated_at=? "
                    "WHERE routine_id=? AND owner=?",
                    (next_due_at, last_fired_at, self.clock(), routine_id, owner),
                )
        return self.routine_info(routine_id, owner)


    def plugin_info(self, plugin_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM plugins WHERE plugin_id=? AND owner=?",
                (plugin_id, owner),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("plugin not found")
        item = dict(row)
        for field in (
            "manifest_json", "declared_capabilities_json", "verified_methods_json",
            "narrowed_capabilities_json", "effective_capabilities_json", "metadata_json",
        ):
            key = field[:-5]
            item[key] = _load(item.pop(field), {} if field in {"manifest_json", "metadata_json"} else [])
        item["trusted_ui"] = bool(item["trusted_ui"])
        return item

    def update_plugin_verification(
        self,
        plugin_id: str,
        owner: str,
        *,
        verified_methods: list[str],
        live_capabilities: list[str],
        narrowed_capabilities: list[str] | None = None,
        state: str = "VERIFIED",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = self.plugin_info(plugin_id, owner)
        declared = set(item["declared_capabilities"])
        narrowed = set(narrowed_capabilities or item["narrowed_capabilities"] or declared)
        live = set(_strings("live_capabilities", live_capabilities))
        effective = sorted(declared & narrowed & live)
        merged = dict(item.get("metadata") or {})
        merged.update(dict(metadata or {}))
        normalized_methods = _strings("verified_methods", verified_methods)
        state = str(state or "").upper()
        if state not in PLUGIN_STATES:
            raise ValueError("invalid plugin state")
        with self._connect() as db:
            db.execute(
                "UPDATE plugins SET state=?,verified_methods_json=?,"
                "narrowed_capabilities_json=?,effective_capabilities_json=?,"
                "metadata_json=?,updated_at=? WHERE plugin_id=? AND owner=?",
                (
                    state,
                    _json(normalized_methods),
                    _json(sorted(narrowed)),
                    _json(effective),
                    _json(merged),
                    self.clock(),
                    plugin_id,
                    owner,
                ),
            )
        self.activity(
            owner,
            "plugin.verify",
            "ok" if state == "VERIFIED" else state.lower(),
            payload={
                "plugin_id": plugin_id,
                "verified_methods": normalized_methods,
                "effective_capabilities": effective,
            },
        )
        return self.plugin_info(plugin_id, owner)

    def list_plugins(self, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT plugin_id FROM plugins WHERE owner=? ORDER BY name,version",
                (owner,),
            ).fetchall()
        return {"items": [self.plugin_info(str(row["plugin_id"]), owner) for row in rows]}


    @staticmethod
    def _ensure_skill_binding_schema(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS skill_bindings(
                binding_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(owner,skill_id,run_id,agent_id)
            );
            CREATE INDEX IF NOT EXISTS idx_skill_bindings_agent
                ON skill_bindings(owner,run_id,agent_id,enabled,priority);
            """
        )

    def skill_info(self, skill_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM skills WHERE skill_id=? AND owner=?",
                (skill_id, owner),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("skill not found")
        item = dict(row)
        item["metadata"] = _load(item.pop("metadata_json"), {})
        return item

    def list_skills(self, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT skill_id FROM skills WHERE owner=? ORDER BY name,version",
                (owner,),
            ).fetchall()
        return {"items": [self.skill_info(str(row["skill_id"]), owner) for row in rows]}

    def bind_skill(
        self,
        skill_id: str,
        owner: str,
        *,
        run_id: str,
        agent_id: str,
        priority: int = 100,
        enabled: bool = True,
    ) -> dict[str, Any]:
        self.skill_info(skill_id, owner)
        if type(priority) is not int or not -10000 <= priority <= 10000:
            raise ValueError("skill binding priority must be -10000..10000")
        binding_id = _id("skill-binding")
        now = self.clock()
        with self._connect() as db:
            self._ensure_skill_binding_schema(db)
            try:
                db.execute(
                    "INSERT INTO skill_bindings VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        binding_id, owner, skill_id, str(run_id), str(agent_id),
                        priority, 1 if enabled else 0, now, now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = db.execute(
                    "SELECT binding_id FROM skill_bindings WHERE owner=? AND skill_id=? "
                    "AND run_id=? AND agent_id=?",
                    (owner, skill_id, str(run_id), str(agent_id)),
                ).fetchone()
                binding_id = str(row["binding_id"])
                db.execute(
                    "UPDATE skill_bindings SET priority=?,enabled=?,updated_at=? "
                    "WHERE binding_id=?",
                    (priority, 1 if enabled else 0, now, binding_id),
                )
        self.activity(
            owner, "skill.bind", "ok", agent_id=agent_id, run_id=run_id,
            payload={"skill_id": skill_id, "binding_id": binding_id, "priority": priority},
        )
        return {
            "binding_id": binding_id,
            "skill_id": skill_id,
            "run_id": str(run_id),
            "agent_id": str(agent_id),
            "priority": priority,
            "enabled": bool(enabled),
        }

    def agent_skills(
        self,
        owner: str,
        *,
        run_id: str,
        agent_id: str,
        max_chars: int = 6000,
    ) -> dict[str, Any]:
        max_chars = max(0, min(int(max_chars), 50000))
        with self._connect() as db:
            self._ensure_skill_binding_schema(db)
            rows = db.execute(
                "SELECT b.binding_id,b.priority,s.* FROM skill_bindings b "
                "JOIN skills s ON s.skill_id=b.skill_id AND s.owner=b.owner "
                "WHERE b.owner=? AND b.run_id=? AND b.agent_id=? AND b.enabled=1 "
                "ORDER BY b.priority ASC,s.name ASC,s.version ASC",
                (owner, str(run_id), str(agent_id)),
            ).fetchall()
        items: list[dict[str, Any]] = []
        chunks: list[str] = []
        used = 0
        truncated = False
        for row in rows:
            header = f"[SKILL {row['name']}@{row['version']} sha256={row['content_sha256']}]"
            body = str(row["content"])
            chunk = header + "\n" + body
            extra = len(chunk) + (2 if chunks else 0)
            if used + extra > max_chars:
                remaining = max_chars - used - (2 if chunks else 0)
                if remaining > len(header) + 24:
                    chunk = chunk[: max(0, remaining - 22)] + "\n[SKILL TRUNCATED]"
                    chunks.append(chunk)
                    items.append({
                        "skill_id": row["skill_id"],
                        "name": row["name"],
                        "version": row["version"],
                        "content_sha256": row["content_sha256"],
                        "priority": int(row["priority"]),
                        "truncated": True,
                    })
                truncated = True
                break
            chunks.append(chunk)
            used += extra
            items.append({
                "skill_id": row["skill_id"],
                "name": row["name"],
                "version": row["version"],
                "content_sha256": row["content_sha256"],
                "priority": int(row["priority"]),
                "truncated": False,
            })
        return {
            "items": items,
            "text": "\n\n".join(chunks),
            "truncated": truncated,
            "chars": len("\n\n".join(chunks)),
        }


    def set_routine_enabled(
        self, routine_id: str, owner: str, *, enabled: bool
    ) -> dict[str, Any]:
        self.routine_info(routine_id, owner)
        with self._connect() as db:
            db.execute(
                "UPDATE routines SET enabled=?,updated_at=? WHERE routine_id=? AND owner=?",
                (1 if enabled else 0, self.clock(), routine_id, owner),
            )
        self.activity(
            owner, "routine.enable" if enabled else "routine.disable", "ok",
            payload={"routine_id": routine_id},
        )
        return self.routine_info(routine_id, owner)
