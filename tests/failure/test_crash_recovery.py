"""Crash recovery — RUNNING interrupted by process death, then restart.

Verifies: state rebuilt, no tasks lost, no duplicates, idempotency preserved,
incomplete executions recovered or classified.
"""
import pytest

from orchestrator.models import Task, TaskStatus
from orchestrator.queue import PriorityTaskQueue
from orchestrator.persistence import PersistenceStore


@pytest.mark.asyncio
async def test_recover_incomplete_tasks_requeues_without_dup(tmp_path):
    q = PriorityTaskQueue()
    t1 = Task(id="T-1", run_id="r", objective="first")
    t2 = Task(id="T-2", run_id="r", objective="second", dependencies=["T-1"])
    await q.add_task(t1)
    await q.add_task(t2)
    popped = await q.pop_ready_task()  # T-1 RUNNING
    assert popped.id == "T-1"

    # Simulate crash: build a NEW queue object and rehydrate
    q2 = PriorityTaskQueue()
    for tid, task in list(q._all_tasks.items()):
        q2.restore_task(task)
    # Before recovery, T-1 is still RUNNING in the rehydrated queue
    assert q2.get_task("T-1").status == TaskStatus.RUNNING
    recovered = q2.recover_incomplete_tasks()
    assert "T-1" in recovered
    assert q2.get_task("T-1").status == TaskStatus.QUEUED
    assert q2.ready_count == 1
    # Idempotent: second recovery call recovers nothing new
    assert q2.recover_incomplete_tasks() == []


@pytest.mark.asyncio
async def test_persisted_tasks_survive_restart(tmp_path):
    store = PersistenceStore("crash-run", base_dir=tmp_path)
    tasks = [Task(id="T-1", run_id="crash-run", objective="keep me"),
             Task(id="T-2", run_id="crash-run", objective="keep me too")]
    store.save_tasks(tasks)
    # "Restart": new store object, same dir
    store2 = PersistenceStore("crash-run", base_dir=tmp_path)
    loaded = store2.load_tasks()
    assert {t.id for t in loaded} == {"T-1", "T-2"}


@pytest.mark.asyncio
async def test_upsert_is_idempotent_no_duplicates(tmp_path):
    store = PersistenceStore("idem-run", base_dir=tmp_path)
    t = Task(id="T-1", run_id="idem-run", objective="once")
    store.upsert_task(t)
    store.upsert_task(t)
    store.upsert_task(t)
    assert len(store.load_tasks()) == 1
