"""Tamper/source-archive tests use explicit fixtures, never native-build claims."""
import gzip
import hashlib
import json
from pathlib import Path
import tarfile

import pytest

from scripts.commander import materialize_rustdesk as materializer


@pytest.fixture
def proof_fixture(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir()
    proofs = tmp_path / "proofs"; proofs.mkdir()
    generated = materializer.build.GENERATED
    native_names = ("target/release/librustdesk.dll", "target/release/deps/dylib_virtual_display.dll", "src/version.rs")
    bundle_names = tuple(materializer.BUNDLE + name for name in ("rustdesk.exe", "librustdesk.dll", "dylib_virtual_display.dll"))
    for name in (*generated, *native_names, *bundle_names, "target/release/sentra-profile-probe.exe"):
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"uncompiled-test-fixture")
    inputs = {"fixture-source": "0" * 64}
    snapshot = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    native = {"source_revision": "fixture", "native_sources": {"fixture": "0" * 64}}
    monkeypatch.setattr(materializer.build, "validate_native_sources", lambda _: native)
    monkeypatch.setattr(materializer.build, "source_inputs", lambda _: inputs)
    phases = {"codegen": generated, "native": native_names, "flutter": bundle_names,
              "profile-test": ("target/release/sentra-profile-probe.exe",)}
    for phase, names in phases.items():
        value = {"phase": phase, "source": str(source), **native, "inputs": inputs,
                 "input_snapshot_sha256": {"before": snapshot, "after": snapshot},
                 "tooling_inputs": {"test-fixture": "0" * 64},
                 "outputs": {name: materializer.build.sha(source / name) for name in names}}
        if phase == "profile-test":
            value["verification"] = {"native_profile_isolation": True}
            value["profile_results"] = {"runs": [
                {"negative": False, "scope": "a", "returncode": 0, "stdout": "profile-config-log-ipc-isolated"},
                {"negative": False, "scope": "b", "returncode": 0, "stdout": "profile-config-log-ipc-isolated"},
                {"negative": True, "returncode": 1, "stderr": "SENTRA config path must stay relative to its owned profile"}]}
        materializer.write_json(proofs / (phase + "-proof.json"), value)
    return source, proofs


def test_exact_bundle_source_and_output_hashes_are_required(proof_fixture):
    source, proofs = proof_fixture
    materializer.verify_proofs(source, proofs)
    (source / materializer.BUNDLE / "extra.dll").write_bytes(b"unproved")
    with pytest.raises(ValueError, match="unproved extra"):
        materializer.verify_proofs(source, proofs)
    (source / materializer.BUNDLE / "extra.dll").unlink()
    (source / materializer.BUNDLE / "librustdesk.dll").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="output mismatch"):
        materializer.verify_proofs(source, proofs)


def test_legacy_proof_without_builder_hashes_is_refused(proof_fixture):
    source, proofs = proof_fixture
    path = proofs / "codegen-proof.json"
    value = json.loads(path.read_text()); value.pop("tooling_inputs")
    materializer.write_json(path, value)
    with pytest.raises(ValueError, match="builder hashes"):
        materializer.verify_proofs(source, proofs)


def test_profile_probe_crash_without_actual_guard_is_not_evidence(proof_fixture):
    source, proofs = proof_fixture
    path = proofs / "profile-test-proof.json"
    value = json.loads(path.read_text()); value["profile_results"]["runs"][-1]["stderr"] = "missing DLL"
    materializer.write_json(path, value)
    with pytest.raises(ValueError, match="profile isolation evidence"):
        materializer.verify_proofs(source, proofs)


@pytest.mark.parametrize("name", ["../private", "/absolute", "C:/drive", "a\\b", "a//b", "./a"])
def test_portable_paths_cannot_escape_materialization(name):
    with pytest.raises(ValueError, match="portable"):
        materializer.portable(name)


