"""Preserve published MIT package metadata without inventing copyright notices.

The supplement resolves what the publisher supplied. It does not apply an SPDX
template to a project, fill in a copyright holder/year, or approve distribution.
Frozen native components are not touched.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.commander import materialize_rustdesk as materializer

PACKAGES = {("memalloc", "0.1.0"), ("repng", "0.2.2"), ("scrap", "0.5.0")}
NOTICE = re.compile(r"^(license|licence|copying|copyright|notice|unlicense)(?:[._-].*)?$", re.I)


def inspect_crate(path: Path, name: str, version: str, expected_checksum: str) -> dict:
    digest = materializer.build.sha(path)
    if digest != expected_checksum:
        raise ValueError("published crate checksum mismatch")
    prefix = name + "-" + version + "/"
    files, manifests = [], {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            materializer.portable(member.name)
            if not member.isfile() or not member.name.startswith(prefix) or member.size > 16 * 1024 * 1024:
                raise ValueError("unexpected/linked published crate member")
            raw = archive.extractfile(member).read()
            relative = member.name[len(prefix):]
            files.append({"path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
            if relative in ("Cargo.toml", "Cargo.toml.orig"):
                manifests[relative] = tomllib.loads(raw.decode("utf-8"))["package"]
    package = manifests.get("Cargo.toml.orig", manifests.get("Cargo.toml"))
    if (not package or package["name"] != name or str(package["version"]) != version or package.get("license") != "MIT"):
        raise ValueError("published package MIT declaration/version differs")
    if len(files) != len({row["path"].casefold() for row in files}):
        raise ValueError("duplicate published crate path")
    return {"name": name, "version": version, "published_license": package["license"],
        "authors_verbatim": package.get("authors", []), "crate_sha256": digest, "files": files,
        "standalone_notice_filenames": [row["path"] for row in files if NOTICE.match(Path(row["path"]).name)],
        "copyright_holder_inferred": False, "copyright_year_inferred": False,
        "license_grant_source": "publisher's original Cargo package metadata, not the generic SPDX template"}


def supplement(source: Path, cache: Path, output: Path):
    source, cache, output = source.resolve(strict=True), cache.resolve(strict=True), output.resolve()
    if output.exists() or any(output == root or output.is_relative_to(root) or root.is_relative_to(output) for root in (source, cache)):
        raise ValueError("fresh isolated supplement destination required")
    lock = tomllib.loads((source / "Cargo.lock").read_text(encoding="utf-8"))["package"]
    published = cache / "published-crates"
    origins = materializer.load_json(published / "origins.json")
    if {(r["name"], r["version"]) for r in origins} != PACKAGES:
        raise ValueError("published package origin set differs")
    registry_origin = materializer.load_json(published / "scrap-registry-origin.json")
    registry_path = published / "scrap-0.5.0.registry.json"
    if (registry_origin["url"] != "https://crates.io/api/v1/crates/scrap/0.5.0"
            or materializer.build.sha(registry_path) != registry_origin["sha256"]):
        raise ValueError("scrap registry metadata differs from its origin pin")
    scrap = materializer.load_json(registry_path)["version"]
    template_origin = materializer.load_json(cache / "mit-template-origin.json")
    revision, response = template_origin["revision"], template_origin["response"]
    if not re.fullmatch("[0-9a-f]{40}", revision) or response["url"] != "https://raw.githubusercontent.com/spdx/license-list-data/" + revision + "/json/details/MIT.json":
        raise ValueError("official SPDX template must be commit-bound")
    template_file = cache / (hashlib.sha256(response["url"].encode()).hexdigest() + ".body")
    if materializer.build.sha(template_file) != response["sha256"]:
        raise ValueError("SPDX template content changed")
    template = materializer.load_json(template_file)
    if template["licenseId"] != "MIT" or "<year>" not in template["licenseText"] or "<copyright holders>" not in template["licenseText"]:
        raise ValueError("MIT canonical template was substituted or filled in")
    output.mkdir(parents=True)
    records = []
    for origin in origins:
        name, version = origin["name"], origin["version"]
        if origin["url"] != "https://static.crates.io/crates/" + name + "/" + name + "-" + version + ".crate":
            raise ValueError("published package origin is not version-bound")
        path = published / (name + "-" + version + ".crate")
        checksum = next((row["checksum"] for row in lock if row["name"] == name and row["version"] == version and row.get("source", "").startswith("registry+")), None)
        if name == "scrap":
            checksum = scrap["checksum"]
        if not checksum or checksum != origin["sha256"]:
            raise ValueError("published archive lacks an independent source checksum")
        record = inspect_crate(path, name, version, checksum)
        record.update(origin_url=origin["url"], checksum_authority="crates.io version metadata" if name == "scrap" else "compiled checkout Cargo.lock")
        shutil.copy2(path, output / path.name)
        records.append(record)
    shutil.copy2(registry_path, output / registry_path.name)
    shutil.copy2(template_file, output / "SPDX-MIT-details.json")
    (output / "SPDX-MIT-canonical-template.txt").write_text(template["licenseText"], encoding="utf-8", newline="\n")
    report = {"schema_version": 1, "published_packages": records, "spdx_template_origin": template_origin,
        "scrap_registry_origin": registry_origin,
        "finding": "All three publishers explicitly declare MIT; no standalone notice filename exists in these exact published archives. Absence of such a file is not an automatic license violation.",
        "template_is_not_a_project_copyright_notice": True, "local_scrap_fork_byte_equivalence_claimed": False,
        "copyright_fields_filled_in": False, "legal_release_ready": False, "frozen_components_modified": False,
        "scope": "Publisher-source and notice-collection evidence. No rights-holder statement for the separate unlicensed RustDesk repositories is supplied."}
    materializer.write_json(output / "report.json", report)
    return {"supplement": str(output), "packages": len(records), "source_files": sum(len(r["files"]) for r in records),
            "standalone_notices": sum(len(r["standalone_notice_filenames"]) for r in records),
            "report_sha256": materializer.build.sha(output / "report.json"), "legal_release_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "cache", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    print(json.dumps(supplement(**vars(parser.parse_args())), sort_keys=True))


if __name__ == "__main__":
    main()
