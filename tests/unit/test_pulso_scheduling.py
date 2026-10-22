"""Pulso enterprise scheduling: routine<->workflow and AP schedule bridges.

Future validation only (not executed during integral implementation).
"""
from __future__ import annotations

import asyncio
import pytest

from sentra_interop.workflow_scheduling import (
    RoutineWorkflowBinding, WorkflowScheduleConflict)
from sentra_interop.activepieces_scheduling import (
    ActivepiecesScheduleBridge, ActivepiecesScheduleConflict)
from sentra_runtime.contracts import OperationRequest
from sentra_interop.workflow_contracts import digest


@pytest.fixture
def authority(tmp_path):
    from pulso_test_authority import make_authority
    center = make_authority(tmp_path / "central", ("activepieces:trigger_enable", "activepieces:trigger_ingest"), owner="o")
    try:
        yield center
    finally:
        center.control.durable.close()


def test_routine_workflow_bind_requires_approval(tmp_path):
    binding = RoutineWorkflowBinding(str(tmp_path / "sched.sqlite3"),
                                     workspace=str(tmp_path))
    with pytest.raises(PermissionError):
        binding.bind(owner="o", routine_id="r1", workflow_id="wf1",
                     definition_id="doc", definition_version="v1",
                     intent_kind="advance")


def test_routine_workflow_occurrence_idempotent(tmp_path):
    binding = RoutineWorkflowBinding(str(tmp_path / "sched.sqlite3"),
                                     workspace=str(tmp_path))
    binding.bind(owner="o", routine_id="r1", workflow_id="wf1",
                 definition_id="doc", definition_version="v1",
                 intent_kind="advance", operator_approved=True)
    first = binding.intent_for_occurrence(owner="o", routine_id="r1",
                                         occurrence_key="2026-01-01T00:00:00")
    second = binding.intent_for_occurrence(owner="o", routine_id="r1",
                                          occurrence_key="2026-01-01T00:00:00")
    assert first == second
    assert first["capability_id"] == "workflow:advance"
    assert first["already_admitted"] is False
    binding.mark_admitted(routine_id="r1",
                          occurrence_key="2026-01-01T00:00:00",
                          operation_id="op1")
    third = binding.intent_for_occurrence(owner="o", routine_id="r1",
                                         occurrence_key="2026-01-01T00:00:00")
    assert third["already_admitted"] is True


def test_routine_workflow_rebind_conflict(tmp_path):
    binding = RoutineWorkflowBinding(str(tmp_path / "sched.sqlite3"),
                                     workspace=str(tmp_path))
    binding.bind(owner="o", routine_id="r1", workflow_id="wf1",
                 definition_id="doc", definition_version="v1",
                 intent_kind="advance", operator_approved=True)
    with pytest.raises(WorkflowScheduleConflict):
        binding.bind(owner="o", routine_id="r1", workflow_id="wf2",
                     definition_id="doc", definition_version="v1",
                     intent_kind="advance", operator_approved=True)


def test_routine_workflow_signal_intent(tmp_path):
    binding = RoutineWorkflowBinding(str(tmp_path / "sched.sqlite3"),
                                     workspace=str(tmp_path))
    binding.bind(owner="o", routine_id="r1", workflow_id="wf1",
                 definition_id="doc", definition_version="v1",
                 intent_kind="signal", signal_name="tick",
                 operator_approved=True)
    intent = binding.intent_for_occurrence(owner="o", routine_id="r1",
                                          occurrence_key="k1",
                                          signal_payload={"n": 1})
    assert intent["capability_id"] == "workflow:signal"
    assert intent["arguments"]["signal_id"].startswith("sched-")


def test_ap_schedule_handler_without_binding_fails(tmp_path):
    from types import SimpleNamespace
    bridge = ActivepiecesScheduleBridge(str(tmp_path / "ap.sqlite3"),
                                        workspace=str(tmp_path))
    request = SimpleNamespace(arguments={"subscription_id": "sub1"})
    with pytest.raises(PermissionError):
        bridge.schedule_handler(request, {"cron": "* * * * *"})


