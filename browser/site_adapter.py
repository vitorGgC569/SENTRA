from __future__ import annotations

import asyncio
from typing import Optional
from playwright.async_api import Page
from .response_capture import ResponseCapture


class ChatSiteAdapterError(RuntimeError):
    """Raised for unrecoverable chatgpt.com page/session states."""


class ChatSiteAdapter:
    """Adapter for chatgpt.com. Sync is event/state-driven (no fixed-sleep reliance)."""

    def __init__(self, page: Page):
        self.page = page

    def _ensure_page_usable(self) -> None:
        try:
            if self.page.is_closed():
                raise ChatSiteAdapterError("Page is closed (sessao desconectada ou aba fechada)")
        except ChatSiteAdapterError:
            raise
        except Exception as e:
            raise ChatSiteAdapterError(f"Page state unreadable: {e}")

    async def send_prompt(self, prompt: str) -> None:
        self._ensure_page_usable()
        # Locators with fallback; wait for the composer to be actionable
        # instead of assuming it is ready (event-driven, not sleep-driven).
        input_box = self.page.get_by_role("textbox")
        if not await input_box.count():
            input_box = self.page.locator("#prompt-textarea, textarea, [contenteditable='true']")
        try:
            await input_box.first.wait_for(state="visible", timeout=15000)
        except Exception:
            raise ChatSiteAdapterError(
                "Elemento de entrada do chatgpt.com ausente (elemento ausente / DOM alterado / login exigido)"
            )
        await input_box.first.fill(prompt)

        # Submit via Send button when visible, else Enter.
        send_btn = self.page.locator("button[data-testid='send-button'], button:has-text('Send')")
        try:
            if await send_btn.count() and await send_btn.first.is_visible():
                await send_btn.first.click()
            else:
                await input_box.first.press("Enter")
        except Exception as e:
            raise ChatSiteAdapterError(f"Falha ao enviar prompt ao chatgpt.com: {e}")

        # Event-driven: wait until generation actually starts (stop button appears)
        # or content begins changing, with a short bounded wait. Small sleeps below
        # are only yield points, never the synchronization mechanism.
        for _ in range(20):
            try:
                if not await self.is_generation_finished():
                    break
            except Exception:
                break
            await asyncio.sleep(0.25)

    async def is_generation_finished(self) -> bool:
        # Check if stop button is gone or send button is back
        try:
            stop_btn = self.page.locator("button[data-testid='stop-button'], button:has-text('Stop generating'), button[aria-label='Stop generating']")
            if await stop_btn.count() and await stop_btn.first.is_visible():
                return False
        except Exception:
            # If the page died mid-poll, report unfinished so the caller times out
            # with a clear TIMEOUT instead of a false "finished".
            return False
        return True

    async def extract_last_response(self) -> str:
        try:
            messages = self.page.locator("[data-message-author-role='assistant'], .markdown, .agent-turn")
            count = await messages.count()
            if count == 0:
                return ""
            return await messages.nth(count - 1).inner_text()
        except Exception:
            return ""

    async def send_and_capture(
        self,
        prompt: str,
        timeout_seconds: int = 15,
        stable_samples: int = 3,
    ) -> str:
        # NOTE: CancelledError and TimeoutError MUST propagate (RF-016/RF-017).
        # Only unexpected page errors fall back to a degraded structured response.
        await self.send_prompt(prompt)

        response = await ResponseCapture.wait_for_stable_response(
            extract_text_fn=self.extract_last_response,
            is_finished_fn=self.is_generation_finished,
            timeout_seconds=timeout_seconds,
            stable_samples=stable_samples,
        )

        # Check for truncation (missing END_RESULT when required)
        if "BEGIN_RESULT" in prompt and "END_RESULT" not in response and response:
            continuation_prompt = (
                "The previous response was interrupted before completion.\n"
                "Please continue EXACTLY from the point of interruption and finalize with END_RESULT."
            )
            try:
                await self.send_prompt(continuation_prompt)
                second_part = await ResponseCapture.wait_for_stable_response(
                    extract_text_fn=self.extract_last_response,
                    is_finished_fn=self.is_generation_finished,
                    timeout_seconds=timeout_seconds,
                    stable_samples=stable_samples,
                )
                response = response + "\n" + second_part
            except (asyncio.CancelledError, TimeoutError):
                raise
            except Exception:
                pass

        if response:
            return response
        raise ChatSiteAdapterError("Resposta vazia do chatgpt.com (resposta incompleta ou sessao expirada)")
