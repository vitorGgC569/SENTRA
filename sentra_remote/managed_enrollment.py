"""Owner-only DOM enrollment in SENTRA's persistent embedded Chromium.

No extra debugging listener, extension installation, cookie export or arbitrary
JavaScript API is introduced. Setup uses the authenticated host control.
"""
from __future__ import annotations

import time
import threading
from pathlib import Path

from .enrollment_bridge import ExtensionLocator, ExtensionPage


def wait_for_platform_login(page, cancelled, notify, *, timeout_s=600):
    from urllib.parse import urlsplit
    from .openai_browser_enrollment import _trusted_platform_location
    from .onboarding import OPENAI_TUNNELS_URL
    deadline, redirected = time.monotonic() + timeout_s, set()
    notified = False
    while time.monotonic() < deadline:
        if cancelled.is_set() or page.is_closed():
            raise ValueError("enrollment_cancelled")
        if _trusted_platform_location(page.url, kind="tunnel"):
            return
        if not notified:
            notify("progress", "Entre na Platform na janela do SENTRA. A configuração continuará automaticamente após o login.")
            notified = True
        parsed = urlsplit(page.url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("open_official_tunnels_page")
        if parsed.hostname == "platform.openai.com" and parsed.path not in redirected:
            redirected.add(parsed.path)
            page.goto(OPENAI_TUNNELS_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(500)
    raise ValueError("login_required")


class ManagedLocator(ExtensionLocator):
    def _append(self, step):
        return ManagedLocator(self.page, [*self.steps, step])

    def filter(self, *, visible=None, has=None):
        result = self
        if visible is not None:
            result = result._append({"kind": "visible", "value": visible})
        if has is not None:
            if has.page is not self.page:
                raise ValueError("cross-page setup locator")
            result = result._append({"kind": "has", "steps": has.steps})
        return result

    def input_value(self):
        return self._call("input_value")

    def select_option(self, *, label=None, value=None, timeout=5000):
        if value is not None:
            return self._call("select_value", value=value)
        return self._call("select_label", label=label)


class ManagedPage(ExtensionPage, ManagedLocator):
    def _append(self, step):
        return ManagedLocator(self, [step])

    def close(self):
        self.closed = True  # One owned setup view is released by its context.

    def prepare_probe(self, app_name, challenge):
        return self.client.request("dom", action="prepare_probe", app_name=app_name,
                                   challenge=challenge) is True


class ManagedClient:
    browser_name = "sentra"

    def __init__(self, launcher, session):
        self.launcher, self.session = launcher, session
        self.closed = threading.Event()

    def request(self, operation, *, timeout=30, **payload):
        if "action" in payload:
            payload["dom_action"] = payload.pop("action")
        try:
            result = self.launcher.runtime_control("setup", {"operation": operation,
                                                           "tab": self.session, **payload})
        except (OSError, ValueError, RuntimeError):
            if operation == "closed":
                return True
            raise
        if result.get("ok") is not True:
            raise ValueError("managed_browser_setup_failed")
        return result.get("result")


class ManagedEnrollmentContext:
    browser_name = "sentra"

    def __init__(self, paths, *, launcher=None, timeout_s=40):
        if launcher is None:
            from sentra_model_gateway.gateway import GatewayConfig, LauncherSupervisor, _load_or_create_turn_authority_token
            executable = paths.install_dir / "web-models/win-unpacked/Codex Web GPT.exe"
            launcher = LauncherSupervisor(GatewayConfig(
                checkout=paths.install_dir / "third_party/codex-chatgpt-web",
                launcher_executable=executable, state_root=paths.state_dir))
            launcher.turn_authority_token = _load_or_create_turn_authority_token(paths.state_dir)
        self.launcher, self.pages, self.closed = launcher, [], False
        launcher.start(hidden=True, browser_host_only=True)
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                # Read-only readiness may retry. Opening the view never retries
                # after an uncertain response: it could already have happened.
                launcher.runtime_control("setup", {"operation": "status"})
                break
            except (OSError, ValueError, RuntimeError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("managed_browser_unavailable") from None
                time.sleep(.2)
        result = launcher.runtime_control("setup", {"operation": "open"})
        if result.get("ok") is not True or not isinstance(result.get("result"), str):
            raise RuntimeError("managed_browser_setup_failed")
        self.client = ManagedClient(launcher, result["result"])

    def new_page(self):
        page = ManagedPage(self.client, self.client.session)
        self.pages.append(page)
        return page

    def configure_runtime(self):
        result = self.launcher.runtime_control("configure-web")
        if result.get("ok") is not True or result.get("configured") is not True or result.get("nativeProvidersChanged") is not False:
            raise RuntimeError("managed_runtime_configuration_failed")

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.client.request("close")
        finally:
            self.client.closed.set()
            for page in self.pages:
                page.closed = True
