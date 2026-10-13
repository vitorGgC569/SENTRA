"""Host-only binding for the existing SENTRA Canvas ConPTY.

This module does not create shells or launch subprocesses. No PID-based
teardown is provided. Read uses the existing protected terminal transcript;
write requires a *current* central physical-effect context and its fence.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from sentra_runtime.effect_boundary import CentralEffectContext, current_effect_context
from sentra_runtime.provider_content import text_digest
from sentra_interop.workflow_storage import projection_db


class ExistingConPTYSession:
    def __init__(self, *, control: Any, canvas: Any):
        self.control = control
        self.canvas = canvas
        self._written_operations: set[str] = set()

    def lifecycle(self, request, *, owner, run_id, workspace_id, canvas_principal):
        """Configured MachineHost lifecycle, inside its existing Operation fence."""
        context = current_effect_context.get()
        if not isinstance(context, CentralEffectContext) or context.request != request or context.receipt.owner != owner or context.receipt.run_id != run_id:
            raise PermissionError("terminal lifecycle outside exact central admission")
        arguments = dict(request.arguments)
        if arguments.pop("workspace_id", None) != workspace_id:
            raise PermissionError("terminal lifecycle project changed")
        ledger = PersistentConPTYLedger(self.control)
        if request.capability_id == "terminal:start":
            import re
            name, shell = arguments.get("name"), arguments.get("shell")
            if set(arguments) != {"name", "shell"} or shell not in {"powershell", "cmd"} or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name):
                raise ValueError("configured Windows shell and bounded name required")
            ws = self.canvas.store.workspace(workspace_id)
            item = self.control.work_item_info(request.work_item_id, owner)
            run = self.control.durable.run_status(run_id, owner, include_details=False)
            if ws["owner"] != canvas_principal or self.canvas.store.principal != canvas_principal or ws["run_id"] != run_id or item["run_id"] != run_id or item.get("assignee_agent_id") != request.principal_id or item.get("metadata", {}).get("workspace_id") != workspace_id or Path(ws["path"]).resolve() != Path(run["workspace"]).resolve():
                raise PermissionError("terminal startup scope changed")
            context.checkpoint()
            result = self.canvas.create_terminal(workspace_id, name, shell)
            terminal_id = result.get("terminal_id") or result.get("id")
            if terminal_id is None:
                raise RuntimeError("terminal startup identity unavailable; no replay")
            ledger.register(owner, workspace_id=workspace_id, terminal_id=terminal_id,
                run_id=run_id, work_item_id=request.work_item_id, principal_id=request.principal_id,
                name=name, shell=shell)
            return {"terminal_id": terminal_id, "state": "OPEN", "started_owned_handle": True}
        terminal_id = arguments.get("terminal_id")
        binding = ledger.get(owner, workspace_id, terminal_id)
        if (binding["run_id"], binding["work_item_id"], binding["principal_id"]) != (run_id, request.work_item_id, request.principal_id):
            raise PermissionError("terminal lifecycle binding differs")
        if request.capability_id == "terminal:read":
            context.checkpoint()
            return self.read(owner, run_id=run_id, work_item_id=request.work_item_id,
                principal_id=request.principal_id, workspace_id=workspace_id,
                terminal_id=terminal_id, canvas_principal=canvas_principal,
                cursor=arguments.get("cursor", 0), head_chars=arguments.get("head_chars", 2048),
                tail_chars=arguments.get("tail_chars", 4096))
        if request.capability_id != "terminal:close" or set(arguments) != {"terminal_id"}:
            raise PermissionError("unknown terminal lifecycle operation")
        self._scope(owner, run_id=run_id, work_item_id=request.work_item_id,
            principal_id=request.principal_id, workspace_id=workspace_id,
            terminal_id=terminal_id, capability="terminal:close", canvas_principal=canvas_principal)
        from sentra_canvas.terminal import WindowsPTY
        with self.canvas._lock:
            session = self.canvas._sessions.get(terminal_id)
            pty = getattr(session, "pty", None)
            record = self.canvas.store.resource("terminals", terminal_id, workspace_id)
            if not isinstance(pty, WindowsPTY) or not pty._process or pty._closed or record.get("pid") != pty.pid:
                raise PermissionError("no owned live kernel handle; PID recovery cannot close it")
            context.checkpoint()
            self.canvas.terminal_close(workspace_id, terminal_id)
        ledger.mark_closed(owner, workspace_id, terminal_id)
        return {"terminal_id": terminal_id, "closed_owned_handle": True, "global_pid_kill": False}

    def _scope(self, owner: str, *, run_id: str, work_item_id: str,
               principal_id: str, workspace_id: str, terminal_id: str,
               capability: str, canvas_principal: str | None = None):
        canvas_principal = owner if canvas_principal is None else canvas_principal
        canvas_ws = self.canvas.store.workspace(workspace_id)
        # Canvas store identities are principal-scoped ("vitor"); the CP
        # canonical owner ("canvas:vitor") is checked by the caller.
        if canvas_ws["owner"] != canvas_principal or self.canvas.store.principal != canvas_principal:
            raise PermissionError("Canvas workspace owner differs")
        if canvas_ws["run_id"] != run_id:
            raise PermissionError("Canvas workspace Run changed")
        run = self.control.durable.run_status(run_id, owner, include_details=False)
        if (not run.get("workspace") or
                Path(run["workspace"]).resolve() != Path(canvas_ws["path"]).resolve()):
            raise PermissionError("central and Canvas workspace paths differ")
        work = self.control.work_item_info(work_item_id, owner)
        if (work["run_id"] != run_id or work.get("assignee_agent_id") != principal_id
                or work.get("metadata", {}).get("workspace_id") != workspace_id):
            raise PermissionError("terminal WorkItem belongs to a different Run")
        self.canvas.store.resource("terminals",terminal_id,workspace_id)
        grant = self.control.authorization.require(
            owner,principal_type="agent",principal_id=principal_id,
            capability=capability,scope_type="work_item",scope_id=work_item_id,
            local_owner=False)
        if not grant.get("grant_id"):
            raise PermissionError("explicit terminal capability grant required")
        return canvas_ws

    def read(self, owner: str, *, run_id: str, work_item_id: str,
             principal_id: str, workspace_id: str, terminal_id: str,
             cursor: int = 0, head_chars: int = 2048,
             tail_chars: int = 4096, canvas_principal: str | None = None) -> dict:
        if (type(cursor) is not int or not 0 <= cursor <= 10**12
                or type(head_chars) is not int or not 0 <= head_chars <= 8192
                or type(tail_chars) is not int or not 0 <= tail_chars <= 8192):
            raise ValueError("bounded ConPTY transcript pagination required")
        self._scope(owner,run_id=run_id,work_item_id=work_item_id,
                    principal_id=principal_id,workspace_id=workspace_id,
                    terminal_id=terminal_id,capability="terminal:read",
                    canvas_principal=canvas_principal)
        # Same Canvas service and same durable DPAPI/keyring-backed transcript.
        result = self.canvas.terminal_output(workspace_id,terminal_id,cursor)
        text = result.get("text","")
        if (not isinstance(text,str) or len(text)>2_000_000 or
                type(result.get("cursor")) is not int or
                result["cursor"]<cursor or result["cursor"]>10**12):
            raise RuntimeError("ConPTY returned invalid or unbounded transcript")
        ledger = PersistentConPTYLedger(self.control)
        ledger.note_cursor(owner, workspace_id, terminal_id, result["cursor"])
        handle = getattr(self.canvas, "_sessions", {}).get(terminal_id)
        pty = getattr(handle, "pty", None)
        live = pty is not None and not getattr(pty, "_closed", True) and pty.poll() is None
        middle_omitted=len(text)>(head_chars+tail_chars)
        return {"terminal_id":terminal_id,"cursor":result["cursor"],
                "status":result["status"],
                "exit_code":result.get("exit_code"),
                "head":text[:head_chars],"tail":text[-tail_chars:] if tail_chars else "",
                "truncated":bool(result.get("truncated")) or middle_omitted,
                "total_chunk_chars":len(text),
                "middle_omitted":middle_omitted,
                "persisted":bool(result.get("persisted",False)),
                "live":live,
                "owned_process_terminated":False}

    def write_stdin(self, owner: str, *, run_id: str, work_item_id: str,
                    principal_id: str, workspace_id: str, terminal_id: str,
                    data: str, operator_approved: bool = False,
                    canvas_principal: str | None = None) -> dict:
        """Write once via the existing PTY *only* within a central gated effect.

        Caller obtains its operation/lease/fence from CentralExecutorFactory /
        DurableOperationGate. This method never constructs authority itself.
        """
        if operator_approved is not True:
            raise PermissionError("explicit terminal input approval required")
        if not isinstance(data,str) or not 1 <= len(data) <= 4096:
            raise ValueError("bounded terminal input required")
        self._scope(owner,run_id=run_id,work_item_id=work_item_id,
                    principal_id=principal_id,workspace_id=workspace_id,
                    terminal_id=terminal_id,capability="terminal:write",
                    canvas_principal=canvas_principal)
        context = current_effect_context.get()
        if not isinstance(context, CentralEffectContext):
            raise PermissionError("no current central durable ConPTY effect admission")
        receipt, request=context.receipt,context.request
        binding={"action":"write_stdin","workspace_id":workspace_id,
                 "terminal_id":terminal_id,
                 "payload_sha256":hashlib.sha256(data.encode("utf-8")).hexdigest()}
        from sentra_mcp.services.action_consent_gate import _digest
        # The two-consent API path additionally pins this precise payload to
        # its reviewed SHA. Direct terminal:write providers retain the legacy
        # exact-arguments fence under trusted host-only admission.
        bound = (dict(request.arguments) == {**binding, "payload_sha256": text_digest(data)} and
                 request.capability_id == "terminal:write")
        consented = (request.capability_id == "api:action:terminal.write_stdin"
                     and dict(request.arguments) == {"body_sha256":_digest(binding)})
        if (receipt.owner != owner or receipt.run_id != run_id
                or request.work_item_id != work_item_id
                or request.principal_id != principal_id
                or not (bound or consented)):
            raise PermissionError("ConPTY effect intent does not match durable operation")
        context.checkpoint()
        if receipt.operation_id in self._written_operations:
            raise PermissionError("ConPTY input already attempted; reconcile outcome")
        self._written_operations.add(receipt.operation_id)
        ledger = PersistentConPTYLedger(self.control)
        ledger.claim_input(owner, receipt.operation_id, workspace_id, terminal_id)
        # An exception/timeout here is UNCERTAIN: never retry with new operation.
        context.checkpoint()
        self.canvas.terminal_input(workspace_id,terminal_id,data)
        return {"operation_id":receipt.operation_id,"transport":"existing-conpty",
                "write_attempted":True,"model_acknowledged":False,
                "automatic_retry":False}

    async def execute_consented_stdin(
            self, *, consent: Any, owner: str, run_id: str,
            work_item_id: str, principal_id: str, workspace_id: str,
            terminal_id: str, data: str, request_id: str, message_id: str,
            action_id: str, operation_id: str, idempotency_key: str):
        """Verified owner-auth approvals + exact hash + two distinct grants.

        Requires a previously approved ActionConsentService intent for
        api:action:terminal.write_stdin, plus terminal:write scope. The
        ActionConsentService performs the physical Operation reservation;
        run_blocking keeps that lock and lease if Canvas I/O blocks or times out.
        Replay returns the durable receipt without sending another byte.
        """
        from sentra_mcp.services.action_consent_gate import ActionConsentService
        if not isinstance(consent,ActionConsentService):
            raise TypeError("real consent service required")
        if type(data) is not str or not 1 <= len(data) <= 4096:
            raise ValueError("bounded terminal input required")
        binding={"action":"write_stdin","workspace_id":workspace_id,
                 "terminal_id":terminal_id,
                 "payload_sha256":hashlib.sha256(data.encode("utf-8")).hexdigest()}
        async def physical_write():
            context=current_effect_context.get()
            if not isinstance(context,CentralEffectContext):
                raise PermissionError("durable ConPTY context unavailable")
            # Canvas Store uses a thread-affine SQLite connection. Execute
            # synchronously on the hosting event-loop thread while the
            # CentralEffectContext holds its physical lock and live lease.
            # A blocking call cannot release the lock before it returns.
            return self.write_stdin(
                owner, run_id=run_id, work_item_id=work_item_id,
                principal_id=principal_id, workspace_id=workspace_id,
                terminal_id=terminal_id, data=data, operator_approved=True,
                canvas_principal=self.canvas.store.principal)
        return await consent.execute(
            control=self.control, owner=owner, run_id=run_id,
            work_item_id=work_item_id, agent_id=principal_id,
            request_id=request_id, message_id=message_id,
            action_id=action_id, action="terminal.write_stdin",
            body=binding, operation_id=operation_id,
            idempotency_key=idempotency_key, host_effect=physical_write)

    async def execute_consented_start(
            self, *, consent: Any, owner: str, run_id: str,
            work_item_id: str, principal_id: str, workspace_id: str,
            name: str, shell: str, request_id: str, message_id: str,
            action_id: str, operation_id: str, idempotency_key: str):
        """Start a host-selected local Canvas ConPTY under a physical gate.

        Requires *both* terminal:start and exact reviewed API-action grants.
        No arbitrary command, argv, env, or shell text from the model is used.
        Owner-auth confirmation has already been durably consumed by consent.
        """
        from sentra_mcp.services.action_consent_gate import ActionConsentService
        if not isinstance(consent,ActionConsentService):
            raise TypeError("trusted owner consent service required")
        import re
        if (shell not in {"powershell", "cmd"} or not isinstance(name,str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}",name)):
            raise ValueError("only vetted Windows shells and Canvas-safe names allowed")
        body={"workspace_id":workspace_id,"name":name,"shell":shell}
        async def physical_start():
            context=current_effect_context.get()
            if not isinstance(context,CentralEffectContext):
                raise PermissionError("durable ConPTY startup context unavailable")
            def startup():
                context.checkpoint()
                ws=self.canvas.store.workspace(workspace_id)
                run=self.control.durable.run_status(run_id,owner,include_details=False)
                item=self.control.work_item_info(work_item_id,owner)
                if (ws["owner"]!=self.canvas.store.principal
                        or ws["run_id"]!=run_id or item["run_id"]!=run_id
                        or not run.get("workspace")
                        or Path(run["workspace"]).resolve()!=Path(ws["path"]).resolve()):
                    raise PermissionError("start scope differs from central owner/Run")
                self.control.authorization.require(
                    owner,principal_type="agent",principal_id=principal_id,
                    capability="terminal:start",scope_type="work_item",
                    scope_id=work_item_id,local_owner=False)
                context.checkpoint()
                # Native WindowsPTY process stays owned by Canvas Session handle.
                result = self.canvas.create_terminal(workspace_id,name,shell)
                terminal_id = result.get("terminal_id") or result.get("id")
                if not terminal_id:
                    raise RuntimeError("created terminal has no identity; reconcile without replay")
                PersistentConPTYLedger(self.control).register(owner,
                    workspace_id=workspace_id, terminal_id=terminal_id, run_id=run_id,
                    work_item_id=work_item_id, principal_id=principal_id, name=name, shell=shell)
                return result
            # Native Canvas SQLite is thread-affine; spawning on a worker
            # thread would fail after reserving intent and mark it UNCERTAIN.
            # Run on the host thread inside the still-active physical fence.
            return startup()
        return await consent.execute(
            control=self.control, owner=owner, run_id=run_id,
            work_item_id=work_item_id, agent_id=principal_id,
            request_id=request_id, message_id=message_id,
            action_id=action_id, action="terminal.start", body=body,
            operation_id=operation_id, idempotency_key=idempotency_key,
            host_effect=physical_start)

    async def execute_consented_close(
            self, *, consent: Any, owner: str, run_id: str,
            work_item_id: str, principal_id: str, workspace_id: str,
            terminal_id: str, request_id: str, message_id: str,
            action_id: str, operation_id: str, idempotency_key: str):
        """Garbage-collect only a PTY whose Windows kernel handle Canvas owns.

        Do NOT accept a PID, a persisted terminal row, or an expired lease as
        proof of process ownership. A lost/restarted Canvas has no retained
        live WindowsPTY object and is categorically unable to kill that PID.
        """
        from sentra_mcp.services.action_consent_gate import ActionConsentService
        from sentra_canvas.terminal import WindowsPTY
        if not isinstance(consent,ActionConsentService):
            raise TypeError("authenticated local consent service required")
        body={"workspace_id":workspace_id,"terminal_id":terminal_id}
        async def physical_close():
            context=current_effect_context.get()
            if not isinstance(context,CentralEffectContext):
                raise PermissionError("durable terminal GC context unavailable")
            context.checkpoint()
            self._scope(owner,run_id=run_id,work_item_id=work_item_id,
                        principal_id=principal_id,workspace_id=workspace_id,
                        terminal_id=terminal_id,capability="terminal:close",
                        canvas_principal=self.canvas.store.principal)
            lock=getattr(self.canvas,"_lock",None)
            sessions=getattr(self.canvas,"_sessions",None)
            if lock is None or not isinstance(sessions,dict):
                raise PermissionError("native Canvas PTY ownership unavailable")
            with lock:
                session=sessions.get(terminal_id)
                pty=getattr(session,"pty",None)
                resource=self.canvas.store.resource("terminals",terminal_id,workspace_id)
                if (not isinstance(pty,WindowsPTY)
                        or not pty._process or pty._closed
                        or type(pty.pid) is not int or pty.pid <= 0
                        or resource.get("pid")!=pty.pid):
                    raise PermissionError("no owned live kernel process handle")
                context.checkpoint()
                # Canvas closes this exact retained instance, not a PID lookup.
                self.canvas.terminal_close(workspace_id,terminal_id)
            PersistentConPTYLedger(self.control).mark_closed(owner, workspace_id, terminal_id)
            return {"terminal_id":terminal_id,"closed_owned_handle":True,
                    "global_pid_kill":False}
        return await consent.execute(
            control=self.control,owner=owner,run_id=run_id,
            work_item_id=work_item_id,agent_id=principal_id,
            request_id=request_id,message_id=message_id,
            action_id=action_id,action="terminal.close",body=body,
            operation_id=operation_id,idempotency_key=idempotency_key,
            host_effect=physical_close)


class PersistentConPTYLedger:
    """Durable projection of terminal session bindings and transcript cursors.

    The live WindowsPTY handle is owned by the Canvas session and never
    survives a restart; this ledger therefore records bindings, last-read
    cursors and close state so a resumed conversation can list sessions,
    re-read persisted transcripts and report ``recoverable`` honestly.
    It never claims a PID, a persisted row or an expired lease as proof of
    a live process. Recovery of output uses ``ExistingConPTYSession.read``,
    which falls back to the protected Canvas transcript when detached.
    """

    def __init__(self, control: Any, *, clock=time.time):
        self.control = control
        self.clock = clock
        self.store = control.store
        with projection_db(None, store=self.store) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS conpty_session_ledger(
                owner TEXT NOT NULL, workspace_id TEXT NOT NULL,
                terminal_id TEXT NOT NULL, run_id TEXT NOT NULL,
                work_item_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                name TEXT NOT NULL, shell TEXT NOT NULL,
                last_cursor INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'OPEN',
                created REAL NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(owner, workspace_id, terminal_id))""")

    def claim_input(self, owner, operation_id, workspace_id, terminal_id):
        from sentra_interop.workflow_storage import projection_db
        with projection_db(None, control=self.control) as db:
            db.execute("CREATE TABLE IF NOT EXISTS conpty_input_attempts(owner TEXT NOT NULL,operation_id TEXT NOT NULL,workspace_id TEXT NOT NULL,terminal_id TEXT NOT NULL,PRIMARY KEY(owner,operation_id))")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM conpty_input_attempts WHERE owner=? AND operation_id=?", (owner, operation_id)).fetchone():
                raise PermissionError("terminal input already attempted; no replay")
            db.execute("INSERT INTO conpty_input_attempts VALUES(?,?,?,?)", (owner, operation_id, workspace_id, terminal_id))

    def register(self, owner: str, *, workspace_id: str, terminal_id: str,
                 run_id: str, work_item_id: str, principal_id: str,
                 name: str, shell: str) -> dict:
        """Record a terminal started under central admission.

        Called by the host after ``execute_consented_start`` succeeds; it
        performs no effect itself.
        """
        if not all(isinstance(value, str) and value for value in (
                owner, workspace_id, terminal_id, run_id, work_item_id,
                principal_id, name)) or shell not in {"powershell", "cmd", "sentra-cli"}:
            raise ValueError("bounded terminal session binding required")
        if len(name) > 48:
            raise ValueError("terminal name exceeds bound")
        now = self.clock()
        with projection_db(None, store=self.store) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM conpty_session_ledger WHERE owner=? AND workspace_id=? AND terminal_id=?",
                (owner, workspace_id, terminal_id)).fetchone()
            if old:
                if tuple(old[key] for key in ("run_id", "work_item_id", "principal_id", "name", "shell")) != (run_id, work_item_id, principal_id, name, shell) or old["state"] != "OPEN":
                    raise PermissionError("terminal identity is immutable or closed")
            else:
                db.execute("INSERT INTO conpty_session_ledger VALUES(?,?,?,?,?,?,?,?,0,'OPEN',?,?)",
                    (owner, workspace_id, terminal_id, run_id, work_item_id, principal_id, name, shell, now, now))
        return self.get(owner, workspace_id, terminal_id)

    def note_cursor(self, owner: str, workspace_id: str, terminal_id: str,
                    cursor: int) -> None:
        if type(cursor) is not int or not 0 <= cursor <= 10**12:
            raise ValueError("bounded transcript cursor required")
        with projection_db(None, store=self.store) as db:
            updated = db.execute("UPDATE conpty_session_ledger SET last_cursor=CASE WHEN last_cursor<? THEN ? ELSE last_cursor END,updated=? "
                                 "WHERE owner=? AND workspace_id=? AND terminal_id=?",
                                 (cursor, cursor, self.clock(), owner, workspace_id, terminal_id)).rowcount
            if updated != 1:
                raise FileNotFoundError("terminal session not registered")

    def mark_closed(self, owner: str, workspace_id: str, terminal_id: str) -> None:
        with projection_db(None, store=self.store) as db:
            updated = db.execute("UPDATE conpty_session_ledger SET state='CLOSED',updated=? "
                                 "WHERE owner=? AND workspace_id=? AND terminal_id=?",
                                 (self.clock(), owner, workspace_id, terminal_id)).rowcount
            if updated != 1:
                raise FileNotFoundError("terminal session not registered")

    def get(self, owner: str, workspace_id: str, terminal_id: str) -> dict:
        with projection_db(None, store=self.store) as db:
            row = db.execute("SELECT * FROM conpty_session_ledger WHERE owner=? "
                             "AND workspace_id=? AND terminal_id=?",
                             (owner, workspace_id, terminal_id)).fetchone()
        if row is None:
            raise FileNotFoundError("terminal session not registered")
        return dict(row)

    def sessions(self, owner: str, workspace_id: str,
                 limit: int = 100) -> list[dict]:
        """List registered sessions with live/persisted status projection.

        ``live`` is True only when the current Canvas process holds the
        session handle; after a restart every entry honestly reports
        ``live=False`` with the persisted transcript still readable.
        """
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("session page limit must be 1..500")
        with projection_db(None, store=self.store) as db:
            rows = db.execute("SELECT * FROM conpty_session_ledger WHERE owner=? "
                              "AND workspace_id=? ORDER BY updated DESC LIMIT ?",
                              (owner, workspace_id, limit)).fetchall()
        return [{"terminal_id": row["terminal_id"], "name": row["name"],
                 "shell": row["shell"], "run_id": row["run_id"],
                 "work_item_id": row["work_item_id"],
                 "principal_id": row["principal_id"],
                 "last_cursor": row["last_cursor"], "state": row["state"],
                 "live": False, "transcript_persisted": True,
                 "reattach_claims_live_handle": False} for row in rows]

    def gc_plan(self, owner: str, workspace_id: str, *,
                idle_before: float, limit: int = 100) -> dict:
        """Produce a no-kill GC plan for idle sessions, by handle only.

        A candidate is an OPEN session whose ledger is idle since
        ``idle_before``. The plan never terminates anything itself: the
        host must prove live-handle ownership (retained WindowsPTY object
        with matching PID, as in ``execute_consented_close``) before
        closing. An expired lease, a persisted row or an OS PID alone is
        not proof, so ``may_close_process`` is always False here.
        """
        import math
        if type(idle_before) not in (int, float) or not math.isfinite(idle_before):
            raise ValueError("finite idle cutoff required")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("GC planning limit must be 1..500")
        with projection_db(None, store=self.store) as db:
            rows = db.execute("SELECT * FROM conpty_session_ledger WHERE owner=? "
                              "AND workspace_id=? AND state='OPEN' AND updated<=? "
                              "ORDER BY updated LIMIT ?",
                              (owner, workspace_id, idle_before, limit)).fetchall()
        candidates = [{"terminal_id": row["terminal_id"], "name": row["name"],
                       "run_id": row["run_id"],
                       "work_item_id": row["work_item_id"],
                       "last_cursor": row["last_cursor"],
                       "action": "host_ownership_review_only",
                       "may_close_process": False} for row in rows]
        return {"owner": owner, "workspace_id": workspace_id,
                "candidates": candidates, "destructive_actions_executed": 0,
                "gc_supported_for_unknown_handle": False}


