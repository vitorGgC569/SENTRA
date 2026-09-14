"""Real repository/test loop, scripted models: never labeled live calibration."""
import json
from pathlib import Path

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.configuration import engine_options
from orchestrator.models import TokenUsage
from orchestrator.providers.base import AgentResponse
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.runtime import IntegratedRun


PATCH = "--- a/value.txt\n+++ b/value.txt\n@@ -1 +1 @@\n-old\n+new\n"


def make_provider(mode="read"):
    calls = {"executor": 0, "repair": 0, "master": 0}

    def respond(request):
        role = request.role
        if role == "planner":
            content = json.dumps({"tasks": [{"id": "T-01", "objective": "fix value",
                "description": "fix value", "dependencies": [], "priority": "MEDIUM", "risk": "LOW"}]})
        elif role in {"executor", "repair"}:
            calls[role] += 1
            content = "BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: fixed\nPATCH:\n```diff\n" + PATCH + "```\nVALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT"
        elif role.startswith("validator"):
            content = json.dumps({"status": "APPROVED", "confidence": .98, "score": 9.6,
                "findings": [], "requirements_checked": request.metadata.get("acceptance_criteria", [])})
        else:
            calls["master"] += 1
            if mode == "invalid":
                content = "not a review"
            elif mode == "read" and calls["master"] == 1:
                content = "[[R|value.txt|1|5]]"
            else:
                if mode == "read":
                    assert "UNTRUSTED_REPOSITORY_RESULTS" in request.user_prompt
                    assert "new" in request.user_prompt  # patched snapshot, NOT original 'old'
                reject = mode == "reject_once" and calls["master"] == 1
                content = json.dumps({"decision": "REJECTED" if reject else "APPROVED",
                    "confidence": .98, "needs_more_work": reject, "critical_issues": [],
                    "remaining_risks": [], "reasoning": "Check the boundary" if reject else "verified",
                    "final_response": "done"})
        return AgentResponse(content=content, model="scripted-cycle", token_usage=TokenUsage(input_tokens=5, output_tokens=5))
    return MockProvider(custom_handler=respond), calls


def fixture_repo(root):
    (root / "value.txt").write_text("old\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_value.py").write_text(
        "from pathlib import Path\ndef test_value():\n    assert Path('value.txt').read_text() == 'new\\n'\n", encoding="utf-8")


@pytest.mark.parametrize("mode,expected", [("read", "CANDIDATE_READY"), ("reject_once", "CANDIDATE_READY"), ("invalid", "FAILED")])
async def test_master_preserves_candidate_and_uses_readonly_gateway(tmp_path, mode, expected):
    fixture_repo(tmp_path)
    provider, calls = make_provider(mode)
    router = ModelRouter({"primary": provider, "master": provider}, fallback_provider_name=None)
    options = engine_options({"oma": {"max_repair_rounds": 2}})
    result = await IntegratedRun(tmp_path, "review-cycle", "fix value", router, **options).run()
    assert result["status"] == expected, result.get("errors")
    assert (tmp_path / "value.txt").read_text() == "old\n"
    assert calls["executor"] == 1
    assert calls["repair"] == (1 if mode == "reject_once" else 0)
    reviews = [json.loads(p.read_text()) for p in (tmp_path / "runs" / "review-cycle").glob("review-*.json")]
    assert reviews and all(r["verification"]["all_passed"] for r in reviews)
    if mode == "invalid":
        assert reviews[0]["status"] == "BLOCKED"
        assert reviews[0]["candidate"]["patch"] == PATCH.rstrip("\n") or reviews[0]["candidate"]["patch"] == PATCH


async def test_queue_runs_existing_engine_then_imports_once_without_promotion(tmp_path, monkeypatch):
    from orchestrator.master_queue import MasterQueue
    fixture_repo(tmp_path)
    provider, calls = make_provider()
    router = ModelRouter({"primary": provider, "master": provider}, fallback_provider_name=None)
    monkeypatch.setattr("orchestrator.configuration.build_router", lambda config: router)
    queue = MasterQueue(tmp_path)
    config = {"oma": {"max_repair_rounds": 2, "inter_call_delay_s": 0}}
    queue.ingest({"schema_version": 1, "limits": {"total_tokens": 220000, "total_seconds": 900},
        "jobs": [{"id": "one", "objective": "fix value", "agents": 6,
                  "budget": {"master": 20000, "secondary": 200000, "task": 150000, "seconds": 900}}]}, config)
    result = await queue.run_next(trust_workspace=True)
    assert result["status"] == "CANDIDATE_READY", result
    initial = queue.inbox()
    queue.import_final("one")
    assert queue.inbox() == initial and len(initial) == 1
    receipt = queue.acknowledge("one", initial[0]["digest"], "central-test")
    assert receipt["promoted"] is False
    assert (tmp_path / "value.txt").read_text() == "old\n"
    before = len(provider.history)
    assert (await queue.run_next(trust_workspace=True))["status"].startswith("IDLE")
    assert len(provider.history) == before
    assert calls["executor"] == 1
