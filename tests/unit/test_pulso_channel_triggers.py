"""Pulso channel trigger bridge against Lume's ChannelService contract.

Future validation only (not executed during integral implementation).
The fake implements Lume's exact claim/ack semantics (CAS revision, no
automatic reassignment, SUCCEEDED-only acknowledgement).
"""
from __future__ import annotations

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
        self.claimed[key] = {"consumer_id": consumer_id}
        return {"claim_id": "claim-" + event_id, "event_id": event_id,
                "connector_id": connector_id, "project_id": "ws1",
                "workspace_id": "ws1",
                "revision": expected_revision + 1,
                "dispatch_idempotency_key": "channel:" + key}

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
    acked = trigger.ack_claim("owner1", claim_id="claim-e1",
                              work_item_id="wi1", operation_id="op1")
    assert acked["status"] == "acknowledged"


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


class FakeDurableControl:
    def __init__(self, state="SUCCEEDED", work_item_id="wi1"):
        self.durable = SimpleNamespace(
            operation_status=lambda operation_id, owner: {
                "operation_id": operation_id, "state": state, "run_id": "run1",
                "progress": {"work_item_id": work_item_id}})


def test_trigger_confirm_dispatch_acks_only_on_succeeded(tmp_path):
    service = FakeChannelService()
    control = FakeDurableControl()
    trigger = _trigger(tmp_path, service=service, control=control)
    trigger.bind_route(owner="owner1", connector_id="tg1", workflow_id="wf1",
                       signal_name="channel_message", operator_approved=True)
    bound = trigger.claim_for_workflow(
        "owner1", connector_id="tg1", event_id="e1",
        consumer_id="pulso-trigger:vitor", expected_revision=1)
    trigger.mark_admitted(dispatch_key="channel:tg1:e1", operation_id="op9")
    done = trigger.confirm_dispatch(
        "owner1", dispatch_key="channel:tg1:e1", work_item_id="wi1",
        operation_id="op9")
    assert done["status"] == "acknowledged"
    failing = _trigger(tmp_path, service=FakeChannelService(),
                       control=FakeDurableControl(state="RUNNING"))
    failing.bind_route(owner="owner1", connector_id="tg1",
                       workflow_id="wf1", signal_name="channel_message",
                       operator_approved=True)
    failing.claim_for_workflow(
        "owner1", connector_id="tg1", event_id="e9",
        consumer_id="pulso-trigger:vitor", expected_revision=1)
    failing.mark_admitted(dispatch_key="channel:tg1:e9", operation_id="op8")
    pending = failing.confirm_dispatch(
        "owner1", dispatch_key="channel:tg1:e9", work_item_id="wi1",
        operation_id="op8")
    assert pending["status"] == "uncertain"
    with pytest.raises(Exception):
        failing.confirm_dispatch(
            "owner1", dispatch_key="channel:tg1:e9", work_item_id="other",
            operation_id="op8")
