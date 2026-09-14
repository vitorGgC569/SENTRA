"""Real tests execute patched source; scripted LLMs cannot override failures."""
import json

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.engine import OMAEngine
from orchestrator.models import Candidate, Task
from orchestrator.providers.base import AgentResponse
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.verification import CandidateVerifier
from workspace.command_runner import CommandRunner
from workspace.git_manager import GitManager


def seed(root):
    (root / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text(
        "from app import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        "def test_negative():\n    assert add(-2, 3) == 1\n")


def patch(expression):
    return ("--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n"
            "-    return a + b\n+    return " + expression + "\n")


async def test_baseline_passes_but_broken_candidate_fails_and_root_is_preserved(tmp_path):
    seed(tmp_path)
    baseline = await CommandRunner(tmp_path).run_command("[[TEST|all]]")
    assert baseline["passed"]
    candidate = Candidate(candidate_id="bad", task_id="T", patch=patch("a - b"))
    result = await CandidateVerifier(tmp_path).verify(candidate)
    assert not result["all_passed"]
    assert "2 failed" in result["results"][0]["stdout"]
    assert result["source_unchanged"] and result["base_hash"] != result["candidate_hash"]
    assert (tmp_path / "app.py").read_text() == "def add(a, b):\n    return a + b\n"


async def test_candidate_cannot_replace_mandatory_checks(tmp_path):
    seed(tmp_path)
    candidate = Candidate(candidate_id="C", task_id="T", patch=patch("a - b"),
                          validation_commands=["[[LINT]]"])
    result = await CandidateVerifier(tmp_path).verify(candidate)
    assert not result["all_passed"]
    assert result["failed_commands"] == ["[[TEST|all]]"]
    assert result["passed_commands"] == ["[[LINT]]"]


async def test_git_isolation_returns_patch_without_touching_checkout(tmp_path):
    seed(tmp_path)
    result = await GitManager(tmp_path).apply_in_isolated_worktree([patch("sum((a, b))")])
    assert result["success"] and "sum((a, b))" in result["patch"]
    assert "sum" not in (tmp_path / "app.py").read_text()


async def test_engine_rejects_actual_failure_repairs_then_sends_only_passed_package(tmp_path):
    seed(tmp_path)
    master_calls = []

    def handler(request):
        if request.role in {"executor", "repair"}:
            expression = "a - b" if request.role == "executor" else "sum((a, b))"
            return AgentResponse(content="BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: add\nPATCH:\n```diff\n"
                                 + patch(expression) + "```\nVALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT")
        if request.role == "master":
            master_calls.append(request)
            assert "sum((a, b))" in request.user_prompt
            return AgentResponse(content=json.dumps({"decision": "APPROVED", "confidence": .95,
                                 "needs_more_work": False, "critical_issues": [], "reasoning": "verified"}))
        # Even unanimous scripted approvals must be blocked by real failing tests.
        return AgentResponse(content=json.dumps({"status": "APPROVED", "confidence": .95,
                             "findings": [], "requirements_checked": []}))

    provider = MockProvider(custom_handler=handler)
    router = ModelRouter({"primary": provider, "master": provider}, fallback_provider_name=None)
    engine = OMAEngine("candidate-evidence", "improve add", tmp_path, router)
    task = Task("T-1", engine.run_id, "improve add")
    await engine.task_queue.add_task(task)
    ready = await engine.task_queue.pop_ready_task()
    assert await engine.process_task(ready)
    assert task.current_repair_round == 1
    assert len(master_calls) == 1
    assert "sum((a, b))" in (tmp_path / "app.py").read_text()
    verifications = [json.loads(p.read_text()) for p in engine.persistence.run_dir.glob("verification-*.json")]
    assert len(verifications) == 2
    assert {v["all_passed"] for v in verifications} == {False, True}
    assert all(v["patch_hash"] and v["candidate_hash"] for v in verifications)


async def test_missing_test_evidence_and_duplicate_votes_cannot_pass():
    from orchestrator.models import ValidationReport
    from orchestrator.quality_gate import QualityGate
    gate = QualityGate()
    task = Task("T", "run", "verify")
    candidate = Candidate(candidate_id="C", task_id=task.id)
    reports = [ValidationReport(validator_id=f"v-{i}", validator_role=f"role-{i}") for i in range(3)]
    assert not gate.evaluate(task, candidate, reports)[0]
    assert not gate.evaluate(task, candidate, reports, {"all_passed": True, "results": []})[0]
    assert not gate.evaluate(task, candidate, [reports[0]] * 3,
                             {"all_passed": True, "results": [{"passed": True}]})[0]
