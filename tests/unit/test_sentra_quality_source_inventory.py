"""Pinned source inventory tests; all Git fixtures are local and offline."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from sentra_quality.source_gate import GateFailure, SourceGate
from sentra_quality.source_inventory import generate_source_inventory


def _git(repo: Path, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        check=True, timeout=10,
    ).stdout.strip()


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / "third_party"
    repo = root / "fixture-repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "remote", "add", "origin", "https://github.com/example/fixture-repo.git")
    (repo / "LICENSE").write_text("Fixture testing only\n", encoding="utf-8")
    (repo / "README.md").write_text("No code execution\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    pin = {
        "name": "fixture-repo", "upstream": "https://github.com/example/fixture-repo",
        "revision": _git(repo, "rev-parse", "HEAD"), "status": "ok",
    }
    (root / "SENTRA_SOURCES_MANIFEST.json").write_text(
        json.dumps({"repos": [pin]}), encoding="utf-8",
    )
    return root, repo


def test_inventory_is_deterministic_offline_and_license_is_only_evidence(sources):
    root, _ = sources
    gate = SourceGate(root)
    one = generate_source_inventory(gate)
    two = generate_source_inventory(SourceGate(root))
    assert one == two
    assert one["count"] == 1
    assert one["verified_git_revisions"]
    assert one["sbom_complete"] is False
    assert one["cve_scanned"] is False
    assert one["license_cleared"] is False
    assert one["packages"][0]["license_files"][0]["path"] == "LICENSE"
    assert one["packages"][0]["release_license_review"] == "REQUIRED"
    assert len(one["inventory_sha256"]) == 64
    assert generate_source_inventory(gate, require_license=True) == one


def test_dirty_tracked_license_blocks_entire_inventory(sources):
    root, repo = sources
    (repo / "LICENSE").write_text("another text", encoding="utf-8")
    with pytest.raises(GateFailure, match="modified"):
        generate_source_inventory(SourceGate(root))


def test_absence_of_root_license_is_reported_not_faked(sources):
    root, repo = sources
    (repo / "LICENSE").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "license absent")
    manifest = root / "SENTRA_SOURCES_MANIFEST.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["repos"][0]["revision"] = _git(repo, "rev-parse", "HEAD")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    gate = SourceGate(root)
    result = generate_source_inventory(gate)
    assert result["packages"][0]["license_files"] == []
    assert result["packages"][0]["release_license_review"] == "MISSING_EVIDENCE"
    with pytest.raises(GateFailure, match="manual license review"):
        generate_source_inventory(gate, require_license=True)


def test_untracked_fake_license_never_counts_as_evidence(sources):
    root, repo = sources
    (repo / "NOTICE").write_text("untracked text", encoding="utf-8")
    report = generate_source_inventory(SourceGate(root))
    assert [p["path"] for p in report["packages"][0]["license_files"]] == ["LICENSE"]


def test_manifest_tamper_denied_without_scanning_clone(sources):
    root, repo = sources
    m = root / "SENTRA_SOURCES_MANIFEST.json"
    data = json.loads(m.read_text(encoding="utf-8"))
    data["repos"][0]["revision"] = "f" * 40
    m.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(GateFailure, match="revision"):
        generate_source_inventory(SourceGate(root))


def test_cli_inventory_with_independent_pin_lock(sources, tmp_path):
    root, repo = sources
    pin = json.loads((root / "SENTRA_SOURCES_MANIFEST.json").read_text())
    pinlock = tmp_path / "pins.json"
    pinlock.write_text(json.dumps(pin), encoding="utf-8")
    result = subprocess.run([
        sys.executable, "-B", "-m", "sentra_quality",
        "--root", str(root), "--trusted-pins", str(pinlock), "inventory",
    ], capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["inventory"]["count"] == 1
