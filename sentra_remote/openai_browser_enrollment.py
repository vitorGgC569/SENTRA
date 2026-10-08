"""Authorized Platform enrollment in an ephemeral Edge session.

Installer consent covers creation with All permissions, capture and storage.
Only redacted status reaches the UI; login happens directly in the browser.
"""
from __future__ import annotations

import queue
import re
import threading
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from .onboarding import OPENAI_TUNNELS_URL, OPENAI_API_KEYS_URL
from .product import ProductPaths, configure_tunnel

TUNNEL_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])tunnel_[A-Za-z0-9_-]{8,128}(?![A-Za-z0-9_-])")
RUNTIME_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,256}(?![A-Za-z0-9_-])")

# Extract ONLY verified identifiers, never the surrounding page content.
_TUNNEL_DOM = r"""() => {
    const items = [location.pathname];
    const nodes = document.querySelectorAll(
      'code, pre, [role="row"], [role="dialog"], a[href*="tunnels"], input[readonly]'
    );
    for (const el of nodes) {
      if (!el.getClientRects().length) continue;
      const content = ('value' in el ? el.value : el.innerText || el.textContent || '');
      if (typeof content === 'string') items.push(content.slice(0, 5000));
      if (el instanceof HTMLAnchorElement) items.push(el.getAttribute('href') || '');
    }
    // Text nodes keep adjacent code elements from becoming one fake ID.
    if (document.body) {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node, length = 0;
      while ((node = walker.nextNode()) && length < 120000) {
        if (!node.parentElement?.getClientRects().length) continue;
        const text = node.textContent || '';
        items.push(text); length += text.length;
      }
    }
    const match = items.flatMap(text => text.match(
      /(?<![A-Za-z0-9_-])tunnel_[A-Za-z0-9_-]{8,128}(?![A-Za-z0-9_-])/g
    ) || []);
    // Prefer atomic tokens over container text that concatenated two IDs.
    const atomic = match.filter(token => !token.slice(7).includes('tunnel_'));
    return [...new Set(atomic)].slice(0, 16);
}"""

# Deliberately scoped to the *current* newly-created key dialog. No scanning
# arbitrary page text, browser storage, network response bodies or cookies.
_KEY_DOM = r"""() => {
    const scopes = [...document.querySelectorAll(
      '[role="dialog"], [aria-modal="true"]'
    )].filter(node => node.getClientRects().length);
    const found = [];
    for (const scope of scopes) {
      // Some Platform dialogs render the one-time secret in an ordinary
      // text node instead of an input/code element.
      const visibleText = scope.innerText || '';
      found.push(...(visibleText.match(/(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,256}(?![A-Za-z0-9_-])/g) || []));
      for (const node of scope.querySelectorAll('input, textarea, code, pre')) {
        if (!node.getClientRects().length || node.type === 'hidden') continue;
        const text = ('value' in node ? node.value : node.innerText || '');
        if (typeof text !== 'string') continue;
        const matches = text.match(/(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,256}(?![A-Za-z0-9_-])/g) || [];
        found.push(...matches);
      }
    }
    return [...new Set(found)].slice(0, 8);
}"""

Action = Literal["detect_tunnel", "open_keys", "import_new_key", "close"]
Notify = Callable[[str, str], None]


