"""Backpressure (Section 49): produção > capacidade não causa OOM nem perda silenciosa."""
import pytest

from orchestrator.models import Task
from orchestrator.queue import PriorityTaskQueue, QueueFullError


@pytest.mark.asyncio
async def test_bounded_queue_rejects_with_accounting_not_oom():
    q = PriorityTaskQueue(max_queue_size=10)
    for i in range(10):
        await q.add_task(Task(id=f"T-{i}", run_id="r", objective=f"task number {i} unique"))
    with pytest.raises(QueueFullError):
        await q.add_task(Task(id="T-overflow", run_id="r", objective="overflow task unique xyz"))
    assert q.dropped_due_to_backpressure == 1
    assert q.queue_size() == 10  # bounded: no unbounded growth


@pytest.mark.asyncio
async def test_backpressure_recovers_after_drain():
    q = PriorityTaskQueue(max_queue_size=5)
    for i in range(5):
        await q.add_task(Task(id=f"B-{i}", run_id="r", objective=f"bounded {i}"))
    with pytest.raises(QueueFullError):
        await q.add_task(Task(id="B-full", run_id="r", objective="extra bounded task"))
    # Drain two slots
    t = await q.pop_ready_task()
    await q.mark_completed(t.id)
    t2 = await q.pop_ready_task()
    await q.mark_completed(t2.id)
    # Now there is room again
    await q.add_task(Task(id="B-retry", run_id="r", objective="extra bounded task retry ok"))
    assert q.get_task("B-retry") is not None
