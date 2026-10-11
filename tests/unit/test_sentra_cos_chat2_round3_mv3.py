"""Real JS MV3 deny-only producer -> BrowserEvidenceService SQLite contract.

Node is a hermetic JavaScript fixture harness, NOT the Code Mode runtime.
No browser login, cookie, account, model, effort, or remote E2E assumed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sentra_mcp.services.browser_evidence import BrowserEvidenceService

EXT = "a" * 32
SHA = "f" * 64
OWNER = "local-operator"
CHAT = "conversation12345"
REQ = "request-abcdef123"
MSG = "message-abcdef123"


def mv3_trace():
    node = shutil.which("node")
    if not node:
        pytest.skip("Hermetic Node JS runner not available")
    fixture = Path(__file__).with_name("sentra_cos_identity_mv3_round3.cjs")
    output = subprocess.run([node, str(fixture)], text=True,
                            capture_output=True, timeout=10)
    assert output.returncode == 0, output.stderr
    lines = [line for line in output.stdout.splitlines()
             if line.startswith("SENTRA_MV3_TRACE=")]
    assert len(lines) == 1
    return json.loads(lines[0].partition("=")[2])


def test_mv3_lifecycle_trace_no_secret_and_all_denials():
    trace = mv3_trace()
    notice = trace["notice"]
    assert set(notice) == {
        "source_sha256", "worker", "document_id", "identity_epoch", "reason"
    }
    assert notice == {
        "source_sha256": SHA, "worker": "TAB-77",
        "document_id": trace["doc"], "identity_epoch": trace["epoch"],
        "reason": "signed_out"
    }
    assert trace["profile_epoch"] != trace["epoch"]
    # Global logout poison is persistent; separate navigation/tab-close cases
    # run in a fresh R5 fixture instead of silently clearing account risk.
    assert "signed_out" in trace["events"]
    serialized = json.dumps(trace).lower()
    for secret in ("cookie", "bearer", "token", "password", "email", "secret"):
        assert secret not in serialized


def test_produced_epoch_notice_revokes_exact_page_and_survives_restart(tmp_path):
    trace = mv3_trace()
    notice = trace["notice"]
    be = BrowserEvidenceService(tmp_path)
    be.configure(extension_id=EXT, principal=OWNER, workspace=str(tmp_path),
                 source_sha256=SHA, enabled=True, expected_revision=0)
    kwargs = {"extension_id": EXT, "source_sha256": SHA, "worker": "TAB-77"}
    nonce = be.challenge(**kwargs, document_id=trace["doc"],
                         identity_epoch=trace["epoch"])["nonce"]
    evidence = {
        "nonce": nonce, "document_id": trace["doc"],
        "identity_epoch": trace["epoch"],
        "conversation_id": CHAT, "route_conversation_id": CHAT,
        "state": "idle", "requests": [
            {"request_id": REQ, "message_id": MSG}
        ]
    }
    assert be.observe(**kwargs, evidence=evidence)["state"] == "observed"
    assert be.chat_access.require_exact_message(OWNER, REQ, MSG)["allowed"]
    # This is the literal producer payload sent to the relay v2 route.
    with pytest.raises(PermissionError, match="epoch"):
        be.invalidate_document(
            extension_id=EXT,
            **{**notice, "identity_epoch": "forged-epoch-1234"})
    assert be.chat_access.require_exact_message(OWNER, REQ, MSG)["allowed"]
    # v2 challenge may never be downgraded to omit identity_epoch.
    with pytest.raises(PermissionError, match="epoch"):
        be.challenge(**kwargs,document_id=trace["doc"])
    assert be.invalidate_document(
        extension_id=EXT, **notice)["state"] == "invalidated"
    with pytest.raises(PermissionError):
        be.chat_access.require_exact_message(OWNER, REQ, MSG)
    assert BrowserEvidenceService(tmp_path).dispatch_state(
        OWNER, CHAT)["send_blocked"] is True
    with pytest.raises(PermissionError, match="revoked"):
        BrowserEvidenceService(tmp_path).challenge(
            **kwargs, document_id=trace["doc"],identity_epoch=trace["epoch"])
    # Deny-only event is idempotent across host restart/unknown ACK.
    assert BrowserEvidenceService(tmp_path).invalidate_document(
        extension_id=EXT, **notice)["state"] == "invalidated"


def test_epoch_observation_conflict_and_other_tab_isolation(tmp_path):
    be=BrowserEvidenceService(tmp_path)
    be.configure(extension_id=EXT,principal=OWNER,workspace=str(tmp_path),
                 source_sha256=SHA,enabled=True,expected_revision=0)
    epoch="epoch-123456789"
    a=dict(extension_id=EXT,source_sha256=SHA,worker="TAB-100")
    nonce=be.challenge(**a,document_id="document-123456789",
                       identity_epoch=epoch)["nonce"]
    evidence=dict(nonce=nonce,document_id="document-123456789",
                  conversation_id="conversation-a123456",
                  route_conversation_id="conversation-a123456",
                  state="idle",requests=[],identity_epoch=epoch)
    with pytest.raises(PermissionError,match="epoch"):
        be.observe(**a,evidence={**evidence,"identity_epoch":"epoch-wrong-123"})
    assert be.observe(**a,evidence=evidence)["state"]=="observed"
    b=dict(extension_id=EXT,source_sha256=SHA,worker="TAB-101")
    nonce=be.challenge(**b,document_id="document-b123456",
                       identity_epoch="epoch-b123456")["nonce"]
    be.observe(**b,evidence={**evidence,
                             "nonce":nonce,"document_id":"document-b123456",
                             "conversation_id":"conversation-b123456",
                             "route_conversation_id":"conversation-b123456",
                             "identity_epoch":"epoch-b123456"})
    be.invalidate_document(**a,document_id="document-123456789",
                           identity_epoch=epoch,reason="navigation")
    assert not be.dispatch_state(OWNER,"conversation-b123456")["send_blocked"]
    assert be.dispatch_state(OWNER,"conversation-a123456")["send_blocked"]


def test_manifest_current_source_hash_after_mv3_change():
    from scripts.commander.extension_identity import extension_source_identity
    root=Path(__file__).resolve().parents[2]/"edge_extension"
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    assert manifest["sentra_source_hash"] == extension_source_identity(root)["source_hash"]


def test_web_mcp_dispatch_bound_to_v2_identity_epoch(tmp_path):
    from types import SimpleNamespace
    from sentra_mcp.services.web_account_dispatch import (
        AuthenticatedWebLink, WebMCPMessageDispatchGuard)
    be=BrowserEvidenceService(tmp_path)
    be.configure(extension_id=EXT,principal=OWNER,workspace=str(tmp_path),
                 source_sha256=SHA,enabled=True,expected_revision=0)
    epoch="epoch-123456789"
    worker="TAB-77"
    document="document-abc123456"
    kw=dict(extension_id=EXT,source_sha256=SHA,worker=worker)
    nonce=be.challenge(**kw,document_id=document,identity_epoch=epoch)["nonce"]
    be.observe(**kw,evidence=dict(nonce=nonce,document_id=document,
        identity_epoch=epoch,conversation_id=CHAT,route_conversation_id=CHAT,
        state="idle",requests=[{"request_id":REQ,"message_id":MSG}]))
    ctx=SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={"x-request-id":REQ})))
    holder={"link":AuthenticatedWebLink(OWNER,REQ,MSG,EXT,worker,document)}
    guard=WebMCPMessageDispatchGuard(
        chat_access=be.chat_access,browser_evidence=be,
        authenticated_link=lambda context: holder["link"],
        # Fixture-only: no real account attestation.
        verified_account=lambda context,link,chat: True)
    with pytest.raises(PermissionError,match="epoch"):
        guard.tool_observer(ctx,"read-only")
    holder["link"]=AuthenticatedWebLink(OWNER,REQ,MSG,EXT,worker,document,
                                         identity_epoch="epoch-tampered123")
    with pytest.raises(PermissionError,match="epoch"):
        guard.tool_observer(ctx,"read-only")
    holder["link"]=AuthenticatedWebLink(OWNER,REQ,MSG,EXT,worker,document,
                                         identity_epoch=epoch)
    assert guard.tool_observer(ctx,"read-only")["account_identity"]=="attested_by_host"
    be.invalidate_document(**kw,document_id=document,identity_epoch=epoch,
                           reason="identity_unknown")
    with pytest.raises(PermissionError):
        guard.tool_observer(ctx,"read-only")
