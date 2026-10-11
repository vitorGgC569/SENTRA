"""Fail-closed two human clicks verified by the host and consumed in SQLite."""
import asyncio
import pytest
from sentra_mcp.services.action_consent_gate import ActionConsentService
from test_sentra_cos_chat2_action_and_message import _central, OWNER


def _verifier(owner,purpose,proof):
    # Test-only fake local session verifier, NOT evidence of production auth.
    return OWNER if owner==OWNER and proof.startswith("verified-click-") else None


def test_owner_auth_required_not_boolean_and_two_assertions_are_single_use(tmp_path):
    cp,legacy,args=_central(tmp_path)
    state=tmp_path/"state"
    try:
        base=dict(owner=OWNER,agent_id=args["agent_id"],work_item_id=args["work_item_id"],
                  enabled=True,expected_revision=0,human_confirmed=True)
        # Old Chat2 caller's boolean now fails closed even with a live Web message.
        with pytest.raises(PermissionError,match="owner-auth"):
            legacy.allow_api(**base)
        svc=ActionConsentService(state,owner_authenticator=_verifier)
        with pytest.raises(PermissionError,match="owner-auth"):
            svc.allow_api(**base,owner_proof="no-session-"*3)
        svc.allow_api(**base,owner_proof="verified-click-01-unique-proof")
        with pytest.raises(PermissionError,match="already consumed"):
            svc.allow_api(**{**base,"enabled":False,"expected_revision":1},
                          owner_proof="verified-click-01-unique-proof")
        proposal=svc.propose_action(**{k:args[k] for k in
                ("owner","agent_id","work_item_id","request_id","message_id","action","body")})
        with pytest.raises(PermissionError,match="owner-auth"):
            svc.approve_action(action_id=proposal["action_id"],
                body_sha256=proposal["body_sha256"],human_confirmed=True)
        svc.approve_action(action_id=proposal["action_id"],
            body_sha256=proposal["body_sha256"],human_confirmed=True,
            owner_proof="verified-click-02-unique-proof")
        with pytest.raises(PermissionError):
            svc.approve_action(action_id=proposal["action_id"],
                body_sha256=proposal["body_sha256"],human_confirmed=True,
                owner_proof="verified-click-03-unique-proof")
        cp.authorization_grant(OWNER,principal_type="agent",
             principal_id="agent-001",capability="api:action:sample",
             scope_type="work_item",scope_id="WI-api-consent")
        effect_calls=[]
        async def effect():
            effect_calls.append(1)
            return {"approved":True}
        payload=dict(**args,action_id=proposal["action_id"],
                     operation_id="op-consent-new-auth",
                     idempotency_key="idem-consent-new-auth",host_effect=effect)
        first=asyncio.run(svc.execute(**payload))
        replay=asyncio.run(svc.execute(**payload))
        assert first.operation.state=="SUCCEEDED" and replay.duplicate
        assert effect_calls==[1]
        assert cp.durable.operation_status("op-consent-new-auth",OWNER)["state"]=="SUCCEEDED"
        # Another service sees the same consumed assertion after restart.
        restarted=ActionConsentService(state,owner_authenticator=_verifier)
        with pytest.raises(PermissionError,match="already consumed"):
            restarted.allow_api(**{**base,"enabled":False,"expected_revision":1},
                       owner_proof="verified-click-01-unique-proof")
    finally:
        cp.durable.close()
