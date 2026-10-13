"""Prepared acceptance for Lume. Do not execute until the coordinated final gate.

These cases use real ControlStore/vault persistence. They do not claim a live
ACP agent, external A2A peer, SDK server or Slack/Tg/WhatsApp account was used.
"""
import hashlib
import hmac
import json
import time

import pytest

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import OperationRequest
from sentra_interop.channels import ChannelService
from sentra_interop.provider_store import ProviderProjectionStore,digest
from sentra_interop.gate import EffectRejected


@pytest.fixture
def central(tmp_path):
    durable=DurableRunService(tmp_path/"central")
    control=ControlPlaneService(durable,ContextBusService(tmp_path/"central"))
    durable.create_run("owner",run_id="run",workspace=str(tmp_path))
    control.ensure_agent("run","owner",agent_id="agent",role="worker")
    control.create_work_item("run","owner",work_item_id="work",objective="Prepared Lume acceptance",
        assignee_agent_id="agent",required_capabilities=["channel:send"],metadata={"workspace_id":"project"})
    try:yield control
    finally:durable.close()


def request(op="one",work="work"):
    return OperationRequest("operation-"+op,"agent","machine","a2a:events",work,"request-"+op,{})


def test_artifact_chunks_are_atomic_deduplicated_and_recoverable(central):
    store=ProviderProjectionStore(central.store,"owner");req=request()
    store.prepare(req,"local","config")
    store.bind(req,"local","config","remote","context","working")
    part={"type":"text","text":"first"}
    payload={"part":part}
    result=store.ingest(req,"local",event_id="event-one",payload=payload,sequence=0,
        artifact={"artifact_id":"artifact","append":False,"complete":False,"parts":[part]})
    assert result["duplicate"] is False
    duplicate=store.ingest(req,"local",event_id="event-one",payload=payload,sequence=0,
        artifact={"artifact_id":"artifact","append":False,"complete":False,"parts":[part]})
    assert duplicate["duplicate"] is True
    second={"type":"text","text":"second"}
    store.ingest(req,"local",event_id="event-two",payload={"part":second},sequence=1,
        artifact={"artifact_id":"artifact","append":True,"complete":True,"parts":[second]})
    restored=ProviderProjectionStore(central.store,"owner")
    value=restored.artifact(req,"local","artifact")
    assert value["complete"] and value["parts"]==[part,second]
    assert value["sha256"]==digest([part,second])
    assert restored.get(request(work="another"),"local","config") is None
    with pytest.raises(EffectRejected):
        restored.ingest(req,"local",event_id="event-two",payload={"part":"changed"})


def test_stream_gap_does_not_apply_artifact_or_advance_cursor(central):
    store=ProviderProjectionStore(central.store,"owner");req=request()
    store.prepare(req,"local","config");store.bind(req,"local","config","remote","context","working")
    with pytest.raises(EffectRejected):
        store.ingest(req,"local",event_id="gap",payload={"text":"missing predecessor"},sequence=2,
            artifact={"artifact_id":"artifact","append":False,"complete":True,"parts":[]})
    assert store.get(req,"local","config")["sequence"]==-1
    with pytest.raises(FileNotFoundError):store.artifact(req,"local","artifact")


def slack_service(central):
    token=central.create_secret("owner",name="test-slack-token",value="test-token")["secret_id"]
    signing=central.create_secret("owner",name="test-slack-signing",value="test-signing")["secret_id"]
    service=ChannelService(central,owner="owner")
    service.configure(connector_id="slack-one",configuration={"kind":"slack","enabled":True,
        "project_id":"project","agent_id":"agent","team_id":"T1","scopes":["chat:write"],
        "token_ref":token,"signing_secret_ref":signing,"routes":[{"external_workspace":"T1",
        "external_conversation":"C1","sender_ids":["U1"],"conversation_id":"conversation-one","space_id":"space-one"}]})
    return service


def signed_event(*,event_id="E1",sender="U1",text="authorized text"):
    body=json.dumps({"type":"event_callback","team_id":"T1","event_id":event_id,
        "event":{"type":"message","user":sender,"channel":"C1","ts":"1.1","text":text}}).encode()
    stamp=str(int(time.time()))
    signature="v0="+hmac.new(b"test-signing",b"v0:"+stamp.encode()+b":"+body,hashlib.sha256).hexdigest()
    return body,{"X-Slack-Signature":signature,"X-Slack-Request-Timestamp":stamp}


def test_signed_channel_inbox_restarts_without_implicit_dispatch_or_duplicate_claim(central):
    service=slack_service(central);body,headers=signed_event()
    ack=service.receive(connector_id="slack-one",raw_body=body,headers=headers)
    assert ack["effect_dispatched"] is False and ack["accepted"][0]["project_id"]=="project"
    restarted=ChannelService(central,owner="owner")
    duplicate=restarted.receive(connector_id="slack-one",raw_body=body,headers=headers)
    assert duplicate["accepted"][0]["duplicate"] is True
    pending=restarted.pending_inbound(connector_id="slack-one",project_id="project")
    assert len(pending)==1 and pending[0]["payload"]["text"]=="authorized text"
    claim=restarted.claim(connector_id="slack-one",event_id="E1",consumer_id="workflow",
                          expected_revision=pending[0]["revision"])
    assert claim["dispatch_idempotency_key"]=="channel:slack-one:E1"
    with pytest.raises(EffectRejected):
        restarted.claim(connector_id="slack-one",event_id="E1",consumer_id="another",expected_revision=1)
    assert restarted.pending_inbound(connector_id="slack-one",project_id="project")==[]


def test_channel_signature_sender_and_changed_replay_fail_closed(central):
    service=slack_service(central);body,headers=signed_event()
    bad=dict(headers);bad["X-Slack-Signature"]="v0="+"0"*64
    with pytest.raises(EffectRejected):service.receive(connector_id="slack-one",raw_body=body,headers=bad)
    body,headers=signed_event(sender="attacker")
    with pytest.raises(EffectRejected):service.receive(connector_id="slack-one",raw_body=body,headers=headers)
    body,headers=signed_event();service.receive(connector_id="slack-one",raw_body=body,headers=headers)
    body,headers=signed_event(text="changed")
    with pytest.raises(EffectRejected):service.receive(connector_id="slack-one",raw_body=body,headers=headers)
