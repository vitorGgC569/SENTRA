"""Conversation execution adapter over Canvas and the single Control Plane.

The protected queue is an execution journal, not a new Run/WorkItem authority.
Only work whose central operation is still QUEUED can be recovered for execution.
Interrupted model submissions remain uncertain until their journal is reconciled.
Reading an UNCERTAIN turn again leaves it UNCERTAIN and does not send it again.
"""
from __future__ import annotations

import hashlib
import os
import queue
from pathlib import Path
import re
import subprocess
import threading
import time
import unicodedata
from contextlib import closing

from sentra_core.conversations import ConversationStore, _encode, _decode
from .owned_process import TaskProcess
from .shell_optional import UNVERIFIED_TURN_MODEL, UNVERIFIED_TURN_REASON
from .shell_web import UnverifiedTurn
from .store import Denied, MODEL_RE

# GPT-6 reasoning and subsequent tool rounds can exceed the former 120/180s
# pair. These are finite wait ceilings, never automatic retries or new sends.
SHELL_PROVIDER_TIMEOUT_SECONDS = 1800
SHELL_EXECUTION_TIMEOUT_SECONDS = 3600
SHELL_TOOL_ROUND_LIMIT = 32
# Attested finals may still be adopted for turns that are in flight or already
# succeeded. UNCERTAIN is not in this set: a later read must not publish it.
_OBSERVABLE_FINAL_STATES = frozenset({
    "RUNNING", "WAITING_EXTERNAL", "CANCEL_REQUESTED", "SUCCEEDED",
})


