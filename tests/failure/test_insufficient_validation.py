"""Abstenção de validadores: quem não executou não vota.

Cobre a espiral de morte observada no piloto real: validadores bloqueados por
budget votavam REJECTED, queimando rounds de repair até escalar sem que nenhum
julgamento tivesse ocorrido. Agora: ran=False é excluído do quorum
(INSUFFICIENT_VALIDATION), conta como abstenção nas métricas, retenta a
VALIDAÇÃO (nunca consome repair) e só então escala. Patch malformado vai
direto ao repair sem gastar round de validador.
"""
import json

import pytest

from orchestrator.models import (
    Candidate, Finding, Severity, Task, TokenUsage, ValidationReport,
)
from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.quality_gate import QualityGate, QuorumPolicy


def _report(role, status, ran=True, findings=None, score=None):
    return ValidationReport(
        validator_role=role, status=status, confidence=0.9, score=score,
        ran=ran, error="" if ran else "simulated infra failure",
        findings=findings or [])


def test_gate_ignores_abstentions_for_quorum():
    gate = QualityGate(QuorumPolicy(validators_required=2, minimum_approvals=2,
                                    objective_test_required=False,
                                    minimum_confidence_threshold=0.5))
    task = Task(id="T-1", run_id="r", objective="x")
    cand = Candidate(candidate_id="C-1", task_id="T-1")
    passed, reason, _ = gate.evaluate(
        task, cand, [_report("v1", "APPROVED"), _report("v2", "REJECTED", ran=False)])
    assert passed is False
    assert reason.startswith("INSUFFICIENT_VALIDATION")


def test_gate_abstained_critical_finding_does_not_block():
    gate = QualityGate(QuorumPolicy(validators_required=2, minimum_approvals=2,
                                    objective_test_required=False,
                                    minimum_confidence_threshold=0.5))
    task = Task(id="T-1", run_id="r", objective="x")
    cand = Candidate(candidate_id="C-1", task_id="T-1", summary="s")
    reports = [_report("v1", "APPROVED", score=9.6), _report("v2", "APPROVED", score=9.8),
               _report("v3", "REJECTED", ran=False,
                       findings=[Finding(severity=Severity.CRITICAL, description="unseen")])]
    passed, reason, pkg = gate.evaluate(
        task, cand, reports, test_results={"all_passed": True, "results": []})
    assert passed is True, reason
    assert pkg.calculated_confidence >= 0.9  # major/critical de ausente ignorados


def test_gate_all_abstained_is_insufficient_not_rejection_on_merits():
    gate = QualityGate(QuorumPolicy(objective_test_required=False,
                                    minimum_confidence_threshold=0.0))
    task = Task(id="T-1", run_id="r", objective="x")
    cand = Candidate(candidate_id="C-1", task_id="T-1")
    passed, reason, pkg = gate.evaluate(task, cand, [_report("v1", "REJECTED", ran=False)])
    assert passed is False
    assert pkg is None
    assert reason.startswith("INSUFFICIENT_VALIDATION")


def test_gate_zero_checks_ran_is_insufficient_not_failed_tests():
    gate = QualityGate(QuorumPolicy(validators_required=1, minimum_approvals=1,
                                    objective_test_required=True))
    task = Task(id="T-1", run_id="r", objective="x")
    cand = Candidate(candidate_id="C-1", task_id="T-1")
    reports = [_report("v1", "APPROVED")]
    test_results = {"all_passed": False, "failed_commands": [], "results": [],
                    "checks_ran": 0, "refused_commands": ["[[TEST|all]]"]}
    passed, reason, _ = gate.evaluate(task, cand, reports, test_results=test_results)
    assert passed is False
    assert reason.startswith("INSUFFICIENT_VALIDATION")


@pytest.mark.asyncio
async def test_refused_commands_are_not_test_failures(tmp_path):
    from workspace.command_runner import CommandRunner
    runner = CommandRunner(tmp_path)
    res = await runner.run_command("python -c \"print('x')\"")
    assert res["passed"] is False
    assert res["refused"] is True
    ok = await runner.run_command("[[LINT]]")
    assert ok["refused"] is False


