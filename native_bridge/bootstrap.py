"""Install-local proof for secure Edge extension -> relay auto-pairing."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from .extension_sources import EXTENSION_IDENTITY_FILES, extension_source_identity
BOOTSTRAP_FILENAME = "sentra-bootstrap.json"
BOOTSTRAP_DOMAIN = b"sentra-edge-bootstrap-v1\0"


def extension_identity(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("extension manifest must be a JSON object")
    version = str(manifest.get("version") or "").strip()
    build_id = str(manifest.get("sentra_build_id") or "").strip()
    if not version or not build_id:
        raise ValueError("extension manifest requires version and sentra_build_id")

    identity = extension_source_identity(root)
    files, source_hash = identity['files'], identity['source_hash']
    declared = str(manifest.get("sentra_source_hash") or "").strip().lower()
    if declared and declared != source_hash:
        raise ValueError("extension manifest source hash is stale")
    return {
        "version": version,
        "build_id": build_id,
        "source_hash": source_hash,
        "files": files,
    }


def bootstrap_proof(token: str, identity: dict[str, Any]) -> str:
    token = str(token or "")
    if len(token) < 32:
        raise ValueError("relay token must contain at least 32 characters")
    material = json.dumps(
        {
            "schema_version": 1,
            "extension_version": str(identity["version"]),
            "build_id": str(identity["build_id"]),
            "source_hash": str(identity["source_hash"]),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(token.encode("utf-8"), BOOTSTRAP_DOMAIN + material, hashlib.sha256).hexdigest()


def extension_bootstrap_payload(root: Path, token: str) -> dict[str, Any]:
    identity = extension_identity(root)
    return {
        "schema_version": 1,
        "extension_version": identity["version"],
        "build_id": identity["build_id"],
        "source_hash": identity["source_hash"],
        "proof": bootstrap_proof(token, identity),
    }


def write_extension_bootstrap(root: Path, token: str) -> dict[str, Any]:
    root = Path(root).resolve()
    payload = extension_bootstrap_payload(root, token)
    target = root / BOOTSTRAP_FILENAME
    temp = target.with_suffix(".tmp")
    temp.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(target)
    return payload
