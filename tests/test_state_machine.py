import pytest
from orchestrator.models import Task, TaskStatus
from orchestrator.state_machine import (
    Phase,
    JobSpec,
    JobState,
    TaskStateMachine,
    InvalidStateTransitionError,
)


def test_task_state_machine_legal_transitions():
    task = Task(id="T-01", run_id="run-1", objective="Test task")
    assert task.status == TaskStatus.PENDING

    TaskStateMachine.transition(task, TaskStatus.QUEUED)
    assert task.status == TaskStatus.QUEUED

    TaskStateMachine.transition(task, TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING

    TaskStateMachine.transition(task, TaskStatus.VALIDATING)
    assert task.status == TaskStatus.VALIDATING

    TaskStateMachine.transition(task, TaskStatus.READY)
    assert task.status == TaskStatus.READY

    TaskStateMachine.transition(task, TaskStatus.QUALITY_GATE)
    assert task.status == TaskStatus.QUALITY_GATE

    TaskStateMachine.transition(task, TaskStatus.READY_FOR_MASTER)
    assert task.status == TaskStatus.READY_FOR_MASTER

    TaskStateMachine.transition(task, TaskStatus.MASTER_REVIEW)
    assert task.status == TaskStatus.MASTER_REVIEW

    TaskStateMachine.transition(task, TaskStatus.COMPLETED)
    assert task.status == TaskStatus.COMPLETED


def test_task_state_machine_repair_cycle():
    task = Task(id="T-02", run_id="run-1", objective="Test repair")
    TaskStateMachine.transition(task, TaskStatus.RUNNING)
    TaskStateMachine.transition(task, TaskStatus.VALIDATING)
    TaskStateMachine.transition(task, TaskStatus.REJECTED)
    assert task.status == TaskStatus.REJECTED

    TaskStateMachine.transition(task, TaskStatus.REPAIRING)
    assert task.status == TaskStatus.REPAIRING

    TaskStateMachine.transition(task, TaskStatus.VALIDATING)
    assert task.status == TaskStatus.VALIDATING


def test_task_state_machine_illegal_transition():
    task = Task(id="T-03", run_id="run-1", objective="Test illegal")
    assert task.status == TaskStatus.PENDING

    # Jumping directly from PENDING to COMPLETED is forbidden by Section 7
    with pytest.raises(InvalidStateTransitionError):
        TaskStateMachine.transition(task, TaskStatus.COMPLETED)


def test_job_state_backwards_compatibility():
    state = JobState()
    assert state.phase == Phase.ANALYZE
    assert state.round_number == 0

    state.log("Test log entry")
    assert len(state.logs) == 1

    d = state.to_dict()
    restored = JobState.from_dict(d)
    assert restored.phase == Phase.ANALYZE
