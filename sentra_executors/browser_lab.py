"""Opt-in, localhost-only browser read capability; not unrestricted Playwright MCP.

No persistent user profile, browser extension, Edge attach, cookie import,
arbitrary MCP tools, navigation outside explicit exact URLs, or file:// paths.
Network isolation also requires OS firewall for untrusted browser binaries.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import tempfile
from dataclasses import dataclass
from urllib.parse import urlsplit

from sentra_runtime.contracts import Capability, Machine
from ._base import GuardedExecutor


def _valid_loopback_url(url: str) -> bool:
    if type(url) is not str or len(url) > 2048 or any(c.isspace() for c in url):
        return False
    try:
        p = urlsplit(url)
        if p.scheme != "http" or p.username is not None or p.password is not None:
            return False
        if p.fragment or not p.path.startswith("/") or not p.port:
            return False
        # Numeric loopback ONLY: hostname "localhost" can be remapped via
        # DNS/hosts files or proxies. This forbids routing outside the host.
        return p.hostname in {"127.0.0.1", "::1"} and bool(p.netloc)
    except ValueError:
        return False


@dataclass(frozen=True)
class BrowserReadBinding:
    capability_id: str
    allowed_urls: tuple[str, ...]
    timeout_seconds: float = 10.0

    def __post_init__(self):
        if (not self.capability_id or not self.allowed_urls or
                len(set(self.allowed_urls)) != len(self.allowed_urls) or
                not all(_valid_loopback_url(url) for url in self.allowed_urls) or
                not 0 < self.timeout_seconds <= 30):
            raise ValueError("invalid_loopback_browser_capability")


def parse_browser_read_query(query: dict) -> dict:
    """Minimal query envelope; deliberately no generic MCP tool execution."""
    if (type(query) is not dict or set(query) != {"method", "params"} or
            query["method"] != "browser.read_page" or
            type(query["params"]) is not dict or
            set(query["params"]) != {"url"} or
            type(query["params"]["url"]) is not str or
            not _valid_loopback_url(query["params"]["url"])):
        raise ValueError("unsupported_browser_query")
    return {"action": "read_page", "url": query["params"]["url"]}


class PlaywrightReadOnlyBackend:
    """Starts only a fresh ephemeral Chromium profile. No user profile reuse."""

    def __init__(self, *, explicitly_approved: bool = False):
        self.explicitly_approved = explicitly_approved

    def run(self, binding: BrowserReadBinding, arguments: dict) -> dict:
        if not self.explicitly_approved:
            raise PermissionError("browser_process_requires_explicit_approval")
        url = arguments["url"]
        if url not in binding.allowed_urls:
            raise PermissionError("url_not_in_allowlist")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright_not_installed") from exc
        # Never pass ~/.config, Edge profile, user storage state, channels,
        # cookies, proxy, extensions or remote debugging parameters.
        with tempfile.TemporaryDirectory(prefix="sentra-browser-lab-") as profile:
            with sync_playwright() as playwright:
                browser = playwright.chromium
                if not os.path.isfile(browser.executable_path):
                    raise RuntimeError("playwright_browser_binary_absent")
                context = browser.launch_persistent_context(
                    user_data_dir=profile, headless=True,
                    java_script_enabled=False, accept_downloads=False,
                    service_workers="block", permissions=[],
                    ignore_https_errors=False,
                    args=["--no-first-run", "--disable-background-networking"],
                )
                try:
                    def route_request(route):
                        # Reject all URLs not explicitly approved. No iframes,
                        # scripts, images, fonts, forms or remote requests.
                        if (route.request.url == url and
                                route.request.resource_type == "document" and
                                route.request.is_navigation_request() and
                                route.request.frame == route.request.frame.page.main_frame):
                            route.continue_()
                        else:
                            route.abort()
                    context.route("**/*", route_request)
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_default_timeout(int(binding.timeout_seconds * 1000))
                    response = page.goto(url, wait_until="domcontentloaded",
                                         timeout=int(binding.timeout_seconds * 1000))
                    if response is None or response.status != 200 or page.url != url:
                        raise RuntimeError("browser_response_not_approved")
                    text = page.locator("body").inner_text(timeout=2500)
                    if len(text.encode("utf-8")) > 65_536:
                        raise RuntimeError("browser_response_size_limit")
                    return {"url_sha256": hashlib.sha256(url.encode()).hexdigest(),
                            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                            "text_length": len(text)}
                finally:
                    context.close()


class BrowserLabExecutor(GuardedExecutor):
    kind = "browser_lab"

    def __init__(self, *, machine_id: str, owner_principal_id: str,
                 bindings: tuple[BrowserReadBinding, ...], policy=None, backend=None):
        if len(set(b.capability_id for b in bindings)) != len(bindings):
            raise ValueError("duplicate_browser_capability")
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
                         bindings={b.capability_id: b for b in bindings}, policy=policy)
        self.backend = backend if backend is not None else PlaywrightReadOnlyBackend()

    def _validate(self, request, binding: BrowserReadBinding) -> dict:
        args = dict(request.arguments)
        if (set(args) != {"action", "url"} or args["action"] != "read_page" or
                type(args["url"]) is not str or
                args["url"] not in binding.allowed_urls or
                not _valid_loopback_url(args["url"])):
            raise ValueError("browser_query_or_url_denied")
        return args

    def _execute(self, binding: BrowserReadBinding, arguments: dict) -> dict:
        return self.backend.run(binding, arguments)


def declare_browser_lab_machine(*, machine_id: str, owner_principal_id: str,
                                bindings: tuple[BrowserReadBinding, ...],
                                policy, backend=None):
    """Explicit capabilities and registered adapter, no automatic browser start."""
    from .discovery import MachineDeclaration
    caps = tuple(Capability(b.capability_id, "Loopback-only browser read", "high")
                 for b in bindings)
    machine = Machine(machine_id, "browser_lab", owner_principal_id, caps)
    return MachineDeclaration(machine, BrowserLabExecutor(
        machine_id=machine_id, owner_principal_id=owner_principal_id,
        bindings=bindings, policy=policy, backend=backend))
