"""RF-016 Timeout Enforcement — real timeout behavior, not idempotency/path-traversal.

Covers: provider never responds, subprocess exceeds deadline, validator/executor
exceed timeout -> detected -> correct state -> retry when allowed -> circuit
breaker -> DLQ/escalation when the limit is exceeded.
"""
import asyncio

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.providers.base import AgentRequest
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.queue import PriorityTaskQueue
from orchestrator.models import Task
from workspace.command_runner import CommandRunner

from tests.support.fake_providers import HangingProvider, SlowProvider


def _req(timeout: int = 2, role: str = "executor", task_id: str = "T-timeout") -> AgentRequest:
    return AgentRequest(
        system_prompt="sys", user_prompt="do work", role=role,
        timeout=timeout, metadata={"task_id": task_id},
    )


@pytest.mark.asyncio
async def test_router_hanging_provider_times_out_and_falls_back():
    hanging = HangingProvider()
    fallback = MockProvider(model_name="fallback-ok")
    router = ModelRouter(
        providers={"primary": hanging, "fallback": fallback},
        primary_provider_name="primary",
        fallback_provider_name="fallback",
    )
    resp = await router.execute(_req(timeout=1))
    assert resp.success is True  # fallback rescued the call
    assert resp.model == "fallback-ok"


@pytest.mark.asyncio
async def test_router_uncertain_browser_failure_does_not_fallback():
    """Double-send protection: UNCERTAIN delivery never retries elsewhere."""
    from orchestrator.providers.base import AgentResponse
    from orchestrator.models import TokenUsage
    from browser.outcomes import classify_failure

    def uncertain(request):
        return AgentResponse(content="", success=False,
                             error="[TIMEOUT] task=T-1 browser send unconfirmed",
                             token_usage=TokenUsage(model="m"),
                             model="m", metadata=classify_failure("DELIVERY_UNCERTAIN"))

    primary = MockProvider(custom_handler=uncertain, model_name="browserish")
    fallback = MockProvider(model_name="fallback-ok")
    router = ModelRouter(providers={"primary": primary, "fallback": fallback},
                         primary_provider_name="primary", fallback_provider_name="fallback")
    resp = await router.execute(_req(timeout=5))
    assert resp.success is False  # falha preservada: fallback PROIBIDO aqui
    assert fallback.history == []  # prova: fallback jamais chamado (sem double-send)


@pytest.mark.asyncio
async def test_router_not_sent_failure_does_fallback():
    """NOT_SENT prova que nada foi entregue: fallback é seguro e exigido."""
    from orchestrator.providers.base import AgentResponse
    from orchestrator.models import TokenUsage
    from browser.outcomes import classify_failure

    def not_sent(request):
        return AgentResponse(content="", success=False,
                             error="FILL_FAILED: prompt preparation failed before submit",
                             token_usage=TokenUsage(model="m"),
                             model="m", metadata=classify_failure("FILL_FAILED"))

    primary = MockProvider(custom_handler=not_sent, model_name="browserish")
    fallback = MockProvider(model_name="fallback-ok")
    router = ModelRouter(providers={"primary": primary, "fallback": fallback},
                         primary_provider_name="primary", fallback_provider_name="fallback")
    resp = await router.execute(_req(timeout=5))
    assert resp.success is True
    assert resp.model == "fallback-ok"


@pytest.mark.asyncio
async def test_router_hanging_provider_without_fallback_returns_timeout():
    hanging = HangingProvider()
    router = ModelRouter(
        providers={"primary": hanging},
        primary_provider_name="primary",
        fallback_provider_name=None,
    )
    resp = await router.execute(_req(timeout=1))
    assert resp.success is False
    assert "TIMEOUT" in (resp.error or "")


@pytest.mark.asyncio
async def test_router_opens_circuit_after_repeated_timeouts():
    hanging = HangingProvider()
    router = ModelRouter(
        providers={"primary": hanging},
        primary_provider_name="primary",
        fallback_provider_name=None,
        failure_threshold=2,
        recovery_timeout=60,
    )
    r1 = await router.execute(_req(timeout=1))
    assert "TIMEOUT" in (r1.error or "")
    r2 = await router.execute(_req(timeout=1))
    assert "TIMEOUT" in (r2.error or "")
    # Circuit is now OPEN: next call fails fast without waiting the full timeout
    start = asyncio.get_running_loop().time()
    r3 = await router.execute(_req(timeout=5))
    elapsed = asyncio.get_running_loop().time() - start
    assert r3.success is False
    assert elapsed < 2.0  # fast-fail, did not hang


@pytest.mark.asyncio
async def test_subprocess_timeout_detected(tmp_path):
    runner = CommandRunner(tmp_path)
    import sys
    # Trusted fixture argv exercises process cleanup; model strings are denied.
    res = await runner.run_argv([sys.executable, "-c", "import time; time.sleep(10)"], timeout=1)
    assert res["passed"] is False
    assert "timed out" in res["stderr"].lower()


@pytest.mark.asyncio
async def test_validator_timeout_propagates_as_failure():
    from orchestrator.agents.validators import SpecializedValidator
    from orchestrator.models import Candidate, ValidatorRole
    from orchestrator.providers.base import AgentResponse
    from orchestrator.models import TokenUsage

    class FastTimeoutProvider:
        """Immediately returns a TIMEOUT failure (as the router would after enforcement)."""
        async def execute(self, request):
            return AgentResponse(content="", success=False,
                                 error="[TIMEOUT] provider exceeded deadline",
                                 token_usage=TokenUsage(model="t"),
                                 model="t")

    router = ModelRouter(providers={"primary": FastTimeoutProvider()},
                         primary_provider_name="primary", fallback_provider_name=None)
    v = SpecializedValidator(ValidatorRole.LOGIC, router)
    task = Task(id="T-v", run_id="r", objective="validate me")
    cand = Candidate(candidate_id="C-v", task_id="T-v", patch="diff")
    # A provider TIMEOUT must never silently become APPROVED.
    report = await asyncio.wait_for(
        v.validate(task, cand, test_results={"all_passed": True}), timeout=15
    )
    assert report.status in ("REJECTED", "DISPUTED")
    # Router-level hanging coverage lives in the two tests above (real wait_for).


@pytest.mark.asyncio
async def test_timeout_retry_then_dlq():
    queue = PriorityTaskQueue()
    t = Task(id="T-retry-timeout", run_id="r", objective="timeout then dlq", max_retries=1)
    await queue.add_task(t)
    popped = await queue.pop_ready_task()
    assert popped is not None
    # Simulate timeout failure #1 -> requeued
    assert await queue.mark_failed(popped.id, "[TIMEOUT] provider exceeded deadline", retryable=True) is True
    popped2 = await queue.pop_ready_task()
    assert popped2 is not None
    # Simulate timeout failure #2 -> exceeds max_retries -> DLQ
    assert await queue.mark_failed(popped2.id, "[TIMEOUT] provider exceeded deadline", retryable=True) is False
    assert queue.dlq_count == 1
