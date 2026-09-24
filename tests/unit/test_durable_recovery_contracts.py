from __future__ import annotations

import json
from pathlib import Path

import pytest

from native_bridge.protocol import ChatJob
from orchestrator.conversation_pool import FixedConversationRouter
from orchestrator.failure_summary import summarize_failure_text, summarize_test_results
from orchestrator.models import TokenUsage
from orchestrator.providers.base import AgentRequest, AgentResponse
from sentra_mcp.services.durable import DurableRunService
from sentra_remote.run_cli import main as run_cli_main
from workspace.patch_manager import PatchManager


def test_patch_dry_run_ast_compile_rejects_before_mutation(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    invalid = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x = 1\n"
        "+def broken(:\n"
    )
    with pytest.raises(ValueError, match="AST syntax error"):
        PatchManager.dry_run_validate(tmp_path, invalid)
    assert target.read_text(encoding="utf-8") == "x = 1\n"

    valid = invalid.replace("def broken(:", "x = 2")
    report = PatchManager.dry_run_validate(tmp_path, valid)
    assert report["valid"] is True
    assert report["python_files"] == ["a.py"]
    assert report["checks"] == ["patch_apply", "ast_parse", "py_compile"]
def test_failure_summary_keeps_assertion_and_drops_noise() -> None:
    noise = "\n".join(f"debug line {i}" for i in range(2000))
    raw = noise + "\nFAILED tests/test_x.py::test_value\nAssertionError: expected 2 actual 1\n"
    summary = summarize_failure_text(raw, max_chars=1200)
    assert "AssertionError: expected 2 actual 1" in summary
    assert len(summary) <= 1200

    evidence = {
        "all_passed": False,
        "failed_commands": ["pytest"],
        "results": [{
            "command": "pytest",
            "passed": False,
            "returncode": 1,
            "stdout": raw,
            "stderr": "",
        }],
    }
    compact = summarize_test_results(evidence, max_result_chars=1200)
    assert compact["failures"][0]["command"] == "pytest"
    assert "AssertionError" in compact["failures"][0]["stdout"]


def test_sentra_run_resume_cli_reads_durable_state(tmp_path: Path, capsys) -> None:
    state = tmp_path / ".sentra"
    service = DurableRunService(state)
    try:
        service.create_run("cli-owner", run_id="run-cli-resume")
        service.checkpoint(
            "run-cli-resume", "cli-owner", {"step": 3}, label="handoff"
        )
    finally:
        service.close()

    assert run_cli_main([
        "--state-dir", str(state), "run", "resume", "run-cli-resume"
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "run-cli-resume"
    assert payload["resume"]["safe_to_continue"] is True
    assert payload["last_event_seq"] >= 2


class _ProjectInner:
    def __init__(self) -> None:
        self.calls = []
        self.budget = None
        self.providers = {}

    async def execute(self, request, preferred_provider=None):
        self.calls.append(dict(request.metadata))
        return AgentResponse(
            content="ok",
            success=True,
            model="fake",
            token_usage=TokenUsage(model="fake"),
            metadata={
                "conversation_url": "https://chatgpt.com/c/project-chat",
                "conversation_id": "project-chat",
                "worker": "W1",
            },
        )
@pytest.mark.asyncio
async def test_fixed_chat_pool_propagates_project_and_stable_title(tmp_path: Path) -> None:
    inner = _ProjectInner()
    pool = FixedConversationRouter(
        inner,
        run_id="run-project",
        store_dir=tmp_path,
        chat_project="https://chatgpt.com/g/g-p-demo/project",
    )
    response = await pool.execute(AgentRequest(
        system_prompt="s",
        user_prompt="u",
        role="executor",
        metadata={"task_id": "T-1"},
    ))
    assert response.success is True
    metadata = inner.calls[0]
    assert metadata["project_url"] == "https://chatgpt.com/g/g-p-demo/project"
    assert metadata["chat_title"] == "[SENTRA] run-project - executor"
    persisted = pool.seats()["run-project:executor"]
    assert persisted["project_url"] == metadata["project_url"]
    assert persisted["chat_title"] == metadata["chat_title"]


def test_chat_job_validates_project_identity_and_title() -> None:
    job = ChatJob(
        task_id="T-project",
        prompt="work",
        project_id="demo-1",
        project_url="https://chatgpt.com/g/g-p-demo/project",
        chat_title="[SENTRA] run-1 - builder",
    )
    job.validate()
    with pytest.raises(ValueError, match="project_url"):
        ChatJob(
            task_id="T-bad",
            prompt="work",
            project_url="https://example.com/project",
        ).validate()
