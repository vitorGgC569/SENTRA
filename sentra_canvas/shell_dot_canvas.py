"""Dot-scoped ConPTY tools and task projections. No implicit provider authority."""
from contextlib import closing
from pathlib import Path
import re
import threading
import uuid

from sentra_core.conversations import _decode
from .adapters import catalog as tool_catalog, cli_argv
from .dot_tool_receipts import (reserve as reserve_delivery, sent as delivery_sent,
    uncertain as delivery_uncertain, deliveries as tool_deliveries,
    terminal_lost as delivery_terminal_lost)
from .shell_requests import ShellHostRequests
from .store import Denied

DOT_CANVAS_ACTIONS = frozenset({
    "dot_canvas_get", "dot_canvas_move", "dot_canvas_link", "dot_canvas_unlink",
    "dot_canvas_terminal", "dot_canvas_terminal_close", "dot_canvas_handoff",
    "dot_canvas_task_submit", "dot_canvas_task_cancel",
})
TOOLS = frozenset({"sentra-cli", "codex", "opencode", "grok"})
SENTRA_MODEL = "sentra/chatgpt-web/gpt-6"
GROK_MODEL = "grok-4.7"


def canvas_root(dot):
    return dot.get("canvas_root_dot_id") or dot["dot_id"]


def dots_for_root(control, owner, project_id, dot_id, space_id=None):
    with closing(control.store.connect("shell")) as db:
        dot = control.shell._entity(db, owner, project_id, "dot", dot_id, space_id=space_id)
        rows = db.execute(
            "SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND kind='dot' AND space_id=?",
            (owner, project_id, dot["space_id"]),
        ).fetchall()
    root = canvas_root(dot)
    return root, [value for value in (_decode(row["body"]) for row in rows)
                  if canvas_root(value) == root]


