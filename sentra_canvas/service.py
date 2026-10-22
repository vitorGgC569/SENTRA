"""Application service using native ConPTY and the existing SENTRA CLI."""
from __future__ import annotations
import codecs
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from contextlib import closing
from sentra_mcp.errors import sanitize_error
from pathlib import Path

from .store import Store, Denied, validated_name, MODEL_RE, TRANSCRIPT_LIMIT, new_id
from .terminal import WindowsPTY, TerminalError
from .instance_lock import InstanceLock
from .namespaces import Namespace
from .graph import GraphStore
from .owned_process import TaskProcess
from .adapters import catalog as terminal_catalog,cli_argv,resolve as resolve_adapters

class Session:
    def __init__(self, persist=None, on_persistence_error=None):
        self.lock=threading.RLock()
        self.decoder=codecs.getincrementaldecoder("utf-8")("replace")
        self.base=0
        self.buffer=""
        self.pty=None
        self.persist=persist
        self.persistence_error=None
        self.on_persistence_error=on_persistence_error
        self.exit_input=b"exit\r"

    def append(self,chunk):
        with self.lock:
            text=self.decoder.decode(chunk)
            if self.persist and text and self.persistence_error is None:
                try:
                    self.persist(text)
                except Exception as exc:
                    # Keep draining ConPTY, but never claim this volatile suffix
                    # survived a restart or append it at the wrong durable offset.
                    self.persistence_error=type(exc).__name__
                    if self.on_persistence_error:
                        try:
                            self.on_persistence_error(self.persistence_error)
                        except Exception:
                            # A failed disk must not stop draining the child pipe.
                            pass
            self.buffer+=text
            if len(self.buffer)>TRANSCRIPT_LIMIT:
                removed=len(self.buffer)-TRANSCRIPT_LIMIT
                self.buffer=self.buffer[removed:]
                self.base+=removed

    def output(self,cursor=0):
        with self.lock:
            requested=max(0,int(cursor))
            cursor=min(self.base+len(self.buffer),max(self.base,requested))
            return {"cursor":self.base+len(self.buffer),
                    "text":self.buffer[cursor-self.base:],
                    "truncated":requested<self.base}

