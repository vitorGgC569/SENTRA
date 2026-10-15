"""Host-gated Code Mode admission + REAL bounded execution (A08 compositor).

Engines:
  - ``bounded-js`` (built-in, explicit interim opt-in): JS-subset interpreter in
    :mod:`sentra_code_mode.bounded_js`. Executes real bounded code today:
    fuel, memory, wall-time, tool-call, source and result bounds, watchdog
    thread + cancel event, no host I/O.
  - ``quickjs-wasm``: real QuickJS WASM via :mod:`sentra_code_mode.quickjs_runtime`
    (pinned artifact + CycloneDX SBOM, wasmtime, no WASI, fuel, memory cap,
    watchdog/interrupt, tool outbox). Explicitly UNAVAILABLE until the reviewed
    artifact + ``wasmtime`` + guest ABI are present; never falls back to
    Python eval, Node or VM subprocess.

Every composed inner tool call (``call_tool(name, args)``) requires its own
host-created OperationRequest decided and fenced by the central
Control Plane (CentralInteropAdapter gate). The sandbox never mints grants.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from . import (CodeModeBudgetExceeded, CodeModeCancelled, CodeModeDisabled,
               CodeModeUnavailable, CodeModeUncertain, QuickJSArtifact, ResourceLimits)
from .schema import CODE_MODE_SIGNATURE


_ENGINES = ("bounded-js", "quickjs-wasm")


class CodeModeDispatcher:
    """Admission + bounded execution bound to the central Control Plane.

    Default engine is ``quickjs-wasm`` (the only A08-satisfying engine, with
    a pinned guest artifact). ``bounded-js`` is an explicit opt-in INTERIM
    engine for development without the guest binary; its receipts always
    carry ``a08_satisfied: False`` and it is NEVER presented as the A08
    solution.
    """

    def __init__(self, control, *, limits: ResourceLimits | None = None,
                 engine: str = "quickjs-wasm",
                 artifact: QuickJSArtifact | None = None):
        if engine not in _ENGINES:
            raise ValueError("unknown Code Mode engine")
        self.control = control
        self.store = control.store
        self.limits = limits or ResourceLimits()
        self.engine = engine
        self.artifact = artifact
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS code_mode_proposals(
                    proposal_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    workspace TEXT NOT NULL, run_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL, source_bytes INTEGER NOT NULL,
                    engine TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS code_mode_denials(
                    proposal_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    denied_at REAL NOT NULL, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS code_mode_executions(
                    execution_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL,
                    owner TEXT NOT NULL, operation_id TEXT NOT NULL,
                    state TEXT NOT NULL, engine TEXT NOT NULL,
                    result_sha256 TEXT, result_bytes INTEGER,
                    tool_calls INTEGER NOT NULL DEFAULT 0,
                    fuel_used INTEGER NOT NULL DEFAULT 0,
                    error TEXT, created REAL NOT NULL, updated REAL NOT NULL);
            """)
            columns = {row[1] for row in
                       db.execute("PRAGMA table_info(code_mode_proposals)").fetchall()}
            if "engine" not in columns:
                db.execute("ALTER TABLE code_mode_proposals ADD COLUMN engine TEXT NOT NULL DEFAULT 'bounded-js'")
            db.execute("CREATE TABLE IF NOT EXISTS code_mode_execution_bindings("
                       "owner TEXT NOT NULL,operation_id TEXT NOT NULL,proposal_id TEXT NOT NULL,"
                       "request_key TEXT NOT NULL,intent_sha256 TEXT NOT NULL,"
                       "protected_result TEXT,PRIMARY KEY(owner,operation_id),"
                       "UNIQUE(owner,request_key))")
            db.execute("CREATE TABLE IF NOT EXISTS code_mode_dispatch_bindings("
                       "owner TEXT NOT NULL,operation_id TEXT NOT NULL,request_key TEXT NOT NULL,"
                       "intent_sha256 TEXT NOT NULL,proposal_id TEXT NOT NULL,"
                       "PRIMARY KEY(owner,operation_id),UNIQUE(owner,request_key))")

    @contextmanager
    def _db(self):
        db = self.store.connect("governance")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _cancel_flag(self, proposal_id: str) -> threading.Event:
        with self._cancel_lock:
            flag = self._cancel_events.get(proposal_id)
            if flag is None:
                flag = threading.Event()
                self._cancel_events[proposal_id] = flag
            return flag

    # -- admission ------------------------------------------------------
    def _binding(self, owner, workspace, run_id, work_item_id, agent_id, *, active=True):
        run = self.control.durable.run_status(run_id, owner)
        work = self.control.work_item_info(work_item_id, owner)
        if (str(Path(run["workspace"]).resolve()) != str(Path(workspace).resolve(strict=True))
                or work["run_id"] != run_id
                or work["assignee_agent_id"] != agent_id
                or (active and (run.get("state") not in {"CREATED", "RUNNING", "PAUSED"}
                    or work.get("state") not in {"QUEUED", "RUNNING", "BLOCKED", "VALIDATING"}))):
            raise PermissionError("Code Mode requires an active, assigned WorkItem in this workspace")
        self.control._agent_from_run(run, agent_id)

    def propose(self, *, owner, workspace, run_id, work_item_id, agent_id,
                source, engine: str | None = None) -> dict[str, Any]:
        """Admit a bounded source snapshot; inert, never executes."""
        if type(source) is not str:
            raise ValueError("Code Mode source must be text")
        raw = source.encode("utf-8")
        if not 1 <= len(raw) <= self.limits.max_source_bytes:
            raise ValueError("Code Mode source outside bounds")
        selected = engine or self.engine
        if selected not in _ENGINES:
            raise ValueError("unknown Code Mode engine")
        self._binding(owner, workspace, run_id, work_item_id, agent_id)
        root = str(Path(workspace).resolve(strict=True))
        proposal_id = "code-" + secrets.token_hex(16)
        digest = hashlib.sha256(raw).hexdigest()
        now = time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO code_mode_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (proposal_id, owner, root, run_id, work_item_id, agent_id,
                        digest, len(raw), selected, "PROPOSED",
                        "ADMITTED_INERT_EXECUTION_PENDING", now, now))
        with self._cancel_lock:
            self._cancel_events.pop(proposal_id, None)
        return {"proposal_id": proposal_id, "source_sha256": digest,
                "source_bytes": len(raw), "engine": selected, "state": "PROPOSED",
                "a08_satisfied": False, "execution_verified": False,
                "interim_engine": selected == "bounded-js",
                "grants_created": False, "worker_started": False,
                "effect": "pending_execution"}

    def _get_proposal(self, owner, proposal_id) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute("SELECT * FROM code_mode_proposals WHERE proposal_id=? AND owner=?",
                             (proposal_id, owner)).fetchone()
        if row is None:
            raise FileNotFoundError("Code Mode proposal not found for this owner")
        return dict(row)

    def status(self, owner, proposal_id) -> dict[str, Any]:
        item = self._get_proposal(owner, proposal_id)
        with self._db() as db:
            executions = db.execute(
                "SELECT * FROM code_mode_executions WHERE proposal_id=? AND owner=? "
                "ORDER BY created DESC LIMIT 8", (proposal_id, owner)).fetchall()
        item["limits"] = self.limits.as_dict()
        item["executions"] = [{**dict(row), "a08_satisfied": self._a08_execution(dict(row))} for row in executions]
        item["cancel_requested"] = self._cancel_flag(proposal_id).is_set() or item["reason"] == "CANCEL_REQUESTED"
        item["a08_satisfied"] = any(self._a08_execution(dict(row)) for row in executions)
        if not item["a08_satisfied"]:
            item["scope_note"] = ("bounded-js is an explicit interim engine; "
                                  "A08 is satisfied only by engine 'quickjs-wasm' "
                                  "with the pinned guest artifact")
        return item

    def cancel(self, owner, proposal_id) -> dict[str, Any]:
        """Request cancellation; the running watchdog/interrupt observes it."""
        item = self._get_proposal(owner, proposal_id)
        self._cancel_flag(proposal_id).set()
        # The live runner shares this event. Never cancel a fresh unused runner.
        now = time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            fresh = db.execute("SELECT state FROM code_mode_proposals WHERE owner=? AND proposal_id=?",
                               (owner, proposal_id)).fetchone()
            if fresh["state"] == "PROPOSED":
                db.execute("UPDATE code_mode_proposals SET state='CANCELLED',"
                           "reason='CANCELLED_BEFORE_EXECUTION',updated=? "
                           "WHERE proposal_id=? AND owner=? AND state='PROPOSED'", (now, proposal_id, owner))
                item = {**item, "state": "CANCELLED", "reason": "CANCELLED_BEFORE_EXECUTION"}
            elif fresh["state"] in {"RUNNING", "UNCERTAIN"}:
                db.execute("UPDATE code_mode_proposals SET reason='CANCEL_REQUESTED',updated=? WHERE owner=? AND proposal_id=?",
                           (now, owner, proposal_id))
                item = {**item, "state": fresh["state"], "reason": "CANCEL_REQUESTED"}
        return {"proposal_id": proposal_id, "cancel_requested": True,
                "state": item["state"], "grants_created": False}

    def inventory(self, owner, *, limit: int = 50) -> dict[str, Any]:
        """Read-only proposal inventory for Nexo/root (same authority).

        Lists admitted proposals with engine, state and latest execution
        state. No grants, no execution, no source bytes (content-addressed
        digests only).
        """
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("bounded inventory listing required")
        with self._db() as db:
            rows = db.execute(
                "SELECT p.proposal_id,p.run_id,p.work_item_id,p.agent_id,"
                "p.source_sha256,p.source_bytes,p.engine,p.state,p.created,p.updated,"
                "(SELECT state FROM code_mode_executions e "
                "WHERE e.proposal_id=p.proposal_id AND e.owner=p.owner "
                "ORDER BY e.created DESC LIMIT 1) AS last_execution "
                "FROM code_mode_proposals p WHERE p.owner=? "
                "ORDER BY p.created DESC LIMIT ?", (owner, limit)).fetchall()
        return {"owner": owner,
                "items": [{**dict(r),
                           "a08_satisfied": False,
                           "execution_state": dict(r).get("last_execution")}
                          for r in rows],
                "grants_created": False}

    def discovery(self) -> dict[str, Any]:
        """Read-only composition discovery for Nexo/root (same authority).

        Publishes the method signature, engine selection, limits and live
        admission status. No owner data, no grants.
        """
        from . import QuickJSWasmAdmission
        admission = QuickJSWasmAdmission(
            limits=self.limits, artifact=self.artifact).status()
        return {"signature": CODE_MODE_SIGNATURE, "engine": self.engine,
                "artifact_configured": self.artifact is not None,
                "admission": admission, "grants_created": False}

    # -- execution ------------------------------------------------------
    async def execute(self, *, owner, proposal_id, operation_id=None,
                      idempotency_key=None, source: str | None = None,
                      tools: Mapping[str, Callable[[Any], Any | Awaitable[Any]]] | None = None,
                      source_operation_id: str | None = None) -> dict[str, Any]:
        """Execute the admitted proposal under full bounds + central fencing.

        ``tools`` maps allowlisted tool names to HOST-SELECTED callables
        (never JS-provided). Each ``call_tool`` inside the sandbox reserves
        its own OperationRequest through the central gate; a denied grant
        fails the execution without partial effects. Idempotent per
        (proposal_id, operation_id): a replay returns the stored receipt.
        """
        for label, value in (("operation", operation_id), ("idempotency", idempotency_key)):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"invalid Code Mode {label} binding")
        if operation_id is None or idempotency_key is None:
            raise ValueError("Code Mode execution requires operation_id + idempotency_key")
        proposal = self._get_proposal(owner, proposal_id)
        self._binding(owner, proposal["workspace"], proposal["run_id"],
                      proposal["work_item_id"], proposal["agent_id"], active=False)
        if source is not None:
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            if digest != proposal["source_sha256"]:
                raise PermissionError("execution source does not match admitted proposal")
        else:
            source = self._proposal_source(owner, proposal)
        from .composition import build_fenced_tool_map
        tools = build_fenced_tool_map(tools or {})
        intent = hashlib.sha256(json.dumps({"proposal_id": proposal_id,
            "source_sha256": proposal["source_sha256"], "engine": proposal["engine"],
            "limits": self.limits.as_dict(), "tools": sorted(tools),
            "run_id": proposal["run_id"], "work_item_id": proposal["work_item_id"],
            "agent_id": proposal["agent_id"]}, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        engine = proposal.get("engine") or self.engine
        execution_id = "exec-" + hashlib.sha256(
            (owner + "\0" + operation_id).encode()).hexdigest()[:32]
        with self._db() as db:
            # Namespace transaction lock is also cross-process on PostgreSQL.
            # Claim and RUNNING reservation commit BEFORE starting the guest.
            db.execute("BEGIN IMMEDIATE")
            binding = db.execute("SELECT * FROM code_mode_execution_bindings "
                "WHERE owner=? AND (operation_id=? OR request_key=?)",
                (owner, operation_id, idempotency_key)).fetchone()
            if binding is not None and (binding["operation_id"] != operation_id
                    or binding["proposal_id"] != proposal_id
                    or binding["request_key"] != idempotency_key
                    or binding["intent_sha256"] != intent):
                raise PermissionError("Code Mode operation/request key conflicts with immutable intent")
            replay = db.execute(
                "SELECT * FROM code_mode_executions WHERE proposal_id=? AND owner=? "
                "AND operation_id=?", (proposal_id, owner, operation_id)).fetchone()
            if replay is not None:
                item = dict(replay)
                if item["state"] == "SUCCEEDED":
                    return self._receipt(item, db=db)
                if item["state"] in ("FAILED", "CANCELLED"):
                    raise CodeModeCancelled(item["error"] or item["state"]) \
                        if item["state"] == "CANCELLED" else CodeModeBudgetExceeded(item["error"] or "failed")
                return {**self._receipt(item, db=db), "state": "UNCERTAIN",
                        "requires_reconciliation": True, "automatic_retry": False}
            if binding is not None:
                raise CodeModeUnavailable("execution claim has no outcome; reconcile without rerunning")
            fresh = db.execute("SELECT state FROM code_mode_proposals WHERE owner=? AND proposal_id=?",
                               (owner, proposal_id)).fetchone()
            if fresh is None or fresh["state"] != "PROPOSED" or self._cancel_flag(proposal_id).is_set():
                raise CodeModeUnavailable("proposal already started or cancelled; reconcile existing execution")
            self._binding(owner, proposal["workspace"], proposal["run_id"],
                          proposal["work_item_id"], proposal["agent_id"])
            from sentra_runtime.effect_boundary import current_effect_context
            context = current_effect_context.get()
            if (context is None or context.receipt.owner != owner or context.receipt.run_id != proposal["run_id"]
                    or context.request.operation_id != operation_id
                    or context.request.idempotency_key != idempotency_key
                    or context.request.work_item_id != proposal["work_item_id"]
                    or context.request.principal_id != proposal["agent_id"]
                    or context.request.capability_id != "code:execute"):
                raise PermissionError("guest execution requires its already admitted central code:execute context")
            context.checkpoint()
            db.execute("INSERT INTO code_mode_execution_bindings VALUES(?,?,?,?,?,NULL)",
                (owner, operation_id, proposal_id, idempotency_key, intent))
            db.execute("INSERT INTO code_mode_executions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (execution_id, proposal_id, owner, operation_id, "RUNNING", engine,
                 None, None, 0, 0, None, time.time(), time.time()))
            db.execute("UPDATE code_mode_proposals SET state='RUNNING',updated=? "
                "WHERE owner=? AND proposal_id=?", (time.time(), owner, proposal_id))
        try:
            result, usage = await self._run_bounded(
                owner, proposal, source, tools, operation_id, idempotency_key)
        except (CodeModeUncertain, asyncio.CancelledError) as exc:
            self._cancel_flag(proposal_id).set()
            self._record_execution(owner, proposal, operation_id, "UNCERTAIN",
                                   execution_id=execution_id, engine=engine,
                                   error="worker/effect completion requires reconciliation")
            self._mark_proposal(owner, proposal_id, "UNCERTAIN", "NO_AUTOMATIC_RETRY")
            raise CodeModeUncertain("started execution requires reconciliation; never rerun") from exc
        except CodeModeCancelled as exc:
            self._record_execution(owner, proposal, operation_id, "CANCELLED",
                                   execution_id=execution_id, engine=engine,
                                   error="execution cancellation confirmed")
            self._mark_proposal(owner, proposal_id, "CANCELLED", "EXECUTION_CANCELLED")
            raise CodeModeCancelled("execution cancellation confirmed") from exc
        except Exception as exc:
            self._cancel_flag(proposal_id).set()
            self._record_execution(owner, proposal, operation_id, "FAILED",
                                   execution_id=execution_id, engine=engine,
                                   error=type(exc).__name__)
            self._mark_proposal(owner, proposal_id, "FAILED", type(exc).__name__)
            raise
        try:
            return self._finish_execution(owner, proposal, operation_id, execution_id,
                                          engine, result, usage)
        except Exception as exc:
            # The guest already ran; even a DB acknowledgement failure cannot
            # authorize another run. Reservation stays durable and immutable.
            raise CodeModeUncertain("result commit not acknowledged; reconcile without rerunning") from exc

    async def dispatch(self, *, owner, workspace, run_id, work_item_id, agent_id,
                       source, operation_id, idempotency_key,
                       tools=None, engine: str | None = None) -> dict[str, Any]:
        """Central-composition entry-point: propose + execute in one call."""
        from .composition import build_fenced_tool_map
        tools = build_fenced_tool_map(tools or {})
        selected = engine or self.engine
        if selected not in _ENGINES or not all(isinstance(v, str) and v for v in (operation_id, idempotency_key)):
            raise ValueError("engine and stable operation/request key required")
        if not isinstance(source, str) or not 1 <= len(source.encode()) <= self.limits.max_source_bytes:
            raise ValueError("source outside bounds")
        root = str(Path(workspace).resolve(strict=True))
        self._binding(owner, root, run_id, work_item_id, agent_id, active=False)
        digest = hashlib.sha256(source.encode()).hexdigest()
        intent = hashlib.sha256(json.dumps({"workspace": root, "run_id": run_id,
            "work_item_id": work_item_id, "agent_id": agent_id, "source_sha256": digest,
            "engine": selected, "limits": self.limits.as_dict(), "tools": sorted(tools)},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            binding = db.execute("SELECT * FROM code_mode_dispatch_bindings WHERE owner=? "
                "AND (operation_id=? OR request_key=?)", (owner, operation_id, idempotency_key)).fetchone()
            if binding is not None:
                if (binding["operation_id"], binding["request_key"], binding["intent_sha256"]) != (operation_id, idempotency_key, intent):
                    raise PermissionError("dispatch key conflicts with immutable intent")
                proposal_id = binding["proposal_id"]
            else:
                self._binding(owner, root, run_id, work_item_id, agent_id)
                proposal_id, now = "code-" + secrets.token_hex(16), time.time()
                db.execute("INSERT INTO code_mode_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (proposal_id, owner, root, run_id, work_item_id, agent_id, digest,
                     len(source.encode()), selected, "PROPOSED", "ADMITTED_INERT_EXECUTION_PENDING", now, now))
                db.execute("INSERT INTO code_mode_dispatch_bindings VALUES(?,?,?,?,?)",
                    (owner, operation_id, idempotency_key, intent, proposal_id))
        try:
            return await self.execute(owner=owner, proposal_id=proposal_id,
                                      operation_id=operation_id,
                                      idempotency_key=idempotency_key, source=source,
                                      tools=tools)
        except Exception as exc:
            return {"proposal_id": proposal_id, "ok": False,
                    "state": "UNCERTAIN" if isinstance(exc, CodeModeUncertain) else "FAILED",
                    "automatic_retry": False, "error_type": type(exc).__name__}

    # -- internals ------------------------------------------------------
    def _proposal_source(self, owner, proposal) -> str:
        # Source bytes are content-addressed at propose() time; the host keeps
        # no separate copy. The central composer must resupply the exact bytes
        # (digest-checked). This avoids a second source-of-truth store.
        raise PermissionError(
            "resupply the exact admitted source bytes (sha256 %s) for execution"
            % proposal["source_sha256"])

    async def _run_bounded(self, owner, proposal, source, tools,
                           operation_id, idempotency_key):
        flag = self._cancel_flag(proposal["proposal_id"])
        stop = threading.Event()
        def durable_cancel_watch():
            # A cancel request may arrive in another host process. This watcher
            # only reads the existing scoped proposal and sets the shared flag.
            while not stop.wait(0.05):
                try:
                    current = self._get_proposal(owner, proposal["proposal_id"])
                    if current["reason"] == "CANCEL_REQUESTED" or current["state"] == "CANCELLED":
                        flag.set(); return
                except Exception:
                    # Lost authority also stops further guest tool admissions.
                    flag.set(); return
        watcher = threading.Thread(target=durable_cancel_watch, name="sentra-code-cancel", daemon=True)
        watcher.start()
        try:
            return await self._run_engine(owner, proposal, source, tools, operation_id, idempotency_key)
        finally:
            stop.set()

    async def _run_engine(self, owner, proposal, source, tools,
                          operation_id, idempotency_key):
        from sentra_runtime.effect_boundary import current_effect_context
        context = current_effect_context.get()
        if context is None:
            raise PermissionError("central guest effect context unavailable")
        flag = self._cancel_flag(proposal["proposal_id"])
        if flag.is_set():
            raise CodeModeCancelled("cancelled before start")
        wall_s = self.limits.wall_milliseconds / 1000.0
        host = _FencedToolBridge(
            control=self.control, owner=owner,
            run_id=proposal["run_id"], work_item_id=proposal["work_item_id"],
            agent_id=proposal["agent_id"], handlers=dict(tools),
            base_operation_id=operation_id, base_idempotency=idempotency_key,
            cancel_flag=flag, limits=self.limits, parent_context=context)
        engine = proposal.get("engine") or self.engine
        loop = asyncio.get_running_loop()
        if engine == "quickjs-wasm":
            from .artifact_config import load_artifact
            from .quickjs_runtime import QuickJSWasmRunner
            artifact = self.artifact
            if artifact is None:
                # Optional stays unavailable-if-unconfigured (explicit), and
                # distribution MUST ship the real guest (see guest/build.sh).
                artifact = load_artifact()
            runner = QuickJSWasmRunner(artifact, self.limits, cancel_event=flag)
            if flag.is_set():
                runner.cancel()

            def invoke():
                # ABI v1 guest; inner tool calls run their own fenced
                # operations on a dedicated loop via asyncio.run().
                return runner.run(source, bridge=host)
            try:
                return await asyncio.wait_for(context.run_blocking(invoke), timeout=wall_s + 0.5)
            except asyncio.TimeoutError as exc:
                flag.set()
                runner.cancel()
                raise CodeModeUncertain("guest runner termination unconfirmed") from exc
            except asyncio.CancelledError:
                flag.set()
                runner.cancel()
                raise
        from .bounded_js import BoundedJSRunner
        runner = BoundedJSRunner(
            fuel=self.limits.fuel, memory_bytes=self.limits.memory_bytes,
            max_tool_calls=self.limits.max_tool_calls,
            max_arg_bytes=self.limits.max_arg_bytes,
            max_result_bytes=self.limits.max_result_bytes,
            call_tool=host.call_sync, cancel_event=flag)

        def invoke_bounded():
            worker_state: dict[str, Any] = {}

            def target():
                try:
                    worker_state["pair"] = runner.run(source)
                except BaseException as exc:  # noqa: BLE001 - receipt must capture
                    worker_state["error"] = exc

            thread = threading.Thread(target=target, daemon=True)
            started = time.monotonic()
            thread.start()
            while thread.is_alive():
                if flag.is_set():
                    thread.join(timeout=0.25)
                    if thread.is_alive():
                        while thread.is_alive():
                            thread.join(timeout=0.05)
                        raise CodeModeUncertain("interim termination delayed; reconcile outcome")
                    raise CodeModeCancelled("cancelled during execution")
                if time.monotonic() - started > wall_s:
                    flag.set()
                    thread.join(timeout=0.25)
                    if thread.is_alive():
                        while thread.is_alive():
                            thread.join(timeout=0.05)
                        raise CodeModeUncertain("interim termination delayed; reconcile outcome")
                    raise CodeModeBudgetExceeded("wall time exceeded")
                time.sleep(0.005)
            thread.join(timeout=1)
            if "error" in worker_state:
                raise worker_state["error"]
            return worker_state["pair"]

        try:
            pair = await asyncio.wait_for(context.run_blocking(invoke_bounded),
                                          timeout=wall_s + 1.0)
        except asyncio.TimeoutError as exc:
            flag.set()
            raise CodeModeUncertain("interim runner termination unconfirmed") from exc
        except asyncio.CancelledError:
            flag.set()
            raise
        return pair[0], pair[1]

    def _record_execution(self, owner, proposal, operation_id, state, *,
                          execution_id=None, engine=None, error=None,
                          result_sha=None, result_bytes=None, tool_calls=0,
                          fuel_used=0):
        now = time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if execution_id is None:
                row = db.execute(
                    "SELECT execution_id FROM code_mode_executions WHERE proposal_id=? "
                    "AND owner=? AND operation_id=?",
                    (proposal["proposal_id"], owner, operation_id)).fetchone()
                execution_id = row["execution_id"] if row else "exec-" + secrets.token_hex(12)
            db.execute("INSERT INTO code_mode_executions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(execution_id) DO UPDATE SET state=excluded.state,"
                       "result_sha256=excluded.result_sha256,result_bytes=excluded.result_bytes,"
                       "tool_calls=excluded.tool_calls,fuel_used=excluded.fuel_used,"
                       "error=excluded.error,updated=excluded.updated",
                       (execution_id, proposal["proposal_id"], owner, operation_id, state,
                        engine or proposal.get("engine") or self.engine,
                        result_sha, result_bytes, tool_calls, fuel_used, error, now, now))

    def _finish_execution(self, owner, proposal, operation_id, execution_id,
                          engine, result, usage):
        raw = json.dumps(result, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
        if len(raw) > self.limits.max_result_bytes:
            raise CodeModeBudgetExceeded("result exceeds max_result_bytes")
        digest = hashlib.sha256(raw).hexdigest()
        from sentra_core.conversations import _encode
        proof = usage.get("execution_proof") or {}
        verified = engine == "quickjs-wasm" and self._runtime_proof(proof)
        if engine == "quickjs-wasm" and not verified:
            raise CodeModeUnavailable("QuickJS execution lacks bounded runtime completion proof")
        receipt = {"proposal_id": proposal["proposal_id"], "ok": True, "engine": engine,
            "state": "SUCCEEDED", "a08_satisfied": verified, "execution_verified": verified,
            "result": result, "result_sha256": digest, "result_bytes": len(raw),
            "tool_calls": usage.get("tool_calls", 0), "fuel_used": usage.get("fuel_used", 0),
            "wasm_fuel_used": usage.get("wasm_fuel_used"),
            "cpu_milliseconds": usage.get("cpu_milliseconds"),
            "execution_proof": proof, "tool_operations": usage.get("tool_operations", []),
            "grants_created": False, "operation_id": operation_id}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM code_mode_executions WHERE execution_id=? AND owner=?",
                             (execution_id, owner)).fetchone()
            if row is None or row["state"] != "RUNNING":
                raise CodeModeUnavailable("execution outcome cannot replace a terminal receipt")
            binding = db.execute("SELECT * FROM code_mode_execution_bindings WHERE owner=? "
                "AND operation_id=? AND proposal_id=?", (owner, operation_id, proposal["proposal_id"])).fetchone()
            if binding is None or binding["protected_result"] is not None:
                raise CodeModeUnavailable("execution claim missing or result already committed")
            protected = _encode({"owner": owner, "proposal_id": proposal["proposal_id"],
                "operation_id": operation_id, "execution_id": execution_id,
                "request_key": binding["request_key"], "intent_sha256": binding["intent_sha256"],
                "result": result, "result_sha256": digest, "receipt": receipt})
            db.execute("UPDATE code_mode_execution_bindings SET protected_result=? "
                       "WHERE owner=? AND operation_id=? AND proposal_id=?",
                       (protected, owner, operation_id, proposal["proposal_id"]))
            db.execute("UPDATE code_mode_executions SET state='SUCCEEDED',result_sha256=?,"
                       "result_bytes=?,tool_calls=?,fuel_used=?,updated=? WHERE execution_id=? AND owner=?",
                       (digest, len(raw), usage.get("tool_calls", 0), usage.get("fuel_used", 0),
                        time.time(), execution_id, owner))
            db.execute("UPDATE code_mode_proposals SET state='SUCCEEDED',reason='EXECUTION_SUCCEEDED',updated=? "
                       "WHERE owner=? AND proposal_id=? AND state='RUNNING'",
                       (time.time(), owner, proposal["proposal_id"]))
        return receipt

    def _protected_receipt(self, item, *, db=None):
        from sentra_core.conversations import _decode
        if db is None:
            with self._db() as connection:
                return self._protected_receipt(item, db=connection)
        row = db.execute("SELECT * FROM code_mode_execution_bindings WHERE owner=? AND operation_id=? AND proposal_id=?",
            (item["owner"], item["operation_id"], item["proposal_id"])).fetchone()
        if row is None or not row["protected_result"]:
            raise CodeModeUnavailable("legacy result unavailable; reconcile without rerunning")
        value = _decode(row["protected_result"])
        if not isinstance(value, dict) or any(value.get(k) != item[k] for k in ("owner", "operation_id", "proposal_id")):
            raise PermissionError("protected result scope differs from execution")
        for name in ("request_key", "intent_sha256"):
            if name in value and value[name] != row[name]:
                raise PermissionError("protected result intent differs from claim")
        if "execution_id" in value and value["execution_id"] != item["execution_id"]:
            raise PermissionError("protected result execution differs from claim")
        raw = json.dumps(value["result"], ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        if (hashlib.sha256(raw).hexdigest() != item["result_sha256"] or len(raw) != item["result_bytes"]
                or value.get("result_sha256") != item["result_sha256"]):
            raise PermissionError("protected result digest differs from execution")
        receipt = value.get("receipt")
        if receipt is not None:
            if (not isinstance(receipt, dict) or receipt.get("state") != "SUCCEEDED"
                    or receipt.get("engine") != item["engine"] or receipt.get("ok") is not True
                    or any(receipt.get(k) != item[k] for k in
                           ("proposal_id", "operation_id", "result_sha256", "result_bytes", "tool_calls", "fuel_used"))
                    or receipt.get("result") != value["result"]):
                raise PermissionError("protected receipt differs from execution")
        return value

    def _receipt(self, item, *, db=None) -> dict[str, Any]:
        result = None
        if item["state"] == "SUCCEEDED":
            value = self._protected_receipt(item, db=db)
            if value.get("receipt") is not None:
                return value["receipt"]
            result = value["result"]
        return {"proposal_id": item["proposal_id"], "ok": item["state"] == "SUCCEEDED",
                "engine": item["engine"], "state": item["state"],
                "a08_satisfied": self._a08_execution(item, db=db), "result": result,
                "result_sha256": item["result_sha256"], "result_bytes": item["result_bytes"],
                "tool_calls": item["tool_calls"], "fuel_used": item["fuel_used"],
                "operation_id": item["operation_id"], "grants_created": False}

    @staticmethod
    def _runtime_proof(proof):
        return (isinstance(proof, dict) and proof.get("runtime") == "wasmtime" and proof.get("abi") == 1
            and proof.get("wasi_imports") is False
            and all(proof.get(k) is True for k in ("guest_completed", "fuel_enforced", "memory_enforced", "cpu_enforced", "epoch_enforced"))
            and all(isinstance(proof.get(k), str) and len(proof[k]) == 64 and
                    all(c in "0123456789abcdef" for c in proof[k]) for k in ("wasm_sha256", "sbom_sha256")))

    def _a08_execution(self, item, *, db=None):
        if item.get("engine") != "quickjs-wasm" or item.get("state") != "SUCCEEDED":
            return False
        try:
            value = self._protected_receipt(item, db=db)
            receipt = value.get("receipt") or {}
            return receipt.get("a08_satisfied") is True and self._runtime_proof(receipt.get("execution_proof"))
        except Exception:
            # Historical digests cannot attest isolation or actual execution.
            return False

    def _mark_proposal(self, owner, proposal_id, state, reason):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE code_mode_proposals SET state=?,reason=?,updated=? "
                       "WHERE proposal_id=? AND owner=? AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED')",
                       (state, reason, time.time(), proposal_id, owner))


class _FencedToolBridge:
    """Synchronous sandbox bridge; every call takes the central durable gate.

    Handlers are host-selected implementations keyed by allowlisted name. The
    bridge builds one OperationRequest per call and executes it through
    CentralInteropAdapter so the central authority decides, fences and
    receipts the effect. JS names/args can never mint a grant.
    """

    def __init__(self, *, control, owner, run_id, work_item_id, agent_id,
                 handlers, base_operation_id, base_idempotency, cancel_flag, limits=None, parent_context=None):
        from sentra_runtime.contracts import Capability, Machine
        self.control = control
        self.owner = owner
        self.run_id = run_id
        self.work_item_id = work_item_id
        self.agent_id = agent_id
        self.handlers = handlers
        self.base_operation_id = base_operation_id
        self.base_idempotency = base_idempotency
        self.cancel_flag = cancel_flag
        self.calls = 0
        self.operations = []
        self.limits = limits or ResourceLimits()
        self.parent_context = parent_context
        item = control.work_item_info(work_item_id, owner)
        machine_id = (item.get("metadata") or {}).get("machine_id")
        if handlers and (not isinstance(machine_id, str) or not machine_id):
            raise CodeModeUnavailable("inner tools require the trusted WorkItem machine binding")
        self._machine = Machine(machine_id or "code-mode-unbound-pure-guest",
                                "code-mode", owner,
                                tuple(Capability("code-tool:" + name, "Code Mode composed tool: " + name)
                                      for name in handlers))

    def call_sync(self, name, args):
        if self.parent_context is not None:
            self.parent_context.checkpoint()
        if self.cancel_flag.is_set():
            raise CodeModeCancelled("cancelled during tool call")
        if not isinstance(name, str) or name not in self.handlers:
            raise PermissionError("tool is not allowlisted for this execution: " + str(name)[:80])
        handler = self.handlers[name]
        if not callable(handler):
            raise ValueError("host tool handler required")
        raw = json.dumps(args, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        if self.calls >= self.limits.max_tool_calls or len(raw) > self.limits.max_arg_bytes:
            raise CodeModeBudgetExceeded("inner tool outbox bound exceeded")
        self.calls += 1
        # Each inner call is its own durable operation under the same WorkItem.
        from sentra_interop.central import CentralInteropAdapter
        from sentra_runtime.contracts import OperationRequest
        operation_id = f"{self.base_operation_id}:tool:{self.calls}"
        idempotency = f"{self.base_idempotency}:tool:{self.calls}"
        gate = CentralInteropAdapter(
            control=self.control, run_id=self.run_id, owner=self.owner,
            machine=self._machine).protocol_gate(
                capabilities=frozenset({"code-tool:" + name}))
        request = OperationRequest(operation_id, self.agent_id,
                                    self._machine.machine_id, "code-tool:" + name,
                                    self.work_item_id, idempotency,
                                    {"tool": name, "args_sha256": hashlib.sha256(
                                        json.dumps(args, sort_keys=True, ensure_ascii=False,
                                                   separators=(",", ":")).encode()).hexdigest()})

        async def run_fenced():
            decision = await gate.decision(request)
            if not decision.allowed:
                raise PermissionError("Code Mode tool grant denied: " + decision.reason[:160])

            async def effect():
                if self.parent_context is not None:
                    self.parent_context.checkpoint()
                gate.physical_context(request).checkpoint()
                if not (await gate.decision(request)).allowed:
                    raise PermissionError("tool grant revoked before effect")
                if self.cancel_flag.is_set():
                    raise CodeModeCancelled("cancelled during tool effect")
                outcome = handler(args)
                if asyncio.iscoroutine(outcome):
                    outcome = await outcome
                gate.physical_context(request).checkpoint()
                if self.parent_context is not None:
                    self.parent_context.checkpoint()
                return outcome
            outcome = await gate.execute(request, effect, timeout=self.limits.wall_milliseconds / 1000)
            self.operations.append({"operation_id": operation_id, "state": outcome.result.state,
                                    "capability_id": request.capability_id})
            if outcome.result.state == "UNCERTAIN":
                raise CodeModeUncertain("inner tool completion requires central reconciliation")
            if outcome.result.state != "SUCCEEDED":
                raise PermissionError("inner tool not completed by central gate")
            return outcome.payload

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            raise CodeModeUnavailable("sync guest bridge cannot run on the host event loop")
        return asyncio.run(run_fenced())
