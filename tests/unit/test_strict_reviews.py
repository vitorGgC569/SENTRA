import json
from types import SimpleNamespace

import pytest

from orchestrator.agents.master import MasterModelAgent, ReviewProtocolError
from orchestrator.agents.router import ModelRouter
from orchestrator.agents.validators import SpecializedValidator
from orchestrator.models import Candidate, CandidatePackage, Task, ValidationReport, ValidatorRole
from orchestrator.providers.base import AgentResponse
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.quality_gate import QualityGate, QuorumPolicy


@pytest.mark.parametrize("score", [None, True, float("nan"), 11, 9.499])
def test_strict_gate_never_derives_or_rounds_up_scores(score):
    gate = QualityGate(QuorumPolicy(validators_required=1, minimum_approvals=1,
        objective_test_required=False, require_explicit_scores=True))
    report = ValidationReport(validator_role="logic", confidence=1.0, score=score)
    assert not gate.evaluate(Task("T", "r", "x"), Candidate(), [report], {})[0]


async def test_strict_missing_score_is_abstention_not_approval():
    provider = MockProvider(custom_handler=lambda _: AgentResponse(content=json.dumps({
        "status": "APPROVED", "confidence": 1.0, "findings": []})))
    router = ModelRouter({"primary": provider}, fallback_provider_name=None)
    report = await SpecializedValidator(ValidatorRole.LOGIC, router, True).validate(Task("T", "r", "x"), Candidate())
    assert not report.ran


@pytest.mark.parametrize("content", ["[[R|a.py|1|5]]", "[]", "{}", '{"decision":"APPROVED","confidence":true}'])
async def test_malformed_master_review_is_not_a_semantic_rejection(content):
    provider = MockProvider(custom_handler=lambda _: AgentResponse(content=content))
    router = ModelRouter({"master": provider}, fallback_provider_name=None)
    with pytest.raises(ReviewProtocolError):
        await MasterModelAgent(router).review_candidate_package("objective", CandidatePackage("C", "T", "x", "s", "", ""))


async def test_api_provider_records_server_identity_and_does_not_double_count_reasoning(monkeypatch):
    from orchestrator.providers.openai_provider import OpenAIProvider
    from orchestrator.providers.base import AgentRequest
    seen = {}
    async def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=20), model="gpt-5.6-sol",
            id="resp_test", status="completed", output_text="ok")
    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        return SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr("orchestrator.providers.openai_provider.AsyncOpenAI", factory)
    provider = OpenAIProvider("gpt-5.6-sol", "test-not-a-real-key")
    response = await provider.execute(AgentRequest("s", "u"))
    assert response.metadata["model_identity"]["source"] == "openai_response"
    assert response.token_usage.output_tokens == 20 and response.token_usage.reasoning_tokens == 0
    assert seen["store"] is False


def test_api_provider_requires_key_without_network():
    from orchestrator.providers.openai_provider import OpenAIProvider
    with pytest.raises(ValueError, match="not configured"):
        OpenAIProvider("gpt-5.6-sol", None)
