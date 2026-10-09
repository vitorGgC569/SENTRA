from __future__ import annotations

from pathlib import Path

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.routine_scheduler import RoutineSchedule, RoutineSchedulerService


def _services(tmp_path: Path):
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    return durable, context, control


def test_routine_schedule_supports_interval_and_cron() -> None:
    assert RoutineSchedule.next_due({"every_seconds": 10}, 100.0) == 110.0
    assert RoutineSchedule.next_due(
        {"every_seconds": 10, "anchor_at": 95.0}, 100.0
    ) == 105.0
    # 2026-09-27 12:34 UTC -> next top of hour.
    base = 1790512440.0
    due = RoutineSchedule.next_due({"cron": "0 * * * *"}, base)
    assert due is not None
    assert due > base
    assert int(due) % 3600 == 0


def test_scheduler_catchup_is_bounded_and_idempotent(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        run = durable.create_run(owner, workspace="project")
        routine = control.create_routine(
            owner,
            authority_run_id=run["run_id"],
            name="catch-up",
            trigger_kind="schedule",
            trigger_spec={"every_seconds": 10, "anchor_at": 100.0},
            work_template={"objective": "Scheduled audit"},
            active_policy="always_enqueue",
            missed_policy="enqueue_missed_with_cap",
            missed_cap=3,
            next_due_at=100.0,
        )
        scheduler = RoutineSchedulerService(control, clock=lambda: 135.0)
        result = scheduler.tick(now=135.0)
        item = next(x for x in result["items"] if x["routine_id"] == routine["routine_id"])
        assert [x["scheduled_at"] for x in item["fires"]] == [100.0, 110.0, 120.0]
        assert item["next_due_at"] == 140.0

        work = control.list_work_items(owner, run_id=run["run_id"])["items"]
        assert len(work) == 3
        assert len({x["external_key"] for x in work}) == 3

        # Simulate a scheduler crash before clock advancement. Re-processing the
        # same occurrence keys must return the same WorkItems, never duplicates.
        control.governance.update_routine_clock(
            routine["routine_id"], owner, next_due_at=100.0
        )
        replay = scheduler.tick(now=135.0)
        replay_item = next(
            x for x in replay["items"] if x["routine_id"] == routine["routine_id"]
        )
        assert len(replay_item["fires"]) == 3
        again = control.list_work_items(owner, run_id=run["run_id"])["items"]
        assert len(again) == 3
    finally:
        context.close()
        durable.close()


def test_scheduler_skip_missed_and_unbound_fail_closed(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        run = durable.create_run(owner, workspace="project")
        bound = control.create_routine(
            owner,
            authority_run_id=run["run_id"],
            name="skip-backlog",
            trigger_kind="schedule",
            trigger_spec={"every_seconds": 10, "anchor_at": 100.0},
            work_template={"objective": "One current job"},
            active_policy="always_enqueue",
            missed_policy="skip_missed",
            next_due_at=100.0,
        )
        unbound = control.create_routine(
            owner,
            name="unbound",
            trigger_kind="schedule",
            trigger_spec={"every_seconds": 10, "anchor_at": 100.0},
            work_template={"objective": "Must not run"},
            next_due_at=100.0,
        )
        scheduler = RoutineSchedulerService(control, clock=lambda: 135.0)
        result = scheduler.tick(now=135.0)
        by_id = {x["routine_id"]: x for x in result["items"]}
        assert len(by_id[bound["routine_id"]]["fires"]) == 1
        assert by_id[bound["routine_id"]]["next_due_at"] == 140.0
        assert by_id[unbound["routine_id"]]["status"] == "UNBOUND"

        work = control.list_work_items(owner, run_id=run["run_id"])["items"]
        assert len(work) == 1
    finally:
        context.close()
        durable.close()
