"""Stage a version-pinned optional SENTRA Electron display for Windows Setup.

The Electron runtime is a display only; SENTRA's broker remains the only
authority. No npm install, download, or arbitrary postinstall hooks here.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

BROWSER_RUNTIME_REQUIRED = ("electron.exe", "resources", "locales", "LICENSE", "LICENSES.chromium.html")
SURFACE_REQUIRED = ("main.cjs", "policy.cjs", "healthcheck.cjs", "SENTRA.ico", "SENTRA-DOT.ico", "THIRD_PARTY_NOTICES.md")


def _inventory(root: Path) -> dict[str, str]:
    """SHA-256 every package file, including Chromium DLLs, locales and ASAR."""
    entries = {}
    total = 0
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError("Electron display may not contain linked files")
        if item == root / "sentra-surface-build.json":
            continue
        if item.is_dir():
            continue
        if not item.is_file():
            raise ValueError("Electron display contains nonregular entry")
        path = item.relative_to(root).as_posix()
        if len(entries) >= 2048 or len(path) > 240:
            raise ValueError("Electron inventory exceeds path/file bound")
        total += item.stat().st_size
        if total > 1_500_000_000:
            raise ValueError("Electron runtime exceeds packaged byte limit")
        digest = hashlib.sha256()
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        entries[path] = digest.hexdigest()
    return entries


def stage_electron_surface(source: Path, destination: Path) -> dict:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    runtime = source / "node_modules" / "electron" / "dist"
    for name in BROWSER_RUNTIME_REQUIRED:
        if not (runtime / name).exists():
            raise FileNotFoundError("Electron runtime unavailable: " + name)
    for name in SURFACE_REQUIRED:
        if not (source / name).is_file():
            raise FileNotFoundError("Electron display source missing: " + name)
    if destination == source or destination.is_relative_to(source):
        raise ValueError("refusing to stage Electron in its source directory")
    temp = destination.with_name(destination.name + ".staging")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    try:
        shutil.copytree(runtime, temp, dirs_exist_ok=True, symlinks=False)
        for name in SURFACE_REQUIRED:
            shutil.copy2(source / name, temp / name)
        fingerprints = _inventory(temp)
        proof = {"schema": 1, "authority": "sentra_canvas", "runtime": "electron",
                 "source_version": json.loads((source / "package.json").read_text(encoding="utf-8"))["devDependencies"]["electron"],
                 "files": fingerprints}
        (temp / "sentra-surface-build.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
        if destination.exists():
            shutil.rmtree(destination)
        temp.replace(destination)
        return proof
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def validate_electron_payload(root: Path) -> dict:
    """Verify critical runtime/main files before copying or launching an install."""
    root = Path(root).resolve()
    manifest_file = root / "sentra-surface-build.json"
    if manifest_file.is_symlink() or not manifest_file.is_file() or manifest_file.stat().st_size > 512000:
        raise FileNotFoundError("Electron display provenance is missing or oversized")
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or payload.get("schema") != 1
            or payload.get("authority") != "sentra_canvas" or payload.get("runtime") != "electron"
            or not isinstance(payload.get("source_version"), str)):
        raise ValueError("invalid Electron display identity")
    hashes = payload.get("files")
    required = {"electron.exe", "main.cjs", "policy.cjs", "healthcheck.cjs", "SENTRA.ico", "SENTRA-DOT.ico",
                "LICENSE", "LICENSES.chromium.html", "THIRD_PARTY_NOTICES.md"}
    if not isinstance(hashes, dict) or not required.issubset(hashes):
        raise ValueError("incomplete Electron build evidence")
    if any(not isinstance(value, str) or len(value) != 64 for value in hashes.values()):
        raise ValueError("invalid Electron component digest")
    if _inventory(root) != hashes:
        raise ValueError("Electron runtime files tampered or missing")
    for name in ("LICENSE", "LICENSES.chromium.html", "THIRD_PARTY_NOTICES.md"):
        if not (root / name).is_file():
            raise FileNotFoundError("Electron runtime license missing: " + name)
    for name in ("locales", "resources"):
        if not (root / name).is_dir():
            raise FileNotFoundError("Electron runtime folder missing: " + name)
    return payload
