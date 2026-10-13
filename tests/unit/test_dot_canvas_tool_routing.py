"""No provider calls: exercise real Dot scope/journal with isolated SQLite."""
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_canvas import adapters, shell_dot_canvas as mod
from sentra_canvas.store import Denied


class ControlStore:
    def __init__(self, path):
        self.path = path
    def connect(self, _area):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db


class Store:
    def __init__(self):
        self.principal = "owner"
        self.terminals = {}
        self.tasks = []
    def resource(self, kind, ident, ws):
        assert ws == "ws"
        if kind == "agents":
            return {"id": ident, "terminal_id": None, "model": "sentra/chatgpt-web/gpt-6"}
        if kind == "terminals":
            return dict(self.terminals[ident])
        if kind == "tasks":
            return next(t for t in self.tasks if t["id"] == ident)
        raise KeyError(kind)
    def list_resources(self, kind, ws):
        assert ws == "ws"
        if kind == "teams":
            return [{"id": "team", "name": "Agentes"}]
        if kind == "tasks":
            return list(self.tasks)
        return []
    def workspace(self, ws):
        assert ws == "ws"
        return {"path": "C:\\sandbox"}


class FakeGraph:
    def __init__(self):
        self.sent = []
    def linked_target(self, ws, source, target):
        assert (ws, source, target) == ("ws", "node1", "node2")
        return {}, {}
    def prepare_handoff(self, ws, source, target, msg, key):
        self.sent.append(("prepared", msg, key))
        return {"id": "handoff1", "status": "prepared"}, True
    def handoff_state(self, ws, ident, state):
        self.sent.append((ident, state))
        return {"id": ident, "status": state}


class Pty:
    def __init__(self):
        self.writes = []
    def poll(self):
        return None
    def write(self, data):
        self.writes.append(data)


class Canvas:
    project_dir = Path(".")
    def __init__(self, tmp_path):
        self.store = Store()
        self.control = SimpleNamespace(store=ControlStore(tmp_path / "requests.db"))
        self.graph = FakeGraph()
        self.pty = Pty()
        self._sessions = {}
        self.started = []
        self.delegated = []
    def _shell_service(self):
        return self.control
    def _runtime(self):
        return SimpleNamespace(owner="owner")
    def graph_detail(self, ws):
        return {"nodes": [
            {"id": "node1", "kind": "agent", "resource_id": "a1", "x": 0, "y": 0},
            {"id": "node2", "kind": "agent", "resource_id": "a2", "x": 100, "y": 0}],
            "links": [{"id": "edge", "source": "node1", "target": "node2"}]}
    def team_members(self, ws, team):
        return [{"id": "a1", "team_role": "coordinator"},
                {"id": "a2", "team_role": "worker"}]
    def create_terminal(self, ws, name, tool, **kw):
        from sentra_canvas.store import validated_name
        validated_name(name)
        self.started.append((tool, kw))
        ident = "term" + str(len(self.started))
        row = {"id": ident, "name": name, "status": "running", "shell": tool}
        self.store.terminals[ident] = row
        self._sessions[ident] = SimpleNamespace(pty=self.pty)
        return row
    def _start(self, ws, name, tool, command):
        return self.create_terminal(ws, name, tool)
    def terminal_close(self, ws, ident):
        self.store.terminals[ident]["status"] = "closed"
    def delegate(self, ws, team, agent, prompt, key, **opts):
        self.delegated.append((ws, team, agent, prompt, key, opts))
        row = {"id": "task1", "agent_id": agent, "team_id": team, "provider": "sentra-cli",
               "status": "queued", "work_item_id": "WI-1", "cancel_requested": False}
        self.store.tasks.append(row)
        return row
    def cancel_task(self, ws, ident):
        for row in self.store.tasks:
            if row["id"] == ident:
                row["cancel_requested"] = True
        return {"requested": True}


@pytest.fixture
def session(tmp_path, monkeypatch):
    canvas = Canvas(tmp_path)
    dots = [
        {"dot_id": "d1", "agent_id": "a1", "space_id": "space", "name": "Alpha"},
        {"dot_id": "d2", "agent_id": "a2", "space_id": "space", "name": "Beta"},
    ]
    monkeypatch.setattr(mod, "dots_for_root", lambda *_args: ("d1", dots))
    # Authority is exercised by the isolated real-Canvas QA, never faked as model success.
    monkeypatch.setattr(mod, "reserve_delivery", lambda *_args, **_kwargs:
                        {"work_item_id": "WI-fake", "operation_id": "op-fake"})
    monkeypatch.setattr(mod, "delivery_sent", lambda *_args, **_kwargs: None)
    return canvas


def dispatch(canvas, action, key="request-0001", **kw):
    return mod.dispatch_dot_canvas(canvas, "ws", action,
                                   {"dot_id": "d1", "space_id": "space", **kw}, key)


def test_open_is_dot_scoped_and_request_idempotent(session):
    first = dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    repeated = dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    assert first == repeated
    assert session.started == [("sentra-cli", {"model": mod.SENTRA_MODEL, "effort": "high"})]
    assert dispatch(session, "dot_canvas_terminal", key="request-0002",
                    member_dot_id="d2")["reused"] is True
    graph = dispatch(session, "dot_canvas_get")
    assert graph["tool_sessions"][0]["member_dot_id"] == "d2"


