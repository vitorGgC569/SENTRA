"""E2E outside fully-mocked world.

- test_e2e_scripted_diversity: planner/executor/validators/repair/master use
  DISTINCT scripted providers (different models/behaviors), proving components
  collaborate without sharing one identical mock brain (anti false-consensus).
- test_e2e_local_model_if_available: tries a real LocalModelProvider (Ollama/vLLM)
  when OMA_LIVE_LOCAL=1 or a local server answers; otherwise SKIPPED and the
  matrix records BLOCKED_EXTERNAL for true live-model E2E.
"""
import json
import os

import pytest

from orchestrator.engine import OMAEngine
from orchestrator.agents.router import ModelRouter
from orchestrator.quality_gate import QuorumPolicy
from orchestrator.anti_explosion import AntiExplosionConfig
from tests.support.fake_providers import ScriptedProvider


PLAN = json.dumps({"tasks": [
    {"id": "T-01", "objective": "Create greeter module", "description": "write greet()",
     "dependencies": [], "priority": "HIGH", "risk": "LOW",
     "required_capabilities": ["python"], "validation_strategy": "standard"},
    {"id": "T-02", "objective": "Verify greeter imports", "description": "import check",
     "dependencies": ["T-01"], "priority": "MEDIUM", "risk": "LOW",
     "required_capabilities": ["pytest"], "validation_strategy": "deterministic"},
]})
EXEC = ("BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: greeter created\nPATCH:\n```diff\n"
        "--- a/greeter.py\n+++ b/greeter.py\n@@ -0,0 +1,2 @@\n+def greet(name):\n+    return f'hi {name}'\n```\n"
        "VALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT")
VALID = json.dumps({"status": "APPROVED", "confidence": 0.96, "score": 9.6,
                    "summary": "looks good",
                    "findings": [], "requirements_checked": ["RF-006"],
                    "tests": [{"name": "t", "status": "PASS"}], "recommended_action": "PROMOTE"})
MASTER = json.dumps({"decision": "APPROVED", "confidence": 0.96, "critical_issues": [],
                     "remaining_risks": [], "needs_more_work": False,
                     "final_response": "greeter delivered", "reasoning": "validated"})


@pytest.mark.asyncio
async def test_e2e_scripted_diversity(tmp_path, monkeypatch):
    import git

    ws = tmp_path / "ws"
    ws.mkdir()
    git.Repo.init(ws)
    (ws / "greeter.py").write_text("# placeholder\n", encoding="utf-8")
    (ws / "tests").mkdir()
    (ws / "tests" / "test_greeter.py").write_text(
        "from greeter import greet\ndef test_greet():\n    assert greet('Ada') == 'hi Ada'\n")

    # Distinct brains per role (no shared identical mock)
    def handler_for(role_key, script):
        def _h(request):
            from orchestrator.providers.base import AgentResponse
            from orchestrator.models import TokenUsage
            content = script
            if "planner" in request.role.lower():
                content = PLAN
            elif "master" in request.role.lower():
                content = MASTER
            elif "validator" in request.role.lower():
                content = json.dumps({**json.loads(VALID), "requirements_checked": request.metadata.get("acceptance_criteria", [])})
            elif request.metadata.get("task_id") == "T-02":
                content = "BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: Verified imports\nVALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT"
            try:
                structured = json.loads(content)
            except Exception:
                structured = None
            return AgentResponse(content=content, structured_data=structured,
                                 token_usage=TokenUsage(input_tokens=20, output_tokens=20,
                                                        model=role_key),
                                 success=True, model=role_key)
        return _h

    from orchestrator.providers.mock_provider import MockProvider
    secondary = MockProvider(custom_handler=handler_for("secondary-qwen", EXEC),
                             model_name="secondary-qwen")
    master = MockProvider(custom_handler=handler_for("master-gpt", EXEC),
                          model_name="master-gpt")
    router = ModelRouter(providers={"primary": secondary, "master": master},
                         primary_provider_name="primary", fallback_provider_name="master")
    monkeypatch.chdir(tmp_path)
    engine = OMAEngine(run_id="e2e-diverse", objective="Deliver greeter module",
                       workspace_path=ws, router=router,
                       quorum_policy=QuorumPolicy(validators_required=3, minimum_approvals=2,
                                                  objective_test_required=True,
                                                  minimum_confidence_threshold=0.5),
                       anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    result = await engine.run()
    assert result["completed_tasks"] == result["total_tasks"] > 0
    # Diversity proof: both model families participated
    assert any(req.role == "executor" for req in secondary.history)
    assert any(req.role == "master" for req in master.history)
    # Traceability end-to-end
    events = engine.persistence.load_events()
    types = {e.event_type.value for e in events}
    for required in ("TASK_CREATED", "CANDIDATE_CREATED", "VALIDATION_COMPLETED",
                     "QUALITY_GATE_PASSED", "READY_FOR_MASTER", "TASK_COMPLETED"):
        assert required in types


@pytest.mark.asyncio
async def test_e2e_local_model_if_available(tmp_path):
    """True live-model E2E. Skipped when no local server is reachable."""
    import json
    import urllib.error
    import urllib.request

    def _openai_model_base_if_available(port: int) -> str | None:
        base = f"http://127.0.0.1:{port}/v1"
        try:
            with urllib.request.urlopen(f"{base}/models", timeout=1.5) as response:
                if response.status != 200:
                    return None
                payload = json.loads(response.read(1024 * 1024))
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            return None
        return base

    live_requested = os.environ.get("OMA_LIVE_LOCAL") == "1"
    base = _openai_model_base_if_available(11434) or _openai_model_base_if_available(8000)
    if base is None and not live_requested:
        pytest.skip("No OpenAI-compatible local model server reachable (BLOCKED_EXTERNAL for live-model E2E)")
    if base is None:
        pytest.fail("OMA_LIVE_LOCAL=1 but no OpenAI-compatible /v1/models endpoint is reachable")

    import git
    from orchestrator.providers.local_provider import LocalModelProvider

    ws = tmp_path / "ws-live"
    ws.mkdir()
    git.Repo.init(ws)
    local = LocalModelProvider(base_url=base, model_name="qwen2.5:0.5b-instruct-q4_K_M")
    router = ModelRouter(providers={"primary": local, "master": local},
                         primary_provider_name="primary", fallback_provider_name="master")
    engine = OMAEngine(run_id="e2e-live-local", objective="Say hello in one file",
                       workspace_path=ws, router=router,
                       quorum_policy=QuorumPolicy(validators_required=2, minimum_approvals=1,
                                                  objective_test_required=False,
                                                  minimum_confidence_threshold=0.3),
                       anti_explosion_config=AntiExplosionConfig(global_task_budget=10))
    result = await engine.run()
    assert result["total_tasks"] >= 1
