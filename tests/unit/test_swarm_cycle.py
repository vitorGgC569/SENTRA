from __future__ import annotations

import asyncio
import json
from pathlib import Path

from orchestrator.providers.base import AgentResponse
from orchestrator.swarm_cycle import DEFAULT_SWARM_AGENTS, PersistentSwarm
from sentra_remote.run_cli import main as sentra_cli_main


class _FakeProvider:
    def __init__(self, spec):
        self.spec = spec
        self.adopted = set()

    def adopt_conversations(self, urls):
        self.adopted.update(urls or [])
        return len(list(urls or []))

    async def execute(self, request):
        existing = request.metadata.get("conversation_url")
        if existing:
            url = existing
        elif self.spec.provider == "gemini":
            url = "https://gemini.google.com/app/" + self.spec.role.replace(".", "_")
        else:
            url = "https://chatgpt.com/c/" + self.spec.role.replace(".", "-")
        conversation_id = url.rsplit("/", 1)[-1]
        text = f"{self.spec.role} completed {request.metadata['task_id']}"
        if "PEER QUESTIONS" in request.user_prompt:
            target = (
                "gpt.implementation"
                if self.spec.role == "gpt.arch"
                else "gpt.arch"
            )
            text += f"\nQ->{target}: verify one invariant from {self.spec.role}"
        return AgentResponse(
            content=text,
            success=True,
            model="fake",
            metadata={
                "conversation_id": conversation_id,
                "conversation_url": url,
                "provider": self.spec.provider,
                "web_model": self.spec.model,
                "model": "fake",
                "worker": "TAB-FAKE",
            },
        )


class _FakeSwarm(PersistentSwarm):
    def _provider(self, spec):
        return _FakeProvider(spec)


def test_swarm_create_has_one_goal_and_seven_logical_agents(tmp_path: Path) -> None:
    swarm = _FakeSwarm(tmp_path)
    try:
        result = swarm.create(
            "Implement feature X safely",
            workspace=str(tmp_path),
            run_id="swarm-test-create",
            acceptance_criteria=["tests green"],
        )
        assert result["run_id"] == "swarm-test-create"
        assert result["goal"] == "Implement feature X safely"
        assert len(result["agents"]) == len(DEFAULT_SWARM_AGENTS) == 7
        assert {item["provider"] for item in result["agents"]} == {"chatgpt", "gemini"}
        assert all(item["chat"] is None for item in result["agents"])
    finally:
        swarm.close()


def test_swarm_round_persists_phases_questions_and_provider_chats(tmp_path: Path) -> None:
    swarm = _FakeSwarm(tmp_path)
    try:
        swarm.create(
            "Implement feature X safely",
            workspace=str(tmp_path),
            run_id="swarm-test-round",
        )
        result = asyncio.run(
            swarm.run_round("swarm-test-round", timeout_s=30, execute=False)
        )
        assert result["rounds_completed"] == 1
        assert result["active_round"] == 0
        assert len(result["agents"]) == 7
        assert all(item["chat"] for item in result["agents"])
        assert {item["chat"]["provider"] for item in result["agents"]} == {
            "chatgpt", "gemini"
        }

        manifest = swarm.load_manifest("swarm-test-round")
        phases = manifest["rounds"]["1"]["phases"]
        assert set(phases) == {
            "discover", "peer_questions", "cross_review", "implement",
            "test", "challenge", "synthesize",
        }
        assert all(item["completed"] for item in phases.values())
        assert 1 <= manifest["rounds"]["1"]["questions_sent"] <= 14
        assert phases["implement"]["roles"] == ["gpt.implementation"]
        assert phases["test"]["roles"] == ["gemini.tests"]
        assert phases["synthesize"]["roles"] == ["gpt.arch"]
    finally:
        swarm.close()


def test_swarm_phase_checkpoint_does_not_resend_completed_roles(tmp_path: Path) -> None:
    swarm = _FakeSwarm(tmp_path)
    try:
        swarm.create("Goal", run_id="swarm-test-checkpoint")
        first = asyncio.run(swarm.run_round("swarm-test-checkpoint", timeout_s=30))
        assert first["rounds_completed"] == 1
        first_file = (
            tmp_path / "swarms" / "swarm-test-checkpoint" / "rounds" / "1"
            / "discover" / "gpt.arch.txt"
        )
        before = first_file.read_text(encoding="utf-8")
        # A second invocation starts round 2; round 1 remains immutable evidence.
        second = asyncio.run(swarm.run_round("swarm-test-checkpoint", timeout_s=30))
        assert second["rounds_completed"] == 2
        assert first_file.read_text(encoding="utf-8") == before
    finally:
        swarm.close()


