"""CHAT 2: identity conflict and two independent human API consents on real SQLite."""
import asyncio
import secrets

import pytest

from sentra_mcp.services.browser_evidence import BrowserEvidenceService
from sentra_mcp.services.action_consent_gate import ActionConsentService
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService

EXT="a"*32
SHA="b"*64
OWNER="local-operator"
REQ="request-123456789"
MSG="message-123456789"
CHAT="conversation-123456789"
DOC="document-123456789"


def _proof():
    # Synthetic human assertion for the hermetic host-auth test harness ONLY.
    # Every click has a distinct, never-replayed opaque assertion.
    return "fixture-owner-click-" + secrets.token_hex(20)


def _observe(be, *, worker="TAB-123", document=DOC, conversation=CHAT,
             request=REQ, message=MSG, state="idle", include=True):
    kwargs=dict(extension_id=EXT,source_sha256=SHA,worker=worker)
    challenge=be.challenge(**kwargs,document_id=document)
    requests=([{"request_id":request,"message_id":message}] if include else [])
    evidence=dict(nonce=challenge["nonce"],document_id=document,
                  conversation_id=conversation,route_conversation_id=conversation,
                  state=state,requests=requests)
    return be.observe(**kwargs,evidence=evidence)


def _enroll(root):
    be=BrowserEvidenceService(root)
    be.configure(extension_id=EXT,source_sha256=SHA,principal=OWNER,
                 workspace=str(root),enabled=True,expected_revision=0)
    return be


def test_message_binding_mismatch_and_second_tab_quarantine(tmp_path):
    be=_enroll(tmp_path)
    _observe(be)
    assert be.chat_access.require_exact_message(OWNER,REQ,MSG)["pairing"]=="observed_metadata_request_id"
    with pytest.raises(PermissionError,match="pairing"):
        be.chat_access.require_exact_message(OWNER,REQ,"wrong-message-123")
    # Same request in a different tab with changed Web message => quarantine,
    # including the first request owner; persistent across service restarts.
    with pytest.raises(PermissionError,match="quarantined"):
        _observe(be,worker="TAB-456",message="message-other123")
    with pytest.raises(PermissionError,match="quarantined"):
        BrowserEvidenceService(tmp_path).chat_access.require_allowed(OWNER,REQ)


def test_navigation_reenrollment_and_approval_fail_closed(tmp_path):
    be=_enroll(tmp_path)
    _observe(be)
    _observe(be,document="document-new-123456",include=False)
    with pytest.raises(PermissionError,match="document"):
        be.chat_access.require_allowed(OWNER,REQ)
    # Re-enrollment revokes even still-open matched tabs; it never grants tools.
    with pytest.raises(PermissionError,match="revoked"):
        _observe(be,document=DOC,include=False)
    with pytest.raises(PermissionError,match="document"):
        be.chat_access.require_exact_message(OWNER,REQ,MSG)
    be.configure(extension_id=EXT,source_sha256=SHA,principal=OWNER,
                 workspace=str(tmp_path),enabled=False,expected_revision=1)
    with pytest.raises(PermissionError,match="collector"):
        be.chat_access.require_allowed(OWNER,REQ)


def _central(tmp_path):
    state=tmp_path/"state"
    be=_enroll(state)
    _observe(be)
    cp=ControlPlaneService(DurableRunService(state),ContextBusService(state))
    cp.durable.create_run(OWNER,run_id="run-api",workspace=str(tmp_path))
    cp.ensure_agent("run-api",OWNER,agent_id="agent-001",role="worker")
    cp.create_work_item("run-api",OWNER,work_item_id="WI-api-consent",
        objective="read reviewed fixture",assignee_agent_id="agent-001",
        required_capabilities=["api:action:sample","api:read:sample"])
    cp.transition_work_item("WI-api-consent",OWNER,"RUNNING")
    consent=ActionConsentService(
        state, owner_authenticator=lambda owner,purpose,proof: (
            owner if purpose and proof.startswith("fixture-owner-click-") else None))
    args=dict(control=cp,owner=OWNER,run_id="run-api",work_item_id="WI-api-consent",
              agent_id="agent-001",request_id=REQ,message_id=MSG,action="sample",
              body={"operation":"sample","id":7})
    return cp,consent,args


