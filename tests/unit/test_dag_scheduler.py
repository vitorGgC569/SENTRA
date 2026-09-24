from __future__ import annotations

import asyncio

import pytest

from orchestrator.models import Task, TaskStatus
from orchestrator.queue import PriorityTaskQueue


def test_resource_locks_allow_independent_tasks_and_serialize_conflicts() -> None:
    async def probe() -> None:
        q = PriorityTaskQueue()
        a = Task(
            id="A", run_id="r", objective="edit A",
            side_effect_scope="WORKSPACE_WRITE",
            target_files=["src/shared.py"],
        )
        b = Task(
            id="B", run_id="r", objective="edit B",
            side_effect_scope="WORKSPACE_WRITE",
            target_files=["src/shared.py"],
        )
        c = Task(
            id="C", run_id="r", objective="edit C",
            side_effect_scope="WORKSPACE_WRITE",
            target_files=["src/other.py"],
        )
        for task in (a, b, c):
            assert await q.add_task(task)

        first = await q.pop_ready_task()
        second = await q.pop_ready_task()
        assert first is a
        assert second is c
        assert b.id in q._ready_queue

        await q.mark_completed(a.id)
        third = await q.pop_ready_task()
        assert third is b

    asyncio.run(probe())


def test_workspace_and_exclusive_locks_are_fail_safe() -> None:
    async def probe() -> None:
        q = PriorityTaskQueue()
        broad = Task(
            id="A", run_id="r", objective="unknown write",
            side_effect_scope="WORKSPACE_WRITE",
        )
        file_write = Task(
            id="B", run_id="r", objective="file write",
            side_effect_scope="WORKSPACE_WRITE",
            target_files=["x.py"],
        )
        read_only = Task(
            id="C", run_id="r", objective="read",
            side_effect_scope="READ_ONLY",
        )
        for task in (broad, file_write, read_only):
            assert await q.add_task(task)

        assert await q.pop_ready_task() is broad
        assert await q.pop_ready_task() is read_only
        assert await q.pop_ready_task() is None
        await q.mark_completed(broad.id)
        assert await q.pop_ready_task() is file_write

        q2 = PriorityTaskQueue()
        exclusive = Task(
            id="X", run_id="r", objective="exclusive",
            side_effect_scope="EXCLUSIVE",
        )
        other = Task(id="Y", run_id="r", objective="other")
        assert await q2.add_task(exclusive)
        assert await q2.add_task(other)
        assert await q2.pop_ready_task() is exclusive
        assert await q2.pop_ready_task() is None
        await q2.mark_completed(exclusive.id)
        assert await q2.pop_ready_task() is other

    asyncio.run(probe())


def test_failed_task_releases_resource_lock_before_retry() -> None:
    async def probe() -> None:
        q = PriorityTaskQueue()
        a = Task(
            id="A", run_id="r", objective="write",
            side_effect_scope="WORKSPACE_WRITE",
            target_files=["same.py"],
            max_retries=1,
        )
        b = Task(
            id="B", run_id="r", objective="write sibling",
            side_effect_scope="WORKSPACE_WRITE",
            target_files=["same.py"],
        )
        assert await q.add_task(a)
        assert await q.add_task(b)
        assert await q.pop_ready_task() is a
        assert await q.mark_failed(a.id, "transient", retryable=True) is True
        assert not q._resource_holders
        assert not q._task_locks

    asyncio.run(probe())



