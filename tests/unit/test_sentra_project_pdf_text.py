"""Authenticated, read-only, bounded PDF text page preview."""
from pathlib import Path
import pytest
from pypdf import PdfWriter
from sentra_canvas.project_review import pdf_text_page
from test_sentra_runtime_canvas_center_http import running_canvas,request


def pdf(path):
    writer=PdfWriter()
    writer.add_blank_page(width=200,height=150)
    writer.add_blank_page(width=300,height=200)
    with Path(path).open("wb") as handle:
        writer.write(handle)
    return path


def test_pdf_page_preview_and_boundaries(tmp_path):
    pdf(tmp_path/"test.pdf")
    first=pdf_text_page(tmp_path,"test.pdf",page=1)
    assert first["pages"]==2 and first["page"]==1
    assert first["text"]=="" and first["rendered"] is False and not first["ocr_used"]
    assert pdf_text_page(tmp_path,"test.pdf",page=2)["pages"]==2
    with pytest.raises(ValueError,match="page"):
        pdf_text_page(tmp_path,"test.pdf",page=3)
    with pytest.raises(ValueError,match="page"):
        pdf_text_page(tmp_path,"test.pdf",page=0)
    with pytest.raises(PermissionError):
        pdf_text_page(tmp_path,"../test.pdf")
    (tmp_path/"invalid.pdf").write_bytes(b"%PDF-not-a-valid-document")
    with pytest.raises(Exception):
        pdf_text_page(tmp_path,"invalid.pdf")


def test_pdf_canvas_http_access_and_no_write(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        workspace=app.create_workspace("PdfSource")
        ws=workspace["id"]
        other=app.create_workspace("PdfOther")["id"]
        source=pdf(Path(workspace["path"])/"page.pdf")
        before=source.read_bytes()
        uri=f"/api/center/project-review?ws={ws}&action=pdf_text&path=page.pdf&page=2"
        status,page=request(server,uri)
        assert status==200 and page["page"]==2 and page["pages"]==2
        assert not page["rendered"]
        assert source.read_bytes()==before
        assert request(server,uri,authorized=False)[0]==401
        assert request(server,uri.replace(f"ws={ws}",f"ws={other}"))[0]!=200
        assert request(server,uri.replace("page=2","page=300"))[0]==400
