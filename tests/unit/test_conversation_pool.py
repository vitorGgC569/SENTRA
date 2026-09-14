"""FixedConversationRouter: 1 chat persistente por seat, com resume em disco."""
import asyncio
import time

import pytest

from orchestrator.conversation_pool import FixedConversationRouter
from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.models import TokenUsage


def _req(role="executor", task="T-1"):
    return AgentRequest(system_prompt="s", user_prompt="u", role=role,
                        timeout=30, metadata={"task_id": task})


class FakeInner:
    """Router interno fake: primeira chamada abre chat, resto continua."""

    def __init__(self):
        self.calls = []
        self.budget = None
        self.adopted = []
        self.providers = {}

    async def execute(self, request, preferred_provider=None):
        self.calls.append((request.role, dict(request.metadata)))
        if request.metadata.get("new_chat", True):
            url = f"https://chatgpt.com/c/{request.role.replace('.', '-')}-abc"
            return AgentResponse(content="ok", success=True, model="fake",
                                 token_usage=TokenUsage(model="fake"),
                                 metadata={"conversation_url": url,
                                           "conversation_id": url.rsplit("/", 1)[-1],
                                           "worker": "W1"})
        return AgentResponse(content="continued", success=True, model="fake",
                             token_usage=TokenUsage(model="fake"),
                             metadata={"conversation_url": request.metadata["conversation_url"],
                                       "conversation_id": request.metadata["conversation_url"].rsplit("/", 1)[-1],
                                       "worker": "W1"})


class AdoptingProvider(FakeInner):
    def __init__(self):
        super().__init__()
        self.adopted = []

    def adopt_conversations(self, urls):
        self.adopted.extend(urls)
        return len(urls)


@pytest.mark.asyncio
async def test_second_call_continues_same_chat(tmp_path):
    inner = FakeInner()
    pool = FixedConversationRouter(inner, run_id="R1", store_dir=tmp_path)
    r1 = await pool.execute(_req("executor"))
    assert r1.success and len(inner.calls) == 1
    assert inner.calls[0][1].get("new_chat", True) is not False  # primeiro abre
    r2 = await pool.execute(_req("executor", task="T-2"))
    assert r2.content == "continued"
    assert inner.calls[1][1]["new_chat"] is False
    assert inner.calls[1][1]["conversation_url"] == \
        "https://chatgpt.com/c/executor-abc"
    assert set(pool.seats()) == {"R1:executor"}


@pytest.mark.asyncio
async def test_max_seats_caps_chat_creation_loudly(tmp_path):
    """O rate limit conta CHATS, não mensagens: 3º assento com max_seats=2
    é RECUSADO alto (CONVERSATION_BLOCKED), sem chamar o provider."""
    inner = FakeInner()
    pool = FixedConversationRouter(inner, run_id="R1", store_dir=tmp_path,
                                   max_seats=2)
    assert (await pool.execute(_req("executor"))).success is True
    assert (await pool.execute(_req("master"))).success is True
    before = len(inner.calls)
    resp = await pool.execute(_req("validator.logic"))
    assert resp.success is False
    assert "seat cap" in (resp.error or "")
    assert len(inner.calls) == before  # provider jamais acionado
    assert set(pool.seats()) == {"R1:executor", "R1:master"}


@pytest.mark.asyncio
async def test_seats_are_independent_per_role(tmp_path):
    inner = FakeInner()
    pool = FixedConversationRouter(inner, run_id="R1", store_dir=tmp_path)
    await pool.execute(_req("executor"))
    await pool.execute(_req("validator.logic"))
    assert set(pool.seats()) == {"R1:executor", "R1:validator.logic"}


@pytest.mark.asyncio
async def test_map_persists_across_processes_and_adopts(tmp_path):
    from orchestrator.agents.router import ModelRouter
    provider = AdoptingProvider()
    inner = ModelRouter({"primary": provider}, fallback_provider_name=None)
    pool = FixedConversationRouter(inner, run_id="R1", store_dir=tmp_path)
    await pool.execute(_req("executor"))
    # Novo processo: carrega do disco e adota no provider interno.
    provider2 = AdoptingProvider()
    unrelated = AdoptingProvider()
    inner2 = ModelRouter({"primary": provider2, "other": unrelated}, fallback_provider_name=None)
    pool2 = FixedConversationRouter(inner2, run_id="R1", store_dir=tmp_path)
    assert provider2.adopted == []  # Adoption happens only for the selected provider.
    r = await pool2.execute(_req("executor", task="T-9"))
    assert r.content == "continued"  # continuou sem abrir chat novo
    assert provider2.adopted == ["https://chatgpt.com/c/executor-abc"]
    assert unrelated.adopted == []


@pytest.mark.asyncio
async def test_provider_without_urls_degrades_to_new_chats(tmp_path):
    class Plain:
        def __init__(self):
            self.calls = 0
            self.providers = {}

        async def execute(self, request, preferred_provider=None):
            self.calls += 1
            return AgentResponse(content="ok", success=True, model="p",
                                 token_usage=TokenUsage(model="p"), metadata={})

    inner = Plain()
    pool = FixedConversationRouter(inner, run_id="R1", store_dir=tmp_path)
    await pool.execute(_req("executor"))
    await pool.execute(_req("executor"))
    assert inner.calls == 2 and pool.seats() == {}


@pytest.mark.asyncio
async def test_inter_call_delay_is_enforced(tmp_path):
    inner = FakeInner()
    pool = FixedConversationRouter(inner, run_id="R1", store_dir=tmp_path,
                                   inter_call_delay_s=0.2)
    start = time.monotonic()
    await pool.execute(_req("executor"))
    await pool.execute(_req("master"))
    assert time.monotonic() - start >= 0.18  # First dispatch need not wait.


@pytest.mark.asyncio
async def test_attribute_proxy_forwards_both_ways(tmp_path):
    inner = FakeInner()
    pool = FixedConversationRouter(inner, run_id="R1", store_dir=tmp_path)
    pool.budget = "B"
    assert inner.budget == "B" and pool.budget == "B"
