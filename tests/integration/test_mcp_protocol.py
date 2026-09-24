from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from sentra_mcp.config import PROJECT_ROOT


def _envelope(result) -> dict:
    assert result.structured_content is not None
    data = result.structured_content
    assert data["ok"] is True, data
    return data["data"]


def test_real_stdio_client_filesystem_process_sentra_resources_and_prompts(tmp_path: Path) -> None:
    async def probe() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-B",
                "-m",
                "sentra_mcp",
                "--transport",
                "stdio",
                "--allowed-root",
                str(tmp_path),
                "--audit-log",
                str(tmp_path / ".sentra" / "audit.jsonl"),
                "--surface",
                "all",
                "--process-mode",
                "unrestricted",
            ],
            cwd=PROJECT_ROOT,
        )
        async with Client(params) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "sentra_health",
                "sentra_write_file",
                "sentra_read_file",
                "sentra_start_process",
                "sentra_read_process_output",
                "sentra_oma_health",
                "sentra_repo_status",
            } <= names

            write = await client.call_tool(
                "sentra_write_file",
                {"path": "stdio.txt", "content": "stdio-file\n", "mode": "rewrite"},
            )
            assert _envelope(write)["bytes"] == len("stdio-file\n".encode())
            read = await client.call_tool("sentra_read_file", {"path": "stdio.txt"})
            assert _envelope(read)["content"] == "stdio-file\n"

            started = await client.call_tool(
                "sentra_start_process",
                {
                    "command": [sys.executable, "-u", "-c", "print('stdio-process-ok')"],
                    "owner": "e2e-stdio",
                    "timeout": 5.0,
                },
            )
            session = _envelope(started)["session_id"]
            latest = {}
            for _ in range(100):
                output = await client.call_tool(
                    "sentra_read_process_output",
                    {"session_id": session, "owner": "e2e-stdio", "offset": 0, "length": 4096},
                )
                latest = _envelope(output)
                if "stdio-process-ok" in latest["stdout"] and not latest["running"]:
                    break
                await asyncio.sleep(0.03)
            assert "stdio-process-ok" in latest["stdout"]
            assert latest["running"] is False

            health = await client.call_tool("sentra_oma_health", {})
            assert _envelope(health)["automatic_promotion"] is False

            resources = await client.list_resources()
            resource_uris = {str(item.uri) for item in resources.resources}
            assert "sentra://capabilities" in resource_uris
            assert "sentra://project/summary" in resource_uris

            caps = await client.read_resource("sentra://capabilities")
            assert caps.contents and getattr(caps.contents[0], "text", None)
            cap_data = json.loads(caps.contents[0].text)
            assert cap_data["security"]["automatic_promotion"] is False
            assert "processes" in cap_data["tool_families"]

            prompts = await client.list_prompts()
            assert "sentra_operator" in {prompt.name for prompt in prompts.prompts}
            prompt = await client.get_prompt("sentra_operator")
            joined = "\n".join(
                getattr(message.content, "text", str(message.content))
                for message in prompt.messages
            )
            assert "no MCP tool for automatic candidate promotion" in joined

    asyncio.run(probe())
    assert (tmp_path / "stdio.txt").read_text(encoding="utf-8") == "stdio-file\n"
    assert (tmp_path / ".sentra" / "audit.jsonl").is_file()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_port(port: int, process: subprocess.Popen[str], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise AssertionError(
                f"HTTP MCP exited early code={process.returncode}\nstdout={stdout}\nstderr={stderr}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("HTTP MCP did not open loopback port")


def test_real_streamable_http_client_on_loopback(tmp_path: Path) -> None:
    port = _free_port()
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
        str(tmp_path),
        "--audit-log",
        str(tmp_path / ".sentra" / "http-audit.jsonl"),
        "--surface",
        "all",
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
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                health = await client.call_tool("sentra_health", {})
                assert _envelope(health)["status"] == "ok"

                write = await client.call_tool(
                    "sentra_write_file",
                    {"path": "http.txt", "content": "http-ok\n"},
                )
                assert _envelope(write)["path"] == "http.txt"
                read = await client.call_tool("sentra_read_file", {"path": "http.txt"})
                assert _envelope(read)["content"] == "http-ok\n"

                oma = await client.call_tool("sentra_oma_health", {})
                assert _envelope(oma)["arbitrary_oma_access"] is False

                resources = await client.list_resources()
                assert "sentra://capabilities" in {str(item.uri) for item in resources.resources}

        asyncio.run(probe())
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    assert process.returncode is not None
    assert (tmp_path / "http.txt").read_text(encoding="utf-8") == "http-ok\n"
