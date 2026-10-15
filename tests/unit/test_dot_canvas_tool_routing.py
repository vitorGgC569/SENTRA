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
    # Old guest-routing tests inject a fake VM executor. Central admission is
    # covered separately; do not make this isolated fake impersonate a real CP.
    monkeypatch.setattr(mod, "_guest_conversation_binding", lambda *_args: "conv-fake")
    monkeypatch.setattr(mod, "_central_guest_submit", lambda _canvas, _project, _member, _cid, executor: executor.execute)
    return canvas


def dispatch(canvas, action, key="request-0001", **kw):
    return mod.dispatch_dot_canvas(canvas, "ws", action,
                                   {"dot_id": "d1", "space_id": "space", **kw}, key)


def test_web6_dot_opens_grok_4_7_through_the_canvas_terminal(session, monkeypatch):
    captured = {}

    def argv(root, workspace, shell):
        captured["shell"] = shell
        captured["workspace"] = str(workspace)
        return ["grok.exe", "--cwd", str(workspace), "--model", "grok-4.7"]

    monkeypatch.setattr(mod, "cli_argv", argv)
    result = dispatch(session, "dot_canvas_terminal", key="grok-web6",
                      member_dot_id="d2", tool="grok")
    assert captured["shell"] == "grok"
    assert result["status"] == "running"
    assert result["model"] == "grok-4.7"
    assert result["route"] == "canvas-grok-terminal"
    assert result["model_acknowledged"] is False
    assert result["authentication_verified"] is False
    assert session.started == [("grok", {})]
    assert session.store.resource("agents", "a2", "ws")["model"] == mod.SENTRA_MODEL


def test_open_without_a_vm_does_not_start_a_host_terminal(session):
    first = dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    repeated = dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    assert first == repeated
    assert first["status"] == "blocked"
    assert first["host_subprocess"] is False
    assert first["reason"] == "Dot terminal requires the registered VM"
    assert session.started == []
    assert session._sessions == {}


def test_foreign_dot_and_unknown_cli_are_denied(session):
    with pytest.raises(Denied):
        dispatch(session, "dot_canvas_terminal", member_dot_id="foreign")
    with pytest.raises(Denied):
        dispatch(session, "dot_canvas_terminal", key="request-0002",
                 member_dot_id="d2", tool="antigravity-app")
    assert session.started == []


