"""Scripted/local integration; deliberately no live ChatGPT traffic."""
import asyncio
import json
import time

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.conversation_pool import FixedConversationRouter
from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.providers.extension_provider import BrowserExtensionProvider


def request(role="executor", task="T1"):
    return AgentRequest("current instructions " + role, "work on " + task,
                        role=role, metadata={"task_id": task})


class ChatProvider:
    persistent_conversations = True

    def __init__(self):
        self.calls, self.starts, self.adopted = [], [], []
        self.created = 0

    def adopt_conversations(self, urls):
        self.adopted.extend(urls)

    async def execute(self, req):
        self.calls.append(req)
        self.starts.append(time.monotonic())
        await asyncio.sleep(.005)
        url = req.metadata.get("conversation_url")
        if req.metadata.get("new_chat", True):
            self.created += 1
            url = f"https://chatgpt.com/c/chat-{self.created}"
        return AgentResponse(content="done", metadata={"conversation_url": url,
                             "conversation_id": url.rsplit("/", 1)[-1], "delivery_state": "CONFIRMED"})


def pool_for(path, provider, delay=0, **kwargs):
    return FixedConversationRouter(ModelRouter({"primary": provider}, fallback_provider_name=None),
                                   "R1", path, delay, **kwargs)


async def test_concurrent_roles_are_paced_and_five_seats_include_planner_repair_judge(tmp_path):
    provider = ChatProvider()
    pool = pool_for(tmp_path, provider, .05, max_seats=5)
    roles = ["planner", "executor", "validator.logic", "validator.requirements",
             "validator.adversarial", "repair", "judge", "master", "executor"]
    results = await asyncio.gather(*(pool.execute(request(role, f"T{i}")) for i, role in enumerate(roles)))
    assert all(r.success for r in results)
    assert provider.created == 5 and len(pool.seats()) == 5
    assert all(b - a >= .045 for a, b in zip(provider.starts, provider.starts[1:]))
    assert provider.calls[5].metadata["conversation_url"] == results[1].metadata["conversation_url"]
    assert provider.calls[6].metadata["conversation_url"] == results[0].metadata["conversation_url"]
    assert "current instructions repair" in provider.calls[5].system_prompt
    assert all("OMA TASK BOUNDARY" in r.system_prompt for r in provider.calls)
    blocked = await pool.execute(request("validator.security"))
    assert not blocked.success and provider.created == 5


async def test_gateway_rounds_persist_first_url_keep_key_and_obey_pacing(tmp_path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "app.py").write_text("ANSWER = 42\n")
    state = tmp_path / "state"

    class Reader(ChatProvider):
        async def execute(self, req):
            stored = json.loads((state / "conversations.json").read_text())
            seat = stored["seats"]["R1:executor"]
            assert seat["state"] == "IN_FLIGHT"
            if self.calls:
                assert seat["url"] == "https://chatgpt.com/c/chat-1"
                assert "ANSWER = 42" in req.user_prompt
                assert req.metadata["refresh_system_prompt"] is False
            result = await super().execute(req)
            if len(self.calls) == 1:
                result.content = "[[R|app.py|1|1]]"
            return result

    provider = Reader()
    pool = pool_for(state, provider, .08)
    with pool.repository_scope(source):
        result = await pool.execute(request())
    assert result.success and result.metadata["repository_commands"] == 1
    assert provider.created == 1 and len(provider.calls) == 2
    assert {r.metadata["conversation_key"] for r in provider.calls} == {"R1:executor"}
    assert provider.starts[1] - provider.starts[0] >= .075
    assert pool.seats()["R1:executor"]["state"] == "CONFIRMED"


async def test_restart_reuses_chat_and_carries_last_dispatch_delay(tmp_path):
    first = ChatProvider()
    await pool_for(tmp_path, first, .12).execute(request())
    second = ChatProvider()
    result = await pool_for(tmp_path, second, .12).execute(request("repair", "T2"))
    assert result.success and second.created == 0
    assert second.starts[0] - first.starts[0] >= .115
    assert second.adopted == ["https://chatgpt.com/c/chat-1"]


