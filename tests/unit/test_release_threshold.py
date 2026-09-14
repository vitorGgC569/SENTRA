"""Release bar: critics release exec only at/above min score (default 9.5)."""
import itertools
import json

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.agents.validators import SpecializedValidator
from orchestrator.models import (
    Candidate, Task, TokenUsage, ValidationReport, ValidatorRole)
from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.quality_gate import QualityGate, QuorumPolicy


def _ok_reports(scores):
    return [ValidationReport(validator_role=f"v{i}", status="APPROVED",
                             confidence=0.95, score=s) for i, s in enumerate(scores)]


def _base_gate(**kw):
    args = dict(validators_required=2, minimum_approvals=2,
                objective_test_required=False, minimum_confidence_threshold=0.0)
    args.update(kw)
    return QualityGate(QuorumPolicy(**args))


def _task_cand():
    return (Task(id="T-1", run_id="r", objective="x"),
            Candidate(candidate_id="C-1", task_id="T-1", summary="s"))


def test_gate_blocks_below_bar_despite_approvals():
    gate = _base_gate()
    task, cand = _task_cand()
    passed, reason, pkg = gate.evaluate(task, cand, _ok_reports([9.6, 9.4]),
                                        test_results={"all_passed": True, "results": []})
    assert passed is False and pkg is None
    assert reason.startswith("Below release threshold")
    assert "9.40" in reason and "9.50" in reason


def test_gate_passes_at_bar_and_records_scores():
    gate = _base_gate()
    task, cand = _task_cand()
    passed, reason, pkg = gate.evaluate(task, cand, _ok_reports([9.5, 10.0]),
                                        test_results={"all_passed": True, "results": []})
    assert passed is True, reason
    assert pkg.min_validator_score == 9.5
    assert pkg.mean_validator_score == 9.75


def test_gate_legacy_reports_use_confidence_fallback():
    gate = _base_gate()
    task, cand = _task_cand()
    reps = [ValidationReport(validator_role="v1", status="APPROVED", confidence=0.96),
            ValidationReport(validator_role="v2", status="APPROVED", confidence=0.96)]
    assert all(r.score is None for r in reps)
    passed, _, _ = gate.evaluate(task, cand, reps,
                                 test_results={"all_passed": True, "results": []})
    assert passed is True  # 0.96*10 = 9.6 >= 9.5


def test_gate_custom_bar_from_policy():
    gate = _base_gate(min_release_score=8.0)
    task, cand = _task_cand()
    passed, _, _ = gate.evaluate(task, cand, _ok_reports([8.0, 9.0]),
                                 test_results={"all_passed": True, "results": []})
    assert passed is True


def _validator_with_content(content):
    def handler(request: AgentRequest) -> AgentResponse:
        try:
            structured = json.loads(content)
        except Exception:
            structured = None
        return AgentResponse(content=content, structured_data=structured,
                             token_usage=TokenUsage(model="m"), success=True, model="m")
    mock = MockProvider(custom_handler=handler, model_name="m")
    router = ModelRouter(providers={"primary": mock}, primary_provider_name="primary",
                         fallback_provider_name=None)
    return SpecializedValidator(ValidatorRole.LOGIC, router)


@pytest.mark.asyncio
async def test_explicit_score_kept_and_capped_by_severity():
    v = _validator_with_content(json.dumps({
        "status": "APPROVED", "confidence": 0.99, "score": 9.9, "summary": "fine",
        "findings": [{"severity": "MAJOR", "category": "X", "description": "big but"}],
        "requirements_checked": []}))
    rep = await v.validate(Task(id="T-1", run_id="r", objective="x"),
                           Candidate(candidate_id="C-1", task_id="T-1", patch="d"),
                           test_results={"all_passed": True, "results": [{"passed": True}]})
    assert rep.score == 7.0  # MAJOR caps at 7 despite claimed 9.9


@pytest.mark.asyncio
async def test_missing_score_falls_back_to_confidence():
    v = _validator_with_content(json.dumps({
        "status": "APPROVED", "confidence": 0.93, "summary": "ok",
        "findings": [], "requirements_checked": []}))
    rep = await v.validate(Task(id="T-1", run_id="r", objective="x"),
                           Candidate(candidate_id="C-1", task_id="T-1", patch="d"),
                           test_results={"all_passed": True, "results": [{"passed": True}]})
    assert rep.score == 9.3


