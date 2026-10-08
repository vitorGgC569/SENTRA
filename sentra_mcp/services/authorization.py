"""Single-authority capability/scope authorization for hosted SENTRA.

Roles are deliberately not a second source of truth.  A role/template may be
expanded by a caller into grants, but authorization decisions are made only from
the durable grants stored here plus the explicit local-owner shortcut.
"""
from __future__ import annotations

import fnmatch
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore

SCOPE_TYPES = {
    "instance", "workspace", "project", "goal", "work_item", "agent", "device",
}
PRINCIPAL_TYPES = {"user", "agent", "plugin", "device", "service"}
GRANT_EFFECTS = {"allow"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class AuthorizationService:
    """Durable, fail-closed allow-grant evaluator with hierarchical scopes."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        store: ControlPlaneStore | None = None,
        clock=time.time,
    ) -> None:
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.path = self.store.path_for("authorization")
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS authorization_grants(
                    grant_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    principal_type TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT,
                    effect TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    expires_at REAL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_grants_principal
                    ON authorization_grants(
                        owner,principal_type,principal_id,revoked,expires_at
                    );
                CREATE TABLE IF NOT EXISTS authorization_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    owner TEXT NOT NULL,
                    action TEXT NOT NULL,
                    grant_id TEXT,
                    principal_type TEXT,
                    principal_id TEXT,
                    capability TEXT,
                    scope_type TEXT,
                    scope_id TEXT,
                    outcome TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return self.store.connect("authorization")

    @staticmethod
    def _text(name: str, value: Any, maximum: int = 256, required: bool = True) -> str:
        text = str(value or "").strip()
        if required and not text:
            raise ValueError(f"{name} is required")
        if len(text) > maximum:
            raise ValueError(f"{name} exceeds {maximum} characters")
        return text

    @staticmethod
    def _grant_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["conditions"] = _load(item.pop("conditions_json"), {})
        item["revoked"] = bool(item["revoked"])
        return item

    def _event(
        self,
        db: sqlite3.Connection,
        owner: str,
        action: str,
        *,
        outcome: str,
        reason: str,
        grant_id: str | None = None,
        principal_type: str | None = None,
        principal_id: str | None = None,
        capability: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> None:
        db.execute(
            "INSERT INTO authorization_events VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "auth-" + uuid.uuid4().hex,
                owner,
                action,
                grant_id,
                principal_type,
                principal_id,
                capability,
                scope_type,
                scope_id,
                outcome,
                reason[:2000],
                self.clock(),
            ),
        )

    def grant(
        self,
        owner: str,
        *,
        principal_type: str,
        principal_id: str,
        capability: str,
        scope_type: str = "instance",
        scope_id: str | None = None,
        conditions: dict[str, Any] | None = None,
        ttl_s: float | None = None,
    ) -> dict[str, Any]:
        principal_type = str(principal_type or "").lower()
        scope_type = str(scope_type or "").lower()
        if principal_type not in PRINCIPAL_TYPES:
            raise ValueError("invalid principal_type")
        if scope_type not in SCOPE_TYPES:
            raise ValueError("invalid scope_type")
        if scope_type != "instance" and not str(scope_id or "").strip():
            raise ValueError("scope_id is required outside instance scope")
        cap = self._text("capability", capability, 256)
        if not all(ch.isalnum() or ch in "._:-*" for ch in cap):
            raise ValueError("capability contains unsupported characters")
        cond = dict(conditions or {})
        allowed_condition_keys = {
            "requires_interactive", "max_actual_cost", "workspace_permission",
            "provider", "device_health",
        }
        unknown = set(cond) - allowed_condition_keys
        if unknown:
            raise ValueError(
                "unknown authorization conditions: " + ", ".join(sorted(unknown))
            )
        expires_at = None
        if ttl_s is not None:
            if not isinstance(ttl_s, (int, float)) or not 1 <= float(ttl_s) <= 31_536_000:
                raise ValueError("ttl_s must be 1..31536000")
            expires_at = self.clock() + float(ttl_s)
        grant_id = "grant-" + uuid.uuid4().hex
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO authorization_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    grant_id,
                    owner,
                    principal_type,
                    self._text("principal_id", principal_id, 256),
                    cap,
                    scope_type,
                    str(scope_id).strip() if scope_id is not None else None,
                    "allow",
                    _json(cond),
                    expires_at,
                    0,
                    now,
                    now,
                ),
            )
            self._event(
                db, owner, "grant", outcome="ok", reason="grant created",
                grant_id=grant_id, principal_type=principal_type,
                principal_id=principal_id, capability=cap,
                scope_type=scope_type, scope_id=scope_id,
            )
        return self.info(grant_id, owner)

    def info(self, grant_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM authorization_grants WHERE grant_id=? AND owner=?",
                (grant_id, owner),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("authorization grant not found")
        return self._grant_row(row)

    def revoke(self, grant_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM authorization_grants WHERE grant_id=? AND owner=?",
                (grant_id, owner),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("authorization grant not found")
            db.execute(
                "UPDATE authorization_grants SET revoked=1,updated_at=? WHERE grant_id=?",
                (self.clock(), grant_id),
            )
            self._event(
                db, owner, "revoke", outcome="ok", reason="grant revoked",
                grant_id=grant_id, principal_type=row["principal_type"],
                principal_id=row["principal_id"], capability=row["capability"],
                scope_type=row["scope_type"], scope_id=row["scope_id"],
            )
        return self.info(grant_id, owner)

    def list_grants(
        self,
        owner: str,
        *,
        principal_type: str | None = None,
        principal_id: str | None = None,
        include_revoked: bool = False,
    ) -> dict[str, Any]:
        where = ["owner=?"]
        params: list[Any] = [owner]
        if principal_type:
            where.append("principal_type=?")
            params.append(str(principal_type).lower())
        if principal_id:
            where.append("principal_id=?")
            params.append(principal_id)
        if not include_revoked:
            where.append("revoked=0")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM authorization_grants WHERE " + " AND ".join(where)
                + " ORDER BY created_at",
                tuple(params),
            ).fetchall()
        return {"items": [self._grant_row(row) for row in rows]}

    @staticmethod
    def _capability_matches(rule: str, requested: str) -> bool:
        if rule == "*":
            return True
        if rule.endswith("*"):
            return requested.startswith(rule[:-1])
        return fnmatch.fnmatchcase(requested, rule)

    @staticmethod
    def _scope_matches(
        grant_scope_type: str,
        grant_scope_id: str | None,
        requested_scope_type: str,
        requested_scope_id: str | None,
        ancestors: dict[str, list[str]] | None,
    ) -> bool:
        if grant_scope_type == "instance":
            return True
        if grant_scope_type == requested_scope_type and grant_scope_id == requested_scope_id:
            return True
        if not ancestors:
            return False
        return str(grant_scope_id) in set(ancestors.get(grant_scope_type, []))

    def _trusted_ancestors(
        self,
        owner: str,
        scope_type: str,
        scope_id: str | None,
    ) -> dict[str, list[str]]:
        """Resolve scope inheritance from persisted SENTRA resources.

        ``ancestors`` on public tool inputs is untrusted metadata. Only relations
        read from the owner-scoped governance and durable databases may broaden a
        grant beyond an exact scope match. Missing or inconsistent records fail
        closed by returning no ancestors.
        """
        if not scope_id:
            return {}

        result: dict[str, list[str]] = {}
        run_id: str | None = None
        goal_id: str | None = None

        try:
            if scope_type == "work_item":
                with self.store.connect("governance") as db:
                    row = db.execute(
                        "SELECT run_id,goal_id,parent_work_item_id FROM work_items "
                        "WHERE work_item_id=? AND owner=?",
                        (scope_id, owner),
                    ).fetchone()
                    if row is None:
                        return {}
                    run_id = str(row["run_id"])
                    goal_id = str(row["goal_id"] or "") or None
                    parent_id = str(row["parent_work_item_id"] or "") or None
                    parents: list[str] = []
                    seen = {str(scope_id)}
                    while parent_id and parent_id not in seen and len(parents) < 128:
                        parent = db.execute(
                            "SELECT run_id,parent_work_item_id FROM work_items "
                            "WHERE work_item_id=? AND owner=?",
                            (parent_id, owner),
                        ).fetchone()
                        if parent is None or str(parent["run_id"]) != run_id:
                            return {}
                        parents.append(parent_id)
                        seen.add(parent_id)
                        parent_id = str(parent["parent_work_item_id"] or "") or None
                    if parent_id:
                        return {}
                    if parents:
                        result["work_item"] = parents
            elif scope_type == "goal":
                goal_id = str(scope_id)
            elif scope_type == "agent":
                durable_path = self.path.parent / "durable.sqlite3"
                with sqlite3.connect(str(durable_path)) as db:
                    db.row_factory = sqlite3.Row
                    row = db.execute(
                        "SELECT run_id,goal_id FROM agents WHERE agent_id=? AND owner=?",
                        (scope_id, owner),
                    ).fetchone()
                    if row is None:
                        return {}
                    run_id = str(row["run_id"])
                    goal_id = str(row["goal_id"] or "") or None
            else:
                return {}

            durable_path = self.path.parent / "durable.sqlite3"
            with sqlite3.connect(str(durable_path)) as db:
                db.row_factory = sqlite3.Row
                if goal_id:
                    goals: list[str] = []
                    seen_goals = {goal_id}
                    current = db.execute(
                        "SELECT run_id,parent_goal_id FROM goals WHERE goal_id=? AND owner=?",
                        (goal_id, owner),
                    ).fetchone()
                    if current is None:
                        return {}
                    run_id = run_id or str(current["run_id"])
                    if str(current["run_id"]) != run_id:
                        return {}
                    parent_goal_id = str(current["parent_goal_id"] or "") or None
                    while parent_goal_id and parent_goal_id not in seen_goals and len(goals) < 128:
                        parent = db.execute(
                            "SELECT run_id,parent_goal_id FROM goals "
                            "WHERE goal_id=? AND owner=?",
                            (parent_goal_id, owner),
                        ).fetchone()
                        if parent is None or str(parent["run_id"]) != run_id:
                            return {}
                        goals.append(parent_goal_id)
                        seen_goals.add(parent_goal_id)
                        parent_goal_id = str(parent["parent_goal_id"] or "") or None
                    if parent_goal_id:
                        return {}
                    result["goal"] = goals

                if run_id:
                    run = db.execute(
                        "SELECT workspace FROM runs WHERE run_id=? AND owner=?",
                        (run_id, owner),
                    ).fetchone()
                    if run is None:
                        return {}
                    workspace = str(run["workspace"] or "")
                    if workspace:
                        result["workspace"] = [workspace]
                    projects = {
                        str(row[0])
                        for row in db.execute(
                            "SELECT DISTINCT project_id FROM chats "
                            "WHERE run_id=? AND owner=? AND project_id IS NOT NULL "
                            "AND project_id!=''",
                            (run_id, owner),
                        ).fetchall()
                    }
                    # A run may contain chats from several projects. In that
                    # case there is no unambiguous project ancestor to grant.
                    if len(projects) == 1:
                        result["project"] = list(projects)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return {}
        return result

    @staticmethod
    def _conditions_match(
        conditions: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[bool, str]:
        if conditions.get("requires_interactive") is True and not context.get("interactive"):
            return False, "interactive approval required"
        max_cost = conditions.get("max_actual_cost")
        if max_cost is not None:
            try:
                proposed = float(context.get("actual_cost", 0.0))
                limit = float(max_cost)
            except (TypeError, ValueError):
                return False, "invalid actual_cost condition context"
            if proposed > limit:
                return False, "actual cost exceeds grant condition"
        workspace_permission = conditions.get("workspace_permission")
        if workspace_permission and workspace_permission not in set(
            context.get("workspace_permissions") or []
        ):
            return False, "workspace permission condition not satisfied"
        provider = conditions.get("provider")
        if provider and str(context.get("provider") or "") != str(provider):
            return False, "provider condition not satisfied"
        device_health = conditions.get("device_health")
        if device_health and str(context.get("device_health") or "").upper() != str(device_health).upper():
            return False, "device health condition not satisfied"
        return True, "conditions satisfied"

    def authorize(
        self,
        owner: str,
        *,
        principal_type: str,
        principal_id: str,
        capability: str,
        scope_type: str = "instance",
        scope_id: str | None = None,
        ancestors: dict[str, list[str]] | None = None,
        context: dict[str, Any] | None = None,
        local_owner: bool = False,
    ) -> dict[str, Any]:
        principal_type = str(principal_type or "").lower()
        scope_type = str(scope_type or "").lower()
        capability = self._text("capability", capability, 256)
        if principal_type not in PRINCIPAL_TYPES:
            raise ValueError("invalid principal_type")
        if scope_type not in SCOPE_TYPES:
            raise ValueError("invalid scope_type")
        if local_owner and principal_type == "user" and principal_id == owner:
            return {
                "allowed": True,
                "source": "local_owner",
                "grant_id": None,
                "reason": "local owner authority",
            }

        now = self.clock()
        trusted_ancestors = self._trusted_ancestors(owner, scope_type, scope_id)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM authorization_grants WHERE owner=? AND principal_type=? "
                "AND principal_id=? AND revoked=0 AND (expires_at IS NULL OR expires_at>?) "
                "ORDER BY created_at",
                (owner, principal_type, principal_id, now),
            ).fetchall()
            rejected_reasons: list[str] = []
            for row in rows:
                if not self._capability_matches(str(row["capability"]), capability):
                    continue
                if not self._scope_matches(
                    str(row["scope_type"]), row["scope_id"],
                    scope_type, scope_id, trusted_ancestors,
                ):
                    continue
                ok, reason = self._conditions_match(
                    _load(row["conditions_json"], {}), dict(context or {})
                )
                if ok:
                    self._event(
                        db, owner, "authorize", outcome="allowed", reason=reason,
                        grant_id=row["grant_id"], principal_type=principal_type,
                        principal_id=principal_id, capability=capability,
                        scope_type=scope_type, scope_id=scope_id,
                    )
                    return {
                        "allowed": True,
                        "source": "grant",
                        "grant_id": row["grant_id"],
                        "reason": reason,
                    }
                rejected_reasons.append(reason)
            reason = (
                "; ".join(sorted(set(rejected_reasons)))
                if rejected_reasons else "no matching active grant"
            )
            self._event(
                db, owner, "authorize", outcome="denied", reason=reason,
                principal_type=principal_type, principal_id=principal_id,
                capability=capability, scope_type=scope_type, scope_id=scope_id,
            )
        return {
            "allowed": False,
            "source": "policy",
            "grant_id": None,
            "reason": reason,
        }

    def require(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        decision = self.authorize(owner, **kwargs)
        if not decision["allowed"]:
            raise PermissionError("authorization denied: " + decision["reason"])
        return decision