async def test_cancelled_send_blocks_only_its_own_seat_without_replay(tmp_path):
    # Bloqueio é POR ASSENTO, não global: um envio incerto nunca é repetido
    # automaticamente, mas assentos saudáveis seguem (travar a run inteira por
    # 1 tab converte soluço local em stall total, visto em run live).
    entered = asyncio.Event()

    class Hanging(ChatProvider):
        async def execute(self, req):
            entered.set()
            await asyncio.Event().wait()

    pool = pool_for(tmp_path, Hanging())
    task = asyncio.create_task(pool.execute(request()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    provider = ChatProvider()
    resumed = pool_for(tmp_path, provider)
    assert resumed.seats()["R1:executor"]["state"] == "UNCERTAIN"
    # O próprio assento travado nunca reenvia sozinho...
    for _ in range(2):
        result = await resumed.execute(request())
        assert not result.success and "reconciliation" in result.error
    assert provider.calls == []
    # ...mas outro assento saudável prossegue normalmente.
    other = await resumed.execute(request("validator.logic"))
    assert other.success
    assert [c.role for c in provider.calls] == ["validator.logic"]


async def test_two_router_instances_cannot_send_from_same_store_concurrently(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class Waiting(ChatProvider):
        async def execute(self, req):
            entered.set()
            await release.wait()
            return await super().execute(req)

    provider = Waiting()
    first = pool_for(tmp_path, provider)
    second_provider = ChatProvider()
    second = pool_for(tmp_path, second_provider)
    task = asyncio.create_task(first.execute(request()))
    await entered.wait()
    blocked = await second.execute(request())
    assert not blocked.success and second_provider.calls == []
    release.set()
    assert (await task).success
    assert (await second.execute(request("repair", "T2"))).success
    assert second_provider.created == 0


@pytest.mark.parametrize("content", ['{', '[]', '{"R2:executor": {}}',
    '{"R1:executor": {"url": "https://evil.example/c/a", "conversation_id": "a"}}'])
def test_corrupt_or_foreign_map_fails_closed(tmp_path, content):
    path = tmp_path / "conversations.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="conversation"):
        pool_for(tmp_path, ChatProvider())
    assert path.read_text() == content


def test_ambiguous_legacy_repair_chat_requires_operator_not_silent_migration(tmp_path):
    original = {f"R1:{role}": {"url": f"https://chatgpt.com/c/{role}", "conversation_id": role}
                for role in ("executor", "repair")}
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="ambiguous legacy"):
        pool_for(tmp_path, ChatProvider())
    assert json.loads(path.read_text()) == original


async def test_unambiguous_legacy_map_migrates_only_on_dispatch(tmp_path):
    path = tmp_path / "conversations.json"
    original = {"R1:planner": {"url": "https://chatgpt.com/c/legacy", "conversation_id": "legacy"}}
    path.write_text(json.dumps(original))
    provider = ChatProvider()
    pool = pool_for(tmp_path, provider)
    assert json.loads(path.read_text()) == original
    assert (await pool.execute(request("master"))).success
    assert provider.created == 0
    assert json.loads(path.read_text())["schema_version"] == 2


async def test_write_failure_before_send_stops_without_provider_call(tmp_path, monkeypatch):
    provider = ChatProvider()
    pool = pool_for(tmp_path, provider)

    def broken_save():
        raise OSError("disk full")

    monkeypatch.setattr(pool, "_save", broken_save)
    result = await pool.execute(request())
    assert not result.success and "intent" in result.error
    assert provider.calls == []


async def test_write_failure_after_send_leaves_durable_intent_and_prevents_restart_replay(tmp_path, monkeypatch):
    provider = ChatProvider()
    pool = pool_for(tmp_path, provider)
    original = pool._save
    calls = 0

    def fail_result():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("disk full after send")
        original()

    monkeypatch.setattr(pool, "_save", fail_result)
    result = await pool.execute(request())
    assert not result.success and len(provider.calls) == 1
    resumed = pool_for(tmp_path, provider)
    assert resumed.seats()["R1:executor"]["state"] == "IN_FLIGHT"
    assert not (await resumed.execute(request())).success
    assert len(provider.calls) == 1


@pytest.mark.parametrize("kind", ["exception", "missing_url", "wrong_id", "quota", "uncertain"])
async def test_delivery_failures_block_fallback_and_further_chats(tmp_path, kind):
    class Broken(ChatProvider):
        async def execute(self, req):
            if kind == "exception":
                raise TimeoutError("browser stalled")
            if kind == "missing_url":
                return AgentResponse(content="done")
            if kind in {"quota", "uncertain"}:
                return AgentResponse(content="", success=False, error=kind,
                                     metadata={"delivery_state": "BLOCKED" if kind == "quota" else "UNCERTAIN"})
            return AgentResponse(content="done", metadata={"conversation_url": "https://chatgpt.com/c/a",
                                                            "conversation_id": "b"})

    broken, fallback = Broken(), ChatProvider()
    calls = []
    _inner = broken.execute
    async def tracked(req):
        calls.append(req.role)
        return await _inner(req)
    broken.execute = tracked
    pool = FixedConversationRouter(ModelRouter({"primary": broken, "fallback": fallback}), "R1", tmp_path)
    assert not (await pool.execute(request())).success
    # Assento saudável não é bloqueado pelo assento travado: a chamada CHEGA ao
    # provider (falha pelo provider quebrado, não por bloqueio global)...
    second = await pool.execute(request("master"))
    assert not second.success
    assert "reconciliation" not in (second.error or "")
    assert "master" in calls
    # ...e o fallback jamais é acionado para entregas incertas do assento travado.
    assert fallback.calls == []


async def test_continuation_cannot_move_to_another_provider(tmp_path):
    first, second = ChatProvider(), ChatProvider()
    pool = FixedConversationRouter(ModelRouter({"primary": first, "other": second}), "R1", tmp_path)
    assert (await pool.execute(request())).success
    result = await pool.execute(request("repair"), preferred_provider="other")
    assert not result.success and second.calls == []


async def test_provider_refreshes_system_only_at_logical_task_boundary(monkeypatch):
    provider = BrowserExtensionProvider()
    url = "https://chatgpt.com/c/existing"
    provider.adopt_conversations([url])
    sent = []

    async def submit_chat(**kwargs):
        sent.append(kwargs)
        return {"status": "COMPLETED", "result": "ok", "conversation_url": url,
                "conversation_id": "existing"}

    monkeypatch.setattr(provider.transport, "submit_chat", submit_chat)
    req = request("repair")
    req.metadata.update(new_chat=False, conversation_url=url, refresh_system_prompt=True)
    assert (await provider.execute(req)).success
    assert req.system_prompt in sent[0]["prompt"]
    req.metadata["refresh_system_prompt"] = False
    req.user_prompt = '{"type":"UNTRUSTED_REPOSITORY_RESULTS"}'
    assert (await provider.execute(req)).success
    assert sent[1]["prompt"] == req.user_prompt


async def test_browser_exception_without_pool_does_not_fallback():
    class TimedOut(ChatProvider):
        async def execute(self, req):
            raise TimeoutError("backstop timeout")

    fallback = ChatProvider()
    router = ModelRouter({"primary": TimedOut(), "fallback": fallback})
    response = await router.execute(request())
    assert not response.success and response.metadata["delivery_state"] == "UNCERTAIN"
    assert fallback.calls == []


async def test_budget_rejection_happens_before_intent_and_send(tmp_path):
    from orchestrator.budgets import TokenBudget
    provider = ChatProvider()
    pool = pool_for(tmp_path, provider)
    pool.budget = TokenBudget(1, 1)
    response = await pool.execute(request())
    assert not response.success and "BUDGET_EXCEEDED" in response.error
    assert provider.calls == [] and pool.seats() == {}
    assert not (tmp_path / "conversations.json").exists()


def test_read_only_status_reports_crash_without_changing_state(tmp_path):
    from orchestrator.conversation_pool import inspect_conversations
    path = tmp_path / "conversations.json"
    content = json.dumps({"schema_version": 2, "run_id": "R1", "last_dispatch_at": time.time(),
                          "seats": {"R1:executor": {"state": "IN_FLIGHT"}}})
    path.write_text(content)
    result = inspect_conversations(tmp_path, "R1")
    assert result["state"] == "BLOCKED" and result["blocked_seats"] == ["R1:executor"]
    assert path.read_text() == content
    assert not (tmp_path / "conversations.lock").exists()


async def test_killed_process_leaves_intent_and_releases_os_lock_without_replay(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    # Trusted local fixture: no relay, browser, or model connection.
    script = '''
import asyncio, sys
from orchestrator.agents.router import ModelRouter
from orchestrator.conversation_pool import FixedConversationRouter
from orchestrator.providers.base import AgentRequest
class Hanging:
    persistent_conversations = True
    async def execute(self, request):
        await asyncio.Event().wait()
async def main():
    router = ModelRouter({"primary": Hanging()}, fallback_provider_name=None)
    pool = FixedConversationRouter(router, "R1", sys.argv[1])
    await pool.execute(AgentRequest("s", "u", role="executor"))
asyncio.run(main())
'''
    child = subprocess.Popen([sys.executable, "-B", "-c", script, str(tmp_path)],
                             cwd=Path(__file__).resolve().parents[2],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        path = tmp_path / "conversations.json"
        deadline = time.monotonic() + 20
        while not path.exists() and time.monotonic() < deadline and child.poll() is None:
            await asyncio.sleep(.02)
        assert path.exists(), "child did not persist intent"
        assert json.loads(path.read_text())["seats"]["R1:executor"]["state"] == "IN_FLIGHT"
    finally:
        if child.poll() is None:
            child.kill()  # Only the subprocess created by this test.
        child.communicate(timeout=5)
    provider = ChatProvider()
    resumed = pool_for(tmp_path, provider)
    response = await resumed.execute(request())
    assert not response.success and "reconciliation" in response.error
    assert provider.calls == []


def test_delivery_controls_require_external_protected_promotion():
    from repository.policy import PROTECTED_COMPONENTS
    assert {"orchestrator/conversation_pool.py", "orchestrator/compute_policy.py",
            "orchestrator/providers/extension_provider.py", "repository/agent_loop.py",
            "browser/outcomes.py"} <= PROTECTED_COMPONENTS
