"""WS1 failure isolation: siblings survive, only unreachable dependents fail.

Covers: one task model/delivery failure, repair exhaustion and CONTEXT_BUDGET
never fail DAG siblings; strictly unreachable dependents fail with
DEPENDENCY_ERROR; partial runs report PARTIAL with per-task errors; transient
delivery failures retry with backoff without consuming repair/quorum; resume
with missing/empty tasks.json replans instead of silent FAILED.
"""
import json

import pytest

from orchestrator.models import TaskStatus, TokenUsage
from orchestrator.providers.base import AgentRequest, AgentResponse


def _ws(tmp_path, name="ws"):
    import git
    ws = tmp_path / name
    ws.mkdir(exist_ok=True)
    try:
        git.Repo.init(ws)
    except Exception:
        pass
    (ws / "f.txt").write_text("base\n", encoding="utf-8")
    (ws / "tests").mkdir(exist_ok=True)
    (ws / "tests" / "test_f.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return ws


def _make_engine(tmp_path, router, run_id="ws1-run", **kw):
    from orchestrator.engine import OMAEngine
    from orchestrator.anti_explosion import AntiExplosionConfig
    ws = _ws(tmp_path, name=f"ws-{run_id}")
    kw.setdefault("anti_explosion_config", AntiExplosionConfig(global_task_budget=50))
    kw.setdefault("transient_backoff_base_s", 0)
    kw.setdefault("transient_max_retries", 3)
    return OMAEngine(run_id=run_id, objective="do thing", workspace_path=ws,
                     router=router, **kw)


def _valid_patch_for(task_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in task_id)
    return ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: built " + task_id + "\nPATCH:\n```diff\n"
            "--- /dev/null\n+++ b/" + safe + ".txt\n@@ -0,0 +1 @@\n+content " + task_id + "\n```\n"
            "VALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT")


def _handler_factory(plan_tasks, fail_executor_for=(), fail_error="[CONTEXT_BUDGET] prompt too large"):
    tok = TokenUsage(input_tokens=5, output_tokens=5, model="m")
    plan = json.dumps({"tasks": plan_tasks})
    master_ok = json.dumps({"decision": "APPROVED", "confidence": 0.97,
                            "critical_issues": [], "remaining_risks": [],
                            "needs_more_work": False, "final_response": "ok",
                            "reasoning": "all bars cleared"})

    def handler(request: AgentRequest) -> AgentResponse:
        role = request.role.lower()
        if "planner" in role:
            return AgentResponse(content=plan, structured_data=json.loads(plan),
                                 token_usage=tok, success=True, model="m")
        if "validator" in role:
            acc = (request.metadata or {}).get("acceptance_criteria", [])
            content = json.dumps({"status": "APPROVED", "confidence": 0.95,
                                  "score": 9.6, "summary": "ok", "findings": [],
                                  "requirements_checked": list(acc)})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "master" in role:
            return AgentResponse(content=master_ok, structured_data=json.loads(master_ok),
                                 token_usage=tok, success=True, model="m")
        # executor / repair: unique new file per task avoids patch overlap and
        # STALE_BASE races in sequential runs.
        task_id = (request.metadata or {}).get("task_id", "")
        if task_id in fail_executor_for:
            return AgentResponse(content="", success=False, error=fail_error,
                                 token_usage=tok, model="m")
        patch = _valid_patch_for(task_id or "T-00")
        return AgentResponse(content=patch, structured_data=None,
                             token_usage=tok, success=True, model="m")
    return handler


def _router(handler):
    from orchestrator.agents.router import ModelRouter
    from orchestrator.providers.mock_provider import MockProvider
    mock = MockProvider(custom_handler=handler, model_name="m")
    return ModelRouter(providers={"primary": mock, "master": mock},
                       primary_provider_name="primary", fallback_provider_name="master")


def _plan_task(tid, deps=()):
    return {"id": tid, "objective": f"objective {tid}", "description": "d",
            "dependencies": list(deps), "priority": "MEDIUM", "risk": "LOW",
            "required_capabilities": [], "validation_strategy": "standard"}


