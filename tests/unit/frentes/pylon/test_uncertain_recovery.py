"""Front 7: reconcile conversations, operations and grants without a second effect."""
from __future__ import annotations

import json
import sqlite3

import pytest

from orchestrator.durable_resources import DurableResourceLeaseManager
from orchestrator.failure_summary import summarize_incident
from orchestrator.models import Task, TaskStatus
from orchestrator.reconcile import classify_seat
from orchestrator.state_machine import InvalidStateTransitionError, TaskStateMachine
from sentra_executors.operation_receipts import HumanReceiptViews
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.uncertain_recovery import INCIDENTS, UncertainRecovery


def _services(tmp_path):
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    return durable, context, control


def _snapshot():
    return {
        "operations": [
            {"id": "op-open", "state": "UNCERTAIN"},
            {"id": "op-done", "state": "SUCCEEDED"},
        ],
        "conversations": [
            {"id": "conv-open", "state": "uncertain"},
            {"id": "conv-done", "state": "completed"},
        ],
        "grants": [
            {"id": "grant-live", "state": "active"},
            {"id": "grant-mid", "state": "claimed"},
        ],
        "work_items": [
            {"id": "work-review", "state": "IN_REVIEW"},
            {"id": "work-done", "state": "COMPLETED"},
        ],
        "relay_jobs": [
            {"id": "job-queued", "state": "QUEUED"},
            {"id": "job-done", "state": "COMPLETED"},
        ],
    }


def test_every_incident_plans_observation_without_resend():
    base = None
    for incident in ("crash", "canvas_closed", "relay_down", "reboot"):
        first = UncertainRecovery(incident).reconcile(**_snapshot())
        second = UncertainRecovery(incident).reconcile(**_snapshot())
        assert first == second
        assert first["effects_executed"] == 0
        assert first["may_resend"] is False
        assert first["automatic_retry"] is False
        assert first["second_effect"] is False
        assert first["promoted_work_items"] == 0
        assert all(item["action"] == "none" and item["may_resend"] is False for item in first["items"])
        by_id = {item["id"]: item for item in first["items"]}
        assert by_id["op-open"]["disposition"] == "observe"
        assert by_id["op-done"]["disposition"] == "preserve"
        assert by_id["conv-open"]["disposition"] == "blocked"
        assert by_id["conv-done"]["disposition"] == "preserve"
        assert by_id["grant-live"]["disposition"] == "preserve"
        assert by_id["grant-mid"]["disposition"] == "observe"
        assert by_id["work-review"]["disposition"] == "observe"
        assert by_id["work-done"]["disposition"] == "preserve"
        assert by_id["job-queued"]["disposition"] == "blocked"
        assert by_id["job-done"]["disposition"] == "preserve"
        if base is None:
            base = first["digest"]
        else:
            assert first["digest"] != base
    with pytest.raises(ValueError):
        UncertainRecovery("not-an-incident")
    assert INCIDENTS == {"crash", "canvas_closed", "relay_down", "reboot"}


def test_durable_recovery_does_not_rewrite_uncertain_operation(tmp_path):
    durable, context, control = _services(tmp_path)
    owner = "pylon-recovery"
    try:
        run_id = durable.create_run(owner, workspace="pylon-lab")["run_id"]
        operation = durable.create_operation(run_id, owner, kind="pylon.observe",
            idempotency_key="pylon-uncertain-op", initial_state="RUNNING",
            cleanup_policy="manual")
        durable.update_operation(operation["operation_id"], owner, state="UNCERTAIN",
            result={"stdout": "SECRET_PATH C:\\private\\do-not-leak", "secret": "token=abc"})
        before = durable.operation_status(operation["operation_id"], owner)
        recovery = UncertainRecovery("reboot")
        plan = recovery.reconcile_durable(
            control, owner, run_id,
            conversations=({"id": "conv-1", "state": "uncertain"},),
            grants=({"id": "grant-1", "state": "active"},),
            work_items=({"id": "work-1", "state": "IN_REVIEW"},),
            relay_jobs=({"id": "job-1", "state": "LEASED"},),
        )
        again = recovery.reconcile_durable(control, owner, run_id,
            conversations=({"id": "conv-1", "state": "uncertain"},),
            grants=({"id": "grant-1", "state": "active"},),
            work_items=({"id": "work-1", "state": "IN_REVIEW"},),
            relay_jobs=({"id": "job-1", "state": "LEASED"},))
        after = durable.operation_status(operation["operation_id"], owner)
        assert after["state"] == "UNCERTAIN"
        assert after["updated_at"] == before["updated_at"]
        assert plan == again
        assert plan["promoted_work_items"] == 0
        assert plan["effects_executed"] == 0
        view = HumanReceiptViews(control).recovery_projection(
            owner, operation["operation_id"], incident="reboot")
        rendered = json.dumps(view)
        assert view["disposition"] == "observe"
        assert view["may_resend"] is False
        assert view["requires_reconciliation"] is True
        assert "SECRET" not in rendered
        assert "token" not in rendered
        assert "private" not in rendered
        summary = summarize_incident({"incident": "reboot", "items": plan["items"],
            "stdout": "SECRET", "path": "C:\\private\\leak"})
        assert "SECRET" not in json.dumps(summary)
        assert "private" not in json.dumps(summary)
        assert summary["effects_executed"] == 0
    finally:
        context.close()
        durable.close()


