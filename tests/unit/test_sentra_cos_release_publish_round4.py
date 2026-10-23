"""Stable release refuses absent, fabricated, stale, or mismatched VM QA."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.commander.release_publish_gate import REQUIRED_PROOFS, check_publication
from scripts.commander.isolated_vm_smoke import preflight
from scripts.commander.msi_media import msi_manifest_entry


def _fixtures(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "release"
    root.mkdir()
    setup = root / "SENTRA-Setup-1.2.3.exe"
    setup.write_bytes(b"synthetic-not-signed")
    msi = root / "SENTRA-Desktop-1.2.3-x64.msi"
    msi.write_bytes(b"synthetic-not-signed-msi")
    cabinet = root / (msi.stem + "-0001.cab")
    cabinet.write_bytes(b"MSCF" + b"synthetic-cab-fixture" * 4)
    inventory = msi.with_suffix(".media.json")
    inventory.write_text(json.dumps({"schema": 1, "msi": msi.name,
        "sha256": hashlib.sha256(msi.read_bytes()).hexdigest(),
        "media": [{"name": cabinet.name, "bytes": cabinet.stat().st_size,
                   "sha256": hashlib.sha256(cabinet.read_bytes()).hexdigest(), "last_sequence": 1}]}))
    (root / "release-manifest.json").write_text(json.dumps({
        "version": "1.2.3", "setup": setup.name,
        "msi_media": msi_manifest_entry(msi),
    }))
    evidence = tmp_path / "external-evidence.json"
    data = {"schema": 1, "version": "1.2.3",
            "setup_sha256": hashlib.sha256(setup.read_bytes()).hexdigest(),
            "msi_sha256": hashlib.sha256(msi.read_bytes()).hexdigest(),
            "msi_media_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
            **{key: True for key in REQUIRED_PROOFS}}
    evidence.write_text(json.dumps(data))
    return root, evidence


def test_publication_denied_without_independent_qa_hash(tmp_path):
    root, evidence = _fixtures(tmp_path)
    with pytest.raises(PermissionError, match="independently"):
        check_publication(root, evidence, expected_sha256="", version="1.2.3")


def test_publication_denied_for_qa_hash_mismatch(tmp_path):
    root, evidence = _fixtures(tmp_path)
    with pytest.raises(PermissionError, match="digest mismatch"):
        check_publication(root, evidence, expected_sha256="0" * 64, version="1.2.3")


def test_publication_denied_when_any_required_vm_proof_missing(tmp_path):
    root, evidence = _fixtures(tmp_path)
    data = json.loads(evidence.read_text())
    data["native_canvas_window_verified"] = False
    evidence.write_text(json.dumps(data))
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with pytest.raises(PermissionError, match="incomplete"):
        check_publication(root, evidence, expected_sha256=digest, version="1.2.3")


def test_publication_denied_if_setup_hash_changed(tmp_path):
    root, evidence = _fixtures(tmp_path)
    (root / "SENTRA-Setup-1.2.3.exe").write_bytes(b"new-untested-setup")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with pytest.raises(PermissionError, match="different Setup"):
        check_publication(root, evidence, expected_sha256=digest, version="1.2.3")


def test_publication_structural_contract_only(tmp_path):
    root, evidence = _fixtures(tmp_path)
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    result = check_publication(root, evidence, expected_sha256=digest, version="1.2.3")
    assert result["release_gate"] == "pass"
    # Fixture proves only contract evaluation; the evidence itself is synthetic.
    assert result["independent_review"] is True


def test_publication_denied_if_required_cab_is_missing(tmp_path):
    root, evidence = _fixtures(tmp_path)
    next(root.glob("*.cab")).unlink()
    with pytest.raises(ValueError, match="cabinet missing"):
        check_publication(root, evidence, expected_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(), version="1.2.3")


def test_publication_denied_for_qa_bound_to_other_cab_inventory(tmp_path):
    root, evidence = _fixtures(tmp_path)
    data = json.loads(evidence.read_text())
    data["msi_media_sha256"] = "0" * 64
    evidence.write_text(json.dumps(data))
    with pytest.raises(PermissionError, match="different MSI external cabinet"):
        check_publication(root, evidence, expected_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(), version="1.2.3")


def test_disposable_vm_smoke_is_disabled_by_default_and_without_signature():
    with pytest.raises(PermissionError, match="DRY RUN"):
        preflight(execute=False, acknowledged=True, trusted_signer="A" * 40)
    with pytest.raises(PermissionError, match="independently trusted"):
        preflight(execute=True, acknowledged=True, trusted_signer="")