def test_sentra_cli_exposes_swarm_create_and_status(tmp_path: Path, capsys) -> None:
    state = tmp_path / "state"
    assert sentra_cli_main([
        "--state-dir", str(state),
        "swarm", "create",
        "--run-id", "swarm-cli",
        "--goal", "Ship feature Y",
        "--workspace", str(tmp_path),
    ]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["run_id"] == "swarm-cli"
    assert len(created["agents"]) == 7

    assert sentra_cli_main([
        "--state-dir", str(state),
        "swarm", "status", "swarm-cli",
    ]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["goal"] == "Ship feature Y"


def test_build_router_accepts_gemini_web_provider_in_mock_mode(tmp_path: Path) -> None:
    from orchestrator.configuration import build_router

    config = {
        "routing": {"worker": "gemini_web", "reviewer": "extension", "roles": {}},
        "oma": {},
        "browser": {},
        "gemini_web": {"model": "flash"},
    }
    router = build_router(config, mock=True, root=tmp_path)
    assert "gemini_web" in router.providers


def test_sentra_cli_lean_profile_creates_one_chatgpt_and_one_gemini_agent(tmp_path: Path, capsys) -> None:
    state = tmp_path / "state-lean"
    assert sentra_cli_main([
        "--state-dir", str(state),
        "swarm", "create",
        "--profile", "lean",
        "--run-id", "swarm-cli-lean",
        "--goal", "Smoke multi-provider cycle",
    ]) == 0
    created = json.loads(capsys.readouterr().out)
    assert len(created["agents"]) == 2
    assert {item["provider"] for item in created["agents"]} == {"chatgpt", "gemini"}
    assert {item["role"] for item in created["agents"]} == {
        "gpt.implementation", "gemini.adversarial"
    }


def test_swarm_uncertain_delivery_is_not_replayed_automatically(tmp_path: Path) -> None:
    swarm = _FakeSwarm(tmp_path)
    try:
        swarm.create("Goal", run_id="swarm-test-uncertain")
        manifest = swarm.load_manifest("swarm-test-uncertain")
        manifest["active_round"] = 1
        manifest["rounds"]["1"] = {
            "phases": {
                "discover": {
                    "completed": False,
                    "roles": [],
                    "deliveries": {
                        "gpt.arch": {
                            "state": "UNCERTAIN",
                            "retry_safe": False,
                            "error": "simulated lost response",
                        }
                    },
                }
            },
            "questions_sent": 0,
        }
        swarm._save_manifest(manifest)

        import pytest
        with pytest.raises(RuntimeError, match="SWARM_DELIVERY_UNCERTAIN"):
            asyncio.run(swarm.run_round("swarm-test-uncertain", timeout_s=30))
    finally:
        swarm.close()


def test_swarm_orphan_output_is_not_completion_authority(tmp_path: Path) -> None:
    swarm = _FakeSwarm(tmp_path)
    try:
        swarm.create("Goal", run_id="swarm-test-output-recovery")
        path = (
            tmp_path / "swarms" / "swarm-test-output-recovery" / "rounds" / "1"
            / "discover" / "gpt.arch.txt"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("already completed", encoding="utf-8")

        manifest = swarm.load_manifest("swarm-test-output-recovery")
        manifest["active_round"] = 1
        manifest["rounds"]["1"] = {
            "phases": {
                "discover": {
                    "completed": False,
                    "roles": [],
                    "deliveries": {
                        "gpt.arch": {"state": "IN_FLIGHT"}
                    },
                }
            },
            "questions_sent": 0,
        }
        swarm._save_manifest(manifest)

        result = asyncio.run(
            swarm.run_round("swarm-test-output-recovery", timeout_s=30)
        )
        assert result["rounds_completed"] == 1
        manifest = swarm.load_manifest("swarm-test-output-recovery")
        discover = manifest["rounds"]["1"]["phases"]["discover"]
        assert "gpt.arch" in discover["roles"]
        assert discover["deliveries"]["gpt.arch"]["state"] == "COMPLETED"
        assert path.read_text(encoding="utf-8") != "already completed"
        assert discover["deliveries"]["gpt.arch"].get("orphan_projection") == str(path)
        assert discover["deliveries"]["gpt.arch"].get("artifact_id")
    finally:
        swarm.close()


def test_swarm_cli_start_and_continue_are_simple_entrypoints() -> None:
    from sentra_remote.run_cli import _parser

    start = _parser().parse_args([
        "swarm", "start",
        "--goal", "Implement feature Z",
        "--profile", "lean",
        "--rounds", "2",
        "--execute",
    ])
    assert start.domain == "swarm"
    assert start.action == "start"
    assert start.profile == "lean"
    assert start.rounds == 2
    assert start.execute is True

    cont = _parser().parse_args([
        "swarm", "continue", "swarm-123",
        "--rounds", "3",
    ])
    assert cont.action == "continue"
    assert cont.run_id == "swarm-123"
    assert cont.rounds == 3


def test_swarm_recognizes_legacy_wait_settled_failure_as_pre_send():
    assert PersistentSwarm._legacy_pre_send_not_ready({
        "state": "UNCERTAIN",
        "error": "gpt/peer_questions: TAB_ERROR tab=1: conversa n├úo estabilizou (gera├º├úo presa?)",
    })
    assert not PersistentSwarm._legacy_pre_send_not_ready({
        "state": "UNCERTAIN",
        "error": "CONVERSATION_MISMATCH after response",
    })


def test_swarm_reconciles_legacy_model_selection_failure_as_not_sent(tmp_path: Path) -> None:
    swarm = _FakeSwarm(tmp_path)
    try:
        swarm.create("Goal", run_id="swarm-test-model-reconcile")
        manifest = swarm.load_manifest("swarm-test-model-reconcile")
        manifest["active_round"] = 1
        manifest["rounds"]["1"] = {
            "phases": {
                "discover": {
                    "completed": False,
                    "roles": ["gpt.implementation"],
                    "deliveries": {
                        "gpt.implementation": {"state": "COMPLETED"},
                        "gemini.adversarial": {
                            "state": "UNCERTAIN",
                            "retry_safe": False,
                            "error": "gemini.adversarial/discover: MODEL_SELECTION_FAILED: selector not found",
                        },
                    },
                }
            },
            "questions_sent": 0,
        }
        swarm._save_manifest(manifest)

        migrated = swarm.load_manifest("swarm-test-model-reconcile")
        delivery = migrated["rounds"]["1"]["phases"]["discover"]["deliveries"]["gemini.adversarial"]
        assert delivery["state"] == "NOT_SENT"
        assert delivery["retry_safe"] is True
        assert delivery["reconciled_from"] == "UNCERTAIN"
    finally:
        swarm.close()
