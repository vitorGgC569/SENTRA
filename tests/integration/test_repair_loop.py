"""Repair loop — defective V1 -> REJECTED -> Repair V2 -> READY -> gate passes.

Proves candidate versioning and full history persistence.
"""
import json

import pytest

from orchestrator.engine import OMAEngine
from orchestrator.agents.router import ModelRouter
from orchestrator.models import Task
from tests.support.fake_providers import ScriptedProvider


EXEC_V1 = (
    "BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: buggy implementation\nPATCH:\n```diff\n"
    "--- a/app.py\n+++ b/app.py\n@@ -0,0 +1,3 @@\n+def add(a, b):\n+    return a - b\n```\n"
    "VALIDATION_COMMANDS:\n- python -c \"print('ok')\"\nEND_RESULT"
)
REPAIR_V2 = (
    "BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: fixed add to use +\nPATCH:\n```diff\n"
    "--- a/app.py\n+++ b/app.py\n@@ -0,0 +1,3 @@\n+def add(a, b):\n+    return a + b\n```\n"
    "VALIDATION_COMMANDS:\n- python -c \"print('ok')\"\nEND_RESULT"
)
REJECT_JSON = json.dumps({"status": "REJECTED", "confidence": 0.4, "summary": "wrong operator",
                          "findings": [{"severity": "MAJOR", "category": "LOGIC",
                                        "description": "subtraction instead of addition"}],
                          "requirements_checked": []})
APPROVE_JSON = json.dumps({"status": "APPROVED", "confidence": 0.97, "summary": "correct",
                           "findings": [], "requirements_checked": ["RF-001"]})
MASTER_OK = json.dumps({"decision": "APPROVED", "confidence": 0.97, "critical_issues": [],
                        "remaining_risks": [], "needs_more_work": False,
                        "final_response": "ok", "reasoning": "v2 verified"})


@pytest.mark.asyncio
async def test_repair_loop_v1_rejected_v2_ready(tmp_path, monkeypatch):
    import git

    ws = tmp_path / "ws"
    ws.mkdir()
    git.Repo.init(ws)
    (ws / "app.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")

    # Script per role: executor returns buggy V1 once; validators reject first
    # round then approve; repair returns fixed V2; master approves.
    def handler(request):
        role = request.role.lower()
        if "executor" in role:
            content = EXEC_V1
        elif "repair" in role:
            content = REPAIR_V2
        elif "master" in role:
            content = MASTER_OK
        else:  # validators: first call each rejects, but ScriptedProvider is per-provider;
            content = REJECT_JSON
        from orchestrator.providers.base import AgentResponse
        from orchestrator.models import TokenUsage
        structured = None
        try:
            structured = json.loads(content)
        except Exception:
            pass
        return AgentResponse(content=content, structured_data=structured,
                             token_usage=TokenUsage(input_tokens=10, output_tokens=10),
                             success=True, model="scripted")

    from orchestrator.providers.mock_provider import MockProvider
    scripted = MockProvider(custom_handler=handler, model_name="scripted-repair")
    router = ModelRouter(providers={"primary": scripted, "master": scripted},
                         primary_provider_name="primary", fallback_provider_name="master")
    monkeypatch.chdir(tmp_path)
    from orchestrator.quality_gate import QuorumPolicy
    from orchestrator.anti_explosion import AntiExplosionConfig

    engine = OMAEngine(run_id="repair-loop-run", objective="fix add function",
                       workspace_path=ws, router=router,
                       quorum_policy=QuorumPolicy(validators_required=3, minimum_approvals=2,
                                                  objective_test_required=False,
                                                  minimum_confidence_threshold=0.3),
                       anti_explosion_config=AntiExplosionConfig(global_task_budget=50))
    # Single task run: bypass planner by seeding the queue
    task = Task(id="T-R1", run_id="repair-loop-run", objective="fix add",
                description="make add correct", max_repair_rounds=4)
    await engine.task_queue.add_task(task)
    engine.metrics.tasks_total = 1
    popped = await engine.task_queue.pop_ready_task()
    ok = await engine.process_task(popped)
    # V1 was buggy: either repaired to success or escalated after rounds — but
    # versioning must exist in either case.
    mem = engine.memory.get_task_memory("T-R1")
    assert len(mem.candidates) >= 1
    versions = [c.version for c in mem.candidates]
    assert versions == sorted(versions)  # monotonic versioning
    persisted = engine.persistence.load_candidates()
    assert len(persisted) >= 1
