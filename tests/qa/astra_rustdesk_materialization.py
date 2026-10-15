"""Verify materialized bytes/source inventory; never starts a desktop session."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.commander import materialize_rustdesk as materializer
from scripts.commander.release_components import _native_payload


def verify(artifact: Path) -> dict:
    artifact = artifact.resolve(strict=True)
    manifest = materializer.load_json(materializer.owned_file(artifact, "manifest.json"), 1024 * 1024)
    listed = manifest["files"]
    expected = {item["path"]: item["sha256"] for item in listed}
    if len(expected) != len(listed) or len({name.casefold() for name in expected}) != len(expected):
        raise ValueError("duplicate component file")
    actual = {p.relative_to(artifact).as_posix() for p in artifact.rglob("*") if p.is_file()}
    if actual != set(expected) | {"manifest.json"}:
        raise ValueError("component inventory differs from exact materialized files")
    for name, digest in expected.items():
        if materializer.build.sha(materializer.owned_file(artifact, name)) != digest:
            raise ValueError("materialized component digest mismatch: " + name)
    _native_payload(artifact, "rustdesk", manifest)
    gate_path = materializer.owned_file(artifact, manifest["bundle_manifest"])
    if materializer.build.sha(gate_path) != manifest["bundle_manifest_sha256"]:
        raise ValueError("compact gate pin differs from release manifest")
    gate = materializer.load_json(gate_path, 65536)
    for name in ("executable", "executable_sha256", "control_extension", "extension", "stock_cli_supported", "bundle_sha256", "source_revision"):
        if gate[name] != manifest[name]:
            raise ValueError("compact gate differs from release manifest: " + name)
    inventory = materializer.load_json(materializer.owned_file(artifact, "corresponding-source/files.json"), 64 * 1024 * 1024)
    source_files = {item["path"]: item for item in inventory}
    if len(source_files) != len(inventory):
        raise ValueError("duplicate source archive inventory")
    seen = set()
    with tarfile.open(materializer.owned_file(artifact, "corresponding-source/sources.tar.gz"), "r|gz") as archive:
        for member in archive:
            materializer.portable(member.name)
            if not member.isfile() or member.name not in source_files or member.name in seen:
                raise ValueError("unlisted/linked/duplicate source archive entry")
            seen.add(member.name)
            entry = source_files[member.name]
            digest = hashlib.sha256()
            stream = archive.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            if digest.hexdigest() != entry["sha256"] or member.size != entry["bytes"]:
                raise ValueError("source archive content differs from recorded hash")
    if seen != set(source_files):
        raise ValueError("source archive lacks recorded files")
    if any(manifest.get(name) is not False for name in ("validated", "homologated", "legal_release_ready")):
        raise ValueError("materialization must not imply peer/legal homologation")
    legal = materializer.load_json(materializer.owned_file(artifact, "legal-review.json"))
    return {"schema_version": 1, "materialized_bytes_verified": True, "files": len(expected),
            "bundle_files": len(gate["bundle_sha256"]), "build_manifest_bytes": gate_path.stat().st_size,
            "source_files_verified": len(seen), "legal_review_items": len(legal["review_required"]),
            "manifest_sha256": materializer.build.sha(artifact / "manifest.json"),
            "peer_authenticated": False, "desktop_session_verified": False, "installed_release_verified": False,
            "legal_release_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.artifact)
    materializer.write_json(args.report, report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
