"""BrowserExtensionProvider contra relay REAL (localhost) — nenhuma extensão simulada.

Regra do projeto: nada simulado. Portanto:
- timeout / cancelamento: exercem o caminho real (transport + relay de verdade,
  sem extensão conectada) e são determinísticos;
- roundtrip ponta a ponta: exige a extensão REAL conectada ao relay
  (Edge + extensão carregada) + OMA_LIVE_EXTENSION=1. Sem isso, SKIP —
  nunca fake. Ver edge_extension/README.md para subir o lado real.
"""
import asyncio

import pytest

from native_bridge.relay import RelayServer
from orchestrator.providers.base import AgentRequest
from orchestrator.providers.extension_provider import BrowserExtensionProvider


@pytest.fixture
def relay():
    # Bind an ephemeral loopback port so an aborted prior test process cannot
    # leave a stale relay/token on a fixed port and contaminate this fixture.
    server = RelayServer(port=0).start()
    server.base_url = f"http://127.0.0.1:{server.server.server_address[1]}"
    yield server
    server.stop()


def _agent_request(task_id="T-ext-1", timeout=10):
    return AgentRequest(system_prompt="sys role", user_prompt="do task",
                        role="executor", timeout=timeout,
                        metadata={"task_id": task_id})


@pytest.mark.asyncio
async def test_provider_fast_fail_clear_message_when_no_extension(relay):
    """Caminho real: sem worker jamais visto, falha rápido e claro (TOOL_ERROR),
    sem queimar o timeout inteiro do job."""
    import time as _t
    provider = BrowserExtensionProvider(relay_base=relay.base_url, token=relay.token)
    start = _t.time()
    resp = await provider.execute(_agent_request(task_id="T-ext-2", timeout=60))
    elapsed = _t.time() - start
    assert resp.success is False
    assert "TOOL_ERROR" in (resp.error or "")
    assert "no extension connected" in (resp.error or "")
    assert "T-ext-2" in (resp.error or "")
    assert elapsed < 30  # graça de 15s, não os 60s do job


@pytest.mark.asyncio
async def test_lazy_pool_leader_counts_as_connected_before_first_tab(relay):
    import json
    import urllib.request
    from browser.extension_transport import ExtensionTransport

    body = json.dumps({"instance_id": "POOL-integration-lazy"}).encode("utf-8")
    request = urllib.request.Request(
        relay.base_url + "/workers/pool-claim",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + relay.token,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request) as response:
        claimed = json.loads(response.read())
    assert claimed["leader"] is True

    transport = ExtensionTransport(
        relay_base=relay.base_url,
        token=relay.token,
    )
    await transport._wait_first_worker(0.1)
    health = await transport.health()
    assert health["workers_ever_seen"] == 0
    assert health["workers_online"] == []
    assert health["pool"]["active"] is True


@pytest.mark.asyncio
async def test_relay_health_reports_workers(relay):
    import urllib.request, json
    with urllib.request.urlopen(urllib.request.Request(relay.base_url + "/jobs/poll?worker=TAB-9", headers={"Authorization": "Bearer " + relay.token})) as r:
        json.loads(r.read())
    with urllib.request.urlopen(relay.base_url + "/health") as r:
        h = json.loads(r.read())
    assert h["workers_ever_seen"] >= 1
    assert "TAB-9" in h["workers_online"]


def test_provider_adopts_only_well_formed_urls():
    provider = BrowserExtensionProvider(relay_base="http://127.0.0.1:18765")
    n = provider.adopt_conversations([
        "https://chatgpt.com/c/abc-123",
        "https://attacker.example/c/123",
        "not-a-url",
        None,
        "https://chatgpt.com/c/abc-123",  # duplicada não conta 2x
    ])
    assert n == 1
    assert provider.adopted_urls == {"https://chatgpt.com/c/abc-123"}


def test_provider_conversation_registry_is_bounded():
    provider = BrowserExtensionProvider(relay_base="http://127.0.0.1:18765")
    provider.MAX_CONVERSATIONS = 10
    for i in range(25):
        provider._remember(f"T-{i}", {"conversation_id": f"c{i}"})
    assert len(provider.conversations) == 10
    assert "T-24" in provider.conversations  # mais recentes preservadas
    assert "T-0" not in provider.conversations  # antigas removidas (FIFO)


@pytest.mark.asyncio
async def test_provider_cancellation_propagates(relay):
    provider = BrowserExtensionProvider(relay_base=relay.base_url, token=relay.token)
    task = asyncio.ensure_future(provider.execute(_agent_request(task_id="T-ext-3", timeout=120)))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_provider_rejects_unreachable_relay():
    provider = BrowserExtensionProvider(relay_base="http://127.0.0.1:19999")
    resp = await provider.execute(_agent_request(task_id="T-ext-4", timeout=5))
    assert resp.success is False
    assert "TOOL_ERROR" in (resp.error or "")
