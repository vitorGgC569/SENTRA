from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EXTENSION_IDENTITY_FILES = (
    "service-worker.js",
    "content-script.js",
    "selectors.js",
    "observer.js",
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
