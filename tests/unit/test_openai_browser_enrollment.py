"""Explicit-consent, ephemeral DOM enrollment tests (no real OpenAI login)."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_remote import openai_browser_enrollment as en
from sentra_remote.product import ProductPaths


class FakePage:
    def __init__(self, url: str, dom: list[str]) -> None:
        self.url = url
        self.dom = dom
        self.closed = False
        self.visits: list[str] = []

    def evaluate(self, script: str) -> list[str]:
        return self.dom

    def goto(self, url: str, **_kw) -> None:
        self.visits.append(url)
        self.url = url
        self.dom = []

    def is_closed(self) -> bool:
        return self.closed


@pytest.mark.parametrize("url", [
    "http://platform.openai.com/settings/organization/tunnels",
    "https://platform.openai.com.evil.invalid/settings/organization/tunnels",
    "https://evil.invalid/settings/organization/tunnels",
    "https://platform.openai.com/settings/organization/tunnels-extra",
    "https://platform.openai.com/login",
    "file:///settings/organization/tunnels",
])
def test_dom_capture_rejects_untrusted_location(url):
    page = FakePage(url, ["tunnel_abcdefgh123456789"])
    with pytest.raises(ValueError, match="open_official_tunnels_page"):
        en.detect_tunnel_in_page(page)


def test_detect_single_tunnel_requires_unambiguous_identifier():
    page = FakePage(en.OPENAI_TUNNELS_URL, [
        "tunnel_abcdefgh123456789", "tunnel_abcdefgh123456789"
    ])
    assert en.detect_tunnel_in_page(page) == "tunnel_abcdefgh123456789"
    page.dom.append("tunnel_otherid987654321")
    with pytest.raises(ValueError, match="tunnel_multiple_visible"):
        en.detect_tunnel_in_page(page)


def test_key_capture_restricted_to_one_time_official_page():
    key = "sk-test_NEWKEY_NOTREAL_0123456789abcdef"
    page = FakePage(en.OPENAI_API_KEYS_URL, [key])
    assert en.capture_new_key_in_page(page) == key
    page.url = en.OPENAI_TUNNELS_URL
    with pytest.raises(ValueError, match="open_official_api_keys_page"):
        en.capture_new_key_in_page(page)
    page.url = en.OPENAI_API_KEYS_URL
    page.dom = ["sk-short"]
    with pytest.raises(ValueError, match="new_key_not_found"):
        en.capture_new_key_in_page(page)


def test_requires_consent_to_start_or_capture_key(tmp_path):
    session = en.OpenAIConsentBrowser(
        ProductPaths(tmp_path / "install", tmp_path / "state"), lambda *_: None,
    )
    with pytest.raises(PermissionError):
        session.start()
    with pytest.raises(RuntimeError):
        session.request("detect_tunnel")
    # Capture without any enrollment consent is forbidden.
    with pytest.raises(PermissionError):
        session.request("import_new_key")


def test_isolated_session_does_not_emit_api_key_or_write_unapproved(
    tmp_path, monkeypatch
):
    secret = "sk-proj_fake_0123456789abcdefghijklmnop"
    tunnel_id = "tunnel_abcdefgh123456789"
    stored: list[tuple[str, str]] = []
    observed: list[tuple[str, str]] = []
    browser_events: list[str] = []

    class Browser:
        def new_context(self, **kwargs):
            assert kwargs["accept_downloads"] is False
            assert kwargs["service_workers"] == "block"
            browser_events.append("context")
            return Context()
        def close(self):
            browser_events.append("browser_closed")

    class Context:
        def new_page(self):
            return page
        def close(self):
            browser_events.append("context_closed")

    class BrowserType:
        def launch(self, *, channel, headless):
            assert channel == "msedge" and not headless
            return Browser()

    class Playwright:
        chromium = BrowserType()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    page = FakePage(en.OPENAI_TUNNELS_URL, [])
    def fake_eval(script):
        return [secret] if page.url == en.OPENAI_API_KEYS_URL else [tunnel_id]
    page.evaluate = fake_eval
    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: Playwright()),
    )
    monkeypatch.setattr(
        en, "configure_tunnel",
        lambda paths, tunnel, key: stored.append((tunnel, key)),
    )
    finished = threading.Event()
    def notify(event: str, detail: str):
        observed.append((event, detail))
        if event == "closed":
            finished.set()

    session = en.OpenAIConsentBrowser(
        ProductPaths(tmp_path / "install", tmp_path / "state"), notify
    )
    session.start(approved=True)
    session.request("detect_tunnel")
    session.request("open_keys")
    session.request("import_new_key", approved=True)
    assert finished.wait(4)
    assert stored == [(tunnel_id, secret)]
    assert secret not in repr(observed)
    assert any(name == "configured" for name, _ in observed)
    assert browser_events[-2:] == ["context_closed", "browser_closed"]
    assert not (tmp_path / "state").exists()

def test_real_dom_selectors_in_ephemeral_edge_without_openai_access():
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page()
                class OfficialPage:
                    def __init__(self, url):
                        self.url = url
                    def evaluate(self, script):
                        return page.evaluate(script)

                page.set_content(
                    '<main><code>tunnel_mysecureabc123456789</code></main>'
                    '<div role="row"><span>tunnel_mysecureabc123456789</span></div>'
                )
                assert en.detect_tunnel_in_page(
                    OfficialPage(en.OPENAI_TUNNELS_URL)
                ) == "tunnel_mysecureabc123456789"

                secret = "sk-proj_newsecret_abcdefghijklmnopqrstuvwxyz"
                page.set_content(
                    '<code>sk-proj_oldercredential_abcdefghijklmnop</code>'
                    '<section role="dialog"><span>' + secret + '</span></section>'
                )
                assert en.capture_new_key_in_page(
                    OfficialPage(en.OPENAI_API_KEYS_URL)
                ) == secret
                page.set_content(
                    '<code>sk-proj_oldercredential_abcdefghijklmnop</code>'
                )
                with pytest.raises(ValueError, match="new_key_not_found"):
                    en.capture_new_key_in_page(
                        OfficialPage(en.OPENAI_API_KEYS_URL)
                    )
            finally:
                browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "browserType.launch" in str(exc):
            pytest.skip("Microsoft Edge Playwright channel unavailable")
        raise


def test_invalid_port_does_not_crash_origin_guard():
    assert not en._trusted_platform_location(
        "https://platform.openai.com:invalid/settings/organization/tunnels",
        kind="tunnel",
    )

@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI-only test")
def test_browser_enrollment_key_is_dpapi_protected_at_rest(tmp_path):
    from sentra_remote.product import configure_tunnel, load_tunnel_config

    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    fake_key = "sk-proj_NOTREAL-0123456789abcdefghijklmnopqrstuvwxyz"
    tunnel = "tunnel_abcdefgh123456789"
    configure_tunnel(paths, tunnel, fake_key)
    serialized = paths.tunnel_config.read_text(encoding="utf-8")
    assert fake_key not in serialized
    assert "dpapi:" in serialized.lower()
    unlocked = load_tunnel_config(paths, reveal_secret=True)
    assert unlocked["runtime_key"] == fake_key
    assert unlocked["tunnel_id"] == tunnel
