from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from .response_capture import ProgressCallback, emit_progress, supports_kwarg
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
      3. bundled Chromium only when allow_invasive_fallback=True.
         Default is fail-closed so a native/profile failure never silently
         opens another browser/profile.
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
        launch_args: Optional[list] = None,
        allow_invasive_fallback: bool = False,
    ):
        self.role = role
        # chatgpt.com actively blocks headless automation; force headed unless explicitly overridden
        self.headless = headless
        self.storage_state_path = storage_state_path
        self.cdp_url = cdp_url
        self.browser_channel = browser_channel or "msedge"
        self.target_url = target_url
        # Extra Chromium flags (ex.: anti-throttling do perfil do bot).
        # Somados aos args base anti-automacao no launch; nunca substituem.
        self.launch_args = list(launch_args) if launch_args else []
        self.allow_invasive_fallback = bool(allow_invasive_fallback)
        if user_data_dir:
            self.user_data_dir = Path(os.path.expandvars(os.path.expanduser(str(user_data_dir))))
        else:
            # Persistent per-role profile under the project so login/session survives restarts.
            # This is the opposite of private/incognito: profile is NEVER ephemeral.
            root = DEFAULT_EDGE_PROFILE_ROOT
            try:
                if "onedrive" in str(root.resolve()).lower():
                    local_app_data = os.environ.get("LOCALAPPDATA")
                    root = (Path(local_app_data) / "SENTRA" / "profiles") if local_app_data else (Path.home() / ".sentra" / "profiles")
            except Exception:
                pass
            self.user_data_dir = root / f"edge-{role}"
        self._playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.adapter: Optional[ChatSiteAdapter] = None
        self._using_persistent_context = False
        self._closed = False

    @property
    def is_live(self) -> bool:
        if self._closed or self.adapter is None or self.page is None:
            return False
        try:
            if self.page.is_closed():
                return False
        except Exception:
            return False
        return True

    async def _cleanup_after_failed_init(self) -> None:
        """Fecha tudo que foi parcialmente criado (nunca deixa browser zumbi).

        No modo CDP fecha só a aba que abrimos; nunca o browser real do usuário.
        """
        try:
            if self.cdp_url:
                if self.page is not None:
                    try:
                        if not self.page.is_closed():
                            await self.page.close()
                    except Exception:
                        pass
            else:
                if self.context is not None:
                    try:
                        await self.context.close()
                    except Exception:
                        pass
                elif self.browser is not None:
                    try:
                        await self.browser.close()
                    except Exception:
                        pass
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self._using_persistent_context = False
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None

    async def initialize(
        self,
        target_url: Optional[str] = None,
        *,
        on_progress: Optional[ProgressCallback] = None,
    ) -> None:
        url = target_url or self.target_url or DEFAULT_TARGET_URL
        self.target_url = url
        self._closed = False
        try:
            await emit_progress(on_progress, "preparing")
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
                    from browser.bot_profile import launch_persistent_with_cookies
                    # Teto duro no launch: perfil travado por instancia
                    # abandona travaria aqui até o timeout externo (15min).
                    # Falha rápido para o fallback chromium abaixo.
                    self.context = await asyncio.wait_for(
                        launch_persistent_with_cookies(
                            self._playwright,
                            str(self.user_data_dir.resolve()),
                            channel=self.browser_channel,
                            headless=self.headless,
                            storage_state_path=str(state_file.resolve()) if state_file else None,
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--no-first-run",
                                "--no-default-browser-check",
                            ] + [a for a in (self.launch_args or []) if isinstance(a, str) and a.startswith("--")],
                        ),
                        timeout=120,
                    )
                    self._using_persistent_context = True
                    self.browser = None  # persistent context owns the browser
                    pages = list(self.context.pages)
                    self.page = pages[0] if pages else await self.context.new_page()
                except Exception as edge_err:
                    if not self.allow_invasive_fallback:
                        raise RuntimeError(
                            "native Edge launch failed; invasive bundled-browser fallback "
                            "is disabled unless explicitly opted in"
                        ) from edge_err
                    # Explicit opt-in only: launch a separate bundled Chromium.
                    err_short = str(edge_err)[:160].encode("ascii", "ignore").decode("ascii")
                    print(f"[{self.role}] Edge unavailable ({err_short}); explicit bundled-browser fallback enabled.")
                    self.browser = await self._playwright.chromium.launch(headless=self.headless)
                    self.context = await self.browser.new_context(
                        storage_state=str(state_file) if state_file else None,
                        viewport={"width": 1280, "height": 800},
                        locale="pt-BR",
                    )
                    self.page = await self.context.new_page()
                    self._using_persistent_context = False

            await emit_progress(on_progress, "navigating")
            if self.page is not None:
                # Teto global anti-congelamento: qualquer chamada CDP sem
                # timeout explícito (count, is_visible, inner_text, evaluate,
                # bring_to_front...) herda 30s em vez de travar para sempre
                # quando o renderer congela. Timeouts explícitos prevalecem.
                try:
                    self.page.set_default_timeout(30000)
                except Exception:
                    pass
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await emit_progress(on_progress, "settling")
            self.adapter = ChatSiteAdapter(self.page)
            await emit_progress(on_progress, "ready")
            try:
                from .bot_profile import is_logged_in
                if await is_logged_in(self.page):
                    await self.persist_auth_state()
            except Exception:
                pass
        except Exception as e:
            await self._cleanup_after_failed_init()
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{self.role}] Browser initialization warning: {err_msg}. Browser offline; calls fail fast.")
            self.adapter = None

    async def persist_auth_state(self) -> bool:
        """Persiste snapshot do estado de autenticação (cookies/localStorage) em disco."""
        if self.context and self.storage_state_path:
            try:
                path = Path(self.storage_state_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                await self.context.storage_state(path=str(path))
                return True
            except Exception:
                pass
        return False

    async def ask(
        self,
        prompt: str,
        timeout_seconds: int = 600,
        *,
        on_progress: Optional[ProgressCallback] = None,
    ) -> str:
        if self.adapter:
            # Hard timeout enforced here (in addition to adapter-level polling deadline)
            # so RF-016 holds even if the page hangs. Cancellation is NOT swallowed:
            # asyncio.CancelledError propagates to the caller (RF-017).
            # Heartbeat: on_progress(fase, timestamp) é chamado durante o envio
            # e a espera, para o provider reportar em gerações longas.
            if on_progress is not None and supports_kwarg(
                self.adapter.send_and_capture, "on_progress"
            ):
                inner = self.adapter.send_and_capture(
                    prompt, timeout_seconds=timeout_seconds, on_progress=on_progress
                )
            else:
                inner = self.adapter.send_and_capture(prompt, timeout_seconds=timeout_seconds)
            res = await asyncio.wait_for(
                inner,
                timeout=timeout_seconds + 10,
            )
            await self.persist_auth_state()
            return res

        # Sem browser live: falha alta, nunca resposta forjada. O ModelRouter
        # converte em fallback para outro provider / circuit breaker / retry.
        raise RuntimeError(
            f"[{self.role}] browser offline (Edge indisponível e sem CDP); "
            f"nenhuma resposta foi gerada"
        )

    async def close(self) -> None:
        """Fecha recursos de forma idempotente; nunca deixa browser zumbi."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.cdp_url:
                # Attached to the user's real, already-running browser: never close
                # it, only tidy up the tab this session opened and disconnect.
                if self.page is not None:
                    try:
                        if not self.page.is_closed():
                            await self.page.close()
                    except Exception:
                        pass
                if self._playwright is not None:
                    try:
                        await self._playwright.stop()
                    except Exception:
                        pass
                return

            # Persist auth snapshot (backup) while keeping the Edge profile on disk.
            # The profile dir itself is the source of truth for "manter infos do navegador".
            await self.persist_auth_state()
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
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.adapter = None
            self._playwright = None
            self._using_persistent_context = False