def test_handoff_without_a_vm_does_not_write_on_the_host(session):
    dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    with pytest.raises(ValueError, match="not attached"):
        dispatch(session, "dot_canvas_handoff", key="handoff-0001",
                 member_dot_id="d2", source_dot_id="d1",
                 tool="sentra-cli", message="Responda OK", approved=True)
    assert session.started == []
    assert session.pty.writes == []


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
    grok = tmp_path / ".grok" / "bin" / "grok.exe"
    grok.parent.mkdir(parents=True)
    grok.write_bytes(b"grok-cli")
    monkeypatch.setattr(adapters, "_which", lambda name: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    argv = adapters.cli_argv(tmp_path, tmp_path / "workspace", "grok")
    assert argv[0] == str(grok.resolve())
    assert argv[1:5] == ["--cwd", str(tmp_path / "workspace"), "--model", "grok-4.7"]
    assert "-p" not in argv
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

def test_imported_folder_follows_the_dot_account():
    accepted = mod._imported_guest_workspace({
        "username": "dotuser",
        "last_project_import": {
            "receipt_state": "SUCCEEDED",
            "guest_path": "/home/dotuser/Imports/one/project",
            "host_folder": r"C:\Users\vitor\host-project",
        },
    }, "linux")
    assert accepted == "/home/dotuser/Imports/one/project"
    assert mod._imported_guest_workspace({
        "username": "dotuser",
        "last_project_import": {
            "receipt_state": "SUCCEEDED",
            "guest_path": "/home/sentra/Imports/one/project",
        },
    }, "linux") is None
    assert mod._imported_guest_workspace({
        "username": "dotuser",
        "last_project_import": {
            "receipt_state": "SUCCEEDED",
            "guest_path": "/home/dotuser/Imports/a;id",
            "host_folder": r"C:\Users\vitor\host-project",
        },
    }, "linux") is None
    assert mod._imported_guest_workspace({
        "username": "dotuser",
        "last_project_import": {
            "receipt_state": "SUCCEEDED",
            "guest_path": "/home/dotuser/../../etc",
            "host_folder": r"C:\Users\vitor\host-project",
        },
    }, "linux") is None


def test_dot_vm_terminal_stays_in_the_guest(session, monkeypatch):
    calls = []

    class Exec:
        proven_guest = True
        execution_surface = "guest"

        def execute(self, request):
            calls.append(request)
            return {
                "exit_code": 0, "stdout": "ok", "stderr": "",
                "execution_surface": "guest", "host_subprocess": False,
                "claims_guest_execution": True,
            }

    monkeypatch.setattr(mod, "_root_vm_record", lambda *_args, **_kwargs: {
        "vm_id": "owned-guest-vm", "username": "sentra", "password": "dot-secret",
        "os_family": "linux",
        "last_project_import": {
            "receipt_state": "SUCCEEDED",
            "guest_path": "/home/sentra/Imports/one/project",
            "host_folder": r"C:\Users\vitor\host-project",
        },
    })
    monkeypatch.setattr(mod, "_guest_terminal_executor", lambda _record: Exec())

    def create_guest(project_id, name, shell):
        assert project_id == "ws"
        row = {"id": "guest-term", "name": name, "status": "running", "shell": shell, "pid": None}
        session.store.terminals["guest-term"] = row
        return row

    session.create_guest_terminal = create_guest
    opened = dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    assert session.started == []
    assert opened["status"] == "running"
    assert opened["execution_surface"] == "guest"
    assert opened["host_subprocess"] is False
    assert opened["claims_guest_execution"] is False
    assert opened["vm_id"] == "owned-guest-vm"
    assert "dot-secret" not in str(opened)
    again = dispatch(session, "dot_canvas_terminal", key="request-0002", member_dot_id="d2")
    assert again["reused"] is True
    assert again["terminal_id"] == "guest-term"
    sent = dispatch(session, "dot_canvas_handoff", key="handoff-guest",
                    member_dot_id="d2", source_dot_id="d1", tool="sentra-cli",
                    message="Responda OK", approved=True)
    assert sent["transport"] == "guest-executor"
    assert sent["host_subprocess"] is False
    assert sent["task_completed"] is False
    assert session.pty.writes == []
    assert calls[0]["placement"] == "guest"
    assert calls[0]["tool"] == "sentra-cli"
    assert calls[0]["prompt"] == "Responda OK"
    assert calls[0]["guest_workspace"] == "/home/sentra/Imports/one/project"
    assert r"C:\Users\vitor\host-project" not in calls[0]["guest_workspace"]


def test_guest_handoff_without_a_guest_process_is_not_sent(session, monkeypatch):
    class Exec:
        proven_guest = True
        execution_surface = "guest"

        def execute(self, request):
            return {
                "exit_code": 0, "stdout": "ok", "stderr": "",
                "execution_surface": "guest", "host_subprocess": True,
            }

    monkeypatch.setattr(mod, "_root_vm_record", lambda *_args, **_kwargs: {
        "vm_id": "owned-guest-vm", "username": "sentra", "password": "dot-secret",
        "os_family": "linux",
    })
    monkeypatch.setattr(mod, "_guest_terminal_executor", lambda _record: Exec())

    def create_guest(project_id, name, shell):
        row = {"id": "guest-term", "name": name, "status": "running", "shell": shell, "pid": None}
        session.store.terminals["guest-term"] = row
        return row

    session.create_guest_terminal = create_guest
    dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    with pytest.raises(RuntimeError, match="did not stay in the VM"):
        dispatch(session, "dot_canvas_handoff", key="handoff-guest-host",
                 member_dot_id="d2", source_dot_id="d1", tool="sentra-cli",
                 message="Responda OK", approved=True)
    assert ("handoff1", "sent") not in session.graph.sent
    assert ("handoff1", "uncertain") in session.graph.sent
    channel = session._sessions["guest-term"].pty
    assert channel.writes == []


def test_guest_handoff_without_a_guest_claim_is_not_sent(session, monkeypatch):
    class Exec:
        proven_guest = True
        execution_surface = "guest"

        def execute(self, request):
            return {
                "exit_code": 0, "stdout": "ok", "stderr": "",
                "execution_surface": "guest", "host_subprocess": False,
                "claims_guest_execution": False,
            }

    monkeypatch.setattr(mod, "_root_vm_record", lambda *_args, **_kwargs: {
        "vm_id": "owned-guest-vm", "username": "sentra", "password": "dot-secret",
        "os_family": "linux",
    })
    monkeypatch.setattr(mod, "_guest_terminal_executor", lambda _record: Exec())

    def create_guest(project_id, name, shell):
        row = {"id": "guest-term", "name": name, "status": "running", "shell": shell, "pid": None}
        session.store.terminals["guest-term"] = row
        return row

    session.create_guest_terminal = create_guest
    dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    with pytest.raises(RuntimeError, match="did not stay in the VM"):
        dispatch(session, "dot_canvas_handoff", key="handoff-guest-unclaimed",
                 member_dot_id="d2", source_dot_id="d1", tool="sentra-cli",
                 message="Responda OK", approved=True)
    assert ("handoff1", "sent") not in session.graph.sent
    assert session._sessions["guest-term"].pty.writes == []


def test_uncertain_guest_write_is_not_recorded():
    class Executor:
        def execute(self, request):
            return {
                "execution_surface": "guest",
                "host_subprocess": False,
                "claims_guest_execution": True,
                "exit_code": 0,
                "stdout": "ok",
                "execution_uncertain": True,
            }

    terminal = mod.GuestDotTerminal(Executor(), "codex", "linux", "/home/sentra")
    with pytest.raises(RuntimeError, match="guest terminal"):
        terminal.write(b"inspect the project\r")
    assert terminal.writes == []


def test_incomplete_dot_vm_does_not_open_a_host_terminal(session, monkeypatch):
    monkeypatch.setattr(mod, "_root_vm_record", lambda *_args, **_kwargs: {"vm_id": "owned-guest-vm"})
    blocked = dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    assert blocked["status"] == "blocked"
    assert blocked["host_subprocess"] is False
    assert blocked["tool_executed"] is False
    assert session.started == []


def test_detached_terminal_requires_new_owned_handle(session):
    opened = dispatch(session, "dot_canvas_terminal", member_dot_id="d2")
    assert opened["status"] == "blocked"
    assert session.started == []
    second = dispatch(session, "dot_canvas_terminal", key="request-0002", member_dot_id="d2")
    assert second["status"] == "blocked"
    assert second["host_subprocess"] is False


def test_guest_canvas_terminal_is_line_oriented_and_retains_real_output():
    """No fake ConPTY: the same Canvas Session serves the guest transcript."""
    from sentra_canvas.service import Session

    calls, persisted = [], []

    class Executor:
        def execute(self, request):
            calls.append(request)
            return {
                "execution_surface": "guest", "host_subprocess": False,
                "claims_guest_execution": True, "execution_uncertain": False,
                "exit_code": 0, "stdout": "VM says ready", "stderr": "",
            }

    session = Session(persist=persisted.append)
    terminal = mod.GuestDotTerminal(
        Executor(), "codex", "windows", r"C:\Users\sentra",
        on_output=session.append,
    )
    session.pty = terminal
    terminal.write(b"check ")
    terminal.write(b"the VM")
    assert calls == [], "partial keystrokes must never start a guest operation"
    terminal.write(b"\r")
    assert len(calls) == 1
    assert calls[0]["placement"] == "guest"
    assert calls[0]["prompt"] == "check the VM"
    assert terminal.writes == ["check the VM"]
    assert "VM says ready" in session.output()["text"]
    assert "VM says ready" in "".join(persisted)
    assert session.pty.poll() is None
    terminal.resize(100, 30)
    terminal.close()
    assert terminal.poll() == 0


def test_guest_canvas_terminal_displays_uncertainty_without_claiming_success():
    from sentra_canvas.service import Session

    class Executor:
        def execute(self, request):
            return {
                "execution_surface": "guest", "host_subprocess": False,
                "claims_guest_execution": False, "execution_uncertain": True,
                "exit_code": None, "stdout": "partial guest output",
            }

    session = Session()
    terminal = mod.GuestDotTerminal(
        Executor(), "sentra-cli", "linux", "/home/sentra",
        on_output=session.append,
    )
    with pytest.raises(RuntimeError, match="guest terminal"):
        terminal.write(b"perform task\r")
    assert terminal.writes == []
    assert "partial guest output" in session.output()["text"]
    assert "não reenviar automaticamente" in session.output()["text"]


def test_central_guest_submit_uses_vm_work_item_authority(monkeypatch):
    """A terminal line is dispatched through dot_vm_execute, not VBox directly."""
    from sentra_canvas import shell_dot_vm
    captured = []

    class Service:
        def dispatch(self, project_id, action, params, key):
            captured.append((project_id, action, params, key))
            return {
                "state": "SUCCEEDED", "operation_id": "op-guest-proved",
                "evidence": {
                    "guest_process_confirmed": True, "execution_surface": "guest",
                    "host_subprocess": False, "claims_guest_execution": True,
                    "execution_uncertain": False, "stdout": "guest evidence",
                },
            }

    class Encoder:
        def _guest_command(self, request):
            return "bounded-guest-cli " + request["prompt"]

        def execute(self, request):
            raise AssertionError("the guest bypassed central admission")

    monkeypatch.setattr(shell_dot_vm, "DotVmServices", lambda _canvas: Service())
    call = mod._central_guest_submit(
        object(), "ws", {"dot_id": "d2", "space_id": "space"}, "conv-2", Encoder())
    result = call({"placement": "guest", "prompt": "inspect", "timeout_s": 120})
    assert result["exit_code"] == 0
    assert result["stdout"] == "guest evidence"
    assert result["claims_guest_execution"] is True
    project, action, params, key = captured[0]
    assert project == "ws" and action == "dot_vm_execute"
    assert params["conversation_id"] == "conv-2"
    assert params["dot_id"] == "d2"
    assert params["arguments"] == {
        "action": "guest.run", "command": "bounded-guest-cli inspect",
        "timeout_seconds": 120,
    }
    assert len(key) == 32


def test_central_guest_submit_does_not_promote_uncertain_vm_result(monkeypatch):
    from sentra_canvas import shell_dot_vm

    class Service:
        def dispatch(self, *args):
            return {"state": "UNCERTAIN", "operation_id": "op-uncertain",
                    "evidence": {"guest_process_confirmed": False, "stdout": "partial"}}

    class Encoder:
        def _guest_command(self, request):
            return "safe command"

    monkeypatch.setattr(shell_dot_vm, "DotVmServices", lambda _: Service())
    call = mod._central_guest_submit(
        object(), "ws", {"dot_id": "d2", "space_id": "space"}, "conv-2", Encoder())
    result = call({"placement": "guest", "prompt": "inspect"})
    assert result["exit_code"] is None
    assert result["claims_guest_execution"] is False
    assert result["execution_uncertain"] is True
    assert result["automatic_retry"] is False


def test_guest_conversation_binding_refuses_missing_ambiguous_or_other_dot(tmp_path):
    from contextlib import closing

    class Shell:
        def _entity(self, db, owner, project, kind, conversation_id, *, space_id):
            assert (owner, project, kind, space_id) == ("owner", "ws", "conversation", "space")
            return {"dot_id": {"a": "d2", "b": "d2", "c": "d1"}[conversation_id]}

    control = SimpleNamespace(store=ControlStore(tmp_path / "scope.sqlite3"), shell=Shell())
    member = {"dot_id": "d2", "space_id": "space"}
    assert mod._guest_conversation_binding(
        control, "owner", "ws", member, {"work_items": {}}) is None
    assert mod._guest_conversation_binding(
        control, "owner", "ws", member, {"work_items": {"c": "wi-for-other-dot"}}) is None
    assert mod._guest_conversation_binding(
        control, "owner", "ws", member, {"work_items": {"a": "wi-a"}}) == "a"
    assert mod._guest_conversation_binding(
        control, "owner", "ws", member, {"work_items": {"a": "wi-a", "b": "wi-b"}}) is None
