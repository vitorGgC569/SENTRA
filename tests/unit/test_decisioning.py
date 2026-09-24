from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.configuration import configure_decisioning
from orchestrator.decisioning import (
    DecisionBatch,
    DecisionController,
    SystemOneHTTPProvider,
)
from orchestrator.providers.base import AgentRequest, AgentResponse


class _Handler(BaseHTTPRequestHandler):
    response = {
        "model": "kev-test",
        "answers": {
            "provider": {
                "type": "choice",
                "choice": "cheap",
                "confidence": 0.8,
                "probabilities": {"primary": 0.1, "cheap": 0.9},
            }
        },
        "usage": {"input_tokens": 12, "output_tokens": 4},
        "latency_ms": 3.5,
    }
    seen_auth = None

    def do_POST(self):
        assert self.path == "/v1/systemone"
        type(self).seen_auth = self.headers.get("authorization")
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length))
        assert payload["model"] == "kev-latest"
        assert "provider" in payload["questions"]
        body = json.dumps(type(self).response).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


@pytest.fixture
def systemone_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_systemone_http_roundtrip(systemone_server):
    _Handler.seen_auth = None
    provider = SystemOneHTTPProvider(
        systemone_server,
        model="kev-latest",
        api_key="local-secret",
        name="kev",
    )
    batch = await provider.decide(
        state={"role": "executor"},
        questions={
            "provider": {
                "type": "choice",
                "instructions": "route",
                "criteria": {"primary": None, "cheap": None},
            }
        },
    )
    assert batch.provider == "kev"
    assert batch.model == "kev-test"
    assert batch.answers["provider"]["choice"] == "cheap"
    assert batch.latency_ms == 3.5
    assert _Handler.seen_auth == "Bearer local-secret"


@pytest.mark.asyncio
async def test_controller_low_confidence_falls_back_deterministically(systemone_server):
    old = _Handler.response
    _Handler.response = {
        "model": "kev-test",
        "answers": {
            "provider": {
                "type": "choice",
                "choice": "cheap",
                "confidence": 0.1,
                "probabilities": {"primary": 0.49, "cheap": 0.51},
            }
        },
    }
    try:
        controller = DecisionController(
            [SystemOneHTTPProvider(systemone_server, name="kev")],
            min_confidence=0.5,
        )
        selected = await controller.choose(
            state="x",
            instructions="route",
            criteria={"primary": None, "cheap": None},
            default="primary",
            question_id="provider",
        )
        assert selected.value == "primary"
        assert selected.source == "deterministic"
        assert selected.used_deterministic_fallback is True
    finally:
        _Handler.response = old


class _Agent:
    def __init__(self, text: str, *, fail: bool = False):
        self.text = text
        self.fail = fail
        self.calls = 0

    async def execute(self, _request):
        self.calls += 1
        if self.fail:
            return AgentResponse(content="", success=False, error="boom")
        return AgentResponse(content=self.text, success=True)


class _Decision:
    name = "kev"

    def __init__(self, choice="cheap", confidence=0.9):
        self.choice = choice
        self.confidence = confidence
        self.calls = 0

    async def decide(self, *, state, questions):
        self.calls += 1
        assert state["deterministic_route"] == "primary"
        return DecisionBatch(
            provider="kev",
            model="kev-test",
            answers={
                "provider": {
                    "type": "choice",
                    "choice": self.choice,
                    "confidence": self.confidence,
                    "probabilities": {"primary": 0.1, "cheap": 0.9},
                }
            },
        )


@pytest.mark.asyncio
async def test_router_decision_reorders_but_keeps_deterministic_route():
    primary = _Agent("PRIMARY_OK")
    cheap = _Agent("", fail=True)
    router = ModelRouter(
        {"primary": primary, "cheap": cheap},
        primary_provider_name="primary",
        fallback_provider_name=None,
    )
    decision = _Decision("cheap", 0.9)
    router.decision_controller = DecisionController([decision], min_confidence=0.2)
    router.decision_routing_enabled = True

    response = await router.execute(
        AgentRequest(system_prompt="s", user_prompt="ordinary task", role="executor")
    )
    assert response.success is True
    assert response.content == "PRIMARY_OK"
    assert cheap.calls == 1
    assert primary.calls == 1
    assert decision.calls == 1


