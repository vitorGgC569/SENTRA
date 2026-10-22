"""Shell-bridge dispatch facade for the Pulso domain (scheduling, goals,
workflows, runtimes, terminals, receipts, channels).

Composition contract for the Codex principal (owner of
``POST /api/shell/bridge``):

- The route handler authenticates the bearer, strips renderer authority
  keys (``owner``, ``principal*``, ``grant*``, ``run_id``,
  ``operation_id``, paths), normalizes ``ws`` to ``project_id``, and calls
  :meth:`PulsoShellDispatch.dispatch` with the server-derived envelope.
  Identity inside this facade is therefore **canonical CP owner**
  (``canvas._runtime().owner``, e.g. ``canvas:vitor``) for Control Plane
  services plus a separately derived **principal** (``store.principal``,
  e.g. ``vitor``) for Canvas store checks. Browser input never selects
  either: params carrying identity/authority selectors (``owner``,
  ``principal*``, ``grant*``, ``run_id``, roots) are denied on arrival.
- Reads return ``{"ok": True, "value": {...}, "request_key": ...}``.
  Mutations reserve ``(request_key, intent)`` **before** any effect with
  the intent SHA-256 (action + scope + params) and scope persisted:
  repeating the key replays the recorded response only when the stored
  intent matches; a mismatched intent is denied; a ``PENDING`` key (live
  or crashed before completion) and a recorded ``UNCERTAIN`` failure both
  return ``status: uncertain`` — queryable under the same key, never
  re-executed, never duplicated.
- Runs, agents and workspace bindings are always derived server-side:
  schedule fire uses the routine's bound authority Run; terminal
  run/work-item/principal come from the persistent session ledger; goal
  Runs come from the Canvas runtime (or ``control.shell.resolve_run``);
  goal agents are verified members of the Run. Renderers select only
  domain selectors (routine/terminal/workflow/channel/event IDs).
- Workflow and runtime mutations are exact intent builders admitted by
  the host as distinct central operations. Channel triggers bind Lume
  inbox claims to workflow signals via ``dispatch_idempotency_key``.

Allowlisted actions (exact map, no prefix dispatch)
----------------------------------------------------
``schedule_list/get/create/enable/disable/pause/resume/fire`` (8),
``goal_status/set/open/advance/stop`` (5),
``workflow_intent/observe/output`` (3),
``runtime_intent/observe`` (2),
``terminal_list/read/write/intent`` (4), ``receipt_get`` (1),
``channel_list/enable/renew/disable/revoke/send_intent/inbox/claim/ack``
(9). Total: 32.
"""
from __future__ import annotations

import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

REQUEST_KEY = re.compile(r"^[A-Za-z0-9_:.=-]{8,128}$")

# Identity/authority selectors that must be server-derived. Renderers send
# domain selectors only (routine/terminal/workflow/channel/event IDs).
FORBIDDEN_PARAMS = frozenset({
    "owner", "principal", "principal_id", "principal_type",
    "grant", "grant_id", "grant_type", "permissions", "permission",
    "workspace_root", "root", "run_id", "operation_id",
})

READ_ACTIONS = frozenset({
    "schedule_list", "schedule_get", "goal_status",
    "workflow_observe", "workflow_output", "runtime_observe",
    "terminal_list", "terminal_read", "receipt_get",
    "channel_list", "channel_inbox",
})

MUTATING_ACTIONS = frozenset({
    "schedule_create", "schedule_enable", "schedule_disable",
    "schedule_pause", "schedule_resume", "schedule_fire",
    "goal_set", "goal_open", "goal_advance", "goal_stop",
    "workflow_intent", "runtime_intent", "terminal_write", "terminal_intent",
    "channel_enable", "channel_renew", "channel_disable",
    "channel_revoke", "channel_send_intent", "channel_claim",
    "channel_ack",
})

SHELL_ACTIONS = READ_ACTIONS | MUTATING_ACTIONS

RUNTIME_PROVIDERS = frozenset({"temporal", "langgraph"})
RUNTIME_OPERATIONS = frozenset({
    "start", "advance", "signal", "interrupt", "resume",
    "cancel", "observe", "reconcile", "fork",
})


class PulsoShellDenied(ValueError):
    pass


