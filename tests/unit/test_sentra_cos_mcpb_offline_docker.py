"""Genuine Docker offline wheel extraction/import under SENTRA SQLite grants/fence."""
import asyncio
import shutil
import subprocess

import pytest

from test_sentra_cos_mcpb_offline import fixture
from sentra_mcp.services.mcpb_offline import verify_offline_dependencies_in_docker
from sentra_mcp.services.mcpb_sandbox import _trusted_docker


def test_docker_pinned_offline_wheel_real_effect_and_no_replay(tmp_path, monkeypatch):
    cp, ws, sha = fixture(tmp_path)
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker CLI not available")
    info = subprocess.run([docker, "image", "inspect", "oma-sandbox:local",
                           "--format", "{{.Id}}"], capture_output=True, text=True, timeout=5)
    if info.returncode or not info.stdout.strip().startswith("sha256:"):
        pytest.skip("Pinned local sandbox image absent")
    cli = subprocess.run([docker, "info", "--format", "{{.OSType}}"],
                         capture_output=True, text=True, timeout=5)
    if cli.returncode or cli.stdout.strip() != "linux":
        pytest.skip("Linux Docker daemon not available")
    monkeypatch.setenv("SENTRA_MCPB_SANDBOX_IMAGE_ID", info.stdout.strip())
    cp.durable.create_run("owner", run_id="run-wheel", workspace=str(ws))
    cp.ensure_agent("run-wheel", "owner", agent_id="worker", role="worker")
    cp.create_work_item("run-wheel", "owner", work_item_id="WI-wheel",
                        objective="offline Docker verified import",
                        assignee_agent_id="worker",
                        required_capabilities=["mcp:deps-install"])
    cp.transition_work_item("WI-wheel", "owner", "RUNNING")
    params = dict(owner="owner", workspace=str(ws), package_sha256=sha,
                  run_id="run-wheel", work_item_id="WI-wheel", agent_id="worker",
                  operation_id="op-wheel-real", idempotency_key="idem-wheel-real")
    try:
        with pytest.raises(PermissionError, match="grant"):
            asyncio.run(verify_offline_dependencies_in_docker(cp, **params))
        with pytest.raises(FileNotFoundError):
            cp.durable.operation_status("op-wheel-real", "owner")
        cp.authorization_grant("owner", principal_type="agent", principal_id="worker",
                               capability="mcp:deps-install", scope_type="work_item",
                               scope_id="WI-wheel")
        outcome = asyncio.run(verify_offline_dependencies_in_docker(cp, **params))
        assert outcome.operation.state == "SUCCEEDED", outcome
        assert outcome.payload["installed_imports"] == ["demo"]
        assert outcome.payload["container_removed"] is True
        with cp.store.connect("plugin_bundle") as db:
            row = db.execute("SELECT container_id,state FROM mcpb_docker_ownership "
                             "WHERE operation_id='op-wheel-real'").fetchone()
        assert row["state"] == "CLEANED" and len(row["container_id"]) == 64
        again = asyncio.run(verify_offline_dependencies_in_docker(cp, **params))
        assert again.duplicate and again.operation.state == "SUCCEEDED"
    finally:
        cp.durable.close()
