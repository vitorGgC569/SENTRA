"""Build-time pinned PDFium policy for native SENTRA Canvas PDF previews.

Only the CI/build host fetches the SHA-256-verified wheel; no PyPI call from
Setup, the installed Canvas, or the PDF preview subprocess.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path

PDFIUM_VERSION = "4.30.0"
PDFIUM_WHEEL = "pypdfium2-4.30.0-py3-none-win_amd64.whl"
PDFIUM_SHA256 = "90dbb2ac07be53219f56be09961eb95cf2473f834d01a42d901d13ccfad64b4c"


def verify_wheel(wheel: Path) -> None:
    if wheel.name != PDFIUM_WHEEL or not wheel.is_file() or wheel.is_symlink():
        raise ValueError("wrong PDFium wheel for Windows x64 release")
    digest = hashlib.sha256()
    with wheel.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != PDFIUM_SHA256:
        raise ValueError("PDFium wheel SHA256 mismatch")


def require_pdfium() -> None:
    try:
        version = importlib.metadata.version("pypdfium2")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("pinned pypdfium2 4.30.0 required at build time") from exc
    if version != PDFIUM_VERSION:
        raise RuntimeError("pypdfium2 build version mismatch; require exactly 4.30.0")
