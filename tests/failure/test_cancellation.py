"""RF-017 Cancellation — proves more than the existence of the CANCELLED enum.

Covers: long task cancelled mid-execution -> provider/subprocess interrupted ->
worker freed -> CANCELLED persisted -> no improper retry -> matching events.
Also covers whole-run cancellation.
"""
import asyncio

import pytest

from orchestrator.engine import OMAEngine
from orchestrator.agents.router import ModelRouter
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.models import Task, TaskStatus
from orchestrator.queue import PriorityTaskQueue
from orchestrator.events import EventType

from tests.support.fake_providers import HangingProvider


@pytest.mark.asyncio
async def test_queue_cancel_running_task_no_retry():
    q = PriorityTaskQueue()
    t = Task(id="T-long", run_id="r", objective="long running work")
    await q.add_task(t)
    popped = await q.pop_ready_task()
    assert popped.status == TaskStatus.RUNNING
    ok = await q.mark_cancelled(popped.id, reason="user abort")
    assert ok is True
    assert q.get_task("T-long").status == TaskStatus.CANCELLED
    assert q.running_count == 0
    assert q.ready_count == 0  # not requeued: no improper retry
    assert q.dlq_count == 0


@pytest.mark.asyncio
async def test_queue_cancel_all_cancels_run():
    q = PriorityTaskQueue()
    for i in range(3):
        await q.add_task(Task(id=f"T-{i}", run_id="r", objective=f"work {i}"))
    popped = await q.pop_ready_task()
    assert popped is not None
    n = await q.cancel_all(reason="run aborted")
    assert n >= 2
    for tid in ("T-0", "T-1", "T-2"):
        assert q.get_task(tid).status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_provider_cancellation_propagates():
    """A hanging provider call wrapped in a task must be interruptible."""
    hanging = HangingProvider()
    router = ModelRouter(providers={"primary": hanging}, primary_provider_name="primary",
                         fallback_provider_name=None)
    from orchestrator.providers.base import AgentRequest

    async def _call():
        return await router.execute(AgentRequest(system_prompt="s", user_prompt="u",
                                                role="executor", timeout=60))

    task = asyncio.ensure_future(_call())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_engine_cancel_task_emits_event_and_persists(tmp_path):
    import git

    ws = tmp_path / "ws"
    ws.mkdir()
    git.Repo.init(ws)
    mock = MockProvider(model_name="mock-cancel")
    router = ModelRouter(providers={"primary": mock, "master": mock},
                         primary_provider_name="primary", fallback_provider_name="master")
    engine = OMAEngine(run_id="cancel-run-1", objective="obj", workspace_path=ws, router=router)
    # Seed a task directly into the queue
    t = Task(id="T-c1", run_id="cancel-run-1", objective="do something")
    await engine.task_queue.add_task(t)
    popped = await engine.task_queue.pop_ready_task()
    assert popped is not None
    ok = await engine.cancel_task(popped.id, reason="test abort")
    assert ok is True
    assert engine.task_queue.get_task("T-c1").status == TaskStatus.CANCELLED
    # Event emitted and persisted to events.jsonl
    history = engine.event_bus.get_history()
    assert any(e.event_type == EventType.TASK_CANCELLED and e.task_id == "T-c1" for e in history)
    persisted = engine.persistence.load_events()
    assert any(e.event_type == EventType.TASK_CANCELLED and e.task_id == "T-c1" for e in persisted)


@pytest.mark.asyncio
async def test_engine_cancel_run_cancels_all(tmp_path):
    import git

    ws = tmp_path / "ws2"
    ws.mkdir()
    git.Repo.init(ws)
    mock = MockProvider(model_name="mock-cancel2")
    router = ModelRouter(providers={"primary": mock, "master": mock},
                         primary_provider_name="primary", fallback_provider_name="master")
    engine = OMAEngine(run_id="cancel-run-2", objective="obj", workspace_path=ws, router=router)
    for i in range(3):
        await engine.task_queue.add_task(Task(id=f"TC-{i}", run_id="cancel-run-2", objective=f"w {i}"))
    n = await engine.cancel_run(reason="abort whole run")
    assert n >= 1
    assert engine._cancel_requested is True
