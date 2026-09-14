"""Event-sourcing proof (Section 64): estado inicial + events.jsonl = estado reconstruído.

Runs a small mock engine run, discards materialized state (tasks.json,
candidates.json), replays events.jsonl, and compares the reconstructed state
with the original. If this holds, the log is a true event source; otherwise it
is only an append-only audit log.
"""
import pytest
from pathlib import Path

from orchestrator.engine import OMAEngine
from orchestrator.agents.router import ModelRouter
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.quality_gate import QuorumPolicy
from orchestrator.anti_explosion import AntiExplosionConfig


@pytest.mark.asyncio
async def test_event_replay_reconstructs_state(tmp_path, monkeypatch):
    import git

    ws = tmp_path / "ws"
    ws.mkdir()
    git.Repo.init(ws)
    (ws / "math_utils.py").write_text("# init\n", encoding="utf-8")

    mock = MockProvider(model_name="mock-replay")
    router = ModelRouter(providers={"primary": mock, "master": mock},
                         primary_provider_name="primary", fallback_provider_name="master")
    # Isolate persistence under tmp runs dir by chdir
    monkeypatch.chdir(tmp_path)
    engine = OMAEngine(
        run_id="replay-run",
        objective="Implement factorial function",
        workspace_path=ws,
        router=router,
        acceptance_criteria=["done"],
        quorum_policy=QuorumPolicy(validators_required=3, minimum_approvals=2,
                                   objective_test_required=True,
                                   minimum_confidence_threshold=0.5),
        anti_explosion_config=AntiExplosionConfig(global_task_budget=50),
    )
    result = await engine.run()
    assert result["completed_tasks"] > 0

    run_dir = ws / "runs" / "replay-run"
    assert (run_dir / "events.jsonl").exists()

    # Materialized state before deletion
    tasks_before = engine.persistence.load_tasks()
    completed_before = engine.task_queue.completed_count

    # Discard materialized state (keep only the event log)
    (run_dir / "tasks.json").unlink()
    if (run_dir / "candidates.json").exists():
        (run_dir / "candidates.json").unlink()

    replayed = engine.persistence.replay_events()
    assert replayed["events_replayed"] > 0
    # Every completed task must appear as COMPLETED in the replay
    for t in tasks_before:
        if engine.task_queue.get_task(t.id) and engine.task_queue.get_task(t.id).status.value == "COMPLETED":
            assert replayed["tasks"].get(t.id) == "COMPLETED"
    assert len(replayed["completed"]) == completed_before
    assert replayed["validations"] > 0
    assert len(replayed["candidates"]) > 0
