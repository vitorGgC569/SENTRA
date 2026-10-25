"""Use an already exposed local DOM connection without reopening a user profile.

Ordinary browser profiles are never copied, read for credentials, relaunched,
or unlocked. Browsers without a DOM bridge remain a separate enrollment case.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import urlsplit


def setup_browser_choices() -> dict[str, str]:
    """Offer installed browsers, without reading or copying their user profiles."""
    choices = {"SENTRA · navegador integrado": "sentra", "Avançado · sessão externa existente": "auto"}
    for name, label, relative in [
        ("edge", "Microsoft Edge · perfil SENTRA", "Microsoft/Edge/Application/msedge.exe"),
        ("chrome", "Google Chrome · perfil SENTRA", "Google/Chrome/Application/chrome.exe"),
    ]:
        if any((Path(os.environ[root]) / relative).is_file()
               for root in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(root)):
            choices[label] = name
    from .enrollment_extension import _find_firefox
    if _find_firefox():
        choices["Firefox · extensão assinada"] = "firefox"
    return choices


@dataclass(frozen=True)
class BrowserEndpoint:
    browser: str
    websocket: str


def discover_browser_endpoints(*, local: Path | None = None,
                               roaming: Path | None = None) -> list[BrowserEndpoint]:
    """Read only Chromium's published DevTools endpoint, never profile contents."""
    local = local or (Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else None)
    roaming = roaming or (Path(os.environ["APPDATA"]) if os.environ.get("APPDATA") else None)
    roots = []
    if local is not None:
        roots += [("edge", local / "Microsoft/Edge/User Data"),
                  ("chrome", local / "Google/Chrome/User Data"),
                  ("brave", local / "BraveSoftware/Brave-Browser/User Data"),
                  ("vivaldi", local / "Vivaldi/User Data"),
                  ("chromium", local / "Chromium/User Data")]
    if roaming is not None:
        roots += [("opera", roaming / "Opera Software/Opera Stable"),
                  ("opera-gx", roaming / "Opera Software/Opera GX Stable")]
    endpoints = []
    seen = set()
    for browser, root in roots:
        published = root / "DevToolsActivePort"
        try:
            if published.is_symlink() or published.stat().st_size > 512:
                continue
            lines = published.read_text(encoding="ascii").splitlines()
            if len(lines) != 2 or not lines[0].isdigit():
                continue
            port = int(lines[0])
            if not 1 <= port <= 65535 or not re.fullmatch(r"/devtools/browser/[A-Za-z0-9-]{8,80}", lines[1]):
                continue
        except (OSError, UnicodeError, ValueError):
            continue
        websocket = f"ws://127.0.0.1:{port}{lines[1]}"
        if websocket not in seen:
            endpoints.append(BrowserEndpoint(browser, websocket))
            seen.add(websocket)
    return endpoints


def _official_platform_tab(page: Any) -> bool:
    try:
        url = urlsplit(page.url)
        return (url.scheme == "https" and url.hostname == "platform.openai.com"
                and url.port in (None, 443) and url.username is None and url.password is None)
    except (ValueError, AttributeError):
        return False


class AttachedEnrollmentContext:
    """Own only our new tab; close() must never close the user's browser/context."""
    def __init__(self, context: Any, browser_name: str) -> None:
        self.context, self.browser_name = context, browser_name
        self.pages = []

    def new_page(self):
        page = self.context.new_page()
        self.pages.append(page)
        return page

    def close(self):
        for page in self.pages:
            if not page.is_closed():
                page.close()
        self.pages.clear()


def attached_enrollment_context(playwright: Any, endpoints: list[BrowserEndpoint]) -> AttachedEnrollmentContext | None:
    candidates = []
    for endpoint in endpoints:
        try:
            browser = playwright.chromium.connect_over_cdp(endpoint.websocket, timeout=2500)
            # The first CDP context is the browser's default persistent context.
            if browser.contexts:
                context = browser.contexts[0]
                candidates.append((endpoint.browser, context))
        except Exception:
            # Stale ports are normal. Never log transport errors or websocket IDs.
            continue
    preferred = [(name, context) for name, context in candidates
                 if any(_official_platform_tab(page) for page in context.pages)]
    selected = preferred or candidates
    if len(selected) > 1:
        raise ValueError("browser_account_selection_required")
    if not selected:
        return None
    name, context = selected[0]
    return AttachedEnrollmentContext(context, name)


def enrollment_context(playwright: Any, state_dir: Path, notify: Callable[[str, str], None], *, bridge=None,
                       allow_setup_profile=False, browser="auto"):
    if browser not in {"auto", "edge", "chrome", "firefox"}:
        raise ValueError("unsupported_setup_browser")
    reuse_existing = not (allow_setup_profile and browser in {"edge", "chrome"})
    if bridge is not None and reuse_existing:
        context = bridge.context()
        if context is not None and (browser == "auto" or context.browser_name.lower() == browser):
            notify("browser_session", "Using the enabled Setup DOM extension in the existing browser profile (" + context.browser_name + ").")
            return context
    endpoints = discover_browser_endpoints() if reuse_existing else []
    if browser != "auto":
        endpoints = [endpoint for endpoint in endpoints if endpoint.browser == browser]
    attached = attached_enrollment_context(playwright, endpoints)
    if attached is not None:
        notify("browser_session", "Reusing the existing browser session through its local DOM connection.")
        return attached
    if not allow_setup_profile or browser == "firefox":
        raise ValueError("browser_extension_required")
    # A separate sign-in profile is an explicit assisted opt-in.
    notify("browser_session", "No existing browser DOM connection is available. Sign-in is required in the setup browser.")
    from .openai_auto_setup import edge_automation_profile
    profile = (Path(state_dir) / "chrome-automation") if browser == "chrome" else edge_automation_profile(state_dir)
    return playwright.chromium.launch_persistent_context(
        str(profile), channel="chrome" if browser == "chrome" else "msedge", headless=False, accept_downloads=False,
        args=["--no-first-run", "--no-default-browser-check", "--disable-sync"],
    )
