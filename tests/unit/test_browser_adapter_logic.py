"""Lógica do adapter browser/Playwright (AGENTE D, sem quebrar nada).

Cobre com doubles MÍNIMOS só na borda Playwright (page fake):
- detecção de conclusão: stop-sumiu em TODAS as camadas + texto-estabiliza
  (hash) via ResponseCapture real, incluindo guarda de baseline e heartbeat;
- seletores em camadas do ChatSiteAdapter real (fallback composer/send/stop);
- classificação de erro (browser_provider + classify_adapter_error).

Lógica pura (hash de estabilidade, fallback, timeouts) é exercida DE VERDADE;
só a página Playwright é fake, no espírito de tests/support/fake_providers.py
(doubles controlam o outro lado do fio; o código sob teste é o de produção).
"""
from __future__ import annotations

import asyncio

import pytest

from browser.response_capture import ResponseCapture
from browser.site_adapter import (
    ASSISTANT_SELECTORS,
    COMPOSER_SELECTORS,
    SEND_SELECTORS,
    STOP_SELECTORS,
    ChatSiteAdapter,
    ChatSiteAdapterError,
    classify_adapter_error,
    is_additional_checks_message,
)
from orchestrator.providers.base import AgentRequest
from orchestrator.providers.browser_provider import BrowserProvider, _classify_browser_error


# ---------------------------------------------------------------------------
# Doubles mínimos na borda Playwright (só a page; adapter/capture são reais)
# ---------------------------------------------------------------------------

class FakeLocator:
    """Imita playwright Locator/ElementHandle só no que o adapter usa."""

    def __init__(self, page, *, count=1, visible=True, enabled=True,
                 single_text="", wait_raises=None, kind="generic"):
        self._page = page
        self._count = count
        self._visible = visible
        self._enabled = enabled
        self._single_text = single_text
        self._wait_raises = wait_raises
        self._kind = kind

    async def count(self):
        return self._count

    @property
    def first(self):
        return self

    def nth(self, i):
        return FakeLocator(self._page, count=1, visible=self._visible,
                           enabled=self._enabled, single_text=self._single_text,
                           kind=self._kind)

    async def wait_for(self, state="visible", timeout=None):
        self._page.calls.append(("wait_for", state, timeout))
        if self._wait_raises:
            raise self._wait_raises
        if self._count == 0:
            raise TimeoutError("fake: no element matching locator")

    async def scroll_into_view_if_needed(self, timeout=None):
        self._page.calls.append(("scroll", timeout))

    async def focus(self, timeout=None):
        self._page.calls.append(("focus", timeout))

    async def fill(self, text, timeout=None, **kwargs):
        self._page.calls.append(("fill", text))
        self._page.filled.append(text)
        if self._kind == "composer":
            self._page.composer_text = text

    async def evaluate(self, js, arg):
        self._page.calls.append(("evaluate", arg))
        if self._kind == "composer":
            self._page.composer_text = arg

    async def press_sequentially(self, text, delay=None, timeout=None):
        self._page.calls.append(("press_sequentially", text))
        if self._kind == "composer":
            self._page.composer_text = text

    async def press(self, key, timeout=None, **kwargs):
        self._page.calls.append(("press", key))
        self._page.pressed.append(key)
        if key == "Enter":
            self._page.sent = True
            if self._page.clear_on_submit:
                self._page.composer_text = ""

    async def click(self, timeout=None, **kwargs):
        self._page.calls.append(("click",))
        self._page.clicked += 1
        self._page.sent = True
        if self._page.clear_on_submit:
            self._page.composer_text = ""

    async def is_visible(self):
        return self._visible

    async def is_enabled(self):
        return self._enabled

    async def input_value(self):
        if self._kind == "composer":
            return self._page.composer_text
        raise RuntimeError("fake: not an input")

    async def inner_text(self):
        if self._single_text:
            return self._single_text
        if self._kind == "composer":
            return self._page.composer_text
        return ""


