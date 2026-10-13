"""Protected chunked attachment drafts never masquerade as ChatGPT uploads."""
import hashlib
import sqlite3

import pytest

from sentra_mcp.services.web_history_assets import WebAssetDrafts, WebAssetConflict
from test_governance_coordination import _services


def setup(tmp_path):
    durable,context,control=_services(tmp_path)
    owner="asset-owner"
    run=durable.create_run(owner,workspace="asset-workspace")["run_id"]
    control.ensure_agent(run,owner,agent_id="asset-agent",role="builder")
    work=control.create_work_item(run,owner,objective="Process one attachment")
    asset=WebAssetDrafts(control)
    data=b"small binary content\x00" * 4500
    request=dict(owner=owner,run_id=run,work_item_id=work["work_item_id"],
                 principal_id="asset-agent",conversation_id="web-chat-123",
                 message_id="web-msg-123",content_type="application/pdf",
                 expected_bytes=len(data),expected_sha256=hashlib.sha256(data).hexdigest(),
                 operator_approved=True)
    return durable,context,control,asset,data,request


def test_attachment_real_work_item_grant_chunks_restart_and_delete(tmp_path):
    durable,context,control,asset,data,p=setup(tmp_path)
    try:
        with pytest.raises(PermissionError):
            asset.begin(**p)
        g=control.authorization.grant(p["owner"],principal_type="agent",
                 principal_id=p["principal_id"],capability="web:attach",
                 scope_type="work_item",scope_id=p["work_item_id"],
                 conditions={"provider":"chatgpt"})
        with pytest.raises(PermissionError):
            asset.begin(**{**p,"operator_approved":False})
        item=asset.begin(**p)
        assert item["web_uploaded"] is False
        with pytest.raises(FileNotFoundError):
            asset.read("other-owner",item["asset_id"])
        with pytest.raises(WebAssetConflict):
            asset.finish(p["owner"],item["asset_id"])
        for number, offset in enumerate(range(0,len(data),65536)):
            asset.put_chunk(p["owner"],item["asset_id"],part=number,
                            content=data[offset:offset+65536])
        asset.put_chunk(p["owner"],item["asset_id"],part=0,
                        content=data[:65536])
        with pytest.raises(WebAssetConflict):
            asset.put_chunk(p["owner"],item["asset_id"],part=0,content=b"different")
        done=WebAssetDrafts(control).finish(p["owner"],item["asset_id"])
        assert done["state"]=="READY_LOCAL" and not done["web_uploaded"]
        assert WebAssetDrafts(control).read(p["owner"],item["asset_id"])==data
        with sqlite3.connect(str(asset.store.path_for("provider_content"))) as db:
            body=db.execute("SELECT protected_base64 FROM web_asset_chunks LIMIT 1").fetchone()[0]
            assert body.startswith(("dpapi:","keyring:"))
            assert "small binary content" not in body
        control.authorization.revoke(g["grant_id"],p["owner"])
        with pytest.raises(PermissionError):
            asset.read(p["owner"],item["asset_id"])
        control.authorization.grant(p["owner"],principal_type="agent",
                 principal_id=p["principal_id"],capability="web:attach",
                 scope_type="work_item",scope_id=p["work_item_id"],
                 conditions={"provider":"chatgpt"})
        with pytest.raises(PermissionError):
            asset.discard(p["owner"],item["asset_id"])
        asset.discard(p["owner"],item["asset_id"],operator_approved=True)
        with sqlite3.connect(str(asset.store.path_for("provider_content"))) as db:
            assert db.execute("SELECT count(*) FROM web_asset_chunks").fetchone()[0]==0
    finally:
        context.close();durable.close()


def test_attachment_rejects_oversized_and_identity_mismatch(tmp_path):
    durable,context,control,asset,data,p=setup(tmp_path)
    try:
        control.authorization.grant(p["owner"],principal_type="agent",
                 principal_id=p["principal_id"],capability="web:attach",
                 scope_type="work_item",scope_id=p["work_item_id"])
        with pytest.raises(ValueError):
            asset.begin(**{**p,"expected_bytes":20*1024*1024+1})
        with pytest.raises(ValueError):
            asset.begin(**{**p,"content_type":"image/png","expected_bytes":8*1024*1024+1})
        with pytest.raises(ValueError):
            asset.begin(**{**p,"message_id":"?"})
        with pytest.raises(ValueError):
            asset.begin(**{**p,"content_type":"application/x-msdownload"})
        item=asset.begin(**p)
        asset.put_chunk(p["owner"],item["asset_id"],part=0,content=b"X"*65536)
        with pytest.raises(WebAssetConflict):
            asset.finish(p["owner"],item["asset_id"])
    finally:
        context.close();durable.close()
