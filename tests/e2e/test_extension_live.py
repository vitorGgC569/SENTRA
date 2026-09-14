"""Roundtrip REAL ponta a ponta — SOMENTE com a extensão de verdade conectada.

Setup (edge_extension/README.md):
  1. Relay rodando: python -m native_bridge.relay (ou via fixture OMAEngine)
  2. Edge com a extensão OMA Browser Bridge carregada (modo desenvolvedor)
  3. OMA_LIVE_EXTENSION=1 pytest tests/e2e/test_extension_live.py -s

Sem isso: SKIP. Nenhuma extensão simulada em nenhum teste do projeto.
"""
import os

import pytest

from native_bridge.relay import RelayServer
from orchestrator.providers.base import AgentRequest
from orchestrator.providers.extension_provider import BrowserExtensionProvider

LIVE = os.environ.get("OMA_LIVE_EXTENSION") == "1"


@pytest.mark.skipif(not LIVE, reason="Requer extensão Edge real conectada (OMA_LIVE_EXTENSION=1)")
@pytest.mark.asyncio
async def test_live_extension_roundtrip_creates_real_conversation():
    # Use the already authenticated/paired operational relay. Do not steal its port
    # or replace its token with an ephemeral test server.
    server = None
    try:
        provider = BrowserExtensionProvider(relay_base="http://127.0.0.1:8765")
        req = AgentRequest(
            system_prompt="Responda exatamente com: EXTENSION_LIVE_OK",
            user_prompt="Responda exatamente com: EXTENSION_LIVE_OK",
            role="executor", timeout=240, metadata={"task_id": "T-live-ext-1"})
        resp = await provider.execute(req)
        assert resp.success is True, f"extensão falhou: {resp.error}"
        assert "EXTENSION_LIVE_OK" in resp.content
        conv = provider.conversations["T-live-ext-1"]
        assert conv["conversation_url"], "extensão real deve reportar a URL da conversa"
        print(f"\n[LIVE] conversa real: {conv['conversation_url']} worker={conv['worker']}")
    finally:
        if server is not None:
            server.stop()