class Canvas:
    def __init__(self,root,db_path=None,principal=None,max_terminals=12,*,state_dir=None,
                 max_task_workers=4,max_pending_tasks=128,shell_configuration=None):
        if type(max_task_workers) is not int or not 1<=max_task_workers<=16:
            raise ValueError("task worker limit must be 1-16")
        if type(max_pending_tasks) is not int or not max_task_workers<=max_pending_tasks<=1024:
            raise ValueError("pending task limit must cover workers and be <=1024")
        root=Path(root).resolve()
        self.project_dir=root
        from .shell_optional import load_shell_configuration
        shell_configuration=load_shell_configuration(shell_configuration, root=root)
        self.state_dir=Path(state_dir).resolve() if state_dir is not None else root/".sentra"/"canvas"
        self.state_dir.mkdir(parents=True,exist_ok=True)
        self.instance_lock=InstanceLock(self.state_dir/"owner.lock")
        self._pty_client=None
        self._durable_inventory=[]
        try:
            projects=self.state_dir/"projects"
            projects.mkdir(exist_ok=True)
            if os.environ.get("SENTRA_PTY_DAEMON") == "1":
                from .pty_client import PtyDaemonClient
                self._pty_client=PtyDaemonClient.connect_or_start(self.state_dir/"pty-host")
                self._durable_inventory=self._pty_client.call("inventory", {"include_history": True})
            self.store=Store(db_path or self.state_dir/"canvas.sqlite3",
                             projects,principal=principal,telemetry_root=self.state_dir.parent,
                             live_terminal_ids={r["terminal_id"] for r in self._durable_inventory
                                                if r.get("process_live", r["exit_code"] is None)})
        except BaseException:
            self.instance_lock.close()
            raise
        self.graph=GraphStore(self.state_dir/"graph.sqlite3")
        self.graph.recover_handoffs([ws["id"] for ws in self.store.workspaces()])
        self._lock=threading.RLock()
        self._shutdown_lock=threading.Lock()
        self._sessions={}
        self._pty_histories={}
        if self._pty_client is not None:
            from .pty_client import DaemonPTY
            for row in self._durable_inventory:
                try:
                    restored = self.store.resource("terminals",row["terminal_id"],row["workspace_id"])
                except (Denied,KeyError,ValueError,FileNotFoundError):
                    continue
                if not row.get('process_live', row['exit_code'] is None):
                    self._pty_histories[row['terminal_id']] = row
                    continue
                session=Session()
                session.exit_input = b"/exit\r" if restored.get('shell') == "sentra-cli" else b"\x03" if restored.get('shell') == "codex" else b"exit\r"
                session.pty=DaemonPTY(self._pty_client,row["workspace_id"],row["terminal_id"],pid=row["pid"],runtime_id=row["runtime_id"])
                self._sessions[row["terminal_id"]]=session
        self._jobs={}
        self._task_threads={}
        self._task_processes={}
        self._job_tasks={}
        self._closing=False
        self._closed=False
        self._agent_tokens={}
        self._agent_port=None
        self._agent_runtime_id=None
        self._durable_agent_bindings=set()
        from .agent_bindings import AgentBindings
        self._agent_bindings=AgentBindings(self.state_dir,self.store.principal)
        if self._pty_client is not None and self._pty_client.capabilities.get('agent_binding_proof'):
            for row in self._durable_inventory:
                if row['terminal_id'] not in self._sessions:
                    continue
                terminal=self.store.resource('terminals',row['terminal_id'],row['workspace_id'])
                if terminal.get('shell')=='sentra-cli':
                    token=self._agent_bindings.recover(row)
                    if token:
                        self._agent_tokens[token]=(row['workspace_id'],row['terminal_id'])
                        self._durable_agent_bindings.add(row['terminal_id'])
        self.max_terminals=max_terminals
        self.max_task_workers=max_task_workers
        self.max_pending_tasks=max_pending_tasks
        self._task_runtime=None
        self._control=None
        self._machine_host=None
        self._collab_authority=None
        self._collab_process=None
        self._shell_runtime=None
        self._project_documents=None
        self._project_file_service=None
        self._channels=None
        self._protocol_interactions=None
        self._shell_machines=None
        self._shell_turn_permissions=None
        self._shell_product_requests=None
        # Host configuration is injected at startup, never selected by renderer.
        self._shell_configuration=shell_configuration
        self._plan_history=None
        self._network_settings=None
        self._task_runtime_error=None
        self._dispatch_stop=threading.Event()
        self._dispatch_wake=threading.Event()
        self._dispatch_thread=threading.Thread(target=self._dispatch_loop,daemon=True,name="sentra-canvas-queue")
        self._dispatch_thread.start()
        self._compose_web_relay_startup()

    def _compose_web_relay_startup(self):
        config = self._shell_configuration.get("web_relay")
        if not isinstance(config, dict) or config.get("enabled") is not True:
            return
        from native_bridge.host_attestors import create_host_attestors
        control = self._shell_service()
        account_attestor, assistant_observer = create_host_attestors(control, owner="canvas:" + self.store.principal)
        if not callable(account_attestor) or not callable(assistant_observer):
            raise RuntimeError("fail-closed: host attestors cannot be constructed")
        self.attach_shell_relay_observers(account_attestor=account_attestor,
                                          assistant_observer=assistant_observer)

    def _runtime(self):
        with self._lock:
            if self._task_runtime is None:
                from sentra_runtime.canvas_authority import CanvasAuthorityRuntime
                self._task_runtime=CanvasAuthorityRuntime(self.state_dir.parent,self.store,
                    control=self._control_service(),owner="canvas:"+self.store.principal)
            return self._task_runtime

    def _control_service(self):
        """Choose the configured authority once; hosted failures never fall back locally."""
        with self._lock:
            if self._control is None:
                from sentra_mcp.services.control_plane import ControlPlaneService
                config=self._shell_configuration.get("control_plane",{})
                if not isinstance(config,dict) or set(config)-{"backend","dsn","tenant_id","principal_id"}:
                    raise ValueError("invalid host Control Plane configuration")
                control=ControlPlaneService.from_store(self.state_dir.parent,**config)
                try:
                    if hasattr(control.store,"assert_principal"):
                        control.store.assert_principal("canvas:"+self.store.principal)
                except BaseException:
                    control.context.close()
                    control.durable.close()
                    raise
                self._control=control
            return self._control

    def _shell_service(self):
        """Compose the conversation surface with the existing runtime authority."""
        with self._lock:
            host = self._machine_service()
            if self._shell_runtime is None:
                from .shell_runtime import CanvasShellRuntime
                self._shell_runtime = CanvasShellRuntime(self, host.control, owner=host.owner)
                host.control.attach_shell_runtime(self._shell_runtime)
                self._shell_runtime.recover_completed()
            return host.control

    def _document_service(self):
        with self._lock:
            control = self._shell_service()
            if self._project_documents is None:
                from .project_documents import ProjectDocuments
                owner = self._runtime().owner
                self._project_documents = ProjectDocuments(control, owner=owner,
                    resolve_space=lambda sid, pid: control.shell.get_space(sid, owner, project_id=pid),
                    resolve_run=lambda pid: control.shell.resolve_run(pid, owner))
            return self._project_documents

    def attach_shell_relay_observers(self, *, account_attestor, assistant_observer):
        """Trusted host composition only; callback authority never comes from HTTP."""
        with self._lock:
            self._shell_service()
            self._shell_runtime.web.attach_observers(account_attestor=account_attestor,
                assistant_observer=assistant_observer)
            self._shell_runtime.recover_completed()

    def _channel_service(self):
        with self._lock:
            if self._channels is None:
                from sentra_interop.channels import ChannelService
                host = self._machine_service()
                self._channels = ChannelService(host.control, owner=host.owner)
            return self._channels

    def channel_receive(self, connector_id, raw_body, headers):
        """Authenticated provider ingress records an inbox; it cannot dispatch work."""
        from sentra_interop.provider_store import identifier
        identifier(connector_id)
        if not isinstance(raw_body, bytes) or len(raw_body) > 1048576:
            raise ValueError("channel webhook body exceeds limit")
        return self._channel_service().receive(connector_id=connector_id,
            raw_body=raw_body, headers=dict(headers))

    def channel_challenge(self, connector_id, query):
        from sentra_interop.provider_store import identifier
        identifier(connector_id)
        return self._channel_service().challenge(connector_id, query)

    def interop_receive(self, machine_id, raw_body, headers):
        """Pinned A2A ingress persists evidence; execution remains an admitted operation."""
        from sentra_interop.provider_store import identifier
        identifier(machine_id)
        if not isinstance(raw_body, bytes) or len(raw_body) > 1048576:
            raise ValueError("interop webhook body exceeds limit")
        host = self._machine_service()
        entry = next((e for e in host.configurations.entries() if e["machine_id"] == machine_id), None)
        if entry is None or entry["configuration"].get("kind") != "a2a":
            raise Denied("configured A2A callback machine required")
        project_id = entry["configuration"]["workspace_id"]
        self.store.workspace(project_id)
        # MachineHost resolves only restored/configured factories and the provider
        # validates callback secret, peer/task/context and replay binding.
        value = host.receive_interop_callback(machine_id, raw_body, dict(headers))
        if (value.get("project_id") or value.get("workspace_id")) != project_id:
            raise Denied("callback project differs from its configured machine")
        return value

    def _channel_configure(self, project_id, payload):
        control = self._shell_service()
        owner = self._runtime().owner
        configuration = payload.get("configuration")
        if not isinstance(configuration, dict) or configuration.get("project_id") != project_id:
            raise Denied("channel configuration belongs to another project")
        agent_id = configuration.get("agent_id")
        self.store.resource("agents", agent_id, project_id)
        run = control.durable.run_status(self._runtime().run(project_id)["run_id"], owner)
        if not any(a["agent_id"] == agent_id for a in run.get("agents", [])):
            raise Denied("channel agent is outside the project Run")
        routes = configuration.get("routes")
        if not isinstance(routes, list) or not 1 <= len(routes) <= 100:
            raise ValueError("bounded channel routes required")
        # The configured routes must reference persisted conversations and Spaces.
        from contextlib import closing
        for item in routes:
            if not isinstance(item, dict):
                raise ValueError("channel route must be an object")
            with closing(control.store.connect("shell")) as db:
                conversation = control.shell._entity(db, owner, project_id, "conversation",
                    item.get("conversation_id"), space_id=item.get("space_id"))
            control.shell.get_space(conversation["space_id"], owner, project_id=project_id)
        return self._channel_service().configure(connector_id=payload.get("connector_id"),
            configuration=configuration, expected_revision=payload.get("expected_revision", 0))

    def shell_delivery_inspect(self, project_id, space_id, conversation_id, operation_id):
        """Read-only inspection of a known, conversation-bound provider operation.

        Does not admit, call, retry, reconcile or mark an operation successful.
        """
        from contextlib import closing
        from sentra_core.conversations import _decode
        self.store.workspace(project_id)
        control = self._shell_service()
        owner = self._runtime().owner
        with closing(control.store.connect("shell")) as db:
            control.shell._entity(db, owner, project_id, "conversation",
                                  conversation_id, space_id=space_id)
            row = db.execute(
                "SELECT protected_input,receipt_id,state FROM canvas_shell_queue "
                "WHERE owner=? AND operation_id=?",
                (owner, operation_id)).fetchone()
        if row is None:
            raise Denied("delivery record not found in this conversation")
        original = _decode(row["protected_input"])["message"]
        if (original.get("project_id") != project_id or
                original.get("space_id") != space_id or
                original.get("conversation_id") != conversation_id or
                original.get("operation_id") != operation_id):
            raise Denied("delivery record belongs to another conversation")
        operation = control.durable.operation_status(operation_id, owner)
        if operation.get("run_id") != original.get("run_id"):
            raise Denied("delivery and operation run differ")
        raw_error = operation.get("error") or {}
        error_code = raw_error.get("code", "") if isinstance(raw_error, dict) else ""
        # Only display known diagnostic codes. Raw provider errors can contain
        # credentials, prompts or private machine identifiers.
        allowed_codes = {"shell_provider_unconfirmed", "shell_model_interrupted",
                         "shell_relay_unconfirmed", "shell_worker_failed"}
        reason_code = error_code if error_code in allowed_codes else (
            "not_yet_attested" if operation["state"] == "UNCERTAIN" else "")
        receipt = (operation.get("result") or {}).get("receipt_id") or row["receipt_id"]
        problem = None
        if operation["state"] == "UNCERTAIN":
            try:
                problem = self._shell_runtime._delivery_problem(original)
            except (OSError, RuntimeError, ValueError, LookupError):
                problem = None  # Failure to inspect the journal never retries the provider.
        return {"status": operation["state"], "operation_id": operation_id,
                "receipt_confirmed": operation["state"] == "SUCCEEDED" and bool(receipt),
                "reason_code": reason_code, "automatic_retry": False,
                "receipt_id": receipt if operation["state"] == "SUCCEEDED" else None,
                "message": ("Resultado definitivo verificado no registro do SENTRA."
                            if operation["state"] == "SUCCEEDED" and receipt else
                            (problem or "Ainda não existe resposta definitiva verificada.") +
                            " A operação não foi reenviada."
                            if operation["state"] == "UNCERTAIN" else
                            "A operação ainda está em " + str(operation["state"]) + ".")}

    def shell_stream_head(self, project_id, space_id, conversation_id):
        """Scoped durable snapshot; a read never repeats a provider request."""
        from contextlib import closing
        self.store.workspace(project_id)
        control = self._shell_service()
        with closing(control.store.connect("shell")) as db:
            control.shell._entity(db, self._runtime().owner, project_id, "conversation",
                                  conversation_id, space_id=space_id)
        return self._shell_runtime.stream.head(project_id, conversation_id) or {"status": "idle", "sequence": 0}

    def shell_stream_content(self, project_id, space_id, conversation_id, reference_id, *, offset=0, limit=65536):
        """Page an immutable protected preview under current live resource scope."""
        from contextlib import closing
        self.store.workspace(project_id)
        control = self._shell_service()
        owner = self._runtime().owner
        control.shell._project(owner, project_id)
        with closing(control.store.connect("shell")) as db:
            db.execute("BEGIN")
            space = control.shell._entity(db, owner, project_id, "space", space_id)
            conversation = control.shell._entity(db, owner, project_id, "conversation", conversation_id, space_id=space_id)
            if (space.get("project_id") != project_id or space.get("space_id") != space_id
                    or conversation.get("project_id") != project_id or conversation.get("conversation_id") != conversation_id):
                raise Denied("conversation identity differs from the authorized stream scope")
            return self._shell_runtime.stream.content(project_id, space_id, conversation_id, reference_id, offset=offset, limit=limit, _db=db)

    def shell_live_preview(self, project_id, space_id, conversation_id):
        """Authenticated, conversation-scoped, nonauthoritative model projection."""
        from contextlib import closing
        self.store.workspace(project_id)
        control = self._shell_service()
        try:
            with closing(control.store.connect("shell")) as db:
                control.shell._entity(db, self._runtime().owner, project_id, "conversation",
                                      conversation_id, space_id=space_id)
        except FileNotFoundError as exc:
            raise Denied("conversation outside the authorized project") from exc
        from .shell_web_preview import web_preview
        observed = web_preview(self._shell_runtime, project_id, conversation_id)
        native = self._shell_runtime.live.view(project_id, conversation_id)
        if native['status'] == 'idle' and observed['status'] == 'idle':
            try:
                draft = self._shell_runtime.conversations.response_draft(conversation_id)
            except PermissionError:
                draft = None
            if draft:
                from sentra_core.model_prose import prose_prefix
                from .shell_stream import content_window
                text = prose_prefix(draft['content'])
                content = content_window(text)
                return {"status": "interrupted", "content": content, "truncated": content != text,
                        "content_offset": len(text)-len(content),
                        "activity": "Entrega incerta. Não reenvie.", "partial": True,
                        "authoritative": False, "closes_trio": False, "persisted": True}
        return observed if observed.get('content') or (native['status'] == 'idle' and observed['status'] != 'idle') else native

    def shell_bridge(self, payload, *, input_client_id=''):
        """Authenticated owner entry point; renderer inputs never select authority."""
        if not isinstance(payload, dict):
            raise ValueError("shell envelope must be an object")
        action = payload.get("action")
        project_id = payload.get("project_id", payload.get("ws"))
        if not isinstance(action, str) or not isinstance(project_id, str):
            raise ValueError("shell action and project_id required")
        if payload.get("ws") is not None and payload["ws"] != project_id:
            raise ValueError("conflicting project identifiers")
        forbidden = {"owner", "principal", "principal_id", "principal_type", "grant",
            "grant_id", "permissions", "permission", "workspace_root", "root", "run_id", "operation_id"}
        if forbidden.intersection(payload):
            raise Denied("shell authority is derived from the authenticated server")
        self.store.workspace(project_id)
        control = self._shell_service()
        request_key = payload.get("request_key")
        params = {k: v for k, v in payload.items() if k not in {"action", "project_id", "ws", "request_key"}}
        if action == "workspace_inventory":
            from .workspace_contract import inventory
            return {"ok": True, "value": inventory(self, project_id, params)}
        if action in {'workspace_presentation_get','workspace_presentation_save'}:
            from .workspace_presentation import dispatch_presentation
            return {'ok':True,'value':dispatch_presentation(self,project_id,action,params)}
        if action in {'workspace_file_get','workspace_file_draft_save'}:
            from .workspace_file_editor import dispatch_editor
            return {'ok':True,'value':dispatch_editor(self,project_id,action,params)}
        if action == "workspace_request_status":
            from .workspace_requests import inspect_request
            return {"ok": True, "value": inspect_request(self, project_id, params, exact_dot=bool(input_client_id))}
        if action=='conversation_permission_status':
            from .conversation_permission_status import inspect_decision
            return {'ok':True,'value':inspect_decision(self,project_id,params)}
        if action == "attachment_upload_status" and request_key is not None:
            # This read uses the original mutation key as a reconciliation selector.
            params["request_key"] = request_key
        if action == "conversation_request_status":
            # This is an owner-scoped inspection of the original durable key.
            # Never dispatch conversation_create or silently replay a prompt.
            if set(params) != {"space_id", "dot_id"} or not request_key:
                raise ValueError("exact original conversation request scope required")
            result = control.shell.inspect_conversation_request(
                self._runtime().owner, project_id=project_id,
                request_key=request_key, space_id=params["space_id"],
                dot_id=params["dot_id"])
            return {"ok": True, "value": result}
        if action == "message_request_status":
            if set(params) != {"space_id", "conversation_id"} or not request_key:
                raise ValueError("exact original message request scope required")
            result = control.shell.inspect_message_request(
                self._runtime().owner, project_id=project_id, request_key=request_key,
                space_id=params["space_id"], conversation_id=params["conversation_id"])
            return {"ok": True, "value": result}
        if action == "channel_configure":
            value = self._channel_configure(project_id, params)
            return {"ok": True, "value": value, "request_key": request_key}
        if action in {'coordinator_approval_list', 'coordinator_approval_reply'}:
            from .shell_approval_inbox import dispatch_coordinator_approval
            value = dispatch_coordinator_approval(self, project_id, action, params, request_key)
            return {'ok': True, 'value': value, 'request_key': request_key}
        if action in {"interaction_list", "interaction_reply"}:
            with self._lock:
                if self._protocol_interactions is None:
                    from sentra_interop.interactions import ProtocolInteractionService
                    self._protocol_interactions = ProtocolInteractionService(control, owner=self._runtime().owner)
            if action == "interaction_list":
                value = self._protocol_interactions.pending(workspace_id=project_id, limit=params.get("limit", 100))
            else:
                value = self._protocol_interactions.reply(workspace_id=project_id,
                    interaction_id=params["interaction_id"], answer=params["answer"], request_key=request_key)
            return {"ok": True, "value": value, "request_key": request_key}
        from .project_review import PROJECT_REVIEW_ACTIONS, ProjectReviewService
        if action=='dot_worktree_review':
            from .task_workspace import review
            return {'ok':True,'value':review(self,project_id,params),'request_key':request_key}
        if action in PROJECT_REVIEW_ACTIONS:
            if params.get('dot_id') or params.get('conversation_id'):
                from .task_workspace import file_service
                service,fields,identity=file_service(self,project_id,params)
                return {'ok':True,'value':{**service.dispatch(action,fields,project_id=project_id),**identity},'request_key':request_key}
            if payload.get("space_id"):
                control.shell.get_space(payload["space_id"], self._runtime().owner, project_id=project_id)
            with self._lock:
                if self._project_file_service is None:
                    self._project_file_service = ProjectReviewService(lambda pid: self.store.workspace(pid)["path"])
            value = self._project_file_service.dispatch(action, params, project_id=project_id)
            return {"ok": True, "value": value, "request_key": request_key}
        if "path" in payload:
            raise Denied("filesystem paths are allowed only by scoped project preview actions")
        from .shell_federation import NETWORK_ACTIONS, NETWORK_READS, dispatch_network
        if action in NETWORK_ACTIONS:
            value = dispatch_network(self, project_id, action, params,
                None if action in NETWORK_READS else request_key)
            return {"ok": True, "value": value, "request_key": request_key}
        from .shell_capabilities import CAPABILITY_ACTIONS, CAPABILITY_READS, dispatch_capability
        if action in CAPABILITY_ACTIONS:
            value = dispatch_capability(self, project_id, action, params,
                None if action in CAPABILITY_READS else request_key)
            return {"ok": True, "value": value, "request_key": request_key}
        from sentra_mcp.services.pacto_product import PACTO_ACTIONS, PACTO_READS, dispatch_pacto_product
        if action in PACTO_ACTIONS:
            if action in PACTO_READS:
                value = dispatch_pacto_product(self, project_id, action, params)
            else:
                with self._lock:
                    if self._shell_product_requests is None:
                        from .shell_requests import ShellHostRequests
                        self._shell_product_requests = ShellHostRequests(control, self._runtime().owner)
                value = self._shell_product_requests.invoke(project_id, action, params, request_key,
                    lambda: dispatch_pacto_product(self, project_id, action, params))
            return {"ok": True, "value": value, "request_key": request_key}
        from .shell_permissions import TURN_PERMISSION_ACTIONS, ShellTurnPermissions
        from .shell_goals import GOAL_ACTIONS, dispatch_goal
        if action in GOAL_ACTIONS:
            value = dispatch_goal(self, project_id, action, params, request_key)
            return {"ok": True, "value": value, "request_key": request_key}
        from .shell_dot_canvas import DOT_CANVAS_ACTIONS, dispatch_dot_canvas
        from .shell_dot_vm import DOT_VM_ACTIONS, DotVmServices
        from .shell_dot_lifecycle import DOT_LIFECYCLE_ACTIONS, DotLifecycleServices
        if action in DOT_VM_ACTIONS:
            with self._lock:
                if getattr(self, '_shell_dot_vm', None) is None:
                    self._shell_dot_vm = DotVmServices(self)
            # Only this bearer-authenticated native owner entry point installs
            # the reviewed storage scope. ShellActor dispatch has no such scope.
            if action == 'dot_vm_execute' and isinstance(params.get('arguments'), dict) and params['arguments'].get('action') == 'storage.enroll':
                from sentra_executors.virtualbox_storage_enrollment import dispatch_owner_storage_enrollment
                value = dispatch_owner_storage_enrollment(self._shell_dot_vm, project_id, params, request_key)
            else:
                value = self._shell_dot_vm.dispatch(project_id, action, params, request_key,input_client_id=input_client_id)
            return {'ok': True, 'value': value, 'request_key': request_key}
        if action in DOT_LIFECYCLE_ACTIONS:
            with self._lock:
                if getattr(self, '_shell_dot_lifecycle', None) is None:
                    self._shell_dot_lifecycle = DotLifecycleServices(self)
            value = self._shell_dot_lifecycle.dispatch(project_id, action, params, request_key)
            return {'ok': True, 'value': value, 'request_key': request_key}
        from .shell_dot_computer import DOT_COMPUTER_ACTIONS, DotComputerServices
        if action in DOT_COMPUTER_ACTIONS:
            with self._lock:
                if getattr(self, '_shell_dot_computer', None) is None:
                    self._shell_dot_computer = DotComputerServices(self)
            value = self._shell_dot_computer.dispatch(project_id, action, params, request_key)
            return {'ok': True, 'value': value, 'request_key': request_key}
        from .shell_access import ACCESS_ACTIONS, dispatch_access
        if action in ACCESS_ACTIONS:
            return {"ok": True, "value": dispatch_access(self, project_id, action, params, request_key)}
        if action in DOT_CANVAS_ACTIONS:
            value = dispatch_dot_canvas(self, project_id, action, params, request_key)
            return {"ok": True, "value": value, "request_key": request_key}
        if action in TURN_PERMISSION_ACTIONS:
            with self._lock:
                if self._shell_turn_permissions is None:
                    self._shell_turn_permissions = ShellTurnPermissions(self)
            return {"ok": True, "value": self._shell_turn_permissions.dispatch(project_id, action, params, request_key),
                "request_key": request_key}
        from .code_machine import CODE_ACTIONS
        if action in CODE_ACTIONS:
            from .shell_code import dispatch_code
            return {"ok": True, "value": dispatch_code(self,project_id,action,params,request_key),
                "request_key":request_key}
        from .shell_machines import MACHINE_ACTIONS, ShellMachineServices
        if action in MACHINE_ACTIONS:
            with self._lock:
                if self._shell_machines is None:
                    self._shell_machines = ShellMachineServices(self)
            value = self._shell_machines.dispatch(project_id, action, params, request_key)
            return {"ok": True, "value": value, "request_key": request_key}
        from .project_documents import DOCUMENT_ACTIONS
        if action in DOCUMENT_ACTIONS:
            params["request_key"] = request_key
            value = self._document_service().dispatch(action, params, project_id=project_id,
                principal_id=self.store.principal, principal_type="user")
            return {"ok": True, "value": value, "request_key": request_key}
        result = control.shell_dispatch(self._runtime().owner, project_id=project_id,
            action=action, payload=params, request_key=request_key)
        if action == "home" and result.get("ok") is True:
            # Optional reads share this owner and project. Their failure must not
            # discard the already confirmed Home or pretend an effect was sent.
            from .shell_federation import home_network
            from .shell_capabilities import home_capabilities
            for field, read_surface in (("network", home_network),
                                       ("optional_surfaces", home_capabilities)):
                try:
                    result["value"][field] = read_surface(self, project_id)
                except (OSError, ValueError, RuntimeError, PermissionError, LookupError):
                    result["value"][field] = {
                        "status": "unavailable", "project_id": project_id,
                        "query_failed": True, "effect_uncertain": False,
                        "reason_code": field + "_query_failed",
                    }
        if action == 'message_list' and result.get('ok') is True:
            from .shell_generated_media import ShellGeneratedMedia
            result['value']['items'] = ShellGeneratedMedia(self._shell_runtime).messages(project_id,
                params['conversation_id'], result['value']['items'])
            from .task_presentation import decorate_messages
            result['value']['items']=decorate_messages(control,self._runtime().owner,project_id,
                params['space_id'],params['conversation_id'],result['value']['items'])
        if action == 'conversation_create':
            # An owner-created conversation starts with the visible default:
            # project reads, with approval required before edits or commands.
            # Agent-created child conversations do not enter this owner route.
            from .shell_access import AccessStore, dispatch_access
            conversation = result['value']
            if conversation.get('conversation_id') and not AccessStore(control, self._runtime().owner).profile(conversation['conversation_id']).get('work_item_id'):
                dispatch_access(self, project_id, 'access_set', {'space_id': conversation['space_id'],
                    'conversation_id': conversation['conversation_id'], 'mode': 'ask'},
                    'default-access-' + hashlib.sha256(request_key.encode()).hexdigest(),default_profile=True)
        if action in {"dot_create", "dot_update"} and result.get("ok") is True:
            # The shell picker posts an id it already read from /api/models.
            # Accepting that id does not run a turn and does not prove access.
            from .shell_optional import CATALOG_SELECTABLE_MODELS
            value = result.get("value")
            chosen = value.get("model") if isinstance(value, dict) else None
            if chosen in CATALOG_SELECTABLE_MODELS:
                catalog = self.model_catalog()
                if chosen in catalog["models"]:
                    result = {**result, "value": {**value, "model_selection":
                        self._unverified_model_selection(chosen, catalog["source"])}}
        return result

    def _machine_service(self):
        """Share the existing durable state; the host owns only dispatch machinery."""
        with self._lock:
            if self._machine_host is None:
                from sentra_runtime.machine_host import MachineHost
                runtime = self._runtime()
                self._machine_host = MachineHost(runtime.control, owner=runtime.owner)
                from .code_machine import configure_code_machine
                self._machine_host.attach_runtime_adapters(canvas=self)
                self._machine_host.attach_configuration_handler("code-mode",
                    lambda host, **kwargs: configure_code_machine(host, canvas=self, **kwargs))
                def validate_scope(config):
                    workspace = self.store.workspace(config["workspace_id"])
                    self.store.resource("agents",config["agent_id"],config["workspace_id"])
                    if Path(workspace["path"]).resolve(strict=True) != Path(config["workspace_root"]).resolve(strict=True):
                        raise Denied("persisted machine workspace root changed")
                self._machine_host.restore(validate_scope)
            return self._machine_host

    def center_machines(self, ws):
        self.store.workspace(ws)
        host=self._machine_service()
        return {"machines": host.inventory(ws), "work_items":host.task_catalog(workspace_id=ws),
                "restore_errors":host.restore_errors}

    def center_telemetry(self,ws,config=None):
        self.store.workspace(ws)
        host=self._machine_service()
        return host.configure_telemetry(config) if config is not None else host.telemetry_status()

    def agent_working_context(self,ws,agent_id,*,goal=None,expected_revision=None):
        from .agent_context import AgentWorkingContext
        contexts=AgentWorkingContext(self.store)
        if goal is None:return contexts.get(ws,agent_id)
        return contexts.set(ws,agent_id,goal=goal,expected_revision=expected_revision)

    def center_mcp_http(self,ws,*,action="list",server_id=None,endpoint=None):
        """Catalog UI only: no direct MCP effect/credential exposure.

        The Canvas owner controls enrollment. Tools still need separate live
        WorkItem grants and the durable operation gate; this method never
        calls a server, creates grants or tests ChatGPT account permissions.
        """
        workspace=self.store.workspace(ws)
        owner=self._runtime().owner
        control=self._machine_service().control
        if action=="list":
            return control.mcp_http_list(owner,workspace["path"])
        if action=="register":
            return control.mcp_http_register(owner,workspace["path"],
                server_id,endpoint,approved=True)
        if action=="disable":
            try:
                return control.mcp_http_disable(owner,workspace["path"],server_id,
                    approved=True)
            except FileNotFoundError as exc:
                raise Denied("MCP HTTP endpoint unavailable for this workspace") from exc
        raise ValueError("unsupported owner MCP HTTP catalog action")

    def center_plugin_bundles(self,ws,*,source=None,expected_sha256=None,
                              action="list",package_sha256=None):
        """Owner-scoped MCPB catalog -> centrally registered, inert plugins."""
        workspace=self.store.workspace(ws)
        control=self._machine_service().control
        root=workspace["path"]
        owner=self.store.principal
        if action=="list":
            if source is not None:
                action="stage"  # Existing Canvas client request compatibility.
            else:
                from sentra_mcp.services.mcpb_supervision import MCPBSupervisionService
                return {**control.bundle_list(owner,root),
                    "supervision":MCPBSupervisionService(control).status(owner,root)}
        if action in {"supervision","supervision_sweep"}:
            from sentra_mcp.services.mcpb_supervision import MCPBSupervisionService
            supervision=MCPBSupervisionService(control)
            return supervision.status(owner,root) if action=="supervision" else supervision.sweep(owner,root,
                approved_by_host=lambda: self.store.workspace(ws)["owner"]==self.store.principal)
        if action=="inspect":
            return control.bundle_inspect(owner,root,package_sha256)
        if action=="register":
            return control.bundle_register(owner,root,package_sha256)
        if action=="disable":
            return control.bundle_disable(owner,root,package_sha256)
        if action!="stage":
            raise ValueError("unsupported MCPB catalog action")
        if not isinstance(source,str) or not source.strip() or len(source)>4096:
            raise ValueError("bounded MCPB source path required")
        from pathlib import Path
        root_path=Path(root).resolve(strict=True)
        candidate=Path(source)
        if not candidate.is_absolute():
            candidate=root_path/candidate
        return control.bundle_stage(owner,root_path,candidate,expected_sha256=expected_sha256)

    def center_skill_library(self,ws,*,action="list",parameters=None):
        workspace=self.store.workspace(ws)
        control=self._machine_service().control
        library=control.skill_library
        owner=self._runtime().owner
        root=workspace["path"]
        p=dict(parameters or {})
        if action=="list":return library.list(owner,root)
        if action=="import":return library.import_local(owner,root,**p)
        if action=="git":return library.import_git(owner,root,**p)
        if action=="github":return library.import_github(owner,root,**p)
        if action=="revoke":return library.revoke(owner,root,**p)
        if action=="versions":return library.versions(owner,root,**p)
        if action=="latest":return library.latest(owner,root,**p)
        if action=="review":return library.review(owner,root,**p)
        if action in {"activate","disclose","upgrade","rollback"}:
            work=control.governance.work_item_info(p["work_item_id"],owner)
            if work.get("metadata",{}).get("workspace_id")!=ws:
                raise Denied("skill WorkItem belongs to another Canvas workspace")
            self.store.resource("agents",p["agent_id"],ws)
            if action=="activate":return library.activate(owner,root,**p)
            if action=="upgrade":return library.upgrade_activation(owner,root,**p)
            if action=="rollback":return library.rollback_activation(owner,root,approved=True,**p)
            return library.disclose(owner,root,**p)
        raise ValueError("unsupported skill library action")

    def center_browser_evidence(self,ws,*,configuration=None):
        workspace=self.store.workspace(ws)
        service=self._machine_service().control.browser_evidence
        if configuration is not None:
            if not isinstance(configuration,dict) or set(configuration)!={
                "extension_id","principal","source_sha256","enabled","expected_revision"
            }:
                raise ValueError("exact browser collector configuration required")
            return service.configure(workspace=workspace["path"],**configuration)
        return service.status(workspace["path"])

    def center_mcp_account(self,ws,*,action="status",attempt_id=None,approved=False):
        """Single local owner path to reattach SENTRA MCP in another ChatGPT account.

        No OAuth, browser cookies or Platform credentials are read or modified.
        ChatGPT owns installation/selection/revocation, so Plus remains
        UNKNOWN until an independent account-level attestation exists.
        """
        self.store.workspace(ws)
        from .mcp_account_switch import MCPAccountSwitch
        wizard=MCPAccountSwitch(self.state_dir.parent)
        owner=self._runtime().owner
        if action=="status":return wizard.status(owner)
        if action=="begin":return wizard.begin(owner,approved=approved)
        if action=="mark_steps":return wizard.mark_steps(owner,attempt_id,approved=approved)
        if action=="cancel":return wizard.cancel(owner,attempt_id,approved=approved)
        raise ValueError("unsupported MCP account migration action")

    def center_plugin_proof(self,ws):
        """Operator-only status, with no account or tunnel secrets returned."""
        self.store.workspace(ws)
        from sentra_remote.connector_proof import ConnectorProof
        return {**ConnectorProof(self.state_dir.parent).status(),
                "browser":self.center_browser_evidence(ws)}

    def center_project_review(self,ws,*,path="",action="list",
                              content=None,expected_sha256=None,page=1,dpi=72):
        """Owner-scoped editor; mutations require separate approved HTTP action."""
        from .project_review import list_level,file_preview,git_diff,preview_edit,pdf_text_page,pdf_visual_page
        workspace=self.store.workspace(ws)
        if action=="list":return list_level(workspace["path"],path)
        if action=="preview":return file_preview(workspace["path"],path)
        if action=="diff":return git_diff(workspace["path"],path)
        if action=="pdf_text":return pdf_text_page(workspace["path"],path,page=page)
        if action=="pdf_visual":return pdf_visual_page(workspace["path"],path,page=page,dpi=dpi)
        if action=="preview_edit":
            result=preview_edit(workspace["path"],path,content=content,
                                expected_sha256=expected_sha256)
            if result["changed"]:
                with self._lock:
                    reviews=getattr(self,"_project_edit_reviews",None)
                    if reviews is None:
                        reviews={}
                        self._project_edit_reviews=reviews
                    now=time.monotonic()
                    for token,entry in list(reviews.items()):
                        if entry["expires"]<=now:
                            reviews.pop(token,None)
                    if len(reviews)>=128:
                        raise Denied("too many pending file reviews")
                    ticket=secrets.token_urlsafe(32)
                    reviews[ticket]={"ws":ws,"path":path,
                                     "before":expected_sha256,
                                     "after":result["after_sha256"],
                                     "expires":now+300}
                return {**result,"review_token":ticket,"review_expires_seconds":300}
            return result
        if action=="save":
            raise Denied("use the owner-confirmed reviewed file save")
        if action=="save_reviewed":
            raise Denied("reviewed save must be invoked via the authenticated owner route")
        raise ValueError("unsupported project editor operation")

    def center_project_save_reviewed(self,ws,path,content,expected_sha256,review_token):
        """Consume a single-use server-side review ticket before any file effect."""
        workspace=self.store.workspace(ws)
        if not isinstance(content,str) or not isinstance(review_token,str) or len(review_token)>128:
            raise Denied("valid reviewed edit is required")
        digest=hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self._lock:
            reviews=getattr(self,"_project_edit_reviews",{})
            entry=reviews.get(review_token)
            if (entry is None or entry["expires"]<=time.monotonic() or
                    entry["ws"]!=ws or entry["path"]!=path or
                    entry["before"]!=expected_sha256 or entry["after"]!=digest):
                raise Denied("file review expired or does not match the proposed changes")
            reviews.pop(review_token,None)
        from .project_review import save_edit
        return save_edit(workspace["path"],path,content=content,
                         expected_sha256=expected_sha256,state_root=self.state_dir)

    def center_conversation_search(self,ws,query,*,limit=20):
        """Search only this operator's protected CLI history in this workspace."""
        if not isinstance(query,str) or not query.strip() or len(query)>200:
            raise ValueError("bounded conversation search query required")
        if type(limit) is not int or not 1<=limit<=50:
            raise ValueError("search limit must be 1..50")
        from sentra_core.conversations import ConversationStore
        workspace=self.store.workspace(ws)
        sessions=ConversationStore(self.state_dir.parent,principal=self.store.principal)
        return sessions.search_page(workspace["path"],query,limit=limit,max_scan=2000,budget_seconds=2)

    def center_conversation_export(self,ws,conversation_id):
        """Explicit local-only, bounded Markdown export of an owned conversation."""
        from sentra_core.conversations import ConversationStore
        workspace=self.store.workspace(ws)
        sessions=ConversationStore(self.state_dir.parent,principal=self.store.principal)
        with sessions._connect() as db:
            sessions._owned(db,conversation_id,workspace["path"])
            total=db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?",(conversation_id,)).fetchone()[0]
            if total>1000:
                raise ValueError("conversation exceeds single-export message limit")
        entries=sessions.messages(conversation_id,limit=1000)
        fragments=["# SENTRA conversation","",f"Conversation ID: {conversation_id}",""]
        for msg in entries:
            fragments.extend([f"## {msg['role'].upper()}","",msg["content"],""])
        text="\n".join(fragments)
        if len(text.encode("utf-8"))>2_000_000:
            raise ValueError("conversation exceeds export byte limit")
        return {"filename":"sentra-conversation-"+conversation_id+".md",
                "content":text,"messages":len(entries),"complete":True}

    def center_chat_access(self,ws,conversation_id=None,*,change=None):
        """Local Canvas operator projection; only blocks/filters ChatGPT tool calls.

        This never binds browser request evidence and never grants a capability.
        The central Control Plane owns the persisted policy.
        """
        self.store.workspace(ws)
        registry=self._machine_service().control.chat_access
        principal="local-operator"
        if change is not None:
            if not isinstance(change,dict):raise ValueError("chat policy object required")
            operation=change.get("operation")
            if operation=="strict":
                return registry.set_strict(principal,change.get("enabled"),
                    expected_revision=change.get("expected_revision"))
            if operation=="chat":
                conversation_id=change.get("conversation_id")
                return registry.set_chat(principal,conversation_id,
                    trusted=change.get("trusted"),blocked=change.get("blocked"),
                    expected_revision=change.get("expected_revision"))
            raise ValueError("unsupported chat access policy change")
        result={"strict_policy":registry.strict_status(principal)}
        if conversation_id:
            result["chat"]={**registry.chat_status(principal,conversation_id),
                **registry.conversation_consent_summary(principal,conversation_id)}
        return result

    def center_network(self,ws,configuration=None,*,agent=False):
        with self._lock:
            if self._network_settings is None:
                from .network_settings import WorkspaceNetworkSettings
                self._network_settings=WorkspaceNetworkSettings(self.store)
                self._network_settings.restore()
            network=self._network_settings
        return network.configure(ws,configuration,agent=agent) if configuration is not None else network.status(ws)

    def center_network_pairing(self,ws):
        self.center_network(ws)
        return self._network_settings.pairing_code(ws)

    def _working_context_snapshot(self,ws,agents,origins,state):
        workspace=self.store.workspace(ws);runtime=self._runtime();run=runtime.run(ws)
        assignments=runtime.governance.list_work_items(runtime.owner,run_id=run["run_id"],
            states=["QUEUED","RUNNING","BLOCKED","VALIDATING"],limit=1000)["items"]
        own=[item for item in assignments if item.get("assignee_agent_id") in agents and
            item.get("metadata",{}).get("workspace_id")==ws]
        targets={link["target"] for link in state["links"] if link["source"] in origins}
        # A note wired *into* this agent/terminal is owner-supplied context,
        # not a capability to edit that note or to control its other links.
        incoming_note_ids={link["source"] for link in state["links"]
            if link["target"] in origins}
        incoming_note_ids={node["id"] for node in state["nodes"]
            if node["kind"]=="note" and node["id"] in incoming_note_ids}
        directed=[node for node in state["nodes"]
                  if node["id"] in targets or node["id"] in incoming_note_ids]
        return {"schema_version":1,"workspace":{"id":ws,"name":workspace["name"],"path":workspace["path"]},
            "run":{"run_id":run["run_id"],"state":run["state"]},
            "agents":[{"id":agent,"name":self.store.resource("agents",agent,ws)["name"],
                "role":self.store.resource("agents",agent,ws)["role"],
                "working_context":self.agent_working_context(ws,agent)} for agent in sorted(agents)],
            "work_items":[{key:item.get(key) for key in ("work_item_id","objective","state","required_capabilities","blockers")} for item in own[:32]],
            "skills":[{"work_item_id":item["work_item_id"],
                **self._machine_service().control.skill_library.disclose(runtime.owner,workspace["path"],
                    item["work_item_id"],item["assignee_agent_id"])} for item in own[:32]],
            "connections":[{**{key:node[key] for key in ("id","kind","title","resource_id")},
                "access":"read_only" if node["id"] in incoming_note_ids and node["id"] not in targets
                         else "outgoing"} for node in directed[:64]],
            "notes":[{"id":node["id"],"title":node["title"],"body":str(node.get("body", ""))[:4000]}
                     for node in directed if node["kind"]=="note"][:8],
            "context_creates_permissions":False,"automatic_coordination_available":True}

    def center_web_delivery(self, ws, *, limit=50):
        """Read the owner/run projection of the existing outbox; never resend."""
        from native_bridge.job_store import JobStore
        from native_bridge.web_send import WebSendAuthority
        self.store.workspace(ws)
        runtime = self._runtime()
        run = runtime.run(ws)
        control = self._machine_service().control
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("delivery limit must be 1..100")
        outbox = self.state_dir.parent / "browser" / "relay.sqlite3"
        if not outbox.is_file():
            return {"messages": [], "available": False, "reason": "outbox_not_initialized", "automatic_resend": False}
        jobs = JobStore(outbox)
        try:
            web = WebSendAuthority(control, jobs)
            with control.store.connect("session_checkpoint") as db:
                rows = db.execute("SELECT job_id FROM web_send_intents WHERE owner=? AND run_id=? "
                                  "ORDER BY updated DESC LIMIT ?", (runtime.owner, run["run_id"], limit)).fetchall()
            messages = []
            for row in rows:
                item = web.status(runtime.owner, row["job_id"])
                receipt = (item.get("delivery") or {}).get("receipt") or {}
                messages.append({**item, "request_id": item["job_id"],
                    "message_id": receipt.get("message_id"), "conversation_id": receipt.get("conversation_id")})
            return {"messages": messages, "available": True, "automatic_resend": False}
        finally:
            jobs.close()

    def center_compact_resume(self, ws, *, action, arguments):
        from native_bridge.conversation_continuation import ConversationWebContinuation
        from native_bridge.job_store import JobStore
        self.store.workspace(ws)
        runtime = self._runtime()
        run = runtime.run(ws)
        allowed = ({"chat_id", "work_item_id", "principal_id", "request_key", "summary", "cursor", "target_url"}
                   if action == "prepare" else {"allocation_id", "continuation_id"})
        if action not in {"prepare", "status", "resume"} or not isinstance(arguments, dict) or set(arguments) - allowed:
            raise ValueError("invalid Compact&Resume action or authority fields")
        outbox = self.state_dir.parent / "browser" / "relay.sqlite3"
        outbox.parent.mkdir(parents=True, exist_ok=True)
        jobs = JobStore(outbox)
        try:
            service = ConversationWebContinuation(self._machine_service().control, jobs)
            kwargs = dict(arguments)
            if action == "prepare":
                kwargs["run_id"] = run["run_id"]
            if action != "status":
                kwargs["operator_approved"] = True
            result = getattr(service, action)(runtime.owner, "canvas-workspace:" + ws, **kwargs)
            if result.get("run_id") != run["run_id"]:
                raise Denied("Compact&Resume belongs to another Canvas workspace")
            return result
        finally:
            jobs.close()

    def center_goal_loop(self, ws, *, action="status", objective="", goal_id=None, loop_id=None,
                         max_steps=2, max_cost_usd=0.0, deadline_seconds=120):
        """Owner HTTP projection of the shared durable Goal/Loop authority."""
        from sentra_executors.goal_loop import ConversationGoalLoop
        self.store.workspace(ws)
        runtime = self._runtime()
        run = runtime.run(ws)
        service = ConversationGoalLoop(self._machine_service().control)
        conversation = "canvas-workspace:" + ws
        current = service.status(runtime.owner, conversation)
        if goal_id is not None and current.get("goal_id") != goal_id:
            raise Denied("Goal does not belong to this Canvas conversation")
        if loop_id is not None and (current.get("loop") or {}).get("loop_id") != loop_id:
            raise Denied("Loop does not belong to this Canvas conversation")
        if action == "set":
            self._machine_service().control.ensure_agent(run["run_id"], runtime.owner,
                agent_id="canvas-goal:" + ws, role="coordinator")
            current = service.set(runtime.owner, conversation, run_id=run["run_id"],
                                  objective=objective, operator_approved=True)
        elif action == "start":
            current = service.open(runtime.owner, conversation,
                                   principal_id="canvas-goal:" + ws, max_steps=max_steps,
                                   max_cost_usd=max_cost_usd, deadline_seconds=deadline_seconds,
                                   operator_approved=True)
        elif action == "stop":
            current = service.stop(runtime.owner, conversation, operator_approved=True)
        elif action == "loop-stop":
            current = service.loop_stop(runtime.owner, conversation, operator_approved=True)
        elif action == "loop-status":
            current = service.loop_status(runtime.owner, conversation)
        elif action == "step":
            current = service.advance(runtime.owner, conversation, objective=objective, operator_approved=True)
        elif action != "status":
            raise ValueError("unsupported Goal/Loop action")
        view = service.status(runtime.owner, conversation)
        loop = view.get("loop") or {}
        goal = view.get("goal") or {}
        goals = [] if view.get("state") == "UNSET" else [{
            "goal_id": view.get("goal_id") or goal.get("goal_id"),
            "loop_id": loop.get("loop_id"), "objective": goal.get("objective", objective),
            "state": current.get("state") or view.get("state"),
            "iteration": len(loop.get("steps", [])), "max_steps": loop.get("max_steps"),
            "cost_usd": None, "next_action": "Requires an authorized WorkItem",
            "block_reason": current.get("reason"), "history": loop.get("steps", []),
        }]
        return {"goals": goals, "conversation_id": conversation,
                "automatic_execution": False, "grants_created": False}

    def center_overview(self,ws,*,operation_offset=0,work_item_offset=0):
        """Current owner-scoped central state, with bounded metadata pages."""
        self.store.workspace(ws)
        runtime=self._runtime();host=self._machine_service();run=runtime.run(ws)
        operations=runtime.durable.list_operations(run["run_id"],runtime.owner,limit=50,offset=operation_offset)
        work=host.control.list_work_items(runtime.owner,run_id=run["run_id"],limit=50,offset=work_item_offset)
        visible=[item for item in work["items"] if item.get("metadata",{}).get("workspace_id")==ws]
        return {"run":{key:run[key] for key in ("run_id","state","desired_state","updated_at","last_event_seq")},
            "work_items":{"items":[{key:item.get(key) for key in ("work_item_id","objective","state",
                "assignee_agent_id","required_capabilities","updated_at","blockers")} for item in visible],"page":work["page"]},
            "operations":operations,"machines":host.inventory(ws),"restore_errors":host.restore_errors,
            "cost":host.control.cost_summary(runtime.owner,run_id=run["run_id"]),
            "budget_policies":self.budget_policies(ws)["items"],"telemetry":host.telemetry_status(),
            "consistency":"current-read","provider_registration_proves_execution":False}

    def center_configure_machine(self, ws, agent_id, kind, *, profiles=None, headless=True,
                                 recalculation_backends=None,ocr_backends=None,provider_config=None,definitions=None):
        """Authenticated owner configuration; agent tokens cannot call this method."""
        workspace = self.store.workspace(ws)
        self.store.resource("agents", agent_id, ws)
        host = self._machine_service()
        if kind == 'git-worktrees':
            if not isinstance(provider_config,dict) or set(provider_config)!={'dot_id'}:
                raise ValueError('explicit Dot binding required for Git worktrees')
            return host.configure_worktrees(workspace_id=ws,workspace_root=workspace['path'],
                agent_id=agent_id,dot_id=provider_config['dot_id'])
        if kind == "workspace-files":
            return host.configure_workspace_files(workspace_id=ws,
                workspace_root=workspace["path"], agent_id=agent_id)
        if kind == "terminal":
            # Existing fenced ConPTY terminal machine; not a general host shell.
            return host.configure_terminal(workspace_id=ws,
                workspace_root=workspace["path"], agent_id=agent_id, canvas=self)
        if kind == "documents":
            return host.configure_documents(workspace_id=ws, workspace_root=workspace["path"],
                                            agent_id=agent_id,recalculation_backends=recalculation_backends,
                                            ocr_backends=ocr_backends)
        if kind == "browser":
            return host.configure_browser(workspace_id=ws, workspace_root=workspace["path"],
                agent_id=agent_id, profiles=profiles, headless=headless)
        if kind == "openhands":
            return host.configure_openhands(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,provider_config=provider_config)
        if kind == "workflow":
            return host.configure_workflow(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,definitions=definitions)
        if kind == "code-mode":
            return host.configure_code(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,provider_config=provider_config)
        if kind in {"daytona","guacamole","rustdesk"}:
            return host.configure_session(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,kind=kind,provider_config=provider_config)
        if kind in {"acp","a2a","mcp","channels","acp_registry"}:
            return host.configure_interop(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,kind=kind,provider_config=provider_config)
        if kind in {"windows_uia_semantic","windows_guest_uia","windows_guest_lifecycle",
                    "windows_guest_artifact","windows_hcs_native","gvisor_workload"}:
            return host.configure_executor(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,kind=kind,provider_config=provider_config)
        raise ValueError("unsupported machine kind")

    def center_file_work_items(self, ws, conversation_id):
        """Read-only owner-scoped file WorkItems for one conversation.

        A configured machine does not imply a Grant. Expose allowed
        capabilities only after the same authoritative policy that the machine
        executor checks. No task/grant is created during this read.
        """
        self.store.workspace(ws)
        host = self._machine_service()
        owner = self._runtime().owner
        control = host.control
        try:
            with closing(control.store.connect("shell")) as db:
                conversation = control.shell._entity(db, owner, ws, "conversation", conversation_id)
                dot = control.shell._entity(db, owner, ws, "dot", conversation["dot_id"],
                                            space_id=conversation["space_id"])
        except FileNotFoundError as exc:
            raise Denied("file WorkItems outside the authorized conversation") from exc
        agent_id = dot["agent_id"]
        machines = [machine for machine in host.inventory(ws)
                    if machine["kind"] in {"workspace-files", "terminal"} and
                       machine["agent_id"] == agent_id]
        machine_ids = {machine["machine_id"] for machine in machines}
        machine_kinds = {machine["machine_id"]: machine["kind"] for machine in machines}
        if not machines:
            return {"items": [], "machine_configured": False, "dot": dot.get("name", "Dot")}
        eligible = {item["work_item_id"]: item for item in
                    host.task_catalog(workspace_id=ws, agent_ids={agent_id})}
        run = self._runtime().run(ws)
        records = control.list_work_items(owner, run_id=run["run_id"],
                                          limit=1000)["items"]
        items = []
        for item in records:
            meta = item.get("metadata", {})
            if (meta.get("machine_id") not in machine_ids or
                    meta.get("workspace_id") != ws or
                    meta.get("conversation_id") != conversation_id or
                    meta.get("file_access_owner_approved" if
                             machine_kinds.get(meta.get("machine_id")) == "workspace-files"
                             else "terminal_access_owner_approved") is not True or
                    item.get("assignee_agent_id") != agent_id):
                continue
            allowed = (eligible[item["work_item_id"]]["capabilities"]
                       if item["work_item_id"] in eligible else [])
            items.append({"work_item_id": item["work_item_id"],
                          "machine_id": meta["machine_id"],
                          "kind": machine_kinds.get(meta["machine_id"]),
                          "state": item["state"],
                          "objective": item.get("objective", ""),
                          "requested_capabilities": item.get("required_capabilities", []),
                          "granted_capabilities": allowed,
                          "authorized": bool(allowed) and item["state"] == "RUNNING",
                          "created_at": item.get("created_at")})
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {"items": items, "machine_configured": True,
                "dot": dot.get("name", "Dot")}

    def center_prepare_task(self, ws, machine_id, capabilities, objective, *, conversation_id=None, approve=False):
        """Owner explicitly creates a scoped task/grant for a configured machine."""
        self.store.workspace(ws)
        host = self._machine_service()
        selected = next((m for m in host.inventory(ws) if m["machine_id"] == machine_id), None)
        if (selected is None or not isinstance(capabilities, list) or not capabilities
                or any(not isinstance(c, str) for c in capabilities)
                or not set(capabilities) <= set(selected["capabilities"])
                or not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000):
            raise ValueError("configured machine, explicit capabilities and objective required")
        runtime = self._runtime()
        run = runtime.run(ws)
        control = host.control
        file_scope = {}
        if selected["kind"] in {"workspace-files", "terminal"}:
            if approve is not True:
                raise Denied("explicit owner approval required for scoped machine grants")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise Denied("file access must be explicitly scoped to a shell conversation")
            with closing(control.store.connect("shell")) as db:
                conversation = control.shell._entity(db, runtime.owner, ws, "conversation", conversation_id)
                dot = control.shell._entity(db, runtime.owner, ws, "dot", conversation["dot_id"],
                                            space_id=conversation["space_id"])
            if dot["agent_id"] != selected["agent_id"]:
                raise Denied("file access conversation belongs to another Dot")
            permission_flag = ("file_access_owner_approved" if selected["kind"] == "workspace-files"
                               else "terminal_access_owner_approved")
            file_scope = {"conversation_id": conversation_id, permission_flag: True}
            # A lost HTTP acknowledgement must not create a second set of Grants.
            for existing in control.list_work_items(host.owner, limit=1000)["items"]:
                if existing.get("state") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    continue
                meta = existing.get("metadata", {})
                if (existing["run_id"] != run["run_id"] or
                        existing.get("assignee_agent_id") != selected["agent_id"] or
                        meta.get("workspace_id") != ws or meta.get("machine_id") != machine_id or
                        meta.get("conversation_id") != conversation_id or
                        meta.get(permission_flag) is not True or
                        not set(capabilities) <= set(existing.get("required_capabilities", []))):
                    continue
                active = [grant for grant in control.authorization.list_grants(host.owner,
                    principal_type="agent", principal_id=selected["agent_id"])["items"]
                    if grant["scope_type"] == "work_item" and
                    grant["scope_id"] == existing["work_item_id"] and
                    grant["capability"] in set(capabilities)]
                if (existing["state"] == "RUNNING" and
                        {grant["capability"] for grant in active} == set(capabilities)):
                    return {"work_item": existing, "machine_id": machine_id,
                            "grant_ids": [grant["grant_id"] for grant in active],
                            "existing_authorization": True}
                raise Denied("existing incomplete file WorkItem must be reviewed or revoked before a new authorization")
        if run["state"] == "CREATED":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING",
                                           reason="owner prepared a machine task")
        elif run["state"] != "RUNNING":
            raise Denied("resume the Canvas run before preparing a machine task")
        control.ensure_agent(run["run_id"], runtime.owner,
                             agent_id=selected["agent_id"], role="worker")
        item = control.create_work_item(run["run_id"], runtime.owner,
            work_item_id="WI-machine-" + secrets.token_hex(12), objective=objective.strip(),
            assignee_agent_id=selected["agent_id"], required_capabilities=sorted(set(capabilities)),
            metadata={"workspace_id": ws, "machine_id": machine_id,
                      "canvas_agent_id": selected["agent_id"], "owner_configured": True,
                      **file_scope})
        grants = [control.authorization_grant(runtime.owner, principal_type="agent",
                    principal_id=selected["agent_id"], capability=cap,
                    scope_type="work_item", scope_id=item["work_item_id"])
                  for cap in sorted(set(capabilities))]
        control.transition_work_item(item["work_item_id"], runtime.owner, "RUNNING")
        return {"work_item": control.work_item_info(item["work_item_id"], runtime.owner),
                "machine_id": machine_id, "grant_ids": [g["grant_id"] for g in grants]}

    def center_revoke_files(self, ws, work_item_id, conversation_id, *, approve=False):
        """Owner revokes only this conversation's existing workspace-files Grants."""
        if approve is not True:
            raise Denied("explicit owner approval required for file access revocation")
        self.store.workspace(ws)
        host = self._machine_service()
        item = host.control.work_item_info(work_item_id, host.owner)
        meta = item.get("metadata", {})
        if (meta.get("workspace_id") != ws or
                meta.get("conversation_id") != conversation_id):
            raise Denied("WorkItem does not belong to this conversation")
        machine = next((m for m in host.inventory(ws) if m["machine_id"] == meta.get("machine_id")), None)
        if (machine is None or machine["kind"] not in {"workspace-files", "terminal"} or
                machine["agent_id"] != item["assignee_agent_id"] or
                meta.get("file_access_owner_approved" if machine["kind"] == "workspace-files"
                         else "terminal_access_owner_approved") is not True):
            raise Denied("invalid scoped machine ownership")
        grants = host.control.authorization.list_grants(host.owner, principal_type="agent",
            principal_id=item["assignee_agent_id"])["items"]
        revoked = []
        for grant in grants:
            if grant["scope_type"] == "work_item" and grant["scope_id"] == work_item_id and (
                    grant["capability"] in set(machine["capabilities"])):
                if not grant.get("revoked"):
                    host.control.authorization_revoke(grant["grant_id"], host.owner)
                    revoked.append(grant["grant_id"])
        if item["state"] in {"RUNNING", "QUEUED", "PENDING"}:
            host.control.transition_work_item(work_item_id, host.owner, "CANCELLED")
        return {"revoked_grants": len(revoked), "work_item_id": work_item_id, "access": "revoked"}

    def center_execute(self, ws, work_item_id, machine_id, capability_id, operation_id,
                       arguments, request_key):
        self.store.workspace(ws)
        return self._machine_service().dispatch(workspace_id=ws, work_item_id=work_item_id,
            machine_id=machine_id, capability_id=capability_id, operation_id=operation_id,
            arguments=arguments, idempotency_key=request_key)

    def center_operation(self, ws, operation_id, *, as_owner=True):
        self.store.workspace(ws)
        return self._machine_service().observe(workspace_id=ws, operation_id=operation_id,
                                               as_owner=as_owner)

    def center_experiences(self, ws, work_item_id, machine_id, query, limit=5):
        self.store.workspace(ws)
        return self._machine_service().experiences(workspace_id=ws,work_item_id=work_item_id,
            machine_id=machine_id,query=query,limit=limit)

    def center_plan(self, ws, work_item_id, action="read", steps=None, expected_revision=None):
        self.store.workspace(ws)
        host=self._machine_service()
        item=host.control.work_item_info(work_item_id,host.owner)
        if item.get("metadata",{}).get("workspace_id")!=ws:
            raise Denied("plan task outside workspace")
        with self._lock:
            if self._plan_history is None:
                from sentra_runtime.plan_history import PlanHistory
                self._plan_history=PlanHistory(host.control,owner=host.owner)
        if action=="read":return self._plan_history.current(work_item_id)
        if action=="revise":return self._plan_history.revise(work_item_id,steps,expected_revision=expected_revision)
        if action in {"undo","redo"}:
            return self._plan_history.navigate(work_item_id,direction=action,expected_revision=expected_revision)
        raise ValueError("unknown plan action")

    def _agent_machine_control(self, token, payload):
        # Validate a live agent session under the Canvas lock, then release it
        # before potentially long provider I/O so other agents/UI remain usable.
        with self._lock:
            binding = self._agent_tokens.get(token)
            if binding is None:
                raise Denied("unknown Canvas agent capability")
            ws, terminal = binding
            workspace = self.store.workspace(ws)
            if payload.get("workspace") != workspace["path"]:
                raise Denied("Canvas capability belongs to another workspace")
            if terminal.startswith("shell:"):
                if self._shell_runtime is None:
                    raise Denied("shell runtime capability is no longer available")
                subject = self._shell_runtime.actors.subject(token, payload)
                agents = {subject["dot"]["agent_id"]}
                shell_conversation_id = subject["message"]["conversation_id"]
            elif terminal.startswith("task:"):
                task = self.store.resource("tasks", terminal[5:], ws)
                process = self._task_processes.get(task["id"])
                if process is None or process.poll() is not None:
                    self._revoke_agent(terminal)
                    raise Denied("Canvas task session is no longer running")
                agents = {task["agent_id"]}
            else:
                session = self._sessions.get(terminal)
                if session is None or session.pty is None or session.pty.poll() is not None:
                    self._revoke_agent(terminal)
                    raise Denied("Canvas agent session is no longer running")
                agents = {a["id"] for a in self.store.list_resources("agents", ws)
                          if a.get("terminal_id") == terminal}
        action = payload["action"]
        if not terminal.startswith("shell:"):
            shell_conversation_id = None
        if action == "machine_list":
            host=self._machine_service()
            tasks=host.task_catalog(workspace_id=ws,agent_ids=agents,conversation_id=shell_conversation_id)
            if shell_conversation_id:
                file_ids = {m["machine_id"] for m in host.inventory(ws)
                            if m["kind"] in {"workspace-files", "terminal", "computer-local", "virtualbox_vm"}}
                tasks = [item for item in tasks if item["machine_id"] not in file_ids
                         or host.control.work_item_info(item["work_item_id"], host.owner)
                         .get("metadata", {}).get("conversation_id") == shell_conversation_id]
            scopes={}
            for item in tasks:scopes.setdefault(item["machine_id"],set()).update(item["capabilities"])
            return {"machines":[{**m,"capabilities":sorted(scopes[m["machine_id"]]),
                "actions":{cap:values for cap,values in m["actions"].items() if cap in scopes[m["machine_id"]]}}
                for m in host.inventory(ws) if m["machine_id"] in scopes],"work_items":tasks}
        runtime = self._runtime()
        if action == "machine_observe":
            row = runtime.durable.operation_status(payload["operation_id"], runtime.owner)
            if (row.get("progress") or {}).get("principal_id") not in agents:
                raise Denied("operation belongs to another Canvas agent")
            return self.center_operation(ws, payload["operation_id"], as_owner=False)
        item = runtime.governance.work_item_info(payload["work_item_id"], runtime.owner)
        if (item.get("assignee_agent_id") not in agents
                or item.get("metadata", {}).get("workspace_id") != ws):
            raise Denied("machine task belongs to another Canvas agent")
        if (shell_conversation_id and payload.get("capability_id", "").startswith(("workspace:file.", "computer:", "terminal:", "vm:"))
                and item.get("metadata", {}).get("conversation_id") != shell_conversation_id):
            raise Denied("file task belongs to another conversation")
        if action == "machine_experiences":
            return self.center_experiences(ws,payload["work_item_id"],payload["machine_id"],
                payload["query"],payload.get("limit",5))
        return self.center_execute(ws, payload["work_item_id"], payload["machine_id"],
            payload["capability_id"], payload["operation_id"], payload["arguments"],
            payload["request_key"])

    def _collaboration_service(self):
        with self._lock:
            if self._collab_authority is None:
                from sentra_collab.authority import CollaborationAuthority
                host = self._machine_service()
                self._collab_authority = CollaborationAuthority(host.control, owner=host.owner)
            return self._collab_authority

    def collab_session(self, ws, work_item_id, principal_id, permission="read"):
        """Owner-issued one-use ticket; grants must already exist in ControlPlane."""
        self.store.workspace(ws)
        return self._collaboration_service().issue(workspace_id=ws, principal_id=principal_id,
            work_item_id=work_item_id, principal_type="user", permission=permission)

    def collab_prepare(self, ws, principal_id):
        """Explicit owner action creates a user-scoped presentation task only."""
        from sentra_collab.authority import _id
        self.store.workspace(ws)
        principal_id = _id(principal_id)
        host = self._machine_service()
        runtime = self._runtime()
        run = runtime.run(ws)
        if run["state"] == "CREATED":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING",
                                           reason="owner enabled Canvas collaboration")
        elif run["state"] != "RUNNING":
            raise Denied("resume the Canvas run before enabling collaboration")
        caps = ["canvas.collab.read", "canvas.collab.write"]
        item = host.control.create_work_item(run["run_id"], host.owner,
            work_item_id="WI-collab-" + secrets.token_hex(12),
            objective="Collaborative Canvas layout and existing note text",
            assignee_user_id=principal_id, required_capabilities=caps,
            metadata={"workspace_id":ws,"owner_configured":True,"canvas_collaboration":True})
        for cap in caps:
            host.control.authorization_grant(host.owner, principal_type="user",
                principal_id=principal_id, capability=cap, scope_type="work_item",
                scope_id=item["work_item_id"])
        host.control.transition_work_item(item["work_item_id"], host.owner, "RUNNING")
        return {"work_item_id":item["work_item_id"],"principal_id":principal_id}

    def collab_disable(self, ws, work_item_id, principal_id):
        self.store.workspace(ws)
        host = self._machine_service()
        item = host.control.work_item_info(work_item_id, host.owner)
        if (item.get("assignee_user_id") != principal_id
                or item.get("metadata", {}).get("workspace_id") != ws
                or item.get("metadata", {}).get("canvas_collaboration") is not True):
            raise Denied("collaboration task identity mismatch")
        rows = host.control.authorization.list_grants(host.owner,
            principal_type="user", principal_id=principal_id)["items"]
        for grant in rows:
            if grant["scope_type"] == "work_item" and grant["scope_id"] == work_item_id:
                host.control.authorization.revoke(grant["grant_id"], host.owner)
        if item["state"] == "RUNNING":
            host.control.transition_work_item(work_item_id, host.owner, "CANCELLED")
        return {"disabled":True}

    def collab_host_call(self, method, params):
        """Private bearer-authenticated callbacks for the owned Node sidecar."""
        if not isinstance(params, dict):
            raise ValueError("collaboration callback parameters required")
        from .project_documents import DOCUMENT_HOST_METHODS
        if method in DOCUMENT_HOST_METHODS:
            return self._document_service().host_call(method, params)
        authority = self._collaboration_service()
        if method == "resolveGrant":
            self.store.workspace(params["workspaceId"])
            return authority.resolve(token=params["token"], workspace_id=params["workspaceId"])
        if method == "checkGrant":
            self.store.workspace(params["workspaceId"])
            return authority.check(params, action=params.get("action", "read"))
        if method == "consumeNonce":
            self.store.workspace(params["workspaceId"])
            return authority.consume(params, fingerprint=params["fingerprint"])
        if method == "loadSnapshot":
            self.store.workspace(params["workspaceId"])
            return authority.load(params["workspaceId"])
        if method == "commitSnapshot":
            self.store.workspace(params["workspaceId"])
            context = params["context"]
            if (context.get("workspaceId") != params["workspaceId"]
                    or context.get("principalId") != params["principalId"]
                    or context.get("epoch") != params["epoch"]):
                raise Denied("collaboration commit identity mismatch")
            result = authority.commit(context=context, expected_revision=params["expectedRevision"],
                snapshot=params["snapshot"], presentation=params["presentation"])
            # Snapshot commits first. A crash during projection is repaired on
            # the next graph read; an unknown acknowledgement is never replayed.
            self._apply_collaboration(params["workspaceId"], authority)
            return result
        raise ValueError("unsupported collaboration callback")

    def _apply_collaboration(self, ws, authority=None):
        authority = authority or self._collaboration_service()
        stored = authority.load(ws)
        self.graph.apply_presentation(ws, stored["revision"], stored["presentation"])
        return stored

    def _dispatch_loop(self):
        while not self._dispatch_stop.is_set():
            try:
                self._drain_tasks()
            except Exception as exc:
                self._task_runtime_error=type(exc).__name__
            self._dispatch_wake.wait(.5)
            self._dispatch_wake.clear()

    def _drain_tasks(self):
        with self._lock:
            if self._closing:return
            runtime=self._runtime()
            error=None
            for task in self.store.projection_tasks():
                try:runtime.project(task)
                except Exception as exc:error=type(exc).__name__
            self._task_runtime_error=error
            queued=self.store.queued_tasks()
            runs={}
            for task in queued:runs.setdefault(task["run_id"],runtime.task_run(task))
            active_agents=set()
            for ident,(ws,agent) in self._job_tasks.items():
                # A registered worker retains its seat until its final state and
                # process teardown have completed, including cancellation.
                task=self.store.resource("tasks",ident,ws)
                runtime.flush_usage(task)
                run=runs.setdefault(task["run_id"],runtime.task_run(task))
                active_agents.add(agent)
                operation=runtime.operation(task)
                governed=runtime.work_item(task)
                if task["cancel_requested"] or operation["state"]=="CANCEL_REQUESTED" or governed["state"] in {"CANCELLED","FAILED","BLOCKED"} or run["state"] in {"CANCELLED","FAILED","SUCCEEDED"}:
                    self.store.request_task_cancel(ws,ident)
                    if ident in self._jobs:self._jobs[ident].set()
            for task in queued:
                run=runs[task["run_id"]]
                governed=runtime.work_item(task)
                if task["cancel_requested"] or governed["state"] in {"CANCELLED","FAILED"} or run["state"] in {"CANCELLED","FAILED","SUCCEEDED"}:
                    self.store.task_state(task["workspace_id"],task["id"],"cancelled")
                    continue
                if run["state"]!="RUNNING" or run["desired_state"]!="RUNNING":continue
                if len(self._job_tasks)>=self.max_task_workers:break
                if task["agent_id"] in active_agents:continue
                operation=runtime.operation(task)
                if operation["state"]!="QUEUED" or operation["progress"].get("revision")!=task["revision"]:
                    continue
                if not runtime.admission(task,reserve=True)["allowed"]:continue
                # Commit the claim before launching a thread or external child.
                self.store.task_state(task["workspace_id"],task["id"],"running")
                claimed=self.store.resource("tasks",task["id"],task["workspace_id"])
                try:runtime.project(claimed)
                except Exception:
                    # No worker/thread/child has been created yet.
                    self.store.task_state(task["workspace_id"],task["id"],"failed","durable claim publication failed before execution")
                    raise
                cancel=threading.Event()
                self._jobs[task["id"]]=cancel
                self._job_tasks[task["id"]]=(task["workspace_id"],task["agent_id"])
                thread=threading.Thread(target=self._run_task,args=(task["workspace_id"],claimed,cancel),
                    daemon=True,name="sentra-task-"+task["id"][:8])
                self._task_threads[task["id"]]=thread
                active_agents.add(task["agent_id"])
                try:thread.start()
                except Exception:
                    self._jobs.pop(task["id"],None);self._task_threads.pop(task["id"],None)
                    self._job_tasks.pop(task["id"],None)
                    self.store.task_state(task["workspace_id"],task["id"],"failed","worker startup failed")
                    raise

    def task_scheduler_status(self):
        with self._lock:
            return {"worker_limit":self.max_task_workers,"pending_limit":self.max_pending_tasks,
                    "active_workers":len(self._job_tasks),"projection_error":self._task_runtime_error,
                    "closing":self._closing}

    def task_governance(self,ws,ident):
        with self._lock:
            task=self.store.resource("tasks",ident,ws)
            runtime=self._runtime()
            runtime.project(task)
            task=self.store.resource("tasks",ident,ws)
            return {"work_item":runtime.work_item(task),
                    "execution_status":task["status"],"check_count":len(task["checks"]),
                    "cost":runtime.governance.cost_summary(runtime.owner,work_item_id=task["work_item_id"]),
                    "provider_usage":runtime.usage_summary(task),
                    "admission":runtime.admission(task) if task["status"]=="queued" else None}

    def task_control(self,ws,ident,action):
        with self._lock:
            task=self.store.resource("tasks",ident,ws)
            if task["status"]!="queued":
                raise ValueError("only queued tasks can be blocked or unblocked; cancel running tasks explicitly")
            if action not in {"block","unblock"}:raise ValueError("invalid work item control")
            runtime=self._runtime()
            runtime.project(task)
            result=runtime.governance.transition_work_item(task["work_item_id"],runtime.owner,
                "BLOCKED" if action=="block" else "QUEUED",reason="explicit native Canvas control")
            self._dispatch_wake.set()
            return result

    def task_verify(self,ws,ident):
        with self._lock:
            return self._runtime().verify(self.store.resource("tasks",ident,ws))

    def budget_policies(self,ws):
        with self._lock:
            workspace=self.store.workspace(ws)
            runtime=self._runtime()
            items=runtime.budgets.list_policies(runtime.owner)["items"]
            def visible(item):
                if item["scope_type"]=="workspace":return item["scope_id"]==workspace["path"]
                if item["scope_type"]=="run":return item["scope_id"]==workspace["run_id"]
                if item["scope_type"]=="work_item":
                    try:work=runtime.governance.work_item_info(item["scope_id"],runtime.owner)
                    except FileNotFoundError:return False
                    return work["metadata"].get("workspace_id")==ws
                return False
            return {"items":[item for item in items if visible(item)]}

    def budget_set(self,ws,scope,limits,*,task_id=None,mode="hard_stop",policy_id=None,enabled=True):
        with self._lock:
            workspace=self.store.workspace(ws)
            runtime=self._runtime()
            if policy_id is not None:
                if policy_id not in {p["budget_policy_id"] for p in self.budget_policies(ws)["items"]}:
                    raise Denied("budget policy is outside this workspace")
                result=runtime.budgets.set_enabled(policy_id,runtime.owner,enabled=enabled)
            else:
                if scope=="workspace":scope_id=workspace["path"]
                elif scope=="run":scope_id=workspace["run_id"]
                elif scope=="work_item":scope_id=self.store.resource("tasks",task_id,ws)["work_item_id"]
                else:raise ValueError("budget scope must be workspace, run or work_item")
                result=runtime.budgets.set_policy(runtime.owner,scope_type=scope,scope_id=scope_id,
                    limits=limits,mode=mode,enabled=enabled)
            self._dispatch_wake.set()
            return result

    def workspaces(self):
        return [{**w,"namespace":Namespace(w["id"]).path}
                for w in self.store.workspaces()]

    def workspace_detail(self,ws):
        root=self.store.workspace(ws)
        terminals=self._list_terminals(ws)
        agents=self.store.list_resources("agents",ws)
        teams=self.store.list_resources("teams",ws)
        tasks=self.store.list_resources("tasks",ws)
        return {
            "workspace":{**root,"namespace":Namespace(ws).path},
            "terminals":[{**t,"namespace":Namespace(ws,session=t["id"]).path}
                         for t in terminals],
            "agents":[{**a,"namespace":Namespace(ws,agent=a["id"]).path}
                      for a in agents],
            "teams":[{**t,"namespace":Namespace(ws,team=t["id"]).path}
                     for t in teams],
            "tasks":[{**t,"namespace":Namespace(ws,team=t["team_id"],
                       agent=t["agent_id"],task=t["id"]).path} for t in tasks],
            "events":self.store.events(ws,limit=100)
        }

    def graph_detail(self, ws):
        state=self.workspace_detail(ws)
        canvas=self.graph.sync(ws,state["terminals"],state["agents"],state["teams"])
        stored = self._apply_collaboration(ws)
        canvas = self.graph.snapshot(ws)
        return {**state, **canvas, "collaboration_revision": stored["revision"],
                "collaboration_layout": stored["presentation"]["layout"]}

    def graph_move(self,ws,ident,x,y):
        self.store.workspace(ws)
        return self.graph.move(ws,ident,x,y)

    def graph_resize(self,ws,ident,width,height):
        self.store.workspace(ws)
        return self.graph.resize(ws,ident,width,height)

    def graph_note(self,ws,title,body,x=440,y=220):
        self.store.workspace(ws)
        note=self.graph.note(ws,title,body,x,y)
        self.store.event(ws,note["id"],"canvas.note.created",title)
        return note

    def graph_update_note(self,ws,ident,body):
        self.store.workspace(ws)
        return self.graph.update_note(ws,ident,body)

    def graph_remove_note(self,ws,ident):
        self.store.workspace(ws)
        self.graph.remove_note(ws,ident)
        self.store.event(ws,ident,"canvas.note.removed")
        return {"ok":True}

    def graph_link(self,ws,source,target):
        self.store.workspace(ws)
        link=self.graph.link(ws,source,target)
        self.store.event(ws,link["id"],"canvas.link.created")
        return link

    def graph_unlink(self,ws,ident):
        self.store.workspace(ws)
        self.graph.unlink(ws,ident)
        self.store.event(ws,ident,"canvas.link.removed")
        return {"ok":True}

    def handoff(self,ws,source,target,message,approved=False,request_key=None):
        """Explicit directed relay to an active agent CLI, never to a shell."""
        self.store.workspace(ws)
        if approved is not True:
            raise Denied("explicit handoff approval required")
        if (not isinstance(message,str) or not 1<=len(message.strip())<=4000
            or any(ord(ch)<32 or ord(ch)==127 for ch in message)):
            raise ValueError("handoff must be a single-line message without control characters")
        if request_key is not None:
            if not isinstance(request_key,str) or not 1<=len(request_key)<=128:
                raise ValueError("handoff request key must contain 1-128 characters")
            previous=self.graph.handoff_request(ws,source,target,message,request_key)
            if previous:
                return {"id":previous["id"],"transport":"conpty-stdin","status":previous["status"],
                        "model_acknowledged":False,"idempotent_replay":True}
        origin,destination=self.graph.linked_target(ws,source,target)
        if destination["kind"]=="agent":
            agent=self.store.resource("agents",destination["resource_id"],ws)
            if not agent["terminal_id"]:
                raise ValueError("destination agent session is not running")
            terminal=self.store.resource("terminals",agent["terminal_id"],ws)
        elif destination["kind"]=="terminal":
            terminal=self.store.resource("terminals",destination["resource_id"],ws)
        else:
            raise ValueError("destination must be a terminal or agent node")
        if terminal["shell"] not in ("sentra-cli","codex"):
            raise Denied("handoff allowed only to supported agent CLIs, not OS shells")
        session=self._sessions.get(terminal["id"])
        if session is None or session.pty is None or session.pty.poll() is not None:
            raise ValueError("destination CLI session is not running")
        result,created=self.graph.prepare_handoff(ws,source,target,message,request_key or new_id())
        if not created:
            return {"id":result["id"],"transport":"conpty-stdin","status":result["status"],
                    "model_acknowledged":False,"idempotent_replay":True}
        self.graph.handoff_state(ws,result["id"],"sending")
        try:
            # A write is evidence of transport only, NOT that a model processed it.
            session.pty.write((message+"\r").encode("utf-8"))
        except BaseException:
            self.graph.handoff_state(ws,result["id"],"uncertain")
            raise
        result=self.graph.handoff_state(ws,result["id"],"sent")
        self.store.event(ws,result["id"],"canvas.handoff.sent",
                         "transport-only "+terminal["shell"])
        return {"id":result["id"],"transport":"conpty-stdin",
                "status":"sent","model_acknowledged":False}

    def _uncertain_receipts_for_terminal(self,ws,terminal):
        agents={a["id"] for a in self.store.list_resources("agents",ws)
                if a["terminal_id"]==terminal}
        targets={n["id"] for n in self.graph.snapshot(ws)["nodes"]
                 if (n["kind"]=="terminal" and n["resource_id"]==terminal)
                 or (n["kind"]=="agent" and n["resource_id"] in agents)}
        return self.graph.interrupt_handoffs(ws,targets)

    def _list_terminals(self,ws):
        result=self.store.list_resources("terminals",ws)
        for terminal in result:
            session=self._sessions.get(terminal["id"])
            if session and session.pty:
                status=session.pty.poll()
                if status is not None and terminal["status"]=="running":
                    self._uncertain_receipts_for_terminal(ws,terminal["id"])
                    self.store.terminal_state(ws,terminal["id"],"exited")
                    terminal["status"]="exited"
                    terminal["exit_code"]=status
        return result

    def create_workspace(self,name):
        return self.store.create_workspace(name)

    def attach_workspace(self,name,path):
        return self.store.attach_workspace(name,path)

    def run_control(self,ws,action):
        self.store.workspace(ws)
        if action not in {"pause","resume","cancel"}:raise ValueError("invalid run control")
        with self._lock:
            result=self._runtime().control_project(ws,action)
            if action=="cancel":
                for ident,(workspace,_) in self._job_tasks.items():
                    if workspace==ws:
                        self.store.request_task_cancel(ws,ident)
                        if ident in self._jobs:self._jobs[ident].set()
            self._dispatch_wake.set()
            return result

    def _start(self,ws,name,shell,argv,*,execution_scope=None):
        with self._lock:
            if self._closing:
                raise RuntimeError("Canvas runtime is shutting down")
            active=sum(1 for s in self._sessions.values()
                       if s.pty is not None and s.pty.poll() is None)
            if active>=self.max_terminals:
                raise ValueError("terminal concurrency quota reached")
            workspace=self.store.workspace(ws)
            execution_directory=Path(workspace['path'])
            from sentra_runtime.effect_boundary import current_effect_context
            effect=current_effect_context.get()
            if effect is not None and effect.request.capability_id=='terminal:start':
                from .task_workspace import directory
                execution_directory=directory(self._shell_service(),self._runtime().owner,effect.request,execution_directory)
            elif execution_scope:
                from .task_workspace import binding
                cid,agent_id=execution_scope
                assigned=binding(self._shell_service(),self._runtime().owner,ws,cid,agent_id)
                if assigned:execution_directory=Path(assigned['path'])
            record=self.store.create_terminal(ws,name,shell)
            session=Session(
                lambda text: self.store.append_terminal_output(ws,record["id"],text),
                lambda error: self.store.event(ws,record["id"],"terminal.transcript.failed",error))
            session.exit_input=b"/exit\r" if shell=="sentra-cli" else b"\x03" if shell=="codex" else b"exit\r"
            self._sessions[record["id"]]=session
            try:
                options={}
                if shell in {'powershell','pwsh'}:
                    from .shell_environment import shell_child_environment
                    options['env']=shell_child_environment(shell,os.environ)
                if shell=="sentra-cli" and self._agent_port is not None:
                    token=secrets.token_urlsafe(36)
                    self._agent_tokens[token]=(ws,record["id"])
                    environment=os.environ.copy()
                    for key in list(environment):
                        if key.startswith(("MAESTRI_","SENTRA_CANVAS_AGENT_")):
                            environment.pop(key)
                    # This capability cannot use the UI/runtime bearer routes.
                    environment.update(SENTRA_CANVAS_AGENT_TOKEN=token,
                                       SENTRA_CANVAS_AGENT_PORT=str(self._agent_port))
                    if (self._agent_runtime_id and self._pty_client is not None
                            and self._pty_client.capabilities.get('agent_binding_proof')):
                        path=self._agent_bindings.reserve(ws,record['id'],token)
                        self._durable_agent_bindings.add(record['id'])
                        self._agent_bindings.publish(record['id'],token,ws,workspace['path'],
                            self._agent_port,self._agent_runtime_id)
                        environment['SENTRA_CANVAS_AGENT_BINDING_FILE']=str(path.resolve())
                    options["env"]=environment
                if self._pty_client is not None:
                    from .pty_client import DaemonPTY
                    session.pty=DaemonPTY.create(self._pty_client,ws,record["id"],argv,execution_directory,**options)
                else:
                    session.pty=WindowsPTY(argv,execution_directory,session.append,**options)
                if options.get('env',{}).get('SENTRA_CANVAS_AGENT_BINDING_FILE'):
                    self._agent_bindings.recover({'process_live':True,'terminal_id':record['id'],'workspace_id':ws,
                        'runtime_id':session.pty.runtime_id,'pid':session.pty.pid,
                        'agent_token_sha256':hashlib.sha256(token.encode()).hexdigest()})
                self.store.terminal_state(ws,record["id"],"running",session.pty.pid)
                record.update(status="running",pid=session.pty.pid)
            except Exception:
                self.store.terminal_state(ws,record["id"],"error")
                self._sessions.pop(record["id"],None)
                self._revoke_agent(record["id"])
                raise
            return record

    def _revoke_agent(self,terminal):
        with self._lock:
            for token,(_,ident) in list(self._agent_tokens.items()):
                if ident==terminal:
                    self._agent_tokens.pop(token,None)
            self._agent_bindings.revoke(terminal)
            self._durable_agent_bindings.discard(terminal)

    def bind_agent_endpoint(self,port,runtime_id):
        with self._lock:
            self._agent_port=port;self._agent_runtime_id=runtime_id
            for token,(ws,terminal) in self._agent_tokens.items():
                session=self._sessions.get(terminal)
                if terminal in self._durable_agent_bindings and session and getattr(session.pty,'durable',False):
                    self._agent_bindings.publish(terminal,token,ws,self.store.workspace(ws)['path'],port,runtime_id)

    def _coordination_tables(self):
        # Additive service-owned tables; preserve the Store/graph schema versions.
        with self.store.tx():
            self.store.db.execute("""CREATE TABLE IF NOT EXISTS canvas_agent_requests(
                principal TEXT NOT NULL, workspace_id TEXT NOT NULL, actor TEXT NOT NULL,
                request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(principal,workspace_id,actor,request_key))""")
            self.store.db.execute("""CREATE TABLE IF NOT EXISTS canvas_agent_nodes(
                principal TEXT NOT NULL, workspace_id TEXT NOT NULL, actor TEXT NOT NULL,
                node_id TEXT NOT NULL, PRIMARY KEY(principal,workspace_id,actor,node_id))""")

    def _coordinate_agent(self,ws,actor,origins,state,payload):
        """Finite mutations, durably reserved before starting external processes."""
        action=payload["action"]
        value=payload.get("value","")
        key=payload.get("request_key")
        if not isinstance(value,str) or len(value)>4000:
            raise ValueError("Canvas coordination value must contain at most 4000 characters")
        if not isinstance(key,str) or not 1<=len(key)<=128:
            raise ValueError("persistent coordination identity required (1-128 characters)")
        self._coordination_tables()
        binding=(self.store.principal,ws,actor)
        identity=(*binding,key)
        fingerprint=hashlib.sha256(json.dumps([action,value],ensure_ascii=False).encode()).hexdigest()
        with self.store.lock:
            previous=self.store.db.execute("""SELECT * FROM canvas_agent_requests
                WHERE principal=? AND workspace_id=? AND actor=? AND request_key=?""",identity).fetchone()
            managed={row[0] for row in self.store.db.execute("""SELECT node_id FROM canvas_agent_nodes
                WHERE principal=? AND workspace_id=? AND actor=?""",binding)}
        if previous:
            if previous["fingerprint"]!=fingerprint:
                raise ValueError("Canvas coordination idempotency collision")
            result=json.loads(previous["result"])
            return {**result,"status":previous["status"] if previous["status"]!="pending" else "uncertain",
                    "request_key":key,"idempotent_replay":True,"model_acknowledged":False}
        connected={link["target"] for link in state["links"] if link["source"] in origins}
        allowed=origins|managed|connected
        sources=origins|managed

        def resolve(value,permitted):
            matches=[n for n in state["nodes"] if n["id"] in permitted
                     and value.strip() in (n["id"],n["resource_id"],n["title"])]
            if len(matches)!=1:
                raise Denied("unique authorized Canvas node required")
            return matches[0]

        parts=value.split("|");brief=None
        if action=="create_agent" and value.lstrip().startswith("{"):
            structured=json.loads(value)
            if not isinstance(structured,dict) or set(structured)-{"name","model","role","brief"}:
                raise ValueError("unsupported structured agent creation field")
            parts=[structured.get("name"),structured.get("model"),structured.get("role","worker")]
            if any(not isinstance(v,str) for v in parts):raise ValueError("agent name/model/role must be text")
            brief=structured.get("brief")
            if brief is not None and (not isinstance(brief,str) or not 1<=len(brief)<=3200):
                raise ValueError("bounded child-agent brief required")
        # Agent nodes survive terminal replacement and keep outgoing coordination.
        source=next((n for n in state["nodes"] if n["id"] in origins and n["kind"]=="agent"),
                    next((n for n in state["nodes"] if n["id"] in origins),None))
        if source is None:
            raise Denied("Canvas coordination origin required")
        if action in {"create_agent","create_terminal"}:
            if not 2<=len(parts)<=3:
                raise ValueError("creation requires name|model|optional role")
            name,model=parts[:2]
            role=parts[2] if len(parts)==3 else "worker"
            validated_name(name)
            if not MODEL_RE.fullmatch(model) or not 1<=len(role.strip())<=80:
                raise ValueError("invalid Canvas model or role")
            terminal_name=name[:44]+"_cli" if action=="create_agent" else name
            if any(t["name"]==terminal_name for t in state["terminals"]) or (
                action=="create_agent" and any(a["name"]==name for a in state["agents"])):
                raise ValueError("Canvas resource name already exists")
            if sum(s.pty is not None and s.pty.poll() is None for s in self._sessions.values())>=self.max_terminals:
                raise ValueError("terminal concurrency quota reached")
        elif action=="connect":
            if len(parts)==1:
                destination=resolve(parts[0],allowed)
            elif len(parts)==2:
                source=resolve(parts[0],sources)
                destination=resolve(parts[1],allowed)
            else:
                raise ValueError("connect requires target or source|target")
            if source["id"]==destination["id"]:
                raise ValueError("cannot connect a node to itself")
        elif action=="create_team":
            if len(parts)!=3:
                raise ValueError("team requires name|coordinator|comma-separated workers")
            name,coordinator,workers=parts
            validated_name(name)
            coordinator=resolve(coordinator,sources)
            workers=[resolve(w,allowed) for w in workers.split(",")]
            members=[coordinator,*workers]
            if (not 1<=len(workers)<=12 or any(n["kind"]!="agent" for n in members)
                or len({n["id"] for n in members})!=len(members)):
                raise ValueError("team requires distinct authorized agents")
            if any(t["name"]==name for t in state["teams"]):
                raise ValueError("Canvas team name already exists")
        else:
            raise ValueError("unsupported Canvas coordination action")
        with self.store.tx():
            self.store.db.execute("INSERT INTO canvas_agent_requests VALUES(?,?,?,?,?,?,?,?)",
                (*identity,fingerprint,"pending","{}",time.time()))
        try:
            grants=[]
            if action in {"create_agent","create_terminal"}:
                if action=="create_agent":
                    resource=self.create_agent(ws,name,model,role,start=True)
                    terminal=resource["terminal_id"]
                    kind="agent"
                else:
                    conversation=new_id()
                    command=self._cli_command(["--workspace",self.store.workspace(ws)["path"],
                        "--model",model,"--no-auto-start","--state-dir",str(self.state_dir.parent),
                        "--session-id",conversation])
                    resource=self._start(ws,name,"sentra-cli",command)
                    resource["conversation_id"]=conversation
                    terminal=resource["id"]
                    kind="terminal"
                graph=self.graph_detail(ws)
                node=next(n for n in graph["nodes"] if n["kind"]==kind and n["resource_id"]==resource["id"])
                grants=[n["id"] for n in graph["nodes"] if
                        (n["kind"]==kind and n["resource_id"]==resource["id"]) or
                        (n["kind"]=="terminal" and n["resource_id"]==terminal)]
                link=self.graph_link(ws,source["id"],node["id"])
                result={"resource":resource,"node_id":node["id"],"link":link,
                        "status":"started","model_acknowledged":False}
                # Make the created identities recoverable before an optional
                # bootstrap delivery. A lost delivery never recreates the child.
                with self.store.tx():
                    self.store.db.executemany("INSERT OR IGNORE INTO canvas_agent_nodes VALUES(?,?,?,?)",
                        [(*binding,ident) for ident in grants])
                    self.store.db.execute("UPDATE canvas_agent_requests SET result=? WHERE principal=? AND workspace_id=? AND actor=? AND request_key=?",
                        (json.dumps(result,ensure_ascii=False),*identity))
                if action=="create_agent":
                    from .agent_context import AgentWorkingContext
                    contexts=AgentWorkingContext(self.store)
                    parent=source["resource_id"] if source["kind"]=="agent" else None
                    snapshot=self._working_context_snapshot(ws,{parent} if parent else set(),{source["id"]},state)
                    parent_context=contexts.get(ws,parent) if parent else {"goal":""}
                    goals=snapshot["work_items"]
                    goal=brief or parent_context.get("goal") or "\n".join(item["objective"] for item in goals)
                    if goal:
                        bounded_goal=goal.encode()[:16000].decode("utf-8",errors="ignore")
                        result["working_context"]=contexts.set(ws,resource["id"],goal=bounded_goal,expected_revision=0,
                            parent_agent_id=parent,source_work_item_ids=[item["work_item_id"] for item in goals][:32])
                        message="Contexto de trabalho recebido do agente coordenador. Seu papel: "+role+". Objetivo: "+goal[:3000]+". Consulte [[CANVAS|context]] para o contexto atual, tarefas e conexões."
                        message=" ".join(re.sub(r"[\x00-\x1f\x7f]"," ",message).split())
                        bootstrap_key="bootstrap-"+hashlib.sha256(json.dumps([ws,actor,key],separators=(",",":")).encode()).hexdigest()
                        delivery=self.handoff(ws,source["id"],node["id"],message,True,bootstrap_key)
                        result["bootstrap_handoff_id"]=delivery.get("id")
                        result["bootstrap_model_answered"]=False
            elif action=="connect":
                result={"link":self.graph_link(ws,source["id"],destination["id"]),"status":"connected"}
            else:
                team=self.create_team(ws,name,coordinator["resource_id"],[w["resource_id"] for w in workers])
                graph=self.graph_detail(ws)
                node=next(n for n in graph["nodes"] if n["kind"]=="team" and n["resource_id"]==team["id"])
                grants=[node["id"]]
                result={"resource":team,"node_id":node["id"],"status":"created"}
            result.update(request_key=key,model_acknowledged=False)
            with self.store.tx():
                self.store.db.executemany("INSERT OR IGNORE INTO canvas_agent_nodes VALUES(?,?,?,?)",
                                         [(*binding,node) for node in grants])
                self.store.db.execute("""UPDATE canvas_agent_requests SET status=?,result=?
                    WHERE principal=? AND workspace_id=? AND actor=? AND request_key=?""",
                    (result["status"],json.dumps(result,ensure_ascii=False),*identity))
            return result
        except BaseException:
            # A crash/failure can follow process creation. Never retry that mutation.
            with self.store.tx():
                self.store.db.execute("""UPDATE canvas_agent_requests SET status='uncertain'
                    WHERE principal=? AND workspace_id=? AND actor=? AND request_key=?""",identity)
            raise

    def agent_control(self,token,payload):
        """A CLI sees only its own directed graph, not the UI bearer authority."""
        with self._lock:
            binding = self._agent_tokens.get(token)
            is_shell = binding is not None and binding[1].startswith("shell:")
        if is_shell and payload.get("action") not in {"machine_list", "machine_execute", "machine_observe", "machine_experiences"}:
            return self._shell_runtime.actors.dispatch(token, payload)
        if payload.get("action") in {"machine_list", "machine_execute", "machine_observe", "machine_experiences"}:
            return self._agent_machine_control(token, payload)
        with self._lock:
            binding=self._agent_tokens.get(token)
            if binding is None:
                raise Denied("unknown Canvas agent capability")
            ws,terminal=binding
            workspace=self.store.workspace(ws)
            if payload.get("workspace")!=workspace["path"]:
                raise Denied("Canvas capability belongs to another workspace")
            if terminal.startswith("task:"):
                task=self.store.resource("tasks",terminal[5:],ws)
                process=self._task_processes.get(task["id"])
                if process is None or process.poll() is not None:
                    self._revoke_agent(terminal)
                    raise Denied("Canvas task session is no longer running")
                agents={task["agent_id"]}
            else:
                session=self._sessions.get(terminal)
                if session is None or session.pty is None or session.pty.poll() is not None:
                    self._revoke_agent(terminal)
                    raise Denied("Canvas agent session is no longer running")
                agents=None
            state=self.graph_detail(ws)
            if agents is None:
                agents={a["id"] for a in state["agents"] if a["terminal_id"]==terminal}
            origins={n["id"] for n in state["nodes"]
                     if (n["kind"]=="terminal" and n["resource_id"]==terminal)
                     or (n["kind"]=="agent" and n["resource_id"] in agents)}
            action=payload.get("action")
            if action=="context":
                return self._working_context_snapshot(ws,agents,origins,state)
            if action=="skill_read":
                parameters=payload.get("parameters")
                if not isinstance(parameters,dict) or parameters.get("agent_id") not in agents:
                    raise Denied("skill read requires the current agent identity")
                return self.center_skill_library(ws,action="disclose",parameters=parameters)
            if action=="network_settings":return self.center_network(ws)
            if action=="network_whitelist":
                value=json.loads(payload.get("value",""))
                return self.center_network(ws,value,agent=True)
            if action=="peers":return self.center_network(ws)["presence"]
            if action in {"claim", "receipt"}:
                if terminal.startswith("task:"):
                    raise Denied("task workers cannot claim interactive handoffs")
                if action=="claim":
                    value=payload.get("value")
                    if not isinstance(value,str) or not 1<=len(value)<=4000:
                        raise ValueError("invalid handoff content")
                    return self.graph.claim_handoff(ws,origins,value) or {"status":"not_found"}
                ident=payload.get("handoff_id")
                if not isinstance(ident,str) or not re.fullmatch(r"[0-9a-f]{32}",ident):
                    raise ValueError("invalid receipt identifier")
                return self.graph.complete_handoff(ws,ident,origins,payload.get("receipt_status"))
            connections=[link for link in state["links"] if link["source"] in origins]
            targets={link["target"] for link in connections}
            nodes=[n for n in state["nodes"] if n["id"] in targets]
            action=payload.get("action")
            if action in {"create_agent","create_terminal","connect","create_team"}:
                actor="agent:"+sorted(agents)[0] if agents else "terminal:"+terminal
                return self._coordinate_agent(ws,actor,origins,state,payload)
            # The note->agent direction publishes read-only note context.
            # It must not grant send, edit, connect or dispatch privileges.
            incoming_note_ids={link["source"] for link in state["links"]
                if link["target"] in origins}
            incoming_notes=[n for n in state["nodes"]
                if n["kind"]=="note" and n["id"] in incoming_note_ids
                and n["id"] not in targets]
            if action=="list":
                outbound=[{k:n[k] for k in ("id","kind","title","resource_id")}
                          for n in nodes]
                return outbound+[{**{k:n[k] for k in ("id","kind","title","resource_id")},
                                  "access":"read_only","direction":"incoming"}
                                 for n in incoming_notes]
            value=payload.get("value","")
            if action=="note_read":
                matches=[n for n in incoming_notes
                    if value.strip() in (n["id"],n["title"])]
                if len(matches)==1:
                    return {"id":matches[0]["id"],"body":matches[0]["body"],
                            "access":"read_only"}
            if not isinstance(value,str):
                raise ValueError("Canvas command value must be text")
            target,_,content=value.partition("|")
            candidates=[n for n in nodes if target.strip() in (n["id"],n["title"])]
            if len(candidates)!=1:
                raise Denied("unique directed Canvas connection required")
            destination=candidates[0]
            source=next(link["source"] for link in connections if link["target"]==destination["id"])
            if action=="dispatch":
                key=payload.get("request_key")
                if not isinstance(key,str) or not key:
                    raise ValueError("persistent delivery identity required")
                return self.handoff(ws,source,destination["id"],content,True,key)
            if action=="check" and destination["kind"] in {"terminal","agent"}:
                ident=destination["resource_id"]
                if destination["kind"]=="agent":
                    ident=self.store.resource("agents",ident,ws)["terminal_id"]
                    if not ident:
                        return {"status":"configured","text":"","recoverable":False}
                output=self.terminal_output(ws,ident)
                receipts=[{"id":h["id"],"transport_status":h["status"],
                           "receipt_status":h["receipt_status"],"receipt_updated":h["receipt_updated"]}
                          for h in self.graph.handoffs(ws,limit=100)
                          if h["source"]==source and h["target"]==destination["id"]]
                return {**output,"text":output["text"][-4000:],"handoffs":receipts[:10]}
            if destination["kind"]=="note":
                if action=="note_read":
                    return {"id":destination["id"],"body":destination["body"]}
                if action=="note_write":
                    return self.graph_update_note(ws,destination["id"],content)
            raise ValueError("unsupported Canvas agent operation")

    def model_catalog(self):
        """Advisory model names from the authenticated Gateway; never attest access."""
        from sentra_cli.client import ModelClient,ProviderHTTPError
        from sentra_cli.config import CLIConfig
        from .shell_optional import CATALOG_SELECTABLE_MODELS
        cfg=CLIConfig(workspace=self.project_dir,state_root=self.state_dir.parent,
                      openai_api_key="none",auto_start_gateway=False)
        try:
            models=ModelClient(cfg).list_models()
            names=[name for name in models if isinstance(name,str)
                   and name.startswith(("sentra/","chatgpt-web/","gemini-web/"))]
            source="authenticated_catalog"
        except (ProviderHTTPError,OSError,ValueError,RuntimeError):
            names=[]
            source="unavailable"
        for name in CATALOG_SELECTABLE_MODELS:
            if name not in names:
                names.append(name)
        return {"models":names,"source":source,"model_access_verified":False,
                "inference_executed":False,"receipt":"access unverified"}

    def select_listed_model(self, model):
        """Accept an id the selector already read from this catalog.

        No provider call is made. Without a credential and a real turn the
        receipt stays access unverified.
        """
        if not isinstance(model,str) or not MODEL_RE.fullmatch(model):
            raise ValueError("invalid model identifier")
        catalog=self.model_catalog()
        if model not in catalog["models"]:
            raise ValueError("model is not in the catalog")
        return self._unverified_model_selection(model, catalog["source"])

    @staticmethod
    def _unverified_model_selection(model, source):
        return {"model":model,"selectable":True,"selected":True,"source":source,
                "model_access_verified":False,"inference_executed":False,
                "credential_present":False,"turn_executed":False,
                "receipt":"access unverified"}

    def _catalog_selection(self, model):
        from .shell_optional import CATALOG_SELECTABLE_MODELS
        if model not in CATALOG_SELECTABLE_MODELS:
            return None
        return self.select_listed_model(model)

    @staticmethod
    def _attach_catalog_selection(record, selection):
        if not selection:
            return record
        return {**record,"model_selection":selection}

    def center_capabilities(self, ws):
        """Authenticated Canvas read-only view of operational integration."""
        self.store.workspace(ws)
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        machines = self._machine_host.inventory(ws) if self._machine_host is not None else []
        return {
            "center": "SENTRA Control Plane",
            "authority": "existing DurableRunService / AuthorizationService",
            "capabilities": ["canvas.workspace.inspect", *sorted({cap for machine in machines
                                                                  for cap in machine["capabilities"]})],
            "registered_machines": machines,
            "remote_executors_enabled": any(machine["kind"] in {"openhands","daytona","guacamole","rustdesk"} for machine in machines),
            "configured_local_executors_enabled": any(machine["kind"] in {"documents","browser"} for machine in machines),
            "durable_intent_api": callable(
                getattr(self._runtime().durable, "reserve_operation_intent", None)),
            "experimental": True,
        }

    def center_inspect(self, ws, work_item_id, operation_id, request_key):
        """Execute a safe lab read through LIVE durable Control Plane authority.

        This compatibility inspection has no
        filesystem/browser/desktop/terminal execution capability; an explicit
        existing SQLite grant, host-owned WorkItem and operation ID are needed.
        """
        import asyncio
        from sentra_mcp.services.authorization import AuthorizationService
        from sentra_runtime.authority_bridge import BoundWorkItemPolicy
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        from sentra_runtime.contracts import (
            Capability, Machine, OperationRequest, OperationResult,
        )
        from sentra_runtime.durable_admission import DurableOperationGate
        from sentra_runtime.executor import ExecutorRegistry

        workspace = self.store.workspace(ws)
        runtime = self._runtime()
        run = runtime.run(ws)
        item = runtime.governance.work_item_info(work_item_id, runtime.owner)
        cap_id = "canvas.workspace.inspect"
        if (item["run_id"] != run["run_id"]
                or item.get("metadata", {}).get("workspace_id") != ws
                or item.get("assignee_agent_id") in (None, "")
                or cap_id not in item.get("required_capabilities", [])):
            raise Denied("work item not bound to approved Canvas workspace capability")
        machine = Machine(
            "canvas-center-" + ws, "canvas-read-only",
            runtime.owner, (Capability(cap_id, "Read local Canvas workspace summary"),),
        )
        authorization = self._machine_service().control.authorization
        policy = BoundWorkItemPolicy(
            owner=runtime.owner, principal_type="agent",
            authorization=authorization, governance=runtime.governance,
        )
        request = OperationRequest(
            operation_id=operation_id,
            principal_id=item["assignee_agent_id"],
            machine_id=machine.machine_id,
            capability_id=cap_id,
            work_item_id=work_item_id,
            idempotency_key=request_key,
            arguments={"workspace_id": ws, "action": "read-only-summary"},
        )

        class _LocalReadAdapter:
            async def start(self, req):
                # The local Canvas Store is the authoritative source of counts;
                # no terminal or third-party process is started.
                count = {
                    "agents": len(self_store.list_resources("agents", ws)),
                    "teams": len(self_store.list_resources("teams", ws)),
                    "terminals": len(self_store.list_resources("terminals", ws)),
                }
                return OperationResult(req.operation_id, "SUCCEEDED", count)

            async def reconcile(self, oid):
                return OperationResult(oid, "UNCERTAIN",
                                       error="durable reconciliation required")

        self_store = self.store
        registry = ExecutorRegistry(policy)
        registry.register(machine, _LocalReadAdapter())
        gate = DurableOperationGate(
            CentralDurableIntentAuthority(runtime.durable),
            policy, machine=machine,
        )
        result = asyncio.run(gate.submit(
            run_id=workspace["run_id"], owner=runtime.owner,
            request=request, effect=registry.submit,
        ))
        return {
            "operation_id": result.operation_id, "state": result.state,
            "evidence": dict(result.evidence),
            "run_id": workspace["run_id"], "work_item_id": work_item_id,
            "source": "real-sentra-control-plane",
        }

    def integrations(self):
        rows=terminal_catalog(self.project_dir)
        from sentra_cli.codex_native import authenticated
        for row in rows:
            if row["id"]=="codex" and row["installed"]:
                row["native_model_authenticated"]=authenticated()
        return rows

    def create_terminal(self,ws,name,shell="powershell",model=None,effort=None):
        workspace=Path(self.store.workspace(ws)["path"])
        if shell=="sentra-cli":
            # Use the same authoritative CLI as Canvas agents, never a stale
            # checkout/dist binary. A selected model must be explicitly bounded.
            if model is not None and (not isinstance(model,str) or not MODEL_RE.fullmatch(model)):
                raise ValueError("invalid SENTRA CLI model")
            args=["--workspace",str(workspace),"--state-dir",str(self.state_dir.parent),
                  "--session-id",new_id()]
            if model:
                args.extend(["--model",model])
            if effort is not None:
                if not isinstance(effort,str) or effort not in {"low","medium","high","xhigh"}:
                    raise ValueError("invalid SENTRA CLI reasoning effort")
                args.extend(["--effort",effort])
            command=self._cli_command(args)
        else:
            if model is not None:
                raise ValueError("model selection requires SENTRA CLI")
            if effort is not None:
                raise ValueError("effort selection requires SENTRA CLI")
            command=cli_argv(self.project_dir,workspace,shell)
        selection=self._catalog_selection(model) if isinstance(model,str) else None
        return self._attach_catalog_selection(self._start(ws,name,shell,command), selection)

    def launch_antigravity(self,ws,approved=False):
        workspace=self.store.workspace(ws)
        if approved is not True:
            raise Denied("explicit approval required to launch external application")
        adapter=resolve_adapters(self.project_dir).get("antigravity-app")
        if adapter is None:raise ValueError("Antigravity application is not installed")
        # GUI only: never claim it is a programmatic agent/ConPTY integration.
        proc=subprocess.Popen([*adapter,workspace["path"]],
                              stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.store.event(ws,str(proc.pid),"external.antigravity.launched","editor")
        return {"started":True,"pid":proc.pid,"mode":"external-app",
                "agent_api_connected":False}

    def terminal_checkpoint(self,ws,terminal):
        self.store.resource('terminals',terminal,ws)
        if self._pty_client is None or terminal not in self._sessions and terminal not in self._pty_histories:
            return {'available':False,'retryable':False,'reason':'durable_checkpoint_unavailable'}
        if not self._pty_client.capabilities.get('ansi_tui_snapshots') and terminal not in self._pty_histories:
            return {'available':False,'retryable':False,'reason':'daemon_checkpoint_unsupported'}
        return self._pty_client.call('checkpoint',{'workspace_id':ws,'terminal_id':terminal})

    def terminal_output(self,ws,terminal,cursor=0):
        record=self.store.resource("terminals",terminal,ws)
        session=self._sessions.get(terminal)
        if not session:
            if terminal in self._pty_histories and self._pty_client is not None:
                data=self._pty_client.call('output',{'workspace_id':ws,'terminal_id':terminal,'cursor':int(cursor)})
                return {**data,'status':'history_restored','recoverable':False}
            return {**self.store.terminal_output(ws,terminal,cursor),
                    "status":record["status"],"recoverable":False,
                    "persisted":True}
        if getattr(session.pty,"durable",False):
            data=session.pty.output(cursor)
            code=data.pop("exit_code")
            return {**data,"status":"running" if data.get('process_live',code is None) else "exited",
                    "exit_code":code,"recoverable":data.get('process_live',code is None)}
        data=session.output(cursor)
        state=session.pty.poll()
        if state is not None:
            self._uncertain_receipts_for_terminal(ws,terminal)
        data.update(status=("running" if state is None else "exited"),
                    exit_code=state,recoverable=True,
                    persisted=session.persistence_error is None,
                    persistence_error=session.persistence_error)
        return data

    def terminal_input(self,ws,terminal,data):
        self.store.resource("terminals",terminal,ws)
        if not isinstance(data,str) or len(data)>4096:
            raise ValueError("invalid terminal input")
        session=self._sessions.get(terminal)
        if session is None or session.pty is None:
            raise TerminalError("terminal is no longer attached")
        session.pty.write(data.encode("utf-8"))
        return {"ok":True}

    def terminal_resize(self,ws,terminal,cols,rows):
        self.store.resource("terminals",terminal,ws)
        session=self._sessions.get(terminal)
        if session is None or session.pty is None:
            raise TerminalError("terminal no longer attached")
        session.pty.resize(int(cols),int(rows))
        return {"ok":True}

    def terminal_close(self,ws,terminal):
        self.store.resource("terminals",terminal,ws)
        self._revoke_agent(terminal)
        session=self._sessions.get(terminal)
        if session and session.pty: session.pty.close(exit_input=session.exit_input)
        self._uncertain_receipts_for_terminal(ws,terminal)
        self.store.terminal_state(ws,terminal,"closed")
        return {"ok":True}

    def terminal_rename(self,ws,terminal,name):
        return self.store.rename_terminal(ws,terminal,name)

    def terminal_duplicate(self,ws,terminal,name):
        source=self.store.resource("terminals",terminal,ws)
        return self.create_terminal(ws,name,source["shell"])

    def _cli_command(self, arguments):
        """Use installed SENTRA CLI when frozen; source CLI in development."""
        if getattr(sys,"frozen",False):
            candidates=[Path(sys.executable).parent/"sentra-cli.exe",
                        self.project_dir/"dist"/"sentra-cli.exe",
                        self.project_dir/"sentra-cli.exe"]
            executable=next((x for x in candidates if x.is_file()),None)
            if executable is None:
                raise FileNotFoundError("SENTRA CLI executable not installed; install CLI to run real agents")
            return [str(executable),*arguments]
        source_root=Path(__file__).resolve().parents[1]
        launch=("import sys;sys.path.insert(0,"+repr(str(source_root))+
                ");from sentra_cli.__main__ import main;sys.exit(main())")
        # The desktop broker may run under pythonw. Its children need the
        # console interpreter so ConPTY and prompt-stdin have real stdio.
        interpreter = Path(sys.executable)
        if os.name == 'nt' and interpreter.name.lower().startswith('pythonw'):
            console = interpreter.with_name(interpreter.name.replace('pythonw', 'python'))
            if not console.is_file():
                raise FileNotFoundError('Python console interpreter required for SENTRA CLI')
            interpreter = console
        return [str(interpreter),"-u","-c",launch,*arguments]

    def create_agent(self,ws,name,model,role="worker",start=False,*,goal=None):
        validated_name(name)
        if not isinstance(model,str) or not MODEL_RE.fullmatch(model):
            raise ValueError("invalid model identifier")
        if not isinstance(role,str) or not 1 <= len(role.strip()) <= 80:
            raise ValueError("invalid agent role")
        if goal is not None and (not isinstance(goal,str) or len(goal.encode())>16000):
            raise ValueError("bounded agent working goal required")
        selection=self._catalog_selection(model)
        if not start:
            agent=self.store.create_agent(ws,name,model,role)
            if goal is not None:self.agent_working_context(ws,agent["id"],goal=goal,expected_revision=0)
            return self._attach_catalog_selection(agent, selection)
        # Process started is NOT evidence of authenticated model readiness.
        conversation_id=new_id()
        command=self._cli_command(["--workspace",self.store.workspace(ws)["path"],
                                   "--model",model,"--no-auto-start",
                                   "--state-dir",str(self.state_dir.parent),"--session-id",conversation_id])
        t=self._start(ws,name[:44]+"_cli","sentra-cli",command)
        try:
            agent=self.store.create_agent(ws,name,model,role,t["id"],conversation_id)
            if goal is not None:self.agent_working_context(ws,agent["id"],goal=goal,expected_revision=0)
            return self._attach_catalog_selection(agent, selection)
        except BaseException:
            self.terminal_close(ws,t["id"])
            raise

    def restart_agent(self,ws,agent_id):
        with self._lock:
            agent=self.store.resource("agents",agent_id,ws)
            existing=self._sessions.get(agent["terminal_id"])
            if existing and existing.pty and existing.pty.poll() is None:
                return agent
            command=self._cli_command(["--workspace",self.store.workspace(ws)["path"],
                "--model",agent["model"],"--no-auto-start","--state-dir",str(self.state_dir.parent),
                "--session-id",agent["conversation_id"]])
            terminal=self._start(ws,agent["name"][:35]+"_cli_"+new_id()[:8],"sentra-cli",command)
            try:
                return self.store.attach_agent_terminal(ws,agent_id,terminal["id"])
            except BaseException:
                self.terminal_close(ws,terminal["id"])
                raise

    def create_team(self,ws,name,coordinator,workers):
        return self.store.create_team(ws,name,coordinator,workers)

    def team_members(self,ws,team):
        return self.store.team_members(ws,team)

    def delegate(self,ws,team,agent,prompt,request_key,provider="test",
                 approved=False,*,checks=None):
        with self._lock:
            if self._closing:
                raise RuntimeError("Canvas runtime is shutting down")
            if provider=="sentra-cli" and approved is not True:
                raise Denied("explicit approval required before CLI can edit project")
            task,created=self.store.create_task(ws,team,agent,provider,prompt,request_key,
                approved=approved,max_pending=self.max_pending_tasks,checks=checks)
            self._dispatch_wake.set()
            return task

    def _run_task(self,ws,task,cancel):
        ident=task["id"]
        process=None
        try:
            if cancel.is_set():
                self.store.task_state(ws,ident,"cancelled"); return
            self.store.task_state(ws,ident,"running")
            if task["provider"]=="test":
                # Explicit deterministic TEST PROVIDER, never represented as AI.
                result="PROVEDOR DE TESTE (sem inferência): "+task["prompt"][:300]
                if cancel.wait(.08):
                    self.store.task_state(ws,ident,"cancelled"); return
                self.store.task_state(ws,ident,"succeeded",result)
                return
            agent=self.store.resource("agents",task["agent_id"],ws)
            # No automatic restart/retry of uncertain model responses.
            command=self._cli_command([
                "--prompt-stdin","--workspace",self.store.workspace(ws)["path"],
                "--model",agent["model"],"--no-auto-start","--timeout","90"])
            command.extend(["--state-dir",str(self.state_dir.parent),"--session-id","task_"+ident])
            with self._lock:
                if self._closing or cancel.is_set():
                    self.store.task_state(ws,ident,"cancelled");return
                environment=os.environ.copy()
                from sentra_runtime.provider_authority import ENVIRONMENT_KEY, prepare_provider_binding
                for key in list(environment):
                    if key.startswith(("MAESTRI_","SENTRA_CANVAS_AGENT_")) or key in {
                            ENVIRONMENT_KEY,"SENTRA_CANVAS_TOKEN","SENTRA_CANVAS_PORT"}:environment.pop(key)
                runtime=self._runtime()
                runtime.project(self.store.resource("tasks",ident,ws))
                binding=prepare_provider_binding(runtime.control,state_root=self.state_dir.parent,
                    owner=runtime.owner,principal=self.store.principal,conversation_id="task_"+ident,
                    project_id=ws,run_id=task["run_id"],work_item_id=task["work_item_id"],
                    operation_id=task["operation_id"])
                environment.update(binding["environment"])
                if self._agent_port is not None:
                    token=secrets.token_urlsafe(36)
                    self._agent_tokens[token]=(ws,"task:"+ident)
                    environment.update(SENTRA_CANVAS_AGENT_TOKEN=token,SENTRA_CANVAS_AGENT_PORT=str(self._agent_port))
                process=TaskProcess(
                    command,cwd=str(self.project_dir),stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,stdin=subprocess.PIPE,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),env=environment)
                self._task_processes[ident]=process
            deadline=time.monotonic()+120
            pending_input=task["prompt"].encode("utf-8")
            while True:
                try:
                    value=pending_input;pending_input=None
                    out,_=process.communicate(input=value,timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancel.is_set():
                        self._stop_task_process(process)
                        self.store.task_state(ws,ident,self._task_outcome(ws,task,process.returncode,True))
                        return
                    if time.monotonic()>deadline:
                        self._stop_task_process(process)
                        raise TimeoutError("SENTRA CLI exceeded 120 second deadline")
            text=sanitize_error(out.decode("utf-8","replace"))
            self.store.task_state(ws,ident,
                                  self._task_outcome(ws,task,process.returncode,cancel.is_set()),
                                  text[-10000:] or f"exit code {process.returncode}")
        except Exception as exc:
            if process is not None and process.poll() is None:
                self._stop_task_process(process)
            outcome=self._task_outcome(ws,task,process.returncode,cancel.is_set()) if process is not None else "failed"
            self.store.task_state(ws,ident,outcome,sanitize_error(f"{type(exc).__name__}: {exc}"))
        finally:
            self._revoke_agent("task:"+ident)
            with self._lock:
                self._jobs.pop(ident,None)
                self._task_threads.pop(ident,None)
                if process is None or process.poll() is not None:
                    self._task_processes.pop(ident,None)
                    self._job_tasks.pop(ident,None)
            self._dispatch_wake.set()

    @staticmethod
    def _stop_task_process(process):
        if isinstance(process,TaskProcess):
            process.terminate_tree()
            process.communicate(timeout=5)
            return
        if process.poll() is None:
            if os.name=="nt":
                subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            else:
                process.kill()
        process.communicate(timeout=5)

    def _task_outcome(self,ws,task,returncode,cancelled=False):
        from sentra_core.conversations import ConversationStore
        try:
            store=ConversationStore(self.state_dir.parent)
            sid="task_"+task["id"]
            store.open(self.store.workspace(ws)["path"],session_id=sid,resume=True)
            status=store.status(sid)
            if status["uncertain_calls"]:
                return "uncertain"
            if status["state"]=="completed" and returncode==0:
                return "succeeded"
            if status["state"]=="provider_error":
                return "failed"
            if cancelled and status["state"]=="ready" and not status["message_count"]:
                return "cancelled"
            return "uncertain"
        except Exception:
            # Missing or unreadable journals cannot prove no submission/effect.
            return "uncertain"

    def cancel_task(self,ws,task):
        with self._lock:
            row=self.store.request_task_cancel(ws,task)
            if row["status"]=="queued":
                self.store.task_state(ws,task,"cancelled")
            elif task in self._jobs:
                self._jobs[task].set()
            self._dispatch_wake.set()
        # Cancellation is cooperative; not declared cancelled until worker acknowledges.
        return {"requested":row["status"] in {"queued","running"}}

    def shutdown(self):
        with self._shutdown_lock:
            self._shutdown()

    def _shutdown(self):
        with self._lock:
            if self._closed:return
            self._closing=True
            self._dispatch_stop.set()
            self._dispatch_wake.set()
            self._agent_tokens.clear()
            for event in self._jobs.values():event.set()
            threads=list(self._task_threads.values())
        self._dispatch_thread.join(timeout=5)
        if self._shell_runtime is not None:
            self._shell_runtime.close()
        if self._shell_machines is not None:
            self._shell_machines.close()
        if self._collab_process is not None:
            self._collab_process.close()
        if self._network_settings is not None:
            self._network_settings.close()
        deadline=time.monotonic()+25
        for thread in threads:
            thread.join(timeout=max(0,deadline-time.monotonic()))
        # Keep the databases and owner lease alive if cancellation has not ended
        # an owned worker. A later explicit shutdown can retry safely.
        with self._lock:
            if any(thread.is_alive() for thread in self._task_threads.values()) or any(
                process.poll() is None for process in self._task_processes.values()):
                raise RuntimeError("Canvas workers have not stopped; runtime ownership retained")
        for sess in list(self._sessions.values()):
            if sess.pty and not getattr(sess.pty,"durable",False):
                try: sess.pty.close(exit_input=sess.exit_input)
                except (OSError,TerminalError): pass
        if self._machine_host is not None:
            # Keep central databases alive if a physical worker still owns I/O.
            self._machine_host.close()
        if self._task_runtime:
            # Publish final task states before closing the shared registry.
            try:
                for task in self.store.projection_tasks():
                    try:self._task_runtime.project(task)
                    except Exception as exc:self._task_runtime_error=type(exc).__name__
            finally:self._task_runtime.close()
        if self._control is not None:
            self._control.context.close()
            self._control.durable.close()
        self.graph.close()
        self.store.close()
        self.instance_lock.close()
        self._closed=True
