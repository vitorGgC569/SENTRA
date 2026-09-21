from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest
from mcp import Client

from sentra_mcp.config import MCPConfig
from sentra_mcp.server import SentraMCPServer
from sentra_mcp.services.process import ProcessService


def _service(tmp_path: Path, **overrides: object) -> ProcessService:
    config = MCPConfig(
        audit_log=tmp_path / "audit.jsonl",
        **overrides,
    )
    return ProcessService(config)


def _wait_for_exit(
    service: ProcessService,
    session_id: str,
    owner: str,
    timeout: float = 3.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = service.read_process_output(session_id, owner, 0, 1_000_000)
        if not latest["running"]:
            return latest
        time.sleep(0.02)
    raise AssertionError(f"process did not exit: {latest}")


def _wait_for_stdout(
    service: ProcessService,
    session_id: str,
    owner: str,
    expected: str,
    timeout: float = 3.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = service.read_process_output(session_id, owner, 0, 1_000_000)
        if expected in str(latest["stdout"]):
            return latest
        time.sleep(0.02)
    raise AssertionError(f"stdout never contained {expected!r}: {latest}")


def _sleep_command(seconds: float = 30.0) -> list[str]:
    return [sys.executable, "-u", "-c", f"import time; time.sleep({seconds})"]


def test_persistent_stdio_echo_and_string_command(tmp_path: Path) -> None:
    service = _service(tmp_path)
    code = "import sys\nfor line in sys.stdin:\n print('E:' + line.rstrip('\\n'), flush=True)"
    process = service.start_process([sys.executable, "-u", "-c", code], "alice")
    session_id = str(process["session_id"])

    service.interact_with_process(session_id, "alice", "hello\n")
    output = _wait_for_stdout(service, session_id, "alice", "E:hello")
    assert output["running"] is True

    service.terminate_session(session_id, "alice")

    simple = f'"{sys.executable}" -u -c "print(12345)"'
    second = service.start_process(simple, "alice")
    result = _wait_for_exit(service, str(second["session_id"]), "alice")
    assert "12345" in result["stdout"]


def test_output_pagination_is_offset_and_length_bounded(tmp_path: Path) -> None:
    service = _service(tmp_path)
    code = "import sys; sys.stdout.write('abcdefghij'); sys.stderr.write('ABCDEFGHIJ')"
    process = service.start_process([sys.executable, "-u", "-c", code], "alice")
    session_id = str(process["session_id"])
    _wait_for_exit(service, session_id, "alice")

    page = service.read_process_output(session_id, "alice", offset=2, length=4)
    assert page["stdout"] == "cdef"
    assert page["stderr"] == "CDEF"
    assert page["offset"] == 2
    assert page["length"] == 4


def test_blocked_empty_and_null_commands_are_rejected_before_spawn(tmp_path: Path) -> None:
    blocked = Path(sys.executable).name.upper()
    service = _service(tmp_path, blocked_commands=(blocked,))

    with pytest.raises(PermissionError, match="blocked"):
        service.start_process([sys.executable, "-c", "print('no')"], "alice")
    with pytest.raises(ValueError, match="empty"):
        service.start_process([], "alice")
    with pytest.raises(ValueError, match="empty"):
        service.start_process("   ", "alice")
    with pytest.raises(ValueError, match="null byte"):
        service.start_process([sys.executable, "bad\x00arg"], "alice")

    assert service.list_processes("alice") == []


def test_owner_isolation_applies_to_read_write_list_and_termination(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = service.start_process(_sleep_command(), "alice")
    session_id = str(process["session_id"])
    pid = int(process["pid"])

    assert service.list_sessions("bob") == []
    assert service.list_processes("bob") == []
    with pytest.raises(PermissionError, match="another owner"):
        service.read_process_output(session_id, "bob")
    with pytest.raises(PermissionError, match="another owner"):
        service.interact_with_process(session_id, "bob", "x")
    with pytest.raises(PermissionError, match="another owner"):
        service.terminate_session(session_id, "bob")
    with pytest.raises(PermissionError, match="another owner"):
        service.kill_process(pid, "bob")

    assert service.terminate_session(session_id, "alice")["running"] is False


def test_flooding_is_truncated_at_shared_output_limit(tmp_path: Path) -> None:
    service = _service(tmp_path, max_output_bytes=128)
    code = "import sys; sys.stdout.write('x'*200); sys.stderr.write('y'*200)"
    process = service.start_process([sys.executable, "-u", "-c", code], "alice")
    result = _wait_for_exit(service, str(process["session_id"]), "alice")

    retained = len(str(result["stdout"]).encode()) + len(str(result["stderr"]).encode())
    assert retained <= 128
    assert result["output_truncated"] is True


def test_max_processes_counts_only_running_managed_children(tmp_path: Path) -> None:
    service = _service(tmp_path, max_processes=1)
    first = service.start_process(_sleep_command(), "alice")

    with pytest.raises(RuntimeError, match="maximum managed process"):
        service.start_process(_sleep_command(), "alice")

    service.terminate_session(str(first["session_id"]), "alice")
    second = service.start_process([sys.executable, "-c", "print('ok')"], "alice")
    _wait_for_exit(service, str(second["session_id"]), "alice")


def test_timeout_marks_and_terminates_process(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = service.start_process(_sleep_command(), "alice", timeout=0.1)
    result = _wait_for_exit(service, str(process["session_id"]), "alice")

    assert result["running"] is False
    assert result["timed_out"] is True


def test_shutdown_terminates_children_and_prevents_new_processes(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = service.start_process(_sleep_command(), "alice")
    session_id = str(process["session_id"])

    service.shutdown()

    result = service.read_process_output(session_id, "alice")
    assert result["running"] is False
    with pytest.raises(RuntimeError, match="shut down"):
        service.start_process([sys.executable, "-c", "print('no')"], "alice")


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group verification")
def test_terminate_session_kills_spawned_process_tree(tmp_path: Path) -> None:
    service = _service(tmp_path)
    code = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
        "print(p.pid,flush=True);time.sleep(30)"
    )
    process = service.start_process([sys.executable, "-u", "-c", code], "alice")
    session_id = str(process["session_id"])
    output = _wait_for_stdout(service, session_id, "alice", "\n")
    child_pid = int(str(output["stdout"]).strip().splitlines()[0])

    service.terminate_session(session_id, "alice")

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        proc_stat = Path(f"/proc/{child_pid}/stat")
        if proc_stat.exists():
            fields = proc_stat.read_text(encoding="utf-8").split()
            if len(fields) > 2 and fields[2] == "Z":
                break
        time.sleep(0.02)
    else:
        pytest.fail("spawned child survived process-group termination")


def test_child_environment_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sensitive = {
        "UNIT_TOKEN": "one",
        "CLIENT_SECRET": "two",
        "DB_PASSWORD": "three",
        "SERVICE_API_KEY": "four",
        "SESSION_COOKIE": "five",
        "PYTHONPATH": "six",
        "PYTHONHOME": "seven",
        "PYTHONSTARTUP": "eight",
    }
    for key, value in sensitive.items():
        monkeypatch.setenv(key, value)

    service = _service(tmp_path)
    code = (
        "import json,os;"
        f"keys={list(sensitive)!r};"
        "print(json.dumps([k for k in keys if k in os.environ]),flush=True)"
    )
    process = service.start_process([sys.executable, "-u", "-c", code], "alice")
    result = _wait_for_exit(service, str(process["session_id"]), "alice")
    assert json.loads(str(result["stdout"])) == []


def test_kill_process_rejects_unmanaged_pid_and_audit_omits_arguments(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    config = MCPConfig(audit_log=audit_path)
    runtime = SentraMCPServer(config)
    service = runtime.processes

    with pytest.raises(PermissionError, match="not a managed process"):
        service.kill_process(os.getpid(), "alice")

    secret = "argument-secret-123"
    process = service.start_process(
        [sys.executable, "-u", "-c", "import time; time.sleep(30)", secret],
        "alice",
    )
    pid = int(process["pid"])
    service.kill_process(pid, "alice")

    audit_text = audit_path.read_text(encoding="utf-8")
    assert secret not in audit_text
    assert '"action":"process.start"' in audit_text
    assert '"action":"process.kill"' in audit_text


def test_mcp_process_tools_are_registered(tmp_path: Path) -> None:
    async def probe() -> None:
        runtime = SentraMCPServer(MCPConfig(audit_log=tmp_path / "audit.jsonl"))
        async with Client(runtime.mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "sentra_start_process",
                "sentra_read_process_output",
                "sentra_interact_process",
                "sentra_list_sessions",
                "sentra_terminate_session",
                "sentra_list_processes",
                "sentra_kill_process",
            } <= names
        runtime.processes.shutdown()

    asyncio.run(probe())
