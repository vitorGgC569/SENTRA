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
    result = cli("--workspace",tmp_path,"--prompt","do work")
    assert result.returncode == 2 and "--trust-workspace" in result.stderr
    assert not (tmp_path/"runs").exists()


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
