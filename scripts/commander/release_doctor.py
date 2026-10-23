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
from scripts.commander.msi_media import verify_msi_manifest


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
    manifest = _json(release / "release-manifest.json")
    media_entry = manifest.get("msi_media")
    media_files = []
    if media_entry is not None:
        media_files = verify_msi_manifest(release / names[1], media_entry)[1:]
    elif expected_signer or (release / names[1]).with_suffix(".media.json").exists():
        raise ValueError("release MSI external-media manifest is required")
    records = [release / name for name in ("package-components.json", "package-artwork.json")
               if (release / name).is_file()]
    all_names = (*names, *(p.name for p in media_files), *(p.name for p in records))
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
    if set(expected) != set(all_names):
        raise ValueError("missing or unexpected release checksum assets")
    actual: dict[str, str] = {}
    for name in all_names:
        file = release / name
        if not file.is_file() or file.is_symlink():
            raise ValueError(f"release artifact missing or not a regular file: {name}")
        actual[name] = _digest(file)
        if actual[name] != expected[name]:
            raise ValueError(f"release SHA256 mismatch: {name}")

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
    shell = manifest.get("shell_surface")
    shell_contract = "unchecked"
    if shell is not None:
        if (not isinstance(shell, dict)
                or shell.get("bridge_contract") != "POST /api/shell/bridge"
                or shell.get("canvas_role") != "internal_orchestration_view"):
            raise ValueError("release shell surface contract mismatch")
        shell_contract = str(shell.get("fallback") or "unknown")

    sidecars_state = "absent"
    sidecars = manifest.get("sidecars")
    if sidecars is not None:
        if not isinstance(sidecars, dict):
            raise ValueError("release sidecars must be an object")
        for kind in ("interop", "workflows", "quality"):
            entry = sidecars.get(kind)
            if entry is None or (isinstance(entry, dict) and entry.get("state") == "absent"):
                continue
            if (not isinstance(entry, dict) or not entry.get("name")
                    or not entry.get("version") or len(str(entry.get("sha256") or "")) != 64
                    or not entry.get("signer")):
                raise ValueError(f"release sidecar manifest incomplete: {kind}")
        combined = str(manifest.get("sidecars_combined_sha256") or "")
        if combined and (len(combined) != 64
                         or any(c not in "0123456789abcdef" for c in combined)):
            raise ValueError("release sidecars combined digest is invalid")
        sidecars_state = "verified-structure"

    provider_pins_state = "absent"
    provider_pins = manifest.get("provider_pins")
    if provider_pins is not None:
        if not isinstance(provider_pins, dict) or not isinstance(provider_pins.get("files"), list):
            raise ValueError("release provider pins must carry a files inventory")
        for entry in provider_pins["files"]:
            if (not isinstance(entry, dict) or not entry.get("provider")
                    or not entry.get("pin_version") or not entry.get("notice")):
                raise ValueError("release provider pin entry incomplete")
        provider_pins_state = "verified-structure"

    artwork_state = "absent"
    artwork = manifest.get("artwork_provenance")
    if artwork is not None:
        if not isinstance(artwork, dict):
            raise ValueError("release artwork provenance must be an object")
        sets = dict(artwork) if "opendots" in artwork or "guacamole" in artwork else {"opendots": artwork}
        for key, entry in sets.items():
            if key == "opendots":
                if (not isinstance(entry, dict)
                        or entry.get("license") != "MIT"
                        or "Atai Barkai" not in str(entry.get("copyright") or "")
                        or not str(entry.get("commit") or "").strip()
                        or not isinstance(entry.get("files"), list) or not entry["files"]):
                    raise ValueError("release opendots provenance incomplete (MIT/Atai Barkai/commit/files)")
            elif key == "guacamole":
                if (not isinstance(entry, dict)
                        or entry.get("package") != "guacamole-common-js"
                        or str(entry.get("version") or "") != "1.5.0"
                        or entry.get("license") != "Apache-2.0"
                        or entry.get("is_apache_clone") is not False
                        or not str(entry.get("integrity") or "").startswith("sha512-")):
                    raise ValueError("release guacamole provenance incomplete "
                                     "(1.5.0/Apache-2.0/non-clone/SRI)")
            else:
                raise ValueError(f"unknown release artwork set: {key}")
        artwork_state = "verified-structure:" + "+".join(sorted(sets))

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
    for name in (*names[:3], *(p.name for p in media_files), *(p.name for p in records)):
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
        for file in media_files:
            if file.suffix == ".cab":
                verify_authenticode(file, signer)
        from scripts.commander.msi_media_signing import require_inscribed_cabinets
        require_inscribed_cabinets(release / names[1])
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
        "artifacts_verified": len(all_names), "update_zip_components": 3,
        "msi_media": "verified-external-cabs" if media_files else "legacy-unsigned-qa-only",
        "sbom": "verified", "payload_provenance": provenance,
        "shell_contract": shell_contract,
        "sidecars": sidecars_state,
        "provider_pins": provider_pins_state,
        "artwork_provenance": artwork_state,
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
