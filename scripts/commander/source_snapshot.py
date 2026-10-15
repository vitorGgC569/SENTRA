"""Isolate reviewed product inputs without copying sessions or build caches.

Create once, then run build_windows.py from the new directory. A snapshot is
an input seal, not a signature or a claim that its binaries passed runtime QA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from scripts.commander.build_windows import ROOT, _source_fingerprint

MANIFEST = "source-snapshot.json"


def _plain_file(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or relative.is_absolute()
            or ".." in relative.parts or relative.as_posix() != name):
        raise ValueError("invalid snapshot input path: " + name)
    path = root.joinpath(*relative.parts)
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("linked snapshot input: " + name)
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("missing or escaped snapshot input: " + name)
    return path


def verify_source_snapshot(root: Path) -> dict:
    root = Path(root).resolve()
    manifest = root / MANIFEST
    if manifest.is_symlink():
        raise ValueError("linked source snapshot manifest")
    proof = json.loads(manifest.read_text(encoding="utf-8"))
    sources = proof.get("sources")
    if proof.get("schema_version") != 1 or not isinstance(sources, dict) or not sources:
        raise ValueError("invalid source snapshot manifest")
    for name, expected in sources.items():
        path = _plain_file(root, name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("source snapshot changed: " + name)
    if _source_fingerprint(root) != sources:
        raise RuntimeError("source snapshot input set changed")
    return proof


def create_source_snapshot(destination: Path, source_root: Path = ROOT) -> dict:
    source_root = Path(source_root).resolve()
    destination = Path(destination).absolute()
    # Never merge into an existing candidate, follow a destination link, or
    # recursively snapshot a child of the source checkout.
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("snapshot destination already exists: " + str(destination))
    destination = destination.resolve()
    if destination.is_relative_to(source_root):
        raise ValueError("snapshot destination must be outside the source checkout")
    sources = _source_fingerprint(source_root)
    if not sources:
        raise ValueError("empty source snapshot")
    # Check the whole allowlist before creating anything. Private .sentra,
    # .codex, .git, node_modules and build outputs are not product inputs.
    for name in sources:
        _plain_file(source_root, name)
    destination.mkdir(parents=True, exist_ok=False)
    total = 0
    for name, expected in sources.items():
        source = _plain_file(source_root, name)
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("source changed while copying snapshot: " + name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(data)
        total += len(data)
    if _source_fingerprint(source_root) != sources:
        raise RuntimeError("source changed during snapshot; no seal written")
    if _source_fingerprint(destination) != sources:
        raise RuntimeError("copied snapshot differs; no seal written")
    proof = {"schema_version": 1, "source_root": str(source_root),
             "sources": sources, "files": len(sources), "bytes": total}
    (destination / MANIFEST).write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    verify_source_snapshot(destination)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = (verify_source_snapshot(args.destination) if args.verify
              else create_source_snapshot(args.destination))
    print(json.dumps({"snapshot": str(args.destination.resolve()),
                      "files": result["files"], "bytes": result["bytes"], "verified": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
