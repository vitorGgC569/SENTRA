from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mcp import Client, StdioServerParameters

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _make_run(root: Path) -> None:
    run = root / "runs" / "RUN-E2E"
    run.mkdir(parents=True)
    (run / "handoff.json").write_text(
        json.dumps({"run_id": "RUN-E2E", "status": "CANDIDATE_READY", "objective": "e2e"}),
        encoding="utf-8",
    )
    (run / "events.jsonl").write_text(
        json.dumps({"event_type": "READY"}) + "\n",
        encoding="utf-8",
    )


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        text = (result.stdout or "").strip()
        return bool(text and str(pid) in text and "No tasks" not in text)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists() and len((fields := stat.read_text(encoding="utf-8").split())) > 2 and fields[2] == "Z":
        return False
    return True


async def _wait_output(client: Client, session_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 5
    latest: dict = {}
    while time.monotonic() < deadline:
        response = await client.call_tool(
            "sentra_read_process_output",
            {"session_id": session_id, "owner": "e2e", "offset": 0, "length": 65536},
        )
        assert response.is_error is False
        latest = response.structured_content["data"]
        if expected in latest["stdout"]:
            return latest
        await asyncio.sleep(0.05)
    raise AssertionError(f"process output did not contain {expected!r}: {latest}")


def test_real_stdio_client_filesystem_process_oma_resources_and_cleanup(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\nworld\n", encoding="utf-8")
    _make_run(tmp_path)
    audit = tmp_path / ".sentra" / "audit.jsonl"

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
            str(audit),
        ],
        cwd=PROJECT_ROOT,
    )
    orphan_pid = 0

    async def probe() -> None:
        nonlocal orphan_pid
        async with Client(params, read_timeout_seconds=15) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "sentra_read_file",
                "sentra_start_process",
                "sentra_oma_status",
                "sentra_repo_status",
            } <= names

            file_result = await client.call_tool(
                "sentra_read_file",
                {"path": "hello.txt", "offset": 1, "length": 1},
            )
            assert file_result.is_error is False
            assert file_result.structured_content["data"]["content"] == "world\n"

            status = await client.call_tool("sentra_oma_status", {"run_id": "RUN-E2E"})
            assert status.is_error is False
            assert status.structured_content["data"]["status"]["status"] == "CANDIDATE_READY"

            repo = await client.call_tool("sentra_repo_status", {})
            assert repo.is_error is False
            assert "NO_GIT_REPO" in repo.structured_content["data"]["result"]

            echo_code = (
                "import sys;"
                "print('ready',flush=True);"
                "exec(\"for line in sys.stdin:\\n print('E:'+line.strip(),flush=True)\")"
            )
            started = await client.call_tool(
                "sentra_start_process",
                {
                    "command": [sys.executable, "-u", "-c", echo_code],
                    "owner": "e2e",
                    "cwd": ".",
                },
            )
            assert started.is_error is False
            session_id = started.structured_content["data"]["session_id"]
            await _wait_output(client, session_id, "ready")
            wrote = await client.call_tool(
                "sentra_interact_process",
                {"session_id": session_id, "owner": "e2e", "stdin": "ping\n"},
            )
            assert wrote.is_error is False
            output = await _wait_output(client, session_id, "E:ping")
            assert Path(output["cwd"]).resolve() == tmp_path.resolve()
            await client.call_tool(
                "sentra_terminate_session",
                {"session_id": session_id, "owner": "e2e"},
            )

            resources = await client.list_resources()
            uris = {str(resource.uri) for resource in resources.resources}
            assert "sentra://capabilities" in uris
            assert "sentra://project/summary" in uris
            capability = await client.read_resource("sentra://capabilities")
            assert '"automatic_promotion": false' in capability.contents[0].text
            run_resource = await client.read_resource("sentra://run/RUN-E2E/summary")
            assert "CANDIDATE_READY" in run_resource.contents[0].text

            prompts = await client.list_prompts()
            assert "sentra_operator" in {prompt.name for prompt in prompts.prompts}
            prompt = await client.get_prompt("sentra_operator", {"run_id": "RUN-E2E"})
            assert "no MCP tool for automatic candidate promotion" in prompt.messages[0].content.text

            sleeper = await client.call_tool(
                "sentra_start_process",
                {
                    "command": [sys.executable, "-u", "-c", "import time; time.sleep(30)"],
                    "owner": "e2e",
                },
            )
            assert sleeper.is_error is False
            orphan_pid = int(sleeper.structured_content["data"]["pid"])
            assert _pid_exists(orphan_pid)
            # Intentionally do not terminate: stdio server lifespan must clean it up.

    asyncio.run(probe())

    deadline = time.monotonic() + 5
    while orphan_pid and time.monotonic() < deadline and _pid_exists(orphan_pid):
        time.sleep(0.05)
    assert orphan_pid and not _pid_exists(orphan_pid)
    assert audit.is_file()
