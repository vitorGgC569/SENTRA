"""RNF-001 load — synthetic benchmarks isolating orchestration overhead (mock).

Records throughput, p50/p95/p99, queue size, failures, completion. The motor
may use mock here: the goal is to measure infrastructure, not model quality.
"""
import time

from orchestrator.anti_explosion import AntiExplosionConfig, AntiExplosionGuard

import pytest

from orchestrator.models import Task, TaskPriority
from orchestrator.queue import PriorityTaskQueue


def _percentiles(samples):
    s = sorted(samples)
    n = len(s)
    if n == 0:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    return {"p50": s[int(n * 0.50)], "p95": s[min(int(n * 0.95), n - 1)],
            "p99": s[min(int(n * 0.99), n - 1)]}


@pytest.mark.asyncio
async def test_load_100_tasks_throughput():
    from orchestrator.anti_explosion import AntiExplosionConfig, AntiExplosionGuard
    q = PriorityTaskQueue(anti_explosion=AntiExplosionGuard(
        AntiExplosionConfig(global_task_budget=100000)), max_queue_size=100000)
    t0 = time.time()
    for i in range(100):
        await q.add_task(Task(id=f"L-{i}", run_id="load", objective=f"synthetic load task {i}",
                              priority=TaskPriority.MEDIUM))
    latencies = []
    completed = 0
    while True:
        t = await q.pop_ready_task()
        if t is None:
            break
        s = time.time()
        await q.mark_completed(t.id)
        latencies.append(time.time() - s)
        completed += 1
    total = time.time() - t0
    pct = _percentiles(latencies)
    print(f"\n[LOAD 100] total={total:.2f}s throughput={completed/total:.1f}/s p50={pct['p50']*1000:.2f}ms p95={pct['p95']*1000:.2f}ms p99={pct['p99']*1000:.2f}ms")
    assert completed == 100
    assert q.completed_count == 100


@pytest.mark.asyncio
async def test_load_1000_tasks_bounded():
    q = PriorityTaskQueue(anti_explosion=AntiExplosionGuard(AntiExplosionConfig(global_task_budget=100000)), max_queue_size=100000)
    t0 = time.time()
    for i in range(1000):
        await q.add_task(Task(id=f"M-{i}", run_id="load", objective=f"bulk synthetic task {i}"))
    completed = 0
    while True:
        t = await q.pop_ready_task()
        if t is None:
            break
        await q.mark_completed(t.id)
        completed += 1
    total = time.time() - t0
    print(f"\n[LOAD 1000] total={total:.2f}s throughput={completed/total:.1f}/s")
    assert completed == 1000


@pytest.mark.asyncio
async def test_load_10000_tasks_queue_only():
    q = PriorityTaskQueue(anti_explosion=AntiExplosionGuard(AntiExplosionConfig(global_task_budget=100000)), max_queue_size=200000)
    t0 = time.time()
    for i in range(10000):
        await q.add_task(Task(id=f"X-{i}", run_id="load", objective=f"mass synthetic task {i} payload"))
    enq_time = time.time() - t0
    completed = 0
    t1 = time.time()
    while True:
        t = await q.pop_ready_task()
        if t is None:
            break
        await q.mark_completed(t.id)
        completed += 1
    drain_time = time.time() - t1
    print(f"\n[LOAD 10000] enqueue={enq_time:.2f}s drain={drain_time:.2f}s total={enq_time+drain_time:.2f}s throughput={completed/(enq_time+drain_time):.1f}/s")
    assert completed == 10000
    assert q.dlq_count == 0
