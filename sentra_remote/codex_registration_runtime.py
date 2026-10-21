"""Pinned offline CLI used only for the supported local plugin commands."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from .windows_paths import filesystem_path

VERSION = "0.163.0"
REVISION = "83086188ae0614bd882818ff1aa23f3194962012"
ARCHIVE_URL = "https://github.com/openai/codex/releases/download/rust-v0.163.0/codex-x86_64-pc-windows-msvc.exe.zip"
ARCHIVE_SHA256 = "dabdb4d16aaf10fea40b74811c96efddcd9138f122163b69ed604fcb3eb704c3"
ARCHIVE_MEMBER = "codex-x86_64-pc-windows-msvc.exe"
FILES = {
    "codex.exe": "2692c8c7bb2cf8b0aefe638741fc90236f4b824c59578ce84994f9de58200993",
    "LICENSE": "d17f227e4df5da1600391338865ce0f3055211760a36688f816941d58232d8dc",
    "NOTICE": "9d71575ecfd9a843fc1677b0efb08053c6ba9fd686a0de1a6f5382fd3c220915",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provenance() -> dict:
    return {"version": VERSION, "revision": REVISION, "archive_url": ARCHIVE_URL,
            "archive_sha256": ARCHIVE_SHA256, "archive_member": ARCHIVE_MEMBER,
            "purpose": "local-plugin-registration", "binary_modified": False,
            "files": FILES}


def validate_registration_runtime(folder: Path) -> Path:
    folder = Path(filesystem_path(folder, resolve=False))
    # The caller selects an owned installation directory. Reject linked
    # ancestors too, rather than checking only the final executable.
    if any(path.is_symlink() or path.is_junction() for path in (folder, *folder.parents)):
        raise ValueError("Codex registration runtime is linked")
    if not folder.is_dir() or {path.name for path in folder.iterdir()} != {*FILES, "provenance.json"}:
        raise ValueError("Codex registration runtime is incomplete")
    for name, expected in FILES.items():
        path = folder / name
        if not path.is_file() or path.is_symlink() or path.is_junction() or file_sha256(path) != expected:
            raise ValueError("Codex registration runtime checksum mismatch")
    record = folder / "provenance.json"
    if record.is_symlink() or not record.is_file() or record.stat().st_size > 16384:
        raise ValueError("Codex registration runtime provenance is invalid")
    if json.loads(record.read_text(encoding="utf-8")) != provenance():
        raise ValueError("Codex registration runtime provenance mismatch")
    return folder / "codex.exe"
