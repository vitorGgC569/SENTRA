"""Real Docker-managed plugin stdout handshake and owner/grant-fenced restart."""
import asyncio
import json
import os
import shutil
import subprocess
import time

import pytest
from sentra_mcp.config import MCPConfig
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.process import ProcessService
from sentra_mcp.services.plugin_host import PluginWorkerHost

SERVER = """
import json,sys
for line in sys.stdin:
 request=json.loads(line)
 if request["method"]=="sentra.handshake":
  result={"protocol_version":1,"name":"restart-fixture","version":"1.0.0",
          "methods":[{"name":"status","capability":"read"}],"capabilities":["read"]}
 else:
  result={"running":True}
 print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}),flush=True)
"""


def _linux_docker():
    def unavailable(reason):
        if os.environ.get("SENTRA_REQUIRE_SANDBOX_RESTART") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    docker = shutil.which("docker")
    if not docker:
        unavailable("Docker CLI unavailable; real sandbox restart not qualified")
    try:
        os_type = subprocess.run([docker, "info", "--format", "{{.OSType}}"],
                                 capture_output=True, text=True, timeout=6)
    except subprocess.TimeoutExpired:
        unavailable("Docker Linux availability probe timed out; real sandbox restart not qualified")
    if os_type.returncode or os_type.stdout.strip() != "linux":
        unavailable("Docker Linux sandbox unavailable; real sandbox restart not qualified")
    return docker


def test_probe_timeout_is_unavailable_not_a_passing_restart(monkeypatch):
    monkeypatch.delenv("SENTRA_REQUIRE_SANDBOX_RESTART", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: "docker-fixture")
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 6
        raise subprocess.TimeoutExpired(args[0], 6)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(pytest.skip.Exception, match="not qualified"):
        _linux_docker()
    monkeypatch.setenv("SENTRA_REQUIRE_SANDBOX_RESTART", "1")
    with pytest.raises(pytest.fail.Exception, match="not qualified"):
        _linux_docker()


def test_actual_sandbox_process_restart_with_workitem_and_operation(tmp_path):
    _linux_docker()
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "worker.py").write_text(SERVER, encoding="utf-8")
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    cp.durable.create_run("owner", run_id="run-restart", workspace=str(ws))
    cp.ensure_agent("run-restart", "owner", agent_id="agent", role="worker")
    cp.create_work_item("run-restart", "owner", work_item_id="WI-restart",
                        objective="approved fenced plugin restart",
                        assignee_agent_id="agent",
                        required_capabilities=["plugin:restart"])
    cp.transition_work_item("WI-restart", "owner", "RUNNING")
    config = MCPConfig(allowed_roots=(ws,), process_mode="sandbox",
                       process_sandbox_image="oma-sandbox:local",
                       audit_log=tmp_path/"process.jsonl")
    processes = ProcessService(config, durable=cp.durable)
    host = PluginWorkerHost(tmp_path/"state", store=cp.store,
                            processes=processes, governance=cp.governance,
                            authorization=cp.authorization)
    plugin = cp.governance.register_plugin("owner", manifest={
        "name": "restart-fixture", "version": "1.0.0", "capabilities": ["read"],
        "worker": {"command": ["python3", "-u", "worker.py"]}},
        verified_methods=[], narrowed_capabilities=["read"])
    def restart(verified):
        return asyncio.run(host.restart_authorized(
            cp, owner="owner", workspace=str(ws), run_id="run-restart",
            work_item_id="WI-restart", agent_id="agent",
            failed_worker_id=old_worker_id, operation_id="op-worker-restart",
            idempotency_key="idem-worker-restart", approval_ref="operator-confirmed",
            verify_host_consent=lambda *args: verified))
    try:
        original = host.start("owner", plugin_id=plugin["plugin_id"],
                              workspace=str(ws), run_id="run-restart", mode="sandbox",
                              timeout_s=12)
        old_worker_id = original["worker"]["plugin_worker_id"]
        assert host.health(old_worker_id, "owner")["status"] == "HEALTHY"
        processes.terminate_session(original["worker"]["session_id"], "owner")
        reconciled = host.reconcile_worker(old_worker_id, "owner")
        assert reconciled["operator_must_reauthorize"]
        with pytest.raises(PermissionError, match="grant"):
            restart(True)
        with pytest.raises(FileNotFoundError):
            cp.durable.operation_status("op-worker-restart", "owner")
        cp.authorization_grant("owner", principal_type="agent",
            principal_id="agent", capability="plugin:restart",
            scope_type="work_item", scope_id="WI-restart")
        with pytest.raises(PermissionError, match="approval"):
            restart(False)
        outcome = restart(True)
        assert outcome.operation.state == "SUCCEEDED", outcome
        new_worker_id = outcome.payload["worker_id"]
        assert new_worker_id != old_worker_id
        assert host.health(new_worker_id, "owner")["status"] == "HEALTHY"
        assert cp.durable.operation_status("op-worker-restart", "owner")["state"] == "SUCCEEDED"
        assert host.info(old_worker_id, "owner")["state"] == "FAILED"
        assert outcome.payload["grants_created"] is False
        host.stop(new_worker_id, "owner")
    finally:
        processes.cleanup()
        cp.durable.close()
