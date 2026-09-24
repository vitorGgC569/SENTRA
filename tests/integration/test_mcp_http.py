from __future__ import annotations

import asyncio
import json
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
    deadline = time.monotonic() + 10
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


def test_real_streamable_http_client_on_loopback(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("http-ok\n", encoding="utf-8")
    run = tmp_path / "runs" / "RUN-HTTP"
    run.mkdir(parents=True)
    (run / "handoff.json").write_text(
        json.dumps({"run_id": "RUN-HTTP", "status": "CANDIDATE_READY"}),
        encoding="utf-8",
    )

    port = _free_port()
    audit = tmp_path / ".sentra" / "audit.jsonl"
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
        str(audit),
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
            async with Client(
                f"http://127.0.0.1:{port}/mcp",
                read_timeout_seconds=15,
            ) as client:
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                assert "sentra_read_file" in names
                assert "sentra_start_process" in names
                assert "sentra_oma_status" in names

                read = await client.call_tool("sentra_read_file", {"path": "hello.txt"})
                assert read.is_error is False
                assert read.structured_content["data"]["content"] == "http-ok\n"

                status = await client.call_tool("sentra_oma_status", {"run_id": "RUN-HTTP"})
                assert status.is_error is False
                assert status.structured_content["data"]["status"]["status"] == "CANDIDATE_READY"

                health = await client.call_tool("sentra_health", {})
                assert health.is_error is False
                assert health.structured_content["data"]["capabilities"]["security"]["http_loopback_only"] is True

                capability = await client.read_resource("sentra://capabilities")
                assert "streamable-http" in capability.contents[0].text

        asyncio.run(probe())
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    assert audit.is_file()
