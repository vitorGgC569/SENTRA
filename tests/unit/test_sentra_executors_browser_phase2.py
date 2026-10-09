"""Phase 2 slice 1: loopback HTTP real; browser fixture, explicit real gate."""
from __future__ import annotations
import asyncio
import hashlib
import importlib.util
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.request import ProxyHandler, HTTPRedirectHandler, build_opener, Request

import pytest
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.executor import ExecutorRegistry, AuthorizationRequired
from sentra_executors import (
    BrowserReadBinding, PlaywrightReadOnlyBackend,
    declare_browser_lab_machine, parse_browser_read_query,
)


def go(coro):
    return asyncio.run(coro)


class Policy:
    allowed = True
    def __call__(self, _request):
        return PolicyDecision(self.allowed, "lab permitted" if self.allowed else "revoked")


class Server(BaseHTTPRequestHandler):
    hits = []
    def do_GET(self):
        type(self).hits.append(self.path)
        if self.path == "/approved":
            body = b"<html><body>sentra phase2 loopback</body></html>"
            self.send_response(200)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "https://example.invalid/forbidden")
            self.end_headers()
            return
        else:
            body = b"not found"
            self.send_response(404)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_args):
        return


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PermissionError("redirect_denied")


class ControlledBrowserFixture:
    """No browser binary: HTTP loopback fetch with no cookies/proxy/redirect."""
    def __init__(self):
        self.calls = []
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def run(self, binding, args):
        url = args["url"]
        assert url in binding.allowed_urls
        self.calls.append(url)
        try:
            with self.opener.open(Request(url, method="GET"),
                                  timeout=binding.timeout_seconds) as response:
                if response.status != 200:
                    raise RuntimeError("unexpected_status")
                raw = response.read(65537)
        except HTTPError as exc:
            raise RuntimeError("fixture_http_denied") from exc
        if len(raw) > 65536:
            raise RuntimeError("document_limit")
        parsed = TextOnly()
        parsed.feed(raw.decode("utf-8"))
        text = "".join(parsed.parts)
        return {"text_length": len(text),
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "url_sha256": hashlib.sha256(url.encode()).hexdigest()}


@pytest.fixture
def loopback():
    Server.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def registry_setup(url, *, backend=None):
    policy = Policy()
    backend = backend or ControlledBrowserFixture()
    binding = BrowserReadBinding("browser.read", (url,))
    declaration = declare_browser_lab_machine(
        machine_id="browser-lab", owner_principal_id="lab",
        bindings=(binding,), policy=policy, backend=backend)
    registry = ExecutorRegistry(authorize=policy)
    declaration.register(registry)
    return registry, policy, backend, declaration


def request(url, *, op="op-1"):
    return OperationRequest(
        operation_id=op, principal_id="lab", machine_id="browser-lab",
        capability_id="browser.read", work_item_id="work",
        idempotency_key=op, arguments=parse_browser_read_query(
            {"method": "browser.read_page", "params": {"url": url}}))


def test_real_http_loopback_fixture_e2e_registry_policy(loopback):
    url = loopback + "/approved"
    registry, policy, browser, decl = registry_setup(url)
    assert [c.capability_id for c in go(decl.discover())] == ["browser.read"]
    result = go(registry.submit(request(url)))
    assert result.state == "SUCCEEDED"
    assert result.evidence["text_sha256"] == hashlib.sha256(
        b"sentra phase2 loopback").hexdigest()
    again = go(registry.submit(request(url)))
    assert again.state == "SUCCEEDED"
    assert browser.calls == [url]
    assert Server.hits == ["/approved"]
    policy.allowed = False
    with pytest.raises(AuthorizationRequired):
        go(registry.submit(request(url)))
    assert Server.hits == ["/approved"]


@pytest.mark.parametrize("bad_url", [
    "https://127.0.0.1:9999/", "http://example.com:80/",
    "http://10.0.0.1:8080/", "file:///C:/Users/profile",
    "http://127.0.0.1:99/private#fragment",
    "http://user:pass@127.0.0.1:99/path",
    "http://127.0.0.1/", "http://127.0.0.1:99/\n",
])
def test_browser_binding_rejects_outbound_personal_files_urls(bad_url):
    with pytest.raises(ValueError, match="invalid_loopback_browser_capability"):
        BrowserReadBinding("browser.read", (bad_url,))


@pytest.mark.parametrize("query", [
    {"method": "browser.click", "params": {"url": "http://127.0.0.1:80/"}},
    {"method": "browser.read_page", "params": {"url": "http://localhost:80/",
                                               "storage_state": "Edge/Cookies"}},
    {"method": "browser.read_page", "params": {"url": "file:///C:/Users/x"}},
    {"method": "browser.eval", "params": {"code": "document.cookie"}},
])
def test_minimal_query_protocol_blocks_mouse_cookies_eval(query):
    with pytest.raises(ValueError, match="unsupported_browser_query"):
        parse_browser_read_query(query)


def test_registry_denies_nonallowlisted_loopback_and_no_fetch(loopback):
    url = loopback + "/approved"
    registry, _, browser, _ = registry_setup(url)
    alt = loopback + "/redirect"
    forged = OperationRequest(
        operation_id="denied", principal_id="lab", machine_id="browser-lab",
        capability_id="browser.read", work_item_id="work",
        idempotency_key="denied",
        arguments={"action": "read_page", "url": alt})
    result = go(registry.submit(forged))
    assert result.state == "FAILED" and result.error == "invalid_scope_or_capability"
    assert browser.calls == [] and Server.hits == []


