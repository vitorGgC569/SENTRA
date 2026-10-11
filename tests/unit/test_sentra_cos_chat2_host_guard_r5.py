"""Rodada 5: host-bound durable receipt -> real WebMCPMessageDispatchGuard.

No external account is attested. The only positive attestor below is a
test-only fixture, never an inference from Edge/React/DOM/model.
"""
from __future__ import annotations
from types import SimpleNamespace
import hashlib
import pytest
from sentra_mcp.services.web_account_dispatch import (
    HostWebReceiptRef, guard_from_durable_web_receipts)
from test_sentra_cos_web_relay_authenticated_routes import configure, grant, post, cleanup, EXT


def test_durable_host_receipt_guard_toolpolicy_and_trust(tmp_path):
    durable,context,control,server,adapter,p=configure(tmp_path)
    try:
        sha="1"*64
        server.state.extension_version=lambda:{"source_hash":sha}
        grant(control,p)
        staged=adapter.stage(**p)
        job=server.state.poll("TAB-337")
        assert job
        args={"source_sha256":sha,"worker":"TAB-337","document_id":"doc-host-r5-12345",
              "identity_epoch":"epoch-host-r5-12345"}
        control.browser_evidence.configure(
            extension_id=EXT,principal="local-operator",workspace="web-lab",
            source_sha256=sha,enabled=True,expected_revision=0)
        code,n=post(server,"/browser-evidence/challenge",args)
        assert code==200
        browser={"nonce":n["nonce"],"document_id":args["document_id"],
                 "identity_epoch":args["identity_epoch"],
                 "conversation_id":"target-chat-123",
                 "route_conversation_id":"target-chat-123","state":"idle",
                 "requests":[{"request_id":"request-metadata-12345",
                              "message_id":"message-33777"}]}
        assert post(server,"/browser-evidence/observe",{
            "source_sha256":sha,"worker":"TAB-337","evidence":browser})[0]==200
        assert post(server,"/jobs/progress",{
            "job_id":job["job_id"],"worker":"TAB-337",
            "lease_token":job["lease_token"],"phase":"sending"})[0]==200
        delivery={"conversation_id":"target-chat-123",
                  "message_id":"message-33777",
                  "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
                  "images_attached":0}
        assert post(server,"/jobs/delivery-receipt",{
            **args,"job_id":job["job_id"],"lease_token":job["lease_token"],
            "evidence":delivery,"request_id":"request-metadata-12345"
        })[1]["state"]=="attested"
        ref=HostWebReceiptRef(p["owner"],p["run_id"],job["job_id"])
        holder={"ref":ref}
        ctx=SimpleNamespace(request_context=SimpleNamespace(
            request=SimpleNamespace(headers={"x-request-id":"request-metadata-12345"})))
        source=lambda context:holder["ref"]  # HOST fixture; not MCP arguments.
        guard=guard_from_durable_web_receipts(
            control=control,host_receipt_ref=source)
        with pytest.raises(PermissionError,match="account identity unverified"):
            guard.tool_observer(ctx,"review")
        with pytest.raises(PermissionError,match="authenticated host job"):
            holder["ref"]=None
            guard.tool_observer(ctx,"review")
        holder["ref"]=ref
        positive=guard_from_durable_web_receipts(
            control=control,host_receipt_ref=source,
            verified_account=lambda context,link,chat: True)
        assert positive.tool_observer(ctx,"review")["grants_created"] is False
        ctx.request_context.request.headers["x-request-id"]="request-tampered123"
        with pytest.raises(PermissionError,match="mismatch"):
            positive.tool_observer(ctx,"review")
        ctx.request_context.request.headers["x-request-id"]="request-metadata-12345"
        # ChatTrust's strict mode never equates an observed page with trust.
        control.chat_access.set_strict("local-operator",True,expected_revision=0)
        with pytest.raises(PermissionError,match="trusted"):
            positive.tool_observer(ctx,"review")
        control.chat_access.set_chat("local-operator","target-chat-123",
                                     trusted=True,blocked=False,expected_revision=0)
        assert positive.tool_observer(ctx,"review")["allowed"]
        control.chat_access.set_chat("local-operator","target-chat-123",
                                     trusted=False,blocked=True,expected_revision=1)
        with pytest.raises(PermissionError,match="blocked"):
            positive.tool_observer(ctx,"review")
        control.chat_access.set_chat("local-operator","target-chat-123",
                                     trusted=True,blocked=False,expected_revision=2)
        # The browser's approval window denies even previously attested IDs.
        n=post(server,"/browser-evidence/challenge",args)[1]
        assert post(server,"/browser-evidence/observe",{
            "source_sha256":sha,"worker":"TAB-337",
            "evidence":{**browser,"nonce":n["nonce"],"state":"awaiting_approval"}})[0]==200
        with pytest.raises(PermissionError,match="approval"):
            positive.tool_observer(ctx,"review")
        n=post(server,"/browser-evidence/challenge",args)[1]
        assert post(server,"/browser-evidence/observe",{
            "source_sha256":sha,"worker":"TAB-337",
            "evidence":{**browser,"nonce":n["nonce"],"state":"idle"}})[0]==200
        assert positive.tool_observer(ctx,"review")["allowed"]
        assert post(server,"/browser-evidence/invalidate",{
            **args,"reason":"profile_changed"})[0]==200
        with pytest.raises(PermissionError):
            positive.tool_observer(ctx,"review")
        assert control.browser_evidence.dispatch_state(
            "local-operator","target-chat-123")["send_blocked"]
    finally:
        cleanup(server,context,durable)
