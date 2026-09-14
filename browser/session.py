from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from .site_adapter import ChatSiteAdapter


DEFAULT_TARGET_URL = "https://chatgpt.com"
DEFAULT_EDGE_PROFILE_ROOT = Path("browser_profiles")


class BrowserSession:
    """
    Playwright-backed session targeting chatgpt.com in Microsoft Edge,
    always in NON-private (persistent) mode so browser info
    (cookies, localStorage, login) is preserved across runs.

    Priority:
      1. cdp_url -> attach to an already-running Edge (never closes it).
      2. persistent Edge profile (channel="msedge", launch_persistent_context)
         -> real Edge window, profile kept on disk.
      3. legacy chromium launch (fallback when Edge is unavailable).
    """

    def __init__(
        self,
        role: str,
        headless: bool = False,
        storage_state_path: Optional[str] = "auth.json",
        cdp_url: Optional[str] = None,
        browser_channel: str = "msedge",
        user_data_dir: Optional[str] = None,
        target_url: str = DEFAULT_TARGET_URL,
    ):
        self.role = role
        # chatgpt.com actively blocks headless automation; force headed unless explicitly overridden
        self.headless = headless
        self.storage_state_path = storage_state_path
        self.cdp_url = cdp_url
        self.browser_channel = browser_channel or "msedge"
        self.target_url = target_url
        if user_data_dir:
            self.user_data_dir = Path(user_data_dir)
        else:
            # Persistent per-role profile under the project so login/session survives restarts.
            # This is the opposite of private/incognito: profile is NEVER ephemeral.
            self.user_data_dir = DEFAULT_EDGE_PROFILE_ROOT / f"edge-{role}"
        self._playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.adapter: Optional[ChatSiteAdapter] = None
        self._using_persistent_context = False

    @property
    def is_live(self) -> bool:
        return self.adapter is not None and self.page is not None

    async def initialize(self, target_url: Optional[str] = None) -> None:
        url = target_url or self.target_url or DEFAULT_TARGET_URL
        self.target_url = url
        try:
            self._playwright = await async_playwright().start()

            if self.cdp_url:
                # Attach to the user's already-running Edge with remote debugging port, e.g.:
                #   msedge.exe --remote-debugging-port=9222 --user-data-dir="<edge-profile-dir>"
                # Never closes the real browser; only closes the tab it opened.
                self.browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
                if not self.browser.contexts:
                    raise RuntimeError("No contexts found in attached Edge via CDP")
                self.context = self.browser.contexts[0]
                self.page = await self.context.new_page()
                self._using_persistent_context = True
            else:
                # Persistent (non-private) Edge profile. Keeps cookies/history/login.
                state_file = (
                    Path(self.storage_state_path)
                    if self.storage_state_path and Path(self.storage_state_path).exists()
                    else None
                )
                self.user_data_dir.mkdir(parents=True, exist_ok=True)
                try:
                    self.context = await self._playwright.chromium.launch_persistent_context(
                        str(self.user_data_dir.resolve()),
                        channel=self.browser_channel,
                        headless=self.headless,
                        viewport={"width": 1280, "height": 800},
                        locale="pt-BR",
                        timezone_id="America/Sao_Paulo",
                        storage_state=str(state_file.resolve()) if state_file else None,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-first-run",
                            "--no-default-browser-check",
                        ],
                    )
                    self._using_persistent_context = True
                    self.browser = None  # persistent context owns the browser
                    pages = list(self.context.pages)
                    self.page = pages[0] if pages else await self.context.new_page()
                except Exception as edge_err:
                    # Fallback to bundled chromium when Edge channel is unavailable
                    err_short = str(edge_err)[:160].encode("ascii", "ignore").decode("ascii")
                    print(f"[{self.role}] Edge channel '{self.browser_channel}' unavailable ({err_short}); falling back to chromium.")
                    self.browser = await self._playwright.chromium.launch(headless=self.headless)
                    self.context = await self.browser.new_context(
                        storage_state=str(state_file) if state_file else None,
                        viewport={"width": 1280, "height": 800},
                        locale="pt-BR",
                    )
                    self.page = await self.context.new_page()
                    self._using_persistent_context = False

            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self.adapter = ChatSiteAdapter(self.page)
        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{self.role}] Browser initialization warning: {err_msg}. Browser offline; calls fail fast.")
            self.adapter = None

    async def ask(self, prompt: str, timeout_seconds: int = 600) -> str:
        if self.adapter:
            # Hard timeout enforced here (in addition to adapter-level polling deadline)
            # so RF-016 holds even if the page hangs. Cancellation is NOT swallowed:
            # asyncio.CancelledError propagates to the caller (RF-017).
            return await asyncio.wait_for(
                self.adapter.send_and_capture(prompt, timeout_seconds=timeout_seconds),
                timeout=timeout_seconds + 10,
            )

        # Sem browser live: falha alta, nunca resposta forjada. O ModelRouter
        # converte em fallback para outro provider / circuit breaker / retry.
        raise RuntimeError(
            f"[{self.role}] browser offline (Edge indisponível e sem CDP); "
            f"nenhuma resposta foi gerada"
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
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
            return

        # Persist auth snapshot (backup) while keeping the Edge profile on disk.
        # The profile dir itself is the source of truth for "manter infos do navegador".
        if self.context and self.storage_state_path:
            try:
                await self.context.storage_state(path=self.storage_state_path)
            except Exception:
                pass
        try:
            if self._using_persistent_context and self.context:
                await self.context.close()
            elif self.browser:
                await self.browser.close()
        except Exception:
            pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
