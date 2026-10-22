"""Physical stopped-container orphan cleanup: exact Docker ID, labels, grants and SQLite."""
import asyncio
import json
import shutil
import subprocess
import time

import pytest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.mcpb_orphans import MCPBDockerOwnership, DockerOwnershipDenied
from mcpb_docker_fixture import probe, trusted_docker


def _docker(*args, check=True):
    proc = subprocess.run([trusted_docker(), *args], capture_output=True,
                          text=True, timeout=12)
    if check and proc.returncode:
        raise RuntimeError("Docker test-owned operation failed")
    return proc


def test_real_stopped_orphan_exact_id_cleanup_with_central_grant(tmp_path, monkeypatch):
    docker = trusted_docker()
    if not docker:
        pytest.skip("Docker CLI unavailable")
    os_name = probe(docker, 'daemon')
    image = probe(docker, 'image')
    if (os_name.returncode or os_name.stdout.strip() != "linux"
            or image.returncode or not image.stdout.strip().startswith("sha256:")):
        pytest.skip("Pinned Docker Linux sandbox image unavailable")
    monkeypatch.setenv("SENTRA_MCPB_SANDBOX_IMAGE_ID", image.stdout.strip())
    ws = tmp_path / "workspace"
    ws.mkdir()
    control = ControlPlaneService(DurableRunService(tmp_path / "state"),
                                  ContextBusService(tmp_path / "state"))
    run, wi, source_op = "run-orphan", "WI-orphan", "op-orphan-source"
    control.durable.create_run("owner", run_id=run, workspace=str(ws))
    control.ensure_agent(run, "owner", agent_id="worker", role="worker")
    control.create_work_item(run, "owner", work_item_id=wi,
                             objective="reconcile only owned stopped Docker",
                             assignee_agent_id="worker",
                             required_capabilities=["mcp:container-cleanup"])
    control.transition_work_item(wi, "owner", "RUNNING")
    control.durable.create_operation(run, "owner", kind="mcpb-test-owned-container",
                                     operation_id=source_op, idempotency_key="source-orphan")
    control.durable.update_operation(source_op, "owner",
                                     progress={"work_item_id": wi})
    ledger = MCPBDockerOwnership(control)
    claim = ledger.prepare(owner="owner", workspace=ws, run_id=run,
                           work_item_id=wi, operation_id=source_op,
                           image_id=image.stdout.strip())
    raw_id = None
    try:
        created = _docker("create", "--pull=never",
                          "--name", claim["container_name"],
                          "--label", "sentra.owner_claim=" + claim["docker_labels"]["sentra.owner_claim"],
                          "--label", "sentra.operation_id=" + source_op,
                          "--network=none", "--read-only", "--cap-drop=ALL",
                          "--security-opt=no-new-privileges", "--pids-limit=16",
                          "--memory=128m", "--user", "65534:65534",
                          image.stdout.strip(), "python3", "-c", "print('fixture')")
        raw_id = created.stdout.strip()
        assert len(raw_id) == 64
        inspected = json.loads(_docker("inspect", raw_id).stdout)[0]
        ledger.bind("owner", source_op, inspected)
        control.durable.update_operation(source_op, "owner", state="RUNNING")
        control.durable.update_operation(source_op, "owner", state="SUCCEEDED")
        with control.store.connect("plugin_bundle") as db:
            db.execute("UPDATE mcpb_docker_ownership SET created_at=?,updated_at=? "
                       "WHERE operation_id=?", (time.time()-240, time.time()-240, source_op))
        params = dict(owner="owner", workspace=ws, source_operation_id=source_op,
                      work_item_id=wi, agent_id="worker", cleanup_operation_id="op-orphan-cleanup",
                      idempotency_key="idem-orphan-cleanup", min_age_seconds=60)
        with pytest.raises(DockerOwnershipDenied, match="grant"):
            asyncio.run(ledger.reconcile_stopped_owned(
                **params, approved_by_host=lambda *a: True))
        assert _docker("inspect", raw_id, check=False).returncode == 0
        control.authorization_grant("owner", principal_type="agent",
                                    principal_id="worker", capability="mcp:container-cleanup",
                                    scope_type="work_item", scope_id=wi)
        with pytest.raises(DockerOwnershipDenied, match="approval"):
            asyncio.run(ledger.reconcile_stopped_owned(
                **params, approved_by_host=lambda *a: False))
        assert _docker("inspect", raw_id, check=False).returncode == 0
        cleaned = asyncio.run(ledger.reconcile_stopped_owned(
            **params, approved_by_host=lambda *a: True))
        assert cleaned.operation.state == "SUCCEEDED", cleaned
        assert cleaned.payload["container_id"] == raw_id
        assert cleaned.payload["removed"] and cleaned.payload["unrelated_processes_affected"] == 0
        assert _docker("inspect", raw_id, check=False).returncode != 0
        assert ledger._row("owner", source_op)["state"] == "CLEANED"
        replay = asyncio.run(ledger.reconcile_stopped_owned(
            **params, approved_by_host=lambda *a: True))
        assert replay.duplicate and replay.operation.state == "SUCCEEDED"
        # Crash simulation: docker rm completed but CLEANED receipt wasn't saved.
        # Reconciliation must inspect absence only, never issue another rm.
        with control.store.connect("plugin_bundle") as db:
            db.execute("UPDATE mcpb_docker_ownership SET state='CLEANING' "
                       "WHERE operation_id=?", (source_op,))
        verify_params = dict(owner="owner", workspace=ws,
                             source_operation_id=source_op, work_item_id=wi,
                             agent_id="worker",
                             verification_operation_id="op-orphan-verify-absence",
                             idempotency_key="idem-orphan-verify-absence")
        with pytest.raises(DockerOwnershipDenied, match="consent"):
            asyncio.run(ledger.confirm_uncertain_absence(
                **verify_params, approved_by_host=lambda *args: False))
        recovered = asyncio.run(ledger.confirm_uncertain_absence(
            **verify_params, approved_by_host=lambda *args: True))
        assert recovered.operation.state == "SUCCEEDED", recovered
        assert recovered.payload["docker_remove_calls"] == 0
        assert recovered.payload["confirmed_absent"] is True
        assert ledger._row("owner", source_op)["state"] == "CLEANED"
        retry_verify = asyncio.run(ledger.confirm_uncertain_absence(
            **verify_params, approved_by_host=lambda *args: True))
        assert retry_verify.duplicate and retry_verify.operation.state == "SUCCEEDED"
    finally:
        # Cleanup ONLY our test container if exact claim and image still match.
        if raw_id and _docker("inspect", raw_id, check=False).returncode == 0:
            item = json.loads(_docker("inspect", raw_id).stdout)[0]
            if (item.get("Id") == raw_id and
                    item.get("Image") == image.stdout.strip() and
                    item.get("Name") == "/" + claim["container_name"] and
                    item.get("Config", {}).get("Labels", {}).get(
                        "sentra.owner_claim") == claim["docker_labels"]["sentra.owner_claim"]):
                _docker("rm", raw_id, check=False)
        control.durable.close()
