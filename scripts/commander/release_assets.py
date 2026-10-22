"""Create SENTRA Desktop v1 release assets, MSI, checksums and CycloneDX SBOM."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentra_remote.installer import INSTALL_MARKER, PRODUCTS, download_tunnel_client
from sentra_version import PRODUCT_VERSION

from scripts.commander.build_msi import build_msi
from scripts.commander.build_windows import _BuildLock
from scripts.commander.extension_identity import stamp_extension_identity


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
    web_models = dist / "web-models" / "win-unpacked"
    if not (web_models / "Codex Web GPT.exe").is_file() or not (web_models / "resources" / "runtime" / "manifest.json").is_file():
        raise FileNotFoundError("Electron Web Models payload missing from release")
    if not (dist / "web-models" / "licenses" / "codex-chatgpt-web" / "LICENSE").is_file():
        raise FileNotFoundError("codex-chatgpt-web license notice missing from release")
    build_state_path = dist / "web-models" / "integration-build.json"
    if not build_state_path.is_file():
        raise FileNotFoundError("Web Models integration build metadata missing from release")
    build_state = json.loads(build_state_path.read_text(encoding="utf-8-sig"))
    patch = ROOT / "integrations" / "codex_chatgpt_web" / "sentra-upstream.patch"
    if str(build_state.get("patch_sha256") or "").lower() != sha256(patch):
        raise RuntimeError("Web Models payload was built from a stale SENTRA upstream patch")
    _copy_tree(dist / "web-models", staging / "web-models")
    # MSI has its own staging tree, distinct from the self-extracting Setup.
    # Without this copy the optional Electron window exists in Setup but
    # silently disappears from an MSI installation.
    from scripts.commander.stage_electron import validate_electron_payload
    electron_payload = dist / "sentra-electron"
    validate_electron_payload(electron_payload)
    _copy_tree(electron_payload, staging / "sentra-electron")
    from scripts.commander.stage_mobile import validate_mobile_runtime
    validate_mobile_runtime(dist / 'sentra-mobile')
    _copy_tree(dist / 'sentra-mobile', staging / 'sentra-mobile')
    from scripts.commander.stage_terminal import validate_terminal_runtime
    validate_terminal_runtime(dist / 'sentra-terminal')
    _copy_tree(dist / 'sentra-terminal', staging / 'sentra-terminal')
    if not (dist / 'runtime-components.json').is_file() or not (dist / 'runtime').is_dir():
        raise FileNotFoundError('materialized native/QuickJS runtime components missing')
    _copy_tree(dist / 'runtime', staging / 'runtime')
    shutil.copy2(dist / 'runtime-components.json', staging / 'runtime-components.json')
    validate_electron_payload(staging / "sentra-electron")
    stamp_extension_identity(staging / "edge_extension")
    # Never distribute an installation-local bootstrap HMAC to another user.
    bootstrap = staging / 'edge_extension' / 'sentra-bootstrap.json'
    bootstrap.unlink(missing_ok=True)
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
    shutil.copytree(ROOT / 'sentra_remote' / 'provider_notices', docs / 'provider_notices')
    from scripts.commander.runtime_dependencies import stage_wasmtime_notices
    stage_wasmtime_notices(docs / 'wasmtime')
    for name in (
        "README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md",
    ):
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, docs / name)
    for name in (
        "START_HERE.md",
        "SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md",
        "QUICKSTART.md",
        "USING_SENTRA.md",
        "SENTRA_CLI.md",
        "WEB_MODELS.md",
        "MCP_SERVER.md",
        "ARCHITECTURE.md",
        "SECURE_MCP_TUNNEL.md",
        "ZERO_CONFIG_SETUP.md",
    ):
        source = ROOT / "docs" / name
        if source.is_file():
            shutil.copy2(source, docs / name)
    media = ROOT / "docs" / "onboarding_media"
    for video in ("mcp-create-tunnel.mp4", "mcp-connect-connector.mp4"):
        source = media / video
        if not source.is_file():
            raise FileNotFoundError(f"Bundled SENTRA onboarding tutorial missing: {source}")
    guide = media / "SENTRA_SETUP_GUIDE.html"
    if not guide.is_file():
        raise FileNotFoundError(f"Bundled SENTRA visual setup guide missing: {guide}")
    shutil.copytree(media, docs / "onboarding_media")
    _stage_opendots_artwork(staging)
    _stage_guacamole_legal(staging)
    _write_staged_artwork_record(staging)
    legal_record = json.loads((staging / 'artwork-provenance.json').read_text(encoding='utf-8'))
    if not {'opendots','guacamole'} <= legal_record.keys():
        raise ValueError('integral release requires OpenDots MIT and Guacamole 1.5.0 Apache provenance')
    _stage_package_contract(staging)
    return staging


def _stage_package_contract(staging: Path) -> None:
    """Copy license, user docs and the audit modules into the Setup tree.

    A clean Windows install can read them without a developer checkout.
    This does not add a paywall and does not block local use.
    """
    from sentra_quality.distribution_diagnosis import PACKAGE_FILES
    for relative in PACKAGE_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"installer package file missing: {relative}")
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _write_staged_artwork_record(staging: Path) -> None:
    """Combine per-set staging records into one manifest-ready document."""
    record: dict[str, Any] = {}
    for name in ("opendots-record.json", "guacamole-record.json"):
        fragment = staging / name
        if fragment.is_file():
            try:
                loaded = json.loads(fragment.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise ValueError(f"invalid staged artwork record {name}") from exc
            if isinstance(loaded, dict):
                record[name.split("-record")[0]] = loaded
            fragment.unlink()
    if record:
        (staging / "artwork-provenance.json").write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


def _stage_opendots_artwork(staging: Path) -> dict[str, Any] | None:
    """Transport OpenDots mascot LICENSE + provenance into the release.

    Prisma owns the assets; Vitra owns release transport. The original PNG
    bytes travel inside the built desktop bundle (Prisma/materialize domain —
    not touched here); the release payload additionally carries LICENSE +
    PROVENANCE.json under docs/opendots/ so every install ships the MIT
    attribution (Copyright Atai Barkai) and the pin record. PNG digests are
    re-verified against PROVENANCE.json at staging time; mismatch refuses
    the staging. Absence of the whole assets dir keeps older trees building
    (returns None); a present-but-incomplete dir fails closed.
    """
    source_dir = ROOT / "sentra_canvas" / "desktop_ui" / "src" / "assets" / "opendots"
    if not source_dir.is_dir():
        return None
    license_file = source_dir / "LICENSE"
    provenance_file = source_dir / "PROVENANCE.json"
    if not license_file.is_file() or not provenance_file.is_file():
        raise FileNotFoundError("OpenDots artwork LICENSE/PROVENANCE.json missing from assets")
    try:
        provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid OpenDots PROVENANCE.json") from exc
    if (not isinstance(provenance, dict) or provenance.get("license") != "MIT"
            or "Atai Barkai" not in str(provenance.get("copyright") or "")
            or not isinstance(provenance.get("files"), dict)):
        raise ValueError("OpenDots provenance identity mismatch (MIT/Atai Barkai/files)")
    target_dir = staging / "docs" / "opendots"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, entry in provenance["files"].items():
        if not isinstance(entry, dict) or not isinstance(name, str):
            raise ValueError("invalid OpenDots provenance file entry")
        expected = str(entry.get("sha256") or "").lower()
        if len(expected) != 64:
            raise ValueError(f"OpenDots provenance lacks sha256 for {name}")
        asset = source_dir / name
        if not asset.is_file() or asset.is_symlink():
            raise FileNotFoundError(f"OpenDots artwork asset missing: {name}")
        if sha256(asset) != expected:
            raise ValueError(f"OpenDots artwork bytes differ from provenance: {name}")
    shutil.copy2(license_file, target_dir / "LICENSE")
    shutil.copy2(provenance_file, target_dir / "PROVENANCE.json")
    notice_src = ROOT / "sentra_remote" / "provider_notices" / "opendots-mascots-NOTICE.txt"
    if notice_src.is_file():
        shutil.copy2(notice_src, target_dir / "opendots-mascots-NOTICE.txt")
    record = {"upstream": str(provenance.get("upstream") or ""),
              "commit": str(provenance.get("commit") or ""),
              "license": "MIT",
              "copyright": str(provenance.get("copyright") or ""),
              "files": sorted(provenance["files"].keys())}
    (staging / "opendots-record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return record


def _stage_guacamole_legal(staging: Path) -> dict[str, Any] | None:
    """Transport guacamole-common-js LICENSE + NOTICE + provenance.

    Prisma owns the pin (guacamole-common-js 1.5.0, padarom repack — not a
    current ASF clone); Vitra owns release transport. The JS bytes arrive via
    the pinned npm tarball at UI build time (Prisma/materialize domain — not
    touched here); the release payload carries the LICENSE + ASF NOTICE +
    PROVENANCE.json (registry tarball URL + SRI integrity) under
    docs/guacamole/ so every install ships attribution and the pin record.
    Absent dir keeps older trees building (None); present-but-incomplete fails.
    """
    source_dir = ROOT / "sentra_canvas" / "desktop_ui" / "src" / "assets" / "guacamole"
    if not source_dir.is_dir():
        return None
    license_file = source_dir / "LICENSE"
    notice_file = source_dir / "NOTICE"
    provenance_file = source_dir / "PROVENANCE.json"
    if not license_file.is_file() or not provenance_file.is_file():
        raise FileNotFoundError("guacamole-common-js LICENSE/PROVENANCE.json missing from assets")
    if not notice_file.is_file():
        raise FileNotFoundError("guacamole ASF NOTICE missing from assets")
    try:
        provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid guacamole PROVENANCE.json") from exc
    if (not isinstance(provenance, dict)
            or provenance.get("package") != "guacamole-common-js"
            or str(provenance.get("version") or "") != "1.5.0"
            or provenance.get("license") != "Apache-2.0"
            or provenance.get("is_apache_clone") is not False):
        raise ValueError("guacamole provenance identity mismatch "
                         "(guacamole-common-js/1.5.0/Apache-2.0/non-ASF-clone)")
    integrity = str(provenance.get("integrity") or "")
    if not integrity.startswith("sha512-") or len(integrity) < 24:
        raise ValueError("guacamole provenance lacks tarball SRI integrity")
    if not str(provenance.get("registry_tarball") or "").startswith("https://"):
        raise ValueError("guacamole provenance lacks HTTPS registry tarball URL")
    target_dir = staging / "docs" / "guacamole"
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(license_file, target_dir / "LICENSE")
    shutil.copy2(notice_file, target_dir / "NOTICE")
    shutil.copy2(provenance_file, target_dir / "PROVENANCE.json")
    notice_src = ROOT / "sentra_remote" / "provider_notices" / "guacamole-common-js-NOTICE.txt"
    if notice_src.is_file():
        shutil.copy2(notice_src, target_dir / "guacamole-common-js-NOTICE.txt")
    record = {"package": "guacamole-common-js", "version": "1.5.0",
              "license": "Apache-2.0", "is_apache_clone": False,
              "registry_tarball": str(provenance.get("registry_tarball") or ""),
              "integrity": integrity,
              "repack_repository": str(provenance.get("repack_repository") or "")}
    (staging / "guacamole-record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return record


def build_update_zip(staging: Path, output: Path) -> Path:
    tunnel_archives = list(staging.glob("tunnel-client-v*-windows-amd64.zip"))
    if len(tunnel_archives) != 1:
        raise ValueError("update staging must contain exactly one pinned tunnel-client archive")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("SENTRA-Setup.exe", "sentra-update-helper.exe"):
            archive.write(staging / name, name)
        archive.write(tunnel_archives[0], tunnel_archives[0].name)
    return output


def build_sbom(release_dir: Path, assets: list[Path], *, runtime_components=None, artwork=None, runtime_dependencies=None) -> Path:
    from scripts.commander.pdfium_pin import require_pdfium, PDFIUM_VERSION
    require_pdfium()
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
    if not any(item["name"].casefold() == "pypdfium2" and item["version"] == PDFIUM_VERSION
               for item in components):
        raise ValueError("release SBOM must contain pinned pypdfium2")
    upstream_manifest = json.loads(
        (ROOT / "integrations" / "codex_chatgpt_web" / "upstream.json").read_text(
            encoding="utf-8"
        )
    )
    upstream_ref = str(upstream_manifest.get("ref") or "").strip()
    upstream_version = upstream_ref[1:] if upstream_ref.startswith("v") else upstream_ref
    components.append({
        "type": "library",
        "name": str(upstream_manifest["name"]),
        "version": upstream_version,
        "licenses": [{"license": {"id": str(upstream_manifest["license"])}}],
        "externalReferences": [{
            "type": "vcs",
            "url": str(upstream_manifest["repository"]) + "#" + str(upstream_manifest["commit"]),
        }],
        "properties": [
            {"name": "sentra:integration_mode", "value": str(upstream_manifest["integration_mode"])},
            {"name": "sentra:upstream_commit", "value": str(upstream_manifest["commit"])},
        ],
    })
    for asset in assets:
        components.append({
            "type": "file",
            "name": asset.name,
            "version": PRODUCT_VERSION,
            "hashes": [{"alg": "SHA-256", "content": sha256(asset)}],
        })
    for name, record in (runtime_components or {}).items():
        if record.get('materialized') is not True or not record.get('files'):
            raise ValueError('runtime SBOM needs materialized per-file provenance')
        for item in record['files']:
            components.append({'type': 'file', 'name': item['path'],
                'hashes': [{'alg': 'SHA-256', 'content': item['sha256']}],
                'properties': [{'name': 'sentra:runtime', 'value': name},
                               {'name': 'sentra:runtime-validated', 'value': 'false'}]})
    for name, record in (artwork or {}).items():
        component = {'type': 'library', 'name': name,
                     'licenses': [{'license': {'id': record['license']}}]}
        if record.get('version'): component['version'] = record['version']
        component['properties'] = [{'name': 'sentra:provenance', 'value': json.dumps(record, sort_keys=True)}]
        components.append(component)
    for name, record in (runtime_dependencies or {}).items():
        components.append({'type': 'library', 'name': name, 'version': record['version'],
            'purl': f"pkg:pypi/{name}@{record['version']}",
            'licenses': [{'license': {'id': record['license']}}],
            'properties': [{'name': 'sentra:native-file-pins', 'value': json.dumps(record['files'], sort_keys=True)}]})
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
    staging = Path(
        tempfile.mkdtemp(prefix="sentra-release-staging-")
    ).resolve()
    artifacts_temp = Path(
        tempfile.mkdtemp(prefix="sentra-release-artifacts-")
    ).resolve()
    artwork: dict[str, Any] | None = None
    components = None
    try:
        build_staging(dist, staging, tunnel_archive)
        from native_bridge.bootstrap import extension_identity
        components = {'extension': extension_identity(staging / 'edge_extension'),
                      'runtime_components': json.loads((staging / 'runtime-components.json').read_text(encoding='utf-8')),
                      'gateway': {'version': PRODUCT_VERSION,
                                  'sha256': sha256(staging / 'web-models' / 'integration-build.json'),
                                  'source_patch_sha256': sha256(ROOT / 'integrations/codex_chatgpt_web/sentra-upstream.patch')}}
        from scripts.commander.runtime_dependencies import require_wasmtime_pin
        components['runtime_dependencies'] = {'wasmtime': require_wasmtime_pin()}
        (release_dir / 'package-components.json').write_text(json.dumps(components, sort_keys=True, indent=2), encoding='utf-8')
        artwork_file = staging / "artwork-provenance.json"
        if artwork_file.is_file():
            try:
                loaded = json.loads(artwork_file.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise ValueError("invalid staged artwork provenance") from exc
            artwork = loaded if isinstance(loaded, dict) else None
        if artwork:
            (release_dir / 'package-artwork.json').write_text(json.dumps(artwork, sort_keys=True, indent=2), encoding='utf-8')

        setup = release_dir / f"SENTRA-Setup-{PRODUCT_VERSION}.exe"
        shutil.copy2(staging / "SENTRA-Setup.exe", setup)

        msi = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-x64.msi"
        local_msi = artifacts_temp / msi.name
        build_msi(staging, local_msi, PRODUCT_VERSION)
        shutil.copy2(local_msi, msi)

        update_zip = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-update.zip"
        local_update_zip = artifacts_temp / update_zip.name
        build_update_zip(staging, local_update_zip)
        shutil.copy2(local_update_zip, update_zip)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(artifacts_temp, ignore_errors=True)

    return finalize_assets(release_dir, signer_thumbprint="", artwork=artwork, components=components)


def finalize_assets(release_dir: Path, *, signer_thumbprint: str,
                     sidecars: dict | None = None,
                     provider_pins: dict | None = None,
                     artwork: dict | None = None, components: dict | None = None) -> dict[str, str]:
    setup = release_dir / f"SENTRA-Setup-{PRODUCT_VERSION}.exe"
    msi = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-x64.msi"
    update_zip = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-update.zip"
    for asset in (setup, msi, update_zip):
        if not asset.is_file():
            raise FileNotFoundError(f"release asset missing: {asset}")
    component_file = release_dir / 'package-components.json'
    if components is None and component_file.is_file():
        components = json.loads(component_file.read_text(encoding='utf-8'))
    artwork_file = release_dir / 'package-artwork.json'
    if artwork is None and artwork_file.is_file():
        artwork = json.loads(artwork_file.read_text(encoding='utf-8'))
    if not components or not artwork or not {'opendots', 'guacamole'} <= artwork.keys():
        raise ValueError('integral release component and license records required')
    sbom = build_sbom(release_dir, [setup, msi, update_zip],
                      runtime_components=components['runtime_components'], artwork=artwork,
                      runtime_dependencies=components['runtime_dependencies'])
    record_assets = [p for p in (component_file, artwork_file) if p.is_file()]
    checksums = write_checksums(release_dir, [setup, msi, update_zip, sbom, *record_assets])
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
        "shell_surface": {
            "entry": "/shell-home.html",
            "fallback": "/desktop.html",
            "bridge_contract": "POST /api/shell/bridge",
            "bridge_reference": "docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md",
            "canvas_role": "internal_orchestration_view",
        },
        "mcp_schema_version": 1,
    }
    component_file = release_dir / 'package-components.json'
    if components is None and component_file.is_file():
        components = json.loads(component_file.read_text(encoding='utf-8'))
    if components:
        extension = components['extension']
        manifest['extension'] = {'version': extension['version'], 'build_id': extension['build_id'],
            'source_hash': extension['source_hash'], 'sha256': hashlib.sha256(json.dumps(extension, sort_keys=True).encode()).hexdigest(),
            'bootstrap': 'installation-local-HMAC-required'}
        manifest['gateway'] = components['gateway']
        manifest['runtime_components'] = components['runtime_components']
        manifest['runtime_dependencies'] = components['runtime_dependencies']
    if sidecars:
        if not isinstance(sidecars, dict):
            raise ValueError("release sidecars must be an object")
        manifest["sidecars"] = sidecars.get("sidecars", sidecars)
        manifest["sidecars_combined_sha256"] = sidecars.get("combined_sha256", "")
    if provider_pins:
        if not isinstance(provider_pins, dict):
            raise ValueError("release provider pins must be an object")
        manifest["provider_pins"] = provider_pins
    if artwork is not None:
        if not isinstance(artwork, dict):
            raise ValueError("release artwork provenance must be an object")
        if isinstance(artwork.get("files"), list) and "opendots" not in artwork:
            artwork = {"opendots": artwork}  # legacy flat record
        manifest["artwork_provenance"] = artwork
    else:
        # Re-finalize preserves a previously composed artwork record.
        previous_file = release_dir / "release-manifest.json"
        if previous_file.is_file():
            try:
                previous = json.loads(previous_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = {}
            if isinstance(previous, dict) and isinstance(
                    previous.get("artwork_provenance"), dict):
                manifest["artwork_provenance"] = previous["artwork_provenance"]
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
    lock_path = ROOT / ".sentra" / "release-assets.lock"
    with _BuildLock(lock_path, description="release asset build"):
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
