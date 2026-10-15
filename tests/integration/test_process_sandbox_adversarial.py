"""Real adversarial tests for SENTRA persistent process isolation."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.services.process import ProcessService
from sentra_mcp.services.workspaces import WorkspaceRegistry

pytestmark = pytest.mark.skipif(
    os.environ.get("OMA_DOCKER_TESTS") != "1",
    reason="opt-in real Docker tests",
)


def _wait(service: ProcessService, session_id: str, owner: str, timeout: float = 20) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = service.read_process_output(session_id, owner, 0, 256 * 1024)
        if not last["running"]:
            return last
        time.sleep(0.05)
    raise AssertionError(f"process did not finish: {last}")


def _config(root: Path, mode: str) -> MCPConfig:
    return MCPConfig(
        allowed_roots=(root,),
        audit_log=root / ".sentra" / f"audit-{mode}.jsonl",
        process_mode=mode,
        process_sandbox_image="oma-sandbox:local",
    )


def _probe_script() -> str:
    return r"""
import json, os, pathlib, socket, subprocess
checks = {}

def cannot_read(path):
    try:
        value = pathlib.Path(path).read_bytes()
    except (OSError, ValueError):
        return True
    return False

checks["windows_literal_blocked"] = cannot_read(r"C:\Windows\win.ini")
checks["wsl_host_mount_blocked"] = cannot_read("/mnt/c/Windows/win.ini")
checks["docker_socket_absent"] = not pathlib.Path("/var/run/docker.sock").exists()

try:
    pathlib.Path("/etc/sentra-escape").write_text("bad")
except OSError:
    checks["rootfs_readonly"] = True
else:
    checks["rootfs_readonly"] = False

try:
    socket.create_connection(("1.1.1.1", 443), timeout=1).close()
except OSError:
    checks["network_blocked"] = True
else:
    checks["network_blocked"] = False

checks["secret_env_absent"] = not any(
    token in key.upper()
    for key in os.environ
    for token in ("SECRET", "TOKEN", "API_KEY", "PASSWORD", "COOKIE")
)

child = subprocess.run(
    ["python", "-c",
     "import pathlib,sys; sys.exit(0 if not pathlib.Path('/mnt/c/Windows/win.ini').exists() else 8)"],
    capture_output=True,
    text=True,
    timeout=5,
)
checks["child_cannot_escape"] = child.returncode == 0

status = pathlib.Path("/proc/self/status").read_text()
checks["no_capabilities"] = "CapEff:\t0000000000000000" in status
checks["no_new_privileges"] = "NoNewPrivs:\t1" in status
checks["seccomp"] = "Seccomp:\t2" in status
checks["nonroot"] = os.getuid() == 65532

print(json.dumps(checks, sort_keys=True))
raise SystemExit(0 if all(checks.values()) else 7)
"""


@pytest.mark.parametrize("mode", ["workspace", "sandbox"])
def test_process_modes_block_host_escape_network_socket_and_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "allowed.txt").write_text("workspace-ok", encoding="utf-8")
    monkeypatch.setenv("SENTRA_TEST_SECRET_TOKEN", "never-enter-container")

    config = _config(root, mode)
    audit = AuditLogger(config.audit_log)
    registry = WorkspaceRegistry(
        config,
        audit,
        state_path=root / ".sentra" / "workspaces.json",
    )
    service = ProcessService(config, audit, registry)
    try:
        status = service.sandbox_status()
        assert status["available"] is True, status
        started = service.start_process(
            ["python", "-c", _probe_script()],
            "mcp:test",
            workspace="sentra",
            mode=mode,
            timeout=15,
        )
        output = _wait(service, started["session_id"], "mcp:test")
        assert output["returncode"] == 0, output
        checks = json.loads(output["stdout"].strip().splitlines()[-1])
        assert all(checks.values()), checks
        assert output["mode"] == mode
        assert output["network"] == "none"
        assert output["image_id"].startswith("sha256:")
    finally:
        service.shutdown()


def test_workspace_read_execute_mount_is_readonly(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    readonly = tmp_path / "readonly"
    primary.mkdir()
    readonly.mkdir()
    (readonly / "data.txt").write_text("immutable", encoding="utf-8")

    config = _config(primary, "workspace")
    audit = AuditLogger(config.audit_log)
    registry = WorkspaceRegistry(
        config,
        audit,
        state_path=primary / ".sentra" / "workspaces.json",
    )
    requested = registry.request_add(
        path=str(readonly),
        owner="mcp:test",
        alias="dataset",
        permissions=("read", "execute"),
        lifetime="permanent",
    )
    registry.approve_local(requested["request_id"])
    service = ProcessService(config, audit, registry)
    code = (
        "import pathlib,sys; p=pathlib.Path('/workspace/data.txt'); "
        "ok=p.read_text()=='immutable'; "
        "\ntry: p.write_text('changed'); writable=True"
        "\nexcept OSError: writable=False"
        "\nprint('READONLY_OK' if ok and not writable else 'BAD'); "
        "sys.exit(0 if ok and not writable else 9)"
    )
    try:
        started = service.start_process(
            ["python", "-c", code],
            "mcp:test",
            workspace="dataset",
            mode="workspace",
            timeout=15,
        )
        output = _wait(service, started["session_id"], "mcp:test")
        assert output["returncode"] == 0, output
        assert "READONLY_OK" in output["stdout"]
        assert output["source_readonly"] is True
        assert (readonly / "data.txt").read_text(encoding="utf-8") == "immutable"
    finally:
        service.shutdown()


def test_sandbox_copy_on_write_never_mutates_source(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "data.txt"
    source.write_text("source", encoding="utf-8")

    config = _config(root, "sandbox")
    audit = AuditLogger(config.audit_log)
    registry = WorkspaceRegistry(config, audit, state_path=root / ".sentra" / "workspaces.json")
    service = ProcessService(config, audit, registry)
    try:
        started = service.start_process(
            [
                "python",
                "-c",
                "from pathlib import Path; p=Path('/workspace/data.txt'); "
                "p.write_text('sandbox-change'); print(p.read_text())",
            ],
            "mcp:test",
            workspace="sentra",
            mode="sandbox",
            timeout=15,
        )
        output = _wait(service, started["session_id"], "mcp:test")
        assert output["returncode"] == 0, output
        assert "sandbox-change" in output["stdout"]
        assert source.read_text(encoding="utf-8") == "source"
    finally:
        service.shutdown()