@pytest.mark.asyncio
async def test_sibling_isolation_partial_status(tmp_path, monkeypatch):
    """One CONTEXT_BUDGET failure isolates; siblings complete; PARTIAL reported."""
    monkeypatch.chdir(tmp_path)
    plan = [_plan_task("T-01"), _plan_task("T-02"), _plan_task("T-03")]
    handler = _handler_factory(plan, fail_executor_for=("T-02",),
                               fail_error="[CONTEXT_BUDGET] prompt exceeds 20000 characters; no text was sent")
    engine = _make_engine(tmp_path, _router(handler), run_id="iso-partial",
                          max_parallel_workers=1)
    result = await engine.run()
    assert result["status"] == "PARTIAL"
    assert result["completed_tasks"] == 2
    assert result["total_tasks"] == 3
    assert engine.task_queue.get_task("T-01").status == TaskStatus.COMPLETED
    assert engine.task_queue.get_task("T-03").status == TaskStatus.COMPLETED
    assert engine.task_queue.get_task("T-02").status == TaskStatus.FAILED
    # Per-task errors present, siblings carry no DEPENDENCY_ERROR.
    assert "task_errors" in result and "T-02" in result["task_errors"]
    assert "CONTEXT_BUDGET" in result["task_errors"]["T-02"]
    assert any("T-02" in e for e in result["errors"])
    for tid in ("T-01", "T-03"):
        assert tid not in result.get("task_errors", {})


@pytest.mark.asyncio
async def test_only_strictly_unreachable_dependent_fails(tmp_path, monkeypatch):
    """Chain P->C fails with DEPENDENCY_ERROR; independent sibling succeeds."""
    monkeypatch.chdir(tmp_path)
    plan = [_plan_task("P"), _plan_task("C", deps=("P",)), _plan_task("S")]
    handler = _handler_factory(plan, fail_executor_for=("P",),
                               fail_error="[MODEL_ERROR] boom permanent")
    engine = _make_engine(tmp_path, _router(handler), run_id="iso-chain",
                          max_parallel_workers=1)
    result = await engine.run()
    assert engine.task_queue.get_task("P").status == TaskStatus.FAILED
    assert engine.task_queue.get_task("C").status == TaskStatus.FAILED
    assert engine.task_queue.get_task("S").status == TaskStatus.COMPLETED
    dlq = {e["task_id"]: e["error"] for e in engine.task_queue.get_dlq()}
    assert "DEPENDENCY_ERROR" in dlq.get("C", "")
    assert result["status"] == "PARTIAL"
    assert result["completed_tasks"] == 1


@pytest.mark.asyncio
async def test_transient_retry_succeeds_without_consuming_repair(tmp_path, monkeypatch):
    """STALE_CONVERSATION retries with backoff, then succeeds; repair untouched."""
    monkeypatch.chdir(tmp_path)
    plan = [_plan_task("T-01")]
    tok = TokenUsage(input_tokens=5, output_tokens=5, model="m")
    calls = {"executor": 0}
    master_ok = json.dumps({"decision": "APPROVED", "confidence": 0.97,
                            "critical_issues": [], "remaining_risks": [],
                            "needs_more_work": False, "final_response": "ok",
                            "reasoning": "ok"})

    def handler(request: AgentRequest) -> AgentResponse:
        role = request.role.lower()
        if "planner" in role:
            content = json.dumps({"tasks": plan})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "executor" in role or "repair" in role:
            calls["executor"] += 1
            if calls["executor"] <= 2:
                return AgentResponse(content="", success=False,
                                     error="STALE_CONVERSATION: conversation did not change after new_chat",
                                     token_usage=tok, model="m")
            patch = _valid_patch_for("T-01")
            return AgentResponse(content=patch, structured_data=None,
                                 token_usage=tok, success=True, model="m")
        if "validator" in role:
            acc = (request.metadata or {}).get("acceptance_criteria", [])
            content = json.dumps({"status": "APPROVED", "confidence": 0.95,
                                  "score": 9.6, "summary": "ok", "findings": [],
                                  "requirements_checked": list(acc)})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        content = master_ok
        return AgentResponse(content=content, structured_data=json.loads(content),
                             token_usage=tok, success=True, model="m")

    engine = _make_engine(tmp_path, _router(handler), run_id="transient-ok",
                          transient_max_retries=3, transient_backoff_base_s=0)
    result = await engine.run()
    assert result["status"] == "COMPLETED", result.get("errors")
    assert calls["executor"] == 3
    task = engine.task_queue.get_task("T-01")
    assert task.current_repair_round == 0
    assert engine.metrics.repair_rounds == 0


