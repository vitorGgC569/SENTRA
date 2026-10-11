"""Host-only binding for the existing SENTRA Canvas ConPTY.

This module does not create shells or launch subprocesses. No PID-based
teardown is provided. Read uses the existing protected terminal transcript;
write requires a *current* central physical-effect context and its fence.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sentra_runtime.effect_boundary import CentralEffectContext, current_effect_context


class ExistingConPTYSession:
    def __init__(self, *, control: Any, canvas: Any):
        self.control = control
        self.canvas = canvas
        self._written_operations: set[str] = set()

    def _scope(self, owner: str, *, run_id: str, work_item_id: str,
               principal_id: str, workspace_id: str, terminal_id: str,
               capability: str):
        canvas_ws = self.canvas.store.workspace(workspace_id)
        if canvas_ws["owner"] != owner or self.canvas.store.principal != owner:
            raise PermissionError("Canvas workspace owner differs")
        if canvas_ws["run_id"] != run_id:
            raise PermissionError("Canvas workspace Run changed")
        run = self.control.durable.run_status(run_id, owner, include_details=False)
        if (not run.get("workspace") or
                Path(run["workspace"]).resolve() != Path(canvas_ws["path"]).resolve()):
            raise PermissionError("central and Canvas workspace paths differ")
        work = self.control.work_item_info(work_item_id, owner)
        if work["run_id"] != run_id:
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
             tail_chars: int = 4096) -> dict:
        if (type(cursor) is not int or not 0 <= cursor <= 10**12
                or type(head_chars) is not int or not 0 <= head_chars <= 8192
                or type(tail_chars) is not int or not 0 <= tail_chars <= 8192):
            raise ValueError("bounded ConPTY transcript pagination required")
        self._scope(owner,run_id=run_id,work_item_id=work_item_id,
                    principal_id=principal_id,workspace_id=workspace_id,
                    terminal_id=terminal_id,capability="terminal:read")
        # Same Canvas service and same durable DPAPI/keyring-backed transcript.
        result = self.canvas.terminal_output(workspace_id,terminal_id,cursor)
        text = result.get("text","")
        if (not isinstance(text,str) or len(text)>2_000_000 or
                type(result.get("cursor")) is not int or
                result["cursor"]<cursor or result["cursor"]>10**12):
            raise RuntimeError("ConPTY returned invalid or unbounded transcript")
        middle_omitted=len(text)>(head_chars+tail_chars)
        return {"terminal_id":terminal_id,"cursor":result["cursor"],
                "status":result["status"],
                "exit_code":result.get("exit_code"),
                "head":text[:head_chars],"tail":text[-tail_chars:] if tail_chars else "",
                "truncated":bool(result.get("truncated")) or middle_omitted,
                "total_chunk_chars":len(text),
                "middle_omitted":middle_omitted,
                "persisted":bool(result.get("persisted",False)),
                "live":bool(result.get("recoverable",False)),
                "owned_process_terminated":False}

    def write_stdin(self, owner: str, *, run_id: str, work_item_id: str,
                    principal_id: str, workspace_id: str, terminal_id: str,
                    data: str, operator_approved: bool = False) -> dict:
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
                    terminal_id=terminal_id,capability="terminal:write")
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
        bound = (dict(request.arguments) == binding and
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
        # An exception/timeout here is UNCERTAIN: never retry with new operation.
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
                terminal_id=terminal_id, data=data, operator_approved=True)
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
                if (ws["owner"]!=owner or self.canvas.store.principal!=owner
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
                return self.canvas.create_terminal(workspace_id,name,shell)
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
                        terminal_id=terminal_id,capability="terminal:close")
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
            return {"terminal_id":terminal_id,"closed_owned_handle":True,
                    "global_pid_kill":False}
        return await consent.execute(
            control=self.control,owner=owner,run_id=run_id,
            work_item_id=work_item_id,agent_id=principal_id,
            request_id=request_id,message_id=message_id,
            action_id=action_id,action="terminal.close",body=body,
            operation_id=operation_id,idempotency_key=idempotency_key,
            host_effect=physical_close)
