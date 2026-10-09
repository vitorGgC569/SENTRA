"""Architectural closeout invariants for SENTRA 1.0 consolidation."""
import asyncio

import pytest

from orchestrator.models import TokenUsage
from orchestrator.providers.base import AgentRequest, AgentResponse


def _request(role="executor", task="T-1"):
    return AgentRequest(
        system_prompt="system",
        user_prompt="user",
        role=role,
        timeout=30,
        metadata={"task_id": task},
    )


def test_conversation_identity_is_provider_aware():
    from sentra_core.conversation import ConversationIdentity

    chatgpt = ConversationIdentity.parse("https://chatgpt.com/c/abc-123?x=1")
    gemini = ConversationIdentity.parse("https://gemini.google.com/app/gem_123")
    assert chatgpt.provider == "chatgpt"
    assert chatgpt.conversation_id == "abc-123"
    assert chatgpt.canonical_url == "https://chatgpt.com/c/abc-123"
    assert gemini.provider == "gemini"
    assert gemini.conversation_id == "gem_123"
    assert gemini.canonical_url == "https://gemini.google.com/app/gem_123"

    assert ConversationIdentity.parse(chatgpt.canonical_url) == chatgpt
    assert ConversationIdentity.parse(gemini.canonical_url) == gemini
    with pytest.raises(ValueError):
        ConversationIdentity.parse("https://example.com/c/nope")


@pytest.mark.asyncio
async def test_fixed_router_accepts_gemini_conversation_identity(tmp_path):
    from orchestrator.agents.router import ModelRouter
    from orchestrator.conversation_pool import FixedConversationRouter

    class Gemini:
        persistent_conversations = True

        def __init__(self):
            self.calls = []
            self.adopted = []

        def adopt_conversations(self, urls):
            self.adopted.extend(urls)
            return len(urls)

        async def execute(self, request):
            self.calls.append(dict(request.metadata))
            url = request.metadata.get("conversation_url")
            if not url:
                url = "https://gemini.google.com/app/gem_123"
            return AgentResponse(
                content="ok",
                success=True,
                model="gemini-web",
                token_usage=TokenUsage(model="gemini-web"),
                metadata={
                    "provider": "gemini",
                    "conversation_url": url,
                    "conversation_id": "gem_123",
                },
            )

    provider = Gemini()
    inner = ModelRouter({"gemini_web": provider}, fallback_provider_name=None)
    pool = FixedConversationRouter(inner, run_id="R1", store_dir=tmp_path)
    first = await pool.execute(_request(), preferred_provider="gemini_web")
    second = await pool.execute(
        _request(task="T-2"), preferred_provider="gemini_web"
    )
    assert first.success and second.success
    assert provider.calls[1]["new_chat"] is False
    assert provider.adopted == ["https://gemini.google.com/app/gem_123"]


def test_control_plane_context_consumer_is_stable_across_tasks():
    from sentra_mcp.services.context_projection import ControlPlaneContextBridge

    seat = "swarm-r1:gpt.arch"
    assert ControlPlaneContextBridge._consumer_id(seat, "round-1") == (
        ControlPlaneContextBridge._consumer_id(seat, "round-2")
    )


def test_provider_rate_governor_isolated_lanes():
    from orchestrator.rate_governor import ProviderRateGovernor

    now = [100.0]
    governor = ProviderRateGovernor(
        {"chatgpt": 3.0, "gemini": 1.0}, clock=lambda: now[0]
    )
    governor.record_dispatch("chatgpt")
    assert governor.delay_for("chatgpt") == pytest.approx(3.0)
    assert governor.delay_for("gemini") == 0.0
    governor.hold("chatgpt", 10.0, reason="PLATFORM_HOLD")
    assert governor.delay_for("chatgpt") == pytest.approx(10.0)
    assert governor.delay_for("gemini") == 0.0

@pytest.mark.asyncio
async def test_turn_scheduler_starts_all_before_collecting():
    from orchestrator.turn_scheduler import ConversationTurnScheduler

    events = []

    async def start(item):
        events.append(("start", item))
        return {"conversation_url": f"https://chatgpt.com/c/{item}"}

    async def collect(started):
        events.append(("collect", started["conversation_url"].rsplit("/", 1)[-1]))
        return {"text": "ok", **started}

    scheduler = ConversationTurnScheduler(start=start, collect=collect)
    result = await scheduler.run_batch(["a", "b", "c"])
    assert [event[0] for event in events[:3]] == ["start", "start", "start"]
    assert [item["text"] for item in result] == ["ok", "ok", "ok"]


def test_swarm_turn_operation_key_is_stable():
    from orchestrator.swarm_cycle import PersistentSwarm

    key = PersistentSwarm.turn_idempotency_key(
        2, "cross_review", "gpt.arch", "abc123"
    )
    assert key == PersistentSwarm.turn_idempotency_key(
        2, "cross_review", "gpt.arch", "abc123"
    )
    assert key != PersistentSwarm.turn_idempotency_key(
        2, "cross_review", "gpt.security", "abc123"
    )


@pytest.mark.asyncio
async def test_gemini_cleanup_is_explicitly_retained_without_fake_delete():
    from browser.extension_transport import ExtensionTransport

    transport = ExtensionTransport(token="x" * 32)
    result = await transport.delete_chat(
        "https://gemini.google.com/app/gem_cleanup",
        provider="gemini",
    )
    assert result["status"] == "UNSUPPORTED"
    assert result["retained"] is True
    assert result["deleted"] is False
    assert result["conversation_url"] == (
        "https://gemini.google.com/app/gem_cleanup"
    )


def test_swarm_operational_pause_resume_reconcile_cancel(tmp_path):
    from orchestrator.swarm_cycle import LEAN_SWARM_AGENTS, PersistentSwarm

    swarm = PersistentSwarm(
        tmp_path / ".sentra",
        relay_token="x" * 32,
        provider_intervals={"chatgpt": 0.0, "gemini": 0.0},
    )
    try:
        created = swarm.create(
            "prove operational controls",
            run_id="swarm-ops-test",
            agents=LEAN_SWARM_AGENTS,
        )
        assert created["state"] == "RUNNING"
        assert swarm.pause("swarm-ops-test")["state"] == "PAUSED"
        assert swarm.resume("swarm-ops-test")["state"] == "RUNNING"
        report = swarm.reconcile("swarm-ops-test", stale_after_s=5)
        assert report["auto_replay"] is False
        assert swarm.chats("swarm-ops-test")["items"] == []
        assert swarm.list_runs(10)["count"] == 1
        assert swarm.cancel("swarm-ops-test")["state"] == "CANCELLED"
    finally:
        swarm.close()


def test_provider_rate_governor_shares_state_across_instances(tmp_path):
    from orchestrator.rate_governor import ProviderRateGovernor

    now = [100.0]
    state = tmp_path / "provider-rate.json"
    first = ProviderRateGovernor(
        {"chatgpt": 5.0}, state_path=state, clock=lambda: now[0]
    )
    second = ProviderRateGovernor(
        {"chatgpt": 5.0}, state_path=state, clock=lambda: now[0]
    )

    first.record_dispatch("chatgpt")
    assert second.delay_for("chatgpt") == pytest.approx(5.0)

    second.hold("chatgpt", 20.0, reason="RATE_LIMITED")
    snap = first.snapshot()["chatgpt"]
    assert snap["held"] is True
    assert snap["reason"] == "RATE_LIMITED"
    assert snap["delay_s"] == pytest.approx(20.0)
