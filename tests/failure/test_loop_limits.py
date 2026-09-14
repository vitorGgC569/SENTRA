"""Loop limits — no cycle escapes deterministic barriers."""
import json

import pytest

from orchestrator.models import Task, TaskStatus, TokenUsage
from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.queue import PriorityTaskQueue
from orchestrator.anti_explosion import AntiExplosionConfig, AntiExplosionError, AntiExplosionGuard


@pytest.mark.asyncio
async def test_identical_rejections_break_early_as_stagnant(tmp_path, monkeypatch):
    """Lapidação com teto: mesma rejeição 3x seguidas escala por STAGNANT,
    sem queimar o 4º round. Humanos só veem o veredito + trilha completa."""
    import git
    from orchestrator.engine import OMAEngine
    from orchestrator.agents.router import ModelRouter
    from orchestrator.providers.mock_provider import MockProvider
    monkeypatch.chdir(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    git.Repo.init(ws)
    (ws / "f.txt").write_text("base\n", encoding="utf-8")
    (ws / "tests").mkdir(exist_ok=True)
    (ws / "tests" / "test_f.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    SAME_REJECT = json.dumps({"status": "REJECTED", "confidence": 0.9,
                              "summary": "same flaw every round",
                              "findings": [{"severity": "MAJOR", "category": "LOGIC",
                                            "description": "identical flaw"}],
                              "requirements_checked": []})
    VALID_PATCH = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: built\nPATCH:\n```diff\n"
                   "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-base\n+built\n```\n"
                   "VALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT")

    def handler(request: AgentRequest) -> AgentResponse:
        role = request.role.lower()
        tok = TokenUsage(input_tokens=5, output_tokens=5, model="m")
        if "planner" in role:
            content = json.dumps({"tasks": [{
                "id": "T-01", "objective": "do thing", "description": "d",
                "dependencies": [], "priority": "HIGH", "risk": "LOW",
                "required_capabilities": [], "validation_strategy": "standard"}]})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "validator" in role:
            return AgentResponse(content=SAME_REJECT, structured_data=json.loads(SAME_REJECT),
                                 token_usage=tok, success=True, model="m")
        return AgentResponse(content=VALID_PATCH, structured_data=None,
                             token_usage=tok, success=True, model="m")

    mock = MockProvider(custom_handler=handler, model_name="m")
    router = ModelRouter(providers={"primary": mock}, primary_provider_name="primary",
                         fallback_provider_name=None)
    engine = OMAEngine(run_id="stag-run", objective="do thing", workspace_path=ws,
                       router=router, stagnation_limit=3,
                       anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    result = await engine.run()
    assert result["status"] == "FAILED"
    assert engine.task_queue.get_task("T-01").status == TaskStatus.ESCALATED
    # Parou no 3º idêntico (limite 3 explícito), sem gastar rounds em repetição inútil.
    assert engine.task_queue.get_task("T-01").current_repair_round == 3
    reasons = [e.payload.get("reason", "") for e in engine.event_bus.get_history()
               if e.event_type.value == "TASK_ESCALATED"]
    assert any("STAGNANT" in str(r) for r in reasons)


def test_lapidadacao_defaults_repair_15_stagnation_5(tmp_path):
    import git
    from orchestrator.agents.router import ModelRouter
    from orchestrator.engine import OMAEngine
    from orchestrator.providers.mock_provider import MockProvider
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    git.Repo.init(ws)
    router = ModelRouter(providers={"primary": MockProvider(model_name="m")},
                         primary_provider_name="primary", fallback_provider_name=None)
    engine = OMAEngine(run_id="d", objective="o", workspace_path=ws, router=router)
    assert engine.max_repair_rounds == 15
    assert engine.stagnation_limit == 5
    from orchestrator.configuration import engine_options
    opts = engine_options({"oma": {"stagnation_limit": 5}})
    assert opts["stagnation_limit"] == 5
    import pytest as _p
    with _p.raises(ValueError, match="stagnation_limit"):
        engine_options({"oma": {"stagnation_limit": 0}})


@pytest.mark.asyncio
async def test_global_task_budget_enforced():
    guard = AntiExplosionGuard(AntiExplosionConfig(global_task_budget=3))
    q = PriorityTaskQueue(anti_explosion=guard)
    for i in range(3):
        assert await q.add_task(Task(id=f"G-{i}", run_id="r", objective=f"budget task {i}")) is True
    # 4th exceeds budget -> rejected (False), never explodes
    assert await q.add_task(Task(id="G-3", run_id="r", objective="over budget task")) is False


def test_branching_factor_limit():
    guard = AntiExplosionGuard(AntiExplosionConfig(branching_factor_limit=2))
    parent = "P-0"
    guard.register_task(Task(id="C-0", run_id="r", objective="child zero"), parent)
    guard.register_task(Task(id="C-1", run_id="r", objective="child one"), parent)
    with pytest.raises(AntiExplosionError):
        guard.register_task(Task(id="C-2", run_id="r", objective="child two"), parent)


def test_max_depth_enforced():
    guard = AntiExplosionGuard(AntiExplosionConfig(max_depth=2))
    with pytest.raises(AntiExplosionError):
        guard.register_task(Task(id="D-deep", run_id="r", objective="too deep", depth=5))


@pytest.mark.asyncio
async def test_max_repair_rounds_escalates_not_loops(tmp_path):
    """A task that always fails the gate must ESCALATE, not loop forever."""
    import git
    from orchestrator.engine import OMAEngine
    from orchestrator.agents.router import ModelRouter
    from orchestrator.providers.mock_provider import MockProvider
    from orchestrator.quality_gate import QuorumPolicy
    from orchestrator.anti_explosion import AntiExplosionConfig

    ws = tmp_path / "ws"
    ws.mkdir()
    git.Repo.init(ws)

    # Validators always reject with critical findings
    import json
    from orchestrator.providers.base import AgentResponse
    from orchestrator.models import TokenUsage

    def always_reject(request):
        if "master" in request.role.lower():
            content = json.dumps({"decision": "REJECTED", "confidence": 0.2,
                                  "critical_issues": ["bad"], "remaining_risks": [],
                                  "needs_more_work": True, "reasoning": "nope"})
        elif "executor" in request.role.lower() or "repair" in request.role.lower():
            content = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: bad\nPATCH:\n```diff\n"
                       "--- a/f\n+++ b/f\n@@\n+x\n```\nVALIDATION_COMMANDS:\n- python -c \"print('ok')\"\nEND_RESULT")
        else:
            content = json.dumps({"status": "REJECTED", "confidence": 0.2, "summary": "bad",
                                  "findings": [{"severity": "CRITICAL", "category": "LOGIC",
                                                "description": "always broken"}]})
        try:
            structured = json.loads(content)
        except Exception:
            structured = None
        return AgentResponse(content=content, structured_data=structured,
                             token_usage=TokenUsage(input_tokens=5, output_tokens=5),
                             success=True, model="m")

    mock = MockProvider(custom_handler=always_reject, model_name="always-bad")
    router = ModelRouter(providers={"primary": mock, "master": mock},
                         primary_provider_name="primary", fallback_provider_name="master")
    engine = OMAEngine(run_id="limits-run", objective="impossible", workspace_path=ws,
                       router=router,
                       quorum_policy=QuorumPolicy(minimum_confidence_threshold=0.99),
                       anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    task = Task(id="T-lim", run_id="limits-run", objective="never passes",
                max_repair_rounds=2, max_retries=0)
    await engine.task_queue.add_task(task)
    engine.metrics.tasks_total = 1
    popped = await engine.task_queue.pop_ready_task()
    ok = await engine.process_task(popped)
    assert ok is False
    # Bounded: repair rounds never exceeded the configured max + 1
    assert popped.current_repair_round <= popped.max_repair_rounds + 1
    assert popped.status.value in ("ESCALATED", "FAILED")
