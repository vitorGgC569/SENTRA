"""Read actual Cargo native-link directives and post-build archive hashes.

This is not retrospective proof that an unrecorded supplier input was unchanged
at compilation time. It neither rebuilds binaries nor approves distribution.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.commander import materialize_rustdesk as materializer

PORTS = {"avcodec": "ffmpeg", "avformat": "ffmpeg", "avutil": "ffmpeg", "libmfx": "mfx-dispatch",
         "opus": "opus", "aom": "aom", "vpx": "libvpx", "yuv": "libyuv"}


def inspect(source: Path, proofs: Path, toolchains: Path, artifact: Path):
    import pefile
    source, proofs, toolchains, artifact = (p.resolve(strict=True) for p in (source, proofs, toolchains, artifact))
    native = materializer.load_json(proofs / "native-proof.json")
    for name, digest in native["outputs"].items():
        if materializer.build.sha(materializer.owned_file(source, name)) != digest:
            raise ValueError("native outputs differ from build proof")
    log = materializer.owned_file(artifact, "provenance/cargo-build-graph.jsonl")
    if materializer.build.sha(log) != materializer.build.sha(proofs / "profile-cargo.log"):
        raise ValueError("archive and current Cargo graphs differ")
    scripts = []
    cargo_cache = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo"))).resolve(strict=True)
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("reason") != "build-script-executed" or not message.get("linked_libs"):
            continue
        directories = []
        for entry in message.get("linked_paths", []):
            candidate = entry.split("=", 1)[1] if entry.startswith(("native=", "all=", "dependency=")) else entry
            path = Path(candidate).resolve(strict=True)
            if not any(path.is_relative_to(root) for root in (source, toolchains, cargo_cache)):
                raise ValueError("Cargo link search escaped the selected build roots")
            if path not in directories:
                directories.append(path)
        links = []
        for entry in message["linked_libs"]:
            kind, name = entry.split("=", 1) if "=" in entry else ("unspecified", entry)
            row = {"directive": entry, "kind": kind, "name": name}
            if kind.split(":", 1)[0] == "static":
                matches = sorted({(root / relative).resolve(strict=True) for root in directories
                    for relative in (name + ".lib", "lib" + name + ".a", name + ".a") if (root / relative).is_file()})
                row["archives"] = [{"path": str(path), "sha256": materializer.build.sha(path), "bytes": path.stat().st_size} for path in matches]
                # cc-rs emits byte-identical .a and .lib aliases on MSVC.
                # Two filenames do not imply two different supplier inputs.
                digests = {item["sha256"] for item in row["archives"]}
                row["uniquely_resolved"] = len(digests) == 1
                row["resolution_basis"] = "unique archive content hash; identical .a/.lib aliases retained"
                row["supplier"] = PORTS.get(name, message["package_id"])
            links.append(row)
        scripts.append({"package_id": message["package_id"], "out_dir": message["out_dir"], "links": links})
    manifest = materializer.load_json(artifact / "manifest.json")
    imports = {}
    for name, digest in manifest["bundle_sha256"].items():
        if not name.lower().endswith((".exe", ".dll")):
            continue
        path = materializer.owned_file(artifact, name)
        if materializer.build.sha(path) != digest:
            raise ValueError("bundle binary changed")
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        imports[name] = sorted({entry.dll.decode("ascii") for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])})
        pe.close()
    ffmpeg_config = toolchains / "vcpkg-9e593bb/buildtrees/ffmpeg/x64-windows-static-rel/config.h"
    flags = {name: int(value) for name, value in re.findall(r"^#define CONFIG_(GPL|VERSION3|NONFREE) ([01])$",
        ffmpeg_config.read_text(encoding="utf-8"), flags=re.M)}
    for name, digest in native["outputs"].items():
        if materializer.build.sha(source / name) != digest:
            raise ValueError("native outputs changed during read-only link audit")
    static = [link for script in scripts for link in script["links"] if link["kind"].split(":", 1)[0] == "static"]
    return {"schema_version": 1, "native_library_sha256": native["outputs"]["target/release/librustdesk.dll"],
        "cargo_graph_sha256": materializer.build.sha(log), "build_scripts_with_native_links": scripts,
        "static_directives": len(static), "static_directives_uniquely_resolved": sum(x["uniquely_resolved"] for x in static),
        "pe_dynamic_imports": imports, "ffmpeg": {"config_sha256": materializer.build.sha(ffmpeg_config), "flags": flags,
            "license_context": "GPL-enabled static FFmpeg; do not describe this tuple as an LGPL-only DLL distribution."},
        "archives_measured_after_build": True, "retrospective_supplier_build_attestation": False,
        "scope": "Observed Cargo build-script native directives and PE import tables; not an exhaustive per-symbol contribution proof.",
        "legal_release_ready": False, "binaries_rebuilt": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "proofs", "toolchains", "artifact", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = vars(parser.parse_args())
    report_path = args.pop("report")
    report = inspect(**args)
    materializer.write_json(report_path, report)
    print(json.dumps({key: report[key] for key in ("static_directives", "static_directives_uniquely_resolved", "ffmpeg", "binaries_rebuilt", "legal_release_ready")}, sort_keys=True))


if __name__ == "__main__":
    main()
