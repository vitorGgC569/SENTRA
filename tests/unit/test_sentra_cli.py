"""Unit and integration tests for SENTRA CLI (sentra_cli).
Tests agent directive parsing, tool execution, Maestri bridge fail-soft behavior,
ModelClient cascade fallback, and zero-regression preservation of native configs.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sentra_cli.__main__ import parse_args
from sentra_cli.config import CLIConfig, find_maestri_cli
from sentra_cli.jobs import BackgroundJobManager, run_job_file
from sentra_cli.maestri import MaestriBridge
from sentra_cli.tools import (
    apply_patch,
    git_diff,
    git_status,
    list_files,
    read_file,
    run_tests,
    write_file,
)
from sentra_cli.client import ModelClient
from sentra_cli.agent import SentraAgent, DIRECTIVE_RE


# ---------------------------------------------------------------------------
# 1. Config Detection Tests
# ---------------------------------------------------------------------------
def test_cli_config_defaults(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path)
    assert cfg.workspace == tmp_path
    assert cfg.gateway_url == "http://127.0.0.1:17842/v1"
    assert "sentra" in cfg.model or "gpt" in cfg.model
    assert isinstance(cfg.is_in_maestri, bool)


def test_cli_config_maestri_pipe_env(tmp_path: Path):
    env = {
        "MAESTRI_PIPE": r"\\.\pipe\maestri-test-123",
        "MAESTRI_TERMINAL_ID": "terminal-123",
        "MAESTRI_WORKSPACE_ID": "workspace-456",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
        assert cfg.maestri_pipe == r"\\.\pipe\maestri-test-123"
        assert cfg.maestri_terminal_id == "terminal-123"
        assert cfg.maestri_workspace_id == "workspace-456"
        assert cfg.is_in_maestri is True


def test_parse_args_respects_environment_defaults():
    env = {
        "SENTRA_CLI_MODEL": "sentra/gemini-web/flash",
        "SENTRA_CLI_FALLBACK_MODEL": "fallback-test",
        "SENTRA_GATEWAY_URL": "http://127.0.0.1:19000/v1",
    }
    with patch.dict(os.environ, env, clear=False):
        args = parse_args([])
    assert args.model == "sentra/gemini-web/flash"
    assert args.fallback_model == "fallback-test"
    assert args.gateway_url == "http://127.0.0.1:19000/v1"


def test_find_maestri_cli_prefers_installed_build_over_path(tmp_path: Path):
    installed = (
        tmp_path
        / "Programs"
        / "Maestri"
        / "resources"
        / "cli"
        / "maestri.exe"
    )
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"installed")
    stale = tmp_path / "stale-maestri.exe"
    stale.write_bytes(b"stale")

    with patch.dict(
        os.environ,
        {"LOCALAPPDATA": str(tmp_path), "MAESTRI_CLI": ""},
        clear=False,
    ), patch("sentra_cli.config.shutil.which", return_value=str(stale)):
        assert find_maestri_cli() == str(installed.resolve())


# ---------------------------------------------------------------------------
# 2. Maestri Bridge Fail-soft Tests
# ---------------------------------------------------------------------------
def test_maestri_bridge_fail_soft_without_pipe(tmp_path: Path):
    with patch.dict(os.environ, {}, clear=True):
        cfg = CLIConfig(
            workspace=tmp_path,
            maestri_pipe=None,
            openai_api_key="none",
        )
        bridge = MaestriBridge(cfg)
        assert not bridge.is_connected

        # Calling any maestri command without active pipe must return a clean message, NOT raise/crash
        res = bridge.list_peers()
        assert "unavailable" in res.lower() or "not running" in res.lower()

        res = bridge.ask("other_agent", "Hello!")
        assert "unavailable" in res.lower() or "not running" in res.lower()

        res = bridge.check("other_agent")
        assert "unavailable" in res.lower() or "not running" in res.lower()

        res = bridge.note_read("note_1")
        assert "unavailable" in res.lower() or "not running" in res.lower()

        res = bridge.note_write("note_1", "Test content")
        assert "unavailable" in res.lower() or "not running" in res.lower()


def test_maestri_bridge_execution_with_cli(tmp_path: Path):
    mock_cli = tmp_path / "mock-maestri.exe"
    mock_cli.write_text("mock binary", encoding="utf-8")
    cfg = CLIConfig(
        workspace=tmp_path,
        maestri_pipe=r"\\.\pipe\mock-pipe",
        maestri_terminal_id="terminal-test",
        maestri_workspace_id="workspace-test",
        maestri_cli_path=str(mock_cli),
    )
    bridge = MaestriBridge(cfg)
    assert bridge.is_connected
    assert bridge.is_available

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Agent-1 (online)\nAgent-2 (idle)",
            stderr="",
        )
        res = bridge.list_peers()
        assert "Agent-1" in res
        mock_run.assert_called_once()


def test_maestri_dispatch_is_non_blocking(tmp_path: Path):
    mock_cli = tmp_path / "mock-maestri.exe"
    mock_cli.write_text("mock binary", encoding="utf-8")
    cfg = CLIConfig(
        workspace=tmp_path,
        maestri_pipe=r"\\.\pipe\mock-pipe",
        maestri_terminal_id="terminal-test",
        maestri_workspace_id="workspace-test",
        maestri_cli_path=str(mock_cli),
    )
    bridge = MaestriBridge(cfg)

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=4242)
        result = bridge.dispatch_ask("Researcher", "inspect the module")

    assert "background" in result.lower()
    assert "4242" in result
    args, kwargs = mock_popen.call_args
    assert args[0] == [
        str(mock_cli),
        "ask",
        "Researcher",
        "inspect the module",
    ]
    assert kwargs["stdin"] is not None
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert kwargs["env"]["MAESTRI_TERMINAL_ID"] == "terminal-test"


def test_agent_maestri_dispatch_routes_without_waiting(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path)
    agent = SentraAgent(cfg)
    agent.maestri.dispatch_ask = MagicMock(return_value="queued")

    result = agent.execute_directive(
        "MAESTRI",
        "dispatch|Researcher|verify the implementation",
    )

    assert result == "queued"
    agent.maestri.dispatch_ask.assert_called_once_with(
        "Researcher", "verify the implementation"
    )


# ---------------------------------------------------------------------------
# 3. Tool Executor Tests (Sandboxed Workspace)
# ---------------------------------------------------------------------------
def test_tool_file_operations(tmp_path: Path):
    # 1. Write file
    target = "test_dir/hello.py"
    write_res = write_file(tmp_path, target, "print('hello sentra')\n")
    assert "Successfully wrote" in write_res
    assert (tmp_path / target).is_file()

    # 2. Read file
    content = read_file(tmp_path, target)
    assert "print('hello sentra')" in content

    # 3. Prevent path traversal outside workspace
    traversal_res = read_file(tmp_path, "../../../secret.txt")
    assert "denied" in traversal_res.lower() or "error" in traversal_res.lower()

    # 4. List files
    file_list = list_files(tmp_path)
    assert "test_dir" in file_list
    dir_files = list_files(tmp_path, "test_dir")
    assert "hello.py" in dir_files


def test_tool_patch_operations(tmp_path: Path):
    file_path = tmp_path / "code.py"
    file_path.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    # Unified diff format patch
    diff = """--- a/code.py
