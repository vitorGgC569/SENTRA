"""MCPB 0.3 binding to SENTRA central governance without executing third-party code."""
from __future__ import annotations
import json
import zipfile
import pytest
from sentra_mcp.services.plugin_bundles import MCPBBundleCatalog
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from test_sentra_runtime_canvas_center_http import running_canvas, request


def fixture_bundle(path, **changes):
    manifest = {
        "manifest_version": "0.3", "name": "tested-plugin", "version": "1.0.0",
        "description": "Offline test MCP plugin",
        "author": {"name": "Fixture author"},
        "server": {"type": "python", "entry_point": "server/main.py",
                   "mcp_config": {"command": "python",
                                  "args": ["${__dirname}/server/main.py"],
                                  "env": {"API_KEY": "${user_config.secret}"}},
                   },
        "user_config": {"secret": {"type": "string", "title": "Private",
                                   "description": "Secret", "required": True}},
    }
    manifest.update(changes)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("server/main.py", "# inert test code")
    return path


def control(root):
    state=root / "state"
    return ControlPlaneService(DurableRunService(state), ContextBusService(state))


def test_staged_manifest_register_idempotent_revocable_no_grants(tmp_path):
    workspace=tmp_path/"ws";workspace.mkdir()
    path=fixture_bundle(workspace/"plugin.mcpb")
    cp=control(tmp_path)
    owner="owner"
    stage=cp.bundle_catalog.stage(owner,workspace,path)
    sha=stage["package_sha256"]
    info=cp.bundle_catalog.describe(owner,workspace,sha)
    assert info["name"]=="tested-plugin"
    assert info["execution_protocol"]=="mcp_stdio" and not info["execution_supported"]
    assert info["required_user_config_keys"]==["secret"]
    assert "API_KEY" not in json.dumps(info)
    first=cp.bundle_catalog.register(owner,workspace,sha,cp.governance)
    assert first["status"]=="REGISTERED" and not first["worker_started"]
    repeated=cp.bundle_catalog.register(owner,workspace,sha,cp.governance)
    assert repeated["plugin_id"]==first["plugin_id"]
    assert repeated["already_registered"]
    assert cp.governance.list_plugins(owner)["items"][0]["effective_capabilities"]==[]
    assert cp.governance.plugin_info(first["plugin_id"],owner)["manifest"].get("worker") is None
    with pytest.raises(FileNotFoundError):
        cp.bundle_catalog.describe(owner,tmp_path,sha)
    second=control(tmp_path).bundle_catalog.registration(owner,workspace,sha)
    assert second=={"plugin_id":first["plugin_id"],"status":"REGISTERED"}
    disabled=cp.bundle_catalog.disable(owner,workspace,sha,cp.governance)
    assert disabled["status"]=="DISABLED"
    assert cp.governance.plugin_info(first["plugin_id"],owner)["state"]=="DISABLED"
    assert cp.bundle_catalog.disable(owner,workspace,sha,cp.governance)["status"]=="DISABLED"
    assert cp.bundle_catalog.register(owner,workspace,sha,cp.governance)["status"]=="DISABLED"


def test_manifest_rejects_mismatch_tamper_and_legacy(tmp_path):
    workspace=tmp_path/"ws";workspace.mkdir()
    cat=MCPBBundleCatalog(tmp_path/"state")
    sha=cat.stage("owner",workspace,fixture_bundle(workspace/"v1.mcpb",manifest_version="0.2"))["package_sha256"]
    with pytest.raises(ValueError, match="0.3"):
        cat.describe("owner",workspace,sha)
    sha=cat.stage("owner",workspace,fixture_bundle(workspace/"v2.mcpb",
        server={"type":"python","entry_point":"../escape.py"}))["package_sha256"]
    with pytest.raises(ValueError,match="unsafe"):
        cat.describe("owner",workspace,sha)
    sha=cat.stage("owner",workspace,fixture_bundle(workspace/"v3.mcpb"))["package_sha256"]
    (cat.target/sha/"manifest.json").write_text('{"name":"modified"}')
    with pytest.raises(ValueError,match="integrity|missing or changed"):
        cat.describe("owner",workspace,sha)


def test_canvas_authenticated_register_and_disable_preserves_user_consent(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        created=app.create_workspace("BoundMCPB")
        ws=created["id"]
        source=fixture_bundle(__import__("pathlib").Path(created["path"])/"bundle.mcpb")
        endpoint="/api/center/plugin-bundles"
        code,staged=request(server,endpoint,json_body={"ws":ws,"source":"bundle.mcpb","approve":True})
        assert code==200
        sha=staged["package_sha256"]
        body={"ws":ws,"action":"register","package_sha256":sha,"approve":True}
        code,_=request(server,endpoint,json_body=body,authorized=False)
        assert code==401
        code,_=request(server,endpoint,json_body={**body,"approve":False})
        assert code==403
        code,registered=request(server,endpoint,json_body=body)
        assert code==200,registered
        assert not registered["created_grants"] and not registered["worker_started"]
        code,state=request(server,endpoint+"?ws="+ws)
        assert code==200 and state["packages"][0]["registration"]["plugin_id"]==registered["plugin_id"]
        assert state["standard_mcp_stdio_host_available"] is False
        code,inspection=request(server,endpoint,json_body={"ws":ws,"action":"inspect",
            "package_sha256":sha,"approve":True})
        assert code==200 and inspection["server_type"]=="python"
        code,revoked=request(server,endpoint,json_body={"ws":ws,"action":"disable",
            "package_sha256":sha,"approve":True})
        assert code==200 and revoked["status"]=="DISABLED"

def test_staged_mcpb_archive_independent_of_workspace_source(tmp_path):
    workspace=tmp_path/"ws";workspace.mkdir()
    source=fixture_bundle(workspace/"original.mcpb")
    control_plane=control(tmp_path)
    catalog=control_plane.bundle_catalog
    sha=catalog.stage("owner",workspace,source)["package_sha256"]
    source.unlink()
    registered=catalog.register("owner",workspace,sha,control_plane.governance)
    assert registered["status"]=="REGISTERED"
    archive=catalog.target/".archives"/(sha+".mcpb")
    assert archive.is_file()
    archive.write_bytes(b"corrupt")
    with pytest.raises(ValueError,match="archive SHA"):
        catalog.describe("owner",workspace,sha)
