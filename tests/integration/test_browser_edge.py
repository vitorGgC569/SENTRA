"""BrowserProvider/Edge integration — chatgpt.com no Edge persistente.

Live-browser assertions (real Edge window) run only when OMA_LIVE_EDGE=1;
otherwise structural + failure-mode tests run deterministically with fakes.
"""
import asyncio
import os

import pytest

from browser.session import BrowserSession
from orchestrator.providers.browser_provider import BrowserProvider
from orchestrator.providers.base import AgentRequest


def test_edge_session_defaults_target_chatgpt_persistent_not_private():
    s = BrowserSession("orchestrator")
    assert s.target_url == "https://chatgpt.com"
    assert s.browser_channel == "msedge"
    assert s.headless is False
    # Persistent profile (not ephemeral/incognito): user_data_dir is a real kept path
    assert "edge-orchestrator" in str(s.user_data_dir) or "edge-" in str(s.user_data_dir)
    assert s.cdp_url is None


def test_edge_session_custom_profile_kept():
    from pathlib import Path
    s = BrowserSession("architect", user_data_dir="browser_profiles/edge-architect",
                       target_url="https://chatgpt.com")
    assert s.user_data_dir == Path("browser_profiles/edge-architect")


@pytest.mark.asyncio
async def test_browser_provider_timeout_taxonomy():
    from tests.support.fake_providers import HangingProvider

    # BrowserProvider with a hanging session double must yield TIMEOUT, not hang
    class HangSession:
        async def ask(self, prompt, timeout_seconds=1):
            await asyncio.sleep(3600)

    provider = BrowserProvider(session=HangSession())
    req = AgentRequest(system_prompt="sys", user_prompt="u", role="executor",
                       timeout=1, metadata={"task_id": "T-edge-1"})
    # BrowserProvider adds +30s grace; bound the test itself
    resp = await asyncio.wait_for(provider.execute(req), timeout=45)
    assert resp.success is False
    assert "TIMEOUT" in (resp.error or "")
    assert "T-edge-1" in (resp.error or "")  # task correlation present


@pytest.mark.asyncio
async def test_browser_provider_empty_response_is_tool_error():
    class EmptySession:
        async def ask(self, prompt, timeout_seconds=5):
            return ""

    provider = BrowserProvider(session=EmptySession())
    req = AgentRequest(system_prompt="s", user_prompt="u", role="executor",
                       timeout=5, metadata={"task_id": "T-edge-2"})
    resp = await provider.execute(req)
    assert resp.success is False
    assert "T-edge-2" in (resp.error or "")


@pytest.mark.asyncio
async def test_browser_provider_cancellation_propagates():
    class HangSession:
        async def ask(self, prompt, timeout_seconds=60):
            await asyncio.sleep(3600)

    provider = BrowserProvider(session=HangSession())
    req = AgentRequest(system_prompt="s", user_prompt="u", role="executor",
                       timeout=60, metadata={"task_id": "T-edge-3"})
    task = asyncio.ensure_future(provider.execute(req))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


LIVE = os.environ.get("OMA_LIVE_EDGE") == "1"


@pytest.mark.skipif(not LIVE, reason="Live Edge test requires OMA_LIVE_EDGE=1 and logged-in Edge profile")
@pytest.mark.asyncio
async def test_live_edge_chatgpt_roundtrip():
    """Real validation: persistent Edge -> chatgpt.com -> stable response.

    Requires: Edge installed, profile logged into chatgpt.com, headed mode.
    Run:  OMA_LIVE_EDGE=1 pytest tests/integration/test_browser_edge.py -k live_edge -s
    """
    s = BrowserSession("live-probe", headless=False,
                       user_data_dir="browser_profiles/edge-orchestrator",
                       target_url="https://chatgpt.com")
    await s.initialize()
    assert s.is_live, "Edge did not connect; login/profile may be missing"
    try:
        answer = await asyncio.wait_for(
            s.ask("Responda exatamente: EDGE_LIVE_OK", timeout_seconds=120), timeout=180
        )
        assert "EDGE_LIVE_OK" in answer
    finally:
        await s.close()
