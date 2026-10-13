"""Pulso enterprise scheduling: routine<->workflow and AP schedule bridges.

Future validation only (not executed during integral implementation).
"""
from __future__ import annotations

import pytest

from sentra_interop.workflow_scheduling import (
    RoutineWorkflowBinding, WorkflowScheduleConflict)
from sentra_interop.activepieces_scheduling import (
    ActivepiecesScheduleBridge, ActivepiecesScheduleConflict)


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


def test_ap_schedule_bind_and_drive(tmp_path):
    from types import SimpleNamespace
    bridge = ActivepiecesScheduleBridge(str(tmp_path / "ap.sqlite3"),
                                        workspace=str(tmp_path))
    schedule = {"cron": "0 9 * * *"}
    bridge.bind_schedule(owner="o", subscription_id="sub1", routine_id="r1",
                         piece="smtp", version="1.0.0", member="send",
                         connection_id=None, schedule=schedule,
                         enable_operation_id="op-enable",
                         operator_approved=True)
    request = SimpleNamespace(arguments={"subscription_id": "sub1"})
    outcome = bridge.schedule_handler(request, dict(schedule))
    assert outcome["routine_id"] == "r1"
    assert outcome["enqueued_here"] is False
    assert outcome["drive_via"] == "RoutineSchedulerService.tick"


def test_ap_webhook_dedupe(tmp_path):
    admitted = {}

    def fake_admitter(subscription_id, event_key, payload):
        assert subscription_id == "sub1"
        admitted[event_key] = payload
        return {"work_item_id": "w-" + event_key}

    bridge = ActivepiecesScheduleBridge(
        str(tmp_path / "ap.sqlite3"), workspace=str(tmp_path),
        trigger_admitter=fake_admitter)
    bridge.bind_schedule(owner="o", subscription_id="sub1", routine_id="r1",
                         piece="webhook", version="1.0.0", member="catch",
                         connection_id=None, schedule={"trigger": "webhook"},
                         enable_operation_id="op-enable",
                         operator_approved=True)
    first = bridge.webhook_handler(
        subscription_id="sub1",
        events=[{"_dedupe_key": "e1", "payload": {"n": 1}}])
    second = bridge.webhook_handler(
        subscription_id="sub1",
        events=[{"_dedupe_key": "e1", "payload": {"n": 1}}])
    assert first[0]["status"] == "ADMITTED"
    assert second[0]["status"] == "REUSED"
    assert second[0]["work_item_id"] == first[0]["work_item_id"]
    assert len(admitted) == 1
