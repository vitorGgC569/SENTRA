"""Concurrency — multiple executors/validators, concurrent queue, DAG, retries."""
import asyncio

import pytest

from orchestrator.models import Task, TaskPriority
from orchestrator.queue import PriorityTaskQueue
from orchestrator.agents.router import ModelRouter
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.providers.base import AgentRequest


@pytest.mark.asyncio
async def test_concurrent_pop_no_double_execution():
    q = PriorityTaskQueue()
    for i in range(50):
        await q.add_task(Task(id=f"T-{i:03d}", run_id="r", objective=f"concurrent work {i}"))

    popped_ids = []
    lock = asyncio.Lock()

    async def worker():
        while True:
            t = await q.pop_ready_task()
            if t is None:
                return
            async with lock:
                popped_ids.append(t.id)
            await asyncio.sleep(0.001)
            await q.mark_completed(t.id)

    await asyncio.gather(*[worker() for _ in range(8)])
    assert len(popped_ids) == 50
    assert len(set(popped_ids)) == 50  # no double execution
    assert q.completed_count == 50


@pytest.mark.asyncio
async def test_concurrent_validators_no_lost_updates():
    mock = MockProvider(model_name="mock-conc")
    router = ModelRouter(providers={"primary": mock}, primary_provider_name="primary",
                         fallback_provider_name=None)

    async def _call(i: int):
        return await router.execute(AgentRequest(system_prompt="s", user_prompt=f"u{i}",
                                                role="validator.logic", timeout=10))

    results = await asyncio.gather(*[_call(i) for i in range(20)])
    assert all(r.success for r in results)
    assert router.total_counts["primary"] == 20


@pytest.mark.asyncio
async def test_dag_with_concurrent_workers_no_deadlock():
    q = PriorityTaskQueue()
    await q.add_task(Task(id="T-root", run_id="r", objective="root"))
    for i in range(10):
        await q.add_task(Task(id=f"T-leaf-{i}", run_id="r", objective=f"leaf {i}",
                              dependencies=["T-root"]))

    async def worker():
        done = 0
        for _ in range(30):
            t = await q.pop_ready_task()
            if t is None:
                await asyncio.sleep(0.005)
                continue
            await asyncio.sleep(0.001)
            await q.mark_completed(t.id)
            done += 1
        return done

    counts = await asyncio.gather(*[worker() for _ in range(4)])
    assert sum(counts) == 11
    assert q.completed_count == 11


@pytest.mark.asyncio
async def test_concurrent_cancel_and_complete_no_corruption():
    q = PriorityTaskQueue()
    for i in range(10):
        await q.add_task(Task(id=f"C-{i}", run_id="r", objective=f"job {i}"))

    async def canceller():
        await asyncio.sleep(0.005)
        await q.mark_cancelled("C-5", reason="simultaneous cancel")

    async def worker():
        while True:
            t = await q.pop_ready_task()
            if t is None:
                return
            if t.id == "C-5":
                return  # was cancelled concurrently
            await q.mark_completed(t.id)

    await asyncio.gather(worker(), canceller(), worker())
    # C-5 cancelled exactly once; never completed afterwards
    assert q.get_task("C-5").status.value == "CANCELLED"
