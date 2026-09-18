"""Smoke LIVE do bot browser (`--provider browser`) — opt-in, sem enviar mensagem.

Setup:
  1. Edge real instalado com perfil persistente (fora do OneDrive, sem symlink).
  2. Login no chatgpt.com já feito nesse perfil (o teste só CHECA, nunca loga).
  3. OMA_LIVE_BROWSER=1 pytest tests/e2e/test_browser_bot_live.py -s

Sem isso: SKIP com motivo claro (mesmo padrão dos outros testes live do projeto).
O teste abre o bot, checa login e fecha SEM enviar nenhuma mensagem:
nenhum send_prompt/ask/submit é chamado em nenhum caminho.
"""
from __future__ import annotations

import os

import pytest

LIVE = os.environ.get("OMA_LIVE_BROWSER") == "1"


@pytest.mark.skipif(not LIVE, reason="Requer Edge real logado no chatgpt.com (OMA_LIVE_BROWSER=1)")
@pytest.mark.asyncio
async def test_browser_bot_login_smoke_no_send():
    """Abre o bot, prova que a sessão está logada e fecha sem enviar nada."""
    from browser.session import BrowserSession

    session = BrowserSession(role="smoke")
    sent = []

    # Guarda de honestidade: se qualquer envio for tentado, o teste falha alto.
    orig_ask = session.ask

    async def _no_send(*args, **kwargs):
        sent.append((args, kwargs))
        raise AssertionError("smoke test must never send a message")

    session.ask = _no_send  # type: ignore[method-assign]
    try:
        await session.initialize()
        assert session.page is not None, "bot não abriu nenhuma página"
        assert session.adapter is not None, (
            "bot offline (Edge indisponível e sem CDP); faça login no perfil persistente")
        assert session.is_live is True

        page = session.page
        url = ""
        try:
            url = page.url or ""
        except Exception:
            url = ""
        assert "chatgpt.com" in url, f"bot fora do alvo oficial, url={url!r}"

        # Checagem de login sem enviar nada: composer precisa existir e não pode
        # haver parede de login. Qualquer dúvida falha alto (sem fingir logado).
        login_wall = ""
        try:
            content = await page.content()
            login_wall = content[:2000].lower()
        except Exception:
            content = ""
        assert "log in" not in login_wall or "composer" in login_wall or "prompt" in login_wall, (
            "parede de login detectada; entre no chatgpt.com no perfil do bot e repita")
        composer = page.get_by_role("textbox")
        try:
            has_composer = await composer.count() > 0
        except Exception:
            has_composer = False
        if not has_composer:
            try:
                fallback = page.locator("#prompt-textarea, textarea, [contenteditable='true']")
                has_composer = await fallback.count() > 0
            except Exception:
                has_composer = False
        assert has_composer, "composer do chatgpt.com ausente (login exigido ou DOM alterado)"
        assert sent == [], "nenhuma mensagem poderia ter sido enviada"
        print(f"\n[LIVE] bot logado ok, url={url} (nada enviado)")
    finally:
        session.ask = orig_ask  # type: ignore[method-assign]
        try:
            await session.close()
        except Exception:
            pass
        assert sent == [], "smoke test enviou mensagem no teardown (proibido)"