class PulsoShellDispatch:
    """Host-composable dispatch for Pulso shell-bridge actions."""

    def __init__(self, control: Any, governance: Any, *,
                 canvas: Any = None, conversations: Any = None,
                 workflow_resolver: Callable | None = None,
                 runtime_resolver: Callable | None = None,
                 terminal_resolver: Callable | None = None,
                 channel_resolver: Callable | None = None,
                 channel_bridge: Any = None,
                 channel_service: Any = None,
                 trigger_bridge: Any = None,
                 idempotency_database: str | None = None,
                 workspace_root: str | None = None,
                 clock=time.time, price_quote=None) -> None:
        self.control, self.governance = control, governance
        self.canvas, self.conversations = canvas, conversations
        self.workflow_resolver = workflow_resolver
        self.runtime_resolver = runtime_resolver
        self.terminal_resolver, self.channel_resolver = terminal_resolver, channel_resolver
        self.channel_bridge = channel_bridge
        self.channel_service = channel_service
        self.trigger_bridge = trigger_bridge
        self.price_quote=price_quote
        self.clock = clock
        self._scheduler: Any = None
        self._handlers: dict[str, Callable[[dict], dict]] = {
            "schedule_list": self._do_schedule_list,
            "schedule_get": self._do_schedule_get,
            "schedule_create": self._do_schedule_create,
            "schedule_enable": self._do_schedule_enable,
            "schedule_disable": self._do_schedule_disable,
            "schedule_pause": self._do_schedule_pause,
            "schedule_resume": self._do_schedule_resume,
            "schedule_fire": self._do_schedule_fire,
            "goal_status": self._do_goal_status,
            "goal_set": self._do_goal_set,
            "goal_open": self._do_goal_open,
            "goal_advance": self._do_goal_advance,
            "goal_stop": self._do_goal_stop,
            "workflow_intent": self._do_workflow_intent,
            "workflow_observe": self._do_workflow_observe,
            "workflow_output": self._do_workflow_output,
            "runtime_intent": self._do_runtime_intent,
            "runtime_observe": self._do_runtime_observe,
            "terminal_list": self._do_terminal_list,
            "terminal_read": self._do_terminal_read,
            "terminal_write": self._do_terminal_write,
            "terminal_intent": self._do_terminal_intent,
            "receipt_get": self._do_receipt_get,
            "channel_list": self._do_channel_list,
            "channel_enable": self._do_channel_enable,
            "channel_renew": self._do_channel_renew,
            "channel_disable": self._do_channel_disable,
            "channel_revoke": self._do_channel_revoke,
            "channel_send_intent": self._do_channel_send_intent,
            "channel_inbox": self._do_channel_inbox,
            "channel_claim": self._do_channel_claim,
            "channel_ack": self._do_channel_ack,
        }
        self._idem: str | None = None
        if idempotency_database is not None:
            if workspace_root is None:
                raise ValueError("idempotency database requires a workspace root")
            root, target = Path(workspace_root).resolve(), Path(idempotency_database).resolve()
            if target == root or not target.is_relative_to(root):
                raise ValueError("shell idempotency projection outside workspace")
            if getattr(control.store, "backend", "sqlite") != "postgres":
                target.parent.mkdir(parents=True, exist_ok=True)
            self._idem = str(target)
            with self._db() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS pulso_shell_requests(
                    request_key TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    action TEXT NOT NULL, scope TEXT NOT NULL,
                    intent_sha256 TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'COMPLETED',
                    protected_response TEXT, error TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL)""")
                if getattr(control.store, "backend", "sqlite") != "postgres":
                    columns = {row["name"] for row in db.execute("PRAGMA table_info(pulso_shell_requests)").fetchall()}
                    for column, definition in (("intent_sha256", "TEXT NOT NULL DEFAULT ''"),
                            ("state", "TEXT NOT NULL DEFAULT 'COMPLETED'"), ("error", "TEXT"),
                            ("updated", "REAL NOT NULL DEFAULT 0")):
                        if column not in columns:
                            db.execute("ALTER TABLE pulso_shell_requests ADD COLUMN " + column + " " + definition)

    @contextmanager
    def _db(self):
        from .workflow_storage import projection_db
        with projection_db(self._idem, control=self.control) as conn:
            yield conn

    def _protect(self, value: dict) -> str:
        from sentra_core.conversations import _encode
        return _encode(value)

    def _unprotect(self, protected: str) -> dict:
        from sentra_core.conversations import _decode
        return _decode(protected)

    @staticmethod
    def _intent_sha(action: str, project_id: str, space_id: Any,
                    conversation_id: Any, params: dict) -> str:
        from .workflow_contracts import digest
        return digest({"action": action, "project_id": project_id,
                       "space_id": space_id, "conversation_id": conversation_id,
                       "params": params})

    # -- envelope ------------------------------------------------------
    def _envelope(self, *, action: str, owner: str, project_id: str,
                  request_key: str | None, space_id: str | None,
                  conversation_id: str | None, params: dict,
                  principal_id: str | None = None,
                  principal_type: str | None = None) -> dict:
        handler = self._handlers.get(action)
        if handler is None or action not in SHELL_ACTIONS:
            raise PulsoShellDenied("unknown Pulso shell action")
        if not isinstance(owner, str) or not owner:
            raise PulsoShellDenied("authenticated owner required")
        if not isinstance(project_id, str) or not 1 <= len(project_id) <= 512:
            raise PulsoShellDenied("bounded project_id required")
        key = request_key or uuid.uuid4().hex
        if not isinstance(key, str) or not REQUEST_KEY.fullmatch(key):
            raise PulsoShellDenied("bounded request_key required")
        if space_id is not None and not isinstance(space_id, str):
            raise PulsoShellDenied("invalid space scope")
        if conversation_id is not None and not isinstance(conversation_id, str):
            raise PulsoShellDenied("invalid conversation scope")
        if not isinstance(params, dict):
            raise PulsoShellDenied("action params must be a mapping")
        intruders = FORBIDDEN_PARAMS.intersection(params)
        if intruders:
            raise PulsoShellDenied(
                "renderer must not send identity/authority selectors: "
                + ",".join(sorted(intruders)))
        if principal_type is not None and principal_type not in {"user", "agent"}:
            raise PulsoShellDenied("invalid principal type")
        if self.canvas is not None:
            runtime = getattr(self.canvas, "_runtime", None)
            if callable(runtime):
                canonical = runtime().owner
                if owner != canonical:
                    raise PermissionError(
                        "shell owner must be the server-derived canonical owner")
            workspace = self.canvas.store.workspace(project_id)
            principal = principal_id or self.canvas.store.principal
            if workspace.get("owner") != principal:
                raise PermissionError("workspace does not belong to this principal")
        else:
            principal = principal_id or owner
        if action.startswith("channel_"):
            connector=params.get("connector_id")
            if connector and self.channel_service is not None:
                if self.channel_service.configuration(connector,active=False)["project_id"]!=project_id:
                    raise PermissionError("channel connector outside selected project")
            subscription=params.get("subscription_id")
            if subscription and self.channel_bridge is not None:
                with self.channel_bridge._db() as db:
                    row=db.execute("SELECT owner,project_id FROM channel_subscriptions WHERE subscription_id=?",(subscription,)).fetchone()
                if row is not None and (row["owner"]!=owner or row["project_id"]!=project_id):
                    raise PermissionError("channel subscription outside selected project")
        return {"action": action, "owner": owner, "principal": principal,
                "principal_type": principal_type or "user",
                "project_id": project_id, "request_key": key,
                "space_id": space_id, "conversation_id": conversation_id,
                "params": params, "scope": project_id,
                "intent_sha256": self._intent_sha(
                    action, project_id, space_id, conversation_id, params)}

    # -- reserve / replay / complete -----------------------------------
    def _reserve(self, ctx: dict) -> tuple[str, dict | None]:
        """Reserve the request key before any effect.

        Returns ("execute"|"replay"|"uncertain", recorded-or-None).
        """
        if self._idem is None:
            raise PulsoShellDenied(
                "idempotency store not composed; refusing mutating shell action")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM pulso_shell_requests WHERE request_key=?",
                             (ctx["request_key"],)).fetchone()
            if row is None:
                db.execute("INSERT INTO pulso_shell_requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (ctx["request_key"], ctx["owner"], ctx["action"],
                            ctx["scope"], ctx["intent_sha256"], "PENDING",
                            None, None, self.clock(), self.clock()))
                return "execute", None
            record = dict(row)
        if (record["owner"], record["action"], record["scope"]) != (
                ctx["owner"], ctx["action"], ctx["scope"]):
            raise PulsoShellDenied("request key bound to a different intent")
        if record["intent_sha256"] and record["intent_sha256"] != ctx["intent_sha256"]:
            raise PulsoShellDenied("request key bound to a different payload")
        if record["state"] == "COMPLETED" and record["protected_response"]:
            return "replay", record
        return "uncertain", record

    def _complete(self, ctx: dict, value: dict) -> None:
        with self._db() as db:
            updated = db.execute(
                "UPDATE pulso_shell_requests SET state='COMPLETED',"
                "protected_response=?,error=NULL,updated=? "
                "WHERE request_key=? AND state='PENDING'",
                (self._protect(value), self.clock(), ctx["request_key"])).rowcount
            if updated != 1:
                raise PulsoShellDenied(
                    "request key changed concurrently; reconcile before retry")

    def _mark_uncertain(self, ctx: dict, error: str) -> None:
        try:
            with self._db() as db:
                db.execute("UPDATE pulso_shell_requests SET state='UNCERTAIN',"
                           "error=?,updated=? WHERE request_key=?",
                           (error[:500], self.clock(), ctx["request_key"]))
        except Exception:
            pass

    @staticmethod
    def _uncertain_value(reason: str, request_key: str) -> dict:
        return {"ok": True,
                "value": {"status": "uncertain", "reason": reason,
                          "reconcile_with_key": request_key,
                          "duplicate_submission": False},
                "request_key": request_key}

    # -- entry point ---------------------------------------------------
    def dispatch(self, *, action: str, owner: str, project_id: str,
                 request_key: str | None = None, space_id: str | None = None,
                 conversation_id: str | None = None,
                 params: dict | None = None,
                 principal_id: str | None = None,
                 principal_type: str | None = None) -> dict:
        """Robust shell dispatch: validate, reserve, execute, record.

        ``owner`` is the server-derived canonical CP owner and
        ``principal_id`` the server-derived principal; neither ever comes
        from the browser (the route strips them and params carrying them
        are denied here as defense in depth).
        """
        ctx = self._envelope(action=action, owner=owner, project_id=project_id,
                             request_key=request_key, space_id=space_id,
                             conversation_id=conversation_id, params=params or {},
                             principal_id=principal_id,
                             principal_type=principal_type)
        handler = self._handlers[ctx["action"]]
        if ctx["action"] in READ_ACTIONS:
            value = handler(ctx)
            if not isinstance(value, dict):
                raise PulsoShellDenied("shell handler returned invalid projection")
            return {"ok": True, "value": value, "request_key": ctx["request_key"]}
        mode, record = self._reserve(ctx)
        if mode == "replay":
            assert record is not None
            return {"ok": True, "value": self._unprotect(record["protected_response"]),
                    "request_key": ctx["request_key"], "idempotent_replay": True}
        if mode == "uncertain":
            return self._uncertain_value(
                "request already admitted with unknown outcome; "
                "reconcile receipts before any new submission",
                ctx["request_key"])
        try:
            value = handler(ctx)
        except Exception as exc:
            self._mark_uncertain(ctx, type(exc).__name__)
            raise
        if not isinstance(value, dict):
            self._mark_uncertain(ctx, "handler returned invalid projection")
            raise PulsoShellDenied("shell handler returned invalid projection")
        self._complete(ctx, value)
        return {"ok": True, "value": value, "request_key": ctx["request_key"]}

    # -- server-derived bindings ---------------------------------------
    def _project_run_id(self, ctx: dict) -> str:
        """Resolve the project's Run server-side (never from the renderer)."""
        if self.canvas is not None:
            runtime = getattr(self.canvas, "_runtime", None)
            if callable(runtime):
                run = runtime().run(ctx["project_id"])
                if not isinstance(run, dict) or not run.get("run_id"):
                    raise PulsoShellDenied("project Run unavailable")
                return str(run["run_id"])
        resolve = getattr(getattr(self.control, "shell", None), "resolve_run", None)
        if callable(resolve):
            run_id = resolve(ctx["project_id"], ctx["owner"])
            if not isinstance(run_id, str) or not run_id:
                raise PulsoShellDenied("project Run unavailable")
            return run_id
        raise PulsoShellDenied("project Run resolution not composed")

    def _routine_authority(self, ctx: dict, routine: dict) -> str | None:
        """Confirm routine project pin and real Run; return bound run or None."""
        from pathlib import Path as _Path
        metadata = dict(routine.get("metadata") or {})
        project_pin = metadata.get("workspace_id", metadata.get("shell_project_id"))
        if project_pin is not None and str(project_pin) != ctx["project_id"]:
            raise PermissionError("routine bound to another project")
        bound = str(metadata.get("_runtime_authority_run_id") or "").strip()
        if not bound:
            return None
        try:
            run = self.control.durable.run_status(bound, ctx["owner"])
        except FileNotFoundError:
            raise PulsoShellDenied("routine authority Run is missing")
        if self.canvas is not None:
            workspace = self.canvas.store.workspace(ctx["project_id"])
            run_workspace = run.get("workspace")
            if not run_workspace or _Path(run_workspace).resolve() != _Path(
                    workspace["path"]).resolve():
                raise PermissionError("routine Run belongs to another workspace")
        return bound

    # -- schedules -----------------------------------------------------
    def _do_schedule_list(self, ctx: dict) -> dict:
        limit = ctx["params"].get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise PulsoShellDenied("list limit must be 1..200")
        listed = self.governance.list_routines(ctx["owner"])
        items = []
        for routine in listed.get("items", []):
            try:
                bound = self._routine_authority(ctx, routine)
            except PermissionError:
                continue
            except PulsoShellDenied:
                bound = None
            items.append({"routine_id": routine["routine_id"],
                          "name": routine.get("name"), "enabled": routine.get("enabled"),
                          "trigger_kind": routine.get("trigger_kind"),
                          "authority_run_confirmed": bound is not None,
                          "scope_confirmed": True})
            if len(items) >= limit:
                break
        return {"items": items,
                "page": {"limit": limit, "returned": len(items),
                         "total": len(items),
                         "scope": ctx["project_id"]}}

    def _do_schedule_get(self, ctx: dict) -> dict:
        routine_id = ctx["params"].get("routine_id", "")
        if not isinstance(routine_id, str) or not routine_id:
            raise PulsoShellDenied("routine_id required")
        routine = self.governance.routine_info(routine_id, ctx["owner"])
        bound = self._routine_authority(ctx, routine)
        routine.pop("trigger_spec_json", None)
        return {"routine": routine, "authority_run_id": bound,
                "scope_confirmed": True}

    def _do_schedule_create(self, ctx: dict) -> dict:
        from sentra_mcp.services.routine_scheduler import RoutineScheduleTZ
        params = ctx["params"]
        trigger_spec = params.get("trigger_spec")
        if not isinstance(trigger_spec, dict):
            raise PulsoShellDenied("trigger_spec mapping required")
        if "every_after_completion_seconds" in trigger_spec:
            RoutineScheduleTZ.next_due_after_completion(
                trigger_spec, None, self.clock())
        else:
            RoutineScheduleTZ.next_due(trigger_spec, self.clock())
        work_template = params.get("work_template")
        if not isinstance(work_template, dict) or not work_template.get("objective"):
            raise PulsoShellDenied("work_template.objective required")
        metadata: dict[str, Any] = {"workspace_id": ctx["project_id"],
                                    "shell_project_id": ctx["project_id"],
                                    "shell_space_id": ctx["space_id"]}
        max_failures = params.get("max_consecutive_failures", 0)
        if max_failures:
            if type(max_failures) is not int or not 1 <= max_failures <= 100:
                raise PulsoShellDenied("max_consecutive_failures must be 1..100")
            metadata["_pulso_max_consecutive_failures"] = max_failures
        cost_cap = params.get("cost_cap_usd")
        if cost_cap is not None:
            if (type(cost_cap) not in (int, float) or cost_cap != cost_cap
                    or not 0 < cost_cap <= 1_000_000):
                raise PulsoShellDenied("bounded positive cost cap required")
            metadata["_pulso_cost_cap_usd"] = float(cost_cap)
        routine = self.governance.create_routine(
            ctx["owner"], name=str(params.get("name", "shell-schedule"))[:200],
            trigger_kind="schedule", trigger_spec=trigger_spec,
            work_template=work_template,
            active_policy=params.get("active_policy", "coalesce_if_active"),
            missed_policy=params.get("missed_policy", "skip_missed"),
            missed_cap=params.get("missed_cap", 1),
            enabled=params.get("enabled", True),
            metadata=metadata)
        return {"routine_id": routine["routine_id"], "status": "created",
                "scope_confirmed": True}

    def _do_schedule_enable(self, ctx: dict) -> dict:
        routine_id = ctx["params"].get("routine_id", "")
        if not routine_id:
            raise PulsoShellDenied("routine_id required")
        routine = self.governance.routine_info(routine_id, ctx["owner"])
        self._routine_authority(ctx, routine)
        self.governance.set_routine_enabled(routine_id, ctx["owner"], enabled=True)
        return {"routine_id": routine_id, "enabled": True}

    def _do_schedule_disable(self, ctx: dict) -> dict:
        routine_id = ctx["params"].get("routine_id", "")
        if not routine_id:
            raise PulsoShellDenied("routine_id required")
        routine = self.governance.routine_info(routine_id, ctx["owner"])
        self._routine_authority(ctx, routine)
        self.governance.set_routine_enabled(routine_id, ctx["owner"], enabled=False)
        return {"routine_id": routine_id, "enabled": False}

    def _scheduler_service(self):
        if self._scheduler is None:
            from sentra_mcp.services.routine_scheduler import RoutineSchedulerService
            self._scheduler = RoutineSchedulerService(
                self.control, clock=self.clock)
        return self._scheduler

    def _do_schedule_pause(self, ctx: dict) -> dict:
        routine_id = ctx["params"].get("routine_id", "")
        if not routine_id:
            raise PulsoShellDenied("routine_id required")
        routine = self.governance.routine_info(routine_id, ctx["owner"])
        self._routine_authority(ctx, routine)
        return self._scheduler_service().set_paused(
            routine_id, ctx["owner"], paused=True,
            reason=ctx["params"].get("reason"),
            operator_approved=ctx["params"].get("operator_approved"))

    def _do_schedule_resume(self, ctx: dict) -> dict:
        routine_id = ctx["params"].get("routine_id", "")
        if not routine_id:
            raise PulsoShellDenied("routine_id required")
        routine = self.governance.routine_info(routine_id, ctx["owner"])
        self._routine_authority(ctx, routine)
        return self._scheduler_service().set_paused(
            routine_id, ctx["owner"], paused=False, reason=None,
            operator_approved=ctx["params"].get("operator_approved"))

    def _do_schedule_fire(self, ctx: dict) -> dict:
        params = ctx["params"]
        routine_id = params.get("routine_id", "")
        if not isinstance(routine_id, str) or not routine_id:
            raise PulsoShellDenied("routine_id required")
        if params.get("operator_approved") is not True:
            raise PermissionError("manual schedule fire requires host owner approval")
        routine = self.governance.routine_info(routine_id, ctx["owner"])
        bound = self._routine_authority(ctx, routine)
        if not bound:
            return {"routine_id": routine_id, "status": "UNBOUND",
                    "reason": "scheduled routine has no runtime authority Run binding"}
        metadata = dict(routine.get("metadata") or {})
        goal_id = str(metadata.get("_runtime_goal_id") or "").strip() or None
        outcome = self.control.fire_routine(
            routine_id, ctx["owner"], run_id=bound, goal_id=goal_id,
            source="shell:" + ctx["request_key"],
            occurrence_key="shell-" + ctx["request_key"])
        work = outcome.get("work_item") or {}
        receipt = None
        if work.get("work_item_id"):
            receipt = {"work_item_id": work["work_item_id"],
                       "projection": "see receipt_get after dispatch"}
        return {"status": outcome.get("status"), "routine_id": routine_id,
                "run_id": bound,
                "work_item": {"work_item_id": work.get("work_item_id")},
                "receipt": receipt}

    # -- goals ---------------------------------------------------------
    def _goals(self, ctx: dict):
        from sentra_executors.goal_loop import ConversationGoalLoop
        return ConversationGoalLoop(self.control, self.conversations, clock=self.clock, price_quote=self.price_quote)

    def _do_goal_status(self, ctx: dict) -> dict:
        conversation_id = ctx["conversation_id"] or ctx["params"].get("conversation_id", "")
        if not conversation_id:
            raise PulsoShellDenied("conversation scope required for goal status")
        return self._goals(ctx).status(ctx["owner"], conversation_id)

    def _do_goal_set(self, ctx: dict) -> dict:
        params = ctx["params"]
        conversation_id = ctx["conversation_id"] or params.get("conversation_id", "")
        if not conversation_id or not params.get("objective"):
            raise PulsoShellDenied("conversation_id and objective required")
        run_id = self._project_run_id(ctx)
        return self._goals(ctx).set(
            ctx["owner"], conversation_id, run_id=run_id,
            objective=params["objective"], operator_approved=params.get("operator_approved"))

    def _do_goal_open(self, ctx: dict) -> dict:
        params = ctx["params"]
        conversation_id = ctx["conversation_id"] or params.get("conversation_id", "")
        agent_id = params.get("agent_id", "")
        if not conversation_id or not agent_id:
            raise PulsoShellDenied("conversation_id and agent_id required")
        run_id = self._project_run_id(ctx)
        run = self.control._run(run_id, ctx["owner"])
        self.control._agent_from_run(run, agent_id)
        return self._goals(ctx).open(
            ctx["owner"], conversation_id, principal_id=agent_id,
            max_steps=params.get("max_steps", 2),
            max_cost_usd=params.get("max_cost_usd", 0.0),
            deadline_seconds=params.get("deadline_seconds", 120),
            operator_approved=params.get("operator_approved"))

    def _do_goal_advance(self, ctx: dict) -> dict:
        params = ctx["params"]
        conversation_id = ctx["conversation_id"] or params.get("conversation_id", "")
        if not conversation_id or not params.get("objective"):
            raise PulsoShellDenied("conversation_id and objective required")
        return self._goals(ctx).advance(
            ctx["owner"], conversation_id, objective=params["objective"],
            operator_approved=params.get("operator_approved"))

    def _do_goal_stop(self, ctx: dict) -> dict:
        params = ctx["params"]
        conversation_id = ctx["conversation_id"] or params.get("conversation_id", "")
        if not conversation_id:
            raise PulsoShellDenied("conversation scope required to stop goal")
        service = self._goals(ctx)
        if params.get("loop_only"):
            return service.loop_stop(ctx["owner"], conversation_id,
                                     operator_approved=params.get("operator_approved"))
        return service.stop(ctx["owner"], conversation_id,
                            operator_approved=params.get("operator_approved"))

    # -- workflows -----------------------------------------------------
    def _execute_resolver(self, resolver, ctx, params):
        if resolver is None:
            raise PulsoShellDenied("executing MachineHost resolver unavailable")
        value = resolver("execute", ctx, dict(params))
        if not isinstance(value, dict) or not value.get("operation_id") or value.get("state") not in {
                "ACCEPTED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}:
            raise PulsoShellDenied("resolver must return an executed Operation and receipt")
        return value

    def _do_workflow_intent(self, ctx):
        params = ctx["params"]
        if params.get("intent_kind") not in {"create", "advance", "resume", "signal", "cancel", "observe", "output", "memory"}:
            raise PulsoShellDenied("unknown workflow operation")
        return self._execute_resolver(self.workflow_resolver, ctx, params)

    def _do_workflow_observe(self, ctx: dict) -> dict:
        if self.workflow_resolver is None:
            raise PulsoShellDenied(
                "workflow bridge not composed; host must inject workflow_resolver")
        return self.workflow_resolver("observe", ctx, ctx["params"])

    def _do_workflow_output(self, ctx: dict) -> dict:
        if self.workflow_resolver is None:
            raise PulsoShellDenied(
                "workflow bridge not composed; host must inject workflow_resolver")
        return self.workflow_resolver("output", ctx, ctx["params"])

    # -- external runtimes ---------------------------------------------
    def _do_runtime_intent(self, ctx):
        params = ctx["params"]
        if params.get("provider") not in RUNTIME_PROVIDERS or params.get("operation") not in RUNTIME_OPERATIONS:
            raise PulsoShellDenied("unknown configured runtime operation")
        if params.get("provider") == "temporal" and params.get("operation") == "fork":
            raise PulsoShellDenied("fork is a LangGraph-only operation")
        return self._execute_resolver(self.runtime_resolver, ctx, params)

    def _do_runtime_observe(self, ctx: dict) -> dict:
        if self.runtime_resolver is None:
            raise PulsoShellDenied(
                "runtime bridge not composed; host must inject runtime_resolver")
        return self.runtime_resolver("observe", ctx, ctx["params"])

    # -- terminals -----------------------------------------------------
    def _terminal(self, ctx: dict):
        from sentra_executors.conpty_sessions import ExistingConPTYSession
        if self.canvas is None:
            raise PulsoShellDenied("terminal actions require composed Canvas host")
        return ExistingConPTYSession(control=self.control, canvas=self.canvas)

    def _terminal_scope(self, ctx: dict) -> dict:
        """Resolve terminal run/work-item/principal from the server ledger."""
        from sentra_executors.conpty_sessions import PersistentConPTYLedger
        if self.canvas is None:
            raise PulsoShellDenied("terminal actions require composed Canvas host")
        terminal_id = ctx["params"].get("terminal_id", "")
        if not isinstance(terminal_id, str) or not terminal_id:
            raise PulsoShellDenied("terminal_id required")
        ledger = PersistentConPTYLedger(self.control)
        try:
            binding = ledger.get(ctx["owner"], ctx["project_id"], terminal_id)
        except FileNotFoundError:
            raise PulsoShellDenied("terminal session not registered for this project")
        return {"run_id": binding["run_id"],
                "work_item_id": binding["work_item_id"],
                "principal_id": binding["principal_id"],
                "workspace_id": ctx["project_id"],
                "terminal_id": terminal_id}

    def _do_terminal_list(self, ctx: dict) -> dict:
        from sentra_executors.conpty_sessions import PersistentConPTYLedger
        ledger = PersistentConPTYLedger(self.control)
        return {"terminals": ledger.sessions(ctx["owner"], ctx["project_id"])}

    def _do_terminal_read(self,ctx):
        self._terminal_scope(ctx)
        if self.terminal_resolver is None:
            raise PulsoShellDenied("central terminal observation resolver unavailable")
        return self.terminal_resolver("observe",ctx,ctx["params"])

    def _do_terminal_intent(self,ctx):
        operation=ctx["params"].get("operation")
        if operation not in {"start","read","write","close"}:
            raise PulsoShellDenied("unknown terminal operation")
        if operation!="start":
            self._terminal_scope(ctx)
        return self._execute_resolver(self.terminal_resolver,ctx,ctx["params"])

    def _do_terminal_write(self, ctx):
        self._terminal_scope(ctx)
        return self._execute_resolver(self.terminal_resolver, ctx, ctx["params"])

    # -- receipts ------------------------------------------------------
    def _do_receipt_get(self, ctx: dict) -> dict:
        from sentra_executors.operation_receipts import HumanReceiptViews
        params = ctx["params"]
        operation_id = params.get("target_operation_id", "")
        if not isinstance(operation_id, str) or not operation_id:
            raise PulsoShellDenied("target_operation_id required")
        operation = self.control.durable.operation_status(operation_id, ctx["owner"])
        work_item = operation.get("progress", {}).get("work_item_id")
        if not work_item or self.control.work_item_info(work_item, ctx["owner"]).get("metadata", {}).get("workspace_id") != ctx["project_id"]:
            raise PermissionError("receipt outside selected project")
        views = HumanReceiptViews(self.control)
        return views.human_receipt(
            ctx["owner"], operation_id,
            work_item_id=work_item)

    # -- channels ------------------------------------------------------
    def _channels(self):
        if self.channel_bridge is None:
            raise PulsoShellDenied(
                "channel bridge not composed; host must inject ChannelTriggerBridge")
        return self.channel_bridge

    def _channel_service(self, ctx: dict):
        service = self.channel_service
        if service is None:
            raise PulsoShellDenied(
                "Lume ChannelService not composed; host must inject it")
        if getattr(service, "owner", ctx["owner"]) != ctx["owner"]:
            raise PermissionError("channel service bound to another owner")
        return service

    def _do_channel_list(self, ctx: dict) -> dict:
        limit = ctx["params"].get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise PulsoShellDenied("list limit must be 1..200")
        return {"subscriptions": self._channels().list(ctx["owner"], limit=limit)}

    def _do_channel_enable(self, ctx: dict) -> dict:
        params = ctx["params"]
        if not params.get("subscription_id"):
            raise PulsoShellDenied("subscription_id required")
        return self._channels().enable(
            owner=ctx["owner"], subscription_id=params["subscription_id"],
            channel=params.get("channel", ""), project_id=ctx["project_id"],
            allow_workspaces=params.get("allow_workspaces", []),
            allow_users=params.get("allow_users", []),
            secret_id=params.get("secret_id"),
            external_subscription_id=params.get("external_subscription_id"),
            ttl_seconds=params.get("ttl_seconds"),
            operator_approved=params.get("operator_approved"))

    def _do_channel_renew(self, ctx: dict) -> dict:
        params = ctx["params"]
        if not params.get("subscription_id") or params.get("ttl_seconds") is None:
            raise PulsoShellDenied("subscription_id and ttl_seconds required")
        return self._channels().renew(
            owner=ctx["owner"], subscription_id=params["subscription_id"],
            ttl_seconds=params["ttl_seconds"],
            operator_approved=params.get("operator_approved"))

    def _do_channel_disable(self, ctx: dict) -> dict:
        params = ctx["params"]
        if not params.get("subscription_id"):
            raise PulsoShellDenied("subscription_id required")
        return self._channels().disable(
            owner=ctx["owner"], subscription_id=params["subscription_id"],
            operator_approved=params.get("operator_approved"))

    def _do_channel_revoke(self, ctx: dict) -> dict:
        params = ctx["params"]
        if not params.get("subscription_id"):
            raise PulsoShellDenied("subscription_id required")
        return self._channels().revoke(
            owner=ctx["owner"], subscription_id=params["subscription_id"],
            operator_approved=params.get("operator_approved"))

    def _do_channel_send_intent(self, ctx: dict) -> dict:
        """Stage (never deliver) one outbound notification.

        The route handler admits the staged dedupe key as a distinct
        central operation with capability ``channel:send`` and drives
        Lume's ``send`` inside admission; per-recipient receipt follows.
        """
        params = ctx["params"]
        if not params.get("subscription_id") or not params.get("recipient"):
            raise PulsoShellDenied("subscription_id and recipient required")
        if not isinstance(params.get("payload"), dict):
            raise PulsoShellDenied("notification payload mapping required")
        if not params.get("dedupe_key"):
            raise PulsoShellDenied("bounded notification dedupe key required")
        staged = self._channels().stage_notification(
            owner=ctx["owner"], subscription_id=params["subscription_id"],
            recipient=params["recipient"], payload=params["payload"],
            dedupe_key=params["dedupe_key"])
        return self._execute_resolver(self.channel_resolver, ctx, {**params, "staged": staged})

    def _do_channel_inbox(self, ctx: dict) -> dict:
        params = ctx["params"]
        limit = params.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise PulsoShellDenied("list limit must be 1..200")
        if params.get("connector_id") and self.channel_service is not None:
            service = self._channel_service(ctx)
            return {"events": service.pending_inbound(
                connector_id=params["connector_id"],
                project_id=ctx["project_id"], limit=min(limit, 100))}
        if not params.get("subscription_id"):
            raise PulsoShellDenied(
                "connector_id (Lume inbox) or subscription_id (local bridge) required")
        return {"events": self._channels().inbound_events(
            ctx["owner"], params["subscription_id"], limit=limit)}

    def _triggers(self):
        bridge = self.trigger_bridge
        if bridge is None:
            raise PulsoShellDenied(
                "channel trigger bridge not composed; host must inject "
                "ChannelWorkflowTrigger")
        return bridge

    def _do_channel_claim(self, ctx: dict) -> dict:
        """Claim one Lume inbox event and bind it to the routed workflow.

        The consumer is derived server-side (``pulso-trigger:<principal>``);
        the workflow comes from the host-bound route — never the renderer.
        Returns the claim plus the exact ``workflow:signal`` intent for the
        host to admit as a distinct central operation.
        """
        params = ctx["params"]
        connector_id = params.get("connector_id", "")
        event_id = params.get("event_id", "")
        if not connector_id or not event_id:
            raise PulsoShellDenied("connector_id and event_id required")
        expected_revision = params.get("expected_revision")
        if type(expected_revision) is not int or expected_revision < 1:
            raise PulsoShellDenied("expected_revision CAS value required")
        lease_seconds = params.get("lease_seconds", 60)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise PulsoShellDenied("lease_seconds must be 1..300")
        consumer_id = "pulso-trigger:" + ctx["principal"][:100]
        trigger = self._triggers()
        intent = trigger.claim_for_workflow(ctx["owner"], connector_id=connector_id,
            event_id=event_id, consumer_id=consumer_id, expected_revision=expected_revision,
            lease_seconds=lease_seconds)
        payload = trigger.signal_payload(ctx["owner"], intent["dispatch_idempotency_key"])
        derived = {**ctx, "request_key": intent["dispatch_idempotency_key"]}
        parameters = {"intent_kind": "signal", "workflow_id": intent["arguments"]["workflow_id"],
            "namespace": intent["arguments"]["namespace"], "name": intent["arguments"]["name"],
            "signal_id": intent["arguments"]["signal_id"], "payload": payload}
        # Stable server ID is recorded before dispatch; recovery can only reconcile it.
        from .workflow_shell_host import server_operation_id
        operation_id = server_operation_id(derived, "workflow:signal")
        trigger.mark_admitted(dispatch_key=intent["dispatch_idempotency_key"], operation_id=operation_id)
        result = self._execute_resolver(self.workflow_resolver, derived, parameters)
        item = self.control.durable.operation_status(result["operation_id"], ctx["owner"])["progress"]["work_item_id"]
        acknowledgement = trigger.confirm_dispatch(ctx["owner"],
            dispatch_key=intent["dispatch_idempotency_key"], work_item_id=item, operation_id=result["operation_id"])
        return {**result, "channel_ack": acknowledgement}

    def _do_channel_ack(self, ctx: dict) -> dict:
        """Acknowledge a claim (SUCCEEDED-only, else uncertain via Lume)."""
        params = ctx["params"]
        claim_id, operation_id = params.get("claim_id"), params.get("target_operation_id")
        if not claim_id or not operation_id:
            raise PulsoShellDenied("claim_id and target_operation_id required")
        operation = self.control.durable.operation_status(operation_id, ctx["owner"])
        item = operation.get("progress", {}).get("work_item_id")
        return self._triggers().ack_claim(ctx["owner"], claim_id=claim_id,
            work_item_id=item, operation_id=operation_id, receipt_id=operation_id)
