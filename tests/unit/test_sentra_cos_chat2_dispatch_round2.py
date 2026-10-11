"""Round 2 browser document revocation and real ToolPolicyProxy dispatch integration.

Page payloads and MCP context are hermetic; the SQLite store, tool wrapper,
central ChatAccess and BrowserEvidenceServices are real production classes.
"""
from types import SimpleNamespace

import pytest

from sentra_mcp.services.browser_evidence import BrowserEvidenceService
from sentra_mcp.services.web_account_dispatch import (
    AuthenticatedWebLink, WebMCPMessageDispatchGuard,
)
from sentra_mcp.tool_policy import ToolPolicyProxy

EXT = "a" * 32
SHA = "f" * 64
OWNER = "local-operator"
WORKER = "TAB-444"
DOC = "document-123456789"
CHAT = "conversation-123456789"
REQ = "request-123456789"
MSG = "message-123456789"


def collector(path):
    be = BrowserEvidenceService(path)
    be.configure(extension_id=EXT,source_sha256=SHA,principal=OWNER,
                 workspace=str(path),enabled=True,expected_revision=0)
    return be


def observe(be, *, document=DOC, worker=WORKER, request=REQ, message=MSG,
            conversation=CHAT, state="idle", include=True):
    kwargs={"extension_id":EXT,"source_sha256":SHA,"worker":worker}
    nonce=be.challenge(**kwargs,document_id=document)["nonce"]
    payload={"nonce":nonce,"document_id":document,"conversation_id":conversation,
             "route_conversation_id":conversation,"state":state,
             "requests":[{"request_id":request,"message_id":message}] if include else []}
    return be.observe(**kwargs,evidence=payload)


def test_new_document_fences_old_mcp_identity_before_any_react_scan(tmp_path):
    be=collector(tmp_path)
    observe(be)
    assert be.chat_access.require_exact_message(OWNER,REQ,MSG)["allowed"]
    # New page challenge alone closes old document even if next scan fails.
    be.challenge(extension_id=EXT,source_sha256=SHA,worker=WORKER,
                 document_id="document-replacement-123")
    with pytest.raises(PermissionError,match="document"):
        be.chat_access.require_exact_message(OWNER,REQ,MSG)
    with pytest.raises(PermissionError,match="revoked"):
        be.challenge(extension_id=EXT,source_sha256=SHA,worker=WORKER,
                     document_id=DOC)
    assert be.dispatch_state(OWNER,CHAT)["state"]=="unknown"
    # A restart must preserve the revocation and not resurrect old requests.
    restarted=BrowserEvidenceService(tmp_path)
    with pytest.raises(PermissionError,match="document"):
        restarted.chat_access.require_allowed(OWNER,REQ)
    with restarted.store.connect("chat_access") as db:
        row=db.execute("SELECT reason FROM browser_revoked_documents WHERE "
                       "extension_id=? AND worker=? AND document_id=?",
                       (EXT,WORKER,DOC)).fetchone()
        assert row["reason"]=="document_changed"


def test_authenticated_invalidation_logout_closed_tab_and_stale_notice(tmp_path):
    be=collector(tmp_path)
    observe(be)
    assert be.invalidate_document(extension_id=EXT,source_sha256=SHA,worker=WORKER,
                                  document_id=DOC,reason="signed_out")["state"]=="invalidated"
    with pytest.raises(PermissionError):
        be.chat_access.require_allowed(OWNER,REQ)
    with pytest.raises(PermissionError,match="revoked"):
        observe(be)
    # An authorized extension may register a truly new document, not the old one.
    observe(be,document="document-fresh-1234567",include=False)
    with pytest.raises(PermissionError,match="stale"):
        be.invalidate_document(extension_id=EXT,source_sha256=SHA,worker=WORKER,
                               document_id=DOC,reason="tab_closed")
    # Account uncertainty is stronger than a document mismatch: it remains
    # blocked even after a newly observed page appears idle.
    with pytest.raises(PermissionError,match="profile or account"):
        be.chat_access.require_allowed(OWNER,REQ)
    with pytest.raises(ValueError,match="reason"):
        be.invalidate_document(extension_id=EXT,source_sha256=SHA,worker=WORKER,
                               document_id="document-fresh-1234567",reason="grant")
    with BrowserEvidenceService(tmp_path).store.connect("chat_access") as db:
        assert db.execute("SELECT COUNT(*) FROM browser_revoked_documents").fetchone()[0]==1