+++ b/code.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
    patch_res = apply_patch(tmp_path, diff)
    assert "success" in patch_res.lower() or "applied" in patch_res.lower()

    updated = file_path.read_text(encoding="utf-8")
    assert "return a + b" in updated


def test_tool_git_status_and_diff(tmp_path: Path):
    # Even if not a git repository, must return clean message, never crash
    diff = git_diff(tmp_path)
    assert isinstance(diff, str)

    status = git_status(tmp_path)
    assert isinstance(status, str)


# ---------------------------------------------------------------------------
# 4. Agent Directive Parsing & Execution Tests
# ---------------------------------------------------------------------------
def test_agent_directive_parser(tmp_path: Path):
    response_text = """
Eu vou inspecionar o arquivo e aplicar uma correção:
[[R|src/main.py|1|50]]

E depois rodar os testes:
[[TEST|tests/test_main.py]]

Também vou enviar uma mensagem ao Maestri:
[[MAESTRI|ask|Researcher|Qual o status do modulo X?]]
"""
    matches = DIRECTIVE_RE.findall(response_text)
    assert len(matches) == 3

    assert matches[0][0] == "R"
    assert "src/main.py" in matches[0][1]

    assert matches[1][0] == "TEST"
    assert "tests/test_main.py" in matches[1][1]

    assert matches[2][0] == "MAESTRI"
    assert "ask|Researcher" in matches[2][1]


def test_agent_execute_directive_and_observation(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path)
    agent = SentraAgent(cfg)

    # Write a test file via directive
    obs_write = agent.execute_directive("W", "sample.txt|Hello world!")
    assert "Successfully wrote" in obs_write
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "Hello world!"

    # Read back via directive
    obs_read = agent.execute_directive("R", "sample.txt|1|10")
    assert "Hello world!" in obs_read


def test_agent_maestri_exec_routes_full_surface(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path)
    agent = SentraAgent(cfg)
    agent.maestri.command = MagicMock(return_value="portal-ok")

    payload = "exec|portal|snapshot|App"
    result = agent.execute_directive("MAESTRI", payload)

    assert result == "portal-ok"
    agent.maestri.command.assert_called_once_with(
        "portal",
        "snapshot",
        "App",
        timeout=180.0,
        allow_destructive=False,
    )


# ---------------------------------------------------------------------------
# 5. ModelClient Cascade Fallback Tests
# ---------------------------------------------------------------------------
def test_model_client_fallback_logic(tmp_path: Path):
    # Setup client with unreachable gateway and no api keys
    with patch.dict(os.environ, {}, clear=True):
        cfg = CLIConfig(
            workspace=tmp_path,
            gateway_url="http://127.0.0.1:59999/v1",  # Guaranteed closed port
            local_base_url="http://127.0.0.1:59998/v1",
            openai_api_key="none",
            auto_start_gateway=False,
        )
        client = ModelClient(cfg)

        # Health probe should return all False gracefully without raising
        health = client.probe_health()
        assert not health["gateway"]
        assert not health["openai"]
        assert not health["local"]

        # Chat execution should cascade and handle error cleanly
        messages = [{"role": "user", "content": "Ping"}]
        result_stream = list(client.chat_stream(messages, model_override="gpt-4o"))
        combined = "".join(result_stream)
        assert (
            "No model provider is ready" in combined
            or "não foi possível" in combined.lower()
        )


