from __future__ import annotations

import asyncio
import re
from typing import Any, List, Optional
from playwright.async_api import Page
from .response_capture import ProgressCallback, ResponseCapture, emit_progress


def _extract_conversation_id(url: str) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    m = re.search(r"/c/([a-zA-Z0-9-]{1,128})", url)
    return m.group(1) if m else None


class ChatSiteAdapterError(RuntimeError):
    """Raised for unrecoverable chatgpt.com page/session states.

    A mensagem carrega palavras-chave da taxonomia lida por
    browser_provider._classify_browser_error (só leitura) e por
    classify_adapter_error abaixo:
      TIMEOUT          <- TimeoutError / "timed out" / "timeout"
      MODEL_ERROR      <- "vazia"/"incompleta"/"expirada"
      NETWORK_ERROR    <- "closed"/"disconnected"/"sessao"
      DEPENDENCY_ERROR <- "ausente"/"dom"/"selector"/"login"
      TOOL_ERROR       <- demais casos
    """


# Seletores em CAMADAS (primário + alternativos), espelhando
# edge_extension/selectors.js. Cada camada é tentada em ordem; nunca há
# um seletor único como ponto de falha. Se o DOM mudar, atualize aqui.
COMPOSER_SELECTORS = (
    "#prompt-textarea",  # primario (caminho validado)
    '[role="textbox"]',  # alternativo 1 (papel ARIA)
    'textarea[data-testid="chat-input"]',  # alternativo 2 (testid)
    "textarea",  # alternativo 3 (tag generica)
    '[contenteditable="true"]',  # alternativo 4 (editor rico)
)

SEND_SELECTORS = (
    "button[data-testid='send-button']",  # primario
    "button[aria-label*='Send'], button[aria-label*='Enviar']",  # alternativo 1
    "form button[type='submit']",  # alternativo 2 (submit do form)
    "button:has-text('Send'), button:has-text('Enviar')",  # alternativo 3 (texto)
)

STOP_SELECTORS = (
    "button[data-testid='stop-button']",  # primario
    "button[aria-label*='Stop'], button[aria-label*='Interromper']",  # alternativo 1
    "button:has-text('Stop generating'), button:has-text('Interromper'), "
    "button:has-text('Parar')",  # alternativo 2 (texto)
)

ASSISTANT_SELECTORS = (
    "[data-message-author-role='assistant']",  # primario
    "[data-message-id], .markdown",  # alternativo 1
    ".agent-turn, article",  # alternativo 2
)

# Taxonomia de erro do caminho Playwright (espelha o provider, sem tocá-lo).
ERROR_TAXONOMY = frozenset({
    "NETWORK_ERROR",
    "DEPENDENCY_ERROR",
    "MODEL_ERROR",
    "TOOL_ERROR",
    "TIMEOUT",
    "CANCELLED",
})


def classify_adapter_error(exc: BaseException) -> str:
    """Classifica exceções na taxonomia OMA sem tocar no browser_provider.

    Mesmos ramos do provider (só leitura), estendido com detecção textual
    de timeout para erros embrulhados que não são instâncias de TimeoutError
    (ex. TimeoutError do Playwright dentro de RuntimeError) — um timeout
    continua TIMEOUT mesmo quando a mensagem cita selector/DOM.
    """
    if isinstance(exc, asyncio.CancelledError):
        return "CANCELLED"
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "TIMEOUT"
    msg = str(exc).lower()
    if "timed out" in msg or "timeout" in msg:
        return "TIMEOUT"
    if "vazia" in msg or "incompleta" in msg or "expirada" in msg:
        return "MODEL_ERROR"
    if "closed" in msg or "disconnected" in msg or "sessao" in msg:
        return "NETWORK_ERROR"
    if "ausente" in msg or "dom" in msg or "selector" in msg or "login" in msg:
        return "DEPENDENCY_ERROR"
    return "TOOL_ERROR"