class FakePage:
    """Page fake configurável por teste (stop visível? send visível? msgs?)."""

    def __init__(self, *, closed=False, url="https://chatgpt.com/",
                 composer_count=1, send_count=1, send_visible=True,
                 send_enabled=True, stop_count=1, stop_visible=False,
                 messages=None, messages_after_send=None,
                 composer_text="", clear_on_submit=True):
        self._closed = closed
        self.url = url
        self.composer_count = composer_count
        self.send_count = send_count
        self.send_visible = send_visible
        self.send_enabled = send_enabled
        self.stop_count = stop_count
        self.stop_visible = stop_visible
        self.messages = list(messages or [])
        self.messages_after_send = messages_after_send
        self.composer_text = composer_text
        self.clear_on_submit = clear_on_submit
        self.sent = False
        self.calls = []
        self.filled = []
        self.pressed = []
        self.clicked = 0

    def is_closed(self):
        return self._closed

    def get_by_role(self, role, **kwargs):
        assert role == "textbox"
        return FakeLocator(self, count=self.composer_count, kind="composer")

    def _assistant_texts(self):
        if self.sent and self.messages_after_send is not None:
            return self.messages_after_send
        return self.messages

    def locator(self, selector, **kwargs):
        sel = selector or ""
        if ("send-button" in sel or "Send" in sel or "Enviar" in sel
                or "submit" in sel):
            return FakeLocator(self, count=self.send_count,
                               visible=self.send_visible,
                               enabled=self.send_enabled, kind="button")
        if ("stop-button" in sel or "Stop" in sel or "Interromper" in sel
                or "Parar" in sel):
            return FakeLocator(self, count=self.stop_count,
                               visible=self.stop_visible, kind="button")
        if ("assistant" in sel or "message-id" in sel or "markdown" in sel
                or "agent-turn" in sel or "article" in sel):
            texts = self._assistant_texts()
            loc = FakeLocator(self, count=len(texts), kind="message")

            def nth(i, _texts=texts):
                text = _texts[i] if 0 <= i < len(_texts) else ""
                return FakeLocator(self, count=1, visible=True,
                                   single_text=text, kind="message")
            loc.nth = nth  # type: ignore[method-assign]
            return loc
        if ("prompt-textarea" in sel or 'role="textbox"' in sel
                or "chat-input" in sel or "contenteditable" in sel
                or sel.strip() == "textarea"):
            return FakeLocator(self, count=self.composer_count, kind="composer")
        return FakeLocator(self, count=0)

    async def goto(self, url, **kwargs):
        self.calls.append(("goto", url))
        self.url = url

    async def bring_to_front(self):
        self.calls.append(("bring_to_front",))

    # O submit (click/Enter) marca "enviado": o locator de mensagens passa
    # a devolver messages_after_send, simulando o turno novo do chat real.


def _req(**kw):
    base = dict(system_prompt="sys", user_prompt="diga oi",
                role="executor", timeout=30, metadata={"task_id": "T-1"})
    base.update(kw)
    return AgentRequest(**base)


def _fast_capture_kwargs(**kw):
    # poll curto acelera o unit sem mudar a lógica (default real é 1.5s).
    out = dict(poll_interval_s=0.05, heartbeat_interval_s=3600.0)
    out.update(kw)
    return out


# ---------------------------------------------------------------------------
# Seletores em camadas existem (contrato anti single-point-of-failure)
# ---------------------------------------------------------------------------

def test_selector_layers_are_nonempty():
    assert len(COMPOSER_SELECTORS) >= 3
    assert len(SEND_SELECTORS) >= 2
    assert len(STOP_SELECTORS) >= 2
    assert len(ASSISTANT_SELECTORS) >= 2
    assert COMPOSER_SELECTORS[0] == "#prompt-textarea"
    assert SEND_SELECTORS[0] == "button[data-testid='send-button']"
    assert STOP_SELECTORS[0] == "button[data-testid='stop-button']"


# ---------------------------------------------------------------------------
# Detecção de conclusão: stop-sumiu em todas as camadas (+ texto estabiliza)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_visible_means_generating():
    adapter = ChatSiteAdapter(FakePage(stop_count=1, stop_visible=True))
    assert await adapter.is_generation_finished() is False