def test_retry_and_lease_admission_do_not_start_a_second_effect(tmp_path):
    task = Task(id="T-pylon", run_id="run-pylon", objective="observe")
    TaskStateMachine.transition(task, TaskStatus.FAILED)
    task.metadata["effect_state"] = "UNCERTAIN"
    with pytest.raises(InvalidStateTransitionError):
        TaskStateMachine.transition(task, TaskStatus.RETRYING)
    assert task.status == TaskStatus.FAILED
    clean = Task(id="T-clean", run_id="run-pylon", objective="retry clean")
    TaskStateMachine.transition(clean, TaskStatus.FAILED)
    TaskStateMachine.transition(clean, TaskStatus.RETRYING)
    assert clean.status == TaskStatus.RETRYING

    workspace = tmp_path / "repo"
    workspace.mkdir()
    manager = DurableResourceLeaseManager(tmp_path / "state", workspace=workspace, logical_run_id="run-a")
    other = DurableResourceLeaseManager(tmp_path / "state", workspace=workspace, logical_run_id="run-b")
    try:
        blocked = manager.admit_after_incident(
            task, {"file:shared.py"}, incident="crash", operation_state="UNCERTAIN")
        assert blocked["may_acquire"] is False
        assert blocked["acquired"] is False
        assert blocked["may_release"] is False
        held = other.acquire(Task(id="B", run_id="run-b", objective="edit",
            target_files=["shared.py"]), {"file:shared.py"})
        assert held
        other.release(held)
        eligible = manager.admit_after_incident(
            clean, {"file:other.py"}, incident="canvas_closed", operation_state="NOT_STARTED")
        assert eligible["may_acquire"] is True
        assert eligible["acquired"] is False
        still_free = other.acquire(Task(id="C", run_id="run-b", objective="edit",
            target_files=["other.py"]), {"file:other.py"})
        assert still_free
        other.release(still_free)
    finally:
        manager.close()
        other.close()


def test_classify_seat_does_not_rewrite_conversations(tmp_path):
    run_dir = tmp_path / "R1"
    run_dir.mkdir()
    payload = {"schema_version": 2, "run_id": "R1", "last_dispatch_at": 0.0,
        "seats": {
            "R1:executor": {"state": "CONFIRMED", "provider": "extension", "role": "executor",
                "task_id": "T-1", "url": "https://chatgpt.com/c/aaaa-1",
                "conversation_id": "aaaa-1", "updated": 100.0},
            "R1:validator.logic": {"state": "IN_FLIGHT", "provider": "extension",
                "role": "validator.logic", "task_id": "T-1", "request_sha256": "ab" * 32,
                "updated": 200.0},
        }}
    path = run_dir / "conversations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    stuck = classify_seat(run_dir, "R1:validator.logic")
    healthy = classify_seat(run_dir, "R1:executor")
    assert stuck["decision"] == "observe_no_relay_job"
    assert stuck["automatic_replay"] is False
    assert stuck["effects_executed"] == 0
    assert healthy["decision"] == "preserve"
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        classify_seat(run_dir, "R1:nobody")

    from native_bridge.job_store import JobStore
    from native_bridge.protocol import ChatJob
    db = tmp_path / "relay.sqlite3"
    store = JobStore(str(db))
    store.submit(ChatJob(task_id="T-1", prompt="hi", timeout_s=60))
    store.close()
    queued = classify_seat(run_dir, "R1:validator.logic", db)
    assert queued["decision"] == "observe_blocked"
    assert queued["may_resend"] is False
    assert path.read_bytes() == before
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET state='COMPLETED'")
    reviewed = classify_seat(run_dir, "R1:validator.logic", db)
    assert reviewed["decision"] == "review_existing_answer"
    assert reviewed["automatic_replay"] is False
    assert path.read_bytes() == before
