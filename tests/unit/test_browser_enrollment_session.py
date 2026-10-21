"""Existing-account DOM connections must not close or export browser sessions."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sentra_remote import browser_enrollment_session as sessions


@pytest.mark.parametrize("browser,relative,area", [
    ("edge", "Microsoft/Edge/User Data", "local"),
    ("chrome", "Google/Chrome/User Data", "local"),
    ("brave", "BraveSoftware/Brave-Browser/User Data", "local"),
    ("vivaldi", "Vivaldi/User Data", "local"),
    ("chromium", "Chromium/User Data", "local"),
    ("opera", "Opera Software/Opera Stable", "roaming"),
    ("opera-gx", "Opera Software/Opera GX Stable", "roaming"),
])
def test_discovers_only_the_published_local_dom_endpoint(tmp_path, browser, relative, area):
    root = tmp_path / area / relative
    root.mkdir(parents=True)
    (root / "DevToolsActivePort").write_text("9222\n/devtools/browser/12345678-abcd\n")
    # No profile preferences/cookies are needed or inspected.
    assert sessions.discover_browser_endpoints(local=tmp_path / "local", roaming=tmp_path / "roaming") == [
        sessions.BrowserEndpoint(browser, "ws://127.0.0.1:9222/devtools/browser/12345678-abcd")]


@pytest.mark.parametrize("value", [
    "0\n/devtools/browser/12345678", "65536\n/devtools/browser/12345678",
    "9222\nws://evil.invalid/control", "9222\n/devtools/browser/../../control",
    "9222\n/devtools/browser/12345678\nextra", "x" * 513,
])
def test_malformed_endpoint_never_becomes_a_connection(tmp_path, value):
    root = tmp_path / "Microsoft/Edge/User Data"
    root.mkdir(parents=True)
    (root / "DevToolsActivePort").write_text(value)
    assert not sessions.discover_browser_endpoints(local=tmp_path, roaming=tmp_path / "none")


def context(url="https://platform.openai.com/settings/organization/tunnels"):
    return Mock(pages=[SimpleNamespace(url=url)])


def test_attached_session_shares_the_existing_context_and_closes_only_its_own_tab():
    original = context()
    original.new_page.return_value.is_closed.return_value = False
    browser = Mock(contexts=[original])
    playwright = Mock()
    playwright.chromium.connect_over_cdp.return_value = browser
    attached = sessions.attached_enrollment_context(playwright, [sessions.BrowserEndpoint("edge", "local-endpoint")])
    tab = attached.new_page()
    assert attached.context is original
    attached.close()
    tab.close.assert_called_once()
    original.close.assert_not_called()
    browser.close.assert_not_called()


def test_multiple_browser_accounts_are_never_guessed():
    playwright = Mock()
    playwright.chromium.connect_over_cdp.side_effect = [Mock(contexts=[context()]), Mock(contexts=[context()])]
    with pytest.raises(ValueError, match="browser_account_selection_required"):
        sessions.attached_enrollment_context(playwright, [
            sessions.BrowserEndpoint("edge", "one"), sessions.BrowserEndpoint("chrome", "two")])


def test_selects_the_sole_browser_with_an_official_platform_tab():
    preferred = context()
    playwright = Mock()
    playwright.chromium.connect_over_cdp.side_effect = [Mock(contexts=[context("https://example.com")]),
                                                       Mock(contexts=[preferred])]
    attached = sessions.attached_enrollment_context(playwright, [
        sessions.BrowserEndpoint("edge", "one"), sessions.BrowserEndpoint("brave", "two")])
    assert attached.context is preferred and attached.browser_name == "brave"


def test_stale_endpoint_is_not_reported_as_a_reused_login():
    playwright = Mock()
    playwright.chromium.connect_over_cdp.side_effect = OSError("do not publish endpoint details")
    assert sessions.attached_enrollment_context(playwright, [sessions.BrowserEndpoint("edge", "stale")]) is None


def test_reusing_context_does_not_launch_or_create_an_empty_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "discover_browser_endpoints", lambda: [sessions.BrowserEndpoint("edge", "local")])
    playwright, notify = Mock(), Mock()
    playwright.chromium.connect_over_cdp.return_value = Mock(contexts=[context()])
    selected = sessions.enrollment_context(playwright, tmp_path / "state", notify)
    assert isinstance(selected, sessions.AttachedEnrollmentContext)
    playwright.chromium.launch_persistent_context.assert_not_called()
    assert not (tmp_path / "state").exists()
    assert notify.call_args.args[0] == "browser_session"


def test_real_edge_existing_session_survives_enrollment_tab(tmp_path):
    """A real browser retains a synthetic login; no OpenAI account is accessed."""
    _check_existing_browser_session(tmp_path, channel="msedge")


def test_real_brave_existing_session_survives_enrollment_tab(tmp_path):
    import os
    executable = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "BraveSoftware/Brave-Browser/Application/brave.exe"
    if not executable.is_file():
        pytest.skip("Brave is not installed on this test host")
    _check_existing_browser_session(tmp_path, executable_path=str(executable))


def _check_existing_browser_session(tmp_path, **launch_options):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from playwright.sync_api import sync_playwright

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            if self.path == "/login":
                self.send_header("Set-Cookie", "session=synthetic; SameSite=Lax; Path=/")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            logged_in = "session=synthetic" in self.headers.get("Cookie", "")
            self.wfile.write(b"<main>synthetic account</main>" if logged_in else b"<main>sign in</main>")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            profile = tmp_path / "profile"
            owner = playwright.chromium.launch_persistent_context(
                str(profile), headless=True, **launch_options,
                args=["--remote-debugging-port=0"],
            )
            try:
                original = owner.new_page()
                origin = f"http://127.0.0.1:{server.server_port}"
                original.goto(origin + "/login")
                original.goto(origin + "/")
                assert original.get_by_text("synthetic account", exact=True).is_visible()
                port, route = (profile / "DevToolsActivePort").read_text().splitlines()
                attached = sessions.attached_enrollment_context(playwright, [
                    sessions.BrowserEndpoint("edge", f"ws://127.0.0.1:{port}{route}")])
                setup_tab = attached.new_page()
                setup_tab.goto(origin + "/")
                assert setup_tab.get_by_text("synthetic account", exact=True).is_visible()
                attached.close()
                assert setup_tab.is_closed()
                assert not original.is_closed()
                original.reload()
                assert original.get_by_text("synthetic account", exact=True).is_visible()
            finally:
                owner.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
