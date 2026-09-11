import pytest
from orchestrator.agents.router import CircuitBreaker, CircuitState, ModelRouter
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.providers.base import AgentRequest, AgentResponse


def test_circuit_breaker_lifecycle():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_attempt() is True

    # 1 failure
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED

    # 2 failures -> trips to OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_attempt() is False


@pytest.mark.asyncio
async def test_model_router_fallback():
    failing_primary = MockProvider()
    failing_primary.should_fail = True

    healthy_fallback = MockProvider(default_response="FALLBACK_SUCCESS")

    router = ModelRouter(
        providers={"primary": failing_primary, "fallback": healthy_fallback},
        primary_provider_name="primary",
        fallback_provider_name="fallback",
    )

    req = AgentRequest(system_prompt="sys", user_prompt="usr", role="test")
    resp = await router.execute(req)

    # Primary failed and router seamlessly failed over to fallback!
    assert resp.success is True
    assert resp.content == "FALLBACK_SUCCESS"