def test_task_deadline_escalates_without_retry(tmp_path) -> None:
    from contextlib import contextmanager

    from orchestrator.engine import OMAEngine
    from orchestrator.models import TaskStatus

    class Budget:
        def register_task(self, task_id, limit):
            return None

    class Router:
        @contextmanager
        def repository_scope(self, *args, **kwargs):
            yield

    class Persistence:
        def save_tasks(self, tasks):
            return None

        def save_metrics(self, metrics):
            return None

    class Metrics:
        def __init__(self):
            self.escalated = 0
            self.failed = 0

        def record_task_escalated(self):
            self.escalated += 1

        def record_task_failed(self):
            self.failed += 1

        def to_dict(self):
            return {}

    class Events:
        def __init__(self):
            self.items = []

        async def publish(self, event):
            self.items.append(event)

    async def probe() -> None:
        engine = object.__new__(OMAEngine)
        engine.run_id = "r"
        engine.workspace_path = tmp_path
        engine.budget = Budget()
        engine.router = Router()
        engine.persistence = Persistence()
        engine.metrics = Metrics()
        engine.event_bus = Events()
        engine.task_queue = PriorityTaskQueue()
        engine._timeout_cancellations = set()
        engine._repository_event = lambda entry: None
        engine._reset_provider_breakers = lambda: None

        task = Task(
            id="T", run_id="r", objective="slow",
            side_effect_scope="WORKSPACE_WRITE",
            target_files=["slow.py"],
            timeout_s=0.03,
        )
        assert await engine.task_queue.add_task(task)
        assert await engine.task_queue.pop_ready_task() is task

        async def slow(_task):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                if _task.id not in engine._timeout_cancellations:
                    await engine.cancel_task(_task.id, reason="operator cancel")
                raise

        engine._process_task = slow
        result = await OMAEngine.process_task(engine, task)

        assert result is False
        assert task.status == TaskStatus.ESCALATED
        assert task.retry_count == 0
        assert task.metadata["timeout_uncertain"] is True
        assert task.metadata["scheduler_state"] == "TIMEOUT_UNCERTAIN"
        assert engine.metrics.escalated == 1
        assert engine.metrics.failed == 0
        assert not engine.task_queue._resource_holders
        assert not engine.task_queue._task_locks

    asyncio.run(probe())



def test_stale_progress_heartbeat_is_observe_only(tmp_path) -> None:
    from contextlib import contextmanager

    from orchestrator.engine import OMAEngine
    from orchestrator.events import EventType
    from orchestrator.models import TaskStatus

    class Budget:
        def register_task(self, task_id, limit):
            return None

    class Router:
        @contextmanager
        def repository_scope(self, *args, **kwargs):
            yield

    class Persistence:
        def save_tasks(self, tasks):
            return None

        def save_metrics(self, metrics):
            return None

        def append_event(self, event):
            return None

    class Metrics:
        def record_task_escalated(self):
            raise AssertionError("stall observation must not escalate")

        def record_task_failed(self):
            raise AssertionError("stall observation must not fail")

        def to_dict(self):
            return {}

    async def probe() -> None:
        engine = object.__new__(OMAEngine)
        engine.run_id = "r"
        engine.workspace_path = tmp_path
        engine.budget = Budget()
        engine.router = Router()
        engine.persistence = Persistence()
        engine.metrics = Metrics()
        engine.event_bus = __import__("orchestrator.events", fromlist=["EventBus"]).EventBus()
        engine.event_bus.subscribe_all(engine._on_event)
        engine.task_queue = PriorityTaskQueue()
        engine._timeout_cancellations = set()
        engine._repository_event = lambda entry: None
        engine._reset_provider_breakers = lambda: None

        task = Task(
            id="T-stall",
            run_id="r",
            objective="slow but eventually completes",
            heartbeat_timeout_s=0.02,
            timeout_s=0.2,
        )
        assert await engine.task_queue.add_task(task)
        assert await engine.task_queue.pop_ready_task() is task

        async def slow(_task):
            await asyncio.sleep(0.06)
            return True

        engine._process_task = slow
        result = await OMAEngine.process_task(engine, task)

        assert result is True
        assert task.status == TaskStatus.RUNNING
        assert task.metadata["scheduler_state"] == "FINISHED"
        assert task.metadata.get("stall_recovered_at") is not None
        assert any(
            e.event_type == EventType.TASK_STALLED
            for e in engine.event_bus.get_history("r")
        )
        assert not any(
            e.event_type == EventType.TASK_ESCALATED
            for e in engine.event_bus.get_history("r")
        )

    asyncio.run(probe())



