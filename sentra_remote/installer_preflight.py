"""Read-only checks of the complete Setup payload before changing an installation."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

MANIFEST = "setup-payload.json"


def payload_files(source, extension, docs, products):
    roots = {"payload": Path(source), "edge_extension": Path(extension), "docs": Path(docs)}
    for prefix, root in roots.items():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if prefix == "payload" and not (relative in products or relative == "runtime-components.json"
                    or relative.split("/")[0] in {"web-models", "sentra-electron", "runtime", "prerequisites"}):
                continue
            if path.is_symlink():
                raise ValueError("Setup payload must not contain symbolic links")
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            yield prefix + "/" + relative, path


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_payload_manifest(source, extension, docs, version, products):
    files = {name: {"sha256": file_hash(path), "bytes": path.stat().st_size}
             for name, path in payload_files(source, extension, docs, products)}
    value = {"schema": 1, "version": version, "files": files}
    target = Path(source) / MANIFEST
    pending = target.with_suffix(".tmp")
    pending.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    pending.replace(target)
    return target


def inspect_payload(source, extension, docs, products, *, version, require_manifest=False,
                    destination=None):
    source, extension, docs = Path(source), Path(extension), Path(docs)
    required = [(name, source / name) for name in products]
    required += [
        ("Edge bridge", extension / "manifest.json"),
        ("Web Models", source / "web-models/win-unpacked/Codex Web GPT.exe"),
        ("Web Models runtime", source / "web-models/win-unpacked/resources/runtime/manifest.json"),
        ("Web Models provenance", source / "web-models/integration-build.json"),
        ("Web Models license", source / "web-models/licenses/codex-chatgpt-web/LICENSE"),
        ("Getting started", docs / "START_HERE.md"),
        ("Onboarding guide", docs / "SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md"),
    ]
    if require_manifest:
        required += [("Bundled desktop", source / "sentra-electron/electron.exe"),
                     ("Runtime components", source / "runtime-components.json"),
                     ("Offline tunnel client", source / "prerequisites/tunnel-client.zip")]
    missing = [name for name, path in required if not path.is_file() or path.stat().st_size == 0]
    manifest = source / MANIFEST
    verified = False
    byte_count = sum(p.stat().st_size for _, p in required if p.is_file())
    if require_manifest and not manifest.is_file():
        missing.append(MANIFEST)
    if manifest.is_file():
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if value.get("schema") != 1 or value.get("version") != version or not isinstance(value.get("files"), dict):
            raise ValueError("invalid Setup payload manifest")
        actual = dict(payload_files(source, extension, docs, products))
        if set(actual) != set(value["files"]):
            raise ValueError("Setup payload manifest file set mismatch")
        for name, path in actual.items():
            expected = value["files"][name]
            if expected.get("bytes") != path.stat().st_size or expected.get("sha256") != file_hash(path):
                raise ValueError("Setup payload checksum mismatch: " + name)
        byte_count = sum(p.stat().st_size for p in actual.values())
        verified = True
    free_bytes = None
    if destination is not None:
        existing = Path(destination).resolve()
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        free_bytes = shutil.disk_usage(existing).free
        if free_bytes < byte_count + 256 * 1024 * 1024:
            missing.append("free_disk_space")
    return {"ok": not missing, "missing": missing, "verified": verified,
            "payload_bytes": byte_count, "free_bytes": free_bytes,
            "python_required_on_client": False, "node_required_on_client": False}