def test_ap_schedule_bind_and_drive(tmp_path, authority):
    from types import SimpleNamespace
    bridge = ActivepiecesScheduleBridge(str(tmp_path / "ap.sqlite3"),
                                        workspace=str(tmp_path), control=authority.control)
    schedule = {"cronExpression": "0 9 * * *", "timezone":"UTC"}
    routine = authority.control.create_routine("o", name="Synthetic schedule", trigger_kind="schedule",
        trigger_spec={"cron":"0 9 * * *", "timezone":"UTC"}, work_template={"objective":"Unit schedule"})
    bridge.bind_schedule(owner="o", subscription_id="sub1", routine_id=routine["routine_id"],
                         piece="smtp", version="1.0.0", member="send",
                         connection_id=None, schedule=schedule,
                         enable_operation_id="op-enable",
                         operator_approved=True)
    request = OperationRequest("op-enable", "agent1", "machine1", "activepieces:trigger_enable", "wi1", "enable-1", {"subscription_id":"sub1"})
    with pytest.raises(PermissionError, match="admitted hook"):
        bridge.schedule_handler(request, dict(schedule))
    async def provider(request):
        return bridge.schedule_handler(request, dict(schedule))
    authority.bind_provider("activepieces:trigger_enable", provider)
    result = asyncio.run(authority.start(request))
    assert result.state == "SUCCEEDED", result
    outcome = result.evidence["payload"]
    assert outcome["routine_id"] == routine["routine_id"]
    assert outcome["enqueued_here"] is False
    assert outcome["drive_via"] == "RoutineSchedulerService.tick"


def test_ap_webhook_dedupe(tmp_path, authority):
    admitted = {}

    def fake_admitter(subscription_id, event_key, payload):
        assert subscription_id == "sub1"
        admitted[event_key] = payload
        return authority.control.create_work_item("run1", "o", work_item_id="w-" + event_key,
            objective="Synthetic webhook", metadata={"workspace_id":"ws1"})

    bridge = ActivepiecesScheduleBridge(
        str(tmp_path / "ap.sqlite3"), workspace=str(tmp_path),
        trigger_admitter=fake_admitter, control=authority.control)
    bridge.bind_schedule(owner="o", subscription_id="sub1", routine_id="r1",
                         piece="webhook", version="1.0.0", member="catch",
                         connection_id=None, schedule={"trigger": "webhook"},
                         enable_operation_id="op-enable",
                         operator_approved=True)
    events = [{"_dedupe_key": "e1", "payload": {"n": 1}}]
    with pytest.raises(PermissionError, match="exact central ingestion"):
        bridge.webhook_handler(subscription_id="sub1", events=events)
    async def enable(request):
        return {"enabled":True}
    async def ingest(request):
        return bridge.webhook_handler(subscription_id="sub1", events=events)
    authority.bind_provider("activepieces:trigger_enable", enable)
    authority.bind_provider("activepieces:trigger_ingest", ingest)
    enabled = asyncio.run(authority.start(OperationRequest("op-enable", "agent1", "machine1", "activepieces:trigger_enable", "wi1", "enable-1", {"subscription_id":"sub1"})))
    assert enabled.state == "SUCCEEDED", enabled
    def dispatch(operation_id):
        result = asyncio.run(authority.start(OperationRequest(operation_id, "agent1", "machine1", "activepieces:trigger_ingest", "wi1", operation_id, {"subscription_id":"sub1", "events_sha256":digest(events)})))
        assert result.state == "SUCCEEDED", result
        return result.evidence["payload"]
    first, second = dispatch("op-first"), dispatch("op-second")
    assert first[0]["status"] == "ADMITTED"
    assert second[0]["status"] == "REUSED"
    assert second[0]["work_item_id"] == first[0]["work_item_id"]
    assert len(admitted) == 1
