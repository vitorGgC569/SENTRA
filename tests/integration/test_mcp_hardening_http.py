from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import Client

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_port(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=2)
            raise AssertionError(f"MCP HTTP server exited early: {stdout}\n{stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("MCP HTTP server did not open loopback port")


def _approve_workspace(state_path: Path, request_id: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sentra_remote.admin",
            "--workspace-state",
            str(state_path),
            "approve-workspace",
            request_id,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _wait_job(
    client: Client,
    job_id: str,
    session_token: str,
    timeout: float = 15,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await client.call_tool(
            "sentra_job_wait",
            {"job_id": job_id, "timeout_s": 1.0, "session_token": session_token},
        )
        data = result.structured_content["data"]
        if data["state"] in {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            return data
    raise AssertionError("job did not reach terminal state")


def test_streamable_http_session_isolation_workspaces_and_async_jobs(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    secondary.mkdir()
    (primary / "primary.txt").write_text("primary\n", encoding="utf-8")
    (secondary / "research.txt").write_text("secondary\n", encoding="utf-8")

    tests = primary / "tests"
    tests.mkdir()
    (tests / "test_async.py").write_text(
        "import time\n\ndef test_async_job():\n    time.sleep(1.2)\n    assert True\n",
        encoding="utf-8",
    )
    (tests / "test_cancel.py").write_text(
        "import time\n\ndef test_cancel_job():\n    time.sleep(30)\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "init"], cwd=primary, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "sentra@example.invalid"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.name", "SENTRA Tests"], cwd=primary, check=True)
    subprocess.run(["git", "add", "."], cwd=primary, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=primary, check=True, capture_output=True)

    port = _free_port()
    audit = primary / ".sentra" / "audit.jsonl"
    workspace_state = primary / ".sentra" / "workspaces.json"
    command = [
        sys.executable,
        "-B",
        "-m",
        "sentra_mcp",
        "--transport",
        "streamable-http",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--allowed-root",
        str(primary),
        "--audit-log",
        str(audit),
        "--process-mode",
        "unrestricted",
    ]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_port(port, process)

        async def probe() -> None:
            url = f"http://127.0.0.1:{port}/mcp"
            async with Client(url, read_timeout_seconds=20) as client_a:
                async with Client(url, read_timeout_seconds=20) as client_b:
                    opened_a = await client_a.call_tool("sentra_session_open", {})
                    opened_b = await client_b.call_tool("sentra_session_open", {})
                    token_a = opened_a.structured_content["data"]["session_token"]
                    token_b = opened_b.structured_content["data"]["session_token"]
                    assert token_a != token_b

                    # Session isolation is proven by owner-scoped search ids.
                    started = await client_a.call_tool(
                        "sentra_start_search",
                        {
                            "path": ".",
                            "pattern": "primary",
                            "search_type": "content",
                            "session_token": token_a,
                        },
                    )
                    search_id = started.structured_content["data"]["search_id"]
                    own = await client_a.call_tool(
                        "sentra_search_wait",
                        {"search_id": search_id, "timeout_s": 5, "session_token": token_a},
                    )
                    assert own.structured_content["ok"] is True
                    other = await client_b.call_tool(
                        "sentra_get_search_results",
                        {"search_id": search_id, "session_token": token_b},
                    )
                    assert other.structured_content["ok"] is False
                    assert other.structured_content["error"]["code"] == "forbidden"

                    # Session-scoped read-only workspace.
                    request = await client_a.call_tool(
                        "sentra_request_workspace",
                        {
                            "path": str(secondary),
                            "alias": "research-session",
                            "permissions": ["read"],
                            "lifetime": "session",
                            "session_token": token_a,
                        },
                    )
                    request_id = request.structured_content["data"]["request_id"]
                    await asyncio.to_thread(
                        _approve_workspace,
                        workspace_state,
                        request_id,
                    )
                    read_a = await client_a.call_tool(
                        "sentra_read_file",
                        {"workspace": "research-session", "path": "research.txt", "session_token": token_a},
                    )
                    assert read_a.structured_content["ok"] is True
                    read_b = await client_b.call_tool(
                        "sentra_read_file",
                        {"workspace": "research-session", "path": "research.txt", "session_token": token_b},
                    )
                    assert read_b.structured_content["ok"] is False

                    denied_write = await client_a.call_tool(
                        "sentra_write_file",
                        {
                            "workspace": "research-session",
                            "path": "research.txt",
                            "content": "no",
                            "session_token": token_a,
                        },
                    )
                    assert denied_write.structured_content["ok"] is False
                    denied_exec = await client_a.call_tool(
                        "sentra_start_process",
                        {
                            "workspace": "research-session",
                            "command": [sys.executable, "-c", "print('no')"],
                            "mode": "unrestricted",
                            "session_token": token_a,
                        },
                    )
                    assert denied_exec.structured_content["ok"] is False

                    # Upgrade same path to permanent read/write/execute.
                    upgrade = await client_a.call_tool(
                        "sentra_request_workspace",
                        {
                            "path": str(secondary),
                            "alias": "research-session",
                            "permissions": ["read", "write", "execute"],
                            "lifetime": "permanent",
                            "session_token": token_a,
                        },
                    )
                    upgrade_id = upgrade.structured_content["data"]["request_id"]
                    await asyncio.to_thread(
                        _approve_workspace,
                        workspace_state,
                        upgrade_id,
                    )
                    read_b_after = await client_b.call_tool(
                        "sentra_read_file",
                        {"workspace": "research-session", "path": "research.txt", "session_token": token_b},
                    )
                    assert read_b_after.structured_content["ok"] is True
                    write = await client_b.call_tool(
                        "sentra_write_file",
                        {
                            "workspace": "research-session",
                            "path": "created.txt",
                            "content": "created\n",
                            "session_token": token_b,
                        },
                    )
                    assert write.structured_content["ok"] is True

                    proc = await client_a.call_tool(
                        "sentra_start_process",
                        {
                            "workspace": "research-session",
                            "command": [sys.executable, "-u", "-c", "print('EXEC_OK')"],
                            "mode": "unrestricted",
                            "timeout": 5,
                            "session_token": token_a,
                        },
                    )
                    assert proc.structured_content["ok"] is True
                    proc_id = proc.structured_content["data"]["session_id"]
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        output = await client_a.call_tool(
                            "sentra_read_process_output",
                            {"session_id": proc_id, "length": 4096, "session_token": token_a},
                        )
                        if output.structured_content["ok"] and "EXEC_OK" in output.structured_content["data"]["stdout"]:
                            break
                        await asyncio.sleep(0.05)
                    else:
                        raise AssertionError("process output not observed")
                    other_proc = await client_b.call_tool(
                        "sentra_read_process_output",
                        {"session_id": proc_id, "length": 4096, "session_token": token_b},
                    )
                    assert other_proc.structured_content["ok"] is False

                    # Connector-safe asynchronous TEST: start returns before suite finishes.
                    t0 = time.monotonic()
                    job = await client_a.call_tool(
                        "sentra_test_start",
                        {"target": "tests/test_async.py", "session_token": token_a},
                    )
                    assert time.monotonic() - t0 < 1.0
                    job_id = job.structured_content["data"]["job_id"]
                    short = await client_a.call_tool(
                        "sentra_job_wait",
                        {"job_id": job_id, "timeout_s": 0.05, "session_token": token_a},
                    )
                    assert short.structured_content["data"]["state"] in {"PENDING", "RUNNING"}
                    assert short.structured_content["data"]["timed_out"] is True
                    terminal = await _wait_job(client_a, job_id, token_a, 15)
                    assert terminal["state"] == "COMPLETED"
                    assert terminal["result"]["passed"] is True

                    # Real cancellation reaches the running command.
                    slow = await client_a.call_tool(
                        "sentra_test_start",
                        {"target": "tests/test_cancel.py", "session_token": token_a},
                    )
                    slow_id = slow.structured_content["data"]["job_id"]
                    await asyncio.sleep(0.3)
                    cancelled = await client_a.call_tool(
                        "sentra_job_cancel",
                        {"job_id": slow_id, "session_token": token_a},
                    )
                    assert cancelled.structured_content["ok"] is True
                    cancelled_terminal = await _wait_job(client_a, slow_id, token_a, 10)
                    assert cancelled_terminal["state"] == "CANCELLED"

                    # Removal requires local approval and becomes effective live.
                    removal = await client_a.call_tool(
                        "sentra_request_remove_workspace",
                        {"workspace": "research-session", "session_token": token_a},
                    )
                    removal_id = removal.structured_content["data"]["request_id"]
                    await asyncio.to_thread(
                        _approve_workspace,
                        workspace_state,
                        removal_id,
                    )
                    removed = await client_a.call_tool(
                        "sentra_read_file",
                        {"workspace": "research-session", "path": "research.txt", "session_token": token_a},
                    )
                    assert removed.structured_content["ok"] is False

            assert (secondary / "created.txt").read_text(encoding="utf-8") == "created\n"

        asyncio.run(probe())
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
