"""TabPool: 50 tarefas em 3 workers — sem perda, sem duplicação, com 1 falha isolada."""
import asyncio

import pytest

from browser.tab_pool import TabPool


@pytest.mark.asyncio
async def test_50_tasks_over_3_workers_no_loss_no_dup():
    pool = TabPool(min_tabs=1, max_tabs=3)
    seen = []

    async def handler(worker, task_id):
        seen.append((worker.worker_id, task_id))
        await asyncio.sleep(0.001)
        if task_id == "T-013":
            raise RuntimeError("injected tab fault (isolamento de falha por tarefa)")

    tasks = [f"T-{i:03d}" for i in range(50)]
    result = await pool.run_all(tasks, handler, timeout_per_task=10.0)
    assert len(result["completed"]) == 49
    assert list(result["failed"].keys()) == ["T-013"]
    assert len({t for _, t in seen}) == 50  # cada tarefa executada exatamente 1x
    workers_used = {w for w, _ in seen}
    assert len(workers_used) == 3  # pool expandiu até o máximo
    assert all(w["state"] == "IDLE" for w in result["workers"])


def test_pool_invalid_bounds_raise_not_assert():
    import pytest as _p
    with _p.raises(ValueError):
        TabPool(min_tabs=0, max_tabs=4)
    with _p.raises(ValueError):
        TabPool(min_tabs=5, max_tabs=2)


@pytest.mark.asyncio
async def test_pool_timeout_isolated_per_task():
    pool = TabPool(min_tabs=1, max_tabs=2)

    async def handler(worker, task_id):
        if task_id == "T-slow":
            await asyncio.sleep(30)
        await asyncio.sleep(0.001)

    result = await pool.run_all(["T-ok", "T-slow"], handler, timeout_per_task=0.2)
    assert result["completed"] == ["T-ok"]
    assert "T-slow" in result["failed"]
