from __future__ import annotations

import asyncio

from orchestrator.durable_resources import DurableResourceLeaseManager
from orchestrator.models import Task
from orchestrator.queue import PriorityTaskQueue


def _task(run_id: str, task_id: str, path: str) -> Task:
    return Task(
        id=task_id,
        run_id=run_id,
        objective="edit file",
        side_effect_scope="WORKSPACE_WRITE",
        target_files=[path],
    )


def test_durable_leases_serialize_same_project_resource_across_runs(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    state = tmp_path / "state"
    a = DurableResourceLeaseManager(
        state, workspace=workspace, logical_run_id="run-a"
    )
    b = DurableResourceLeaseManager(
        state, workspace=workspace, logical_run_id="run-b"
    )
    try:
        first = a.acquire(_task("run-a", "A", "src/shared.py"), {"file:src/shared.py"})
        assert first
        blocked = b.acquire(_task("run-b", "B", "src/shared.py"), {"file:src/shared.py"})
        assert blocked is None
        first_token = int(first[0]["fencing_token"])

        a.release(first)
        second = b.acquire(_task("run-b", "B", "src/shared.py"), {"file:src/shared.py"})
        assert second
        assert int(second[0]["fencing_token"]) > first_token
        b.release(second)
    finally:
        a.close()
        b.close()


def test_durable_leases_allow_independent_files(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    state = tmp_path / "state"
    a = DurableResourceLeaseManager(state, workspace=workspace, logical_run_id="run-a")
    b = DurableResourceLeaseManager(state, workspace=workspace, logical_run_id="run-b")
    try:
        la = a.acquire(_task("run-a", "A", "a.py"), {"file:a.py"})
        lb = b.acquire(_task("run-b", "B", "b.py"), {"file:b.py"})
        assert la and lb
        a.release(la)
        b.release(lb)
    finally:
        a.close()
        b.close()


class _FakeLeaseManager:
    def __init__(self, allow=True):
        self.allow = allow
        self.acquired = []
        self.released = []

    def acquire(self, task, resources):
        self.acquired.append((task.id, set(resources)))
        if not self.allow:
            return None
        return [{
            "logical_resource": next(iter(resources)),
            "resource_key": "lease:key",
            "fencing_token": 7,
            "lease_until": 999.0,
        }]

    def release(self, leases):
        self.released.append(list(leases))


def test_queue_binds_durable_lease_lifecycle_to_task():
    async def probe():
        leases = _FakeLeaseManager()
        queue = PriorityTaskQueue(resource_lease_manager=leases)
        task = _task("r", "A", "x.py")
        assert await queue.add_task(task)
        selected = await queue.pop_ready_task()
        assert selected is task
        assert selected.metadata["durable_resource_leases"][0]["fencing_token"] == 7
        await queue.mark_completed(task.id)
        assert leases.released
        assert "durable_resource_leases" not in task.metadata

    asyncio.run(probe())


def test_queue_keeps_task_ready_when_global_lease_is_busy():
    async def probe():
        leases = _FakeLeaseManager(allow=False)
        queue = PriorityTaskQueue(resource_lease_manager=leases)
        task = _task("r", "A", "x.py")
        assert await queue.add_task(task)
        assert await queue.pop_ready_task() is None
        assert task.id in queue._ready_queue
        assert task.id not in queue._running_tasks

    asyncio.run(probe())
