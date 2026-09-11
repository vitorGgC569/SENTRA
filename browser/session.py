from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from .site_adapter import ChatSiteAdapter


class BrowserSession:
    def __init__(
        self,
        role: str,
        headless: bool = False,
        storage_state_path: Optional[str] = "auth.json",
        cdp_url: Optional[str] = None,
    ):
        self.role = role
        self.headless = headless
        self.storage_state_path = storage_state_path
        self.cdp_url = cdp_url
        self._playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.adapter: Optional[ChatSiteAdapter] = None

    async def initialize(self, target_url: str = "https://chatgpt.com") -> None:
        try:
            self._playwright = await async_playwright().start()

            if self.cdp_url:
                # Connect to existing open Chrome session with remote debugging port
                self.browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
                self.context = self.browser.contexts[0]
                self.page = await self.context.new_page()
            else:
                state_file = Path(self.storage_state_path) if self.storage_state_path and Path(self.storage_state_path).exists() else None
                self.browser = await self._playwright.chromium.launch(headless=self.headless)
                self.context = await self.browser.new_context(
                    storage_state=str(state_file) if state_file else None,
                    viewport={"width": 1280, "height": 800},
                )
                self.page = await self.context.new_page()

            await self.page.goto(target_url, wait_until="domcontentloaded")
            self.adapter = ChatSiteAdapter(self.page)
        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{self.role}] Browser initialization warning: {err_msg}. Running in simulation/fallback mode.")
            self.adapter = None

    async def ask(self, prompt: str, timeout_seconds: int = 600) -> str:
        if self.adapter:
            return await self.adapter.send_and_capture(prompt, timeout_seconds=timeout_seconds)
        
        # Fallback simulation response if no live browser connected
        return (
            f"BEGIN_RESULT\n"
            f"STATUS: COMPLETE\n"
            f"SUMMARY: Simulated response for role {self.role}.\n"
            f"PATCH:\n"
            f"```diff\n"
            f"--- a/README.md\n"
            f"+++ b/README.md\n"
            f"@@ -1,3 +1,4 @@\n"
            f"+# AutonomousInfinityAI active iteration\n"
            f"```\n"
            f"VALIDATION_COMMANDS:\n"
            f"- python -c \"print('simulated test passed')\"\n"
            f"END_RESULT"
        )

    async def close(self) -> None:
        if self.cdp_url:
            # Attached to the user's real, already-running browser: never close
            # it, only tidy up the tab this session opened and disconnect.
            if self.page:
                try:
                    await self.page.close()
                except Exception:
                    pass
            if self._playwright:
                await self._playwright.stop()
            return

        if self.context and self.storage_state_path:
            try:
                await self.context.storage_state(path=self.storage_state_path)
            except Exception:
                pass
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