@pytest.mark.asyncio
async def test_stop_gone_means_finished():
    adapter = ChatSiteAdapter(FakePage(stop_count=0, stop_visible=False))
    assert await adapter.is_generation_finished() is True
    adapter = ChatSiteAdapter(FakePage(stop_count=1, stop_visible=False))
    assert await adapter.is_generation_finished() is True


@pytest.mark.asyncio
async def test_page_dying_mid_poll_reports_unfinished():
    class DyingPage(FakePage):
        def locator(self, selector, **kwargs):
            raise RuntimeError("context destroyed")
    adapter = ChatSiteAdapter(DyingPage())
    # Nunca mente "finished" quando a página morreu: o chamador dá TIMEOUT real.
    assert await adapter.is_generation_finished() is False


@pytest.mark.asyncio
async def test_stable_text_and_finished_returns_response():
    texts = ["parcial", "quase lá", "final!", "final!", "final!", "final!"]
    state = {"i": 0}

    async def extract():
        idx = min(state["i"], len(texts) - 1)
        state["i"] += 1
        return texts[idx]

    finished_calls = {"n": 0}

    async def is_finished():
        finished_calls["n"] += 1
        return state["i"] >= 2  # geração "termina" cedo; estabilidade decide

    out = await ResponseCapture.wait_for_stable_response(
        extract, is_finished, timeout_seconds=20, stable_samples=2,
        **_fast_capture_kwargs())
    assert out == "final!"
    assert finished_calls["n"] >= 3


@pytest.mark.asyncio
async def test_unstable_text_never_counts_as_stable_and_times_out():
    n = {"i": 0}

    async def extract():
        n["i"] += 1
        return f"mudando-{n['i']}"

    async def is_finished():
        return True  # finished sozinho NÃO basta sem hash estável

    with pytest.raises(TimeoutError, match="stable"):
        await ResponseCapture.wait_for_stable_response(
            extract, is_finished, timeout_seconds=1, stable_samples=2,
            **_fast_capture_kwargs())


@pytest.mark.asyncio
async def test_empty_text_never_counts_as_stable():
    async def extract():
        return ""

    async def is_finished():
        return True

    with pytest.raises(TimeoutError, match="stable"):
        await ResponseCapture.wait_for_stable_response(
            extract, is_finished, timeout_seconds=1, stable_samples=1,
            **_fast_capture_kwargs())


@pytest.mark.asyncio
async def test_baseline_text_never_satisfies_new_turn():
    """Guarda de baseline: turno anterior travado nunca conta como estável."""
    async def extract():
        return "resposta velha"

    async def is_finished():
        return True

    with pytest.raises(TimeoutError, match="stable"):
        await ResponseCapture.wait_for_stable_response(
            extract, is_finished, timeout_seconds=1, stable_samples=1,
            baseline_text="resposta velha", **_fast_capture_kwargs())


@pytest.mark.asyncio
async def test_end_result_marker_still_requires_stability():
    # Mesmo sem stop-sumido, END_RESULT estável resolve (caminho real do capture).
    seq = ["BEGIN_RESULT rascunho", "BEGIN_RESULT ok\nEND_RESULT",
           "BEGIN_RESULT ok\nEND_RESULT", "BEGIN_RESULT ok\nEND_RESULT"]
    it = iter(seq)
    last = {"t": seq[-1]}

    async def extract():
        try:
            last["t"] = next(it)
        except StopIteration:
            pass
        return last["t"]

    async def is_finished():
        return False  # stop nunca some; só END_RESULT+estabilidade resolve

    out = await ResponseCapture.wait_for_stable_response(
        extract, is_finished, timeout_seconds=20, stable_samples=1,
        **_fast_capture_kwargs())
    assert "END_RESULT" in out


@pytest.mark.asyncio
async def test_extract_fn_error_is_treated_as_empty_then_times_out():
    async def extract():
        raise RuntimeError("page hiccup")

    async def is_finished():
        return True

    with pytest.raises(TimeoutError):
        await ResponseCapture.wait_for_stable_response(
            extract, is_finished, timeout_seconds=1, stable_samples=1,
            **_fast_capture_kwargs())


