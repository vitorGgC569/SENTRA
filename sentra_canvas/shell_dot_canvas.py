"""Dot-scoped ConPTY tools and task projections. No implicit provider authority."""
from contextlib import closing
from pathlib import Path

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
TOOLS = frozenset({"sentra-cli", "codex", "opencode"})
SENTRA_MODEL = "sentra/chatgpt-web/gpt-6"


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
            if action == "dot_canvas_terminal_close":
                if _owned_live(canvas, previous):
                    canvas.terminal_close(project_id, previous["id"])
                    delivery_terminal_lost(control, owner, project_id, previous["id"])
                return {"status": "closed", "terminal_id": previous["id"] if previous else None}
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
            with closing(control.store.connect("shell")) as db, db:
                db.execute("INSERT INTO canvas_dot_tool_sessions VALUES(?,?,?,?,?,?) "
                           "ON CONFLICT(owner,project_id,space_id,member_dot_id,tool) "
                           "DO UPDATE SET terminal_id=excluded.terminal_id",
                           (owner, project_id, member["space_id"], member["dot_id"],
                            tool, terminal["id"]))
            return {"status": "running", "terminal_id": terminal["id"],
                    "model_acknowledged": False, "authentication_verified": False}
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
            return {"status": "sent", "handoff_id": record["id"],
                    "work_item_id": ids["work_item_id"],
                    "operation_id": ids["operation_id"],
                    "transport": "conpty-stdin", "model_acknowledged": False,
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