@pytest.mark.asyncio
async def test_router_critical_and_explicit_routes_bypass_decision_model():
    primary = _Agent("PRIMARY")
    cheap = _Agent("CHEAP")
    router = ModelRouter(
        {"primary": primary, "cheap": cheap},
        primary_provider_name="primary",
        fallback_provider_name=None,
    )
    decision = _Decision("cheap", 0.99)
    router.decision_controller = DecisionController([decision])
    router.decision_routing_enabled = True

    critical = await router.execute(
        AgentRequest(
            system_prompt="s",
            user_prompt="critical task",
            role="executor",
            metadata={"priority": "CRITICAL"},
        )
    )
    assert critical.content == "PRIMARY"
    assert decision.calls == 0

    explicit = await router.execute(
        AgentRequest(system_prompt="s", user_prompt="forced", role="executor"),
        preferred_provider="primary",
    )
    assert explicit.content == "PRIMARY"
    assert decision.calls == 0



def test_configure_decisioning_builds_ordered_systemone_chain(monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "secret")
    router = ModelRouter({"primary": _Agent("PRIMARY")}, fallback_provider_name=None)
    out = configure_decisioning(router, {
        "decisioning": {
            "enabled": True,
            "routing": True,
            "retry": True,
            "validator_selection": True,
            "quality_advisory": True,
            "min_confidence": 0.42,
            "providers": [
                {
                    "name": "kev",
                    "type": "systemone",
                    "base_url": "http://127.0.0.1:8009",
                    "model": "kev-latest",
                },
                {
                    "name": "jev",
                    "type": "systemone",
                    "base_url": "https://example.invalid",
                    "model": "jev-latest",
                    "api_key_env": "TEST_JEV_KEY",
                },
            ],
        }
    })
    assert out is router
    assert router.decision_routing_enabled is True
    assert router.decision_retry_enabled is True
    assert router.decision_validator_selection_enabled is True
    assert router.decision_quality_advisory_enabled is True
    assert router.decision_min_confidence == 0.42
    assert [p.name for p in router.decision_controller.providers] == ["kev", "jev"]
    assert router.decision_controller.providers[1].api_key == "secret"


def test_decisioning_rejects_plaintext_remote_endpoint():
    router = ModelRouter({"primary": _Agent("PRIMARY")}, fallback_provider_name=None)
    with pytest.raises(ValueError, match="loopback"):
        configure_decisioning(router, {
            "decisioning": {
                "enabled": True,
                "routing": True,
                "providers": [{
                    "name": "bad",
                    "base_url": "http://example.com:8009",
                }],
            }
        })


@pytest.mark.asyncio
async def test_controller_supports_noul_and_score():
    class Typed:
        name = "kev"

        async def decide(self, *, state, questions):
            qid, question = next(iter(questions.items()))
            if question["type"] == "noul":
                answer = {"type": "noul", "noul": 0.83}
            else:
                answer = {
                    "type": "score",
                    "score": 1.7,
                    "confidence": 0.74,
                    "probabilities": {"0": 0.05, "1": 0.2, "2": 0.75},
                }
            return DecisionBatch(provider="kev", model="kev-test", answers={qid: answer})

    controller = DecisionController([Typed()])
    probability, source = await controller.noul(
        state={"gate": "candidate"},
        instructions="Should another validator run?",
    )
    assert probability == pytest.approx(0.83)
    assert source == "kev"

    score, confidence, source = await controller.score(
        state={"gate": "candidate"},
        instructions="How ready is this candidate?",
        criteria=["not ready", "needs review", "ready"],
    )
    assert score == pytest.approx(1.7)
    assert confidence == pytest.approx(0.74)
    assert source == "kev"



