"""Bounded document helpers; PDF writer is dependency-free and filesystem-confined."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..audit import AuditLogger
from .filesystem import FilesystemService


def _pdf_escape(text: str) -> str:
    raw = text.encode("cp1252", errors="replace").decode("cp1252")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_pdf(text: str, title: str = "SENTRA Document") -> bytes:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    pages: list[list[str]] = []
    page: list[str] = []
    for line in lines:
        while len(line) > 100:
            page.append(line[:100])
            line = line[100:]
            if len(page) >= 45:
                pages.append(page)
                page = []
        page.append(line)
        if len(page) >= 45:
            pages.append(page)
            page = []
    if page or not pages:
        pages.append(page)

    objects: list[bytes] = []
    catalog_id = 1
    pages_id = 2
    font_id = 3
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"PLACEHOLDER")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    for page_lines in pages:
        content = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        safe_title = _pdf_escape(title)
        content += [f"({safe_title}) Tj", "T*"]
        for line in page_lines:
            content += [f"({_pdf_escape(line)}) Tj", "T*"]
        content += ["ET"]
        stream = "\n".join(content).encode("cp1252", errors="replace")
        content_id = len(objects) + 1
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("ascii")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer\n<< /Size {len(objects)+1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


class DocumentService:
    def __init__(self, filesystem: FilesystemService, audit: AuditLogger) -> None:
        self.filesystem = filesystem
        self.audit = audit

    def document_info(self, path: str) -> dict[str, Any]:
        _, target, rel = self.filesystem._resolve(path)
        if not target.is_file():
            raise FileNotFoundError("document not found")
        suffix = target.suffix.casefold()
        info: dict[str, Any] = {
            "path": rel,
            "suffix": suffix,
            "size": target.stat().st_size,
        }
        if suffix == ".pdf":
            if target.stat().st_size > self.filesystem.max_read_bytes:
                raise ValueError("document exceeds read limit")
            raw = target.read_bytes()
            info["type"] = "pdf"
            info["pages_approx"] = len(re.findall(rb"/Type\s*/Page\b", raw))
            info["pdf_header"] = raw.startswith(b"%PDF-")
        elif suffix in {".docx", ".xlsx", ".pptx"}:
            info["type"] = suffix[1:]
        else:
            info["type"] = "file"
        return info

    def write_pdf(self, path: str, text: str, title: str = "SENTRA Document") -> dict[str, Any]:
        if not path.casefold().endswith(".pdf"):
            raise ValueError("PDF output path must end in .pdf")
        payload = _build_pdf(text, title)
        if len(payload) > self.filesystem.max_write_bytes:
            raise ValueError("PDF exceeds configured write limit")
        _, target, rel = self.filesystem._resolve(path)
        if target.exists() and target.is_dir():
            raise IsADirectoryError("PDF target is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        self.audit.emit("document.write_pdf", "ok", {"path": rel, "bytes": len(payload)})
        return {"path": rel, "bytes": len(payload), "pages_approx": len(re.findall(rb"/Type\s*/Page\b", payload))}