@pytest.mark.asyncio
async def test_heartbeat_reports_waiting_then_reading():
    beats = []

    def on_progress(phase, ts):
        beats.append(phase)

    async def extract():
        return "nova resposta"

    async def is_finished():
        return True

    out = await ResponseCapture.wait_for_stable_response(
        extract, is_finished, timeout_seconds=20, stable_samples=1,
        poll_interval_s=0.05, heartbeat_interval_s=0.0, on_progress=on_progress)
    assert out == "nova resposta"
    assert beats[0] == "waiting" and beats[-1] == "reading"


@pytest.mark.asyncio
async def test_default_poll_interval_is_documented():
    assert ResponseCapture.DEFAULT_POLL_INTERVAL_S == 1.5


# ---------------------------------------------------------------------------
# Fallback de seletores (composer/send) no adapter real
# ---------------------------------------------------------------------------

def _adapter(page, **kw):
    kw.setdefault("composer_timeout_ms", 5000)
    kw.setdefault("submit_accept_timeout_s", 5.0)
    kw.setdefault("generation_start_timeout_s", 0.3)
    return ChatSiteAdapter(page, **kw)


@pytest.mark.asyncio
async def test_send_uses_composer_then_send_button():
    page = FakePage(composer_count=1, send_count=1, send_visible=True,
                    stop_count=1, stop_visible=True, messages=["ok"])
    adapter = _adapter(page)
    await adapter.send_prompt("olá")
    assert page.filled == ["olá"]
    assert page.clicked == 1
    assert page.pressed == []


@pytest.mark.asyncio
async def test_send_falls_back_across_composer_layers():
    # Camada primária ausente no DOM fake parcial: locator("#prompt-textarea")
    # conta 0, mas a camada ARIA responde — o adapter varre até achar.
    page = FakePage(composer_count=1, send_count=0,
                    stop_count=1, stop_visible=True, messages=["ok"])
    seen = []

    orig_locator = page.locator

    def layered(selector, **kwargs):
        seen.append(selector)
        if selector == "#prompt-textarea":
            return FakeLocator(page, count=0, kind="composer")
        return orig_locator(selector, **kwargs)

    page.locator = layered  # type: ignore[method-assign]
    adapter = _adapter(page)
    await adapter.send_prompt("fallback!")
    assert page.filled == ["fallback!"]
    assert COMPOSER_SELECTORS[0] in seen and len(seen) >= 2


@pytest.mark.asyncio
async def test_send_falls_back_to_enter_when_no_send_button():
    page = FakePage(composer_count=1, send_count=0, send_visible=False,
                    stop_count=1, stop_visible=True, messages=["ok"])
    adapter = _adapter(page)
    await adapter.send_prompt("via enter")
    assert page.filled == ["via enter"]
    assert page.pressed == ["Enter"]
    assert page.clicked == 0


@pytest.mark.asyncio
async def test_send_raises_when_composer_missing():
    page = FakePage(composer_count=0, stop_count=0)
    adapter = ChatSiteAdapter(page, composer_timeout_ms=300,
                              submit_accept_timeout_s=0.3,
                              generation_start_timeout_s=0.1)
    with pytest.raises(ChatSiteAdapterError, match="ausente"):
        await adapter.send_prompt("sem composer")


@pytest.mark.asyncio
async def test_send_refuses_closed_page():
    adapter = _adapter(FakePage(closed=True))
    with pytest.raises(ChatSiteAdapterError, match="[Cc]losed|sessao"):
        await adapter.send_prompt("x")


@pytest.mark.asyncio
async def test_send_refuses_login_wall_without_sending():
    page = FakePage(composer_count=1, url="https://chatgpt.com/auth/login")
    adapter = _adapter(page)
    with pytest.raises(ChatSiteAdapterError, match="[Ll]ogin"):
        await adapter.send_prompt("x")
    assert page.filled == [] and page.clicked == 0 and page.pressed == []


@pytest.mark.asyncio
async def test_send_reports_submit_failed_when_never_accepted():
    # Composer nunca esvazia e geração nunca começa: SUBMIT_FAILED alto.
    page = FakePage(composer_count=1, send_count=1, send_visible=True,
                    stop_count=0, clear_on_submit=False)
    adapter = ChatSiteAdapter(page, composer_timeout_ms=2000,
                              submit_accept_timeout_s=0.5,
                              generation_start_timeout_s=0.1)
    with pytest.raises(ChatSiteAdapterError, match="SUBMIT_FAILED"):
        await adapter.send_prompt("preso")


