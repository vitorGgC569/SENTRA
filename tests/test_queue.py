import pytest
from orchestrator.models import Task, TaskPriority, TaskStatus
from orchestrator.queue import PriorityTaskQueue


@pytest.mark.asyncio
async def test_queue_priority_ordering():
    queue = PriorityTaskQueue()

    t_low = Task(id="T-low", run_id="r1", objective="low priority", priority=TaskPriority.LOW)
    t_high = Task(id="T-high", run_id="r1", objective="high priority", priority=TaskPriority.HIGH)
    t_crit = Task(id="T-crit", run_id="r1", objective="critical priority", priority=TaskPriority.CRITICAL)

    await queue.add_task(t_low)
    await queue.add_task(t_high)
    await queue.add_task(t_crit)

    first = await queue.pop_ready_task()
    assert first.id == "T-crit"

    second = await queue.pop_ready_task()
    assert second.id == "T-high"

    third = await queue.pop_ready_task()
    assert third.id == "T-low"


@pytest.mark.asyncio
async def test_queue_dag_dependency_resolution():
    queue = PriorityTaskQueue()

    t1 = Task(id="T-1", run_id="r1", objective="step 1", dependencies=[])
    t2 = Task(id="T-2", run_id="r1", objective="step 2", dependencies=["T-1"])

    await queue.add_task(t1)
    await queue.add_task(t2)

    assert queue.ready_count == 1
    assert queue.blocked_count == 1

    popped1 = await queue.pop_ready_task()
    assert popped1.id == "T-1"

    # Until T-1 is completed, T-2 cannot be popped
    assert await queue.pop_ready_task() is None

    # Mark T-1 completed
    await queue.mark_completed("T-1")

    # Now T-2 is unblocked and ready!
    assert queue.ready_count == 1
    assert queue.blocked_count == 0

    popped2 = await queue.pop_ready_task()
    assert popped2.id == "T-2"


@pytest.mark.asyncio
async def test_queue_retry_and_dlq():
    queue = PriorityTaskQueue()
    t = Task(id="T-flaky", run_id="r1", objective="flaky", max_retries=2)
    await queue.add_task(t)

    # Pop and fail attempt 1
    popped = await queue.pop_ready_task()
    requeued = await queue.mark_failed(popped.id, "Flaky error 1", retryable=True)
    assert requeued is True
    assert queue.ready_count == 1

    # Pop and fail attempt 2
    popped = await queue.pop_ready_task()
    requeued = await queue.mark_failed(popped.id, "Flaky error 2", retryable=True)
    assert requeued is True

    # Pop and fail attempt 3 (exceeds max_retries=2)
    popped = await queue.pop_ready_task()
    requeued = await queue.mark_failed(popped.id, "Flaky error 3", retryable=True)
    assert requeued is False

    # Should now be in Dead Letter Queue (DLQ)
    assert queue.dlq_count == 1
    dlq_entries = queue.get_dlq()
    assert dlq_entries[0]["task_id"] == "T-flaky"