def test_other_tab_identity_survives_targeted_invalidation(tmp_path):
    be=collector(tmp_path)
    observe(be,worker="TAB-111",request="request-first-123",message="message-first-123")
    observe(be,worker="TAB-222",request="request-second-123",message="message-second-123")
    be.invalidate_document(extension_id=EXT,source_sha256=SHA,worker="TAB-111",
                           document_id=DOC,reason="tab_closed")
    with pytest.raises(PermissionError,match="document"):
        be.chat_access.require_allowed(OWNER,"request-first-123")
    # The second worker has its own enrolled document and immutable message.
    assert be.chat_access.require_exact_message(
        OWNER,"request-second-123","message-second-123")["allowed"]
    assert be.chat_access.require_allowed(OWNER,"request-second-123")["conversation_id"]==CHAT


def test_mcp_tool_wrapper_exact_join_precedes_real_tool_body_and_approval(tmp_path):
    be=collector(tmp_path)
    observe(be)
    link=AuthenticatedWebLink(OWNER,REQ,MSG,EXT,WORKER,DOC)
    live={"link":link}
    # Fixture-only trusted host attestation; never proof of a live ChatGPT account.
    guard=WebMCPMessageDispatchGuard(chat_access=be.chat_access,browser_evidence=be,
                                     authenticated_link=lambda ctx: live["link"],
                                     verified_account=lambda ctx,link,chat: True)
    effects=[]
    class MCP:
        def tool(self,*args,**kwargs):
            return lambda fn:fn
    proxy=ToolPolicyProxy(MCP(),(),chat_access=be.chat_access,
                          request_observer=guard.tool_observer)
    @proxy.tool()
    def sensitive_local_effect(*,ctx):
        effects.append("effect")
        return "OK"
    context=SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={"x-request-id":REQ})))
    assert sensitive_local_effect(ctx=context)=="OK"
    assert effects==["effect"]
    live["link"]=AuthenticatedWebLink(OWNER,REQ,"message-fake-12345",EXT,WORKER,DOC)
    with pytest.raises(PermissionError,match="pairing"):
        sensitive_local_effect(ctx=context)
    live["link"]=AuthenticatedWebLink(OWNER,REQ,MSG,EXT,"TAB-999",DOC)
    with pytest.raises(PermissionError,match="tab/document"):
        sensitive_local_effect(ctx=context)
    live["link"]=link
    context.request_context.request.headers["x-request-id"]="request-attacker-123"
    with pytest.raises(PermissionError,match="transport mismatch"):
        sensitive_local_effect(ctx=context)
    context.request_context.request.headers["x-request-id"]=REQ
    live["link"]=None
    with pytest.raises(PermissionError,match="authenticated"):
        sensitive_local_effect(ctx=context)
    live["link"]=link
    observe(be,state="awaiting_approval")
    with pytest.raises(PermissionError,match="approval"):
        sensitive_local_effect(ctx=context)
    assert effects==["effect"]
    observe(be,state="idle")
    assert sensitive_local_effect(ctx=context)=="OK"
    assert len(effects)==2


def test_mcp_guard_absent_browser_or_wrong_extension_build_is_fail_closed(tmp_path):
    be=collector(tmp_path)
    observe(be)
    guard=WebMCPMessageDispatchGuard(
        chat_access=be.chat_access,browser_evidence=be,
        authenticated_link=lambda context: AuthenticatedWebLink(
            OWNER,REQ,MSG,EXT,WORKER,DOC))
    ctx=SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(
        headers={"x-request-id":REQ})))
    with pytest.raises(PermissionError,match="account identity unverified"):
        guard.tool_observer(ctx,"read-safe")
    assert WebMCPMessageDispatchGuard(
        chat_access=be.chat_access,browser_evidence=be,
        authenticated_link=guard.authenticated_link,
        verified_account=lambda ctx,link,chat: True
    ).tool_observer(ctx,"read-safe")["account_identity"]=="attested_by_host"
    be.configure(extension_id=EXT,source_sha256=SHA,principal=OWNER,
                 workspace=str(tmp_path),enabled=False,expected_revision=1)
    with pytest.raises(PermissionError,match="collector"):
        guard.tool_observer(ctx,"read-safe")