@pytest.mark.asyncio
async def test_extract_last_response_returns_last_message():
    adapter = _adapter(FakePage(messages=["primeira", "última"]))
    assert await adapter.extract_last_response() == "última"


@pytest.mark.asyncio
async def test_extract_last_response_empty_when_no_messages():
    adapter = _adapter(FakePage(messages=[]))
    assert await adapter.extract_last_response() == ""


@pytest.mark.asyncio
async def test_send_and_capture_returns_new_turn_past_baseline():
    # Adapter real + page fake: baseline é o turno velho; após o envio surge
    # texto novo, que estabiliza e é devolvido (guarda de baseline exercida).
    page = FakePage(composer_count=1, send_count=0,
                    stop_count=0, messages=["turno velho"],
                    messages_after_send=["resposta nova"])
    adapter = _adapter(page)
    out = await adapter.send_and_capture("pergunta", timeout_seconds=20,
                                         stable_samples=1, poll_interval_s=0.05,
                                         heartbeat_interval_s=3600.0)
    assert out == "resposta nova"
    assert page.filled == ["pergunta"]  # sem continuação (sem BEGIN_RESULT)


# ---------------------------------------------------------------------------
# Classificação de erro (taxonomias reais do provider e do adapter)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc,code", [
    (asyncio.TimeoutError("deadline"), "TIMEOUT"),
    (TimeoutError("deadline"), "TIMEOUT"),
    (RuntimeError("page closed unexpectedly"), "NETWORK_ERROR"),
    (RuntimeError("sessao desconectada"), "NETWORK_ERROR"),
    (RuntimeError("elemento ausente / DOM alterado / login exigido"), "DEPENDENCY_ERROR"),
    (RuntimeError("selector mudou"), "DEPENDENCY_ERROR"),
    (RuntimeError("resposta incompleta do modelo"), "MODEL_ERROR"),
    (RuntimeError("resposta vazia"), "MODEL_ERROR"),
    (RuntimeError("resposta expirada"), "MODEL_ERROR"),
    (RuntimeError("coisa estranha qualquer"), "TOOL_ERROR"),
])
def test_classify_browser_error_mapping(exc, code):
    assert _classify_browser_error(exc) == code


def test_classify_cancellation_is_cancelled():
    assert _classify_browser_error(asyncio.CancelledError()) == "CANCELLED"


@pytest.mark.parametrize("exc,code", [
    (asyncio.TimeoutError("x"), "TIMEOUT"),
    (RuntimeError("TimeoutError: Waiting for selector"), "TIMEOUT"),
    (RuntimeError("locator timed out after 15000ms"), "TIMEOUT"),
    (RuntimeError("Target page, context or browser has been closed"), "NETWORK_ERROR"),
    (RuntimeError("FILL_FAILED: composer não reteve o texto (DOM alterado / selector obsoleto: boom)"),
     "DEPENDENCY_ERROR"),
    (RuntimeError("resposta vazia do chat"), "MODEL_ERROR"),
    (RuntimeError("boom desconhecido"), "TOOL_ERROR"),
])
def test_classify_adapter_error_mapping(exc, code):
    assert classify_adapter_error(exc) == code


def test_classify_adapter_cancellation_propagates():
    assert classify_adapter_error(asyncio.CancelledError()) == "CANCELLED"


