"""Dependentes de tarefas terminais nunca travam a run (regressão do deadlock).

Cobre: ESCALATED, FAILED-permanente (DLQ) e CANCELLED liberam dependentes como
FAILED com DEPENDENCY_ERROR (cascata), e o run loop termina em vez de girar.
"""
import pytest

from orchestrator.models import Task, TaskStatus
from orchestrator.queue import PriorityTaskQueue


@pytest.mark.asyncio
async def test_dependent_of_escalated_fails_fast():
    q = PriorityTaskQueue()
    await q.add_task(Task(id="T-1", run_id="r", objective="root"))
    await q.add_task(Task(id="T-2", run_id="r", objective="child", dependencies=["T-1"]))
    await q.add_task(Task(id="T-3", run_id="r", objective="grandchild", dependencies=["T-2"]))
    root = await q.pop_ready_task()
    assert root.id == "T-1"
    await q.mark_escalated("T-1", reason="no progress")
    # Cascata: T-2 e T-3 falham com erro de dependência, nada fica bloqueado
    assert q.get_task("T-2").status == TaskStatus.FAILED
    assert q.get_task("T-3").status == TaskStatus.FAILED
    assert q.blocked_count == 0
    assert not q.has_pending_work()
    assert any("DEPENDENCY_ERROR" in e.get("error", "") for e in q.get_dlq())


@pytest.mark.asyncio
async def test_dependent_of_dlq_failed_fails_fast():
    q = PriorityTaskQueue()
    await q.add_task(Task(id="A", run_id="r", objective="a", max_retries=0))
    await q.add_task(Task(id="B", run_id="r", objective="b", dependencies=["A"]))
    a = await q.pop_ready_task()
    assert await q.mark_failed(a.id, "boom", retryable=True) is False  # DLQ direto
    assert q.get_task("B").status == TaskStatus.FAILED
    assert not q.has_pending_work()


@pytest.mark.asyncio
async def test_dependent_of_cancelled_fails_fast():
    q = PriorityTaskQueue()
    await q.add_task(Task(id="X", run_id="r", objective="x"))
    await q.add_task(Task(id="Y", run_id="r", objective="y", dependencies=["X"]))
    x = await q.pop_ready_task()
    assert await q.mark_cancelled(x.id, reason="user abort") is True
    assert q.get_task("Y").status == TaskStatus.FAILED
    assert not q.has_pending_work()


@pytest.mark.asyncio
async def test_run_loop_terminates_with_failed_dependency(tmp_path):
    """O run() termina (FAILED) em vez de girar quando o pai escala."""
    import git
    from orchestrator.engine import OMAEngine
    from orchestrator.agents.router import ModelRouter
    from orchestrator.providers.mock_provider import MockProvider

    ws = tmp_path / "ws"
    ws.mkdir()
    git.Repo.init(ws)
    mock = MockProvider(model_name="mock-dep")
    router = ModelRouter(providers={"primary": mock, "master": mock},
                         primary_provider_name="primary", fallback_provider_name="master")
    engine = OMAEngine(run_id="dep-run", objective="obj", workspace_path=ws, router=router)
    await engine.task_queue.add_task(Task(id="P", run_id="dep-run", objective="parent"))
    await engine.task_queue.add_task(Task(id="C", run_id="dep-run", objective="child",
                                          dependencies=["P"]))
    parent = await engine.task_queue.pop_ready_task()
    await engine.task_queue.mark_escalated(parent.id, reason="stuck")
    # O loop do run() deve sair via guard, sem tarefas pendentes
    doomed = await engine.task_queue.fail_unfulfillable_blocked()
    assert engine.task_queue.get_task("C").status == TaskStatus.FAILED
    assert not engine.task_queue.has_pending_work()
