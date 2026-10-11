"""The real local bearer-protected Canvas GET exposes the passive PDFium projection.

The production renderer and its parser limits are tested in Chat 5's own
project_review suite. A monkeypatch here proves the HTTP host-to-service
wiring without forcing PDFium installation on the developer machine.
"""
from pathlib import Path
from urllib.parse import urlencode

from test_sentra_runtime_canvas_center_http import running_canvas, request


def url(ws, **extra):
    return "/api/center/project-review?" + urlencode({"ws": ws, **extra})


def test_pdf_visual_get_owner_authenticated_and_read_only(tmp_path, monkeypatch):
    from sentra_canvas import project_review
    calls = []

    def fake_render(root, relative, *, page=1, dpi=72):
        calls.append((Path(root), relative, page, dpi))
        return {
            "path": relative, "page": page, "pages": 1, "dpi": dpi,
            "image_base64": "iVBORw0KGgo=", "mime": "image/png",
            "source_sha256": "e"*64, "read_only": True, "rendered": True,
            "ocr_used": False, "grants_created": False,
        }

    monkeypatch.setattr(project_review, "pdf_visual_page", fake_render)
    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("VisualPdf")["id"]
        owner = app._runtime().owner
        path = url(ws, action="pdf_visual", path="report.pdf", page=1, dpi=90)
        assert request(server, path, authorized=False)[0] == 401
        assert calls == []
        code, view = request(server, path)
        assert code == 200, view
        assert view["page"] == 1 and view["dpi"] == 90
        assert view["mime"] == "image/png"
        assert view["read_only"] and not view["grants_created"]
        assert view["source_sha256"] == "e"*64
        assert calls == [(Path(app.store.workspace(ws)["path"]), "report.pdf", 1, 90)]
        assert app._machine_service().control.authorization.list_grants(owner)["items"] == []
        assert request(server, url(ws, action="save", path="report.pdf"))[0] == 403


def test_pdf_visual_direct_handler_fails_closed_on_invalid_path_dpi(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace("PdfBounds")["id"]
        (Path(app.store.workspace(ws)["path"])/"fake.pdf").write_bytes(b"%PDF-fake")
        # Rejected *before* any native renderer execution.
        assert request(server, url(ws, action="pdf_visual",
                                   path="fake.pdf", dpi=96))[0] != 200
        assert request(server, url(ws, action="pdf_visual",
                                   path="../secret.pdf", dpi=72))[0] != 200
        assert request(server, url(ws, action="pdf_visual",
                                   path="fake.pdf", page=201))[0] != 200


def test_pdf_visual_only_native_unavailable_and_timeout_map_to_503(tmp_path, monkeypatch):
    """A missing/hung PDFium gives a safe text-fallback code, not global 500."""
    from sentra_canvas import project_review

    with running_canvas(tmp_path) as (app, server):
        ws=app.create_workspace("VisualUnavailable")["id"]
        endpoint=url(ws, action="pdf_visual", path="document.pdf", page=1, dpi=72)

        def unavailable(*args, **kwargs):
            raise RuntimeError("PDFium is not installed; visual PDF preview disabled")

        monkeypatch.setattr(project_review, "pdf_visual_page", unavailable)
        code, payload=request(server,endpoint)
        assert code==503, payload
        assert payload["error"] == "visual PDF preview unavailable"
        assert request(server,endpoint,authorized=False)[0]==401

        def timed_out(*args, **kwargs):
            raise TimeoutError("native PDF renderer timeout")

        monkeypatch.setattr(project_review, "pdf_visual_page", timed_out)
        assert request(server,endpoint)[0]==503

        def unknown_failure(*args, **kwargs):
            raise RuntimeError("unexpected parser programming error")

        monkeypatch.setattr(project_review, "pdf_visual_page", unknown_failure)
        assert request(server,endpoint)[0]==500
        assert app._machine_service().control.authorization.list_grants(
            app._runtime().owner)["items"] == []
