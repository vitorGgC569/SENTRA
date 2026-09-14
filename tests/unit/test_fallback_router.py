"""DegradedFallbackRouter: one honest local attempt max, fakes only, no live."""
import asyncio

import pytest

from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.providers.degradation import DeadPathBudget
from orchestrator.providers.fallback_router import DegradedFallbackRouter
from orchestrator.models import TokenUsage


DEAD = "[TOOL_ERROR] task=T-1 no extension connected: nenhum worker fez poll"
LEASE = "[MODEL_ERROR] task=T-2 [sw=1.4.0] LEASE_LOST"
CONTENT = "[CONVERSATION_MISMATCH] result came from another conversation"
UNCERTAIN = "[MODEL_ERROR] task=T-3 DELIVERY_UNCERTAIN: state unknown"
BLOCKED = "[MODEL_ERROR] ACCOUNT_LIMIT reached"


def _request():
    return AgentRequest(system_prompt="sys", user_prompt="do task",
                        role="executor", timeout=10,
                        metadata={"task_id": "T-1"})


class FailProvider:
    def __init__(self, error, metadata=None):
        self.error = error
        self.metadata = dict(metadata or {})
        self.calls = 0

    async def execute(self, request):
        self.calls += 1
        return AgentResponse(content="", success=False, error=self.error,
                             token_usage=TokenUsage(model="fake-primary"),
                             model="fake-primary", metadata=dict(self.metadata))


class SuccessProvider:
    def __init__(self, content="ok", model="fake-model"):
        self.content = content
        self.model = model
        self.calls = 0

    async def execute(self, request):
        self.calls += 1
        return AgentResponse(content=self.content, success=True, model=self.model,
                             token_usage=TokenUsage(model=self.model),
                             metadata={})


@pytest.mark.asyncio
async def test_degrades_once_on_dead_path_and_marks_honestly():
    primary = FailProvider(DEAD)
    fallback = SuccessProvider(content="weak answer", model="qwen-local")
    router = DegradedFallbackRouter(primary, fallback)
    resp = await router.execute(_request())
    assert resp.success is True
    assert resp.content == "weak answer"
    assert resp.model == "qwen-local"
    assert resp.metadata["degraded"] is True
    assert "no extension connected" in resp.metadata["original_error"]
    assert primary.calls == 1
    assert fallback.calls == 1  # at most once per call


@pytest.mark.asyncio
async def test_primary_success_never_touches_fallback():
    primary = SuccessProvider(content="strong answer", model="browser-extension")
    fallback = SuccessProvider(content="weak", model="qwen-local")
    router = DegradedFallbackRouter(primary, fallback)
    resp = await router.execute(_request())
    assert resp.success is True
    assert resp.metadata.get("degraded") is not True
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_never_degrades_on_content_quality():
    primary = FailProvider(CONTENT)
    fallback = SuccessProvider(content="weak", model="qwen-local")
    router = DegradedFallbackRouter(primary, fallback)
    resp = await router.execute(_request())
    assert resp.success is False
    assert "CONVERSATION_MISMATCH" in (resp.error or "")
    assert resp.metadata.get("degraded") is not True
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_never_degrades_on_uncertain_delivery():
    primary = FailProvider(LEASE, metadata={"delivery_state": "UNCERTAIN",
                                            "retry_safe": False})
    fallback = SuccessProvider(content="weak", model="qwen-local")
    router = DegradedFallbackRouter(primary, fallback)
    resp = await router.execute(_request())
    assert resp.success is False
    assert "LEASE_LOST" in (resp.error or "")
    assert fallback.calls == 0  # reconcile path, never replay


@pytest.mark.asyncio
async def test_never_degrades_on_blocked_quota():
    primary = FailProvider(BLOCKED)
    fallback = SuccessProvider(content="weak", model="qwen-local")
    router = DegradedFallbackRouter(primary, fallback)
    resp = await router.execute(_request())
    assert resp.success is False
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_allow_degrade_false_disables_fallback():
    primary = FailProvider(DEAD)
    fallback = SuccessProvider(content="weak", model="qwen-local")
    router = DegradedFallbackRouter(primary, fallback, allow_degrade=False)
    resp = await router.execute(_request())
    assert resp.success is False
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_fallback_failure_returns_primary_error_honestly():
    primary = FailProvider(DEAD)
    fallback = FailProvider("[NETWORK_ERROR] local model unavailable",
                            metadata={})
    router = DegradedFallbackRouter(primary, fallback)
    resp = await router.execute(_request())
    assert resp.success is False
    assert "no extension connected" in (resp.error or "")
    assert "local model unavailable" in str(resp.metadata.get("fallback_error", ""))
    assert resp.metadata.get("degraded") is not True


@pytest.mark.asyncio
async def test_budget_ceiling_aborts_without_calling_fallback():
    primary = FailProvider(DEAD)
    fallback = SuccessProvider(content="weak", model="qwen-local")
    budget = DeadPathBudget(max_consecutive_dead_path=2)
    router = DegradedFallbackRouter(primary, fallback, budget=budget)
    first = await router.execute(_request())
    assert first.success is True and first.metadata.get("degraded") is True
    second = await router.execute(_request())
    assert second.success is True and second.metadata.get("degraded") is True
    assert router.consecutive_dead_path == 2
    third = await router.execute(_request())
    assert third.success is False
    assert "DEAD_PATH_BUDGET" in (third.error or "")
    assert "no extension connected" in (third.error or "")
    assert fallback.calls == 2  # ceiling call never attempted the fallback


@pytest.mark.asyncio
async def test_primary_success_resets_streak():
    budget = DeadPathBudget(max_consecutive_dead_path=2)
    dead = FailProvider(DEAD)
    weak = SuccessProvider(content="weak", model="qwen-local")
    router = DegradedFallbackRouter(dead, weak, budget=budget)
    await router.execute(_request())
    assert router.consecutive_dead_path == 1
    healed = DegradedFallbackRouter(SuccessProvider("strong", "browser-extension"),
                                    weak, budget=budget)
    resp = await healed.execute(_request())
    assert resp.success is True
    assert router.consecutive_dead_path == 0


@pytest.mark.asyncio
async def test_cancellation_always_propagates():
    class CancellingPrimary:
        async def execute(self, request):
            raise asyncio.CancelledError()

    router = DegradedFallbackRouter(CancellingPrimary(),
                                    SuccessProvider("weak", "local"))
    with pytest.raises(asyncio.CancelledError):
        await router.execute(_request())