def _norm_space(text: str) -> str:
    return " ".join((text or "").split())


class ChatSiteAdapter:
    """Adapter for chatgpt.com. Sync is event/state-driven (no fixed-sleep reliance)."""

    def __init__(
        self,
        page: Page,
        *,
        composer_timeout_ms: int = 15000,
        submit_accept_timeout_s: float = 8.0,
        generation_start_timeout_s: float = 5.0,
    ):
        self.page = page
        self.composer_timeout_ms = composer_timeout_ms
        self.submit_accept_timeout_s = submit_accept_timeout_s
        self.generation_start_timeout_s = generation_start_timeout_s

    def _ensure_page_usable(self) -> None:
        try:
            if self.page.is_closed():
                raise ChatSiteAdapterError("Page is closed (sessao desconectada ou aba fechada)")
        except ChatSiteAdapterError:
            raise
        except Exception as e:
            raise ChatSiteAdapterError(f"Page state unreadable: {e}")
        try:
            url = (self.page.url or "").lower()
        except Exception:
            url = ""
        if any(m in url for m in ("auth/login", "/login", "auth0", "accounts.google")):
            raise ChatSiteAdapterError(
                "Parede de login no chatgpt.com (login exigido / DOM fora da conversa)"
            )

    async def open_new_chat(self, timeout_s: float = 30.0) -> None:
        """Navega para um chat em branco. Depois disso a página não segura conversa alguma."""
        self._ensure_page_usable()
        try:
            await self.page.goto("https://chatgpt.com/", wait_until="domcontentloaded",
                                 timeout=int(timeout_s * 1000))
            try:
                # Traz a janela para frente: janela oculta/minimizada congela
                # o renderer e mata a automação em silêncio minutos depois.
                await self.page.bring_to_front()
            except Exception:
                pass
            await self._resolve_composer()
        except ChatSiteAdapterError:
            raise
        except Exception as e:
            raise ChatSiteAdapterError(f"Falha ao abrir novo chat: {e}")

    async def open_conversation(self, url: str, timeout_s: float = 30.0) -> None:
        """Navega para uma conversa existente; no-op se já estiver nela. Recusa login wall e redirecionamento (identidade incerta)."""
        self._ensure_page_usable()
        target_id = _extract_conversation_id(url)
        try:
            current = self.page.url or ""
        except Exception:
            current = ""
        current_id = _extract_conversation_id(current)
        if (target_id and current_id and target_id == current_id) or (
            current.split("?")[0].rstrip("/") == (url or "").split("?")[0].rstrip("/")
        ):
            await self._resolve_composer()
            return
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            try:
                await self.page.bring_to_front()
            except Exception:
                pass
            await self._resolve_composer()
        except ChatSiteAdapterError:
            raise
        except Exception as e:
            raise ChatSiteAdapterError(f"Falha ao abrir conversa: {e}")
        try:
            final = self.page.url or ""
        except Exception:
            final = ""
        final_id = _extract_conversation_id(final)
        matches_identity = (target_id and final_id and target_id == final_id) or (
            final.split("?")[0].rstrip("/") == (url or "").split("?")[0].rstrip("/")
        )
        if not matches_identity:
            raise ChatSiteAdapterError(f"Conversa redirecionou para {final!r}; identidade incerta")
        try:
            url_lower = (self.page.url or "").lower()
        except Exception:
            url_lower = ""
        if any(m in url_lower for m in ("auth/login", "/login", "auth0", "accounts.google")):
            raise ChatSiteAdapterError(
                "Parede de login no chatgpt.com (login exigido / DOM fora da conversa)"
            )

    async def _first_ready_button(self, selectors) -> Optional[Any]:
        """Primeiro botão visível E habilitado em qualquer camada (nunca seletor único)."""
        for sel in selectors:
            try:
                loc = self.page.locator(sel)
                count = await loc.count()
            except Exception:
                continue
            for i in range(min(count, 4)):
                try:
                    el = loc.nth(i)
                    if await el.is_visible() and await el.is_enabled():
                        return el
                except Exception:
                    continue
        return None

    async def _wait_ready_button(self, selectors, timeout_s: float = 10.0) -> Optional[Any]:
        """Aguarda o botão de envio ficar pronto (pós-paste o React ainda
        está sincronizando estado; checagem única perde a janela)."""
        deadline = asyncio.get_running_loop().time() + max(1.0, timeout_s)
        while asyncio.get_running_loop().time() < deadline:
            found = await self._first_ready_button(selectors)
            if found is not None:
                return found
            await asyncio.sleep(0.5)
        return await self._first_ready_button(selectors)

    async def _resolve_composer(self) -> Any:
        """Localiza o composer varrendo as camadas em ordem (orientado a estado)."""
        self._ensure_page_usable()
        # Primeiro: espera o composer EXISTIR (SPA ainda hidratando após
        # navegação não tem nó algum — checagem única aqui falharia em ~1s).
        try:
            await self.page.wait_for_selector(
                ",".join(COMPOSER_SELECTORS),
                state="attached",
                timeout=self.composer_timeout_ms,
            )
        except Exception:
            pass
        for sel in COMPOSER_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if not await loc.count():
                    continue
                await loc.first.wait_for(state="visible", timeout=self.composer_timeout_ms)
                return loc.first
            except Exception:
                continue
        # Último recurso: papel ARIA (mesmo alvo, outro mecanismo de busca).
        try:
            input_box = self.page.get_by_role("textbox")
            if await input_box.count():
                await input_box.first.wait_for(state="visible", timeout=self.composer_timeout_ms)
                return input_box.first
        except Exception:
            pass
        raise ChatSiteAdapterError(
            "Elemento de entrada do chatgpt.com ausente (elemento ausente / DOM alterado / login exigido)"
        )

    async def _read_composer_text(self, box) -> str:
        try:
            return await box.input_value()
        except Exception:
            pass
        try:
            return await box.inner_text()
        except Exception:
            return ""

    async def _composer_holds(self, box, prompt: str) -> bool:
        """Confere se o composer reteve o prompt (tolerante a normalização de espaço).

        Leitura vazia ou ilegível = FALSO (indeterminado nunca conta como
        confirmação: aceitar texto fantasma produzia SUBMIT_FAILED em loop
        quando o fill caía num nó substituído pelo React).
        Só retorna True com o head do prompt presente no texto lido.
        """
        try:
            got = await self._read_composer_text(box)
        except Exception:
            return False
        if not got or not got.strip():
            return False
        head = _norm_space((prompt or "")[:40])
        return bool(head) and (head in _norm_space(got))

    async def _wait_submit_accepted(self, box, timeout_s: Optional[float] = None) -> bool:
        """Aceite = composer esvaziou OU geração começou (stop visível). Estado, não sleep."""
        limit = self.submit_accept_timeout_s if timeout_s is None else timeout_s
        deadline = asyncio.get_running_loop().time() + limit
        while asyncio.get_running_loop().time() < deadline:
            try:
                if not (await self._read_composer_text(box)).strip():
                    return True
            except Exception:
                pass
            try:
                if not await self.is_generation_finished():
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.25)
        return False

    async def send_prompt(
        self,
        prompt: str,
        *,
        on_progress: Optional[ProgressCallback] = None,
    ) -> None:
        self._ensure_page_usable()
        await emit_progress(on_progress, "sending")

        # Locators with fallback; wait for the composer to be actionable
        # instead of assuming it is ready (event-driven, not sleep-driven).
        box = await self._resolve_composer()
        try:
            await box.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        try:
            await box.focus(timeout=5000)
        except Exception:
            pass

        # Preenche com verificação + fallbacks (fill -> evaluate direto ->
        # digitação sequencial em prompts curtos). Sem isso, um editor que
        # descarta o fill vira envio parcial silencioso.
        fill_err = ""
        accepted_fill = False
        try:
            await box.fill(prompt, timeout=10000)
            if await self._composer_holds(box, prompt):
                accepted_fill = True
        except Exception as e:
            fill_err = str(e)[:200]
        if not accepted_fill:
            try:
                await box.evaluate(
                    """(el, text) => {
                        el.focus();
                        if (el.isContentEditable) {
                            el.textContent = text;
                            el.dispatchEvent(new InputEvent('input', {bubbles: true}));
                        } else {
                            el.value = text;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        }
                    }""",
                    prompt,
                )
                if await self._composer_holds(box, prompt):
                    accepted_fill = True
            except Exception as e:
                fill_err = ((fill_err + " | " + str(e))[:300]) if fill_err else str(e)[:300]
        if not accepted_fill and prompt and len(prompt) <= 2000:
            try:
                await box.focus(timeout=5000)
                await box.press_sequentially(prompt, delay=1, timeout=60000)
                if await self._composer_holds(box, prompt):
                    accepted_fill = True
            except Exception as e:
                fill_err = ((fill_err + " | " + str(e))[:300]) if fill_err else str(e)[:300]
        if not accepted_fill:
            raise ChatSiteAdapterError(
                "FILL_FAILED: composer não reteve o texto "
                f"(DOM alterado / selector obsoleto: {fill_err})"
            )

        # Re-resolve e re-verifica no handle fresco: o React pode ter
        # substituído o nó entre o fill e o clique (texto some sem erro).
        try:
            box = await self._resolve_composer()
            if not await self._composer_holds(box, prompt):
                await box.evaluate(
                    """(el, text) => {
                        el.focus();
                        if (el.isContentEditable) {
                            el.textContent = text;
                            el.dispatchEvent(new InputEvent('input', {bubbles: true}));
                        } else {
                            el.value = text;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        }
                    }""",
                    prompt,
                )
                box = await self._resolve_composer()
                if not await self._composer_holds(box, prompt):
                    raise ChatSiteAdapterError(
                        "FILL_FAILED: texto não persistiu após re-fill (nó instável)"
                    )
        except ChatSiteAdapterError:
            raise
        except Exception as e:
            raise ChatSiteAdapterError(f"FILL_FAILED na re-verificação: {e}")

        # Submit via botão de envio em camadas; sem affordance, Enter.
        # Um único clique no primeiro botão pronto (cliques extras em outras
        # camadas arriscariam envio duplicado no DOM real).
        # Se não confirmado, UMA retentativa com o mecanismo alternativo —
        # seguro porque só retenta se o composer ainda retém o texto
        # (nada foi enviado); se esvaziou, espera mais uma janela.
        submitted_with = None
        try:
            send_btn = await self._wait_ready_button(SEND_SELECTORS, timeout_s=10.0)
            if send_btn is not None:
                await send_btn.click(timeout=8000)
                submitted_with = "button"
            else:
                await box.press("Enter", timeout=5000)
                submitted_with = "enter"
            accepted = await self._wait_submit_accepted(box)
        except ChatSiteAdapterError:
            raise
        except Exception as e:
            raise ChatSiteAdapterError(f"Falha ao enviar prompt ao chatgpt.com: {e}")
        if not accepted:
            try:
                current = await self._read_composer_text(box)
            except Exception:
                current = ""
            head = _norm_space((prompt or "")[:40])
            still_holds = bool(head) and (head in _norm_space(current or ""))
            if still_holds:
                try:
                    if submitted_with == "button":
                        await box.press("Enter", timeout=5000)
                    else:
                        retry_btn = await self._wait_ready_button(SEND_SELECTORS, timeout_s=10.0)
                        if retry_btn is not None:
                            await retry_btn.click(timeout=8000)
                    accepted = await self._wait_submit_accepted(box)
                except ChatSiteAdapterError:
                    raise
                except Exception as e:
                    raise ChatSiteAdapterError(f"Falha na retentativa de envio: {e}")
            else:
                accepted = await self._wait_submit_accepted(box)
        if not accepted:
            raise ChatSiteAdapterError(
                "SUBMIT_FAILED: composer preenchido mas envio não confirmado "
                "(geração não iniciou e composer não esvaziou)"
            )
        await emit_progress(on_progress, "sent")

        # Event-driven: wait until generation actually starts (stop button appears)
        # with a short bounded wait. Small sleeps below
        # are only yield points, never the synchronization mechanism.
        start_deadline = asyncio.get_running_loop().time() + self.generation_start_timeout_s
        while asyncio.get_running_loop().time() < start_deadline:
            try:
                if not await self.is_generation_finished():
                    break
            except Exception:
                break
            await asyncio.sleep(0.25)

    async def is_generation_finished(self) -> bool:
        # Check if stop button is gone em TODAS as camadas (como observer.js).
        # If the page died mid-poll (nenhuma camada legível), report unfinished
        # so the caller times out with a clear TIMEOUT instead of a false
        # "finished".
        probed = False
        for sel in STOP_SELECTORS:
            try:
                loc = self.page.locator(sel)
                count = await loc.count()
                probed = True
            except Exception:
                continue
            for i in range(min(count, 4)):
                try:
                    if await loc.nth(i).is_visible():
                        return False
                except Exception:
                    continue
        if not probed:
            return False
        return True

    async def extract_last_response(self) -> str:
        for sel in ASSISTANT_SELECTORS:
            try:
                messages = self.page.locator(sel)
                count = await messages.count()
                if count == 0:
                    continue
                return await messages.nth(count - 1).inner_text()
            except Exception:
                continue
        return ""

    async def send_and_capture(
        self,
        prompt: str,
        timeout_seconds: int = 15,
        stable_samples: int = 3,
        *,
        on_progress: Optional[ProgressCallback] = None,
        poll_interval_s: float = 1.5,
        heartbeat_interval_s: float = 10.0,
    ) -> str:
        # NOTE: CancelledError and TimeoutError MUST propagate (RF-016/RF-017).
        # Only unexpected page errors fall back to a degraded structured response.
        # Baseline (como observer.js): o turno anterior nunca satisfaz o envio
        # novo — a captura só resolve com texto que mudou após o envio.
        try:
            baseline = await self.extract_last_response()
        except Exception:
            baseline = ""
        await self.send_prompt(prompt, on_progress=on_progress)

        response = await ResponseCapture.wait_for_stable_response(
            extract_text_fn=self.extract_last_response,
            is_finished_fn=self.is_generation_finished,
            timeout_seconds=timeout_seconds,
            stable_samples=stable_samples,
            baseline_text=baseline or None,
            poll_interval_s=poll_interval_s,
            heartbeat_interval_s=heartbeat_interval_s,
            on_progress=on_progress,
        )

        # Check for truncation (missing END_RESULT when required)
        if "BEGIN_RESULT" in prompt and "END_RESULT" not in response and response:
            continuation_prompt = (
                "The previous response was interrupted before completion.\n"
                "Please continue EXACTLY from the point of interruption and finalize with END_RESULT."
            )
            try:
                await self.send_prompt(continuation_prompt, on_progress=on_progress)
                second_part = await ResponseCapture.wait_for_stable_response(
                    extract_text_fn=self.extract_last_response,
                    is_finished_fn=self.is_generation_finished,
                    timeout_seconds=timeout_seconds,
                    stable_samples=stable_samples,
                    baseline_text=response,
                    poll_interval_s=poll_interval_s,
                    heartbeat_interval_s=heartbeat_interval_s,
                    on_progress=on_progress,
                )
                response = response + "\n" + second_part
            except (asyncio.CancelledError, TimeoutError):
                raise
            except Exception:
                pass

        if response:
            return response
        raise ChatSiteAdapterError("Resposta vazia do chatgpt.com (resposta incompleta ou sessao expirada)")