@pytest.mark.asyncio
async def test_out_of_range_score_falls_back():
    v = _validator_with_content(json.dumps({
        "status": "APPROVED", "confidence": 0.9, "score": 15, "summary": "ok",
        "findings": [], "requirements_checked": []}))
    rep = await v.validate(Task(id="T-1", run_id="r", objective="x"),
                           Candidate(candidate_id="C-1", task_id="T-1", patch="d"),
                           test_results={"all_passed": True, "results": [{"passed": True}]})
    assert rep.score == 9.0


@pytest.mark.asyncio
async def test_repair_prompt_shows_scores_and_bar():
    from orchestrator.agents.repair import RepairAgent
    seen = {}

    def handler(request: AgentRequest) -> AgentResponse:
        seen["prompt"] = request.user_prompt
        content = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: fixed\nPATCH:\n```diff\n"
                   "--- a/f.txt\n+++ b/f.txt\n@@ -0,0 +1 @@\n+x\n```\n"
                   "VALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT")
        return AgentResponse(content=content, structured_data=None,
                             token_usage=TokenUsage(model="m"), success=True, model="m")

    mock = MockProvider(custom_handler=handler, model_name="m")
    router = ModelRouter(providers={"primary": mock}, primary_provider_name="primary",
                         fallback_provider_name=None)
    agent = RepairAgent(router)
    task = Task(id="T-1", run_id="r", objective="x")
    cand = Candidate(candidate_id="C-1", task_id="T-1", patch="d", version=1)
    reports = [ValidationReport(validator_role="validator.logic", status="REJECTED",
                                confidence=0.8, score=8.0),
               ValidationReport(validator_role="validator.requirements", status="APPROVED",
                                confidence=0.9, score=9.0)]
    await agent.repair_candidate(task, cand, reports, {}, release_bar=9.5)
    prompt = seen["prompt"]
    assert "validator.logic: 8.00/10 (REJECTED)" in prompt
    assert "validator.requirements: 9.00/10 (APPROVED)" in prompt
    assert "9.50" in prompt


@pytest.mark.asyncio
async def test_engine_loop_refines_until_bar_then_releases(tmp_path, monkeypatch):
    """8.0 -> repair -> 9.0 -> repair -> 9.6 -> RELEASED. repair_rounds == 2."""
    import git
    from orchestrator.anti_explosion import AntiExplosionConfig
    from orchestrator.engine import OMAEngine
    monkeypatch.chdir(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    git.Repo.init(ws)
    (ws / "f.txt").write_text("base\n", encoding="utf-8")
    (ws / "tests").mkdir(exist_ok=True)
    (ws / "tests" / "test_f.py").write_text("def test_ok():\n    assert True\n",
                                            encoding="utf-8")
    calls = itertools.count(1)
    tok = TokenUsage(input_tokens=5, output_tokens=5, model="m")
    plan = json.dumps({"tasks": [{
        "id": "T-01", "objective": "do thing", "description": "d", "dependencies": [],
        "priority": "HIGH", "risk": "LOW", "required_capabilities": [],
        "validation_strategy": "standard"}]})
    patch = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: built\nPATCH:\n```diff\n"
             "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-base\n+built\n```\n"
             "VALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT")
    master_ok = json.dumps({"decision": "APPROVED", "confidence": 0.97,
                            "critical_issues": [], "remaining_risks": [],
                            "needs_more_work": False, "final_response": "ship it",
                            "reasoning": "all bars cleared"})

    def handler(request: AgentRequest) -> AgentResponse:
        role = request.role.lower()
        if "planner" in role:
            return AgentResponse(content=plan, structured_data=json.loads(plan),
                                 token_usage=tok, success=True, model="m")
        if "master" in role:
            return AgentResponse(content=master_ok, structured_data=json.loads(master_ok),
                                 token_usage=tok, success=True, model="m")
        if "validator" in role:
            n = next(calls)
            score = 8.0 if n <= 4 else (9.0 if n <= 8 else 9.6)
            content = json.dumps({"status": "APPROVED", "confidence": 0.95,
                                  "score": score, "summary": f"round score {score}",
                                  "findings": [],
                                  "requirements_checked": request.metadata.get(
                                      "acceptance_criteria", [])})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        return AgentResponse(content=patch, structured_data=None,
                             token_usage=tok, success=True, model="m")

    mock = MockProvider(custom_handler=handler, model_name="m")
    router = ModelRouter(providers={"primary": mock, "master": mock},
                         primary_provider_name="primary", fallback_provider_name="master")
    engine = OMAEngine(run_id="release-run", objective="do thing", workspace_path=ws,
                       router=router,
                       anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    result = await engine.run()
    assert result["status"] == "COMPLETED"
    assert result["completed_tasks"] == 1
    assert engine.metrics.repair_rounds == 2
    assert engine.completed_packages[0].min_validator_score == 9.6