class _FakePool:
    def __init__(self, text=None, exc=None):
        self.text = text
        self.exc = exc
        self.calls = []

    async def submit(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return {"raw_response": self.text}


class _FakeSession:
    def __init__(self, text=None, exc=None):
        self.text = text
        self.exc = exc
        self.calls = []

    async def ask(self, prompt, timeout_seconds=0):
        self.calls.append((prompt, timeout_seconds))
        if self.exc:
            raise self.exc
        return self.text


@pytest.mark.asyncio
async def test_browser_provider_success_via_pool():
    prov = BrowserProvider(pool=_FakePool(text="olá mundo"))
    resp = await prov.execute(_req())
    assert resp.success is True and resp.content == "olá mundo"
    assert resp.model == "browser-chatgpt-edge"
    assert resp.token_usage.output_tokens > 0


@pytest.mark.asyncio
async def test_browser_provider_success_via_session():
    prov = BrowserProvider(session=_FakeSession(text="via sessão"))
    resp = await prov.execute(_req())
    assert resp.success is True and resp.content == "via sessão"


@pytest.mark.asyncio
async def test_browser_provider_empty_response_is_failure_not_forged():
    prov = BrowserProvider(pool=_FakePool(text=""))
    resp = await prov.execute(_req())
    assert resp.success is False
    assert resp.content == ""


@pytest.mark.asyncio
async def test_browser_provider_error_carries_taxonomy_code():
    prov = BrowserProvider(session=_FakeSession(exc=TimeoutError("lento demais")))
    resp = await prov.execute(_req())
    assert resp.success is False
    assert "[TIMEOUT]" in (resp.error or "")


@pytest.mark.asyncio
async def test_browser_provider_without_backend_fails_loudly():
    prov = BrowserProvider()
    resp = await prov.execute(_req())
    assert resp.success is False
    assert resp.content == ""


@pytest.mark.asyncio
async def test_browser_provider_never_swallows_cancellation():
    class Cancelling:
        async def submit(self, **kwargs):
            raise asyncio.CancelledError()
    prov = BrowserProvider(pool=Cancelling())
    with pytest.raises(asyncio.CancelledError):
        await prov.execute(_req())


def test_extract_conversation_id():
    from browser.site_adapter import _extract_conversation_id

    assert _extract_conversation_id("https://chatgpt.com/c/3c9e97c9-4444-5555-6666-abcdef123456") == "3c9e97c9-4444-5555-6666-abcdef123456"
    assert _extract_conversation_id("https://chatgpt.com/c/3c9e97c9-4444-5555-6666-abcdef123456?model=auto") == "3c9e97c9-4444-5555-6666-abcdef123456"
    assert _extract_conversation_id("https://chatgpt.com/c/3c9e97c9-4444-5555-6666-abcdef123456/") == "3c9e97c9-4444-5555-6666-abcdef123456"
    assert _extract_conversation_id("https://chatgpt.com/") is None
    assert _extract_conversation_id("") is None


@pytest.mark.asyncio
async def test_open_conversation_noop_when_already_on_target():
    page = FakePage(url="https://chatgpt.com/c/target-conv-123")
    adapter = ChatSiteAdapter(page)
    await adapter.open_conversation("https://chatgpt.com/c/target-conv-123?model=gpt-4o")
    # Não deve ter chamado goto, pois já está na conversa desejada
    goto_calls = [c for c in page.calls if c[0] == "goto"]
    assert len(goto_calls) == 0


@pytest.mark.asyncio
async def test_open_conversation_navigates_and_preserves_identity_with_params():
    page = FakePage(url="https://chatgpt.com/")
    adapter = ChatSiteAdapter(page)

    # Simula o ChatGPT normalizando a URL com query params ao carregar
    original_goto = page.goto
    async def goto_with_params(url, **kwargs):
        await original_goto(url + "?temporary-chat=false", **kwargs)
    page.goto = goto_with_params

    await adapter.open_conversation("https://chatgpt.com/c/target-conv-456")
    goto_calls = [c for c in page.calls if c[0] == "goto"]
    assert len(goto_calls) == 1
    assert "target-conv-456" in page.url


@pytest.mark.asyncio
async def test_open_conversation_rejects_actual_mismatch():
    page = FakePage(url="https://chatgpt.com/")
    adapter = ChatSiteAdapter(page)

    # Simula redirecionamento para outra conversa completamente diferente
    async def goto_evil(url, **kwargs):
        page.calls.append(("goto", url))
        page.url = "https://chatgpt.com/c/different-conv-789"
    page.goto = goto_evil

    with pytest.raises(ChatSiteAdapterError, match="identidade incerta"):
        await adapter.open_conversation("https://chatgpt.com/c/target-conv-456")




# ---------------------------------------------------------------------------
# Recuperação automática do aviso de "verificações adicionais" do ChatGPT
# ---------------------------------------------------------------------------

ADDITIONAL_CHECKS_PT = (
    "Nossos sistemas estão fazendo verificações adicionais antes de responder a esta solicitação. "
    "Você pode tentar novamente com um modelo mais rápido para receber uma resposta mais rápida, "
    "embora ele possa ter menos capacidade para lidar com solicitações complexas. Saiba mais"
)


def test_detects_additional_checks_message_pt_and_en():
    assert is_additional_checks_message(ADDITIONAL_CHECKS_PT)
    assert is_additional_checks_message(
        "Our systems are performing additional checks before responding to this request. Learn more"
    )
    assert not is_additional_checks_message("Resposta normal do modelo.")


@pytest.mark.asyncio
async def test_additional_checks_recovery_stops_then_sends_continue():
    adapter = _adapter(FakePage())
    events = []

    async def fake_stop(timeout_s=6.0):
        events.append("stop")
        return True

    async def fake_send(prompt, on_progress=None):
        events.append(("send", prompt))

    adapter._stop_generation_for_recovery = fake_stop  # type: ignore[method-assign]
    adapter.send_prompt = fake_send  # type: ignore[method-assign]

    await adapter._recover_additional_checks()
    assert events == ["stop", ("send", "Continue")]


@pytest.mark.asyncio
async def test_send_and_capture_recovers_additional_checks_and_returns_real_answer():
    adapter = _adapter(FakePage())
    samples = iter([
        "turno anterior",
        ADDITIONAL_CHECKS_PT,
        ADDITIONAL_CHECKS_PT,
        "resposta final",
        "resposta final",
    ])
    last = {"value": "resposta final"}
    sent = []
    recovered = []

    async def extract():
        try:
            last["value"] = next(samples)
        except StopIteration:
            pass
        return last["value"]

    async def send(prompt, on_progress=None):
        sent.append(prompt)

    async def count():
        return 2

    async def recover(on_progress=None):
        recovered.append("Continue")

    async def finished():
        return True

    adapter.extract_last_response = extract  # type: ignore[method-assign]
    adapter.send_prompt = send  # type: ignore[method-assign]
    adapter._assistant_message_count = count  # type: ignore[method-assign]
    adapter._recover_additional_checks = recover  # type: ignore[method-assign]
    adapter.is_generation_finished = finished  # type: ignore[method-assign]

    out = await adapter.send_and_capture(
        "pergunta",
        timeout_seconds=5,
        stable_samples=1,
        poll_interval_s=0.01,
        heartbeat_interval_s=3600,
    )
    assert out == "resposta final"
    assert sent == ["pergunta"]
    assert recovered == ["Continue"]


@pytest.mark.asyncio
async def test_additional_checks_recovery_has_loop_guard():
    adapter = _adapter(FakePage())
    samples = iter([
        "turno anterior",
        ADDITIONAL_CHECKS_PT,
        ADDITIONAL_CHECKS_PT,
        ADDITIONAL_CHECKS_PT,
    ])
    last = {"value": ADDITIONAL_CHECKS_PT}
    counts = iter([2, 3, 4])

    async def extract():
        try:
            last["value"] = next(samples)
        except StopIteration:
            pass
        return last["value"]

    async def send(prompt, on_progress=None):
        return None

    async def count():
        return next(counts, 4)

    async def recover(on_progress=None):
        return None

    async def finished():
        return True

    adapter.extract_last_response = extract  # type: ignore[method-assign]
    adapter.send_prompt = send  # type: ignore[method-assign]
    adapter._assistant_message_count = count  # type: ignore[method-assign]
    adapter._recover_additional_checks = recover  # type: ignore[method-assign]
    adapter.is_generation_finished = finished  # type: ignore[method-assign]

    with pytest.raises(ChatSiteAdapterError, match="ADDITIONAL_CHECKS_LOOP"):
        await adapter.send_and_capture(
            "pergunta",
            timeout_seconds=5,
            stable_samples=1,
            poll_interval_s=0.01,
            heartbeat_interval_s=3600,
        )