def test_capability_admission_skips_incompatible_high_priority_task() -> None:
    from orchestrator.models import TaskPriority

    async def probe() -> None:
        q = PriorityTaskQueue()
        gpu = Task(
            id="GPU",
            run_id="r",
            objective="gpu work",
            priority=TaskPriority.CRITICAL,
            required_capabilities=["gpu", "python"],
        )
        cpu = Task(
            id="CPU",
            run_id="r",
            objective="cpu work",
            priority=TaskPriority.MEDIUM,
            required_capabilities=["python"],
        )
        assert await q.add_task(gpu)
        assert await q.add_task(cpu)

        selected = await q.pop_ready_task(
            available_capabilities={"python", "filesystem"},
            node_id="local:test",
        )
        assert selected is cpu
        assert selected.metadata["assigned_node_id"] == "local:test"
        assert "python" in selected.metadata["capability_snapshot"]
        assert gpu.id in q._ready_queue
        assert q.unsatisfied_capabilities({"python", "filesystem"}) == {
            "GPU": ["gpu"]
        }

    asyncio.run(probe())


def test_local_capability_manifest_is_deterministic_and_supports_python(tmp_path) -> None:
    from orchestrator.resources import NodeCapabilityManifest, ResourceCapabilityRegistry

    manifest = NodeCapabilityManifest.probe_local(tmp_path, max_concurrency=3)
    assert manifest.health == "ONLINE"
    assert manifest.max_concurrency == 3
    assert manifest.supports(["python", manifest.os])
    assert manifest.missing(["python"]) == []

    registry = ResourceCapabilityRegistry()
    registry.upsert(manifest)
    assert registry.compatible(["python"]) == [manifest]
    assert registry.compatible(["definitely-missing-capability"]) == []



def test_stale_heartbeat_is_observational_and_can_recover(tmp_path) -> None:
    from contextlib import contextmanager

    from orchestrator.engine import OMAEngine
    from orchestrator.events import EventType

    class Budget:
        def register_task(self, task_id, limit):
            return None

    class Router:
        @contextmanager
        def repository_scope(self, *args, **kwargs):
            yield

    class Persistence:
        def save_tasks(self, tasks):
            return None
        def save_metrics(self, metrics):
            return None

    class Metrics:
        def record_task_escalated(self):
            raise AssertionError("stall must not escalate before total timeout")
        def record_task_failed(self):
            raise AssertionError("stall must not fail a recovering task")
        def to_dict(self):
            return {}

    class Events:
        def __init__(self):
            self.items = []
        async def publish(self, event):
            self.items.append(event)

    async def probe() -> None:
        engine = object.__new__(OMAEngine)
        engine.run_id = "r"
        engine.workspace_path = tmp_path
        engine.budget = Budget()
        engine.router = Router()
        engine.persistence = Persistence()
        engine.metrics = Metrics()
        engine.event_bus = Events()
        engine.task_queue = PriorityTaskQueue()
        engine._timeout_cancellations = set()
        engine._repository_event = lambda entry: None
        engine._reset_provider_breakers = lambda: None

        task = Task(
            id="HB", run_id="r", objective="slow but healthy enough",
            timeout_s=0.30,
            heartbeat_timeout_s=0.03,
        )
        assert await engine.task_queue.add_task(task)
        assert await engine.task_queue.pop_ready_task() is task

        async def slow(_task):
            await asyncio.sleep(0.09)
            return True

        engine._process_task = slow
        result = await OMAEngine.process_task(engine, task)

        assert result is True
        assert task.metadata["scheduler_state"] == "FINISHED"
        assert "stall_recovered_at" in task.metadata
        stalled = [
            event for event in engine.event_bus.items
            if event.event_type == EventType.TASK_STALLED
        ]
        assert len(stalled) == 1
        assert stalled[0].payload["action"] == "observe_only"
        assert "no cancellation or retry" in stalled[0].payload["reason"]

    asyncio.run(probe())