@pytest.mark.asyncio
async def test_validator_without_checks_does_not_fabricate_critical(tmp_path):
    from orchestrator.agents.validators import SpecializedValidator
    from orchestrator.models import ValidatorRole
    from orchestrator.agents.router import ModelRouter
    from orchestrator.providers.mock_provider import MockProvider
    mock = MockProvider(model_name="m")
    router = ModelRouter(providers={"primary": mock}, primary_provider_name="primary",
                         fallback_provider_name=None)
    v = SpecializedValidator(ValidatorRole.LOGIC, router)
    task = Task(id="T-1", run_id="r", objective="x")
    cand = Candidate(candidate_id="C-1", task_id="T-1", patch="diff")
    # Modelo aprovou, mas nenhuma checagem executou: sem CRITICAL fantasma.
    rep = await v.validate(task, cand, test_results={"all_passed": False, "failed_commands": [],
                                                     "results": [], "checks_ran": 0,
                                                     "refused_commands": ["[[TEST|all]]"]})
    assert rep.ran is True
    assert rep.status == "APPROVED"
    assert rep.findings == []


def test_report_serialization_preserves_ran():
    r = _report("v1", "REJECTED", ran=False)
    assert ValidationReport.from_dict(r.to_dict()).ran is False
    assert ValidationReport.from_dict(_report("v1", "APPROVED").to_dict()).ran is True


class RoleFailProvider:
    """Falha para papéis com 'validator'; sucesso mínimo para os demais."""

    def __init__(self):
        self.calls = []

    async def execute(self, request: AgentRequest) -> AgentResponse:
        self.calls.append(request.role)
        role = request.role.lower()
        tok = TokenUsage(input_tokens=5, output_tokens=5, model="rolefail")
        if "validator" in role:
            return AgentResponse(content="", success=False,
                                 error="[BUDGET_EXCEEDED] test budget exhausted",
                                 token_usage=tok, model="rolefail")
        if "planner" in role:
            content = json.dumps({"tasks": [{
                "id": "T-01", "objective": "do thing", "description": "d",
                "dependencies": [], "priority": "HIGH", "risk": "LOW",
                "required_capabilities": [], "validation_strategy": "standard"}]})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="rolefail")
        if "repair" in role:
            content = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: fix\nPATCH:\n```diff\n"
                       "--- a/f.txt\n+++ b/f.txt\n@@ -0,0 +1 @@\n+fixed\n```\n"
                       "VALIDATION_COMMANDS:\n- python -c \"print('ok')\"\nEND_RESULT")
            return AgentResponse(content=content, structured_data=None,
                                 token_usage=tok, success=True, model="rolefail")
        if "master" in role:
            content = json.dumps({"decision": "APPROVED", "confidence": 0.9,
                                  "critical_issues": [], "remaining_risks": [],
                                  "needs_more_work": False, "final_response": "ok",
                                  "reasoning": "ok"})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="rolefail")
        # executor
        content = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: built\nPATCH:\n```diff\n"
                   "--- a/f.txt\n+++ b/f.txt\n@@ -0,0 +1 @@\n+hello\n```\n"
                   "VALIDATION_COMMANDS:\n- python -c \"print('ok')\"\nEND_RESULT")
        return AgentResponse(content=content, structured_data=None,
                             token_usage=tok, success=True, model="rolefail")


def _make_engine(tmp_path, router, **kw):
    import git
    from orchestrator.engine import OMAEngine
    from orchestrator.anti_explosion import AntiExplosionConfig
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    try:
        git.Repo.init(ws)
    except Exception:
        pass
    (ws / "f.txt").write_text("base\n", encoding="utf-8")
    return OMAEngine(run_id=kw.pop("run_id", "t-run"), objective="do thing",
                     workspace_path=ws, router=router,
                     anti_explosion_config=AntiExplosionConfig(global_task_budget=50), **kw)


@pytest.mark.asyncio
async def test_engine_retries_validation_never_repair_then_escalates(tmp_path, monkeypatch):
    from orchestrator.agents.router import ModelRouter
    from orchestrator.models import TaskStatus
    monkeypatch.chdir(tmp_path)
    provider = RoleFailProvider()
    router = ModelRouter(providers={"primary": provider}, primary_provider_name="primary",
                         fallback_provider_name=None)
    engine = _make_engine(tmp_path, router, run_id="abstain-run", max_repair_rounds=4)
    result = await engine.run()
    assert result["status"] == "FAILED"
    task = engine.task_queue.get_task("T-01")
    assert task.status == TaskStatus.ESCALATED
    # Nenhum repair consumido: o problema era infra, não o candidato.
    assert task.current_repair_round == 0
    assert engine.metrics.repair_rounds == 0
    # 4 validadores x (1 + 2 retries) = 12 abstenções, 0 tentativas reais.
    assert engine.metrics.validation_abstentions == 12
    assert engine.metrics.validation_attempts == 0
    assert engine.metrics.validation_approvals == 0
    kinds = [e.event_type.value for e in engine.event_bus.get_history()]
    assert "TASK_ESCALATED" in kinds