class _RetryDecision:
    name = "kev"

    def __init__(self, choice: str, confidence: float = 0.9):
        self.choice = choice
        self.confidence = confidence
        self.calls = 0

    async def decide(self, *, state, questions):
        self.calls += 1
        assert state["classification"] == "SAFE_TRANSIENT"
        qid = next(iter(questions))
        return DecisionBatch(
            provider="kev",
            model="kev-test",
            answers={
                qid: {
                    "type": "choice",
                    "choice": self.choice,
                    "confidence": self.confidence,
                    "probabilities": {
                        "retry": 0.9 if self.choice == "retry" else 0.1,
                        "abort": 0.9 if self.choice == "abort" else 0.1,
                    },
                }
            },
        )


def _retry_engine(decision, *, threshold=0.35):
    from orchestrator.engine import OMAEngine

    engine = OMAEngine.__new__(OMAEngine)
    router = ModelRouter({"primary": _Agent("PRIMARY")}, fallback_provider_name=None)
    router.decision_controller = DecisionController([decision], min_confidence=threshold)
    router.decision_retry_enabled = True
    router.decision_min_confidence = threshold
    engine.router = router
    engine.transient_max_retries = 2
    engine.transient_backoff_base_s = 0.0
    return engine


@pytest.mark.asyncio
async def test_retry_decision_can_stop_safe_transient_early():
    decision = _RetryDecision("abort", 0.9)
    engine = _retry_engine(decision)
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        raise TimeoutError("temporary timeout")

    with pytest.raises(RuntimeError, match="DECISION_ABORT"):
        await engine._with_transient_retry("probe", flaky)
    assert calls == 1
    assert decision.calls == 1


@pytest.mark.asyncio
async def test_low_confidence_retry_advice_falls_back_to_existing_retry():
    decision = _RetryDecision("abort", 0.1)
    engine = _retry_engine(decision, threshold=0.5)
    calls = 0

    async def flaky_then_ok():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary timeout")
        return "OK"

    assert await engine._with_transient_retry("probe", flaky_then_ok) == "OK"
    assert calls == 2
    assert decision.calls == 1


@pytest.mark.asyncio
async def test_non_transient_failure_never_queries_retry_model():
    decision = _RetryDecision("retry", 0.99)
    engine = _retry_engine(decision)

    async def bad():
        raise ValueError("content is invalid")

    with pytest.raises(ValueError, match="content is invalid"):
        await engine._with_transient_retry("probe", bad)
    assert decision.calls == 0



class _MappedDecision:
    name = "kev"

    def __init__(self, *, validator="validator.security", confidence=0.9,
                 readiness=3.4, readiness_confidence=0.8):
        self.validator = validator
        self.confidence = confidence
        self.readiness = readiness
        self.readiness_confidence = readiness_confidence
        self.calls = []

    async def decide(self, *, state, questions):
        qid, question = next(iter(questions.items()))
        self.calls.append(qid)
        if qid == "next_validator":
            probs = {key: 0.05 for key in question["criteria"]}
            if self.validator in probs:
                probs[self.validator] = 0.9
            return DecisionBatch(
                provider="kev", model="kev-test",
                answers={qid: {
                    "type": "choice", "choice": self.validator,
                    "confidence": self.confidence, "probabilities": probs,
                }},
            )
        if qid == "candidate_readiness":
            return DecisionBatch(
                provider="kev", model="kev-test",
                answers={qid: {
                    "type": "score", "score": self.readiness,
                    "confidence": self.readiness_confidence,
                    "probabilities": {"0": 0.02, "1": 0.03, "2": 0.1, "3": 0.35, "4": 0.5},
                }},
            )
        raise AssertionError(qid)


def _decision_engine(provider, *, threshold=0.35):
    from orchestrator.engine import OMAEngine

    engine = OMAEngine.__new__(OMAEngine)
    router = ModelRouter({"primary": _Agent("PRIMARY")}, fallback_provider_name=None)
    router.decision_controller = DecisionController([provider], min_confidence=threshold)
    router.decision_validator_selection_enabled = True
    router.decision_quality_advisory_enabled = True
    router.decision_min_confidence = threshold
    traces = []
    router.decision_trace_sink = traces.append
    engine.router = router
    return engine, traces


