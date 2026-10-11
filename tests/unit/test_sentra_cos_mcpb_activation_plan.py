"""MCPB launch candidates are pinned, disabled by default and real-grant checked."""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
import pytest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService


def staged(root: Path, control: ControlPlaneService, *, config=None, secret=False):
    manifest={
        "manifest_version":"0.3", "name":"local-mcp-fixture", "version":"1.0.0",
        "author":{"name":"Local QA"}, "server":{"type":"python",
            "entry_point":"server/main.py",
            "mcp_config": config or {"command":"python",
                "args":["${__dirname}/server/main.py"]}},
    }
    if secret:
        manifest["user_config"]={"token":{"type":"string","required":True}}
        manifest["server"]["mcp_config"]["env"]={"TOKEN":"${user_config.token}"}
    file=root/"local.mcpb"
    with zipfile.ZipFile(file,"w") as archive:
        archive.writestr("manifest.json",json.dumps(manifest))
        archive.writestr("server/main.py","print('should not run')\n")
    sha=control.bundle_stage("owner",str(root),str(file))["package_sha256"]
    plugin=control.bundle_register("owner",str(root),sha)
    return sha,plugin


def make_control(tmp_path):
    return ControlPlaneService(DurableRunService(tmp_path/"state"),
                               ContextBusService(tmp_path/"state"))


def make_running_work(control,workspace):
    run_id="run-mcpb"
    control.durable.create_run("owner",run_id=run_id,workspace=str(workspace))
    control.ensure_agent(run_id,"owner",agent_id="trusted-agent",role="worker")
    control.create_work_item(run_id,"owner",work_item_id="WI-mcpb",
        objective="Only prepare a reviewed local MCPB launch",
        assignee_agent_id="trusted-agent",required_capabilities=["mcp:launch"])
    control.transition_work_item("WI-mcpb","owner","RUNNING")
    return {"run_id":run_id,"work_item_id":"WI-mcpb","agent_id":"trusted-agent"}


def test_mcpb_plan_requires_real_work_item_grant_and_pins_files(tmp_path):
    ws=tmp_path/"workspace"
    ws.mkdir()
    cp=make_control(tmp_path)
    sha,plugin=staged(ws,cp)
    args=make_running_work(cp,ws)
    with pytest.raises(PermissionError,match="authorization"):
        cp.bundle_activation_plan("owner",str(ws),sha,**args)
    grant=cp.authorization_grant("owner",principal_type="agent",
        principal_id="trusted-agent",capability="mcp:launch",
        scope_type="work_item",scope_id="WI-mcpb")
    plan=cp.bundle_activation_plan("owner",str(ws),sha,**args)
    assert plan["plugin_id"]==plugin["plugin_id"]
    assert Path(plan["executable"]).absolute()==Path(sys.executable).absolute()
    assert plan["args"]==["-u",str((cp.bundle_catalog.target/sha/"server/main.py").resolve())]
    assert plan["policy_constraints"]["argv_sha256"]==plan["argv_sha256"]
    assert plan["grant_checked"] and not plan["ready_to_execute"]
    assert not plan["durable_operation_reserved"] and not plan["worker_started"]
    assert not cp.governance.plugin_info(plugin["plugin_id"],"owner")["effective_capabilities"]
    assert not (cp.bundle_catalog.target/sha/"server"/"ran.log").exists()
    cp.authorization_revoke(grant["grant_id"],"owner")
    with pytest.raises(PermissionError,match="authorization"):
        cp.bundle_activation_plan("owner",str(ws),sha,**args)
    cp.bundle_disable("owner",str(ws),sha)
    with pytest.raises(PermissionError,match="registration"):
        cp.bundle_activation_plan("owner",str(ws),sha,**args)


@pytest.mark.parametrize("config,secret",[
    ({"command":"powershell","args":["-NoProfile"]},False),
    ({"command":"python","args":["${__dirname}/server/main.py","--force"]},False),
    ({"command":"python","args":["${__dirname}/server/main.py"],
      "env":{"PATH":"C:/malicious"}},False),
    (None,True),
])
def test_mcpb_plan_refuses_shell_flags_env_secrets(tmp_path,config,secret):
    ws=tmp_path/"workspace"
    ws.mkdir()
    cp=make_control(tmp_path)
    sha,_=staged(ws,cp,config=config,secret=secret)
    with pytest.raises(PermissionError):
        cp.bundle_catalog.launch_spec("owner",str(ws),sha,cp.governance)
