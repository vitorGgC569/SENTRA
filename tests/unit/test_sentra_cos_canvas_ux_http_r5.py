"""R5: real CanvasServer HTTP and SQLite under isolated tmp_path.

Runs the genuine localhost CanvasHandler, not a mocked JSON HTTP response.
The QA Vite origin is a test-only view; Playwright forwards requests to the
actual CanvasServer with its freshly generated, short-lived owner bearer.
No live ChatGPT/Edge profile and no effects or grants.
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest
from pypdf import PdfWriter
from test_sentra_runtime_canvas_center_http import running_canvas, request
from test_sentra_cos_canvas_ux_browser import vite


def _pdf(path: Path):
    pdf = PdfWriter()
    pdf.add_blank_page(width=144, height=96)
    with path.open("wb") as output:
        pdf.write(output)
    return path


def _protected_rows(root: Path) -> dict:
    """Count grant/operation-like rows in *this test's* SQLite files only."""
    result = {}
    for db in (*root.rglob("*.sqlite"), *root.rglob("*.db")):
        with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2) as connection:
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                if any(word in name.casefold() for word in ("grant", "operation", "approval")):
                    result[(str(db.relative_to(root)), name)] = connection.execute(
                        'SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
    return result


def test_real_canvas_http_owner_scope_and_visual_contract(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("OwnerPDF")["id"]
        foreign = app.create_workspace("ForeignPDF")["id"]
        source = _pdf(Path(app.store.workspace(ws)["path"]) / "document.pdf")
        (Path(app.store.workspace(ws)["path"]) / "notes.md").write_text(
            "safe read only\n", encoding="utf-8")
        before = source.read_bytes()
        root_url = f"/api/center/project-review?ws={ws}&path=document.pdf"
        status, text = request(server, root_url + "&action=pdf_text&page=1")
        assert status == 200 and text["read_only"] and not text["ocr_used"]
        assert text["source_sha256"] == hashlib.sha256(before).hexdigest()
        status, _ = request(server, root_url + "&action=pdf_text&page=1", authorized=False)
        assert status == 401
        status, _ = request(server,
            f"/api/center/project-review?ws={foreign}&action=pdf_text&path=document.pdf&page=1")
        assert status != 200
        status, _ = request(server,
            f"/api/center/project-review?ws={ws}&action=pdf_text&path=..%2Fdocument.pdf")
        assert status == 403
        baseline = _protected_rows(tmp_path)
        status, visual = request(server, root_url + "&action=pdf_visual&page=1&dpi=72")
        # Until coordinator allows pdf_visual GET, this must remain denied;
        # when integrated, enforce passive image envelope and no OCR/grants.
        assert status in (200, 403), (status, visual)
        if status == 200:
            png = base64.b64decode(visual["image_base64"], validate=True)
            assert png.startswith(b"\x89PNG\r\n\x1a\n")
            assert visual["source_sha256"] == hashlib.sha256(before).hexdigest()
            assert visual["mime"] == "image/png" and visual["read_only"]
            assert not visual["grants_created"] and not visual["ocr_used"]
            assert (visual["width"], visual["height"], visual["dpi"]) == (144, 96, 72)
        else:
            assert "error" in visual
        assert source.read_bytes() == before
        assert _protected_rows(tmp_path) == baseline


def test_real_canvas_host_and_origin_protection(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("OriginProtected")["id"]
        (_pdf(Path(app.store.workspace(ws)["path"]) / "page.pdf"))
        uri = f"http://127.0.0.1:{server.server_port}/api/center/project-review?ws={ws}&action=pdf_text&path=page.pdf"
        def get(headers):
            req = Request(uri, headers=headers)
            try:
                with urlopen(req, timeout=5) as response:
                    return response.status
            except HTTPError as error:
                return error.code
        bearer = "Bearer " + server.secret
        assert get({"Authorization": bearer}) == 200
        assert get({"Authorization": "Bearer wrong"}) == 401
        assert get({"Authorization": bearer, "Origin": "https://attacker.invalid"}) == 403
        assert get({"Authorization": bearer, "Host": "attacker.invalid"}) == 403
        assert get({"Authorization": bearer, "Sec-Fetch-Site": "cross-site"}) == 403


def test_chromium_dom_to_actual_canvas_http_owner_pdf_and_no_effects(tmp_path, vite):
    from playwright.sync_api import sync_playwright, expect

    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("BrowserOwner")["id"]
        workspace = Path(app.store.workspace(ws)["path"])
        pdf = _pdf(workspace / "invoice.pdf")
        source = pdf.read_bytes()
        (workspace / "notes.md").write_text("live local preview\n", encoding="utf-8")
        # The QA React harness defaults to qa-workspace; substitute ONLY the
        # test-only HTML bootstrap identifier, without changing production JSX.
        # Server still validates the actual workspace id from every request.
        assert ws != "qa-workspace"
        status, first = request(
            server, f"/api/center/project-review?ws={ws}&action=list&path=")
        assert status == 200
        assert any(item["name"] == "invoice.pdf" for item in first["items"])
        baseline = _protected_rows(tmp_path)
        proxy_requests = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1100, "height": 820},
                                              reduced_motion="reduce")
                page = context.new_page()
                page.set_default_timeout(9000)
                page.add_init_script(
                    "window.__QA_WORKSPACE_ID = " + repr(ws) + ";")
                def forward(route):
                    req = route.request
                    parsed = urlsplit(req.url)
                    proxy_requests.append((req.method, parsed.path, parsed.query))
                    # Real HTTP, real CanvasHandler and real per-fixture owner
                    # authorization; no route.fulfill JSON mocking.
                    target = (f"http://127.0.0.1:{server.server_port}" +
                              parsed.path + ("?" + parsed.query if parsed.query else ""))
                    headers = {"Authorization": req.headers.get("authorization", ""),
                               "Content-Type": "application/json"}
                    result = route.fetch(url=target, method=req.method, headers=headers,
                                         post_data=req.post_data if req.method == "POST" else None)
                    route.fulfill(response=result)
                page.route("**/api/center/project-review**", forward)
                page.goto(vite +
                    "/desktop-assets/src/qa/project-review-test.html#token=" + server.secret)
                modal = page.get_by_role("dialog", name="Arquivos do projeto")
                expect(modal).to_be_visible()
                expect(modal).to_have_attribute("aria-modal", "true")
                expect(page.get_by_role("button", name="invoice.pdf")).to_be_visible()
                page.get_by_role("button", name="notes.md").click()
                expect(page.locator(".project-review-content pre")).to_contain_text(
                    "live local preview")
                page.get_by_role("button", name="Atualizar arquivos").click()
                page.get_by_role("button", name="invoice.pdf").click()
                # Real CanvasServer now emits a native PDFium PNG at default
                # 72dpi; UI validates the owner-bound passive response.
                expect(page.locator(".project-review-page img")).to_be_visible()
                expect(page.get_by_role("alert")).to_have_count(0)
                expect(page.get_by_role("status")).to_have_count(0)
                assert page.locator(".project-review-page img").get_attribute(
                    "src").startswith("data:image/png;base64,")
                # Strict frontend safety: coordinator currently does not parse
                # requested dpi (125/150%). Do not show mislabeled raster.
                with page.expect_response(lambda response: "action=pdf_visual" in response.url
                        and "dpi=108" in response.url, timeout=10000) as loading:
                    page.locator(".project-review-pdf-nav select").select_option("150")
                assert loading.value.status == 200
                status_108, visual_108 = request(server,
                    f"/api/center/project-review?ws={ws}&path=invoice.pdf&action=pdf_visual&page=1&dpi=108")
                assert status_108 == 200
                if visual_108["dpi"] == 108:
                    expect(page.locator(".project-review-page img")).to_be_visible()
                    expect(page.get_by_role("alert")).to_have_count(0)
                else:
                    # Central currently ignores dpi; fail closed and report to
                    # coordinator instead of displaying an incorrectly scaled PNG.
                    assert visual_108["dpi"] == 72
                    expect(page.get_by_role("alert")).to_contain_text("PDF visual", timeout=10000)
                assert all(method == "GET" for method, *_ in proxy_requests)
                assert page.locator('input[type="file"]').count() == 0
                assert not any("upload" in query for _, _, query in proxy_requests)
                assert pdf.read_bytes() == source
                assert _protected_rows(tmp_path) == baseline
                context.close()
            finally:
                browser.close()


def test_real_canvas_missing_pdfium_is_closed_and_text_stays_owner_auth(tmp_path, monkeypatch):
    import importlib.util
    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("MissingPdfium")["id"]
        source = _pdf(Path(app.store.workspace(ws)["path"]) / "fallback.pdf")
        before = source.read_bytes()
        url = f"/api/center/project-review?ws={ws}&path=fallback.pdf"
        initial_counts = _protected_rows(tmp_path)
        original = importlib.util.find_spec
        with monkeypatch.context() as patch:
            patch.setattr(importlib.util, "find_spec",
                lambda name: None if name == "pypdfium2" else original(name))
            code, body = request(server, url + "&action=pdf_visual&page=1&dpi=72")
        # Coordinator currently converts runtime unavailability to HTTP 500.
        # Chat 5 must not silently fall back on 500; coordinator to map 503.
        assert code in (500, 503), (code, body)
        assert "error" in body and "image_base64" not in body
        assert request(server, url + "&action=pdf_text&page=1")[0] == 200
        assert request(server, url + "&action=pdf_text&page=1", authorized=False)[0] == 401
        assert source.read_bytes() == before
        assert _protected_rows(tmp_path) == initial_counts
