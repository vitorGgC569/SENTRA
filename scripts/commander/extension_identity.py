from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

EXTENSION_IDENTITY_FILES = (
    "service-worker.js",
    "content-script.js",
    "recovery-guard.js",
    "selectors.js",
    "observer.js",
    "conversation-evidence.js",
    "COS-NOTICE.txt",
)


def extension_source_identity(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    files: dict[str, dict[str, str]] = {}
    for name in EXTENSION_IDENTITY_FILES:
        target = root / name
        if not target.is_file():
            raise FileNotFoundError(f"extension identity file missing: {target}")
        files[name] = {
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
    source_hash = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "source_hash": source_hash,
        "files": files,
    }


def stamp_extension_identity(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"extension manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("extension manifest must be a JSON object")
    build_id = str(manifest.get("sentra_build_id") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not build_id:
        raise ValueError("extension manifest requires sentra_build_id")
    if not version:
        raise ValueError("extension manifest requires version")

    identity = extension_source_identity(root)
    manifest["sentra_source_hash"] = identity["source_hash"]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "version": version,
        "build_id": build_id,
        **identity,
    }


def stage_extension_source(source: Path, destination: Path) -> dict[str, Any]:
    """Final-phase source pipeline. Never restamps the live/source extension.

    Installation-local HMAC bootstrap cannot be distributed to another machine.
    The installed relay creates it with its real local token after installation.
    """
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination.resolve().is_relative_to(source):
        raise PermissionError("extension staging must be a new isolated directory")
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in source.rglob('*')):
        raise PermissionError("linked extension source cannot be shipped")
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('sentra-bootstrap.json', '*.tmp', '__pycache__'))
    identity = stamp_extension_identity(destination)
    record = {**identity, "bootstrap": "installation-local-HMAC-required", "source_mutated": False}
    (destination / 'sentra-distribution.json').write_text(json.dumps(record, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return record
