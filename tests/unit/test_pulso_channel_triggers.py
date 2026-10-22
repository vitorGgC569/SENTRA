"""Pulso channel trigger bridge against Lume's ChannelService contract.

Future validation only (not executed during integral implementation).
The fake implements Lume's exact claim/ack semantics (CAS revision, no
automatic reassignment, SUCCEEDED-only acknowledgement).
"""
from __future__ import annotations

import asyncio

import pytest

from sentra_interop.gate import EffectRejected
from sentra_interop.workflow_channel_triggers import (
    ChannelTriggerConflict, ChannelWorkflowTrigger)


class FakeChannelService:
    owner = "owner1"

    def __init__(self):
        self.claimed: dict[str, dict] = {}

    def pending_inbound(self, *, connector_id, project_id, limit=100):
        return [{"connector_id": connector_id, "event_id": "e1",
                 "project_id": project_id, "workspace_id": project_id,
                 "conversation_id": "conv1", "space_id": None,
                 "agent_id": "agent1", "revision": 1,
                 "payload": {"text": "ship it", "sender": "U1"},
                 "chat_trust_inherited": False}]

    def claim(self, *, connector_id, event_id, consumer_id,
              expected_revision, lease_seconds=60):
        key = connector_id + ":" + event_id
        if key in self.claimed:
            raise EffectRejected(
                "channel event already claimed; reconcile before dispatch")
        claim = {"consumer_id": consumer_id, "claim_id": "claim-" + event_id, "event_id": event_id,
                "connector_id": connector_id, "project_id": "ws1",
                "workspace_id": "ws1",
                "revision": expected_revision + 1,
                "dispatch_idempotency_key": "channel:" + key}
        self.claimed[key] = claim
        return dict(claim)

    def inbound_claim(self, *, connector_id, event_id, consumer_id=None):
        claim = self.claimed.get(connector_id + ":" + event_id)
        if claim is not None and consumer_id not in (None, claim["consumer_id"]):
            raise EffectRejected("claim belongs to another consumer")
        return dict(claim) if claim is not None else None

    def claimed_payload(self, *, connector_id, event_id, claim_id):
        claim = self.inbound_claim(connector_id=connector_id, event_id=event_id)
        assert claim is not None and claim["claim_id"] == claim_id
        return {"text": "ship it", "sender": "U1"}

    def ack(self, *, claim_id, work_item_id, operation_id, receipt_id=None):
        return {"claim_id": claim_id, "status": "acknowledged",
                "operation_id": operation_id,
                "receipt_id": receipt_id or operation_id}


def _trigger(tmp_path, **kwargs):
    service = kwargs.pop("service", FakeChannelService())
    return ChannelWorkflowTrigger(
        str(tmp_path / "trig.sqlite3"), workspace=str(tmp_path),
        channel_service=service, **kwargs)


def test_trigger_claim_binds_workflow_intent(tmp_path):
    trigger = _trigger(tmp_path)
    trigger.bind_route(owner="owner1", connector_id="tg1", workflow_id="wf1",
                       signal_name="channel_message", operator_approved=True)
    bound = trigger.claim_for_workflow(
        "owner1", connector_id="tg1", event_id="e1",
        consumer_id="pulso-trigger:vitor", expected_revision=1)
    assert bound["capability_id"] == "workflow:signal"
    assert bound["dispatch_idempotency_key"] == "channel:tg1:e1"
    assert bound["arguments"]["signal_id"].startswith("ch-")
    assert bound["effects_started"] is False
    assert bound["already_admitted"] is False
    # Same dispatch key replays the recorded intent instead of duplicating.
    trigger.channel_service.claimed.clear()
    replayed = trigger.claim_for_workflow(
        "owner1", connector_id="tg1", event_id="e1",
        consumer_id="pulso-trigger:vitor", expected_revision=2)
    assert replayed["arguments"] == bound["arguments"]
    trigger.mark_admitted(dispatch_key="channel:tg1:e1", operation_id="op1")
    with pytest.raises(ChannelTriggerConflict, match="central control required"):
        trigger.ack_claim("owner1", claim_id="claim-e1", work_item_id="wi1", operation_id="op1")


