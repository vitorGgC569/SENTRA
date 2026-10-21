"""Materialize an isolated, non-homologated RustDesk component from real proofs.

Never builds, downloads, installs or starts RustDesk. A build dependency inventory
is deliberately not described as an exact static-linkage or legal approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile
import tomllib
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.commander import build_rustdesk as build
from scripts.commander.build_windows import _BuildLock
from scripts.commander.release_components import _native_payload

BUNDLE = "flutter/build/windows/x64/runner/Release/"
HEX = re.compile(r"[0-9a-f]{64}\Z")
LEGAL = re.compile(r"^(licen[cs]e|copying|copyright|notice|authors)(?:[._-].*)?$", re.I)


def portable(name: str) -> str:
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError("portable relative file required: " + repr(name))
    return name


def owned_file(root: Path, name: str) -> Path:
    path = root / portable(name)
    for current in (path, *path.parents):
        if current == root.parent:
            break
        if current.is_symlink() or current.is_junction():
            raise ValueError("linked materialization input: " + name)
    if not path.is_file() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("missing/escaped materialization input: " + name)
    return path


def load_json(path: Path, bound=4 * 1024 * 1024):
    if path.is_symlink() or path.stat().st_size > bound:
        raise ValueError("unsafe/oversized JSON input: " + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_proofs(source: Path, proofs: Path) -> tuple[dict, dict, dict]:
    native = build.validate_native_sources(source)
    inputs = build.source_inputs(source)
    records = {}
    for phase in ("codegen", "native", "flutter", "profile-test"):
        path = owned_file(proofs, phase + "-proof.json")
        proof = load_json(path)
        if (proof.get("phase") != phase or Path(proof["source"]).resolve(strict=True) != source
                or proof.get("inputs") != inputs or proof.get("source_revision") != native["source_revision"]
                or proof.get("native_sources") != native["native_sources"]):
            raise ValueError("stale RustDesk proof: " + phase)
        snapshot = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        if proof.get("input_snapshot_sha256", {}).get("after") != snapshot:
            raise ValueError("RustDesk input snapshot differs: " + phase)
        if phase != "codegen" and proof["input_snapshot_sha256"].get("before") != snapshot:
            raise ValueError("RustDesk inputs changed during build: " + phase)
        if not proof.get("tooling_inputs") or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in proof["tooling_inputs"].values()):
            raise ValueError("RustDesk proof lacks builder hashes: " + phase)
        outputs = proof.get("outputs")
        if not isinstance(outputs, dict) or not outputs:
            raise ValueError("RustDesk proof lacks real outputs: " + phase)
        for name, digest in outputs.items():
            if not isinstance(digest, str) or not HEX.fullmatch(digest) or build.sha(owned_file(source, name)) != digest:
                raise ValueError("RustDesk proof output mismatch: " + phase + "/" + name)
        records[phase] = {"sha256": build.sha(path), "proof": proof}
    if set(records["codegen"]["proof"]["outputs"]) != set(build.GENERATED):
        raise ValueError("RustDesk bridge output set differs")
    expected_native = {"target/release/librustdesk.dll", "target/release/deps/dylib_virtual_display.dll", "src/version.rs"}
    if set(records["native"]["proof"]["outputs"]) != expected_native:
        raise ValueError("RustDesk native output set differs")
    bundle = records["flutter"]["proof"]["outputs"]
    if any(not name.startswith(BUNDLE) for name in bundle):
        raise ValueError("RustDesk Flutter proof contains a non-bundle file")
    actual = {p.relative_to(source).as_posix() for p in (source / BUNDLE).rglob("*") if p.is_file()}
    if actual != set(bundle):
        raise ValueError("RustDesk bundle contains missing/unproved extra files")
    for name, original in (("librustdesk.dll", "target/release/librustdesk.dll"),
                           ("dylib_virtual_display.dll", "target/release/deps/dylib_virtual_display.dll")):
        if bundle.get(BUNDLE + name) != records["native"]["proof"]["outputs"][original]:
            raise ValueError("RustDesk bundle native dependency differs: " + name)
    profile = records["profile-test"]["proof"]
    runs = profile.get("profile_results", {}).get("runs", [])
    positives = [run for run in runs if run.get("negative") is False]
    negatives = [run for run in runs if run.get("negative") is True]
    if (profile.get("verification", {}).get("native_profile_isolation") is not True
            or len(positives) != 2 or len(negatives) != 1
            or any(run.get("returncode") != 0 or run.get("stdout", "").strip() != "profile-config-log-ipc-isolated" for run in positives)
            or positives[0].get("scope") == positives[1].get("scope")
            or negatives[0].get("returncode") in (None, 0, 99)
            or "SENTRA config path must stay relative to its owned profile" not in negatives[0].get("stderr", "")):
        raise ValueError("RustDesk native profile isolation evidence missing")
    return native, inputs, records


def tree_files(root: Path) -> list[str]:
    result = []
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if name not in (".git", "target", "__pycache__", ".dart_tool"))
        for folder in folders:
            path = Path(directory) / folder
            if path.is_symlink() or path.is_junction():
                raise ValueError("linked source directory: " + str(path))
        result.extend((Path(directory) / name).relative_to(root).as_posix() for name in sorted(files) if name != ".git")
    return result


class Archive:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.raw = path.open("xb")
        self.compressed = gzip.GzipFile(filename="", fileobj=self.raw, mode="wb", mtime=0, compresslevel=3)
        self.tar = tarfile.open(fileobj=self.compressed, mode="w|")
        self.entries = []
        self.seen = set()

    def add(self, root: Path, name: str, prefix: str):
        path = owned_file(root, name)
        target = portable(prefix + "/" + name)
        if target.casefold() in self.seen:
            raise ValueError("duplicate source archive path: " + target)
        before = build.sha(path)
        info = tarfile.TarInfo(target)
        info.size, info.mode, info.mtime = path.stat().st_size, path.stat().st_mode & 0o777, 0
        with path.open("rb") as stream:
            self.tar.addfile(info, stream)
        if build.sha(path) != before:
            raise ValueError("source changed while archiving: " + str(path))
        self.entries.append({"path": target, "sha256": before, "bytes": info.size})
        self.seen.add(target.casefold())

    def close(self):
        self.tar.close(); self.compressed.close(); self.raw.close()


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:90]


def copy_licenses(root: Path, names: list[str], artifact: Path, category: str, label: str) -> list[str]:
    copied = []
    for name in names:
        if LEGAL.match(Path(name).name):
            target_name = "licenses/" + category + "/" + slug(label) + "/" + portable(name)
            target = artifact / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(owned_file(root, name), target)
            copied.append(target_name)
    return copied


def collect_cargo(source: Path, proofs: Path, artifact: Path, archive: Archive, gaps: list) -> list[dict]:
    log = owned_file(proofs, "profile-cargo.log")
    manifests = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("reason") == "compiler-artifact":
            manifests[item["package_id"]] = Path(item["manifest_path"]).resolve(strict=True)
    if not manifests:
        raise ValueError("actual Cargo build graph missing")
    cargo_root = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo"))).resolve(strict=True)
    local_names = list(build.source_inputs(source))
    components = []
    for identity, manifest in sorted(manifests.items()):
        root = manifest.parent
        if not root.is_relative_to(source) and not root.is_relative_to(cargo_root):
            raise ValueError("Cargo dependency outside owned source/cache")
        package = tomllib.loads(manifest.read_text(encoding="utf-8"))["package"]
        name, version = package["name"], package["version"]
        label = slug(name + "-" + str(version) + "-" + hashlib.sha256(identity.encode()).hexdigest()[:8])
        if root.is_relative_to(source):
            names = [(source / name).relative_to(root).as_posix() for name in local_names
                     if (source / name).is_relative_to(root) and LEGAL.match(Path(name).name)]
        else:
            names = tree_files(root)
        # The root and all pinned submodules are archived separately, including
        # local packages. Cargo cache dependencies retain their exact sources.
        if not root.is_relative_to(source):
            for relative in names:
                archive.add(root, relative, "cargo/" + label)
        legal = copy_licenses(root, names, artifact, "cargo", label)
        declared = package.get("license")
        license_file = package.get("license-file")
        if isinstance(license_file, str) and license_file not in names:
            target = owned_file(root, license_file)
            relative = "licenses/cargo/" + label + "/" + portable(license_file)
            (artifact / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, artifact / relative); legal.append(relative)
        if not legal:
            gaps.append({"code": "cargo_license_text_missing", "component": identity, "declared": declared})
        if not declared and not license_file:
            gaps.append({"code": "cargo_license_declaration_missing", "component": identity,
                         "available_license_files": legal})
        components.append({"ecosystem": "cargo", "name": name, "version": str(version), "identity": identity,
            "declared_license": declared, "license_files": legal, "manifest_sha256": build.sha(manifest),
            "inventory_scope": "observed compilation graph; includes build dependencies",
            "source_archive_prefix": "rustdesk" if root.is_relative_to(source) else "cargo/" + label})
    shutil.copy2(log, artifact / "provenance/cargo-build-graph.jsonl")
    return components


def pub_root(config: Path, uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        if parsed.netloc:
            raise ValueError("remote Pub package URI refused")
        return Path(unquote(parsed.path).lstrip("/") if os.name == "nt" else unquote(parsed.path)).resolve(strict=True)
    if parsed.scheme:
        raise ValueError("non-local Pub package URI refused")
    return (config.parent / unquote(uri)).resolve(strict=True)


def collect_pub(source: Path, toolchains: Path, artifact: Path, archive: Archive, gaps: list) -> list[dict]:
    import yaml
    config = owned_file(source, "flutter/.dart_tool/package_config.json")
    lock = yaml.safe_load(owned_file(source, "flutter/pubspec.lock").read_text(encoding="utf-8"))["packages"]
    cache = (Path(os.environ["PUB_CACHE"]) if os.environ.get("PUB_CACHE") else
             Path(os.environ["LOCALAPPDATA"]) / "Pub/Cache").resolve(strict=True)
    components = []
    for package in load_json(config)["packages"]:
        name = package["name"]
        root = pub_root(config, package["rootUri"])
        if not any(root.is_relative_to(base) for base in (source, toolchains, cache)):
            raise ValueError("Pub dependency outside selected source/toolchain/cache: " + name)
        pin = lock.get(name, {})
        label = slug(name + "-" + str(pin.get("version", "local")))
        names = tree_files(root) if not root.is_relative_to(source) else ["pubspec.yaml"]
        if not root.is_relative_to(source):
            for relative in names:
                archive.add(root, relative, "pub/" + label)
        legal = copy_licenses(root, names, artifact, "pub", label)
        if not legal and not root.is_relative_to(source):
            gaps.append({"code": "pub_license_text_missing", "component": name, "lock": pin})
        components.append({"ecosystem": "pub", "name": name, "version": str(pin.get("version", "local")),
            "identity": name, "lock": pin, "license_files": legal,
            "inventory_scope": "resolved Pub graph; tree shaking/linkage not attested",
            "source_archive_prefix": "rustdesk/flutter" if root.is_relative_to(source) else "pub/" + label})
    shutil.copy2(config, artifact / "provenance/pub-package-config.json")
    descriptor = owned_file(source, "flutter/.flutter-plugins-dependencies")
    shutil.copy2(descriptor, artifact / "provenance/flutter-plugin-dependencies.json")
    return components


def collect_vcpkg(toolchains: Path, artifact: Path, archive: Archive, gaps: list) -> list[dict]:
    root = (toolchains / "vcpkg-9e593bb").resolve(strict=True)
    revision = build._git(root, "rev-parse", "HEAD").strip()
    if revision != "9e593bb18ea69cc5095e012465dcd675a822ed0d":
        raise ValueError("vcpkg revision differs from approved build baseline")
    components = []
    for share in sorted((root / "installed/x64-windows-static/share").iterdir()):
        if not share.is_dir():
            continue
        name = share.name
        names = tree_files(share)
        legal = copy_licenses(share, names, artifact, "vcpkg", name)
        sbom_file = share / "vcpkg.spdx.json"
        spdx = load_json(sbom_file) if sbom_file.is_file() else {}
        port = next((p for p in spdx.get("packages", []) if p.get("SPDXID") == "SPDXRef-port"), {})
        resources = share / "vcpkg-spdx-resources.json"
        if sbom_file.is_file():
            target = artifact / ("provenance/vcpkg/" + name + ".spdx.json")
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(sbom_file, target)
        for relative in names:
            archive.add(share, relative, "vcpkg/installed-share/" + name)
        source_dirs = sorted((root / "buildtrees" / name / "src").glob("*"))
        for directory in source_dirs:
            if directory.is_dir():
                for relative in tree_files(directory):
                    archive.add(directory, relative, "vcpkg/sources/" + name + "/" + slug(directory.name))
        # Store exact applied build scripts/configuration and the source recipe,
        # not compiled object caches. Original package SPDX retains download pins.
        buildtree = root / "buildtrees" / name
        for relative in ("x64-windows-static-rel/config.h", "x64-windows-static-rel/build.sh", "x64-windows-static.vcpkg_abi_info.txt"):
            if (buildtree / relative).is_file():
                archive.add(buildtree, relative, "vcpkg/build-config/" + name)
        recipe = root / "ports" / name
        if recipe.is_dir():
            for relative in tree_files(recipe):
                archive.add(recipe, relative, "vcpkg/baseline-recipes/" + name)
        if not legal:
            gaps.append({"code": "vcpkg_license_text_missing", "component": name})
        if resources.is_file() and load_json(resources).get("packages") and not source_dirs:
            gaps.append({"code": "vcpkg_source_tree_missing", "component": name})
        components.append({"ecosystem": "vcpkg", "name": name, "version": port.get("versionInfo", "unknown"),
            "identity": name, "declared_license": port.get("licenseDeclared"), "license_files": legal,
            "inventory_scope": "installed static build inputs; exact link contribution not attested",
            "source_archive_prefix": "vcpkg/sources/" + name, "baseline": revision})
    return components


def compact_gate(manifest: dict) -> dict:
    revision = manifest.get("source_revision", manifest.get("upstream", {}).get("revision"))
    if not isinstance(revision, str) or not re.fullmatch("[0-9a-f]{40}", revision):
        raise ValueError("exact RustDesk source revision required for compact gate")
    gate = {key: manifest[key] for key in ("executable", "executable_sha256", "control_extension",
        "extension", "stock_cli_supported", "compiled", "bundle_sha256")}
    gate.update(source_revision=revision, validated=False, homologated=False)
    raw = json.dumps(gate, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if len(raw) > 65536:
        raise ValueError("RustDesk runtime gate manifest exceeds 64 KiB")
    return gate


def _finalize_runtime_manifest(artifact: Path) -> dict:
    """Audit and attach bounded runtime metadata, preserving the prior proof.

    This also upgrades a component materialized before the small-gate contract,
    without rebuilding or re-archiving source bytes. The previous manifest and
    finalizer source/hash remain shipped evidence of that metadata transform.
    """
    path = owned_file(artifact, "manifest.json")
    manifest = load_json(path, 1024 * 1024)
    listed = manifest.get("files", [])
    expected = {item["path"]: item["sha256"] for item in listed}
    if len(expected) != len(listed) or len({name.casefold() for name in expected}) != len(expected):
        raise ValueError("duplicate materialized component file")
    actual = {p.relative_to(artifact).as_posix() for p in artifact.rglob("*") if p.is_file()}
    if actual != set(expected) | {"manifest.json"}:
        raise ValueError("materialized component file set changed before runtime gate")
    for name, digest in expected.items():
        if build.sha(owned_file(artifact, name)) != digest:
            raise ValueError("materialized bytes changed before runtime gate: " + name)
    _native_payload(artifact, "rustdesk", manifest)
    gate = compact_gate(manifest)
    if manifest.get("bundle_manifest"):
        existing = owned_file(artifact, manifest["bundle_manifest"])
        if load_json(existing, 65536) != gate or build.sha(existing) != manifest.get("bundle_manifest_sha256"):
            raise ValueError("existing runtime gate differs from its release pins")
        return {"artifact": str(artifact), "files": len(expected), "bundle_files": len(gate["bundle_sha256"]),
                "manifest_sha256": build.sha(path), "build_manifest_bytes": existing.stat().st_size,
                "compiled": True, "validated": False, "legal_release_ready": False}
    previous_sha = build.sha(path)
    shutil.copy2(path, artifact / "provenance/manifest-before-runtime-gate.json")
    shutil.copy2(Path(__file__), artifact / "corresponding-source/metadata-materializer.py")
    write_json(artifact / "bundle-manifest.json", gate)
    gate_sha = build.sha(artifact / "bundle-manifest.json")
    # Explicit file entries tie every shipped executable/library/asset to the
    # SBOM, while dependency inventories retain their honest superset scope.
    sbom_path = owned_file(artifact, "sbom.cdx.json")
    sbom = load_json(sbom_path)
    for name, digest in sorted(gate["bundle_sha256"].items()):
        sbom["components"].append({"type": "file", "bom-ref": "runtime-file:" + name, "name": name,
            "hashes": [{"alg": "SHA-256", "content": digest}]})
    inventory_path = owned_file(artifact, "dependency-inventory.json")
    inventory = load_json(inventory_path)
    if not any(item["name"] == "dylib_virtual_display" and item["ecosystem"] == "cargo" for item in inventory):
        inventory.append({"ecosystem": "cargo", "name": "dylib_virtual_display", "version": "0.1.0",
            "identity": "native helper from native-proof.json", "declared_license": None,
            "license_files": ["LICENSE-RustDesk.txt"], "source_archive_prefix": "rustdesk/libs/virtual_display/dylib",
            "inventory_scope": "separately compiled native helper; root license supplied, package declaration absent"})
        sbom["components"].append({"type": "library", "bom-ref": "native-helper:dylib_virtual_display",
            "name": "dylib_virtual_display", "version": "0.1.0", "properties": [
                {"name": "sentra:inventory-scope", "value": "separately compiled native helper"}]})
        legal_path = owned_file(artifact, "legal-review.json")
        legal = load_json(legal_path)
        legal["review_required"].append({"code": "cargo_license_declaration_missing", "component": "dylib_virtual_display",
            "available_license_files": ["LICENSE-RustDesk.txt"], "detail": "Native helper package has no license declaration; no inherited grant is asserted."})
        write_json(legal_path, legal)
        write_json(inventory_path, inventory)
    write_json(sbom_path, sbom)
    write_json(artifact / "provenance/runtime-gate-finalization.json", {
        "schema_version": 1, "previous_manifest_sha256": previous_sha, "bundle_manifest_sha256": gate_sha,
        "materializer_sha256": build.sha(Path(__file__)), "sources_rearchived": False, "binaries_rebuilt": False,
        "validated": False, "homologated": False, "legal_release_ready": False})
    manifest.update(source_revision=gate["source_revision"], bundle_manifest="bundle-manifest.json", bundle_manifest_sha256=gate_sha)
    manifest["files"] = [{"path": p.relative_to(artifact).as_posix(), "sha256": build.sha(p)}
                         for p in sorted(artifact.rglob("*")) if p.is_file() and p != path]
    # The release manifest is replaced last, after every new metadata byte has
    # a pin. A failed transform cannot publish a success report.
    temporary = path.with_name("manifest.next")
    write_json(temporary, manifest)
    if temporary.stat().st_size > 1024 * 1024:
        raise ValueError("RustDesk complete manifest exceeds release component bound")
    os.replace(temporary, path)
    return {"artifact": str(artifact), "files": len(manifest["files"]), "bundle_files": len(gate["bundle_sha256"]),
            "dependencies": len(inventory), "manifest_sha256": build.sha(path),
            "build_manifest_bytes": (artifact / "bundle-manifest.json").stat().st_size,
            "compiled": True, "validated": False, "legal_release_ready": False}


def finalize_runtime_manifest(artifact: Path) -> dict:
    artifact = artifact.resolve(strict=True)
    with _BuildLock(artifact.parent / (artifact.name + ".materialize.lock"), "RustDesk component metadata finalization"):
        return _finalize_runtime_manifest(artifact)


def _materialize(source: Path, proofs: Path, toolchains: Path, output: Path, abi_report: Path | None):
    native, inputs, records = verify_proofs(source, proofs)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("component already exists; select a new isolated destination")
    artifact = Path(tempfile.mkdtemp(prefix=output.name + "-partial-", dir=output.parent))
    (artifact / "provenance").mkdir()
    gaps = [{"code": "legal_release_review_pending", "detail": "Collected source/notice evidence is not legal distribution approval."},
            {"code": "runtime_linkage_scope_not_fully_attributed", "detail": "Cargo compilation, resolved Pub and installed vcpkg inventories are supersets, not an exact per-symbol runtime dependency proof."}]
    for name, digest in records["flutter"]["proof"]["outputs"].items():
        target = artifact / name[len(BUNDLE):]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(owned_file(source, name), target)
        if build.sha(target) != digest:
            raise ValueError("bundle changed during materialization")
    for phase in records:
        shutil.copy2(owned_file(proofs, phase + "-proof.json"), artifact / ("provenance/" + phase + "-proof.json"))
    if abi_report:
        report = load_json(abi_report)
        if (report.get("library_sha256") != build.sha(artifact / "librustdesk.dll")
                or report.get("native_build_proof_sha256") != records["native"]["sha256"]):
            raise ValueError("ABI report does not identify this native build")
        shutil.copy2(abi_report, artifact / "provenance/abi-report.json")
    notices = owned_file(artifact, "data/flutter_assets/NOTICES.Z")
    with gzip.open(notices, "rb") as stream:
        expanded = stream.read(16 * 1024 * 1024 + 1)
    if len(expanded) > 16 * 1024 * 1024:
        raise ValueError("Flutter notices exceed bound")
    (artifact / "THIRD_PARTY_NOTICES-Flutter.txt").write_bytes(expanded)
    engine = toolchains / "flutter3.24.5/flutter/bin/cache/artifacts/engine/windows-x64-release"
    shutil.copy2(owned_file(engine, "license.windows_flutter.md"), artifact / "LICENSE-Flutter-engine.txt")
    shutil.copy2(owned_file(source, "LICENCE"), artifact / "LICENSE-RustDesk.txt")
    archive = Archive(artifact / "corresponding-source/sources.tar.gz")
    try:
        for name in sorted(set(inputs) | {"src/version.rs"}):
            archive.add(source, name, "rustdesk")
        for name in ("scripts/commander/build_rustdesk.py", "scripts/commander/flutter_plugin_links.py",
                     "scripts/commander/materialize_rustdesk.py", "sentra_executors/remote_rustdesk_build.py",
                     "sentra_executors/remote_rustdesk_gate.rs", "tests/qa/rustdesk_profile_native.rs"):
            archive.add(ROOT, name, "sentra-build-tools")
        components = collect_cargo(source, proofs, artifact, archive, gaps)
        components.extend(collect_pub(source, toolchains, artifact, archive, gaps))
        components.extend(collect_vcpkg(toolchains, artifact, archive, gaps))
    finally:
        archive.close()
    write_json(artifact / "corresponding-source/files.json", archive.entries)
    write_json(artifact / "dependency-inventory.json", components)
    write_json(artifact / "legal-review.json", {"release_ready": False, "review_required": gaps,
        "corresponding_source_completeness_verified": False,
        "ffmpeg_configuration": "See vcpkg/build-config/ffmpeg/config.h inside source archive; no inferred license grant."})
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "metadata": {"component": {"type": "application", "name": "sentra-rustdesk", "version": "1.5.0"}},
        "components": [{"type": "library", "bom-ref": str(index), "name": c["name"], "version": c["version"],
            "properties": [{"name": "sentra:ecosystem", "value": c["ecosystem"]},
                           {"name": "sentra:inventory-scope", "value": c["inventory_scope"]}],
            **({"licenses": [{"license": {"name": c["declared_license"]}}]} if isinstance(c.get("declared_license"), str) else {})}
            for index, c in enumerate(components)]}
    write_json(artifact / "sbom.cdx.json", sbom)
    bundle_pins = {name[len(BUNDLE):]: digest for name, digest in records["flutter"]["proof"]["outputs"].items()}
    provenance = {"schema_version": 1, "source": native, "input_snapshot_sha256": records["native"]["proof"]["input_snapshot_sha256"],
        "proofs": {phase: {"sha256": entry["sha256"], "tooling_inputs": entry["proof"]["tooling_inputs"],
                            "toolchain": entry["proof"]["toolchain"]} for phase, entry in records.items()},
        "materializer_sha256": build.sha(Path(__file__)), "compiled": True, "materialized": True,
        "validated": False, "homologated": False, "peer_connectivity_verified": False,
        "legal_release_ready": False, "source_archive_sha256": build.sha(artifact / "corresponding-source/sources.tar.gz"),
        "created_at": datetime.now(timezone.utc).isoformat()}
    write_json(artifact / "provenance.json", provenance)
    if build.source_inputs(source) != inputs or any(build.sha(owned_file(source, BUNDLE + name)) != digest for name, digest in bundle_pins.items()):
        raise ValueError("RustDesk source/bundle changed during materialization")
    files = [{"path": p.relative_to(artifact).as_posix(), "sha256": build.sha(p)} for p in sorted(artifact.rglob("*")) if p.is_file()]
    if len(files) > 20000 or sum(p.stat().st_size for p in artifact.rglob("*") if p.is_file()) > 4 * 1024 ** 3:
        raise ValueError("component exceeds release materialization quota")
    manifest = {"schema_version": 1, "component": "rustdesk", "compiled": True,
        "executable": "rustdesk.exe", "executable_sha256": bundle_pins["rustdesk.exe"],
        "control_extension": "sentra-desktop-control-v1", "extension": "sentra-peer-gate-v1",
        "stock_cli_supported": False, "bundle_sha256": bundle_pins, "files": files,
        "upstream": {"url": native["upstream"], "revision": native["source_revision"], "license": "GNU AGPL v3 (LICENCE)"},
        "sbom": "sbom.cdx.json", "provenance": "provenance.json", "validated": False,
        "homologated": False, "legal_release_ready": False, "legal_review": "legal-review.json"}
    _native_payload(artifact, "rustdesk", manifest)
    write_json(artifact / "manifest.json", manifest)
    final = _finalize_runtime_manifest(artifact)
    artifact.rename(output)
    return {**final, "artifact": str(output), "legal_review_items": len(gaps) + 1}


def materialize(source: Path, proofs: Path, toolchains: Path, output: Path, abi_report: Path | None = None):
    source, proofs, toolchains = source.resolve(strict=True), proofs.resolve(strict=True), toolchains.resolve(strict=True)
    output = output.resolve()
    if any(output == root or output.is_relative_to(root) or root.is_relative_to(output) for root in (source, proofs, toolchains)):
        raise ValueError("component output must be separate from source/proofs/toolchains")
    with _BuildLock(source.parent / (source.name + ".sentra-build.lock"), "RustDesk source materialization"), \
            _BuildLock(output.parent / (output.name + ".materialize.lock"), "RustDesk component materialization"):
        return _materialize(source, proofs, toolchains, output, abi_report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "proofs", "toolchains", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--abi-report", type=Path)
    args = parser.parse_args()
    print(json.dumps(materialize(**vars(args)), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
