"""Offline fail-closed verification of SENTRA Windows release media.

Does not install, start services, inspect credentials or publish artifacts.
Signed status can only be asserted with a separately supplied trusted publisher.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentra_version import PRODUCT_VERSION


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _json(path: Path, limit: int = 16 * 1024 * 1024) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"release metadata missing or oversized: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid release metadata: {path.name}")
    return data


def audit_release(
    release_dir: Path, *,
    version: str = PRODUCT_VERSION,
    expected_signer: str = "",
    dist_dir: Path | None = None,
) -> dict[str, Any]:
    """Verify a complete immutable candidate, without destructive operations."""
    release = release_dir.resolve(strict=True)
    names = (
        f"SENTRA-Setup-{version}.exe",
        f"SENTRA-Desktop-{version}-x64.msi",
        f"SENTRA-Desktop-{version}-update.zip",
        f"SENTRA-Desktop-{version}.cdx.json",
    )
    expected: dict[str, str] = {}
    checksums_path = release / "SHA256SUMS.txt"
    if not checksums_path.is_file() or checksums_path.stat().st_size > 8192:
        raise ValueError("missing or oversized SHA256SUMS")
    for line in checksums_path.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9._-]+)", line)
        if not match:
            raise ValueError("malformed release checksum entry")
        digest, name = match.groups()
        if name in expected:
            raise ValueError("duplicate release checksum entry")
        expected[name] = digest
    if set(expected) != set(names):
        raise ValueError("missing or unexpected release checksum assets")
    actual: dict[str, str] = {}
    for name in names:
        file = release / name
        if not file.is_file() or file.is_symlink():
            raise ValueError(f"release artifact missing or not a regular file: {name}")
        actual[name] = _digest(file)
        if actual[name] != expected[name]:
            raise ValueError(f"release SHA256 mismatch: {name}")

    manifest = _json(release / "release-manifest.json")
    if manifest.get("version") != version:
        raise ValueError("release version mismatch")
    if any(manifest.get(key) != name for key, name in zip(
        ("setup", "msi", "sbom"), (names[0], names[1], names[3])
    )):
        raise ValueError("release manifest asset identity mismatch")
    if manifest.get("checksums") != "SHA256SUMS.txt":
        raise ValueError("release checksum manifest identity mismatch")
    if manifest.get("sha256") != actual[names[2]]:
        raise ValueError("release update manifest digest mismatch")
    url = manifest.get("url")
    if not isinstance(url, str) or not url.startswith("https://") or not url.endswith("/" + names[2]):
        raise ValueError("update URL must be a matching HTTPS release URL")

    bom = _json(release / names[3])
    if bom.get("bomFormat") != "CycloneDX" or bom.get("specVersion") != "1.5":
        raise ValueError("missing required CycloneDX SBOM")
    metadata = bom.get("metadata")
    component = metadata.get("component") if isinstance(metadata, dict) else None
    if not isinstance(component, dict) or component.get("version") != version or component.get("name") != "SENTRA Desktop":
        raise ValueError("SBOM product identity mismatch")
    components = bom.get("components")
    if not isinstance(components, list):
        raise ValueError("SBOM has no component inventory")
    if not any(isinstance(item, dict) and item.get("name", "").casefold() == "pypdfium2"
               and item.get("version") == "4.30.0" for item in components):
        raise ValueError("release SBOM lacks pinned PDFium 4.30.0")
    for name in names[:3]:
        if not any(
            isinstance(item, dict) and item.get("type") == "file" and item.get("name") == name
            and {"alg": "SHA-256", "content": actual[name]} in item.get("hashes", [])
            for item in components
        ):
            raise ValueError(f"SBOM file digest missing or stale: {name}")

    with zipfile.ZipFile(release / names[2]) as archive:
        names_in_zip = archive.namelist()
        mandatory = {"SENTRA-Setup.exe", "sentra-update-helper.exe"}
        tunnels = [name for name in names_in_zip if re.fullmatch(
            r"tunnel-client-v[0-9.]+-windows-amd64.zip", name
        )]
        if len(tunnels) != 1 or set(names_in_zip) != mandatory | set(tunnels) or len(names_in_zip) != 3:
            raise ValueError("update ZIP contains unexpected or missing components")
        if any(item.is_dir() or item.file_size <= 0 for item in archive.infolist()):
            raise ValueError("update ZIP has empty/invalid components")
        # Verify the Setup that updater executes is precisely the asset in the
        # checksummed release, not a different executable inside the ZIP.
        with archive.open("SENTRA-Setup.exe") as src:
            digest = hashlib.sha256()
            for block in iter(lambda: src.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != actual[names[0]]:
            raise ValueError("update ZIP Setup differs from released Setup")

    signer = str(expected_signer or "").replace(" ", "").upper()
    if signer:
        if not re.fullmatch(r"[A-F0-9]{40,64}", signer):
            raise ValueError("invalid expected publisher thumbprint")
        if str(manifest.get("signer_thumbprint") or "").replace(" ", "").upper() != signer:
            raise ValueError("release manifest publisher does not match trusted signer")
        from sentra_remote.updater import verify_authenticode
        verify_authenticode(release / names[0], signer)
        verify_authenticode(release / names[1], signer)
    elif manifest.get("signer_thumbprint"):
        # A manifest-asserted signer cannot attest an unsigned audit.
        raise ValueError("claimed release publisher requires independent signer verification")

    provenance = "not_checked"
    if dist_dir is not None:
        from scripts.commander.build_windows import _source_fingerprint
        dist = dist_dir.resolve(strict=True)
        evidence = _json(dist / "build-provenance-payload.json", limit=8 * 1024 * 1024)
        if evidence.get("phase") != "payload" or evidence.get("sources") != _source_fingerprint():
            raise ValueError("payload provenance is stale relative to current sources")
        if signer:
            seal = evidence.get("signed_seal")
            if not isinstance(seal, dict) or seal.get("signer_thumbprint") != signer:
                raise ValueError("signed release requires payload provenance sealed after signing")
        executable_hashes = evidence.get("executables")
        if not isinstance(executable_hashes, dict) or not executable_hashes:
            raise ValueError("payload binary manifest missing")
        for filename, value in executable_hashes.items():
            binary = dist / filename
            if (not isinstance(value, dict) or not binary.is_file() or
                _digest(binary) != value.get("sha256") or binary.stat().st_size != value.get("bytes")):
                raise ValueError(f"payload binary provenance mismatch: {filename}")
        provenance = "verified"
    return {
        "schema": 1, "result": "pass", "version": version,
        "artifacts_verified": len(names), "update_zip_components": 3,
        "sbom": "verified", "payload_provenance": provenance,
        "authenticode": "verified" if signer else "not_verified_unsigned_qa_only",
        "ready_for_install_smoke": bool(signer and provenance == "verified"),
        # Artifact integrity alone never certifies UI, account auth or clean install.
        "homologated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SENTRA Windows artifact Doctor")
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--version", default=PRODUCT_VERSION)
    parser.add_argument("--trusted-signer", default="")
    args = parser.parse_args(argv)
    try:
        result = audit_release(
            args.release, version=args.version,
            expected_signer=args.trusted_signer, dist_dir=args.dist,
        )
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"schema": 1, "result": "fail", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