def _bindings(control, owner, project_id, space_id):
    with closing(control.store.connect("shell")) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS canvas_dot_tool_sessions(
            owner TEXT NOT NULL, project_id TEXT NOT NULL, space_id TEXT NOT NULL,
            member_dot_id TEXT NOT NULL, tool TEXT NOT NULL, terminal_id TEXT NOT NULL,
            PRIMARY KEY(owner, project_id, space_id, member_dot_id, tool))""")
        return [dict(row) for row in db.execute(
            "SELECT member_dot_id,tool,terminal_id FROM canvas_dot_tool_sessions "
            "WHERE owner=? AND project_id=? AND space_id=?",
            (owner, project_id, space_id),
        )]


def _owned_live(canvas, terminal):
    if not terminal:
        return False
    session = canvas._sessions.get(terminal["id"])
    return bool(session and session.pty and session.pty.poll() is None)


class GuestDotTerminal:
    """Line-oriented guest CLI channel with real Canvas output, not a host PTY.

    A visible terminal is only an attached transport, never proof that a model
    answered. Every submitted line is executed through the bound guestcontrol
    executor; a partial keystroke must never trigger a VM operation.
    """

    execution_surface = "guest"
    host_subprocess = False

    def __init__(self, executor, tool, os_family, guest_workspace=None, on_output=None, submit=None):
        self._executor = executor
        self._submit = submit if submit is not None else executor.execute
        self.tool = tool
        self.os_family = os_family if os_family in {"linux", "windows"} else "linux"
        self.guest_workspace = guest_workspace or (
            r"C:\Users\sentra" if self.os_family == "windows" else "/home/sentra")
        self._on_output = on_output
        self._lock = threading.RLock()
        self._pending = ""
        self.writes = []
        self._closed = False

    def _emit(self, value):
        if self._on_output is not None and value:
            self._on_output(value.encode("utf-8", "replace"))

    def poll(self):
        return 0 if self._closed else None

    def close(self, exit_input=None):
        with self._lock:
            self._closed = True
            self._pending = ""

    def resize(self, cols, rows):
        """The guest is a bounded one-shot CLI, not a resizable ConPTY."""
        if not 20 <= int(cols) <= 500 or not 5 <= int(rows) <= 200:
            raise ValueError("invalid terminal size")

    def _execute_line(self, text):
        request = {
            "placement": "guest",
            "tool": self.tool,
            "prompt": text,
            "guest_workspace": self.guest_workspace,
            "timeout_s": 120,
        }
        if self.tool == "sentra-cli":
            request["model"] = SENTRA_MODEL
            request["effort"] = "high"
        elif self.tool == "opencode":
            request["model"] = "opencode/muse-spark-1.3-contributor-free#high"
            request["effort"] = "high"
        try:
            produced = self._submit(request)
        except BaseException:
            self._emit("[VM] Falha ou execução não confirmada. Não reenviar automaticamente.\r\n")
            raise
        exit_code = produced.get("exit_code") if isinstance(produced, dict) else None
        valid = (isinstance(produced, dict)
                 and produced.get("execution_surface") == "guest"
                 and produced.get("host_subprocess") is not True
                 and produced.get("claims_guest_execution") is True
                 and produced.get("execution_uncertain") is not True
                 and type(exit_code) is int and exit_code == 0)
        if isinstance(produced, dict) and produced.get("execution_surface") == "guest":
            for key in ("stdout", "stderr"):
                value = produced.get(key)
                if isinstance(value, str) and value:
                    # The durable transcript is bounded, as is the frontend.
                    if len(value) > 131072:
                        value = value[:131072] + "\r\n[VM] Saída truncada; consulte o recibo.\r\n"
                    self._emit(value.rstrip("\r\n") + "\r\n")
        if not valid:
            self._emit("[VM] Resultado não confirmado no guest; não reenviar automaticamente.\r\n")
            raise RuntimeError("guest terminal did not stay in the VM")
        self.writes.append(text)

    def write(self, data):
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        if len(text) > 4096:
            raise ValueError("guest terminal input too large")
        with self._lock:
            if self._closed:
                raise RuntimeError("guest terminal is closed")
            echo = []
            for char in text:
                if char in "\r\n":
                    if not self._pending:
                        continue
                    prompt, self._pending = self._pending.strip(), ""
                    echo.append("\r\n")
                    self._emit("".join(echo))
                    echo.clear()
                    if prompt:
                        self._execute_line(prompt)
                elif char in "\b\x7f":
                    if self._pending:
                        self._pending = self._pending[:-1]
                        echo.append("\b \b")
                elif ord(char) >= 32:
                    if len(self._pending) >= 4000:
                        raise ValueError("guest prompt exceeds 4000 characters")
                    self._pending += char
                    echo.append(char)
            self._emit("".join(echo))


def _root_vm_record(canvas, project_id, root_dot_id):
    """Dot VM row, or None when this canvas has no registry."""
    try:
        control = canvas._shell_service()
        owner = canvas._runtime().owner
        from .shell_dot_vm import VmStore
        return VmStore(control, owner).get(project_id, root_dot_id)
    except Exception:
        return None


def _vm_id(record):
    if not isinstance(record, dict):
        return None
    vm_id = record.get("vm_id")
    if isinstance(vm_id, str) and vm_id.strip() and vm_id == vm_id.strip() and "\0" not in vm_id and len(vm_id) <= 128:
        return vm_id
    return None


def _guest_terminal_executor(record):
    from sentra_executors.guest_execution import resolve_guest_executor
    username = record.get("username") if isinstance(record.get("username"), str) else record.get("guest_username")
    password = record.get("password") if isinstance(record.get("password"), str) else record.get("guest_password")
    family = record.get("os_family") if isinstance(record.get("os_family"), str) else "linux"
    return resolve_guest_executor(
        vm_id=record.get("vm_id"),
        username=username,
        password=password,
        os_family=family,
        client=record.get("virtualbox_client"),
    )


def _dot_account(record):
    username = None
    if isinstance(record, dict):
        username = record.get("username") if isinstance(record.get("username"), str) else record.get("guest_username")
    if (not isinstance(username, str) or ".." in username
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}", username.strip())):
        return "sentra"
    return username.strip()


def _dot_home(record, os_family):
    account = _dot_account(record)
    if os_family == "windows":
        return "C:\\Users\\" + account
    return "/home/" + account


def _imported_guest_workspace(record, os_family):
    """Use the imported guest folder only when that import receipt succeeded."""
    imported = record.get("last_project_import") if isinstance(record, dict) else None
    if not isinstance(imported, dict) or imported.get("receipt_state") != "SUCCEEDED":
        return None
    path = imported.get("guest_path")
    if not isinstance(path, str):
        return None
    path = path.strip()
    if (not path or "\0" in path or len(path) > 240
            or any(char in path for char in "\n\r'\"$;`|&<>")
            or any(part == ".." for part in path.replace("\\", "/").split("/"))):
        return None
    host_folder = imported.get("host_folder")
    if isinstance(host_folder, str) and host_folder.strip() and path == host_folder.strip():
        return None
    home = _dot_home(record, "windows" if os_family == "windows" else "linux")
    if os_family == "windows":
        if not path.startswith(home + "\\") or "/" in path:
            return None
    elif not path.startswith(home + "/") or "\\" in path:
        return None
    return path


def _guest_channel(canvas, terminal):
    if not terminal:
        return None
    session = canvas._sessions.get(terminal["id"])
    pty = getattr(session, "pty", None) if session else None
    if getattr(pty, "execution_surface", None) == "guest" and pty.poll() is None:
        return pty
    return None


def _allocate_guest_terminal(canvas, project_id, name, shell):
    creator = getattr(canvas, "create_guest_terminal", None)
    if callable(creator):
        return creator(project_id, name, shell)
    row = canvas.store.create_terminal(project_id, name, shell)
    canvas.store.terminal_state(project_id, row["id"], "running", None)
    return {**row, "status": "running", "pid": None}


def _bind_tool_terminal(control, owner, project_id, space_id, member_dot_id, tool, terminal_id):
    with closing(control.store.connect("shell")) as db, db:
        db.execute("INSERT INTO canvas_dot_tool_sessions VALUES(?,?,?,?,?,?) "
                   "ON CONFLICT(owner,project_id,space_id,member_dot_id,tool) "
                   "DO UPDATE SET terminal_id=excluded.terminal_id",
                   (owner, project_id, space_id, member_dot_id, tool, terminal_id))


def _guest_conversation_binding(control, owner, project_id, member, record):
    """Find a single conversation with an existing VM WorkItem for this Dot.

    Never guess which conversation/Grant an agent should inherit. A Canvas
    terminal with zero or multiple bindings stays unavailable until the
    owner makes the binding unambiguous.
    """
    candidates = []
    work_items = record.get("work_items") if isinstance(record, dict) else None
    if not isinstance(work_items, dict):
        return None
    with closing(control.store.connect("shell")) as db:
        for conversation_id, work_item_id in work_items.items():
            if not isinstance(conversation_id, str) or not isinstance(work_item_id, str):
                continue
            try:
                conversation = control.shell._entity(
                    db, owner, project_id, "conversation", conversation_id,
                    space_id=member["space_id"])
            except (Denied, KeyError, ValueError):
                continue
            if conversation.get("dot_id") == member["dot_id"]:
                candidates.append(conversation_id)
    return candidates[0] if len(candidates) == 1 else None


def _central_guest_submit(canvas, project_id, member, conversation_id, executor):
    """Return a guest CLI executor admitted by the same vm:guest Control Plane.

    Input from the terminal must not call VBoxManage directly. The generated
    request key is unique to a human-submitted line and is never reused to
    silently retry an uncertain effect.
    """
    from .shell_dot_vm import DotVmServices
    if not callable(getattr(executor, "_guest_command", None)):
        raise ValueError("guest CLI command encoder is unavailable")
    service = DotVmServices(canvas)

    def submit(request):
        command = executor._guest_command(request)
        response = service.dispatch(project_id, "dot_vm_execute", {
            "dot_id": member["dot_id"], "space_id": member["space_id"],
            "conversation_id": conversation_id,
            "arguments": {"action": "guest.run", "command": command,
                          "timeout_seconds": int(request.get("timeout_s", 120))},
        }, uuid.uuid4().hex)
        evidence = response.get("evidence") if isinstance(response, dict) else None
        evidence = evidence if isinstance(evidence, dict) else {}
        confirmed = (
            response.get("state") == "SUCCEEDED"
            and evidence.get("guest_process_confirmed") is True
            and evidence.get("execution_surface") == "guest"
            and evidence.get("host_subprocess") is False
            and evidence.get("claims_guest_execution") is True
            and evidence.get("execution_uncertain") is not True
        )
        return {
            "exit_code": 0 if confirmed else None,
            "stdout": evidence.get("stdout", "") if isinstance(evidence.get("stdout"), str) else "",
            "stderr": "",
            "execution_surface": "guest" if confirmed else "blocked",
            "host_subprocess": False,
            "claims_guest_execution": confirmed,
            "execution_uncertain": not confirmed,
            "operation_id": response.get("operation_id"),
            "automatic_retry": False,
        }

    return submit


def _open_guest_dot_terminal(canvas, control, owner, project_id, member, tool, record):
    """Attach the Dot CLI to its VM. A missing registry does not start a host shell."""
    from sentra_executors.guest_execution import is_proven_guest_executor
    if tool not in {"sentra-cli", "opencode", "codex"}:
        return {
            "status": "blocked", "execution_surface": "blocked", "host_subprocess": False,
            "claims_guest_execution": False, "tool_executed": False,
            "reason": "this tool has no guest terminal in the Dot VM",
        }
    executor = _guest_terminal_executor(record)
    if not is_proven_guest_executor(executor):
        return {
            "status": "blocked", "execution_surface": "blocked", "host_subprocess": False,
            "claims_guest_execution": False, "tool_executed": False,
            "reason": "Dot VM registry cannot prove a guest terminal",
        }
    conversation_id = _guest_conversation_binding(
        control, owner, project_id, member, record)
    if conversation_id is None:
        return {
            "status": "blocked", "execution_surface": "blocked", "host_subprocess": False,
            "claims_guest_execution": False, "tool_executed": False,
            "reason": "Dot VM terminal requires exactly one authorized conversation and VM WorkItem",
        }
    try:
        submit = _central_guest_submit(
            canvas, project_id, member, conversation_id, executor)
    except (ValueError, RuntimeError) as exc:
        return {
            "status": "blocked", "execution_surface": "blocked", "host_subprocess": False,
            "claims_guest_execution": False, "tool_executed": False,
            "reason": str(exc),
        }
    family = record.get("os_family") if isinstance(record.get("os_family"), str) else "linux"
    family = family.strip().lower() if family.strip().lower() in {"linux", "windows"} else "linux"
    name = "Dot_" + member["agent_id"][:12] + "_" + tool.replace("-", "_")
    terminal = _allocate_guest_terminal(canvas, project_id, name, tool)
    from .service import Session
    persist_output = getattr(canvas.store, "append_terminal_output", None)
    persist = (lambda chunk: persist_output(project_id, terminal["id"], chunk)
               ) if callable(persist_output) else None
    session = Session(persist=persist)
    channel = GuestDotTerminal(
        executor, tool, family,
        _imported_guest_workspace(record, family) or _dot_home(record, family),
        on_output=session.append, submit=submit,
    )
    session.pty = channel
    session.exit_input = b""
    canvas._sessions[terminal["id"]] = session
    _bind_tool_terminal(control, owner, project_id, member["space_id"], member["dot_id"], tool, terminal["id"])
    return {
        "status": "running", "terminal_id": terminal["id"], "reused": False,
        "execution_surface": "guest", "host_subprocess": False,
        "claims_guest_execution": False, "tool_executed": False,
        "vm_id": _vm_id(record), "model_acknowledged": False, "authentication_verified": False,
    }


def _binding_terminal(canvas, control, owner, project_id, space_id, member_id, tool):
    for row in _bindings(control, owner, project_id, space_id):
        if row["member_dot_id"] == member_id and row["tool"] == tool:
            return canvas.store.resource("terminals", row["terminal_id"], project_id)
    return None


def dot_graph(canvas, project_id, dot_id, space_id=None):
    control, owner = canvas._shell_service(), canvas._runtime().owner
    root, dots = dots_for_root(control, owner, project_id, dot_id, space_id)
    graph = canvas.graph_detail(project_id)
    agents = {dot["agent_id"] for dot in dots}
    resources = [canvas.store.resource("agents", agent, project_id) for agent in agents]
    terminals = [canvas.store.resource("terminals", agent["terminal_id"], project_id)
                 for agent in resources if agent.get("terminal_id")]
    nodes = [node for node in graph["nodes"] if node["kind"] == "agent"
             and node["resource_id"] in agents]
    ids = {node["id"] for node in nodes}
    allowed_dots = {dot["dot_id"] for dot in dots}
    sessions = []
    for row in _bindings(control, owner, project_id, dots[0]["space_id"]):
        if row["member_dot_id"] not in allowed_dots or row["tool"] not in TOOLS:
            continue
        try:
            terminal = canvas.store.resource("terminals", row["terminal_id"], project_id)
        except (KeyError, ValueError, Denied):
            continue
        if terminal["status"] == "running" and not _owned_live(canvas, terminal):
            terminal = {**terminal, "status": "detached", "recoverable": False}
        sessions.append({"member_dot_id": row["member_dot_id"], "tool": row["tool"],
                         "terminal": terminal})
    teams = []
    for team in canvas.store.list_resources("teams", project_id):
        members = canvas.team_members(project_id, team["id"])
        if any(m["id"] in agents and m["team_role"] == "worker" for m in members):
            teams.append({"id": team["id"], "name": team["name"],
                          "worker_ids": [m["id"] for m in members
                                         if m["id"] in agents and m["team_role"] == "worker"]})
    tasks = [{"id": t["id"], "agent_id": t["agent_id"], "team_id": t["team_id"],
              "provider": t["provider"], "status": t["status"],
              "work_item_id": t.get("work_item_id"), "operation_id": t.get("operation_id"),
              "cancel_requested": t.get("cancel_requested", False)}
             for t in canvas.store.list_resources("tasks", project_id)
             if t["agent_id"] in agents]
    return {"project_id": project_id, "canvas_root_dot_id": root, "dots": dots,
            "nodes": nodes, "agents": resources, "terminals": terminals,
            "tool_sessions": sessions, "tools": tool_catalog(canvas.project_dir),
            "teams": teams, "tasks": tasks,
            "deliveries": tool_deliveries(canvas, control, owner, project_id,
                                          dots[0]["space_id"], allowed_dots),
            "links": [link for link in graph["links"]
                      if link["source"] in ids and link["target"] in ids]}


def dispatch_dot_canvas(canvas, project_id, action, params, request_key):
    fields = {"dot_id", "space_id"}
    fields |= {
        "dot_canvas_move": {"id", "x", "y"},
        "dot_canvas_link": {"source", "target"},
        "dot_canvas_unlink": {"id"},
        "dot_canvas_terminal": {"member_dot_id", "tool"},
        "dot_canvas_terminal_close": {"member_dot_id", "tool"},
        "dot_canvas_handoff": {"source_dot_id", "member_dot_id", "tool", "message", "approved"},
        "dot_canvas_task_submit": {"member_dot_id", "team_id", "prompt", "approved"},
        "dot_canvas_task_cancel": {"task_id"},
    }.get(action, set())
    if set(params) - fields or not {"dot_id", "space_id"} <= params.keys():
        raise ValueError("canonical Dot/Space canvas required")
    graph = dot_graph(canvas, project_id, params["dot_id"], params["space_id"])
    if action == "dot_canvas_get":
        return graph
    members = {dot["dot_id"]: dot for dot in graph["dots"]}
    control, owner = canvas._shell_service(), canvas._runtime().owner
    def require_member():
        member = members.get(params.get("member_dot_id"))
        if member is None:
            raise Denied("terminal or task belongs to another Dot canvas")
        return member
    def tool_for_member(member):
        tool = params.get("tool", "sentra-cli")
        if tool not in TOOLS:
            raise Denied("unverified CLI or external application is not a ConPTY tool")
        return tool
    def apply():
        if action in {"dot_canvas_terminal", "dot_canvas_terminal_close"}:
            member = require_member()
            tool = tool_for_member(member)
            previous = _binding_terminal(canvas, control, owner, project_id,
                                         member["space_id"], member["dot_id"], tool)
            vm_record = _root_vm_record(canvas, project_id, graph["canvas_root_dot_id"])
            if action == "dot_canvas_terminal_close":
                guest = _guest_channel(canvas, previous) is not None
                if _owned_live(canvas, previous):
                    canvas.terminal_close(project_id, previous["id"])
                    delivery_terminal_lost(control, owner, project_id, previous["id"])
                return {"status": "closed", "terminal_id": previous["id"] if previous else None,
                        "host_subprocess": False if guest else None}
            if tool in {"sentra-cli", "opencode", "codex"}:
                if _vm_id(vm_record):
                    live_guest = _guest_channel(canvas, previous)
                    if live_guest is not None:
                        return {
                            "status": "running", "terminal_id": previous["id"], "reused": True,
                            "execution_surface": "guest", "host_subprocess": False,
                            "claims_guest_execution": False, "vm_id": _vm_id(vm_record),
                        }
                    if _owned_live(canvas, previous):
                        canvas.terminal_close(project_id, previous["id"])
                        delivery_terminal_lost(control, owner, project_id, previous["id"])
                    return _open_guest_dot_terminal(
                        canvas, control, owner, project_id, member, tool, vm_record)
                if _owned_live(canvas, previous):
                    canvas.terminal_close(project_id, previous["id"])
                    delivery_terminal_lost(control, owner, project_id, previous["id"])
                return {
                    "status": "blocked", "execution_surface": "blocked", "host_subprocess": False,
                    "claims_guest_execution": False, "tool_executed": False,
                    "reason": "Dot terminal requires the registered VM",
                }
            if _owned_live(canvas, previous):
                return {"status": "running", "terminal_id": previous["id"], "reused": True}
            if tool == "sentra-cli":
                terminal = canvas.create_terminal(project_id, "Dot_" + member["agent_id"][:12] + "_sentra",
                                                  "sentra-cli", model=SENTRA_MODEL, effort="high")
            else:
                workspace = Path(canvas.store.workspace(project_id)["path"])
                command = cli_argv(canvas.project_dir, workspace, tool)
                terminal = canvas._start(project_id, "Dot_" + member["agent_id"][:12] + "_" + tool.replace("-", "_"),
                                         tool, command)
                if tool == "opencode":
                    # Stop only this owned ConPTY session, never the shared OpenCode service.
                    canvas._sessions[terminal["id"]].exit_input = b"\x03"
            _bind_tool_terminal(control, owner, project_id, member["space_id"], member["dot_id"], tool, terminal["id"])
            result = {"status": "running", "terminal_id": terminal["id"],
                      "model_acknowledged": False, "authentication_verified": False}
            if tool == "grok":
                result["model"] = GROK_MODEL
                result["route"] = "canvas-grok-terminal"
            return result
        if action == "dot_canvas_handoff":
            target = require_member()
            tool = tool_for_member(target)
            source = members.get(params.get("source_dot_id"))
            message = params.get("message")
            if source is None:
                raise Denied("sender belongs to another Dot canvas")
            if params.get("approved") is not True:
                raise Denied("explicit handoff approval required")
            if (not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000
                    or any(ord(c) < 32 or ord(c) == 127 for c in message)):
                raise ValueError("single-line bounded handoff required")
            node_ids = {n["resource_id"]: n["id"] for n in graph["nodes"]}
            origin, dest = node_ids[source["agent_id"]], node_ids[target["agent_id"]]
            canvas.graph.linked_target(project_id, origin, dest)
            terminal = _binding_terminal(canvas, control, owner, project_id,
                                         target["space_id"], target["dot_id"], tool)
            session = canvas._sessions.get(terminal["id"]) if terminal else None
            if (not terminal or terminal["status"] != "running" or not session
                    or not session.pty or session.pty.poll() is not None):
                raise ValueError("destination CLI is not attached and running")
            record, created = canvas.graph.prepare_handoff(project_id, origin, dest,
                                                           message, request_key)
            if not created:
                return {"status": record["status"], "handoff_id": record["id"],
                        "model_acknowledged": False, "automatic_retry": False}
            # The central WorkItem and Operation are reserved before the one-shot
            # ConPTY effect. An exception after reservation is UNCERTAIN, never retry.
            ids = reserve_delivery(canvas, control, owner, project_id=project_id,
                space_id=target["space_id"], request_key=request_key,
                root_dot_id=graph["canvas_root_dot_id"],source=source,target=target,
                tool=tool,terminal_id=terminal["id"],handoff_id=record["id"])
            canvas.graph.handoff_state(project_id, record["id"], "sending")
            try:
                session.pty.write((message + "\r").encode("utf-8"))
                canvas.graph.handoff_state(project_id, record["id"], "sent")
                delivery_sent(control, owner, ids)
            except BaseException:
                try:
                    canvas.graph.handoff_state(project_id, record["id"], "uncertain")
                except Exception:
                    pass
                delivery_uncertain(control, owner, ids, "write or receipt unconfirmed")
                raise
            guest = getattr(session.pty, "execution_surface", None) == "guest"
            return {"status": "sent", "handoff_id": record["id"],
                    "work_item_id": ids["work_item_id"],
                    "operation_id": ids["operation_id"],
                    "transport": "guest-executor" if guest else "conpty-stdin",
                    "execution_surface": "guest" if guest else "host",
                    "host_subprocess": False if guest else True,
                    "model_acknowledged": False,
                    "task_completed": False}
        if action == "dot_canvas_task_submit":
            member = require_member()
            team = next((t for t in graph["teams"] if t["id"] == params.get("team_id")
                         and member["agent_id"] in t["worker_ids"]), None)
            if team is None:
                raise Denied("Dot must belong to an existing team as worker")
            if params.get("approved") is not True:
                raise Denied("explicit task approval required")
            task = canvas.delegate(project_id, team["id"], member["agent_id"],
                                   params.get("prompt"), request_key,
                                   provider="sentra-cli", approved=True)
            return {"status": "accepted", "task_id": task["id"],
                    "work_item_id": task.get("work_item_id"),
                    "execution_status": task["status"], "task_completed": False}
        if action == "dot_canvas_task_cancel":
            task = next((t for t in graph["tasks"] if t["id"] == params.get("task_id")), None)
            if task is None:
                raise Denied("task belongs to another Dot canvas")
            result = canvas.cancel_task(project_id, task["id"])
            return {"status": "cancel_requested" if result["requested"] else "unchanged",
                    "task_id": task["id"], "task_completed": False}
        if action == "dot_canvas_move":
            result = canvas.graph_move(project_id, params["id"], params["x"], params["y"])
        elif action == "dot_canvas_link":
            result = canvas.graph_link(project_id, params["source"], params["target"])
        else:
            result = canvas.graph_unlink(project_id, params["id"])
        return {"status": "applied", "canvas_root_dot_id": graph["canvas_root_dot_id"],
                "result": result}
    ids = {node["id"] for node in graph["nodes"]}
    if action == "dot_canvas_link" and (params.get("source") not in ids
                                         or params.get("target") not in ids):
        raise Denied("agents belong to another Dot canvas")
    if action == "dot_canvas_unlink" and params.get("id") not in {
            link["id"] for link in graph["links"]}:
        raise Denied("link belongs to another Dot canvas")
    if action == "dot_canvas_move" and params.get("id") not in ids:
        raise Denied("node belongs to another Dot canvas")
    return ShellHostRequests(control, owner).invoke(
        project_id, action, params, request_key, apply)
