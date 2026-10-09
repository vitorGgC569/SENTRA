from __future__ import annotations

import asyncio

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.engine import OMAEngine
from orchestrator.models import Candidate, Task
from orchestrator.providers.mock_provider import MockProvider


def _router():
    provider = MockProvider(model_name="m")
    return ModelRouter(
        {"primary": provider, "master": provider},
        primary_provider_name="primary",
        fallback_provider_name="master",
    )


def _remote(node_id="remote:one", *, capabilities=("python", "gpu"), capacity=2):
    return {
        "node_id": node_id,
        "os": "windows",
        "capabilities": list(capabilities),
        "workspaces": [],
        "cpu_count": 8,
        "max_concurrency": capacity,
        "health": "ONLINE",
        "metadata": {"source": "test"},
    }


def _engine(tmp_path, *, remote=None, producers=None):
    return OMAEngine(
        "multi-node",
        "exercise node scheduler",
        tmp_path,
        _router(),
        resource_manifests=[remote or _remote()],
        candidate_producers=producers or {},
        max_parallel_workers=4,
        fixed_conversations=False,
        enforce_milestone_gate=False,
    )


def test_remote_manifest_without_candidate_producer_is_fail_closed(tmp_path):
    engine = _engine(tmp_path)
    task = Task(
        id="T-remote",
        run_id=engine.run_id,
        objective="needs gpu",
        required_capabilities=["gpu"],
    )

    async def probe():
        assert await engine.task_queue.add_task(task)
        detail = engine._unrunnable_ready_tasks()
        assert detail["T-remote"]["code"] == "REMOTE_EXECUTOR_UNAVAILABLE"
        assert detail["T-remote"]["compatible_nodes"] == ["remote:one"]

    asyncio.run(probe())


def test_remote_candidate_producer_is_used_and_candidate_is_normalized(tmp_path):
    calls = []

    class Producer:
        async def produce_candidate(self, task, *, context_summary, workspace_path):
            calls.append((task.id, context_summary, workspace_path))
            return Candidate(
                candidate_id="cand-remote",
                task_id=task.id,
                run_id="",
                summary="remote proposal",
                patch="",
                created_by="remote.worker",
            )

    engine = _engine(tmp_path, producers={"remote:one": Producer()})
    task = Task(
        id="T-remote",
        run_id=engine.run_id,
        objective="needs gpu",
        required_capabilities=["gpu"],
        metadata={"assigned_node_id": "remote:one"},
    )
    candidate = asyncio.run(
        engine._produce_candidate(task, context_summary="bounded context")
    )
    assert candidate.task_id == task.id
    assert candidate.run_id == engine.run_id
    assert task.metadata["candidate_producer_node"] == "remote:one"
    assert calls and calls[0][0] == task.id


def test_remote_candidate_task_mismatch_is_rejected(tmp_path):
    async def producer(task, **_kwargs):
        return Candidate(candidate_id="bad", task_id="OTHER", run_id=task.run_id)

    engine = _engine(tmp_path, producers={"remote:one": producer})
    task = Task(
        id="T-remote",
        run_id=engine.run_id,
        objective="needs gpu",
        required_capabilities=["gpu"],
        metadata={"assigned_node_id": "remote:one"},
    )
    with pytest.raises(ValueError, match="REMOTE_CANDIDATE_TASK_MISMATCH"):
        asyncio.run(engine._produce_candidate(task, context_summary="ctx"))


def test_executable_nodes_respect_per_node_capacity(tmp_path):
    async def producer(task, **_kwargs):
        return Candidate(candidate_id="c", task_id=task.id, run_id=task.run_id)

    engine = _engine(
        tmp_path,
        remote=_remote(capacity=1),
        producers={"remote:one": producer},
    )
    ids = [node.node_id for node in engine._executable_nodes()]
    assert engine.resource_manifest.node_id in ids
    assert "remote:one" in ids

    engine._node_inflight["remote:one"] = 1
    ids = [node.node_id for node in engine._executable_nodes()]
    assert "remote:one" not in ids


def test_capabilities_are_not_union_across_nodes(tmp_path):
    async def producer(task, **_kwargs):
        return Candidate(candidate_id="c", task_id=task.id, run_id=task.run_id)

    engine = OMAEngine(
        "multi-node-union",
        "do not synthesize capabilities",
        tmp_path,
        _router(),
        resource_manifests=[
            _remote("remote:gpu", capabilities=("gpu",)),
            _remote("remote:browser", capabilities=("browser",)),
        ],
        candidate_producers={
            "remote:gpu": producer,
            "remote:browser": producer,
        },
        max_parallel_workers=4,
        enforce_milestone_gate=False,
    )
    task = Task(
        id="T-both",
        run_id=engine.run_id,
        objective="needs both",
        required_capabilities=["gpu", "browser"],
    )

    async def probe():
        assert await engine.task_queue.add_task(task)
        detail = engine._unrunnable_ready_tasks()
        assert detail["T-both"]["code"] == "CAPABILITY_MISSING"

    asyncio.run(probe())
