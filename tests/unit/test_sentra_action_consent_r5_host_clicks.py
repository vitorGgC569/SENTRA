"""R5 host-minted click tokens, same owner/session, nonce, TTL and SQLite replay."""
import asyncio
import pytest
from sentra_mcp.services.action_consent_gate import (
    ActionConsentService, HostOwnerClickAuthenticator, HostOwnerSession)
from test_sentra_cos_chat2_action_and_message import _central, OWNER


def _setup(tmp_path):
    cp, _, args = _central(tmp_path)
    state=tmp_path/"state"
    now=[10000.0]
    session_id="operator-session-a-"+"A"*40
    context={"session":HostOwnerSession(
        OWNER,session_id,"http://127.0.0.1:8765",True)}
    resolver=lambda:context["session"]
    issuer=HostOwnerClickAuthenticator(state,session_lookup=resolver,
                                        clock=lambda:now[0])
    consent=ActionConsentService(state,owner_authenticator=issuer)
    return cp, args, context, now, issuer, consent


def _first(svc,issuer,owner=OWNER,revision=0,enabled=True):
    token=issuer.issue_click(owner=owner,purpose="api-consent")
    return svc.allow_api(owner=owner,agent_id="agent-001",work_item_id="WI-api-consent",
                         enabled=enabled,expected_revision=revision,
                         human_confirmed=True,owner_proof=token)


def _propose(svc,args):
    return svc.propose_action(**{k:args[k] for k in (
        "owner","agent_id","work_item_id","request_id","message_id","action","body")})


def test_host_clicks_same_session_nonce_origin_csrf_and_persistence(tmp_path):
    cp,args,ctx,now,issuer,svc=_setup(tmp_path)
    try:
        assert _first(svc,issuer)["revision"]==1
        prop=_propose(svc,args)
        click=issuer.issue_click(owner=OWNER,purpose="action:"+prop["action_id"])
        ctx["session"]=HostOwnerSession(OWNER,"operator-session-b-"+"B"*40,
                                          "http://127.0.0.1:8765",True)
        with pytest.raises(PermissionError,match="owner-auth"):
            svc.approve_action(action_id=prop["action_id"],body_sha256=prop["body_sha256"],
                human_confirmed=True,owner_proof=click)
        wrong_session=issuer.issue_click(owner=OWNER,purpose="action:"+prop["action_id"])
        with pytest.raises(PermissionError,match="same authenticated host session"):
            svc.approve_action(action_id=prop["action_id"],body_sha256=prop["body_sha256"],
                human_confirmed=True,owner_proof=wrong_session)
        ctx["session"]=HostOwnerSession(OWNER,"operator-session-a-"+"A"*40,
                                          "http://127.0.0.1:8765",False)
        with pytest.raises(PermissionError,match="CSRF"):
            issuer.issue_click(owner=OWNER,purpose="action:"+prop["action_id"])
        ctx["session"]=HostOwnerSession(OWNER,"operator-session-a-"+"A"*40,
                                          "http://127.0.0.1:9999",True)
        with pytest.raises(PermissionError,match="owner-auth"):
            svc.approve_action(action_id=prop["action_id"],body_sha256=prop["body_sha256"],
                               human_confirmed=True,owner_proof=click)
        ctx["session"]=HostOwnerSession(OWNER,"operator-session-a-"+"A"*40,
                                          "http://127.0.0.1:8765",True)
        expired=issuer.issue_click(owner=OWNER,purpose="action:"+prop["action_id"],ttl_s=1)
        now[0]+=2
        with pytest.raises(PermissionError,match="owner-auth"):
            svc.approve_action(action_id=prop["action_id"],body_sha256=prop["body_sha256"],
                               human_confirmed=True,owner_proof=expired)
        svc.approve_action(action_id=prop["action_id"],body_sha256=prop["body_sha256"],
                           human_confirmed=True,owner_proof=click)
        with pytest.raises(PermissionError):
            svc.approve_action(action_id=prop["action_id"],body_sha256=prop["body_sha256"],
                               human_confirmed=True,owner_proof=click)
        with pytest.raises(PermissionError,match="consumed"):
            issuer(owner=OWNER,purpose="action:"+prop["action_id"],owner_proof=click)
        cp.authorization_grant(OWNER,principal_type="agent",principal_id="agent-001",
            capability="api:action:sample",scope_type="work_item",scope_id="WI-api-consent")
        called=[]
        async def effect():
            called.append(1)
            return {"ok":True}
        execute=dict(**args,action_id=prop["action_id"],
             operation_id="op-r5-two-clicks",idempotency_key="idem-r5-two-clicks",
             host_effect=effect)
        result=asyncio.run(svc.execute(**execute))
        assert result.operation.state=="SUCCEEDED"
        restarted=ActionConsentService(tmp_path/"state",
            owner_authenticator=HostOwnerClickAuthenticator(
                tmp_path/"state",session_lookup=lambda:ctx["session"],
                clock=lambda:now[0]))
        assert asyncio.run(restarted.execute(**execute)).duplicate
        assert called==[1]
    finally:
        cp.durable.close()


def test_revoked_session_freezes_approved_action_before_effect(tmp_path):
    cp,args,ctx,now,issuer,svc=_setup(tmp_path)
    try:
        _first(svc,issuer)
        prop=_propose(svc,args)
        click=issuer.issue_click(owner=OWNER,purpose="action:"+prop["action_id"])
        svc.approve_action(action_id=prop["action_id"],body_sha256=prop["body_sha256"],
                           human_confirmed=True,owner_proof=click)
        cp.authorization_grant(OWNER,principal_type="agent",principal_id="agent-001",
            capability="api:action:sample",scope_type="work_item",scope_id="WI-api-consent")
        issuer.revoke_current_session(owner=OWNER)
        never=[]
        async def effect():
            never.append(1)
        with pytest.raises(PermissionError,match="revoked"):
            asyncio.run(svc.execute(**args,action_id=prop["action_id"],
                 operation_id="op-r5-revoked",idempotency_key="idem-r5-revoked",
                 host_effect=effect))
        assert never==[]
        with pytest.raises(FileNotFoundError):
            cp.durable.operation_status("op-r5-revoked",OWNER)
        with pytest.raises(PermissionError,match="revoked"):
            issuer.issue_click(owner=OWNER,purpose="api-consent")
    finally:
        cp.durable.close()
