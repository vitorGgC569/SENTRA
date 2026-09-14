"""Planner: JSON-only hardening, fence-aware parse, bounded retry, fail high.

Regression: live planners once returned structurally complete task JSON with
UNESCAPED inner quotes (e.g. "titulo visivel "SENTRA Teste", secao"), the
first-{-to-last-} slice failed to parse, and the engine SILENTLY fell back to
one task carrying the raw objective. That fallback is gone: no JSON, no plan.
"""
import json

import pytest

from orchestrator.agents.planner import TaskPlanner, _extract_tasks
from orchestrator.providers.base import AgentResponse


def _task(i, deps=()):
    return {"id": f"T-{i:02d}", "objective": f"goal {i}",
            "description": f"do {i}", "dependencies": list(deps),
            "priority": "HIGH", "risk": "LOW", "required_capabilities": [],
            "validation_strategy": "standard", "target_files": []}


def _valid_json(n=2):
    return json.dumps({"tasks": [_task(1)] + [
        _task(i, deps=("T-01",)) for i in range(2, n + 1)]})


# Real observed failure shape: complete structure, unescaped inner quotes.
BROKEN_QUOTES = ('{"tasks": [{"id": "T-01", "objective": "Criar index com '
                 'titulo visivel "SENTRA Teste", secao e rodape", '
                 '"description": "d", "dependencies": [], "priority": "HIGH", '
                 '"risk": "LOW", "required_capabilities": [], '
                 '"validation_strategy": "s", "target_files": []}]}')


class StubRouter:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0

    async def execute(self, request):
        self.calls += 1
        item = self.contents[min(self.calls - 1, len(self.contents) - 1)]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, AgentResponse):
            return item
        if isinstance(item, dict):
            return AgentResponse(content="", structured_data=item)
        return AgentResponse(content=item)


def _planner(contents):
    router = StubRouter(contents)
    planner = TaskPlanner(router)
    return planner, router


def test_extract_prefers_fenced_block():
    body = "claro!\n```json\n" + _valid_json(3) + "\n```\npronto.\n"
    tasks = _extract_tasks(body)
    assert [t["id"] for t in tasks] == ["T-01", "T-02", "T-03"]


def test_extract_rejects_unescaped_inner_quotes():
    with pytest.raises(ValueError):
        _extract_tasks(BROKEN_QUOTES)


def test_retry_then_success_counts_attempts():
    planner, router = _planner(["so texto, sem json", BROKEN_QUOTES,
                                "```json\n" + _valid_json(5) + "\n```"])
    tasks = __import__("asyncio").run(
        planner.plan(run_id="R", objective="obj"))
    assert [t.id for t in tasks] == ["T-01", "T-02", "T-03", "T-04", "T-05"]
    assert router.calls == 3


def test_total_failure_raises_instead_of_fake_single_task():
    planner, router = _planner(["lixo", "mais lixo {incompleto", ""])
    with pytest.raises(RuntimeError, match="planner failed"):
        __import__("asyncio").run(planner.plan(run_id="R", objective="obj"))
    assert router.calls == 3


def test_blocked_seat_fails_fast_without_burning_retries():
    planner, router = _planner([
        _fail(),
        AgentResponse(content="", success=False,
                      error="[CONVERSATION_BLOCKED] R:master requires delivery reconciliation"),
        _valid_json(1),
    ])
    with pytest.raises(RuntimeError, match="CONVERSATION_BLOCKED"):
        __import__("asyncio").run(planner.plan(run_id="R", objective="obj"))
    assert router.calls == 2


def test_structured_data_path_untouched():
    planner, router = _planner([{"tasks": [_task(1)]}])
    tasks = __import__("asyncio").run(
        planner.plan(run_id="R", objective="obj"))
    assert [t.id for t in tasks] == ["T-01"]
    assert router.calls == 1


def test_provider_error_retries_then_succeeds():
    planner, router = _planner([_fail(), _valid_json(1)])
    tasks = __import__("asyncio").run(
        planner.plan(run_id="R", objective="obj"))
    assert [t.id for t in tasks] == ["T-01"]
    assert router.calls == 2


def _fail():
    return AgentResponse(content="", success=False, error="boom")
