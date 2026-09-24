"""Bounded, workspace-aware structured document helpers."""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

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
    catalog_id, pages_id, font_id = 1, 2, 3
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"PLACEHOLDER")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    for page_lines in pages:
        content = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        content += [f"({_pdf_escape(title)}) Tj", "T*"]
        for line in page_lines:
            content += [f"({_pdf_escape(line)}) Tj", "T*"]
        content += ["ET"]
        stream = "\n".join(content).encode("cp1252", errors="replace")
        content_id = len(objects) + 1
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = (
        f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>"
    ).encode("ascii")
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
    SUPPORTED = {".pdf", ".docx", ".csv", ".parquet", ".jsonl", ".ipynb"}

    def __init__(self, filesystem: FilesystemService, audit: AuditLogger) -> None:
        self.filesystem = filesystem
        self.audit = audit

    def _target(
        self,
        path: str,
        *,
        workspace: str | None,
        owner: str | None,
        permission: str = "read",
    ) -> tuple[Path, str, dict[str, Any]]:
        _, target, rel, view = self.filesystem._resolve_access(
            path,
            workspace=workspace,
            owner=owner,
            permission=permission,
        )
        return target, rel, view

    @staticmethod
    def _workspace(view: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace": view["id"],
            "workspace_id": view["workspace_id"],
            "workspace_alias": view["alias"],
        }

    def document_info(
        self,
        path: str,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        target, rel, view = self._target(
            path, workspace=workspace, owner=owner, permission="read"
        )
        if not target.is_file():
            raise FileNotFoundError("document not found")
        suffix = target.suffix.casefold()
        size = target.stat().st_size
        info: dict[str, Any] = {
            "path": rel,
            "suffix": suffix,
            "size": size,
            "structured_read_supported": suffix in self.SUPPORTED,
            **self._workspace(view),
        }
        if size > self.filesystem.max_read_bytes:
            info["over_read_limit"] = True
            return info
        if suffix == ".pdf":
            raw = target.read_bytes()
            info.update({
                "type": "pdf",
                "pages_approx": len(re.findall(rb"/Type\s*/Page\b", raw)),
                "pdf_header": raw.startswith(b"%PDF-"),
            })
        elif suffix == ".docx":
            info["type"] = "docx"
        elif suffix == ".csv":
            info["type"] = "csv"
        elif suffix == ".parquet":
            info["type"] = "parquet"
        elif suffix == ".jsonl":
            info["type"] = "jsonl"
        elif suffix == ".ipynb":
            info["type"] = "notebook"
        else:
            info["type"] = "file"
        return info

    @staticmethod
    def _bounds(offset: int, limit: int) -> tuple[int, int]:
        if offset < 0:
            raise ValueError("offset must be zero or greater")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        return offset, limit

    def _read_pdf(self, target: Path, offset: int, limit: int) -> dict[str, Any]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF text extraction requires the pypdf dependency") from exc
        reader = PdfReader(str(target), strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception as exc:
                raise PermissionError("encrypted PDF cannot be read without credentials") from exc
            if not unlocked:
                raise PermissionError("encrypted PDF cannot be read without credentials")
        total = len(reader.pages)
        selected = []
        chars = 0
        for index in range(offset, min(total, offset + limit)):
            text = reader.pages[index].extract_text() or ""
            chars += len(text.encode("utf-8"))
            if chars > self.filesystem.max_read_bytes:
                raise ValueError("extracted PDF text exceeds configured read limit")
            selected.append({"page": index + 1, "text": text})
        return {
            "type": "pdf",
            "total_pages": total,
            "offset": offset,
            "returned": len(selected),
            "pages": selected,
        }

    def _read_docx(self, target: Path, offset: int, limit: int) -> dict[str, Any]:
        with zipfile.ZipFile(target) as archive:
            try:
                info = archive.getinfo("word/document.xml")
            except KeyError as exc:
                raise ValueError("DOCX is missing word/document.xml") from exc
            if info.file_size > self.filesystem.max_read_bytes:
                raise ValueError("DOCX XML exceeds configured read limit")
            raw = archive.read(info)
        root = ET.fromstring(raw)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        blocks: list[dict[str, Any]] = []
        for paragraph in root.iter(namespace + "p"):
            text = "".join(node.text or "" for node in paragraph.iter(namespace + "t"))
            if text:
                blocks.append({"type": "paragraph", "text": text})
        selected = blocks[offset : offset + limit]
        return {
            "type": "docx",
            "total_blocks": len(blocks),
            "offset": offset,
            "returned": len(selected),
            "blocks": selected,
        }

    def _read_csv(self, target: Path, offset: int, limit: int) -> dict[str, Any]:
        raw = target.read_bytes()
        if len(raw) > self.filesystem.max_read_bytes:
            raise ValueError("CSV exceeds configured read limit")
        text = raw.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return {"type": "csv", "columns": [], "total_rows": 0, "rows": []}
        columns = [str(value) for value in rows[0]]
        data = rows[1:]
        selected = [
            {columns[idx] if idx < len(columns) and columns[idx] else f"column_{idx+1}": value
             for idx, value in enumerate(row)}
            for row in data[offset : offset + limit]
        ]
        return {
            "type": "csv",
            "columns": columns,
            "total_rows": len(data),
            "offset": offset,
            "returned": len(selected),
            "rows": selected,
        }

    def _read_jsonl(self, target: Path, offset: int, limit: int) -> dict[str, Any]:
        raw = target.read_bytes()
        if len(raw) > self.filesystem.max_read_bytes:
            raise ValueError("JSONL exceeds configured read limit")
        lines = raw.decode("utf-8-sig").splitlines()
        selected: list[dict[str, Any]] = []
        for index, line in enumerate(lines[offset : offset + limit], start=offset):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {index + 1}") from exc
            selected.append({"line": index + 1, "value": value})
        return {
            "type": "jsonl",
            "total_lines": len(lines),
            "offset": offset,
            "returned": len(selected),
            "items": selected,
        }

    def _read_notebook(self, target: Path, offset: int, limit: int) -> dict[str, Any]:
        raw = target.read_bytes()
        if len(raw) > self.filesystem.max_read_bytes:
            raise ValueError("notebook exceeds configured read limit")
        data = json.loads(raw.decode("utf-8-sig"))
        cells = data.get("cells")
        if not isinstance(cells, list):
            raise ValueError("invalid notebook: cells must be an array")
        selected: list[dict[str, Any]] = []
        for index, cell in enumerate(cells[offset : offset + limit], start=offset):
            if not isinstance(cell, dict):
                continue
            source = cell.get("source", [])
            if isinstance(source, list):
                source = "".join(str(item) for item in source)
            item = {
                "index": index,
                "cell_type": cell.get("cell_type"),
                "source": str(source),
                "execution_count": cell.get("execution_count"),
            }
            outputs = cell.get("outputs")
            if isinstance(outputs, list):
                item["output_count"] = len(outputs)
            selected.append(item)
        return {
            "type": "notebook",
            "nbformat": data.get("nbformat"),
            "total_cells": len(cells),
            "offset": offset,
            "returned": len(selected),
            "cells": selected,
        }

    def _read_parquet(self, target: Path, offset: int, limit: int) -> dict[str, Any]:
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("Parquet reading requires pyarrow") from exc
        parquet = pq.ParquetFile(target)
        total = int(parquet.metadata.num_rows)
        rows: list[dict[str, Any]] = []
        seen = 0
        for batch in parquet.iter_batches(batch_size=min(1024, max(64, limit))):
            pyrows = batch.to_pylist()
            if seen + len(pyrows) <= offset:
                seen += len(pyrows)
                continue
            start = max(0, offset - seen)
            take = pyrows[start : start + (limit - len(rows))]
            rows.extend(take)
            seen += len(pyrows)
            if len(rows) >= limit:
                break
        return {
            "type": "parquet",
            "columns": list(parquet.schema.names),
            "total_rows": total,
            "row_groups": parquet.num_row_groups,
            "offset": offset,
            "returned": len(rows),
            "rows": rows,
        }

    def read_document(
        self,
        path: str,
        *,
        workspace: str | None = None,
        owner: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        offset, limit = self._bounds(offset, limit)
        target, rel, view = self._target(
            path, workspace=workspace, owner=owner, permission="read"
        )
        if not target.is_file():
            raise FileNotFoundError("document not found")
        if target.stat().st_size > self.filesystem.max_read_bytes:
            raise ValueError("document exceeds configured read limit")
        suffix = target.suffix.casefold()
        if suffix == ".pdf":
            result = self._read_pdf(target, offset, limit)
        elif suffix == ".docx":
            result = self._read_docx(target, offset, limit)
        elif suffix == ".csv":
            result = self._read_csv(target, offset, limit)
        elif suffix == ".parquet":
            result = self._read_parquet(target, offset, limit)
        elif suffix == ".jsonl":
            result = self._read_jsonl(target, offset, limit)
        elif suffix == ".ipynb":
            result = self._read_notebook(target, offset, limit)
        else:
            raise ValueError(
                "structured document read supports PDF, DOCX, CSV, Parquet, JSONL and ipynb"
            )
        result.update({"path": rel, **self._workspace(view)})
        self.audit.emit(
            "document.read",
            "ok",
            {
                "path": rel,
                "type": result["type"],
                "workspace": view["id"],
                "offset": offset,
                "limit": limit,
            },
        )
        return result

    def write_pdf(
        self,
        path: str,
        text: str,
        title: str = "SENTRA Document",
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        if not path.casefold().endswith(".pdf"):
            raise ValueError("PDF output path must end in .pdf")
        payload = _build_pdf(text, title)
        if len(payload) > self.filesystem.max_write_bytes:
            raise ValueError("PDF exceeds configured write limit")
        target, rel, view = self._target(
            path, workspace=workspace, owner=owner, permission="write"
        )
        if target.exists() and target.is_dir():
            raise IsADirectoryError("PDF target is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        self.audit.emit(
            "document.write_pdf",
            "ok",
            {"path": rel, "bytes": len(payload), "workspace": view["id"]},
        )
        return {
            "path": rel,
            "bytes": len(payload),
            "pages_approx": len(re.findall(rb"/Type\s*/Page\b", payload)),
            **self._workspace(view),
        }
