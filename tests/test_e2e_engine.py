import pytest
from pathlib import Path
from orchestrator.engine import OMAEngine
from orchestrator.agents.router import ModelRouter
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.quality_gate import QuorumPolicy
from orchestrator.anti_explosion import AntiExplosionConfig


@pytest.mark.asyncio
async def test_oma_engine_e2e_full_cycle(tmp_path):
    # Setup temporary isolated git repository for the run
    workspace = tmp_path / "target_workspace"
    workspace.mkdir()
    import git
    repo = git.Repo.init(workspace)

    # Initial file
    init_file = workspace / "math_utils.py"
    init_file.write_text("# Initial file\n", encoding="utf-8")
    repo.git.add(A=True)
    repo.index.commit("Initial commit")

    # Set up Mock Provider and ModelRouter
    mock_provider = MockProvider(model_name="mock-e2e")
    router = ModelRouter(
        providers={"primary": mock_provider, "master": mock_provider},
        primary_provider_name="primary",
        fallback_provider_name="master",
    )

    quorum = QuorumPolicy(
        validators_required=3,
        minimum_approvals=2,
        critical_rejection_blocks=True,
        objective_test_required=False,  # mock tests
        minimum_confidence_threshold=0.7,
    )

    engine = OMAEngine(
        run_id="e2e-test-run",
        objective="Implement factorial function in math_utils.py",
        workspace_path=workspace,
        router=router,
        acceptance_criteria=["Factorial function implemented", "Tests pass"],
        quorum_policy=quorum,
        anti_explosion_config=AntiExplosionConfig(global_task_budget=50),
    )

    result = await engine.run()

    assert result["status"] == "COMPLETED"
    assert result["completed_tasks"] > 0
    assert result["total_tasks"] == result["completed_tasks"]
    assert result["final_synthesis"] is not None

    # Check metrics
    metrics = result["metrics"]
    assert metrics["tasks_completed"] > 0
    assert metrics["validation_pass_rate"] > 0.0

    # Verify persistence files were created in runs/e2e-test-run/
    run_dir = Path("runs") / "e2e-test-run"
    assert (run_dir / "tasks.json").exists()
    assert (run_dir / "candidates.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "run.json").exists()