@pytest.mark.asyncio
async def test_transient_exhausted_fails_isolated(tmp_path, monkeypatch):
    """DELIVERY_EXPIRED exhausts retries then fails isolated without repair burn."""
    monkeypatch.chdir(tmp_path)
    plan = [_plan_task("T-FAIL"), _plan_task("T-OK")]
    from orchestrator.models import TokenUsage as TU
    tok = TU(input_tokens=5, output_tokens=5, model="m")
    calls = {"fail": 0}
    master_ok = json.dumps({"decision": "APPROVED", "confidence": 0.97,
                            "critical_issues": [], "remaining_risks": [],
                            "needs_more_work": False, "final_response": "ok",
                            "reasoning": "ok"})

    def handler(request: AgentRequest) -> AgentResponse:
        role = request.role.lower()
        if "planner" in role:
            content = json.dumps({"tasks": plan})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if ("executor" in role or "repair" in role) and (request.metadata or {}).get("task_id") == "T-FAIL":
            calls["fail"] += 1
            return AgentResponse(content="", success=False,
                                 error="DELIVERY_EXPIRED: execution uncertain; not automatically resent",
                                 token_usage=tok, model="m")
        if "validator" in role:
            acc = (request.metadata or {}).get("acceptance_criteria", [])
            content = json.dumps({"status": "APPROVED", "confidence": 0.95,
                                  "score": 9.6, "summary": "ok", "findings": [],
                                  "requirements_checked": list(acc)})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "master" in role:
            return AgentResponse(content=master_ok, structured_data=json.loads(master_ok),
                                 token_usage=tok, success=True, model="m")
        tid = (request.metadata or {}).get("task_id", "T-OK")
        patch = _valid_patch_for(tid)
        return AgentResponse(content=patch, structured_data=None,
                             token_usage=tok, success=True, model="m")

    engine = _make_engine(tmp_path, _router(handler), run_id="transient-dlq",
                          transient_max_retries=2, transient_backoff_base_s=0,
                          max_parallel_workers=1)
    result = await engine.run()
    # 1 initial + 2 retries for the failing task.
    assert calls["fail"] == 3
    assert engine.task_queue.get_task("T-FAIL").status == TaskStatus.FAILED
    assert engine.task_queue.get_task("T-OK").status == TaskStatus.COMPLETED
    assert engine.task_queue.get_task("T-FAIL").current_repair_round == 0
    assert result["status"] == "PARTIAL"
    assert "DELIVERY_EXPIRED" in result["task_errors"]["T-FAIL"]


