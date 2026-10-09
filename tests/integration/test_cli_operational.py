import json
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.configuration import build_router, engine_options

ROOT = Path(__file__).resolve().parents[2]


def cli(*args):
    return subprocess.run([sys.executable,"-B",str(ROOT/"main.py"),*map(str,args)],
                          capture_output=True,text=True,encoding="utf-8",timeout=45)


def test_cli_demo_then_status_and_separate_promotion(tmp_path):
    workspace = tmp_path / "demo"
    result = cli("--demo","--workspace",workspace,"--job-id","cli-demo")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CANDIDATE_READY" in result.stdout
    assert "factorial" not in (workspace/"math_utils.py").read_text()
    status = cli("--status","--workspace",workspace,"--job-id","cli-demo")
    assert status.returncode == 0
    assert json.loads(status.stdout)["integration_tests"]["all_passed"]
    assert json.loads(status.stdout)["conversation_pool"]["state"] in {"ABSENT", "IDLE"}
    result = cli("--promote","cli-demo","--workspace",workspace,"--trust-workspace")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "def factorial" in (workspace/"math_utils.py").read_text()


def test_cli_failures_are_nonzero_and_preserve_user_files(tmp_path):
    (tmp_path/"keep.txt").write_text("mine")
    result = cli("--demo","--workspace",tmp_path)
    assert result.returncode == 2 and (tmp_path/"keep.txt").read_text() == "mine"
    result = cli("--workspace",tmp_path,"--prompt","do work","--sandbox","host")
    assert result.returncode == 2 and "--trust-workspace" in result.stderr
    assert not (tmp_path/"runs").exists()


def test_cli_remote_workers_require_explicit_workspace_and_are_disabled_in_demo(tmp_path):
    missing_workspace = cli(
        "--workspace", tmp_path,
        "--prompt", "inspect",
        "--remote-principal", "user-1",
        "--sandbox", "host",
        "--trust-workspace",
    )
    assert missing_workspace.returncode == 2
    assert "--remote-workspace" in missing_workspace.stderr

    demo_remote = cli(
        "--demo",
        "--workspace", tmp_path / "demo-remote",
        "--remote-principal", "user-1",
        "--remote-workspace", "sentra",
    )
    assert demo_remote.returncode == 2
    assert "Remote Agents" in demo_remote.stderr


def test_routing_is_explicit_and_profiles_are_argv():
    routing = build_router({"routing":{"worker":"extension","reviewer":"local","roles":{"validator":"local"}}},mock=True)
    assert routing.primary_name == "extension"
    assert routing.providers["master"] is routing.providers["local"]
    assert routing.fallback_name is None
    assert routing.role_routes["validator"] == "local"
    with pytest.raises(ValueError):
        engine_options({"validation":{"profiles":{"all":"echo unsafe"}}})
    with pytest.raises(ValueError):
        build_router({"routing":{"worker":"invented"}},mock=True)


def test_service_cli_exposes_singleton_tunnel_actions() -> None:
    from sentra_remote.run_cli import _parser

    parser = _parser()
    restart = parser.parse_args([
        "--state-dir", ".sentra",
        "service", "restart-tunnel",
        "--install-dir", ".",
    ])
    assert restart.domain == "service"
    assert restart.action == "restart-tunnel"
    assert restart.install_dir == "."

    configure = parser.parse_args([
        "service", "configure-tunnel",
        "--tunnel-id", "tunnel_1234567890",
    ])
    assert configure.action == "configure-tunnel"
    assert configure.tunnel_id == "tunnel_1234567890"
    assert configure.runtime_key_env == "CONTROL_PLANE_API_KEY"


def test_singleton_wrapper_has_valid_powershell_syntax() -> None:
    import os
    import subprocess
    from pathlib import Path

    if os.name != "nt":
        return
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "commander"
        / "Start-SENTRA-Singleton.ps1"
    )
    escaped = str(script).replace("'", "''")
    command = (
        "$p='" + escaped + "'; "
        "[scriptblock]::Create([IO.File]::ReadAllText($p)) | Out-Null"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