def test_task_idempotency_is_stable_and_roundtrips() -> None:
    a = Task(id="T-1", run_id="R", objective="same objective")
    b = Task(id="T-1", run_id="R", objective="same objective")
    c = Task(id="T-1", run_id="R", objective="different objective")

    assert a.idempotency_key.startswith("task-")
    assert a.idempotency_key == b.idempotency_key
    assert a.idempotency_key != c.idempotency_key
    restored = Task.from_dict(a.to_dict())
    assert restored.idempotency_key == a.idempotency_key


def test_crash_recovery_requeues_safe_scope_and_escalates_uncertain_scope() -> None:
    from orchestrator.models import TaskStatus

    async def probe() -> None:
        q = PriorityTaskQueue()
        safe = Task(
            id="SAFE", run_id="r", objective="local",
            status=TaskStatus.RUNNING,
            side_effect_scope="ISOLATED",
        )
        external = Task(
            id="EXT", run_id="r", objective="external",
            status=TaskStatus.RUNNING,
            side_effect_scope="EXTERNAL",
        )
        dependent = Task(
            id="DEP", run_id="r", objective="dependent",
            status=TaskStatus.PENDING,
            dependencies=["EXT"],
        )
        safe_key = safe.idempotency_key
        q.restore_task(safe)
        q.restore_task(external)
        q.restore_task(dependent)

        recovered = q.recover_incomplete_tasks()
        assert recovered == ["SAFE"]
        assert safe.status == TaskStatus.QUEUED
        assert safe.idempotency_key == safe_key
        assert external.status == TaskStatus.ESCALATED
        assert external.metadata["recovery_required"] is True
        assert external.id not in q._ready_queue
        assert dependent.id in q._blocked_tasks

        failed = await q.fail_unfulfillable_blocked()
        assert dependent.id in failed
        assert dependent.status == TaskStatus.FAILED

    asyncio.run(probe())



def test_task_idempotency_replay_and_conflict() -> None:
    async def probe() -> None:
        q = PriorityTaskQueue()
        first = Task(
            id="T-1", run_id="r", objective="compile sources",
            idempotency_key="idem-compile",
        )
        replay = Task(
            id="T-1", run_id="r", objective="compile sources",
            idempotency_key="idem-compile",
        )
        assert await q.add_task(first) is True
        created_before = q.anti_explosion.total_tasks_created
        assert await q.add_task(replay) is True
        assert q.anti_explosion.total_tasks_created == created_before
        assert len(q._all_tasks) == 1
        assert q._ready_queue.count("T-1") == 1

        conflicting_key = Task(
            id="T-2", run_id="r", objective="different work",
            idempotency_key="idem-compile",
        )
        with pytest.raises(ValueError, match="id/idempotency key"):
            await q.add_task(conflicting_key)

        conflicting_id = Task(
            id="T-1", run_id="r", objective="changed objective",
            idempotency_key="idem-changed",
        )
        with pytest.raises(ValueError, match="id/idempotency key"):
            await q.add_task(conflicting_id)

    asyncio.run(probe())


def test_restore_rebuilds_task_idempotency_index() -> None:
    q = PriorityTaskQueue()
    restored = Task(
        id="T-restore", run_id="r", objective="restore me",
        idempotency_key="idem-restore",
        status=TaskStatus.QUEUED,
    )
    q.restore_task(restored)
    assert q._idempotency_index["idem-restore"] == "T-restore"

    same = Task(
        id="T-restore", run_id="r", objective="restore me",
        idempotency_key="idem-restore",
        status=TaskStatus.QUEUED,
    )
    q.restore_task(same)
    assert len(q._all_tasks) == 1

    collision = Task(
        id="T-other", run_id="r", objective="other",
        idempotency_key="idem-restore",
        status=TaskStatus.QUEUED,
    )
    with pytest.raises(ValueError):
        q.restore_task(collision)