@pytest.mark.asyncio
async def test_permanent_error_does_not_retry(tmp_path, monkeypatch):
    """CONTEXT_BUDGET is permanent: single attempt, isolated failure."""
    monkeypatch.chdir(tmp_path)
    plan = [_plan_task("T-01")]
    tok = TokenUsage(input_tokens=5, output_tokens=5, model="m")
    calls = {"n": 0}

    def handler(request: AgentRequest) -> AgentResponse:
        role = request.role.lower()
        if "planner" in role:
            content = json.dumps({"tasks": plan})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "executor" in role:
            calls["n"] += 1
            return AgentResponse(content="", success=False,
                                 error="[CONTEXT_BUDGET] prompt exceeds 20000 characters; no text was sent",
                                 token_usage=tok, model="m")
        raise AssertionError("repair/validators must not run after permanent executor failure")

    engine = _make_engine(tmp_path, _router(handler), run_id="permanent-once",
                          transient_max_retries=3, transient_backoff_base_s=0)
    result = await engine.run()
    assert calls["n"] == 1
    assert result["status"] == "FAILED"
    assert engine.task_queue.get_task("T-01").status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_resume_empty_tasks_replans(tmp_path, monkeypatch):
    """Resume with tasks.json [] replans from objective instead of silent FAILED."""
    monkeypatch.chdir(tmp_path)
    plan = [_plan_task("T-01")]
    from orchestrator.models import TokenUsage as TU
    tok = TU(input_tokens=5, output_tokens=5, model="m")
    master_ok = json.dumps({"decision": "APPROVED", "confidence": 0.97,
                            "critical_issues": [], "remaining_risks": [],
                            "needs_more_work": False, "final_response": "ok",
                            "reasoning": "ok"})

    def handler(request: AgentRequest) -> AgentResponse:
        role = request.role.lower()
        if "planner" in role:
            content = json.dumps({"tasks": plan})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "validator" in role:
            acc = (request.metadata or {}).get("acceptance_criteria", [])
            content = json.dumps({"status": "APPROVED", "confidence": 0.95,
                                  "score": 9.6, "summary": "ok", "findings": [],
                                  "requirements_checked": list(acc)})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "master" in role:
            return AgentResponse(content=master_ok, structured_data=json.loads(master_ok),
                                 token_usage=tok, success=True, model="m")
        patch = _valid_patch_for((request.metadata or {}).get("task_id", "T-01"))
        return AgentResponse(content=patch, structured_data=None,
                             token_usage=tok, success=True, model="m")

    from orchestrator.engine import OMAEngine
    from orchestrator.anti_explosion import AntiExplosionConfig
    ws = _ws(tmp_path, name="ws-resume-empty")
    router = _router(handler)
    engine = OMAEngine(run_id="resume-empty", objective="do thing", workspace_path=ws,
                       router=router, transient_backoff_base_s=0,
                       anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    # Poison the resume state: run metadata exists but no usable task.
    await engine.initialize()
    engine.persistence._atomic_write_json(engine.persistence.tasks_file, [])
    engine2 = OMAEngine(run_id="resume-empty", objective="do thing", workspace_path=ws,
                        router=router, transient_backoff_base_s=0,
                        anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    result = await engine2.run(resume=True)
    assert result["total_tasks"] == 1
    assert result["status"] == "COMPLETED", result.get("errors")
    assert result["completed_tasks"] == 1


@pytest.mark.asyncio
async def test_resume_missing_tasks_replans(tmp_path, monkeypatch):
    """Resume with missing tasks.json replans from objective."""
    monkeypatch.chdir(tmp_path)
    plan = [_plan_task("T-01")]
    from orchestrator.models import TokenUsage as TU
    tok = TU(input_tokens=5, output_tokens=5, model="m")
    master_ok = json.dumps({"decision": "APPROVED", "confidence": 0.97,
                            "critical_issues": [], "remaining_risks": [],
                            "needs_more_work": False, "final_response": "ok",
                            "reasoning": "ok"})

    def handler(request: AgentRequest) -> AgentResponse:
        role = request.role.lower()
        if "planner" in role:
            content = json.dumps({"tasks": plan})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "validator" in role:
            acc = (request.metadata or {}).get("acceptance_criteria", [])
            content = json.dumps({"status": "APPROVED", "confidence": 0.95,
                                  "score": 9.6, "summary": "ok", "findings": [],
                                  "requirements_checked": list(acc)})
            return AgentResponse(content=content, structured_data=json.loads(content),
                                 token_usage=tok, success=True, model="m")
        if "master" in role:
            return AgentResponse(content=master_ok, structured_data=json.loads(master_ok),
                                 token_usage=tok, success=True, model="m")
        patch = _valid_patch_for((request.metadata or {}).get("task_id", "T-01"))
        return AgentResponse(content=patch, structured_data=None,
                             token_usage=tok, success=True, model="m")

    from orchestrator.engine import OMAEngine
    from orchestrator.anti_explosion import AntiExplosionConfig
    ws = _ws(tmp_path, name="ws-resume-missing")
    router = _router(handler)
    engine = OMAEngine(run_id="resume-missing", objective="do thing", workspace_path=ws,
                       router=router, transient_backoff_base_s=0,
                       anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    await engine.initialize()
    assert not engine.persistence.tasks_file.exists()
    engine2 = OMAEngine(run_id="resume-missing", objective="do thing", workspace_path=ws,
                        router=router, transient_backoff_base_s=0,
                        anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    result = await engine2.run(resume=True)
    assert result["total_tasks"] == 1
    assert result["status"] == "COMPLETED", result.get("errors")
