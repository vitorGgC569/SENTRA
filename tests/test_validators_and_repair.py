import pytest
from orchestrator.models import Task, Candidate, ValidatorRole, ValidationReport, Finding, Severity
from orchestrator.agents.validators import ValidatorPool
from orchestrator.agents.repair import RepairAgent
from orchestrator.agents.router import ModelRouter
from orchestrator.providers.mock_provider import MockProvider


@pytest.mark.asyncio
async def test_validator_pool_evaluation():
    mock_p = MockProvider()
    router = ModelRouter({"primary": mock_p})
    pool = ValidatorPool(router)

    task = Task(id="T-val", run_id="r-val", objective="Build sorting algorithm")
    cand = Candidate(candidate_id="c-val", task_id="T-val", patch="--- a/sort.py\n+++ b/sort.py\n")

    reports = await pool.validate_candidate(
        task=task,
        candidate=cand,
        roles=[ValidatorRole.LOGIC, ValidatorRole.REQUIREMENTS, ValidatorRole.SECURITY],
    )

    assert len(reports) == 3
    roles = [r.validator_role for r in reports]
    assert "validator.logic" in roles
    assert "validator.requirements" in roles
    assert "validator.security" in roles


@pytest.mark.asyncio
async def test_repair_agent_iteration():
    mock_p = MockProvider()
    router = ModelRouter({"primary": mock_p})
    repair_agent = RepairAgent(router)

    task = Task(id="T-rep", run_id="r-rep", objective="Fix off-by-one error")
    c1 = Candidate(candidate_id="c1", task_id="T-rep", version=1, patch="--- a/x\n+++ b/x\n")
    report = ValidationReport(
        validator_role="validator.logic",
        status="REJECTED",
        findings=[Finding(severity=Severity.CRITICAL, description="IndexError when array is empty")],
    )

    c2 = await repair_agent.repair_candidate(task, c1, [report])
    assert c2.version == 2
    assert c2.task_id == "T-rep"