def test_double_human_consent_real_central_grant_operation_and_replay(tmp_path):
    cp,svc,args=_central(tmp_path)
    effects=[]
    async def effect():
        effects.append("called")
        return {"ok":True,"count":len(effects)}
    try:
        with pytest.raises(PermissionError,match="first human API consent"):
            svc.allow_api(owner=OWNER,agent_id=args["agent_id"],work_item_id=args["work_item_id"],
                          enabled=True,expected_revision=0)
        first=svc.allow_api(owner=OWNER,agent_id=args["agent_id"],work_item_id=args["work_item_id"],
                            enabled=True,expected_revision=0,human_confirmed=True,owner_proof=_proof())
        assert first=={"enabled":True,"revision":1,"grants_created":False}
        proposal=svc.propose_action(**{k:args[k] for k in
            ("owner","agent_id","work_item_id","request_id","message_id","action","body")})
        action_id=proposal["action_id"]
        execute=dict(**args,action_id=action_id,operation_id="op-api-123456",
                     idempotency_key="idem-api-123456",host_effect=effect)
        with pytest.raises(PermissionError,match="second human"):
            svc.approve_action(action_id=action_id,body_sha256=proposal["body_sha256"])
        svc.approve_action(action_id=action_id,body_sha256=proposal["body_sha256"],
                           human_confirmed=True,owner_proof=_proof())
        with pytest.raises(PermissionError,match="grant"):
            asyncio.run(svc.execute(**execute))
        with pytest.raises(FileNotFoundError):
            cp.durable.operation_status("op-api-123456",OWNER)
        grant=cp.authorization_grant(OWNER,principal_type="agent",
            principal_id="agent-001",capability="api:action:sample",
            scope_type="work_item",scope_id="WI-api-consent")
        with pytest.raises(PermissionError,match="mismatched"):
            asyncio.run(svc.execute(**{**execute,"body":{"id":9}}))
        result=asyncio.run(svc.execute(**execute))
        assert result.operation.state=="SUCCEEDED" and result.payload=={"ok":True,"count":1}
        assert effects==["called"]
        row=cp.durable.operation_status("op-api-123456",OWNER)
        assert row["progress"]["work_item_id"]=="WI-api-consent"
        again=asyncio.run(svc.execute(**execute))
        assert again.duplicate and effects==["called"]
        # A new Operation cannot reuse the consumed approval.
        with pytest.raises(PermissionError,match="used"):
            asyncio.run(svc.execute(**{**execute,"operation_id":"op-api-new-123",
                                        "idempotency_key":"idem-api-new-123"}))
        cp.authorization_revoke(grant["grant_id"],OWNER)
        fresh=svc.propose_action(**{k:args[k] for k in
            ("owner","agent_id","work_item_id","request_id","message_id","action","body")})
        svc.approve_action(action_id=fresh["action_id"],body_sha256=fresh["body_sha256"],
                           human_confirmed=True,owner_proof=_proof())
        with pytest.raises(PermissionError,match="grant"):
            asyncio.run(svc.execute(**{**execute,"action_id":fresh["action_id"],
                 "operation_id":"op-api-revoked","idempotency_key":"idem-api-revoked"}))
        assert effects==["called"]
    finally:
        cp.durable.close()


def test_consent_revision_and_browser_approval_blocks_effect(tmp_path):
    cp,svc,args=_central(tmp_path)
    async def effect():
        pytest.fail("browser approval must block host effect")
    try:
        svc.allow_api(owner=OWNER,agent_id="agent-001",work_item_id="WI-api-consent",
                      enabled=True,expected_revision=0,human_confirmed=True,owner_proof=_proof())
        prepared=svc.propose_action(**{k:args[k] for k in
            ("owner","agent_id","work_item_id","request_id","message_id","action","body")})
        svc.approve_action(action_id=prepared["action_id"],body_sha256=prepared["body_sha256"],
                           human_confirmed=True,owner_proof=_proof())
        cp.authorization_grant(OWNER,principal_type="agent",principal_id="agent-001",
                               capability="api:action:sample",scope_type="work_item",
                               scope_id="WI-api-consent")
        be=BrowserEvidenceService(tmp_path/"state")
        _observe(be,state="awaiting_approval")
        with pytest.raises(PermissionError,match="approval"):
            asyncio.run(svc.execute(**args,action_id=prepared["action_id"],
                operation_id="op-api-blocked",idempotency_key="idem-api-blocked",
                host_effect=effect))
        svc.allow_api(owner=OWNER,agent_id="agent-001",work_item_id="WI-api-consent",
                      enabled=False,expected_revision=1,human_confirmed=True,owner_proof=_proof())
        _observe(be,state="idle")
        with pytest.raises(PermissionError,match="revoked"):
            asyncio.run(svc.execute(**args,action_id=prepared["action_id"],
                operation_id="op-api-blocked2",idempotency_key="idem-api-blocked2",
                host_effect=effect))
    finally:
        cp.durable.close()


def test_read_api_requires_first_consent_and_distinct_durable_read_grant(tmp_path):
    cp,svc,args=_central(tmp_path)
    reads=[]
    async def host_read():
        reads.append("read")
        return {"public_fixture":"TEST_ONLY"}
    payload={key:value for key,value in args.items() if key!="action"}
    payload.update(resource="sample",operation_id="op-read-api123",
                   idempotency_key="idem-read-api123",host_read=host_read)
    try:
        with pytest.raises(PermissionError,match="first API consent"):
            asyncio.run(svc.read_api(**payload))
        svc.allow_api(owner=OWNER,agent_id="agent-001",work_item_id="WI-api-consent",
                      enabled=True,expected_revision=0,human_confirmed=True,owner_proof=_proof())
        # Granting the action API does not authorize an unrelated READ effect.
        cp.authorization_grant(OWNER,principal_type="agent",principal_id="agent-001",
            capability="api:action:sample",scope_type="work_item",scope_id="WI-api-consent")
        with pytest.raises(PermissionError,match="distinct"):
            asyncio.run(svc.read_api(**payload))
        grant=cp.authorization_grant(OWNER,principal_type="agent",principal_id="agent-001",
            capability="api:read:sample",scope_type="work_item",scope_id="WI-api-consent")
        result=asyncio.run(svc.read_api(**payload))
        assert result.operation.state=="SUCCEEDED"
        assert result.payload=={"public_fixture":"TEST_ONLY"}
        assert reads==["read"]
        assert cp.durable.operation_status("op-read-api123",OWNER)["progress"]["work_item_id"]=="WI-api-consent"
        assert asyncio.run(svc.read_api(**payload)).duplicate
        assert reads==["read"]
        cp.authorization_revoke(grant["grant_id"],OWNER)
        with pytest.raises(PermissionError,match="distinct"):
            asyncio.run(svc.read_api(**{**payload,"operation_id":"op-new-read123",
                                        "idempotency_key":"idem-new-read123"}))
        assert reads==["read"]
    finally:
        cp.durable.close()