@pytest.mark.asyncio
async def test_validator_selection_adds_one_confident_standby_without_removing_active():
    from orchestrator.models import Task, ValidationReport, ValidatorRole

    provider = _MappedDecision(validator="validator.security", confidence=0.9)
    engine, traces = _decision_engine(provider)
    task = Task(id="T-D", run_id="r", objective="ordinary refactor")
    active = [ValidatorRole.LOGIC, ValidatorRole.REQUIREMENTS, ValidatorRole.ADVERSARIAL]
    expanded = active + [ValidatorRole.EDGE_CASES, ValidatorRole.SECURITY, ValidatorRole.PERFORMANCE]
    reports = [ValidationReport(
        task_id=task.id,
        candidate_id="cand-1",
        validator_role="validator.logic",
        status="DISPUTED",
        confidence=0.6,
        score=7.0,
    )]

    selected = await engine._decision_select_validator_expansion(
        task, active, expanded, reports, "disagreement"
    )
    assert selected == active + [ValidatorRole.SECURITY]
    assert selected[:3] == active
    assert provider.calls == ["next_validator"]
    assert traces[-1]["kind"] == "validator_selection"
    assert set(traces[-1]["deferred"]) == {
        "validator.edge_cases", "validator.performance"
    }


@pytest.mark.asyncio
async def test_validator_selection_low_confidence_keeps_full_deterministic_expansion():
    from orchestrator.models import Task, ValidatorRole

    provider = _MappedDecision(validator="validator.security", confidence=0.1)
    engine, traces = _decision_engine(provider, threshold=0.5)
    task = Task(id="T-D", run_id="r", objective="ordinary refactor")
    active = [ValidatorRole.LOGIC, ValidatorRole.REQUIREMENTS, ValidatorRole.ADVERSARIAL]
    expanded = active + [ValidatorRole.EDGE_CASES, ValidatorRole.SECURITY, ValidatorRole.PERFORMANCE]

    selected = await engine._decision_select_validator_expansion(
        task, active, expanded, [], "Confidence below threshold: 0.4 < 0.75"
    )
    assert selected == expanded
    assert provider.calls == ["next_validator"]
    assert traces == []


@pytest.mark.asyncio
async def test_validator_selection_never_reduces_high_or_critical_task():
    from orchestrator.models import Task, TaskPriority, ValidatorRole

    provider = _MappedDecision()
    engine, traces = _decision_engine(provider)
    active = [ValidatorRole.LOGIC, ValidatorRole.REQUIREMENTS, ValidatorRole.ADVERSARIAL]
    expanded = active + [ValidatorRole.EDGE_CASES, ValidatorRole.SECURITY, ValidatorRole.PERFORMANCE]
    task = Task(
        id="T-C", run_id="r", objective="security change",
        priority=TaskPriority.CRITICAL, risk="CRITICAL",
    )
    selected = await engine._decision_select_validator_expansion(
        task, active, expanded, [], "Confidence below threshold"
    )
    assert selected == expanded
    assert provider.calls == []
    assert traces == []


@pytest.mark.asyncio
async def test_quality_readiness_is_advisory_only_and_traced():
    from orchestrator.models import Candidate, Task, ValidationReport

    provider = _MappedDecision(readiness=3.4, readiness_confidence=0.81)
    engine, traces = _decision_engine(provider)
    task = Task(id="T-Q", run_id="r", objective="candidate")
    candidate = Candidate(task_id=task.id, run_id="r", candidate_id="cand-q")
    reports = [ValidationReport(
        task_id=task.id,
        candidate_id=candidate.candidate_id,
        validator_role="validator.logic",
        status="APPROVED",
        confidence=0.95,
        score=9.8,
    )]
    advisory = await engine._decision_quality_advisory(
        task, candidate, reports,
        {"all_passed": True, "checks_ran": 4, "failed_commands": []},
        False,
        "Quorum not met: received 1/3 reports.",
    )
    assert advisory["score"] == pytest.approx(3.4)
    assert advisory["confidence"] == pytest.approx(0.81)
    assert advisory["deterministic_gate_passed"] is False
    assert advisory["authoritative"] is False
    assert traces[-1]["kind"] == "quality_readiness"
    assert traces[-1]["deterministic_gate_passed"] is False