class TerminalWriteGate:
    """Fenced dispatch gate for ConPTY stdin (no direct facade writes).

    The shell facade (or any host caller) builds the exact effect intent
    with :meth:`request` — a pure builder resolving run/work-item/
    principal from the server-side session ledger. The host root admits
    that intent as a distinct central ``terminal:write`` operation, then
    calls :meth:`execute` with the admitted request **inside** the
    current central admission. Without a matching
    :class:`CentralEffectContext`, execution fails closed; the facade
    never calls ``write_stdin`` directly.
    """

    def __init__(self, *, control: Any, canvas: Any):
        self.control, self.canvas = control, canvas
        self.session = ExistingConPTYSession(control=control, canvas=canvas)
        self.ledger = PersistentConPTYLedger(control)

    def request(self, owner: str, *, workspace_id: str, terminal_id: str,
                data: str, principal: str) -> dict:
        """Build the exact fenced ``terminal:write`` intent (no effect)."""
        if not isinstance(data, str) or not 1 <= len(data) <= 4096:
            raise ValueError("bounded terminal input required")
        if not isinstance(terminal_id, str) or not terminal_id:
            raise ValueError("terminal identity required")
        try:
            binding = self.ledger.get(owner, workspace_id, terminal_id)
        except FileNotFoundError:
            raise ValueError("terminal session not registered for this project")
        if binding["state"] != "OPEN":
            raise ValueError("terminal session is not open")
        return {
            "capability_id": "terminal:write",
            "arguments": {
                "action": "write_stdin", "workspace_id": workspace_id,
                "terminal_id": terminal_id,
                "payload_sha256": text_digest(data)},
            "scope": {"owner": owner, "run_id": binding["run_id"],
                      "work_item_id": binding["work_item_id"],
                      "principal_id": binding["principal_id"]},
            "principal": principal,
            "admit_via": "central operation journal",
            "execute_via": "TerminalWriteGate.execute inside admission",
            "effects_started": False}

    def execute(self, *, request: Any, data: str, owner: str, run_id: str,
                work_item_id: str, principal_id: str, workspace_id: str,
                terminal_id: str, principal: str) -> dict:
        """Perform one fenced write inside the current central admission."""
        context = current_effect_context.get()
        if not isinstance(context, CentralEffectContext):
            raise PermissionError("no current central durable ConPTY effect admission")
        if getattr(request, "capability_id", None) != "terminal:write":
            raise PermissionError("admitted request is not a terminal write")
        expected = {"action": "write_stdin", "workspace_id": workspace_id,
                    "terminal_id": terminal_id,
                    "payload_sha256": text_digest(data)}
        if dict(getattr(request, "arguments", {}) or {}) != expected:
            raise PermissionError("admitted ConPTY intent does not match payload")
        receipt = context.receipt
        if (receipt.owner != owner or receipt.run_id != run_id
                or context.request != request or request.work_item_id != work_item_id
                or request.principal_id != principal_id):
            raise PermissionError("ConPTY admission does not match durable operation")
        return self.session.write_stdin(
            owner, run_id=run_id, work_item_id=work_item_id,
            principal_id=principal_id, workspace_id=workspace_id,
            terminal_id=terminal_id, data=data, operator_approved=True,
            canvas_principal=principal)