def _trusted_platform_location(url: str, *, kind: str) -> bool:
    """Never inspect a lookalike or redirected identity-provider page."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    expected = (
        "/settings/organization/tunnels" if kind == "tunnel" else
        "/settings/organization/api-keys"
    )
    try:
        return (
            parts.scheme == "https"
            and parts.hostname == "platform.openai.com"
            and parts.port in (None, 443)
            and parts.username is None and parts.password is None
            and (parts.path == expected or parts.path.startswith(expected + "/"))
        )
    except ValueError:
        return False


def _single_identifier(values: Any, pattern: re.Pattern[str], *, label: str) -> str:
    if not isinstance(values, list):
        raise ValueError(f"{label}_not_found")
    valid = {
        value for value in values
        if isinstance(value, str)
        and pattern.fullmatch(value)
    }
    if not valid:
        raise ValueError(f"{label}_not_found")
    if len(valid) != 1:
        raise ValueError(f"{label}_multiple_visible")
    return next(iter(valid))


def detect_tunnel_in_page(page: Any) -> str:
    if not _trusted_platform_location(page.url, kind="tunnel"):
        raise ValueError("open_official_tunnels_page")
    values = page.evaluate(_TUNNEL_DOM)
    return _single_identifier(values, TUNNEL_PATTERN, label="tunnel")


def capture_new_key_in_page(page: Any) -> str:
    """Read the one-time dialog after installer or Desktop enrollment consent."""
    if not _trusted_platform_location(page.url, kind="key"):
        raise ValueError("open_official_api_keys_page")
    values = page.evaluate(_KEY_DOM)
    return _single_identifier(values, RUNTIME_KEY_PATTERN, label="new_key")


class OpenAIConsentBrowser:
    """User-controlled browser with serialized Playwright operations.

    An ephemeral Edge profile prevents access to cookies from other browser
    sessions. This worker never reads or forwards credentials to callbacks.
    """

    def __init__(self, paths: ProductPaths, notify: Notify, *, runtime: Any = None) -> None:
        self.paths = paths
        self.notify = notify
        self._commands: queue.Queue[Action] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._tunnel_id: str | None = None
        self._running = threading.Event()
        self._closed = threading.Event()
        self._cancelled = threading.Event()
        self._approved = False
        self._automatic = False
        self.runtime = runtime

    def start(self, *, approved: bool = False, automatic: bool = False) -> None:
        if not approved:
            raise PermissionError("browser enrollment requires explicit user approval")
        if self._thread is not None:
            raise RuntimeError("enrollment browser is already running")
        self._approved = True
        self._automatic = automatic
        self._thread = threading.Thread(
            target=self._serve, name="sentra-openai-consent-browser", daemon=True
        )
        self._thread.start()

    def request(self, action: Action, *, approved: bool = False) -> None:
        if action not in {"detect_tunnel", "open_keys", "import_new_key", "close"}:
            raise ValueError("unsupported browser enrollment action")
        if action == "import_new_key" and not (approved or self._approved):
            raise PermissionError("capture and storage require enrollment approval")
        if self._automatic and action != "close":
            raise RuntimeError("automatic enrollment is already handling this step")
        if self._thread is None or self._closed.is_set():
            raise RuntimeError("enrollment browser is not running")
        self._commands.put(action)

    def close(self) -> None:
        self._cancelled.set()
        if self._thread is not None and not self._closed.is_set():
            self._commands.put("close")

    def _emit(self, event: str, message: str) -> None:
        try:
            self.notify(event, message)
        except Exception:
            # A closed desktop window must not prevent resource cleanup.
            pass

    def _serve(self) -> None:
        page = None
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                # Browser context is nonpersistent and unprivileged. The user
                # signs in directly; SENTRA does NOT handle their login.
                browser = playwright.chromium.launch(channel="msedge", headless=False)
                try:
                    context = browser.new_context(
                        accept_downloads=False, service_workers="block"
                    )
                    try:
                        page = context.new_page()
                        page.goto(OPENAI_TUNNELS_URL, wait_until="domcontentloaded", timeout=30000)
                        self._running.set()
                        if self._automatic:
                            from .openai_auto_setup import AutomaticEnrollment, configure_and_verify
                            from .product import load_tunnel_config
                            tunnel_id, secret = AutomaticEnrollment(
                                page, self._emit, self._cancelled,
                                existing_tunnel_id=str(load_tunnel_config(self.paths).get("tunnel_id") or ""),
                            ).run()
                            try:
                                if self._cancelled.is_set():
                                    raise RuntimeError("enrollment_cancelled")
                                if self.runtime is None:
                                    from .local_runtime import LocalRuntime
                                    from .product import ProductSettings
                                    self.runtime = LocalRuntime(self.paths, ProductSettings.load(self.paths.settings))
                                self._emit("progress", "Saving with Windows protection and verifying MCP and tunnel…")
                                result = configure_and_verify(self.paths, tunnel_id, secret, self.runtime)
                            finally:
                                secret = ""
                            if result.get("ok"):
                                self._emit("ready", "SENTRA configured. MCP and the authenticated OpenAI tunnel are verified.")
                            else:
                                self._emit("attention", "tunnel_verification_failed" if result.get("rollback_restored") else "manual_recovery_required")
                            return
                        self._emit(
                            "opened",
                            "Official Platform browser opened. Sign in and choose the tunnel.",
                        )
                        while True:
                            try:
                                action = self._commands.get(timeout=0.25)
                            except queue.Empty:
                                if page.is_closed():
                                    break
                                continue
                            if action == "close":
                                break
                            try:
                                if page.is_closed():
                                    raise RuntimeError("browser_closed")
                                if action == "detect_tunnel":
                                    tunnel_id = detect_tunnel_in_page(page)
                                    self._tunnel_id = tunnel_id
                                    self._emit("tunnel", tunnel_id)
                                elif action == "open_keys":
                                    if not self._tunnel_id:
                                        raise ValueError("select_tunnel_first")
                                    page.goto(
                                        OPENAI_API_KEYS_URL,
                                        wait_until="domcontentloaded", timeout=30000
                                    )
                                    self._emit(
                                        "key_page",
                                        "Create a NEW Runtime API key with All permissions. "
                                        "Leave its one-time reveal dialog open.",
                                    )
                                elif action == "import_new_key":
                                    if not self._tunnel_id:
                                        raise ValueError("select_tunnel_first")
                                    secret = capture_new_key_in_page(page)
                                    try:
                                        # DPAPI protected; never return the
                                        # plaintext key to the desktop or logs.
                                        configure_tunnel(self.paths, self._tunnel_id, secret)
                                    finally:
                                        secret = ""
                                    self._emit(
                                        "configured",
                                        "Runtime API key securely saved. Connecting SENTRA services.",
                                    )
                                    break
                            except Exception as exc:
                                # Never echo Playwright exception messages: they
                                # may include page HTML, login URL or a new key.
                                known_reasons = {
                                    "open_official_tunnels_page",
                                    "open_official_api_keys_page",
                                    "tunnel_not_found", "tunnel_multiple_visible",
                                    "new_key_not_found", "new_key_multiple_visible",
                                    "select_tunnel_first",
                                }
                                reason = str(exc) if str(exc) in known_reasons else type(exc).__name__
                                self._emit("attention", reason)
                    finally:
                        context.close()
                finally:
                    browser.close()
        except Exception as exc:
            # Browser startup may fail for network, login, or Playwright
            # errors. Only the exception class is safe to disclose.
            known_reasons = {
                "all_permissions_unavailable", "platform_ui_needs_attention",
                "login_required", "enrollment_cancelled", "tunnel_multiple_visible",
                "new_key_multiple_visible", "open_official_tunnels_page",
                "open_official_api_keys_page",
                "chatgpt_workspace_required",
                "workspace_association_unverified",
            }
            self._emit("attention", (
                "playwright_or_edge_unavailable"
                if isinstance(exc, (ImportError, OSError))
                else str(exc) if str(exc) in known_reasons else type(exc).__name__
            ))
        finally:
            self._tunnel_id = None
            self._running.clear()
            self._closed.set()
            self._emit("closed", "Enrollment browser closed. No browser session retained.")
