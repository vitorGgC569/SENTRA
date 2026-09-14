import asyncio
import json
from pathlib import Path

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.models import Task, TaskStatus
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.runtime import IntegratedRun, RunLock, promote_candidate
from workspace.sandbox import fingerprint, source_files


def router():
    provider = MockProvider()
    return ModelRouter({"primary": provider, "master": provider}, fallback_provider_name=None), provider


async def test_isolated_run_handoff_and_explicit_promotion(tmp_path):
    (tmp_path / "math_utils.py").write_text("# baseline\n")
    original = fingerprint(source_files(tmp_path))
    routing, provider = router()
    run = IntegratedRun(tmp_path, "operational", "implement factorial", routing)
    result = await run.run()
    assert result["status"] == "CANDIDATE_READY"
    assert result["completed_tasks"] == 2
    assert result["integration_tests"]["all_passed"]
    assert result["source_unchanged"]
    assert fingerprint(source_files(tmp_path)) == original
    assert any(req.role == "executor" and "UNTRUSTED_REPOSITORY_RESULTS" in req.user_prompt
               for req in provider.history)
    assert all("UNTRUSTED_REPOSITORY_RESULTS" not in req.user_prompt for req in provider.history if req.role == "master")
    assert (Path(result["candidate_workspace"]) / "tests" / "test_factorial_edges.py").is_file()
    assert Path(result["patch_path"]).is_file()
    assert Path(result["handoff_path"]).with_suffix(".md").is_file()
    calls = len(provider.history)
    # Finished resume reuses the persisted handoff, without another model call.
    resumed = await IntegratedRun(tmp_path, "operational", "implement factorial", routing, resume=True).run()
    assert resumed["status"] == "CANDIDATE_READY" and len(provider.history) == calls
    promoted = await promote_candidate(tmp_path, "operational")
    assert promoted["status"] == "APPLIED"
    assert "def factorial" in (tmp_path / "math_utils.py").read_text()
    assert fingerprint(source_files(tmp_path)) == result["candidate_hash"]


async def test_promotion_rejects_stale_workspace_and_tampered_patch(tmp_path):
    (tmp_path / "math_utils.py").write_text("# baseline\n")
    routing, _ = router()
    result = await IntegratedRun(tmp_path, "guard", "factorial", routing).run()
    (tmp_path / "user.txt").write_text("user work")
    with pytest.raises(ValueError, match="STALE_BASE"):
        await promote_candidate(tmp_path, "guard")
    (tmp_path / "user.txt").unlink()
    Path(result["patch_path"]).write_text("tampered")
    with pytest.raises(ValueError, match="changed after verification"):
        await promote_candidate(tmp_path, "guard")
    assert (tmp_path / "math_utils.py").read_text() == "# baseline\n"


async def test_resume_reconstructs_checkpoint_and_skips_committed_task(tmp_path):
    (tmp_path / "math_utils.py").write_text("# baseline\n")
    routing, provider = router()
    run = IntegratedRun(tmp_path, "restart", "factorial", routing)
    original_checkpoint = run._checkpoint
    def crash_after_commit(packages):
        original_checkpoint(packages)
        if len(packages) == 1:
            run.engine.request_cancel("simulate process interrupted after durable commit")
    run._checkpoint = crash_after_commit
    interrupted = await run.run()
    assert interrupted["status"] == "CANCELLED"
    prior_executions = sum(req.role == "executor" and req.metadata["task_id"] == "T-01" for req in provider.history)
    # Simulate a torn/uncommitted staging edit; recovery must ignore it.
    (Path(interrupted["candidate_workspace"]) / "math_utils.py").write_text("partial broken edit")
    usage_before = run.engine.budget.used.copy()
    resumed = await IntegratedRun(tmp_path, "restart", "factorial", routing, resume=True).run()
    assert resumed["status"] == "CANDIDATE_READY"
    assert sum(req.role == "executor" and req.metadata["task_id"] == "T-01" for req in provider.history) == prior_executions
    assert resumed["metrics"]["budget_accounting"]["used"]["secondary"] >= usage_before["secondary"]
    assert (tmp_path / "math_utils.py").read_text() == "# baseline\n"


def test_run_lock_and_identifier_boundary(tmp_path):
    with RunLock(tmp_path / "lock"):
        with pytest.raises(RuntimeError, match="holds"):
            with RunLock(tmp_path / "lock"):
                pass
    routing, _ = router()
    with pytest.raises(ValueError, match="run_id"):
        IntegratedRun(tmp_path, "../escape", "unsafe", routing)


async def test_real_engine_dispatch_overlaps_independent_tasks_but_respects_dag(tmp_path):
    from orchestrator.engine import OMAEngine
    routing, _ = router()
    engine = OMAEngine("concurrent", "test scheduler", tmp_path, routing, max_parallel_workers=2)
    active, peak, completed = set(), [], set()
    async def plan():
        for t in [Task("A",engine.run_id,"alpha"), Task("B",engine.run_id,"beta"),
                  Task("C",engine.run_id,"gamma",dependencies=["A","B"])]:
            await engine.task_queue.add_task(t)
        engine.metrics.tasks_total = 3
    async def process(task):
        assert set(task.dependencies) <= completed
        active.add(task.id)
        peak.append(len(active))
        await asyncio.sleep(.03)
        # Isolate scheduler testing from provider/filesystem validation, which has its own E2Es.
        task.status = TaskStatus.MASTER_REVIEW
        await engine.task_queue.mark_completed(task.id)
        completed.add(task.id)
        active.remove(task.id)
        return True
    engine.plan_initial_tasks, engine.process_task = plan, process
    result = await engine.run()
    assert result["status"] == "COMPLETED"
    assert max(peak) == 2 and completed == {"A","B","C"}
