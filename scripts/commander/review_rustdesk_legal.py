"""Collect version-bound notice evidence into a NEW isolated RustDesk candidate.

This is an engineering evidence review, not a fabricated license grant. Separate
repositories with no authoritative grant remain unresolved. Frozen v1 bytes are
never modified; network responses retain their origin and exact content hash.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.commander import materialize_rustdesk as materializer

NOTICE = re.compile(r"^(?:licen[cs]e|copying|copyright|notice|unlicense)(?:[._-].*)?$", re.I)
ALLOWED = {"api.github.com", "raw.githubusercontent.com", "codeberg.org", "pypi.org", "files.pythonhosted.org", "www.apache.org"}


def fetch(url: str, cache: Path) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED or parsed.username or parsed.password:
        raise ValueError("non-official/untrusted evidence origin")
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()
    metadata, body = cache / (key + ".json"), cache / (key + ".body")
    if metadata.is_file():
        record = materializer.load_json(metadata)
        if record["url"] != url or (record["status"] == 200 and
                (Path(record.get("cache_file", "")).resolve() != body.resolve()
                 or body.is_symlink() or not body.is_file() or materializer.build.sha(body) != record["sha256"])):
            raise ValueError("evidence cache changed")
        return record
    try:
        with urlopen(Request(url, headers={"User-Agent": "SENTRA-version-bound-source-audit", "Accept": "application/vnd.github+json"}), timeout=30) as response:
            if urlparse(response.url).hostname not in ALLOWED:
                raise ValueError("evidence redirect escaped official origin")
            data = response.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024:
                raise ValueError("evidence exceeds bound")
            body.write_bytes(data)
            record = {"url": url, "final_url": response.url, "status": response.status,
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "cache_file": str(body),
                "etag": response.headers.get("ETag")}
    except HTTPError as error:
        record = {"url": url, "status": error.code, "error": error.reason}
    materializer.write_json(metadata, record)
    return record


def github_repository(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    return "/".join(parts[:2]) if parsed.hostname == "github.com" and len(parts) >= 2 else None


def cargo_packages(proofs: Path) -> dict:
    result = {}
    for line in (proofs / "profile-cargo.log").read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("reason") == "compiler-artifact":
            manifest = Path(record["manifest_path"]).resolve(strict=True)
            package = tomllib.loads(manifest.read_text(encoding="utf-8"))["package"]
            vcs_path = manifest.parent / ".cargo_vcs_info.json"
            vcs = materializer.load_json(vcs_path) if vcs_path.is_file() else {}
            revision = vcs.get("git", {}).get("sha1")
            if " (git+" in record["package_id"]:
                revision = record["package_id"].rsplit("#", 1)[-1].rstrip(")")
                repository = github_repository(record["package_id"].split(" (git+", 1)[-1].split("?", 1)[0].split("#", 1)[0])
            else:
                repository = github_repository(package.get("repository")) or github_repository(package.get("homepage"))
            result[record["package_id"]] = {"root": manifest.parent, "metadata": package, "vcs": vcs,
                                          "revision": revision, "repository": repository}
    # Some old target crates omit repository but share the exact VCS commit
    # with the main crate. This supplies an observed association, not 'latest'.
    repos = {p["revision"]: p["repository"] for p in result.values() if p["revision"] and p["repository"]}
    for package in result.values():
        if not package["repository"]:
            package["repository"] = repos.get(package["revision"])
    return result


def pinned_root_notices(repository: str, revision: str, cache: Path) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not re.fullmatch("[0-9a-f]{40}", revision):
        raise ValueError("exact GitHub repository/commit required")
    listing = fetch("https://api.github.com/repos/" + repository + "/contents?ref=" + revision, cache)
    result = {"repository": repository, "revision": revision, "listing": listing, "notices": []}
    if listing["status"] != 200:
        return result
    entries = json.loads(Path(listing["cache_file"]).read_text(encoding="utf-8"))
    for entry in entries:
        if entry["type"] == "file" and NOTICE.match(entry["name"]):
            result["notices"].append(fetch("https://raw.githubusercontent.com/" + repository + "/" + revision + "/" + quote(entry["path"], safe="/"), cache))
        elif entry["type"] == "dir" and entry["name"].upper() == "LICENSES":
            children = fetch("https://api.github.com/repos/" + repository + "/contents/" + quote(entry["path"], safe="/") + "?ref=" + revision, cache)
            if children["status"] == 200:
                for child in json.loads(Path(children["cache_file"]).read_text(encoding="utf-8")):
                    if child["type"] == "file":
                        result["notices"].append(fetch("https://raw.githubusercontent.com/" + repository + "/" + revision + "/" + quote(child["path"], safe="/"), cache))
    return result


def collect(source: Path, proofs: Path, frozen: Path, cache: Path):
    packages = cargo_packages(proofs)
    review = materializer.load_json(frozen / "legal-review.json")
    identities = {row["component"] for row in review["review_required"] if row["code"] == "cargo_license_text_missing"}
    pairs = {(packages[name]["repository"], packages[name]["revision"]) for name in identities
             if packages[name]["repository"] and packages[name]["revision"]}
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda pair: pinned_root_notices(*pair, cache), sorted(pairs)))
    materializer.write_json(cache / "pinned-root-notices.json", results)
    return {"repositories": len(results), "notices": sum(sum(n["status"] == 200 for n in result["notices"]) for result in results),
            "listing_failures": [{"repository": r["repository"], "revision": r["revision"], "status": r["listing"]["status"]}
                                 for r in results if r["listing"]["status"] != 200]}


def verify_component(artifact: Path, expected_sha: str) -> dict:
    manifest_file = materializer.owned_file(artifact, "manifest.json")
    if materializer.build.sha(manifest_file) != expected_sha:
        raise ValueError("frozen component manifest pin changed")
    manifest = materializer.load_json(manifest_file, 1024 * 1024)
    listed = {item["path"]: item["sha256"] for item in manifest["files"]}
    if len(listed) != len(manifest["files"]) or len({p.casefold() for p in listed}) != len(listed):
        raise ValueError("duplicate frozen component path")
    actual = {p.relative_to(artifact).as_posix() for p in artifact.rglob("*") if p.is_file()}
    if actual != set(listed) | {"manifest.json"}:
        raise ValueError("frozen component file set changed")
    for name, digest in listed.items():
        if materializer.build.sha(materializer.owned_file(artifact, name)) != digest:
            raise ValueError("frozen component bytes changed: " + name)
    return manifest


def review_candidate(*, source: Path, proofs: Path, toolchains: Path, frozen: Path, output: Path, cache: Path,
                     frozen_manifest_sha256: str) -> dict:
    source, proofs, toolchains, frozen, cache = (p.resolve(strict=True) for p in (source, proofs, toolchains, frozen, cache))
    output = output.resolve()
    if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in (frozen, source, proofs, toolchains, cache)):
        raise ValueError("legal candidate must be separate from frozen evidence/source")
    if output.exists():
        raise FileExistsError("select a fresh legal-review candidate")
    baseline = verify_component(frozen, frozen_manifest_sha256)
    materializer.verify_proofs(source, proofs)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(frozen, output)
    if verify_component(output, frozen_manifest_sha256) != baseline:
        raise ValueError("copied legal candidate differs from frozen component")
    packages = cargo_packages(proofs)
    inventory = materializer.load_json(output / "dependency-inventory.json")
    by_identity = {row["identity"]: row for row in inventory}
    original_review = materializer.load_json(output / "legal-review.json")
    roots = materializer.load_json(cache / "pinned-root-notices.json")
    extras = materializer.load_json(cache / "extra-notices.json") if (cache / "extra-notices.json").is_file() else []
    pinned = {}
    for row in [*roots, *extras]:
        pinned.setdefault((row["repository"], row["revision"]), []).extend(n for n in row["notices"] if n["status"] == 200)
    evidence = []

    def local(path: Path, origin: str, role="notice"):
        path = path.resolve(strict=True)
        digest = materializer.build.sha(path)
        name = "licenses/reviewed/" + digest[:16] + "-" + materializer.slug(path.name)
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)
        if materializer.build.sha(destination) != digest:
            raise ValueError("legal evidence copy changed")
        record = {"path": name, "sha256": digest, "origin": origin, "role": role}
        evidence.append(record)
        return record

    def remote(record: dict):
        if record["status"] != 200:
            raise ValueError("unsuccessful HTTP response is not license evidence")
        path = Path(record["cache_file"])
        if path.resolve() != (cache / (hashlib.sha256(record["url"].encode()).hexdigest() + ".body")).resolve():
            raise ValueError("notice cache path escaped its origin binding")
        if materializer.build.sha(path) != record["sha256"]:
            raise ValueError("retrieved notice changed")
        result = local(path, record["url"])
        # Retain the readable original filename without depending on cache paths.
        result["original_filename"] = record["url"].rsplit("/", 1)[-1]
        return result

    apache_record = fetch("https://www.apache.org/licenses/LICENSE-2.0.txt", cache)
    apache = remote(apache_record) if apache_record["status"] == 200 else None
    flutter_root = toolchains / "flutter3.24.5/flutter"
    flutter_revision = materializer.build._git(flutter_root, "rev-parse", "HEAD").strip()
    if flutter_revision != "dec2ee5c1f98f8e84a7d5380c05eb8a3d0a81668":
        raise ValueError("Flutter SDK license does not match pinned framework")
    sdk_notice = local(flutter_root / "LICENSE", "https://github.com/flutter/flutter/blob/" + flutter_revision + "/LICENSE")
    for name in ("COPYRIGHT", "LICENSE-MIT", "LICENSE-APACHE"):
        root = Path.home() / ".rustup/toolchains/1.75.0-x86_64-pc-windows-msvc/share/doc/rust"
        local(root / name, "rustup:1.75.0-x86_64-pc-windows-msvc/share/doc/rust/" + name)

    vcpkg = toolchains / "vcpkg-9e593bb"
    resources_path = vcpkg / "installed/x64-windows-static/share/vcpkg-tool-meson/vcpkg-spdx-resources.json"
    resources = materializer.load_json(resources_path)["packages"]
    meson = next(row for row in resources if row.get("packageFileName") == "meson-1.9.0.tar.gz")
    checksum = next(row["checksumValue"] for row in meson["checksums"] if row["algorithm"] == "SHA512")
    meson_path = vcpkg / "downloads/meson-1.9.0.tar.gz"
    if hashlib.sha512(meson_path.read_bytes()).hexdigest() != checksum:
        raise ValueError("Meson source differs from vcpkg source pin")
    meson_target = output / "corresponding-source/meson-1.9.0.tar.gz"
    shutil.copy2(meson_path, meson_target)
    meson_evidence = {"path": meson_target.relative_to(output).as_posix(), "sha256": materializer.build.sha(meson_target),
        "sha512": checksum, "origin": meson["downloadLocation"], "role": "build-tool-source"}
    evidence.append(meson_evidence)
    local(resources_path, "vcpkg:installed/vcpkg-tool-meson/vcpkg-spdx-resources.json", "source-pin")

    # These old crates predate cargo_vcs_info. A release tag plus identical
    # published source bytes ties the shared root notice to the actual package.
    old = {"serial": ("dcuddeback/serial-rs", "7ed6540c2789b7c7365cd7a89fcb7bac7c567de8", "serial/src/lib.rs"),
           "dlopen_derive": ("szymonwieloch/rust-dlopen", "26b70292744db1052403378d4a01075b6171e3d1", "rust-dlopen-derive/src/lib.rs")}
    resolutions = []
    for index, issue in enumerate(original_review["review_required"]):
        component, code = issue.get("component"), issue["code"]
        resolution = {"id": index, "original": issue, "status": "unresolved", "evidence": []}
        if code.startswith("cargo_"):
            package = packages.get(component)
            name = component.split()[0]
            if name == "dylib_virtual_display":
                root = source / "libs/virtual_display/dylib"
                package = {"root": root, "metadata": tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))["package"], "repository": None, "revision": None}
            if package:
                root = package["root"]
                git_root = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
                same_project = git_root.returncode == 0 and Path(git_root.stdout.strip()).resolve() == source
                declared = package["metadata"].get("license")
                ns = pinned.get((package["repository"], package["revision"]), [])
                if same_project and code == "cargo_license_declaration_missing":
                    resolution.update(status="resolved_collection", reason="Package belongs to the same pinned project tree; root LICENCE is supplied. No new per-package declaration was invented.")
                    resolution["evidence"].append(local(source / "LICENCE", "rustdesk:" + baseline["source_revision"] + "/LICENCE"))
                elif same_project and not declared:
                    resolution.update(status="resolved_collection", reason="Root LICENCE covers the pinned project source tree; package is not a separate Git repository.")
                    resolution["evidence"].append(local(source / "LICENCE", "rustdesk:" + baseline["source_revision"] + "/LICENCE"))
                elif ns:
                    resolution.update(status="resolved_collection", reason="Notice retrieved from the repository at the package's recorded exact VCS commit.")
                    resolution["evidence"].extend(remote(item) for item in ns)
                elif package["repository"] == "codeberg.org/xfix/enum-map" or "codeberg.org/xfix/enum-map" in str(package["metadata"].get("repository")):
                    ns = [fetch("https://codeberg.org/xfix/enum-map/raw/commit/" + package["revision"] + "/LICENSES/" + n, cache) for n in ("MIT.txt", "Apache-2.0.txt")]
                    if all(n["status"] == 200 for n in ns):
                        resolution.update(status="resolved_collection", reason="Workspace LICENSES files from the exact Codeberg package VCS commit.")
                        resolution["evidence"].extend(remote(item) for item in ns)
                elif name in old:
                    repo, revision, relative = old[name]
                    anchor = fetch("https://raw.githubusercontent.com/" + repo + "/" + revision + "/" + relative, cache)
                    if anchor["status"] == 200 and Path(anchor["cache_file"]).read_bytes() == (root / "src/lib.rs").read_bytes():
                        resolution.update(status="resolved_collection", reason="Official release tree notice plus byte-identical published crate source anchor.")
                        resolution["evidence"].extend(remote(n) for n in pinned[(repo, revision)])
                        resolution["evidence"].append(remote(anchor))
                elif name == "qrcodegen":
                    text = (root / "src/lib.rs").read_text(encoding="utf-8")[:6000]
                    if "PERMISSION IS HEREBY GRANTED" in text.upper() and "SOFTWARE IS PROVIDED" in text.upper():
                        resolution.update(status="resolved_collection", reason="Full MIT notice and copyright are embedded in the published source header.")
                        resolution["evidence"].append(local(root / "src/lib.rs", component + ":src/lib.rs"))
                elif isinstance(declared, str) and "Apache-2.0" in declared and apache:
                    resolution.update(status="resolved_collection", reason="Published package explicitly declares an Apache-2.0 option; canonical full text and original package metadata are supplied. No grant is inferred for undeclared repositories.")
                    resolution["evidence"].extend([apache, local(root / "Cargo.toml", component + ":Cargo.toml", "published-license-declaration")])
                    if (root / "README.md").is_file():
                        resolution["evidence"].append(local(root / "README.md", component + ":README.md"))
                if resolution["status"] == "unresolved":
                    resolution["reason"] = "Separate repository has no explicit snapshot grant." if not declared else "Published license declaration exists; an attributable full notice for this historical snapshot remains unverified."
                    resolution["evidence"].append(local(root / "Cargo.toml", component + ":Cargo.toml", "published-package-metadata"))
                    for readme in (root / "README.md", root / "readme.md"):
                        if readme.is_file():
                            resolution["evidence"].append(local(readme, component + ":" + readme.name, "published-readme"))
                row = by_identity.get(component)
                if row:
                    row["notice_review_status"] = resolution["status"]
                    row["license_files"] = sorted(set(row["license_files"]) | {e["path"] for e in resolution["evidence"]})
        elif code == "pub_license_text_missing":
            resolution.update(status="resolved_collection", reason="SDK package is part of the pinned Flutter tree; framework root BSD notice is supplied.", evidence=[sdk_notice])
        elif code == "vcpkg_source_tree_missing" and component == "vcpkg-tool-meson":
            resolution.update(status="resolved_collection", reason="Official Meson source archive matches the exact vcpkg SHA-512; applied patches/recipes are retained in existing sources.", evidence=[meson_evidence])
        elif code == "vcpkg_license_text_missing":
            owners = {"jpeg": "libjpeg-turbo", "unofficial-libvpx": "libvpx", "aclocal": "pkgconf"}
            owner = owners[component]
            info = next((vcpkg / "installed/vcpkg/info").glob(owner + "_*.list"))
            if "/share/" + component + "/" not in info.read_text(encoding="utf-8"):
                raise ValueError("vcpkg alias ownership not established")
            resolution.update(status="resolved_collection", reason="Installed ownership list identifies an alias/build macro belonging to " + owner + "; it is not an additional runtime library.")
            resolution["evidence"].append(local(info, "vcpkg:installed/vcpkg/info/" + info.name, "installed-file-ownership"))
            if component == "aclocal":
                resolution["evidence"].append(local(vcpkg / "installed/x64-windows-static/share/aclocal/pkg.m4", "vcpkg:pkgconf/pkg.m4 (inline GPL notice and Autoconf exception)"))
            else:
                resolution["evidence"].append(local(vcpkg / ("installed/x64-windows-static/share/" + owner + "/copyright"), "vcpkg:" + owner + "/copyright"))
        else:
            resolution["reason"] = "Distribution approval and static-linking obligations remain separate from automated notice collection."
        resolutions.append(resolution)

    # hwcodec contains additional third-party notices in source headers. Keep
    # them for binary notices even though this does not license the wrapper.
    hwcodec = next(row["root"] for name, row in packages.items() if name.startswith("hwcodec "))
    for path in sorted((hwcodec / "externals").rglob("*")):
        if path.is_file() and path.suffix.lower() in (".cpp", ".h"):
            prefix = path.read_text(encoding="utf-8", errors="replace")[:8000]
            if "Copyright" in prefix and ("Redistribution" in prefix or "Permission is hereby" in prefix):
                local(path, "hwcodec:778df1f99597722473b29443bac22ae6c23946fe/" + path.relative_to(hwcodec).as_posix(), "embedded-third-party-notice")
    shutil.copy2(output / "manifest.json", output / "provenance/manifest-before-legal-review-v2.json")
    shutil.copy2(Path(__file__), output / "corresponding-source/legal-reviewer.py")
    materializer.write_json(output / "legal-evidence.json", evidence)
    materializer.write_json(output / "legal-resolutions.json", resolutions)
    unresolved = [row for row in resolutions if row["status"] != "resolved_collection"]
    materializer.write_json(output / "legal-review.json", {"release_ready": False,
        "corresponding_source_completeness_verified": False, "review_required": [row["original"] for row in unresolved],
        "resolved_collection_count": len(resolutions) - len(unresolved), "unresolved_count": len(unresolved),
        "resolution_evidence": "legal-resolutions.json", "note": "Collection findings are not automatic license violations or fabricated grants."})
    materializer.write_json(output / "dependency-inventory.json", inventory)
    materializer.write_json(output / "provenance/legal-review-v2.json", {"parent_manifest_sha256": frozen_manifest_sha256,
        "reviewer_sha256": materializer.build.sha(Path(__file__)), "binaries_rebuilt": False,
        "resolved_collection": len(resolutions) - len(unresolved), "unresolved": len(unresolved),
        "legal_release_ready": False, "source_archive_sha256": materializer.build.sha(output / "corresponding-source/sources.tar.gz")})
    baseline["legal_evidence"], baseline["legal_resolutions"] = "legal-evidence.json", "legal-resolutions.json"
    baseline["files"] = [{"path": p.relative_to(output).as_posix(), "sha256": materializer.build.sha(p)}
                         for p in sorted(output.rglob("*")) if p.is_file() and p.name != "manifest.json"]
    materializer.write_json(output / "manifest.json", baseline)
    if (output / "manifest.json").stat().st_size > 1024 * 1024:
        raise ValueError("legal candidate release manifest exceeds bound")
    verify_component(frozen, frozen_manifest_sha256)
    result = {"artifact": str(output), "parent_manifest_sha256": frozen_manifest_sha256,
        "manifest_sha256": materializer.build.sha(output / "manifest.json"), "resolved_collection": len(resolutions) - len(unresolved),
        "unresolved": len(unresolved), "legal_release_ready": False, "files": len(baseline["files"])}
    materializer.write_json(cache / "v2-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "proofs", "frozen", "cache"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--toolchains", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--frozen-manifest-sha256")
    args = parser.parse_args()
    if args.output:
        if not args.toolchains or not args.frozen_manifest_sha256:
            parser.error("v2 review requires toolchains and explicit frozen manifest pin")
        result = review_candidate(**vars(args))
    else:
        result = collect(args.source, args.proofs, args.frozen, args.cache)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