def test_source_archive_contains_only_selected_bytes_and_verifiable_hashes(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    (source / "main.rs").write_text("// actual fixture source\n", encoding="utf-8")
    (source / "private.env").write_text("never selected", encoding="utf-8")
    archive = materializer.Archive(tmp_path / "sources.tar.gz")
    try:
        archive.add(source, "main.rs", "rustdesk")
        with pytest.raises(ValueError, match="duplicate"):
            archive.add(source, "main.rs", "rustdesk")
    finally:
        archive.close()
    with tarfile.open(tmp_path / "sources.tar.gz", "r:gz") as stream:
        assert stream.getnames() == ["rustdesk/main.rs"]
        data = stream.extractfile("rustdesk/main.rs").read()
    assert hashlib.sha256(data).hexdigest() == archive.entries[0]["sha256"]
    assert b"private.env" not in gzip.decompress((tmp_path / "sources.tar.gz").read_bytes())


def test_output_inside_source_is_refused_without_writing(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    proofs = tmp_path / "proofs"; proofs.mkdir()
    tools = tmp_path / "tools"; tools.mkdir()
    output = source / "artifact"
    with pytest.raises(ValueError, match="separate"):
        materializer.materialize(source, proofs, tools, output)
    assert not output.exists()


def test_compact_gate_omits_large_legal_inventory_and_keeps_source_pins():
    manifest = {"executable": "rustdesk.exe", "executable_sha256": "0" * 64,
        "compiled": True, "control_extension": "sentra-desktop-control-v1", "extension": "sentra-peer-gate-v1",
        "stock_cli_supported": False, "bundle_sha256": {"rustdesk.exe": "0" * 64},
        "upstream": {"revision": "1" * 40}, "files": [{"path": "license" + str(i)} for i in range(2000)]}
    gate = materializer.compact_gate(manifest)
    assert "files" not in gate
    assert gate["source_revision"] == "1" * 40
    assert gate["bundle_sha256"] == manifest["bundle_sha256"]
    assert gate["validated"] is False and gate["homologated"] is False
    manifest["bundle_sha256"] = {"x" * 300 + str(i): "0" * 64 for i in range(300)}
    with pytest.raises(ValueError, match="64 KiB"):
        materializer.compact_gate(manifest)


def test_gate_metadata_transform_preserves_prior_proof_and_is_idempotent(tmp_path, monkeypatch):
    # This is metadata-only synthetic input. The actual candidate's PE/export
    # and tar bytes are verified separately by the dedicated QA command.
    artifact = tmp_path / "artifact"; artifact.mkdir()
    (artifact / "provenance").mkdir(); (artifact / "corresponding-source").mkdir()
    (artifact / "rustdesk.exe").write_bytes(b"uncompiled unit fixture")
    materializer.write_json(artifact / "sbom.cdx.json", {"components": []})
    materializer.write_json(artifact / "dependency-inventory.json", [])
    materializer.write_json(artifact / "legal-review.json", {"review_required": []})
    digest = materializer.build.sha(artifact / "rustdesk.exe")
    manifest = {"executable": "rustdesk.exe", "executable_sha256": digest,
        "compiled": True, "control_extension": "sentra-desktop-control-v1", "extension": "sentra-peer-gate-v1",
        "stock_cli_supported": False, "bundle_sha256": {"rustdesk.exe": digest}, "upstream": {"revision": "1" * 40},
        "files": [{"path": p.name, "sha256": materializer.build.sha(p)} for p in artifact.iterdir() if p.is_file()]}
    materializer.write_json(artifact / "manifest.json", manifest)
    previous = materializer.build.sha(artifact / "manifest.json")
    monkeypatch.setattr(materializer, "_native_payload", lambda *_: None)
    first = materializer.finalize_runtime_manifest(artifact)
    assert first["build_manifest_bytes"] < 65536
    updated = materializer.load_json(artifact / "manifest.json")
    assert updated["bundle_manifest"] == "bundle-manifest.json"
    assert materializer.build.sha(artifact / "provenance/manifest-before-runtime-gate.json") == previous
    assert updated["bundle_manifest_sha256"] == materializer.build.sha(artifact / "bundle-manifest.json")
    assert materializer.finalize_runtime_manifest(artifact)["manifest_sha256"] == first["manifest_sha256"]
    (artifact / "rustdesk.exe").write_bytes(b"changed after finalization")
    with pytest.raises(ValueError, match="changed before runtime gate"):
        materializer.finalize_runtime_manifest(artifact)
