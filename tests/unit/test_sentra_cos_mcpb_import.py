"""Adversarial MCPB import + actual Canvas authenticated route."""
from __future__ import annotations
import hashlib
import io
import json
import stat
import zipfile

import pytest
from sentra_mcp.services.plugin_bundles import MCPBBundleCatalog
from test_sentra_runtime_canvas_center_http import running_canvas,request


def bundle(destination,files=None):
    entries={"manifest.json":json.dumps({"name":"QA MCP server","version":"1.2.3"}).encode(),
             "server/index.js":b"console.log('not executed');"}
    entries.update(files or {})
    with zipfile.ZipFile(destination,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for k,v in entries.items():
            archive.writestr(k,v)
    return destination


def test_mcpb_import_stages_inactive_and_does_not_run(tmp_path):
    workspace=tmp_path/"ws";workspace.mkdir()
    path=bundle(workspace/"example.mcpb")
    catalog=MCPBBundleCatalog(tmp_path/"state")
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    row=catalog.stage("user",workspace,path,expected_sha256=digest)
    assert row["status"]=="staged_inactive" and not row["enabled"]
    assert row["requires_grant_and_activation"]
    assert catalog.list("user",workspace)[0]["enabled"]==0
    assert catalog.stage("user",workspace,path)["package_sha256"]==digest
    assert len(catalog.list("user",workspace))==1
    with pytest.raises(ValueError,match="checksum"):
        catalog.stage("user",workspace,path,expected_sha256="0"*64)
    outside=bundle(tmp_path/"outside.mcpb")
    with pytest.raises(PermissionError):
        catalog.stage("user",workspace,outside)


@pytest.mark.parametrize("bad",[
    {"../escape.js":b"x"},
    {"NUL.txt":b"x"},
    {"a.js":b"x","A.JS":b"y"},
    {"folder":b"x","folder/payload":b"y"},
    {"bad:x":b"x"},
])
def test_mcpb_import_rejects_unsafe_archives(tmp_path,bad):
    workspace=tmp_path/"workspace";workspace.mkdir()
    target=bundle(workspace/"bad.mcpb",bad)
    with pytest.raises(ValueError):
        MCPBBundleCatalog(tmp_path/"state").stage("owner",workspace,target)


def test_windows_separator_not_accepted_in_mcpb():
    from sentra_mcp.services.plugin_bundles import _safe
    with pytest.raises(ValueError):
        _safe("bad\\\\path.txt")


def test_canvas_bundle_import_requires_bearer_and_explicit_consent(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        workspace=app.create_workspace("ImportLab")
        ws=workspace["id"]
        source=bundle(__import__("pathlib").Path(workspace["path"])/"approved.mcpb")
        uri=f"/api/center/plugin-bundles?ws={ws}"
        code,result=request(server,uri)
        assert code==200 and result["packages"]==[]
        data={"ws":ws,"source":"approved.mcpb","approve":True}
        code,_=request(server,"/api/center/plugin-bundles",json_body=data,authorized=False)
        assert code==401
        code,_=request(server,"/api/center/plugin-bundles",json_body={**data,"approve":False})
        assert code==403
        code,result=request(server,"/api/center/plugin-bundles",json_body=data)
        assert code==200 and result["status"]=="staged_inactive",result
        code,result=request(server,uri)
        assert code==200 and len(result["packages"])==1
        assert result["packages"][0]["enabled"]==0