class _FakeSentraGatewayHandler(BaseHTTPRequestHandler):
    last_path = ""
    last_body: dict[str, object] = {}
    last_turn_header = ""
    requests: list[dict[str, object]] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(
                200,
                {
                    "service": "sentra-model-gateway",
                    "status": "ok",
                    "ready": True,
                    "catalog": {
                        "status": "ready",
                        "models": [{"id": "sentra/chatgpt-web/high"}],
                    },
                    "upstream": {
                        "status": "ok",
                        "accepting_turns": True,
                    },
                },
            )
            return
        if self.path == "/v1/models":
            self._send_json(
                200,
                {
                    "data": [
                        {
                            "id": "sentra/chatgpt-web/high",
                            "object": "model",
                        }
                    ]
                },
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length") or "0")
        body = json.loads(self.rfile.read(size) or b"{}")
        type(self).last_path = self.path
        type(self).last_body = body
        type(self).last_turn_header = (
            self.headers.get("x-codex-turn-metadata") or ""
        )
        type(self).requests.append(
            {
                "path": self.path,
                "body": body,
                "turn_header": type(self).last_turn_header,
            }
        )
        if self.path != "/v1/responses":
            self._send_json(404, {"error": "not found"})
            return
        raw = (
            'event: response.output_text.delta\n'
            'data: {"type":"response.output_text.delta","delta":"OK"}\n\n'
            'event: response.completed\n'
            'data: {"type":"response.completed","response":{"status":"completed","model":"chatgpt-web/high"}}\n\n'
            'data: [DONE]\n\n'
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_model_client_uses_responses_api_for_gateway(tmp_path: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeSentraGatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        cfg = CLIConfig(
            workspace=tmp_path,
            gateway_url=f"http://127.0.0.1:{port}/v1",
            model="sentra/chatgpt-web/high",
            local_base_url="http://127.0.0.1:59998/v1",
            openai_api_key="none",
            auto_start_gateway=False,
        )
        _FakeSentraGatewayHandler.requests = []
        client = ModelClient(cfg)
        with patch.object(client, "_browser_host_ready", return_value=True):
            result = "".join(
                client.chat_stream([{"role": "user", "content": "Ping"}])
            )
            result2 = "".join(
                client.chat_stream([{"role": "user", "content": "Ping 2"}])
            )
        assert result == "OK"
        assert result2 == "OK"
        assert _FakeSentraGatewayHandler.last_path == "/v1/responses"
        assert _FakeSentraGatewayHandler.last_body["model"] == (
            "sentra/chatgpt-web/high"
        )
        assert "input" in _FakeSentraGatewayHandler.last_body

        first, second = _FakeSentraGatewayHandler.requests[-2:]
        first_body = first["body"]
        second_body = second["body"]
        assert isinstance(first_body, dict)
        assert isinstance(second_body, dict)
        first_meta = json.loads(str(first["turn_header"]))
        second_meta = json.loads(str(second["turn_header"]))
        assert first_meta["request_kind"] == "turn"
        assert first_meta["thread_id"] == second_meta["thread_id"]
        assert first_meta["turn_id"] != second_meta["turn_id"]
        client_meta = first_body["client_metadata"]
        assert isinstance(client_meta, dict)
        assert (
            client_meta["x-codex-turn-metadata"]
            == first["turn_header"]
        )
        assert str(client_meta["sentra_conversation_uri"]).startswith(
            "conversation://sentra-cli/"
        )
        assert first_body["prompt_cache_key"] == first_meta["thread_id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_maestri_full_surface_exec_preserves_terminal_context(tmp_path: Path):
    mock_cli = tmp_path / "mock-maestri.exe"
    mock_cli.write_text("mock binary", encoding="utf-8")
    cfg = CLIConfig(
        workspace=tmp_path,
        maestri_pipe=r"\\.\pipe\mock-pipe",
        maestri_terminal_id="terminal-test",
        maestri_workspace_id="workspace-test",
        maestri_cli_path=str(mock_cli),
        openai_api_key="none",
    )
    bridge = MaestriBridge(cfg)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="snapshot-ok",
            stderr="",
        )
        result = bridge.execute_json('["portal","snapshot","App"]')
        assert result == "snapshot-ok"
        args, kwargs = mock_run.call_args
        assert args[0][1:] == ["portal", "snapshot", "App"]
        env = kwargs["env"]
        assert env["MAESTRI_PIPE"] == r"\\.\pipe\mock-pipe"
        assert env["MAESTRI_TERMINAL_ID"] == "terminal-test"
        assert env["MAESTRI_WORKSPACE_ID"] == "workspace-test"


def test_agent_maestri_exec_pipe_surface(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    agent = SentraAgent(cfg)
    agent.maestri = MagicMock()
    agent.maestri.command.return_value = "snapshot-ok"

    directive = '[[MAESTRI|exec|portal|snapshot|App]]'
    match = DIRECTIVE_RE.fullmatch(directive)
    assert match is not None
    assert match.group(2) == "exec|portal|snapshot|App"

    result = agent.execute_directive("MAESTRI", match.group(2) or "")
    assert result == "snapshot-ok"
    agent.maestri.command.assert_called_once_with(
        "portal",
        "snapshot",
        "App",
        timeout=180.0,
        allow_destructive=False,
    )


def test_maestri_destructive_command_requires_confirmation(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    bridge = MaestriBridge(cfg)
    bridge.run_cmd = MagicMock(return_value={"ok": True, "stdout": "removed"})

    denied = bridge.command("dismiss", "Peer")
    assert "--confirm" in denied
    bridge.run_cmd.assert_not_called()

    allowed = bridge.command(
        "dismiss",
        "Peer",
        allow_destructive=True,
    )
    assert allowed == "removed"
    bridge.run_cmd.assert_called_once_with(["dismiss", "Peer"], timeout=60.0)


def test_agent_maestri_exec_confirm_is_forwarded(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    agent = SentraAgent(cfg)
    agent.maestri = MagicMock()
    agent.maestri.command.return_value = "removed"

    result = agent.execute_directive(
        "MAESTRI",
        "exec|dismiss|Peer|--confirm",
    )
    assert result == "removed"
    agent.maestri.command.assert_called_once_with(
        "dismiss",
        "Peer",
        timeout=180.0,
        allow_destructive=True,
    )


# ---------------------------------------------------------------------------
# 6. Global Non-Regression Check
# ---------------------------------------------------------------------------
def test_user_codex_config_toml_is_preserved(tmp_path: Path):
    """Constructing SENTRA CLI config must never mutate the user's Codex config.

    codex-chatgpt-web may intentionally own a global openai_base_url while its
    route is connected, so asserting that the key never exists is incorrect.
    The CLI invariant is non-mutation of the user's existing route/config.
    """
    codex_config_path = Path.home() / ".codex" / "config.toml"
    if not codex_config_path.is_file():
        return

    before = codex_config_path.read_bytes()
    CLIConfig(workspace=tmp_path)
    after = codex_config_path.read_bytes()

    assert after == before

def test_sentra_cli_runtime_dependencies_are_locked() -> None:
    root = Path(__file__).resolve().parents[2]
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    lock = (root / "requirements.lock.txt").read_text(encoding="utf-8")

    assert "rich>=15.0,<16" in requirements
    assert (
        "rich==15.0.0 --hash=sha256:"
        "33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb"
    ) in lock
    assert (
        "markdown-it-py==4.2.0 --hash=sha256:"
        "9f7ebbcd14fe59494226453aed97c1070d83f8d24b6fc3a3bcf9a38092641c4a"
    ) in lock
    assert (
        "mdurl==0.1.2 --hash=sha256:"
        "84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8"
    ) in lock

def test_frozen_cli_spawns_internal_gateway_service(tmp_path: Path) -> None:
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    client = ModelClient(cfg)
    process = MagicMock(pid=4321)

    with patch.object(sys, "frozen", True, create=True), patch(
        "sentra_cli.client.subprocess.Popen",
        return_value=process,
    ) as popen:
        result = client._spawn_gateway()

    assert result == "gateway pid=4321"
    args, kwargs = popen.call_args
    assert args[0] == [
        sys.executable,
        "--gateway-service",
    ]
    assert kwargs["cwd"] == str(Path(sys.executable).resolve().parent)


def test_headless_upstream_uses_runtime_serve(tmp_path: Path) -> None:
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    client = ModelClient(cfg)
    runtime_root = tmp_path / "runtime-bundle"
    runtime_cli = runtime_root / "bin" / "codex-chatgpt-web.cmd"
    bun = runtime_root / "runtime" / (
        "bun.exe" if os.name == "nt" else "bun"
    )
    app = runtime_root / "app" / "cli.js"
    for path in (runtime_cli, bun, app):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")
    pid_file = tmp_path / "headless.pid"
    process = MagicMock(pid=7777)

    with patch.object(
        client,
        "_upstream_ready",
        return_value=False,
    ), patch.object(
        client,
        "_web_runtime_cli_path",
        return_value=runtime_cli,
    ), patch.object(
        client,
        "_headless_pid_path",
        return_value=pid_file,
    ), patch.object(
        client,
        "_turn_authority_token",
        return_value="t" * 64,
    ), patch.object(
        client,
        "_browser_relay_token_file",
        return_value=None,
    ), patch(
        "sentra_cli.client.subprocess.Popen",
        return_value=process,
    ) as popen:
        result = client._spawn_headless_upstream()

    assert result == "upstream pid=7777"
    state = json.loads(pid_file.read_text(encoding="utf-8"))
    assert state["pid"] == 7777
    assert state["executable"] == str(bun.resolve())
    args, kwargs = popen.call_args
    assert args[0] == [str(bun), str(app), "serve"]
    assert kwargs["cwd"] == str(runtime_root)
    assert kwargs["env"]["SENTRA_WEB_GATEWAY_URL"] == client._gateway_origin() + "/v1"
    assert kwargs["env"]["SENTRA_TURN_AUTHORITY_URL"] == client._gateway_origin()
    assert kwargs["env"]["SENTRA_TURN_AUTHORITY_TOKEN"] == "t" * 64
    assert kwargs["env"]["SENTRA_MANAGED_TUNNEL"] == "1"
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None


def test_ensure_gateway_ready_never_starts_electron(tmp_path: Path) -> None:
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    client = ModelClient(cfg)
    initial = {
        "reachable": True,
        "turn_ready": False,
        "ready": False,
        "status_code": 503,
        "catalog_ready": True,
        "upstream_status": "unavailable",
        "launcher": {"running": False, "pid": None, "source": "none"},
        "error": None,
        "payload": {},
    }
    ready = {
        **initial,
        "turn_ready": True,
        "ready": True,
        "status_code": 200,
        "upstream_status": "ok",
    }

    client.gateway_status = MagicMock(side_effect=[initial, ready])
    client._upstream_ready = MagicMock(return_value=False)
    client._spawn_gateway = MagicMock(return_value="unexpected")
    client._spawn_headless_upstream = MagicMock(
        return_value="upstream pid=123"
    )
    client._gateway_admin_post = MagicMock()

    with patch("sentra_cli.client.time.sleep", return_value=None):
        result = client.ensure_gateway_ready(wait_s=1.0)

    assert result["turn_ready"] is True
    assert "upstream pid=123" in result["action"]
    client._spawn_gateway.assert_not_called()
    client._spawn_headless_upstream.assert_called_once_with()
    client._gateway_admin_post.assert_not_called()


def test_internal_gateway_service_restores_sys_argv() -> None:
    from sentra_cli import __main__ as cli_main

    original = sys.argv[:]
    fake_client = MagicMock()
    fake_client._spawn_headless_upstream.return_value = "upstream pid=1234"
    with patch(
        "sentra_model_gateway.gateway.main",
        return_value=None,
    ) as gateway_main, patch(
        "sentra_cli.client.ModelClient",
        return_value=fake_client,
    ):
        result = cli_main._run_gateway_service(["--launch-upstream"])

    assert result == 0
    gateway_main.assert_called_once_with()
    fake_client._spawn_headless_upstream.assert_called_once_with()
    fake_client._stop_headless_upstream.assert_called_once_with()
    assert sys.argv == original

def test_frozen_gateway_layout_matches_installed_commander(tmp_path: Path) -> None:
    from sentra_cli import __main__ as cli_main

    install_dir = tmp_path / "Commander"
    executable = install_dir / "sentra-cli.exe"
    actual_install, checkout, launcher = cli_main._frozen_gateway_layout(
        str(executable)
    )

    assert actual_install == install_dir.resolve()
    assert checkout == install_dir.resolve() / "third_party" / "codex-chatgpt-web"
    assert launcher == (
        install_dir.resolve()
        / "web-models"
        / "win-unpacked"
        / "Codex Web GPT.exe"
    )


def test_frozen_gateway_service_uses_headless_upstream(tmp_path: Path) -> None:
    from sentra_cli import __main__ as cli_main

    install_dir = tmp_path / "Commander"
    executable = install_dir / "sentra-cli.exe"
    launcher = (
        install_dir / "web-models" / "win-unpacked" / "Codex Web GPT.exe"
    )
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"test")
    state_dir = tmp_path / "state"

    fake_server = MagicMock()
    fake_server.serve_forever.side_effect = KeyboardInterrupt
    fake_paths = MagicMock(state_dir=state_dir)
    fake_client = MagicMock()
    fake_client._spawn_headless_upstream.return_value = "upstream pid=5678"

    with patch.object(sys, "executable", str(executable)), patch(
        "sentra_model_gateway.gateway.GatewayServer",
        return_value=fake_server,
    ) as server_cls, patch(
        "sentra_model_gateway.gateway.load_or_create_gateway_admin_token",
        return_value="a" * 64,
    ), patch(
        "sentra_remote.product.ProductPaths.default",
        return_value=fake_paths,
    ), patch(
        "sentra_cli.client.ModelClient",
        return_value=fake_client,
    ):
        result = cli_main._run_frozen_gateway_service(
            ["--port", "17852", "--launch-upstream"]
        )

    assert result == 0
    config = server_cls.call_args.args[0]
    assert config.port == 17852
    assert config.checkout == install_dir.resolve() / "third_party" / "codex-chatgpt-web"
    assert config.launcher_executable == launcher.resolve()
    assert config.state_root == state_dir
    fake_client._spawn_headless_upstream.assert_called_once_with()
    fake_client._stop_headless_upstream.assert_called_once_with()
    fake_server.launcher.start.assert_not_called()
    fake_server.start_upstream_watchdog.assert_not_called()
    fake_server.server_close.assert_called_once_with()

def test_browser_host_ready_adopts_compatible_existing_launcher(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    client = ModelClient(cfg)
    exe = tmp_path / "Codex Web GPT.exe"
    helper = tmp_path / "browser-helper.cjs"
    descriptor = tmp_path / "launcher-browser.json"
    exe.write_bytes(b"exe")
    helper.write_text("helper", encoding="utf-8")
    descriptor.write_text(
        json.dumps({
            "version": 3,
            "kind": "codex-web-gpt-launcher",
            "pid": 1234,
            "endpoint": "http://127.0.0.1:62079",
            "helper": {"executable": str(exe), "script": str(helper)},
            "sentraManaged": False,
        }),
        encoding="utf-8",
    )
    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({
        "webSocketDebuggerUrl": "ws://127.0.0.1:62079/devtools/browser/test"
    }).encode()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    with patch.object(client, "_browser_descriptor_path", return_value=descriptor), patch.object(
        client, "_browser_host_executable_path", return_value=exe
    ), patch.object(client, "_pid_running", return_value=True), patch(
        "sentra_cli.client.urllib.request.urlopen", return_value=response
    ):
        assert client._browser_host_ready() is True

def test_stop_browser_host_refuses_unmanaged_descriptor(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    client = ModelClient(cfg)
    exe = tmp_path / "Codex Web GPT.exe"
    helper = tmp_path / "browser-helper.cjs"
    descriptor = tmp_path / "launcher-browser.json"
    exe.write_bytes(b"exe")
    helper.write_text("helper", encoding="utf-8")
    descriptor.write_text(json.dumps({
        "version": 3,
        "kind": "codex-web-gpt-launcher",
        "pid": 1234,
        "helper": {"executable": str(exe), "script": str(helper)},
        "sentraManaged": False,
    }), encoding="utf-8")
    with patch.object(client, "_browser_descriptor_path", return_value=descriptor), patch.object(
        client, "_browser_host_executable_path", return_value=exe
    ), patch("sentra_cli.client.subprocess.run") as run:
        assert client._stop_browser_host() == "browser-host-not-owned"
        run.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows ownership verification path")
def test_stop_browser_host_stops_matching_sentra_owned_process(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    client = ModelClient(cfg)
    exe = tmp_path / "Codex Web GPT.exe"
    helper = tmp_path / "browser-helper.cjs"
    descriptor = tmp_path / "launcher-browser.json"
    exe.write_bytes(b"exe")
    helper.write_text("helper", encoding="utf-8")
    descriptor.write_text(json.dumps({
        "version": 3,
        "kind": "codex-web-gpt-launcher",
        "pid": 4321,
        "helper": {"executable": str(exe), "script": str(helper)},
        "sentraManaged": True,
    }), encoding="utf-8")
    inspect = MagicMock(returncode=0, stdout=str(exe) + "\n", stderr="")
    stopped = MagicMock(returncode=0, stdout="stopped", stderr="")
    with patch.object(client, "_browser_descriptor_path", return_value=descriptor), patch.object(
        client, "_browser_host_executable_path", return_value=exe
    ), patch.object(client, "_pid_running", return_value=True), patch(
        "sentra_cli.client.subprocess.run", side_effect=[inspect, stopped]
    ) as run:
        assert client._stop_browser_host() == "browser-host-stopped pid=4321"
    assert run.call_count == 2
    assert descriptor.exists() is False

def test_one_shot_returns_nonzero_when_provider_failed(tmp_path: Path) -> None:
    from sentra_cli import __main__ as cli_main

    fake_repl = MagicMock()
    fake_repl.agent.client.last_error = "gateway failed"
    with patch("sentra_cli.__main__.SentraREPL", return_value=fake_repl):
        result = cli_main.main(["--workspace", str(tmp_path), "-p", "Ping"])

    assert result == 1
    fake_repl.run_one_shot.assert_called_once_with("Ping")

def test_one_shot_returns_zero_when_provider_succeeds(tmp_path: Path) -> None:
    from sentra_cli import __main__ as cli_main

    fake_repl = MagicMock()
    fake_repl.agent.client.last_error = None
    with patch("sentra_cli.__main__.SentraREPL", return_value=fake_repl):
        result = cli_main.main(["--workspace", str(tmp_path), "-p", "Ping"])

    assert result == 0

def test_maestri_orchestration_intent_is_explicit_and_conservative() -> None:
    assert SentraAgent.wants_maestri_orchestration(
        "Você está num terminal dentro do Maestri, como mestre. "
        "Por gentileza gerencie outros terminais e crie a melhor colaboração "
        "para atuação nesse repositório"
    ) is True
    assert SentraAgent.wants_maestri_orchestration(
        "Coordene os agentes no Maestri para trabalhar neste repositório"
    ) is True
    assert SentraAgent.wants_maestri_orchestration(
        "Como gerenciar agentes no Maestri?"
    ) is False
    assert SentraAgent.wants_maestri_orchestration(
        "Explique o que é o Maestri"
    ) is False


def test_maestri_worker_command_uses_installed_cli_outside_sentra_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    maestri_cli = tmp_path / "maestri.exe"
    maestri_cli.write_bytes(b"stub")
    installed_cli = (
        tmp_path / "localappdata" / "SENTRA" / "Commander" / "sentra-cli.exe"
    )
    installed_cli.parent.mkdir(parents=True)
    installed_cli.write_bytes(b"stub")
    cfg = CLIConfig(
        workspace=workspace,
        openai_api_key="none",
        maestri_cli_path=str(maestri_cli),
    )
    bridge = MaestriBridge(cfg)

    with patch.dict(
        os.environ,
        {"LOCALAPPDATA": str(tmp_path / "localappdata")},
        clear=False,
    ):
        command = bridge._worker_command()

    assert str(installed_cli.resolve()) in command
    assert str(workspace) not in command


def test_maestri_worker_command_supports_fast_model_override_and_bounded_timeout(
    tmp_path: Path,
) -> None:
    maestri_cli = tmp_path / "maestri.exe"
    maestri_cli.write_bytes(b"stub")
    (tmp_path / "sentra-cli.cmd").write_text("@echo off\n", encoding="utf-8")
    cfg = CLIConfig(
        workspace=tmp_path,
        openai_api_key="none",
        maestri_cli_path=str(maestri_cli),
    )
    bridge = MaestriBridge(cfg)

    with patch.dict(
        os.environ,
        {
            "SENTRA_MAESTRI_WORKER_MODEL": "sentra/gemini-web/flash",
            "SENTRA_MAESTRI_WORKER_TIMEOUT": "999",
        },
        clear=False,
    ):
        command = bridge._worker_command()

    assert "--model sentra/gemini-web/flash" in command
    assert "--timeout 55" in command


def test_maestri_orchestrate_repository_recruits_links_and_dispatches(
    tmp_path: Path,
) -> None:
    cli = tmp_path / "maestri.exe"
    cli.write_bytes(b"stub")
    (tmp_path / "sentra-cli.cmd").write_text("@echo off\n", encoding="utf-8")
    cfg = CLIConfig(
        workspace=tmp_path,
        openai_api_key="none",
        maestri_pipe=r"\\.\pipe\maestri-test",
        maestri_terminal_id="terminal-test",
        maestri_workspace_id="workspace-test",
        maestri_cli_path=str(cli),
    )
    bridge = MaestriBridge(cfg)
    bridge.list_peers = MagicMock(return_value='You:\n  - name: "SENTRA", maestro: true')
    bridge.recruit = MagicMock(side_effect=[
        'Recruited "SENTRA-Implementation".',
        'Recruited "SENTRA-Review".',
    ])
    bridge.connect = MagicMock(return_value="Connected.")
    bridge.dispatch_terminal_submit = MagicMock(
        side_effect=["impl submitted", "review submitted"]
    )

    result = bridge.orchestrate_repository("Melhorar o SENTRA CLI")

    assert "collaboration started" in result.lower()
    assert bridge.recruit.call_count == 2
    bridge.recruit.assert_any_call(
        "SENTRA-Implementation",
        directory=str(tmp_path),
        command=r".\sentra-cli.cmd --model sentra/chatgpt-web/gpt-5.6-sol-instant --timeout 50",
    )
    bridge.recruit.assert_any_call(
        "SENTRA-Review",
        directory=str(tmp_path),
        command=r".\sentra-cli.cmd --model sentra/chatgpt-web/gpt-5.6-sol-instant --timeout 50",
    )
    bridge.connect.assert_called_once_with(
        "SENTRA-Implementation",
        "SENTRA-Review",
    )
    assert bridge.dispatch_terminal_submit.call_count == 2
    calls = {
        call.args[0]: call.args[1]
        for call in bridge.dispatch_terminal_submit.call_args_list
    }
    assert set(calls) == {"SENTRA-Implementation", "SENTRA-Review"}
    assert "Melhorar o SENTRA CLI" in calls["SENTRA-Implementation"]
    assert "Melhorar o SENTRA CLI" in calls["SENTRA-Review"]


def test_maestri_orchestrate_repository_reuses_existing_workers(
    tmp_path: Path,
) -> None:
    cli = tmp_path / "maestri.exe"
    cli.write_bytes(b"stub")
    cfg = CLIConfig(
        workspace=tmp_path,
        openai_api_key="none",
        maestri_pipe=r"\\.\pipe\maestri-test",
        maestri_terminal_id="terminal-test",
        maestri_workspace_id="workspace-test",
        maestri_cli_path=str(cli),
    )
    bridge = MaestriBridge(cfg)
    bridge.list_peers = MagicMock(return_value=(
        'You:\n  - name: "SENTRA", maestro: true\n\nConnected agents:\n'
        '  - name: "SENTRA-Implementation"\n'
        '  - name: "SENTRA-Review"'
    ))
    bridge.recruit = MagicMock()
    bridge.connect = MagicMock(return_value="Already connected.")
    bridge.dispatch_terminal_submit = MagicMock(
        side_effect=["impl submitted", "review submitted"]
    )

    result = bridge.orchestrate_repository("Continuar o trabalho")

    assert "already connected" in result
    bridge.recruit.assert_not_called()
    bridge.connect.assert_called_once()
    assert bridge.dispatch_terminal_submit.call_count == 2

def test_dispatch_terminal_submit_appends_enter_atomically(tmp_path: Path) -> None:
    cli = tmp_path / "maestri.exe"
    cli.write_bytes(b"stub")
    cfg = CLIConfig(
        workspace=tmp_path,
        openai_api_key="none",
        maestri_pipe=r"\\.\pipe\maestri-test",
        maestri_terminal_id="terminal-test",
        maestri_workspace_id="workspace-test",
        maestri_cli_path=str(cli),
    )
    bridge = MaestriBridge(cfg)
    bridge.run_cmd = MagicMock(
        return_value={"ok": True, "stdout": "typed", "stderr": "", "exit_code": 0}
    )
    bridge._dispatch_background = MagicMock(return_value="dispatched pid=99")

    result = bridge.dispatch_terminal_submit(
        "SENTRA-Implementation",
        "linha 1\npath C:\\tmp",
    )

    assert "terminal submit dispatched" in result
    bridge.run_cmd.assert_called_once_with([
        "ask",
        "SENTRA-Implementation",
        "--raw",
        r"linha 1\npath C:\\tmp",
    ], timeout=8.0)
    bridge._dispatch_background.assert_called_once_with([
        "ask",
        "SENTRA-Implementation",
        "--raw",
        r"\n",
    ])

def test_maestri_terminal_submit_appends_enter_atomically(tmp_path: Path) -> None:
    cli = tmp_path / "maestri.exe"
    cli.write_bytes(b"stub")
    cfg = CLIConfig(
        workspace=tmp_path,
        openai_api_key="none",
        maestri_pipe=r"\\.\pipe\maestri-test",
        maestri_terminal_id="terminal-test",
        maestri_workspace_id="workspace-test",
        maestri_cli_path=str(cli),
    )
    bridge = MaestriBridge(cfg)
    bridge.run_cmd = MagicMock(
        return_value={"ok": True, "stdout": "typed", "stderr": "", "exit_code": 0}
    )
    bridge._dispatch_background = MagicMock(return_value="dispatched pid=9001")

    result = bridge.dispatch_terminal_submit(
        "SENTRA-Implementation",
        "linha 1\nlinha 2",
    )

    assert "9001" in result
    bridge.run_cmd.assert_called_once_with([
        "ask",
        "SENTRA-Implementation",
        "--raw",
        r"linha 1\nlinha 2",
    ], timeout=8.0)
    bridge._dispatch_background.assert_called_once_with([
        "ask",
        "SENTRA-Implementation",
        "--raw",
        r"\n",
    ])

def test_background_job_submit_returns_immediate_ack(tmp_path: Path) -> None:
    manager = BackgroundJobManager(tmp_path)
    fake_process = MagicMock(pid=2468)
    with patch("sentra_cli.jobs.subprocess.Popen", return_value=fake_process):
        ack = manager.submit("BUILD", timeout=180.0)

    assert ack.startswith("ACK job=")
    assert "state=QUEUED" in ack
    assert "operation=BUILD" in ack
    assert "pid=2468" in ack
    jobs = list((tmp_path / ".sentra" / "cli-jobs").glob("job-*.json"))
    assert len(jobs) == 1
    payload = json.loads(jobs[0].read_text(encoding="utf-8"))
    assert payload["state"] == "QUEUED"
    assert payload["operation"] == "BUILD"


def test_background_job_worker_persists_success(tmp_path: Path) -> None:
    spec = tmp_path / "job-test.json"
    spec.write_text(json.dumps({
        "version": 1,
        "job_id": "job-test",
        "operation": "TEST",
        "raw_args": "tests/unit/test_example.py",
        "workspace": str(tmp_path),
        "state": "QUEUED",
        "created_at": 0.0,
        "started_at": None,
        "finished_at": None,
        "pid": None,
        "result": None,
        "error": None,
    }), encoding="utf-8")

    with patch(
        "sentra_cli.jobs.run_tests",
        return_value="Test status: PASSED\n\n1 passed",
    ):
        code = run_job_file(spec)

    assert code == 0
    payload = json.loads(spec.read_text(encoding="utf-8"))
    assert payload["state"] == "SUCCEEDED"
    assert payload["pid"] == os.getpid()
    assert "1 passed" in payload["result"]
    assert payload["finished_at"] is not None


def test_agent_async_tool_ack_stops_same_turn_model_loop(tmp_path: Path) -> None:
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    agent = SentraAgent(cfg)
    agent.client.chat_stream = MagicMock(
        return_value=iter(["Vou validar agora. [[BUILD]]"])
    )
    agent.jobs.submit = MagicMock(
        return_value=(
            "ACK job=job-fast state=QUEUED operation=BUILD pid=99. "
            "Disparado em background; use /job job-fast ou /jobs."
        )
    )
    results: list[str] = []

    chunks = list(agent.step_stream(
        "faca o build",
        on_tool_result=results.append,
    ))

    assert agent.client.chat_stream.call_count == 1
    agent.jobs.submit.assert_called_once()
    assert any("ACK job=job-fast" in item for item in results)
    assert "Vou validar agora." in "".join(chunks)

def test_background_job_worker_uses_inprocess_pytest_when_frozen(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "job-frozen.json"
    spec.write_text(json.dumps({
        "version": 1,
        "job_id": "job-frozen",
        "operation": "TEST",
        "raw_args": "tests/unit/test_example.py",
        "workspace": str(tmp_path),
        "state": "QUEUED",
        "created_at": 0.0,
        "started_at": None,
        "finished_at": None,
        "pid": None,
        "result": None,
        "error": None,
    }), encoding="utf-8")

    with patch.object(sys, "frozen", True, create=True), patch(
        "sentra_cli.jobs._run_frozen_pytest",
        return_value="Test status: PASSED\n\nfrozen ok",
    ) as frozen_pytest, patch("sentra_cli.jobs.run_tests") as run_tests_mock:
        code = run_job_file(spec)

    assert code == 0
    frozen_pytest.assert_called_once_with(
        tmp_path.resolve(),
        "tests/unit/test_example.py",
    )
    run_tests_mock.assert_not_called()
    payload = json.loads(spec.read_text(encoding="utf-8"))
    assert payload["state"] == "SUCCEEDED"
    assert "frozen ok" in payload["result"]

def test_maestri_worker_command_caps_turn_timeout(tmp_path: Path) -> None:
    cli = tmp_path / "maestri.exe"
    cli.write_bytes(b"stub")
    (tmp_path / "sentra-cli.cmd").write_text("@echo off\n", encoding="utf-8")
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none", maestri_cli_path=str(cli))
    bridge = MaestriBridge(cfg)

    command = bridge._worker_command()

    assert "--model sentra/chatgpt-web/gpt-5.6-sol-instant" in command
    assert "--timeout 50" in command


def test_responses_stream_enforces_absolute_deadline(tmp_path: Path) -> None:
    cfg = CLIConfig(
        workspace=tmp_path,
        openai_api_key="none",
        timeout_s=55.0,
    )
    client = ModelClient(cfg)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            yield b'event: response.heartbeat\n'

    with patch("sentra_cli.client.urllib.request.urlopen", return_value=FakeResponse()), patch(
        "sentra_cli.client.time.monotonic",
        side_effect=[100.0, 156.0],
    ), patch.object(
        client,
        "_interrupt_web_turn",
        return_value=(True, "ok"),
    ) as interrupt:
        with pytest.raises(Exception, match="turn deadline exceeded after 55.0s"):
            list(client._responses_stream([{"role": "user", "content": "ping"}], cfg.model))

    interrupt.assert_called_once()
    assert str(interrupt.call_args.args[0]).startswith("sentra-cli-turn-")

def test_chatgpt_web_rejected_preflight_error_is_concise_and_not_uncertain(tmp_path: Path) -> None:
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    client = ModelClient(cfg)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            yield b"event: response.failed\n"
            yield (b'data: {"type":"response.failed","response":'
                   b'{"id":"opaque-private-trace","error":'
                   b'{"code":"chatgpt_model_controls_unavailable",'
                   b'"message":"Think-only composer has no model picker"}}}\n')

    with patch("sentra_cli.client.urllib.request.urlopen", return_value=Response()):
        with pytest.raises(Exception) as error:
            list(client._responses_stream([{"role": "user", "content": "test"}], cfg.model))
    assert "HTTP 400" in str(error.value)
    assert "chatgpt_model_controls_unavailable" in str(error.value)
    assert "Think-only composer" in str(error.value)
    assert "opaque-private-trace" not in str(error.value)
    assert client.last_delivery_state == "rejected"


def test_chatgpt_web_unknown_failure_remains_uncertain(tmp_path: Path) -> None:
    cfg = CLIConfig(workspace=tmp_path, openai_api_key="none")
    client = ModelClient(cfg)
    detail, rejected = client._stream_failure_detail({
        "type": "response.failed",
        "response": {"error": {"code": "server_is_overloaded", "message": "Upstream unavailable"}},
    })
    assert detail == "server_is_overloaded: Upstream unavailable"
    assert rejected is False
