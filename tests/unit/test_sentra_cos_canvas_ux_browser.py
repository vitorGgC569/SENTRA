"""Real Chromium / real Vite / React+Radix DOM. Only synthesized credentials and API fixtures.

No connection to live ChatGPT, Edge user profile, real Canvas bearer, or
persistent processes. Uses isolated Chromium context and loopback-only Vite.
"""
import base64
import hashlib
import io
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "sentra_canvas" / "desktop_ui"
SHA_A = hashlib.sha256(b"hello\n").hexdigest()
SHA_B = hashlib.sha256(b"modified outside\n").hexdigest()
PDF_SHA = hashlib.sha256(b"synthetic test PDF only").hexdigest()

@pytest.fixture(scope="module")
def vite():
    pytest.importorskip("playwright.sync_api")
    vite_bin = UI / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_bin.exists():
        pytest.skip("Vite local dependency is missing")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        ["node", str(vite_bin), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=UI, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            if process.poll() is not None:
                pytest.fail(f"isolated Vite exited early: {process.returncode}")
            try:
                with urlopen(base + "/desktop-assets/src/qa/project-review-test.html", timeout=.3) as result:
                    if result.status == 200:
                        break
            except OSError:
                time.sleep(.1)
        else:
            pytest.fail("isolated Vite fixture failed to bind loopback")
        yield base
    finally:
        process.terminate()  # only PID created by this fixture, never user Edge/Canvas
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


class MockCanvas:
    def __init__(self):
        self.calls = []
        self.visual_status = 200
        self.preview_sha = SHA_A
        self.preview_text = "hello\n"
        self.saved = 0
        self.pngs = {}

    def route(self, route):
        req = route.request
        params = parse_qs(urlsplit(req.url).query)
        body = req.post_data_json if req.method == "POST" else {}
        action = (body or {}).get("action") or params.get("action", [""])[0]
        self.calls.append((req.method, action, params, body))
        assert req.headers.get("authorization") == "Bearer qa-local-fixture"
        if req.method == "POST":
            if action == "preview_edit":
                route.fulfill(json={
                    "diff": "-hello\n+updated\n", "changed": True,
                    "review_token": "qa-single-use-review", "write_performed": False,
                })
                return
            if action == "save":
                assert body.get("approve") is True
                assert body.get("review_token") == "qa-single-use-review"
                self.saved += 1
                self.preview_text = body["content"]
                self.preview_sha = hashlib.sha256(self.preview_text.encode()).hexdigest()
                route.fulfill(json={"written": True, "grants_created": False})
                return
            route.fulfill(status=405, json={"error": "denied"})
            return
        if action == "list":
            route.fulfill(json={"items": [
                {"name": "README.md", "path": "README.md", "directory": False},
                {"name": "sample.pdf", "path": "sample.pdf", "directory": False},
            ], "read_only": True})
        elif action == "preview":
            route.fulfill(json={
                "path": "README.md", "content": self.preview_text, "sha256": self.preview_sha,
                "editable": True, "size_bytes": len(self.preview_text), "read_only": True,
            })
        elif action == "diff":
            route.fulfill(json={"diff": "+line from git\n", "read_only": True})
        elif action == "pdf_visual":
            if self.visual_status != 200:
                route.fulfill(status=self.visual_status, json={"error":
                    "PDF renderer unavailable" if self.visual_status == 503 else "access denied"})
                return
            from PIL import Image
            dpi = int(params.get("dpi", ["72"])[0])
            width = round(80 * dpi / 72)
            height = round(60 * dpi / 72)
            png = io.BytesIO()
            Image.new("RGB", (width, height), "white").save(png, format="PNG")
            route.fulfill(json={
                "path": "sample.pdf", "page": 1, "pages": 2, "dpi": dpi,
                "width": width, "height": height, "mime": "image/png",
                "image_base64": base64.b64encode(png.getvalue()).decode(),
                "rendered": True, "ocr_used": False, "read_only": True,
                "source_sha256": PDF_SHA, "grants_created": False,
            })
        elif action == "pdf_text":
            route.fulfill(json={
                "path": "sample.pdf", "text": "Fallback textual seguro de teste.",
                "page": int(params.get("page", ["1"])[0]), "pages": 2,
                "rendered": False, "ocr_used": False, "read_only": True,
                "source_sha256": PDF_SHA,
            })
        else:
            route.fulfill(status=404, json={"error": "unknown action"})


def _page(browser, vite, model, dpr=1):
    context = browser.new_context(viewport={"width": 1180, "height": 850},
                                  device_scale_factor=dpr, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(6000)
    page.route("**/api/center/project-review**", model.route)
    page.goto(vite + "/desktop-assets/src/qa/project-review-test.html#token=qa-local-fixture",
              wait_until="domcontentloaded")
    page.get_by_role("dialog", name="Arquivos do projeto").wait_for(timeout=12000)
    page.get_by_role("button", name="sample.pdf").wait_for()
    return context, page


@pytest.mark.parametrize("dpr,scale,dpi", [(1, "100%", 72), (1.25, "125%", 90), (1.5, "150%", 108)])
def test_chromium_real_dom_keyboard_aria_dpi_docks_persist(vite, dpr, scale, dpi):
    from playwright.sync_api import sync_playwright, expect
    model = MockCanvas()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)  # bundled Chromium, isolated ephemeral profile
        try:
            context, page = _page(browser, vite, model, dpr)
            assert abs(page.evaluate("window.devicePixelRatio") - dpr) < .01
            dialog = page.get_by_role("dialog", name="Arquivos do projeto")
            expect(dialog).to_have_attribute("aria-modal", "true")
            expect(page.get_by_role("navigation", name="Arquivos do workspace")).to_be_visible()
            source = page.get_by_role("button", name="README.md")
            source.focus()
            source.press("ArrowDown")
            expect(page.get_by_role("button", name="sample.pdf")).to_be_focused()
            page.keyboard.press("Control+b")
            expect(page.get_by_role("navigation", name="Arquivos do workspace")).to_have_count(0)
            page.keyboard.press("Control+k")
            expect(page.get_by_role("searchbox", name="Buscar nesta pasta (Ctrl+K)")).to_be_focused()
            page.get_by_role("searchbox", name="Buscar nesta pasta (Ctrl+K)").fill("sample")
            expect(page.get_by_role("button", name="README.md")).to_have_count(0)
            expect(page.get_by_role("button", name="sample.pdf")).to_be_visible()
            page.get_by_role("searchbox", name="Buscar nesta pasta (Ctrl+K)").fill("")
            page.keyboard.press("Control+i")
            expect(page.locator("aside.project-review-details")).to_be_visible()
            # A synthetic 100/125/150% environment plus explicit selected PDF raster DPI.
            page.get_by_role("button", name="sample.pdf").click()
            expect(page.locator(".project-review-page img")).to_be_visible()
            page.locator(".project-review-pdf-nav select").select_option(scale.replace("%", ""))
            expect(page.locator(".project-review-page img")).to_be_visible()
            assert any(call[1] == "pdf_visual" and call[2].get("dpi") == [str(dpi)]
                       for call in model.calls)
            assert model.saved == 0
            assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches") is True
            page.reload()
            expect(page.locator("aside.project-review-details")).to_be_visible()
            expect(page.get_by_role("navigation", name="Arquivos do workspace")).to_be_visible()
            page.keyboard.press("Escape")
            expect(dialog).to_have_count(0)
            page.locator("main > button").click()
            expect(dialog).to_be_visible()
            assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
            context.close()
        finally:
            browser.close()


def test_chromium_pdf_fallback_parser_missing_and_unauthorized_denied(vite):
    from playwright.sync_api import sync_playwright, expect
    model = MockCanvas()
    model.visual_status = 503
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context, page = _page(browser, vite, model)
            page.get_by_role("button", name="sample.pdf").click()
            expect(page.locator(".project-review-content pre")).to_contain_text("Fallback textual seguro")
            expect(page.get_by_role("status")).to_contain_text("local autenticada")
            expect(page.locator(".project-review-page img")).to_have_count(0)
            assert model.saved == 0
            assert any(a == "pdf_text" for _, a, _, _ in model.calls)
            model.visual_status = 401
            page.get_by_role("button", name="Atualizar arquivos").click()
            page.get_by_role("button", name="sample.pdf").click()
            expect(page.get_by_role("alert")).to_contain_text("access denied")
            # For 401/403, authorization must fail closed rather than fetch a text fallback.
            assert model.calls[-1][1] == "pdf_visual"
            context.close()
        finally:
            browser.close()


def test_chromium_owner_editor_review_never_saves_on_shortcut_or_focus_change(vite):
    from playwright.sync_api import sync_playwright, expect
    model = MockCanvas()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context, page = _page(browser, vite, model)
            page.get_by_role("button", name="README.md").click()
            expect(page.locator(".project-review-content pre")).to_contain_text("hello")
            page.get_by_role("button", name="Editar").click()
            editor = page.locator("textarea.project-review-editor")
            editor.fill("updated\n")
            editor.press("Control+s")
            expect(page.locator(".project-review-review pre")).to_contain_text("+updated")
            assert model.saved == 0
            save = page.locator(".project-review-review button")
            expect(save).to_be_disabled()
            page.locator(".project-review-review input[type=checkbox]").check()
            expect(save).to_be_enabled()
            # Editing after review invalidates ticket/consent.
            editor.fill("changed since review")
            expect(save).to_have_count(0)
            assert model.saved == 0
            editor.fill("updated\n")
            editor.press("Control+s")
            page.locator(".project-review-review input[type=checkbox]").check()
            page.locator(".project-review-review button").click()
            expect(page.get_by_role("status")).to_contain_text("Arquivo salvo")
            assert model.saved == 1
            context.close()
        finally:
            browser.close()


def test_chromium_concurrent_external_edit_marks_stale_and_disables_save(vite):
    from playwright.sync_api import sync_playwright, expect
    model = MockCanvas()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context, page = _page(browser, vite, model)
            page.get_by_role("button", name="README.md").click()
            page.get_by_role("button", name="Editar").click()
            editor = page.locator("textarea.project-review-editor")
            editor.fill("precious unsaved draft")
            model.preview_sha = SHA_B
            model.preview_text = "modified outside\n"
            expect(page.get_by_role("status")).to_contain_text("mudou no disco", timeout=6000)
            assert "precious unsaved draft" in editor.input_value()
            expect(editor).to_be_disabled()
            assert model.saved == 0
            context.close()
        finally:
            browser.close()

