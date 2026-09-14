"""Local protocol integration with scripted responses, not a live-browser claim."""
import asyncio
import json

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.models import TokenUsage
from orchestrator.providers.base import AgentRequest, AgentResponse
from repository.agent_loop import AgentToolLoop
from repository.gateway import CommandGateway


async def test_worker_reads_code_and_receives_result_without_master(tmp_path):
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n")

    class Worker:
        def __init__(self):
            self.turns = []

        async def execute(self, request):
            self.turns.append(request)
            if len(self.turns) == 1:
                return AgentResponse(content="[[R|app.py|1|2]]", token_usage=TokenUsage(10, 4))
            data = json.loads(request.user_prompt)
            assert "return a + b" in data["results"][0]["data"]
            assert "F01" in data["results"][0]["data"]
            assert len(request.metadata["messages"]) == 4
            return AgentResponse(content="FINAL_VALIDATED_WORKER_ANSWER", token_usage=TokenUsage(20, 5))

    class Master:
        async def execute(self, request):
            raise AssertionError("central/master must not be called for repository reads")

    worker = Worker()
    router = ModelRouter({"primary": worker, "master": Master()}, fallback_provider_name=None)
    with router.repository_scope(tmp_path):
        response = await router.execute(AgentRequest("implement", "read add", role="executor",
                                                   metadata={"task_id": "T-1"}))
    assert response.success and response.content == "FINAL_VALIDATED_WORKER_ANSWER"
    assert response.metadata["repository_commands"] == 1
    assert response.token_usage.input_tokens == 30 and response.token_usage.output_tokens == 9
    assert worker.turns[0].metadata["repository_session_id"] == worker.turns[1].metadata["repository_session_id"]


async def test_simultaneous_workers_get_separate_aliases_and_conversations(tmp_path):
    (tmp_path / "a.py").write_text("A = 1\n")
    (tmp_path / "b.py").write_text("B = 2\n")
    gw = CommandGateway(tmp_path)
    seen = {}

    async def provider(request):
        task = request.metadata["task_id"]
        turn = seen.get(task, 0)
        seen[task] = turn + 1
        await asyncio.sleep(.01)
        if not turn:
            return AgentResponse(content=f"[[R|{task}.py]]")
        result = json.loads(request.user_prompt)["results"][0]["data"]
        assert f"{task.upper()} = " in result
        assert "F01" in result
        return AgentResponse(content="done")

    responses = await asyncio.gather(*[
        AgentToolLoop(gw).run(AgentRequest("s", "u", role="executor", metadata={"task_id": task}), provider)
        for task in ("a", "b")])
    assert all(r.success for r in responses)
    assert len({r.metadata["repository_session_id"] for r in responses}) == 2
    assert not gw.sessions.sessions


async def test_model_cannot_write_through_read_dialogue(tmp_path):
    gw = CommandGateway(tmp_path)
    calls = 0

    async def provider(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return AgentResponse(content="[[W|a.py|A01]]")
        assert "DENIED" in request.user_prompt
        return AgentResponse(content="write rejected")

    response = await AgentToolLoop(gw).run(AgentRequest("s", "u", role="executor"), provider)
    assert response.success and not (tmp_path / "a.py").exists()


async def test_embedded_directives_in_examples_are_not_executed(tmp_path):
    gw = CommandGateway(tmp_path)

    async def provider(request):
        return AgentResponse(content="Example:\n```\n[[R|auth.json]]\n```")

    response = await AgentToolLoop(gw).run(AgentRequest("s", "u", role="executor"), provider)
    assert response.success and gw.command_count == 0


async def test_repeat_and_total_round_limits_stop_before_central(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    gw = CommandGateway(tmp_path)

    async def provider(request):
        return AgentResponse(content="[[R|app.py]]")

    request = AgentRequest("s", "u", role="executor")
    response = await AgentToolLoop(gw, max_repeated=2).run(request, provider)
    assert not response.success and "NO_PROGRESS" in response.error
    response = await AgentToolLoop(gw, max_rounds=1).run(request, provider)
    assert not response.success and "DIRECTIVE_LIMIT" in response.error
    assert not gw.sessions.sessions


async def test_loop_cancellation_releases_session(tmp_path):
    gw = CommandGateway(tmp_path)
    started = asyncio.Event()

    async def provider(request):
        started.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(AgentToolLoop(gw).run(AgentRequest("s", "u", role="executor"), provider))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not gw.sessions.sessions