def test_trigger_refuses_unrouted_connector(tmp_path):
    trigger = _trigger(tmp_path)
    with pytest.raises(ChannelTriggerConflict):
        trigger.claim_for_workflow(
            "owner1", connector_id="nope", event_id="e1",
            consumer_id="pulso-trigger:vitor", expected_revision=1)


def test_trigger_never_reassigns_claim(tmp_path):
    trigger = _trigger(tmp_path)
    trigger.bind_route(owner="owner1", connector_id="tg1", workflow_id="wf1",
                       signal_name="channel_message", operator_approved=True)
    trigger.claim_for_workflow(
        "owner1", connector_id="tg1", event_id="e1",
        consumer_id="pulso-trigger:vitor", expected_revision=1)
    with pytest.raises(EffectRejected):
        trigger.claim_for_workflow(
            "owner1", connector_id="tg1", event_id="e1",
            consumer_id="pulso-trigger:other", expected_revision=2)


def test_trigger_route_rebind_conflict(tmp_path):
    trigger = _trigger(tmp_path)
    trigger.bind_route(owner="owner1", connector_id="tg1", workflow_id="wf1",
                       signal_name="channel_message", operator_approved=True)
    with pytest.raises(ChannelTriggerConflict):
        trigger.bind_route(owner="owner1", connector_id="tg1",
                           workflow_id="wf2", signal_name="channel_message",
                           operator_approved=True)
    with pytest.raises(PermissionError):
        trigger.bind_route(owner="owner1", connector_id="tg2",
                           workflow_id="wf1", signal_name="s")


def test_trigger_service_owner_mismatch(tmp_path):
    service = FakeChannelService()
    service.owner = "someone-else"
    trigger = _trigger(tmp_path, service=service)
    with pytest.raises(PermissionError):
        trigger.poll("owner1", connector_id="tg1", project_id="ws1")


@pytest.fixture
def authority(tmp_path):
    from pulso_test_authority import make_authority
    center = make_authority(tmp_path / "central", "workflow:signal")
    async def provider(request):
        return {"signal_id":request.arguments["signal_id"]}
    center.bind_provider("workflow:signal", provider)
    try:
        yield center
    finally:
        center.control.durable.close()


def test_trigger_confirm_dispatch_acks_only_on_succeeded(tmp_path, authority):
    from sentra_runtime.contracts import OperationRequest
    service = FakeChannelService()
    control = authority.control
    trigger = _trigger(tmp_path, service=service, control=control)
    trigger.bind_route(owner="owner1", connector_id="tg1", workflow_id="wf1",
                       signal_name="channel_message", operator_approved=True)
    bound = trigger.claim_for_workflow(
        "owner1", connector_id="tg1", event_id="e1",
        consumer_id="pulso-trigger:vitor", expected_revision=1)
    trigger.mark_admitted(dispatch_key="channel:tg1:e1", operation_id="op9")
    request = OperationRequest("op9", "agent1", "machine1", "workflow:signal", "wi1",
        "pulso:channel:tg1:e1", bound["arguments"])
    result = asyncio.run(authority.start(request))
    assert result.state == "SUCCEEDED", result
    done = trigger.confirm_dispatch(
        "owner1", dispatch_key="channel:tg1:e1", work_item_id="wi1",
        operation_id="op9")
    assert done["status"] == "acknowledged"
    failing = _trigger(tmp_path, service=FakeChannelService(), control=control)
    failing.bind_route(owner="owner1", connector_id="tg1",
                       workflow_id="wf1", signal_name="channel_message",
                       operator_approved=True)
    failing.claim_for_workflow(
        "owner1", connector_id="tg1", event_id="e9",
        consumer_id="pulso-trigger:vitor", expected_revision=1)
    failing.mark_admitted(dispatch_key="channel:tg1:e9", operation_id="op8")
    control.durable.create_operation("run1", "owner1", kind="sentra.machine", operation_id="op8", idempotency_key="pending-8")
    control.durable.update_operation("op8", "owner1", state="RUNNING", progress={"work_item_id":"wi1"})
    pending = failing.confirm_dispatch(
        "owner1", dispatch_key="channel:tg1:e9", work_item_id="wi1",
        operation_id="op8")
    assert pending["status"] == "uncertain"
    with pytest.raises(Exception):
        failing.confirm_dispatch(
            "owner1", dispatch_key="channel:tg1:e9", work_item_id="other",
            operation_id="op8")