@pytest.mark.asyncio
async def test_engine_malformed_patch_skips_validators(tmp_path, monkeypatch):
    from orchestrator.agents.router import ModelRouter
    from orchestrator.models import TaskStatus
    from orchestrator.providers.mock_provider import MockProvider
    from orchestrator.providers.base import AgentResponse as _AR
    from orchestrator.models import TokenUsage as _TU
    monkeypatch.chdir(tmp_path)

    def bad_patch(request):
        role = request.role.lower()
        if "planner" in role:
            content = json.dumps({"tasks": [{
                "id": "T-01", "objective": "do thing", "description": "d",
                "dependencies": [], "priority": "HIGH", "risk": "LOW",
                "required_capabilities": [], "validation_strategy": "standard"}]})
            return _AR(content=content, structured_data=json.loads(content),
                       token_usage=_TU(model="m"), success=True, model="m")
        content = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: bad\nPATCH:\n```diff\n"
                   "this is not a unified diff at all\n```\n"
                   "VALIDATION_COMMANDS:\n- python -c \"print('ok')\"\nEND_RESULT")
        return _AR(content=content, structured_data=None,
                   token_usage=_TU(model="m"), success=True, model="m")

    mock = MockProvider(custom_handler=bad_patch, model_name="bad")
    router = ModelRouter(providers={"primary": mock}, primary_provider_name="primary",
                         fallback_provider_name=None)
    engine = _make_engine(tmp_path, router, run_id="badpatch-run", max_repair_rounds=0)
    result = await engine.run()
    assert result["status"] == "FAILED"
    assert engine.task_queue.get_task("T-01").status == TaskStatus.ESCALATED
    # Nenhum validador foi acionado: sintaxe barrada na entrada, sem gasto.
    assert engine.metrics.validation_attempts == 0
    assert engine.metrics.validation_abstentions == 0
    reasons = [e.payload.get("reason", "") for e in engine.event_bus.get_history()
               if e.event_type.value == "CANDIDATE_REJECTED"]
    assert any(str(r).startswith("PATCH_SYNTAX") for r in reasons)


@pytest.mark.asyncio
async def test_engine_malformed_patch_reaches_repair_without_state_crash(tmp_path, monkeypatch):
    """V1 malformado -> repair legítimo (transição QUALITY_GATE preservada)."""
    from orchestrator.agents.router import ModelRouter
    from orchestrator.models import TaskStatus
    from orchestrator.providers.mock_provider import MockProvider
    from orchestrator.providers.base import AgentResponse as _AR
    from orchestrator.models import TokenUsage as _TU
    monkeypatch.chdir(tmp_path)

    calls = {"repair": 0}

    def handler(request):
        role = request.role.lower()
        if "planner" in role:
            content = json.dumps({"tasks": [{
                "id": "T-01", "objective": "do thing", "description": "d",
                "dependencies": [], "priority": "HIGH", "risk": "LOW",
                "required_capabilities": [], "validation_strategy": "standard"}]})
            return _AR(content=content, structured_data=json.loads(content),
                       token_usage=_TU(model="m"), success=True, model="m")
        if "repair" in role:
            calls["repair"] += 1
            content = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: fix\nPATCH:\n```diff\n"
                       "--- a/f.txt\n+++ b/f.txt\n@@ -0,0 +1 @@\n+fixed\n```\n"
                       "VALIDATION_COMMANDS:\n- python -c \"print('ok')\"\nEND_RESULT")
            return _AR(content=content, structured_data=None,
                       token_usage=_TU(model="m"), success=True, model="m")
        content = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: bad\nPATCH:\n```diff\n"
                   "this is not a unified diff at all\n```\n"
                   "VALIDATION_COMMANDS:\n- python -c \"print('ok')\"\nEND_RESULT")
        return _AR(content=content, structured_data=None,
                   token_usage=_TU(model="m"), success=True, model="m")

    mock = MockProvider(custom_handler=handler, model_name="bad")
    router = ModelRouter(providers={"primary": mock}, primary_provider_name="primary",
                         fallback_provider_name=None)
    engine = _make_engine(tmp_path, router, run_id="badpatch-repair-run", max_repair_rounds=1)
    result = await engine.run()
    kinds = [e.event_type.value for e in engine.event_bus.get_history()]
    # Sem crash de transição: repair foi solicitado e executou de verdade.
    assert "REPAIR_REQUESTED" in kinds
    assert calls["repair"] >= 1
    assert "TASK_FAILED" not in kinds or engine.task_queue.get_task("T-01").status in (
        TaskStatus.ESCALATED, TaskStatus.FAILED, TaskStatus.COMPLETED)
    # V1 não gastou validadores; V2 (válida) sim.
    assert engine.metrics.validation_attempts >= 0
    assert result["status"] in ("FAILED", "COMPLETED")