def test_foreign_dot_and_unknown_cli_are_denied(session):
    with pytest.raises(Denied):
        dispatch(session, "dot_canvas_terminal", member_dot_id="foreign")
    with pytest.raises(Denied):
        dispatch(session, "dot_canvas_terminal", key="request-0002",
                 member_dot_id="d2", tool="antigravity-app")
    assert session.started == []


def test_handoff_is_transport_only_never_completed(session):
    dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    result = dispatch(session, "dot_canvas_handoff", key="handoff-0001",
                      member_dot_id="d2", source_dot_id="d1",
                      tool="sentra-cli", message="Responda OK", approved=True)
    assert result["status"] == "sent"
    assert result["model_acknowledged"] is False
    assert result["task_completed"] is False
    assert session.pty.writes == [b"Responda OK\\r".replace(b"\\r", b"\r")]
    assert dispatch(session, "dot_canvas_handoff", key="handoff-0001",
                    member_dot_id="d2", source_dot_id="d1",
                    tool="sentra-cli", message="Responda OK", approved=True) == result
    assert len(session.pty.writes) == 1


def test_handoff_without_approval_never_writes(session):
    dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    with pytest.raises(Denied):
        dispatch(session, "dot_canvas_handoff", key="handoff-0002",
                 member_dot_id="d2", source_dot_id="d1", message="Execute", approved=False)
    assert session.pty.writes == []


def test_task_accepts_without_falsely_completing_and_cancels(session):
    result = dispatch(session, "dot_canvas_task_submit", member_dot_id="d2",
                      team_id="team", prompt="Auditar documentos", approved=True)
    assert result["status"] == "accepted" and result["task_completed"] is False
    assert result["execution_status"] == "queued"
    assert result["work_item_id"] == "WI-1"
    cancel = dispatch(session, "dot_canvas_task_cancel", key="request-0002", task_id="task1")
    assert cancel == {"status": "cancel_requested", "task_id": "task1", "task_completed": False}
    with pytest.raises(Denied):
        dispatch(session, "dot_canvas_task_cancel", key="request-0003", task_id="foreign")


def test_windows_native_opencode_avoids_shell_shim_and_antigravity_is_not_cli(monkeypatch, tmp_path):
    names = {"cmd.exe": r"C:\\Windows\\System32\\cmd.exe",
             "opencode.cmd": r"C:\\Tools\\opencode.cmd"}
    monkeypatch.setattr(adapters, "_which", lambda name: Path(names[name])
                        if name in names else None)
    monkeypatch.setenv('APPDATA', str(tmp_path))
    native = tmp_path / 'npm/node_modules/@opencode/cli/bin/opencode.exe'
    native.parent.mkdir(parents=True)
    native.write_bytes(b'test-native-program')
    argv = adapters.cli_argv(tmp_path, tmp_path, "opencode")
    assert argv[0] == str(native.resolve())
    assert '/C' not in argv and str(Path(names['opencode.cmd'])) not in argv
    assert argv[-1] == "opencode/muse-spark-1.3-contributor-free#high"
    with pytest.raises(ValueError):
        adapters.cli_argv(tmp_path, tmp_path, "antigravity-app")

@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows-only ConPTY proof")
def test_real_conpty_echo_is_owned_and_receivable(tmp_path):
    import shutil
    from sentra_canvas.terminal import WindowsPTY
    cmd = shutil.which("cmd.exe")
    if not cmd:
        pytest.skip("cmd.exe missing")
    output = []
    pty = WindowsPTY([cmd, "/D", "/C", "echo SENTRA_OWNED_CONPTY_OK"],
                     tmp_path, output.append)
    try:
        assert pty.wait(6) == 0
        import time
        end = time.monotonic() + 2
        while b"SENTRA_OWNED_CONPTY_OK" not in b"".join(output) and time.monotonic() < end:
            time.sleep(0.03)
        assert b"SENTRA_OWNED_CONPTY_OK" in b"".join(output)
    finally:
        pty.close()


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows-only executable")
def test_real_opencode_shim_help(tmp_path):
    import shutil
    import subprocess
    if not shutil.which("opencode.cmd"):
        pytest.skip("OpenCode not installed")
    argv = adapters.cli_argv(tmp_path, tmp_path, "opencode")
    argv.append("--help")
    result = subprocess.run(argv, cwd=tmp_path, capture_output=True,
                            text=True, timeout=20, check=False)
    assert result.returncode == 0, (result.stdout + result.stderr)[-1000:]
    assert "opencode mini [flags]" in result.stdout

def test_detached_terminal_requires_new_owned_handle(session):
    opened=dispatch(session,"dot_canvas_terminal",member_dot_id="d2")
    old=opened["terminal_id"]
    del session._sessions[old]  # Recreated backend has no owned kernel handle.
    rows=dispatch(session,"dot_canvas_get")["tool_sessions"]
    assert rows[0]["terminal"]["status"]=="detached"
    second=dispatch(session,"dot_canvas_terminal",key="request-0002",member_dot_id="d2")
    assert second["terminal_id"]!=old and not second.get("reused")
