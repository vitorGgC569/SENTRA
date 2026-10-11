"""Real local Docker MCP stdio over the SENTRA durable Control Plane.

No network, no shell, no Windows host Python execution; local image must
already exist and the Docker daemon must be available (no implicit pull).
"""
import asyncio
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService

SERVER = r'''
import json, socket, sys
def emit(item): print(json.dumps(item,separators=(",",":")),flush=True)
for line in sys.stdin:
 req=json.loads(line)
 method=req.get("method")
 if method=="initialize":
  emit({"jsonrpc":"2.0","id":req["id"],"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":"isolated","version":"1"}}})
 elif method=="tools/list":
  emit({"jsonrpc":"2.0","id":req["id"],"result":{"tools":[{"name":"echo"}]}})
 elif method=="tools/call":
  can_write=False
  try:
   open("/bundle/probe.txt","w").write("escaped")
   can_write=True
  except OSError: pass
  network=False
  try:
   with socket.create_connection(("1.1.1.1",53),0.25): network=True
  except OSError: pass
  payload=req["params"]["arguments"]["value"]
  emit({"jsonrpc":"2.0","id":req["id"],"result":{"content":[{"type":"text","text":payload}],"sandbox":{"host_package_write":can_write,"outbound_network":network}}})
'''


def _fixture(tmp_path):
    ws=tmp_path/"workspace"
    ws.mkdir()
    state=tmp_path/"state"
    control=ControlPlaneService(DurableRunService(state), ContextBusService(state))
    manifest={"manifest_version":"0.3","name":"readonly-fixture","version":"1.0.0",
              "author":{"name":"Test"},"server":{"type":"python",
              "entry_point":"server/main.py","mcp_config":{
                  "command":"python","args":["${__dirname}/server/main.py"]}}}
    file=ws/"sample.mcpb"
    with zipfile.ZipFile(file,"w") as z:
        z.writestr("manifest.json",json.dumps(manifest))
        z.writestr("server/main.py",SERVER)
    sha=control.bundle_stage("owner",str(ws),str(file))["package_sha256"]
    control.bundle_register("owner",str(ws),sha)
    control.durable.create_run("owner",run_id="run-docker",workspace=str(ws))
    control.ensure_agent("run-docker","owner",agent_id="agent",role="worker")
    control.create_work_item("run-docker","owner",work_item_id="WI-docker",
        objective="docker isolated MCP test",assignee_agent_id="agent",
        required_capabilities=["mcp:launch","mcp:list","mcp:echo"])
    control.transition_work_item("WI-docker","owner","RUNNING")
    params=dict(owner="owner",workspace=str(ws),package_sha256=sha,
        run_id="run-docker",work_item_id="WI-docker",agent_id="agent",
        tool_name="echo", arguments={"value":"SENTRA_DOCKER_OK"},
        operation_id="op-docker-e2e",idempotency_key="idem-docker-e2e")
    return control,ws,params


def _grant(control, capability):
    return control.authorization_grant("owner",principal_type="agent",
        principal_id="agent",capability=capability,scope_type="work_item",
        scope_id="WI-docker")


def test_mcpb_isolation_requires_host_image_and_discovery_and_tool_grants(tmp_path,monkeypatch):
    cp,ws,params=_fixture(tmp_path)
    _grant(cp,"mcp:launch")
    with pytest.raises(PermissionError,match="pinned local Docker image"):
        asyncio.run(cp.bundle_call_tool(**params))
    monkeypatch.setenv("SENTRA_MCPB_SANDBOX_IMAGE_ID","sha256:"+"0"*64)
    with pytest.raises(PermissionError,match="discovery"):
        asyncio.run(cp.bundle_call_tool(**params))
    _grant(cp,"mcp:list")
    with pytest.raises(PermissionError,match="named tool"):
        asyncio.run(cp.bundle_call_tool(**params))
    assert not (cp.bundle_catalog.target/params["package_sha256"]/"probe.txt").exists()
    with pytest.raises(FileNotFoundError):
        cp.durable.operation_status(params["operation_id"],"owner")
    cp.durable.close()


def test_mcpb_real_docker_durable_stdio_and_no_replay(tmp_path,monkeypatch):
    docker=shutil.which("docker")
    if not docker:
        pytest.skip("Docker CLI not installed")
    # Only a locally installed image may be used, by immutable image ID.
    inspection=subprocess.run([docker,"image","inspect","oma-sandbox:local","--format","{{.Id}}"],
        capture_output=True,text=True,timeout=5)
    if inspection.returncode or not inspection.stdout.strip().startswith("sha256:"):
        pytest.skip("Local isolation image not present")
    info=subprocess.run([docker,"info","--format","{{.OSType}}"],
        capture_output=True,text=True,timeout=5)
    if info.returncode or info.stdout.strip()!="linux":
        pytest.skip("Linux container Docker daemon unavailable")
    monkeypatch.setenv("SENTRA_MCPB_SANDBOX_IMAGE_ID",inspection.stdout.strip())
    cp,ws,params=_fixture(tmp_path)
    grants=[_grant(cp,cap) for cap in ("mcp:launch","mcp:list","mcp:echo")]
    try:
        result=asyncio.run(cp.bundle_call_tool(**params))
        assert result.operation.state=="SUCCEEDED",result
        assert result.payload["content"][0]["text"]=="SENTRA_DOCKER_OK"
        assert result.payload["sandbox"]=={"host_package_write":False,"outbound_network":False}
        row=cp.durable.operation_status(params["operation_id"],"owner")
        assert row["run_id"]=="run-docker" and row["state"]=="SUCCEEDED"
        assert row["progress"]["work_item_id"]=="WI-docker"
        assert not (cp.bundle_catalog.target/params["package_sha256"]/"probe.txt").exists()
        # Reuse of an operation never starts the container a second time.
        again=asyncio.run(cp.bundle_call_tool(**params))
        assert again.duplicate and again.operation.state=="SUCCEEDED"
        cp.authorization_revoke(grants[-1]["grant_id"],"owner")
        with pytest.raises(PermissionError,match="named tool"):
            asyncio.run(cp.bundle_call_tool(**{**params,
                "operation_id":"op-after-revoke","idempotency_key":"idem-after-revoke"}))
    finally:
        cp.durable.close()