@pytest.mark.asyncio
async def test_engine_persists_decision_advisory_event(tmp_path):
    from orchestrator.engine import OMAEngine
    from orchestrator.events import EventType

    primary = _Agent("PRIMARY")
    cheap = _Agent("CHEAP")
    router = ModelRouter(
        {"primary": primary, "cheap": cheap},
        primary_provider_name="primary",
        fallback_provider_name=None,
    )
    router.decision_controller = DecisionController([_Decision("cheap", 0.9)])
    router.decision_routing_enabled = True

    engine = OMAEngine(
        run_id="decision-event",
        objective="test decision telemetry",
        workspace_path=tmp_path,
        router=router,
        max_parallel_workers=1,
        max_rounds=1,
        no_progress_limit=1,
        transient_backoff_base_s=0,
    )

    response = await engine.router.execute(
        AgentRequest(
            system_prompt="s",
            user_prompt="simple low-risk task",
            role="executor",
            metadata={"task_id": "T-1", "candidate_id": "C-1"},
        )
    )
    assert response.content == "CHEAP"

    advisories = [
        event for event in engine.persistence.load_events()
        if event.event_type == EventType.DECISION_ADVISORY
    ]
    assert len(advisories) == 1
    event = advisories[0]
    assert event.task_id == "T-1"
    assert event.candidate_id == "C-1"
    assert event.producer == "decisioning"
    assert event.payload["baseline"] == "primary"
    assert event.payload["selected"] == "cheap"
    assert event.payload["source"] == "kev"



@pytest.mark.asyncio
async def test_executor_propagates_task_priority_and_risk_to_router():
    from orchestrator.agents.executor import ExecutorAgent
    from orchestrator.models import Task, TaskPriority

    class Capture:
        request = None

        async def execute(self, request, preferred_provider=None):
            self.request = request
            return AgentResponse(
                content="BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: ok\nPATCH:\nVALIDATION_COMMANDS:\nEND_RESULT"
            )

    capture = Capture()
    task = Task(
        id="T-CRIT", run_id="r", objective="critical change",
        priority=TaskPriority.CRITICAL, risk="CRITICAL",
    )
    await ExecutorAgent(capture).execute_task(task)
    assert capture.request.metadata["priority"] == "CRITICAL"
    assert capture.request.metadata["risk"] == "CRITICAL"


@pytest.mark.asyncio
async def test_validator_propagates_task_priority_and_risk_to_router():
    from orchestrator.agents.validators import SpecializedValidator
    from orchestrator.models import Candidate, Task, TaskPriority, ValidatorRole

    class Capture:
        request = None

        async def execute(self, request, preferred_provider=None):
            self.request = request
            return AgentResponse(
                content="",
                structured_data={
                    "status": "APPROVED",
                    "confidence": 0.96,
                    "score": 9.8,
                    "summary": "ok",
                    "findings": [],
                    "requirements_checked": [],
                },
            )

    capture = Capture()
    task = Task(
        id="T-HIGH", run_id="r", objective="sensitive change",
        priority=TaskPriority.HIGH, risk="HIGH",
    )
    candidate = Candidate(task_id=task.id, run_id="r", candidate_id="cand-high")
    report = await SpecializedValidator(
        ValidatorRole.SECURITY, capture, require_explicit_scores=True
    ).validate(task, candidate, {"all_passed": True, "results": []})
    assert report.ran is True
    assert capture.request.metadata["priority"] == "HIGH"
    assert capture.request.metadata["risk"] == "HIGH"
