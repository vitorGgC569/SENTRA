"""Encrypted peer offer -> real SENTRA local host -> authorization/ledger.

Proves *admission only*, never remote tool/model execution or 2-PC Hamachi.
"""
from __future__ import annotations

import hashlib
import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.peer_work_wire import PeerWireDenied
from sentra_canvas.peer_admission import admit_pending_offer
from sentra_mcp.services.authorization import AuthorizationService
from sentra_runtime.executor import AuthorizationRequired
from test_canvas_peer_work_wire import pair, message


@pytest.fixture
def hosts(tmp_path):
    app=Canvas(tmp_path/"product",state_dir=tmp_path/"product-state")
    try:
        ws=app.create_workspace("PeerAdmissionQA")["id"]
        local=app.create_agent(ws,"ReceiverWorker","sentra/codex/current",start=False)
        origin=app.create_agent(ws,"SenderWorker","sentra/codex/current",start=False)
        a,b,alice,bob=pair(tmp_path,workspace=ws)
        yield app,ws,local,origin,a,b,alice,bob
    finally:
        app.shutdown()


def incoming(hosts):
    app,ws,local,origin,a,b,alice,bob=hosts
    frame=message(alice,bob,subject="WI-REMOTE")
    body,replayed=bob.accept(frame)
    assert replayed is False
    return body


def local_item(hosts, *,remote_peer=None,remote_subject="WI-REMOTE"):
    app,ws,local,origin,a,b,alice,bob=hosts
    rt=app._runtime()
    run=rt.run(ws)
    item=rt.governance.create_work_item(
        run["run_id"],rt.owner,
        work_item_id="WI-LOCAL",
        objective="Safely acknowledge remote signed task reference",
        assignee_agent_id=local["id"],
        required_capabilities=["peer.task.accept"],
        metadata={
            "workspace_id":ws,
            "remote_peer_id":remote_peer or a.node_id,
            "remote_subject_id":remote_subject,
        },
    )
    rt.governance.transition_work_item("WI-LOCAL",rt.owner,"RUNNING")
    return rt


def admit(hosts,body):
    app,ws,local,origin,a,b,alice,bob=hosts
    return admit_pending_offer(
        canvas=app,wire=bob,workspace_id=ws,
        sender=body["source"],message_id=body["message_id"],
        local_work_item_id="WI-LOCAL",
    )


def test_receiver_requires_local_workitem_and_separate_grant(hosts):
    body=incoming(hosts)
    with pytest.raises((FileNotFoundError,PermissionError,PeerWireDenied)):
        admit(hosts,body)
    rt=local_item(hosts)
    with pytest.raises(AuthorizationRequired,match="grant denied"):
        admit(hosts,body)
    assert len(hosts[-1].inbox())==1
    assert hosts[-1].inbox()[0]["state"]=="PENDING_LOCAL_ADMISSION"
    app,ws,local,origin,a,b,alice,bob=hosts
    auth=AuthorizationService(app.state_dir.parent)
    grant=auth.grant(
        rt.owner,principal_type="agent",principal_id=local["id"],
        capability="peer.task.accept",
        scope_type="work_item",scope_id="WI-LOCAL",
    )
    approved=admit(hosts,body)
    assert approved["state"]=="ADMITTED_LOCAL_NO_EFFECT"
    assert approved["remote_task_executed"] is False
    assert approved["receipt_is_work_completion"] is False
    assert bob.inbox()[0]["state"]=="ADMITTED_LOCAL_NO_EFFECT"
    op=rt.durable.operation_status(approved["operation_id"],rt.owner)
    assert op["state"]=="SUCCEEDED"
    with pytest.raises(PeerWireDenied,match="already processed"):
        admit(hosts,body)
    auth.revoke(grant["grant_id"],rt.owner)
    assert bob.inbox()[0]["state"]=="ADMITTED_LOCAL_NO_EFFECT"


def test_wrong_remote_peer_or_subject_denied_without_operation(hosts):
    body=incoming(hosts)
    rt=local_item(hosts,remote_peer="peer-not-our-allowed-sender")
    app,ws,local,origin,a,b,alice,bob=hosts
    auth=AuthorizationService(app.state_dir.parent)
    auth.grant(rt.owner,principal_type="agent",principal_id=local["id"],
               capability="peer.task.accept",scope_type="work_item",
               scope_id="WI-LOCAL")
    with pytest.raises(PeerWireDenied,match="mapping"):
        admit(hosts,body)
    assert bob.inbox()[0]["state"]=="PENDING_LOCAL_ADMISSION"
    with rt.durable.lock:
        assert rt.durable.db.execute("SELECT COUNT(*) FROM operations").fetchone()[0]==0


def test_cross_workspace_identity_not_accepted(hosts):
    body=incoming(hosts)
    local_item(hosts)
    app,ws,local,origin,a,b,alice,bob=hosts
    other=app.create_workspace("OtherPeer")["id"]
    with pytest.raises(PeerWireDenied,match="trusted peer/workspace"):
        admit_pending_offer(
            canvas=app,wire=bob,workspace_id=other,
            sender=a.node_id,message_id=body["message_id"],
            local_work_item_id="WI-LOCAL",
        )


def test_offer_without_pinned_verified_signed_inbox_denied(hosts):
    app,ws,local,origin,a,b,alice,bob=hosts
    rt=local_item(hosts)
    with pytest.raises(PeerWireDenied,match="authenticated pending"):
        admit_pending_offer(
            canvas=app,wire=bob,workspace_id=ws,
            sender=a.node_id,message_id="unverified-id",
            local_work_item_id="WI-LOCAL",
        )


def test_forged_client_does_not_create_receiver_authorization(hosts):
    body=incoming(hosts)
    rt=local_item(hosts)
    app,ws,local,origin,a,b,alice,bob=hosts
    auth=AuthorizationService(app.state_dir.parent)
    # The presence of the *sender* grant does not replace recipient admission.
    auth.grant(rt.owner,principal_type="agent",principal_id=origin["id"],
               capability="peer.task.accept",scope_type="work_item",
               scope_id="WI-LOCAL")
    with pytest.raises(AuthorizationRequired,match="grant denied"):
        admit(hosts,body)
    assert bob.inbox()[0]["state"]=="PENDING_LOCAL_ADMISSION"
