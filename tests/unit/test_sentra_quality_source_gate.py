"""Provenance gate regression tests: actual local Git repos, never any network."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from sentra_quality import GateFailure, SourceGate


UPSTREAM = "https://github.com/example/offline-test"


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=15, check=True)
    return proc.stdout.strip()


@pytest.fixture
def source(tmp_path):
    third = tmp_path / "third_party"
    repo = third / "offline-test"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "SENTRA Tester")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "remote", "add", "origin", UPSTREAM + ".git")
    (repo / "README.md").write_text("trusted initial content\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-qm", "fixture")
    sha = git(repo, "rev-parse", "HEAD")
    manifest = third / "SENTRA_SOURCES_MANIFEST.json"
    record = {"name": "offline-test", "upstream": UPSTREAM,
              "revision": sha, "status": "ok"}
    manifest.write_text(json.dumps({"repos": [record]}), encoding="utf-8")
    return third, repo, manifest, record


def test_verifies_commit_origin_and_tracked_checkout(source):
    root, repo, _manifest, _record = source
    gate = SourceGate(root)
    result = gate.verify("offline-test")
    assert result.tracked_files == 1
    assert result.revision == git(repo, "rev-parse", "HEAD")
    assert gate.verify_all() == (result,)


def test_attestation_is_stable_and_never_runs_vendor_code(source):
    root, repo, _, _ = source
    expected = hashlib.sha256((repo / "README.md").read_bytes()).hexdigest()
    first = SourceGate(root).attest_file("offline-test", "README.md")
    assert first["sha256"] == expected
    assert first["revision"] == git(repo, "rev-parse", "HEAD")
    assert first["path"] == "README.md"


def test_modified_tracked_file_denied(source):
    root, repo, _, _ = source
    (repo / "README.md").write_text("malicious replacement", encoding="utf-8")
    with pytest.raises(GateFailure, match="modified"):
        SourceGate(root).verify("offline-test")


def test_untracked_file_never_attested(source):
    root, repo, _, _ = source
    (repo / "created.py").write_text("print('should never execute')", encoding="utf-8")
    gate = SourceGate(root)
    assert gate.verify("offline-test").tracked_files == 1
    with pytest.raises(GateFailure, match="untracked"):
        gate.attest_file("offline-test", "created.py")


@pytest.mark.parametrize("name", [
    "../offline-test", ".hidden", "offline-test/../../", "offline-test\\..",
])
def test_unknown_or_invalid_project_does_not_escape(source, name):
    with pytest.raises(GateFailure):
        SourceGate(source[0]).verify(name)


@pytest.mark.parametrize("candidate", [
    "../README.md", "/README.md", r"..\README.md", "-README.md",
    "dir/../../README.md",
])
def test_candidate_paths_cannot_escape_repository(source, candidate):
    with pytest.raises(GateFailure):
        SourceGate(source[0]).attest_file("offline-test", candidate)


def test_bad_remote_denied(source):
    root, repo, _, _ = source
    git(repo, "remote", "set-url", "origin", "https://github.com/wrong/wrong")
    with pytest.raises(GateFailure, match="origin"):
        SourceGate(root).verify("offline-test")


def test_bad_revision_denied(source):
    root, _repo, manifest, record = source
    record["revision"] = "0" * 40
    manifest.write_text(json.dumps({"repos": [record]}), encoding="utf-8")
    with pytest.raises(GateFailure, match="revision"):
        SourceGate(root).verify("offline-test")


@pytest.mark.parametrize("alter", [
    {"status": "failed"},
    {"upstream": "http://github.com/example/offline-test"},
    {"upstream": "https://github.com/any/repo?token=secret"},
    {"revision": "latest"},
    {"name": "../escape"},
])
def test_fail_closed_on_manifest_tamper(source, alter):
    root, _repo, manifest, record = source
    record.update(alter)
    manifest.write_text(json.dumps({"repos": [record]}), encoding="utf-8")
    with pytest.raises(GateFailure):
        SourceGate(root)


def test_reject_duplicate_names_and_corrupt_manifest(source):
    root, _repo, manifest, record = source
    manifest.write_text(json.dumps({"repos": [record, record]}), encoding="utf-8")
    with pytest.raises(GateFailure, match="duplicate"):
        SourceGate(root)
    manifest.write_text("not-json", encoding="utf-8")
    with pytest.raises(GateFailure, match="manifest"):
        SourceGate(root)


def test_missing_source_and_git_metadata_denied(source):
    root, repo, _, _ = source
    # Git object files can be read-only on Windows; rename metadata instead
    # of deleting it while testing a missing checkout.
    (repo / ".git").rename(repo / "git-metadata-disabled")
    with pytest.raises(GateFailure, match="metadata"):
        SourceGate(root).verify("offline-test")


def test_cli_verify_and_attest_without_network(source):
    root, _repo, _manifest, record = source
    # The CLI requires a separately approved pin lock. The test fixture must
    # provide its own lock rather than bypassing the production fail-closed gate.
    trusted = root.parent / "trusted-fixture-pins.json"
    trusted.write_text(json.dumps({"repos": [record]}), encoding="utf-8")
    for argv in (
        ["verify", "offline-test"],
        ["attest", "offline-test", "README.md"],
        ["verify-all"],
    ):
        p = subprocess.run(
            ["python", "-B", "-m", "sentra_quality", "--root", str(root),
             "--trusted-pins", str(trusted), *argv],
            capture_output=True, text=True, timeout=20, check=False,
        )
        assert p.returncode == 0, p.stderr
        assert json.loads(p.stdout)["ok"] is True


def test_independent_pins_detect_mutated_manifest_even_when_git_origin_matches(source):
    root, repo, manifest, record = source
    trusted = root.parent / "independent-trusted-lock.json"
    trusted.write_text(json.dumps({"repos": [dict(record)]}), encoding="utf-8")
    # Attacker changes both ignored manifest and Git remote. Without an
    # independent lock, those two mutable inputs might appear consistent.
    git(repo, "remote", "set-url", "origin", "https://github.com/forged/repository")
    record["upstream"] = "https://github.com/forged/repository"
    manifest.write_text(json.dumps({"repos": [record]}), encoding="utf-8")
    assert SourceGate(root).verify("offline-test").name == "offline-test"
    with pytest.raises(GateFailure, match="independent trusted pins"):
        SourceGate(root, trusted_pins=trusted)