def test_browser_real_backend_does_not_launch_without_explicit_approval(loopback):
    url = loopback + "/approved"
    registry, _, _, _ = registry_setup(url, backend=PlaywrightReadOnlyBackend())
    result = go(registry.submit(request(url)))
    assert result.state == "FAILED" and result.error == "backend_error"
    assert Server.hits == []


@pytest.mark.skipif(
    os.environ.get("SENTRA_BROWSER_LAB_APPROVED") != "1" or
    os.environ.get("SENTRA_BROWSER_ISOLATED_VM") != "1",
    reason="real Playwright requires authorized isolated VM opt-in",
)
def test_real_playwright_chromium_loopback_only_opt_in(loopback):
    pytest.importorskip("playwright.sync_api")
    import os.path
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.isfile(p.chromium.executable_path):
            pytest.skip("approved Playwright chromium browser binary unavailable")
    url = loopback + "/approved"
    registry, _, _, _ = registry_setup(
        url, backend=PlaywrightReadOnlyBackend(explicitly_approved=True))
    result = go(registry.submit(request(url)))
    assert result.state == "SUCCEEDED"
    assert result.evidence["text_sha256"] == hashlib.sha256(
        b"sentra phase2 loopback").hexdigest()
    assert Server.hits == ["/approved"]


def test_production_browser_backend_ephemeral_profile_and_network_route(monkeypatch, tmp_path, loopback):
    """Full browser backend algorithm with fake Playwright process ONLY."""
    import pathlib
    import sys
    from types import SimpleNamespace
    import playwright.sync_api as sync_api

    exe = tmp_path / "fixture-approved-browser.exe"
    exe.write_bytes(b"synthetic fixture, NEVER executed")
    captured = {"profile": None, "closed": False, "blocked": []}

    class Frame:
        pass

    class Page:
        def __init__(self, url):
            self.url = "about:blank"
            self.main_frame = Frame()
            self.main_frame.page = self
            self.destination = url
        def set_default_timeout(self, millis):
            assert millis > 0
        def goto(self, url, wait_until, timeout):
            assert url == self.destination
            assert wait_until == "domcontentloaded"
            assert timeout > 0
            request = SimpleNamespace(
                url=url, resource_type="document", frame=self.main_frame,
                is_navigation_request=lambda: True)
            route = SimpleNamespace(
                request=request,
                continue_=lambda: captured.setdefault("continued", True),
                abort=lambda: captured["blocked"].append(url))
            captured["handler"](route)
            assert captured.get("continued") is True
            hostile = SimpleNamespace(
                url="https://external.example/pixel",
                resource_type="image", frame=self.main_frame,
                is_navigation_request=lambda: False)
            captured["handler"](SimpleNamespace(
                request=hostile, continue_=lambda: pytest.fail("outbound"),
                abort=lambda: captured["blocked"].append(hostile.url)))
            self.url = url
            return SimpleNamespace(status=200)
        def locator(self, selector):
            assert selector == "body"
            return SimpleNamespace(inner_text=lambda timeout: "lab only")

    class Context:
        def __init__(self, url):
            self.pages = [Page(url)]
        def route(self, pattern, handler):
            assert pattern == "**/*"
            captured["handler"] = handler
        def close(self):
            captured["closed"] = True

    class Chromium:
        executable_path = str(exe)
        def launch_persistent_context(self, **kwargs):
            profile = kwargs["user_data_dir"]
            assert pathlib.Path(profile).is_dir()
            assert pathlib.Path(profile).name.startswith("sentra-browser-lab-")
            assert kwargs["java_script_enabled"] is False
            assert kwargs["accept_downloads"] is False
            assert kwargs["service_workers"] == "block"
            assert kwargs["permissions"] == []
            assert "channel" not in kwargs
            assert "storage_state" not in kwargs
            captured["profile"] = profile
            return Context(loopback + "/approved")

    class FakePlaywright:
        def __enter__(self):
            return SimpleNamespace(chromium=Chromium())
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", FakePlaywright)
    url = loopback + "/approved"
    registry, _, _, _ = registry_setup(
        url, backend=PlaywrightReadOnlyBackend(explicitly_approved=True))
    out = go(registry.submit(request(url)))
    assert out.state == "SUCCEEDED"
    assert out.evidence["text_sha256"] == hashlib.sha256(b"lab only").hexdigest()
    assert captured["closed"]
    assert not pathlib.Path(captured["profile"]).exists()
    assert captured["blocked"] == ["https://external.example/pixel"]
    assert Server.hits == []  # browser process was NOT launched


def test_localhost_hostname_remap_is_not_trusted():
    # "localhost" can be remapped; numeric loopback is the enforced surface.
    with pytest.raises(ValueError):
        BrowserReadBinding("browser.read", ("http://localhost:8080/",))


def test_allowed_loopback_redirect_to_external_is_denied_without_followup(loopback):
    # Even an initially allowlisted endpoint must not redirect off-host.
    url = loopback + "/redirect"
    registry, _, fixture_browser, _ = registry_setup(url)
    result = go(registry.submit(request(url)))
    assert result.state == "FAILED"
    assert result.error == "backend_error"
    assert fixture_browser.calls == [url]
    assert Server.hits == ["/redirect"]
    assert result.evidence == {}