class CanvasShellRuntime:
    def __init__(self, canvas, control, *, owner):
        self.canvas, self.control, self.owner = canvas, control, owner
        from .shell_optional import OptionalShellServices
        self.optional = OptionalShellServices(self)
        self.conversations = ConversationStore(canvas.state_dir.parent, principal=canvas.store.principal)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._processes = {}
        self._queue = queue.Queue(maxsize=canvas.max_pending_tasks)
        self._conversation_locks = {}
        self._executing_operations = set()
        from .shell_stream import ShellStreamJournal
        self.stream = ShellStreamJournal(control.store, owner, bind_queue=True)
        self.stream_error = None
        self._stream_closed_operations = set()
        from .shell_live import ShellLivePreviews
        self.live = ShellLivePreviews(canvas.state_dir, on_change=self._stream_preview, on_batch=self._stream_previews)
        from .shell_web import ShellWebRuntime
        self.web = ShellWebRuntime(self)
        from .shell_actor import ShellActorService
        self.actors = ShellActorService(self)
        with closing(control.store.connect("shell")) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS canvas_shell_provider_bindings(
                  owner TEXT NOT NULL, project_id TEXT NOT NULL, workspace TEXT NOT NULL,
                  conversation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                  work_item_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL, principal TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS canvas_shell_queue(
                  operation_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                  project_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                  message_id TEXT NOT NULL, protected_input TEXT NOT NULL,
                  state TEXT NOT NULL, created_at REAL NOT NULL, receipt_id TEXT);
            """)
            rows = db.execute("SELECT operation_id,state FROM canvas_shell_queue WHERE owner=?",
                              (owner,)).fetchall()
        for row in rows:
            op = control.durable.operation_status(row["operation_id"], owner)
            if row["state"] == "queued" and op["state"] == "QUEUED":
                self._queue.put_nowait(row["operation_id"])
            elif row["state"] == "running" and op["state"] in {"STARTING", "RUNNING", "WAITING_EXTERNAL"}:
                control.durable.update_operation(op["operation_id"], owner, state="UNCERTAIN",
                    event_type="SHELL_INTERRUPTED_SUBMISSION", progress={"automatic_retry": False})
        self._threads = [threading.Thread(target=self._worker, daemon=True,
            name="sentra-shell-worker-" + str(i)) for i in range(canvas.max_task_workers)]
        for thread in self._threads:
            thread.start()
        self._stream_thread = threading.Thread(target=self._collect_stream, daemon=True,
                                               name="sentra-shell-stream-ingest")
        self._stream_thread.start()

    def _stream_preview(self, record, preview, *, retain_reference=False):
        import sqlite3
        try:
            return self.stream.publish(record["project_id"], record["space_id"], record["conversation_id"], preview,
                                       _retain_reference=retain_reference) is not None
        except (OSError, RuntimeError, ValueError, PermissionError, sqlite3.Error) as exc:
            self.stream_error = type(exc).__name__
            return False

    def _stream_previews(self, observations):
        import sqlite3
        try:
            results = self.stream.publish_many([
                (record["project_id"], record["space_id"], record["conversation_id"], preview)
                for record, preview in observations
            ])
            return [result is not None for result in results]
        except (OSError, RuntimeError, ValueError, PermissionError, sqlite3.Error) as exc:
            self.stream_error = type(exc).__name__
            return [False] * len(observations)

    def _collect_stream(self):
        """One ingestion loop per runtime, independent of windows/subscribers."""
        from .shell_web_preview import web_preview
        import sqlite3
        while not self._stop.is_set():
            try:
                self.stream_error = None
                self.live.pump()
                with closing(self.control.store.connect("shell")) as db:
                    rows = db.execute("SELECT project_id,conversation_id,operation_id,protected_input FROM canvas_shell_queue "
                        "WHERE owner=? AND state='running' ORDER BY created_at DESC", (self.owner,)).fetchall()
                seen_conversations = set()
                for row in rows:
                    if self._stop.is_set():
                        break
                    key = (row["project_id"], row["conversation_id"])
                    if key in seen_conversations:
                        continue
                    seen_conversations.add(key)
                    if row["operation_id"] in self._stream_closed_operations:
                        continue
                    # Native callbacks already persist and fan out their observations.
                    if self.live.has_active(row["project_id"], row["conversation_id"]):
                        continue
                    message = _decode(row["protected_input"])["message"]
                    state = self.control.durable.operation_status(row["operation_id"], self.owner)["state"]
                    if state in {"UNCERTAIN", "FAILED", "CANCELLED"}:
                        prior = self.stream.head(row["project_id"], row["conversation_id"])
                        if prior and prior.get("operation_id") != row["operation_id"]:
                            self._stream_closed_operations.add(row["operation_id"])
                            continue
                        observed = prior or {"content": ""}
                        observed = {**observed, "status": "interrupted", "operation_id": row["operation_id"],
                                    "activity": "Entrega incerta. Não reenvie."}
                        if self._stream_preview(message, observed, retain_reference=bool(prior and prior.get("content_ref"))):
                            self._stream_closed_operations.add(row["operation_id"])
                        continue
                    observed = web_preview(self, row["project_id"], row["conversation_id"], include_full=True)
                    if observed.get("operation_id") not in {None, row["operation_id"]}:
                        continue
                    if observed.get("status") != "idle":
                        self.stream.publish(row["project_id"], message["space_id"], row["conversation_id"], observed)
            except (OSError, RuntimeError, ValueError, PermissionError, sqlite3.Error) as exc:
                # A broken presentation feed must not resend or cancel a producer.
                # Only the class enters diagnostics; content/credentials stay private.
                self.stream_error = type(exc).__name__
            self._stop.wait(.05 if self._processes or self.live.has_active() else .2)

    def _project(self, project_id, owner):
        if owner != self.owner or owner != self.canvas._runtime().owner:
            raise Denied("shell runtime owner mismatch")
        return self.canvas.store.workspace(project_id)

    def _journal_messages(self, conversation_id):
        # The public transcript deliberately omits execution metadata. Read the
        # protected journal under the same principal for exact completion receipts.
        with self.conversations._connect() as db:
            self.conversations._owned(db, conversation_id)
            rows = db.execute("SELECT seq,role,kind,protected_content FROM messages "
                "WHERE conversation_id=? ORDER BY seq", (conversation_id,)).fetchall()
        return [{"seq": row["seq"], "role": row["role"], "kind": row["kind"],
                 "content": _decode(row["protected_content"])} for row in rows]

    def _journal_calls(self, conversation_id):
        with self.conversations._connect() as db:
            self.conversations._owned(db, conversation_id)
            rows = db.execute("SELECT id,kind,operation,state FROM calls "
                "WHERE conversation_id=? ORDER BY created", (conversation_id,)).fetchall()
        return [{"id": row["id"], "kind": row["kind"], "operation": row["operation"],
                 "state": row["state"]} for row in rows]

    def _remember_turn(self, message, dot_id, content):
        from orchestrator.memory import LiveDotSession, build_turn_memory
        journal, calls = [], []
        try:
            journal = self._journal_messages(message["conversation_id"])
            calls = self._journal_calls(message["conversation_id"])
        except Exception:
            journal, calls = [], []
        memory = build_turn_memory(content=content, conversation_id=message["conversation_id"],
            journal=journal, calls=calls)
        root = Path(self._project(message["project_id"], self.owner)["path"]) / ".sentra"
        LiveDotSession(root, self.owner, dot_id, message["conversation_id"]).save_dot(
            plan=memory["plan"], context=memory["context"],
            run_id=message["run_id"], work_item_id=message["work_item_id"],
            operation_id=message["operation_id"])
        return memory

    def _dot_session_view(self, project_id, owner, dot, conversation_id):
        from orchestrator.memory import LiveDotSession
        view = {"present": False, "authorizes_effects": False, "provider_handoff": False, "steps": []}
        root = Path(self._project(project_id, owner)["path"]) / ".sentra"
        try:
            loaded = LiveDotSession(root, owner, dot["dot_id"], conversation_id).load_dot()
        except FileNotFoundError:
            return view
        body = loaded["plan"]["body"]
        view["present"] = True
        view["objective"] = body.get("objective")
        view["steps"] = list(body.get("steps") or [])
        return view

    def _delivery_problem(self, message):
        # Project only known provider errors, never CLI output, tokens or paths.
        journal = self._journal_messages(message["conversation_id"])
        start = next((index for index in range(len(journal) - 1, -1, -1)
                      if journal[index]["role"] == "user" and journal[index]["content"] == message.get("content")), None)
        if start is None:
            return None
        for entry in journal[start + 1:]:
            if entry["role"] == "user":
                break
            if entry["kind"] != "provider_error":
                continue
            content = str(entry["content"])
            if "connector_not_found" in content:
                return "O plugin SENTRA não foi encontrado no ChatGPT. Confira o plugin instalado e o nome configurado em Ambientes e modelos."
            if "model_version_unavailable" in content:
                return "O ChatGPT não confirmou o modelo escolhido para este Dot. A mensagem não foi enviada; confira o modelo em Ambientes e modelos."
            if 'turn deadline exceeded' in content:
                return 'O ChatGPT excedeu o limite de espera antes de confirmar a resposta. A entrega permanece incerta; nenhum reenvio automático foi feito.'
            return "O provedor não confirmou o envio. Consulte a entrega em Ambientes e modelos antes de repetir a mensagem."
        return None

    def voice_availability(self, project_id, owner):
        return self.optional.voice_availability(project_id, owner)

    def attachment_availability(self, project_id, owner):
        return self.optional.attachment_availability(project_id, owner)

    def voice_dispatch(self, project_id, owner, action, payload, request_key):
        return self.optional.voice_dispatch(project_id, owner, action, payload, request_key)

    def attachment_dispatch(self, project_id, owner, action, payload, request_key):
        return self.optional.attachment_dispatch(project_id, owner, action, payload, request_key)

    attachment_register = attachment_dispatch

    def validate_attachments(self, project_id, owner, conversation, refs):
        self.web._configuration()
        return self.optional.validate_attachments(project_id, owner, conversation, refs)

    def message_capabilities(self, project_id, owner, dot, conversation, refs):
        """Declare intent requirements; declarations never confer Grants."""
        self._project(project_id, owner)
        from sentra_runtime.coordinator_admission import COORDINATOR_CAPABILITIES
        from sentra_mcp.services.shell_coordinator import dot_manages_canvas
        capabilities = {cap for kind, cap in COORDINATOR_CAPABILITIES.items() if kind not in {"pause", "resume", "cancel"}} if dot_manages_canvas(dot) else set()
        if self._coordinator_child(project_id, owner):
            capabilities.add("model:invoke")
        from .full_access import source
        if source(self.control, owner, conversation['conversation_id']):
            capabilities.add('model:invoke')
            if self._turn_uses_web(project_id, conversation):
                capabilities.add('web:send')
        if refs:
            capabilities.update({"web:send", "web:attach"})
        if conversation.get('native_generation') == 'image':
            native_config = self.web._configuration()
            if dot['model'] not in native_config['models']:
                raise Denied('O modelo escolhido para este Dot não permite geração de imagens nesta conexão.')
            with self.conversations._connect() as db:
                existing = db.execute('SELECT owner,workspace FROM conversations WHERE id=?',
                    (conversation['conversation_id'],)).fetchone()
            if existing and (existing['owner'] != self.canvas.store.principal or existing['workspace'] != self.canvas.store.workspace(project_id)['path']):
                raise Denied('conversation journal belongs to another workspace')
            if existing and self._journal_messages(conversation['conversation_id']) and not self.web.owns_conversation(project_id, conversation['conversation_id']):
                raise Denied('Use uma nova conversa para criar uma imagem; esta conversa ainda não tem continuidade Web vinculada.')
            capabilities.add('web:send')
        return sorted(capabilities)

    @staticmethod
    def _coordinator_child(project_id, owner):
        from sentra_runtime.effect_boundary import current_effect_context
        context = current_effect_context.get()
        return bool(context is not None and context.receipt.owner == owner
            and context.request.capability_id in {"canvas.coordinator.delegate", "canvas.coordinator.handoff"}
            and context.request.arguments.get("project_id") == project_id)

    def _turn_uses_web(self, project_id, message):
        return bool(message.get("attachments")) or message.get("native_generation") == "image" or self.web.owns_conversation(project_id, message["conversation_id"])

    def _not_submitted_delivery(self, operation_id, work_item_id):
        op = self.control.durable.operation_status(operation_id, self.owner)
        if op["state"] in {"QUEUED", "STARTING", "RUNNING"}:
            self.control.durable.update_operation(operation_id, self.owner, state="FAILED",
                event_type="SHELL_MODEL_NOT_SUBMITTED",
                error={"code": "model_access_unverified", "message": UNVERIFIED_TURN_REASON},
                progress={"automatic_retry": False, "delivery": "not_submitted",
                    "receipt": "access unverified", "model_access_verified": False,
                    "inference_executed": False},
                result={"delivery": "not_submitted", "receipt": "access unverified",
                    "model_access_verified": False, "inference_executed": False, "resent": False})
        return {"status": "not_submitted", "operation_id": operation_id,
            "work_item_id": work_item_id, "receipt_id": None, "receipt": "access unverified",
            "delivery": "not_submitted", "reason": UNVERIFIED_TURN_REASON, "resent": False,
            "automatic_retry": False, "model_access_verified": False, "inference_executed": False}

    def _stop_unverified_web_turn(self, oid, message):
        """Listed Grok access was not submitted. Leave no queued row to rediscover."""
        receipt = self._not_submitted_delivery(oid, message.get("work_item_id"))
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("UPDATE canvas_shell_queue SET state='not_submitted' WHERE operation_id=? AND state IN ('queued','running')", (oid,))
        return receipt

    def _model_grant(self, message, dot):
        from .shell_access import AccessStore
        from .full_access import source
        if AccessStore(self.control, self.owner).raw_profile(message['conversation_id']).get('full_source') and not source(self.control, self.owner, message['conversation_id']):
            raise Denied('full-access delegation was revoked')
        item = self.control.work_item_info(message["work_item_id"], self.owner)
        if message.get("coordinator_child") or "model:invoke" in item.get("required_capabilities", []):
            return self.control.authorization.require(self.owner, principal_type="agent",
                principal_id=dot["agent_id"], capability="model:invoke", scope_type="work_item",
                scope_id=item["work_item_id"], context={"provider": "shell-model"}, local_owner=False)

    @staticmethod
    def _name(display, identity):
        ascii_name = unicodedata.normalize("NFKD", display).encode("ascii", "ignore").decode()
        stem = re.sub(r"[^A-Za-z0-9_-]", "_", ascii_name).strip("_") or "Dot"
        if not stem[0].isalpha():
            stem = "Dot_" + stem
        return stem[:34] + "_" + hashlib.sha256(identity.encode()).hexdigest()[:10]

    def resolve_project(self, project_id, owner):
        workspace = self._project(project_id, owner)
        run = self.canvas._runtime().run(project_id)
        agents = self.canvas.store.list_resources("agents", project_id)
        for agent in agents:
            try:
                known = self.control.durable.agent_info(agent['id'], owner)
            except FileNotFoundError:
                known = None
            # Reading Home/Space is not a heartbeat from an agent. Preserve
            # current pause/state and avoid projecting the entire Run for every
            # known agent on every UI poll. Admission still ensures new bindings.
            if known is None or known['run_id'] != run['run_id'] or (known.get('metadata') or {}).get('workspace_id') != project_id:
                self.control.ensure_agent(run["run_id"], owner, agent_id=agent["id"],
                    role=agent["role"], metadata={"workspace_id": project_id})
        return {"project_id": project_id, "name": workspace["name"], "run_id": run["run_id"],
            "agents": agents, "teams": self.canvas.store.list_resources("teams", project_id),
            "capabilities": ["shell.conversations", "shell.spaces", "shell.dots", "shell.coordinate"]}

    def admit_dot(self, project_id, owner, spec, request_key):
        self._project(project_id, owner)
        name = self._name(spec["name"], spec["dot_id"])
        with self.canvas._lock:
            matches = [a for a in self.canvas.store.list_resources("agents", project_id) if a["name"] == name]
            agent = matches[0] if matches else self.canvas.create_agent(project_id, name,
                spec["model"], spec["role"], start=False, goal=spec.get("instructions") or None)
            if agent["model"] != spec["model"] or agent["role"] != spec["role"]:
                raise ValueError("Dot admission identity collision")
            self.control.ensure_agent(spec["run_id"], owner, agent_id=agent["id"], role=agent["role"],
                metadata={"workspace_id": project_id, "space_id": spec["space_id"], "dot_id": spec["dot_id"]})
        return {"agent_id": agent["id"], "name": spec["name"], "model": agent["model"],
            "role": agent["role"], "status": "available"}

    def update_dot(self, project_id, owner, dot, request_key):
        self._project(project_id, owner)
        agent = self.canvas.store.resource("agents", dot["agent_id"], project_id)
        if not MODEL_RE.fullmatch(dot["model"]):
            raise ValueError("invalid admitted model")
        if dot["model"] != agent["model"]:
            catalog = self.canvas.model_catalog()["models"]
            if catalog and dot["model"] not in catalog:
                raise ValueError("model is not in the authenticated catalog")
            with closing(self.control.store.connect("shell")) as db:
                rows = db.execute("SELECT protected_input FROM canvas_shell_queue WHERE owner=? AND project_id=? "
                    "AND state IN ('queued','running')", (owner, project_id)).fetchall()
            if any(_decode(row["protected_input"])["dot"]["agent_id"] == dot["agent_id"] for row in rows):
                raise ValueError("Aguarde o envio pendente deste Dot antes de trocar o modelo.")
            if agent.get("terminal_id"):
                terminal = self.canvas.store.resource("terminals", agent["terminal_id"], project_id)
                if terminal.get("status") == "running":
                    raise ValueError("Pare o terminal deste Dot antes de trocar o modelo.")
        with self.canvas.store.tx():
            self.canvas.store.db.execute("UPDATE agents SET role=?,model=? WHERE id=? AND workspace_id=?",
                (dot["role"], dot["model"], dot["agent_id"], project_id))
        context = self.canvas.agent_working_context(project_id, dot["agent_id"])
        self.canvas.agent_working_context(project_id, dot["agent_id"], goal=dot.get("instructions", ""),
            expected_revision=context["revision"])
        return self.control.durable.update_agent(dot["agent_id"], owner,
            metadata={"display_name": dot["name"], "shell_revision": dot["revision"],
                "model": dot["model"], "mascot": dot.get("mascot", "blue")})

    def dispatch_message(self, project_id, owner, dot, message, request_key):
        message = dict(message)
        if self._coordinator_child(project_id, owner):
            message["coordinator_child"] = True  # Server-only marker, persisted in protected queue.
        self._project(project_id, owner)
        agent = self.canvas.store.resource("agents", dot["agent_id"], project_id)
        operation = self.control.durable.operation_status(message["operation_id"], owner)
        item = self.control.work_item_info(message["work_item_id"], owner)
        if operation["run_id"] != message["run_id"] or item["run_id"] != message["run_id"] or item["assignee_agent_id"] != agent["id"]:
            raise Denied("conversation authority mismatch")
        if operation["state"] == "UNCERTAIN":
            consulted = self.reconcile_message(project_id, owner, message)
            consulted["resent"] = False
            return consulted
        from .full_access import inherit, prepare_turn
        with self.canvas._lock:
            inherit(self, message, dot)
            prepare_turn(self, message, dot)
        message["live_dot_session"] = self._dot_session_view(
            project_id, owner, dot, message["conversation_id"])
        if not MODEL_RE.fullmatch(agent["model"]):
            raise ValueError("invalid admitted model")
        uses_web = self._turn_uses_web(project_id, message)
        if uses_web and dot.get("model") == UNVERIFIED_TURN_MODEL:
            return self._not_submitted_delivery(operation["operation_id"], item["work_item_id"])
        waiting_approval = False
        required = []
        try:
            self._model_grant(message, dot)
        except PermissionError:
            waiting_approval = True
            required.append("model:invoke")
        if uses_web:
            self.web._configuration()
            try:
                self.web.grants(message, dot)
            except PermissionError:
                waiting_approval = True
                required.extend(["web:send", "web:attach"] if message.get("attachments") else ["web:send"])
        with self._lock, closing(self.control.store.connect("shell")) as db, db:
            old = db.execute("SELECT * FROM canvas_shell_queue WHERE operation_id=?",
                             (operation["operation_id"],)).fetchone()
            if old:
                return self.reconcile_message(project_id, owner, message)
            if self._stop.is_set() or self._queue.full():
                raise RuntimeError("conversation queue unavailable")
            payload = {"dot": dot, "message": message, "request_key": request_key}
            db.execute("INSERT INTO canvas_shell_queue VALUES(?,?,?,?,?,?,?,?,?)",
                (operation["operation_id"], owner, project_id, message["conversation_id"],
                 message["message_id"], _encode(payload), "queued", time.time(), None))
        self._queue.put_nowait(operation["operation_id"])
        return {"status": "waiting_approval" if waiting_approval else "queued",
            "operation_id": operation["operation_id"], "work_item_id": item["work_item_id"], "receipt_id": None,
            **({"required_capabilities": sorted(set(required)),
                "grant_created": False} if waiting_approval else {})}

    def _worker(self):
        while not self._stop.is_set():
            try:
                oid = self._queue.get(timeout=.5)
            except queue.Empty:
                with closing(self.control.store.connect("shell")) as db:
                    rows = db.execute("SELECT operation_id FROM canvas_shell_queue WHERE owner=? AND state='queued' ORDER BY created_at LIMIT ?",
                        (self.owner, self.canvas.max_pending_tasks)).fetchall()
                for row in rows:
                    try:
                        self._queue.put_nowait(row["operation_id"])
                    except queue.Full:
                        break
                continue
            try:
                self._execute(oid)
            except UnverifiedTurn:
                with closing(self.control.store.connect("shell")) as db:
                    row = db.execute("SELECT protected_input FROM canvas_shell_queue WHERE operation_id=? AND owner=?",
                        (oid, self.owner)).fetchone()
                if row is not None:
                    self._stop_unverified_web_turn(oid, _decode(row["protected_input"])["message"])
            except Exception as worker_error:
                # Preserve authoritative failure/uncertainty; never submit again.
                try:
                    op = self.control.durable.operation_status(oid, self.owner)
                    if op["state"] in {"STARTING", "RUNNING", "WAITING_EXTERNAL"}:
                        import traceback
                        frames=[{'module':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
                            for frame in traceback.extract_tb(worker_error.__traceback__)[-8:]]
                        self.control.durable.update_operation(oid, self.owner, state="UNCERTAIN",
                            event_type="SHELL_WORKER_FAILED", progress={"automatic_retry": False},
                            error={'code':'shell_worker_failed','message':'Falha interna no turno; consulte o diagnóstico, sem reenviar.',
                                'exception_type':type(worker_error).__name__,'frames':frames})
                except Exception:
                    pass
            finally:
                self._queue.task_done()

    def _execute(self, oid):
        # Idle discovery may enqueue the same durable queued row while its
        # first worker is still checking admission. Duplicates must not occupy
        # every worker waiting for that conversation's long-running turn.
        with self._lock:
            if oid in self._executing_operations:
                return
            self._executing_operations.add(oid)
        try:
            self._execute_reserved(oid)
        finally:
            with self._lock:
                self._executing_operations.discard(oid)

    def _execute_reserved(self, oid):
        with closing(self.control.store.connect("shell")) as db:
            row = db.execute("SELECT * FROM canvas_shell_queue WHERE operation_id=? AND owner=?",
                             (oid, self.owner)).fetchone()
        if row is None or row["state"] != "queued":
            return
        data = _decode(row["protected_input"])
        message, dot = data["message"], data["dot"]
        with self._lock:
            lock = self._conversation_locks.setdefault(message["conversation_id"], threading.Lock())
        # A distinct queued turn in the same conversation also must not hold a
        # worker slot while its predecessor generates. Its row stays queued;
        # the existing idle discovery will revisit it after the lock is free.
        if not lock.acquire(blocking=False):
            return
        try:
            with closing(self.control.store.connect("shell")) as db:
                current = db.execute("SELECT state FROM canvas_shell_queue WHERE operation_id=?", (oid,)).fetchone()
            if current is None or current["state"] != "queued":
                return
            self._execute_locked(oid, message, dot)
        finally:
            lock.release()

    def _execute_locked(self, oid, message, dot):
        current_operation = self.control.durable.operation_status(oid, self.owner)
        if current_operation["state"] != "QUEUED":
            return
        from .full_access import prepare_turn
        prepare_turn(self, message, dot)
        run = self.control.durable.run_status(message["run_id"], self.owner, include_details=False)
        if run["state"] in {"PAUSED", "CREATED", "BLOCKED", "RECOVERING"}:
            if not self._stop.wait(.5):
                try:
                    self._queue.put_nowait(oid)
                except queue.Full:
                    pass  # The durable queued row is rediscovered by an idle worker.
            return
        if run["state"] != "RUNNING":
            self.control.durable.request_cancel(oid, self.owner, side_effect_may_have_started=False)
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("UPDATE canvas_shell_queue SET state='cancelled' WHERE operation_id=?", (oid,))
            return
        from .full_access import prepare_resources
        prepare_resources(self, message, dot)
        uses_web = self._turn_uses_web(message["project_id"], message)
        if uses_web and dot.get("model") == UNVERIFIED_TURN_MODEL:
            self._stop_unverified_web_turn(oid, message)
            return
        try:
            self._model_grant(message, dot)
        except PermissionError:
            self._stop.wait(.5)
            return
        if uses_web:
            try:
                self.web.grants(message, dot)
            except PermissionError:
                self._stop.wait(.5)
                return  # Discovery retries admission only; it has not staged or sent anything.
        item = self.control.work_item_info(message["work_item_id"], self.owner)
        if item["state"] == "PENDING":
            self.control.transition_work_item(item["work_item_id"], self.owner, "QUEUED")
        self.control.start_work_item_execution(item["work_item_id"], self.owner,
            run_id=message["run_id"], agent_id=dot["agent_id"])
        with closing(self.control.store.connect("shell")) as db, db:
            changed = db.execute("UPDATE canvas_shell_queue SET state='running' WHERE operation_id=? AND state='queued'", (oid,)).rowcount
            if changed != 1:
                return
            # Bind the current admitted turn only while holding its conversation lock.
            workspace = self._project(message["project_id"], self.owner)
            db.execute("INSERT INTO canvas_shell_provider_bindings VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET run_id=excluded.run_id,"
                "work_item_id=excluded.work_item_id,operation_id=excluded.operation_id,agent_id=excluded.agent_id",
                (self.owner, message["project_id"], workspace["path"], message["conversation_id"], message["run_id"],
                 message["work_item_id"], oid, dot["agent_id"], self.canvas.store.principal))
        self.control.durable.update_operation(oid, self.owner, state="STARTING", event_type="SHELL_MODEL_STARTING")
        workspace = self._project(message["project_id"], self.owner)
        sid = message["conversation_id"]
        self.conversations.open(workspace["path"], session_id=sid)
        if uses_web:
            if dot.get("model") == UNVERIFIED_TURN_MODEL:
                self._stop_unverified_web_turn(oid, message)
                return
            result = self.web.execute(message, dot)
            if result is None:
                self.control.durable.update_operation(oid, self.owner, state="UNCERTAIN",
                    event_type="SHELL_BINARY_RELAY_UNCONFIRMED", progress={"automatic_retry": False})
                return
            self._publish_answer(message, result["content"], result["receipt_id"],
                evidence={key: value for key, value in result.items() if key != "content"})
            return
        if self._coordinator_uses_dot_vm(message, dot):
            self._execute_coordinator_in_guest(oid, message, dot)
            return
        previous_sequence = max((m["seq"] for m in self._journal_messages(sid)), default=0)
        self.conversations.set_model_preferences(sid, dot["model"], dot.get("effort"), workspace=workspace["path"])
        command = self.canvas._cli_command(["--prompt-stdin", "--workspace", workspace["path"],
            "--model", dot["model"], "--no-auto-start", "--timeout", str(SHELL_PROVIDER_TIMEOUT_SECONDS),
            "--max-tool-rounds", str(SHELL_TOOL_ROUND_LIMIT),
            "--state-dir", str(self.canvas.state_dir.parent), "--resume", sid])
        from sentra_runtime.provider_authority import ENVIRONMENT_KEY, prepare_provider_binding
        environment = {k: v for k, v in os.environ.items()
            if not k.startswith(("MAESTRI_", "SENTRA_CANVAS_AGENT_"))
            and k not in {ENVIRONMENT_KEY, "SENTRA_CANVAS_TOKEN", "SENTRA_CANVAS_PORT"}}
        binding = prepare_provider_binding(self.control, state_root=self.canvas.state_dir.parent,
            owner=self.owner, principal=self.canvas.store.principal, conversation_id=sid,
            project_id=message["project_id"], run_id=message["run_id"],
            work_item_id=message["work_item_id"], operation_id=oid)
        environment.update(binding["environment"])
        live_record = self.live.begin(project_id=message["project_id"],
            conversation_id=message["conversation_id"], operation_id=oid, space_id=message["space_id"])
        environment.update(self.live.environment(live_record))
        deadline = time.monotonic() + SHELL_EXECUTION_TIMEOUT_SECONDS
        actor_token = None
        try:
            with self.canvas._lock:
                self._model_grant(message, dot)
                if self.canvas._agent_port is not None:
                    actor_token = self.actors.register(message, dot, deadline=deadline)
                    environment.update(SENTRA_CANVAS_AGENT_TOKEN=actor_token,
                        SENTRA_CANVAS_AGENT_PORT=str(self.canvas._agent_port), SENTRA_CANVAS_AGENT_SCOPE="shell")
                from .task_workspace import for_work_item
                assigned=for_work_item(self.control,self.owner,message['work_item_id'],dot['agent_id'])
                process = TaskProcess(command, cwd=assigned['path'] if assigned else workspace['path'], env=environment,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._processes[oid] = process
        except BaseException:
            self.live.close(live_record)
            if actor_token is not None:
                self.actors.revoke(actor_token)
            raise
        pending = message["content"].encode("utf-8")
        try:
            self.control.durable.update_operation(oid, self.owner, state="RUNNING", event_type="SHELL_MODEL_RUNNING")
            while True:
                try:
                    input_value, pending = pending, None
                    process.communicate(input=input_value, timeout=.25)
                    self.live.update(live_record)
                    break
                except subprocess.TimeoutExpired:
                    self.live.update(live_record)
                    active = self.control.durable.operation_status(oid, self.owner)
                    current = self.control.durable.run_status(message["run_id"], self.owner, include_details=False)
                    grant_live = True
                    try:
                        self._model_grant(message, dot)
                    except PermissionError:
                        grant_live = False
                    actor = self.control.durable.agent_info(dot["agent_id"], self.owner)
                    work = self.control.work_item_info(message["work_item_id"], self.owner)
                    if self._stop.is_set() or active["state"] == "CANCEL_REQUESTED" or current["state"] != "RUNNING" or time.monotonic() > deadline or not grant_live or actor["desired_state"] == "WAITING" or work["assignee_agent_id"] != dot["agent_id"]:
                        process.terminate_tree()
                        process.communicate(timeout=10)
                        self.control.durable.update_operation(oid, self.owner, state="UNCERTAIN",
                            event_type="SHELL_MODEL_INTERRUPTED", progress={"automatic_retry": False})
                        return
            status = self.conversations.status(sid)
            messages = self._journal_messages(sid)
            answers = [m for m in messages if m["role"] == "assistant" and m["seq"] > previous_sequence
                       and m.get("kind", "message") != "provider_error"]
            if process.returncode != 0 or status["uncertain_calls"] or not answers:
                self.control.durable.update_operation(oid, self.owner, state="UNCERTAIN",
                    event_type="SHELL_MODEL_RESULT_UNCONFIRMED", progress={"journal_available": True, "automatic_retry": False},
                    error={"code": "shell_provider_unconfirmed", "message": self._delivery_problem(message) or "O provedor não confirmou uma resposta."})
                return
            answer = answers[-1]
            content = answer["content"]
            receipt = "conversation:" + sid + ":" + str(answer["seq"])
            timing = self.live.view(message['project_id'], sid).get('timings_ms', {})
            timing['confirmed'] = round((time.monotonic() - live_record['started']) * 1000)
            self._publish_answer(message, content, receipt, evidence={"protected_journal": True, "timings_ms": timing})
        finally:
            self.live.close(live_record)
            if actor_token is not None:
                self.actors.revoke(actor_token)
            if process.poll() is None:
                process.terminate_tree()
            with self._lock:
                self._processes.pop(oid, None)

    def _coordinator_vm_record(self, message, dot):
        """VM row for this Dot's family. No row keeps the native host CLI, including Codex."""
        from .shell_dot_canvas import canvas_root, _root_vm_record
        if not isinstance(message, dict) or not isinstance(dot, dict):
            return None
        project_id = message.get("project_id")
        dot_id = dot.get("dot_id")
        if not isinstance(project_id, str) or not isinstance(dot_id, str):
            return None
        entity = dot
        space_id = message.get("space_id") if isinstance(message.get("space_id"), str) else None
        try:
            with closing(self.control.store.connect("shell")) as db:
                loaded = self.control.shell._entity(
                    db, self.owner, project_id, "dot", dot_id, space_id=space_id)
            if isinstance(loaded, dict):
                entity = loaded
        except Exception:
            entity = dot
        try:
            root = canvas_root(entity)
        except Exception:
            return None
        if not isinstance(root, str) or not root:
            return None
        return _root_vm_record(self.canvas, project_id, root)

    def _coordinator_uses_dot_vm(self, message, dot):
        from .shell_dot_canvas import _vm_id
        return _vm_id(self._coordinator_vm_record(message, dot)) is not None

    def _execute_coordinator_in_guest(self, oid, message, dot):
        """Run the coordinator inside the Dot VM. Never start it on the host."""
        from sentra_executors.guest_execution import is_proven_guest_executor
        from .shell_dot_canvas import (
            _dot_home, _guest_terminal_executor, _imported_guest_workspace, _vm_id,
        )
        record = self._coordinator_vm_record(message, dot) or {}
        vm_id = _vm_id(record)
        username = record.get("username") if isinstance(record.get("username"), str) else record.get("guest_username")
        password = record.get("password") if isinstance(record.get("password"), str) else record.get("guest_password")

        def uncertain(reason):
            if isinstance(password, str) and password and password in reason:
                reason = "coordinator guest did not confirm a result"
            self.control.durable.update_operation(oid, self.owner, state="UNCERTAIN",
                event_type="SHELL_COORDINATOR_GUEST_UNCONFIRMED",
                progress={"automatic_retry": False, "execution_surface": "blocked",
                    "host_subprocess": False, "vm_id": vm_id},
                error={"code": "coordinator_not_in_guest", "message": reason})

        family = record.get("os_family") if isinstance(record.get("os_family"), str) else "linux"
        family = family.strip().lower() if family.strip().lower() in {"linux", "windows"} else "linux"
        model = dot.get("model") if isinstance(dot, dict) else None
        effort = dot.get("effort") if isinstance(dot, dict) else None
        prompt = message.get("content") if isinstance(message, dict) else None
        if model not in {"sentra/chatgpt-web/gpt-6", "sentra/grok/grok-4.7"}:
            uncertain("coordinator model is not admitted inside the Dot VM")
            return
        if effort not in {None, "high"}:
            uncertain("coordinator effort is not admitted inside the Dot VM")
            return
        if not isinstance(prompt, str) or not prompt.strip() or "\0" in prompt:
            uncertain("coordinator prompt is not usable inside the Dot VM")
            return
        if not (isinstance(vm_id, str) and isinstance(username, str) and username.strip()
                and "\0" not in username and isinstance(password, str) and password
                and "\0" not in password and "\n" not in password and "\r" not in password):
            uncertain("Dot VM registry cannot prove the coordinator guest")
            return
        try:
            executor = _guest_terminal_executor(record)
        except Exception:
            uncertain("Dot VM registry cannot prove the coordinator guest")
            return
        if not is_proven_guest_executor(executor):
            uncertain("Dot VM registry cannot prove the coordinator guest")
            return
        guest_workspace = _imported_guest_workspace(record, family) or _dot_home(record, family)
        request = {
            "placement": "guest",
            "tool": "sentra-cli",
            "prompt": prompt,
            "guest_workspace": guest_workspace,
            "model": model,
            "effort": "high",
            "timeout_s": 120,
            "vm_id": vm_id,
        }
        try:
            produced = executor.execute(request)
        except Exception:
            uncertain("coordinator guest did not confirm a result")
            return
        stdout = produced.get("stdout") if isinstance(produced, dict) else None
        exit_code = produced.get("exit_code") if isinstance(produced, dict) else None
        proven = (
            isinstance(produced, dict)
            and produced.get("execution_surface") == "guest"
            and produced.get("host_subprocess") is not True
            and produced.get("claims_guest_execution") is True
            and produced.get("execution_uncertain") is not True
            and type(exit_code) is int and exit_code == 0
            and isinstance(stdout, str)
            and bool(stdout.strip())
            and "\0" not in stdout
            and password not in stdout
        )
        if not proven:
            uncertain("coordinator guest did not confirm a result")
            return
        receipt = "guest:" + vm_id + ":" + oid
        self.control.durable.update_operation(oid, self.owner, state="RUNNING",
            event_type="SHELL_COORDINATOR_GUEST_RUNNING")
        self._publish_answer(message, stdout, receipt, evidence={
            "execution_surface": "guest",
            "host_subprocess": False,
            "protected_journal": False,
            "vm_id": vm_id,
            "claims_guest_execution": True,
        })

    def _publish_answer(self, message, content, receipt, *, evidence):
        oid = message["operation_id"]
        assistant_id = 'assistant-' + hashlib.sha256(oid.encode()).hexdigest()[:32]
        with closing(self.control.store.connect('shell')) as db:
            row = db.execute('SELECT protected_input FROM canvas_shell_queue WHERE owner=? AND operation_id=?',
                (self.owner, oid)).fetchone()
        from .shell_generated_media import ShellGeneratedMedia
        original = _decode(row['protected_input']) if row else None
        assets = ShellGeneratedMedia(self).publish(message, original['dot'], assistant_id) if original else []
        from .task_verification import confirm_for_publish
        verification=confirm_for_publish(self,message)
        self.control.durable.update_operation(oid, self.owner, state="SUCCEEDED",
            event_type="SHELL_MODEL_VERIFIED_FINAL", result={**evidence, "receipt_id": receipt, 'generated_assets': assets,
                **({'task_verification':verification} if verification else {}),
                "content_sha256": hashlib.sha256(content.encode()).hexdigest()})
        if original and isinstance(content, str) and content.strip():
            self._remember_turn(message, original["dot"]["dot_id"], content)
        self.control.shell.record_runtime_message(self.owner, project_id=message["project_id"],
            space_id=message["space_id"], conversation_id=message["conversation_id"],
            message_id=assistant_id, content=content,
            revision=1, receipt_id=receipt, operation_id=oid)
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("UPDATE canvas_shell_queue SET state='completed',receipt_id=? WHERE operation_id=?", (receipt, oid))
        self.control.shell.reconcile_message(self.owner, project_id=message["project_id"], message_id=message["message_id"])
        self._stream_preview(message, {
            "status": "committed", "activity": "Salvo", "content": content,
            "operation_id": oid,
            "message_id": assistant_id, "receipt_id": receipt,
        })
        from sentra_runtime.dot_tool_dispatch import retain_coordinator_turn
        retain_coordinator_turn(
            self.control, self.owner, project_id=message["project_id"],
            coordinator_work_item_id=message["work_item_id"], journal_receipt=receipt,
            reviewer_agent_id=message.get("agent_id"),
        )

    def reconcile_message(self, project_id, owner, message):
        self._project(project_id, owner)
        op = self.control.durable.operation_status(message["operation_id"], owner)
        if (op.get("progress") or {}).get("delivery") == "not_submitted":
            receipt = self._not_submitted_delivery(op["operation_id"], message.get("work_item_id"))
            receipt["resent"] = False
            return receipt
        with closing(self.control.store.connect("shell")) as db:
            row = db.execute("SELECT protected_input,state FROM canvas_shell_queue WHERE owner=? AND operation_id=?",
                (owner, message["operation_id"])).fetchone()
        if row and row["state"] != "completed":
            queued = _decode(row["protected_input"])
            original, dot = queued["message"], queued["dot"]
            if op["state"] == "QUEUED":
                try:
                    self._model_grant(original, dot)
                except PermissionError:
                    return {"status": "waiting_approval", "operation_id": op["operation_id"],
                        "work_item_id": original["work_item_id"], "receipt_id": None,
                        "required_capabilities": ["model:invoke"], "grant_created": False}
            if original.get("attachments") or original.get('native_generation') == 'image' or self.web.owns_conversation(project_id, original["conversation_id"]):
                if op["state"] == "QUEUED":
                    try:
                        self.web.grants(original, dot)
                    except PermissionError:
                        return {"status": "waiting_approval", "operation_id": op["operation_id"], "receipt_id": None,
                            "work_item_id": original["work_item_id"], "grant_created": False}
                elif op["state"] in _OBSERVABLE_FINAL_STATES and self.web.availability()["model_delivery_available"]:
                    final = self.web.observe(original, dot)
                    if final is not None:
                        self._publish_answer(original, final["content"], final["receipt_id"],
                            evidence={key: value for key, value in final.items() if key != "content"})
                        op = self.control.durable.operation_status(original["operation_id"], owner)
        receipt = (op.get("result") or {}).get("receipt_id")
        state = ("dispatched" if op["state"] == "SUCCEEDED" and receipt else
                 "queued" if op["state"] == "QUEUED" else
                 "running" if op["state"] in {"STARTING", "RUNNING", "WAITING_EXTERNAL"} else
                 "uncertain")
        reason = (op.get("error") or {}).get("message")
        if state == "uncertain" and row:
            reason = self._delivery_problem(_decode(row["protected_input"])["message"]) or reason
        result = {"status": state, "operation_id": op["operation_id"], "receipt_id": receipt,
                **({"reason": reason} if state == "uncertain" and reason else {})}
        if state == "uncertain":
            result["resent"] = False
        return result

    def recover_completed(self):
        """Publish already committed journal receipts after a crash; never call a model."""
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT * FROM canvas_shell_queue WHERE owner=? AND state='running'",
                (self.owner,)).fetchall()
        for row in rows:
            op = self.control.durable.operation_status(row["operation_id"], self.owner)
            result = op.get("result") or {}
            data = _decode(row["protected_input"])
            message = data["message"]
            if (message.get("attachments") or message.get('native_generation') == 'image' or result.get("web_attested_final")) and self.web.availability()["model_delivery_available"]:
                if op["state"] in _OBSERVABLE_FINAL_STATES:
                    final = self.web.observe(message, data["dot"])
                    if final is not None:
                        self._publish_answer(message, final["content"], final["receipt_id"],
                            evidence={key: value for key, value in final.items() if key != "content"})
                continue
            if op["state"] != "SUCCEEDED" or not result.get("protected_journal"):
                continue
            sid = message["conversation_id"]
            receipt = result.get("receipt_id", "")
            prefix = "conversation:" + sid + ":"
            if not receipt.startswith(prefix) or not receipt[len(prefix):].isdigit():
                raise Denied("committed conversation receipt has invalid scope")
            seq = int(receipt[len(prefix):])
            answer = next((m for m in self._journal_messages(sid) if m["seq"] == seq
                and m["role"] == "assistant" and m["kind"] != "provider_error"), None)
            if answer is None or hashlib.sha256(answer["content"].encode()).hexdigest() != result.get("content_sha256"):
                raise Denied("committed conversation journal differs from its receipt")
            self.control.shell.record_runtime_message(self.owner, project_id=message["project_id"],
                space_id=message["space_id"], conversation_id=sid,
                message_id="assistant-" + hashlib.sha256(row["operation_id"].encode()).hexdigest()[:32],
                content=answer["content"], revision=1, receipt_id=receipt, operation_id=row["operation_id"])
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("UPDATE canvas_shell_queue SET state='completed',receipt_id=? WHERE operation_id=?",
                    (receipt, row["operation_id"]))
            self.control.shell.reconcile_message(self.owner, project_id=message["project_id"], message_id=message["message_id"])

    def _node(self, project_id, agent_id):
        self.canvas.store.resource("agents", agent_id, project_id)
        graph = self.canvas.graph_detail(project_id)
        return next(n for n in graph["nodes"] if n["kind"] == "agent" and n["resource_id"] == agent_id)

    def coordinate(self, project_id, owner, intent, request_key):
        self._project(project_id, owner)
        kind = intent["kind"]
        if kind in {"pause", "resume", "cancel"}:
            result = self.canvas.run_control(project_id, kind)
        elif kind == "create_team":
            result = self.canvas.create_team(project_id, self._name(intent["name"], request_key),
                intent["coordinator_agent_id"], intent["worker_agent_ids"])
        elif kind == "connect":
            source, target = (self._node(project_id, intent[field])["id"] for field in ("source_agent_id", "target_agent_id"))
            result = self.canvas.graph_link(project_id, source, target)
        elif kind == "delegate":
            result = self.canvas.delegate(project_id, intent["canvas_team_id"], intent["agent_id"],
                intent["objective"], request_key, provider="sentra-cli", approved=True)
        elif kind == "handoff":
            source, target = (self._node(project_id, intent[field])["id"] for field in ("source_agent_id", "target_agent_id"))
            content = re.sub(r"[\x00-\x1f\x7f]", " ", intent["content"])
            result = self.canvas.handoff(project_id, source, target, content, approved=True, request_key=request_key)
        elif kind == "reassign":
            result = self.control.reassign_work_item(intent["target_work_item_id"], owner, agent_id=intent["agent_id"])
        else:
            raise ValueError("unsupported coordination intent")
        return {"status": "queued" if kind == "delegate" else "applied", "result": result,
            "receipt_id": result.get("id") or result.get("work_item_id") or result.get("run_id")}

    def close(self):
        self._stop.set()
        self.stream.close()
        self._stream_thread.join(timeout=5)
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            if process.poll() is None:
                process.terminate_tree()
        deadline = time.monotonic() + 20
        for thread in self._threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self._threads):
            raise RuntimeError("conversation workers still own runtime resources")
        self.live.close_all()
        self.web.close()
