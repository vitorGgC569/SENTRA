"""Create SENTRA Desktop v1 release assets, MSI, checksums and CycloneDX SBOM."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentra_remote.installer import INSTALL_MARKER, PRODUCTS, download_tunnel_client
from sentra_version import PRODUCT_VERSION

from scripts.commander.build_msi import build_msi


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def build_staging(dist: Path, staging: Path, tunnel_archive: Path) -> Path:
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    names = tuple(PRODUCTS) + ("SENTRA-Setup.exe",)
    for name in names:
        source = dist / name
        if not source.is_file():
            raise FileNotFoundError(f"release binary missing: {source}")
        shutil.copy2(source, staging / name)
    _copy_tree(ROOT / "edge_extension", staging / "edge_extension")
    (staging / INSTALL_MARKER).write_text(
        json.dumps(
            {
                "product": "SENTRA Desktop",
                "version": PRODUCT_VERSION,
                "installation_id": "msi-" + PRODUCT_VERSION,
                "installation_type": "msi",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    shutil.copy2(tunnel_archive, staging / tunnel_archive.name)
    download_tunnel_client(staging, tunnel_archive)
    docs = staging / "docs"
    docs.mkdir()
    for name in (
        "README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md",
    ):
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, docs / name)
    for name in ("QUICKSTART.md", "ARCHITECTURE.md", "SECURE_MCP_TUNNEL.md"):
        source = ROOT / "docs" / name
        if source.is_file():
            shutil.copy2(source, docs / name)
    return staging


def build_update_zip(staging: Path, output: Path) -> Path:
    tunnel_archives = list(staging.glob("tunnel-client-v*-windows-amd64.zip"))
    if len(tunnel_archives) != 1:
        raise ValueError("update staging must contain exactly one pinned tunnel-client archive")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("SENTRA-Setup.exe", "sentra-update-helper.exe"):
            archive.write(staging / name, name)
        archive.write(tunnel_archives[0], tunnel_archives[0].name)
    return output


def build_sbom(release_dir: Path, assets: list[Path]) -> Path:
    components: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").strip()
        version = str(distribution.version or "").strip()
        if not name or not version:
            continue
        key = (name.casefold(), version)
        if key in seen:
            continue
        seen.add(key)
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
        })
    for asset in assets:
        components.append({
            "type": "file",
            "name": asset.name,
            "version": PRODUCT_VERSION,
            "hashes": [{"alg": "SHA-256", "content": sha256(asset)}],
        })
    components.sort(key=lambda item: (item["type"], item["name"].casefold(), item.get("version", "")))
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:" + __import__("uuid").uuid4().hex,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "SENTRA Desktop",
                "version": PRODUCT_VERSION,
            },
        },
        "components": components,
    }
    path = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}.cdx.json"
    path.write_text(json.dumps(bom, indent=2), encoding="utf-8")
    return path


def write_checksums(release_dir: Path, assets: list[Path]) -> Path:
    path = release_dir / "SHA256SUMS.txt"
    lines = [f"{sha256(asset)}  {asset.name}" for asset in sorted(assets, key=lambda p: p.name.lower())]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def create_assets(
    dist: Path,
    release_dir: Path,
    tunnel_archive: Path,
) -> dict[str, str]:
    release_dir.mkdir(parents=True, exist_ok=True)
    staging = release_dir / "staging"
    build_staging(dist, staging, tunnel_archive)

    setup = release_dir / f"SENTRA-Setup-{PRODUCT_VERSION}.exe"
    shutil.copy2(staging / "SENTRA-Setup.exe", setup)
    msi = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-x64.msi"
    build_msi(staging, msi, PRODUCT_VERSION)
    update_zip = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-update.zip"
    build_update_zip(staging, update_zip)

    shutil.rmtree(staging, ignore_errors=True)
    return finalize_assets(release_dir, signer_thumbprint="")


def finalize_assets(release_dir: Path, *, signer_thumbprint: str) -> dict[str, str]:
    setup = release_dir / f"SENTRA-Setup-{PRODUCT_VERSION}.exe"
    msi = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-x64.msi"
    update_zip = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-update.zip"
    for asset in (setup, msi, update_zip):
        if not asset.is_file():
            raise FileNotFoundError(f"release asset missing: {asset}")
    sbom = build_sbom(release_dir, [setup, msi, update_zip])
    checksums = write_checksums(release_dir, [setup, msi, update_zip, sbom])
    manifest = {
        "version": PRODUCT_VERSION,
        "url": (
            "https://github.com/vitorGgC569/SENTRA/releases/download/"
            f"v{PRODUCT_VERSION}/{update_zip.name}"
        ),
        "sha256": sha256(update_zip),
        "signer_thumbprint": signer_thumbprint.replace(" ", "").upper(),
        "setup": setup.name,
        "msi": msi.name,
        "sbom": sbom.name,
        "checksums": checksums.name,
    }
    manifest_path = release_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "setup": str(setup),
        "msi": str(msi),
        "update_zip": str(update_zip),
        "sbom": str(sbom),
        "checksums": str(checksums),
        "manifest": str(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    parser.add_argument("--release", default=str(ROOT / "release"))
    parser.add_argument("--tunnel-archive")
    parser.add_argument("--finalize-only", action="store_true")
    parser.add_argument("--signer-thumbprint", default="")
    args = parser.parse_args()
    release_dir = Path(args.release).resolve()
    if args.finalize_only:
        result = finalize_assets(
            release_dir,
            signer_thumbprint=args.signer_thumbprint,
        )
    else:
        if not args.tunnel_archive:
            parser.error("--tunnel-archive is required unless --finalize-only is used")
        result = create_assets(
            Path(args.dist).resolve(),
            release_dir,
            Path(args.tunnel_archive).resolve(),
        )
        if args.signer_thumbprint:
            result = finalize_assets(
                release_dir,
                signer_thumbprint=args.signer_thumbprint,
            )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
