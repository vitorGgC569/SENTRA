"""Regression checks for SENTRA CI/CD policy and its failure gates."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ci_contract", ROOT / "scripts/ci/verify_release_contract.py")
assert spec is not None and spec.loader is not None
ci_contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_contract)


def test_current_release_contract_is_consistent_without_requiring_commit():
    ci_contract.verify(tracked=False, upstream=False)


def test_unhashed_dependency_is_rejected(tmp_path):
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text("pytest==8.0.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unhashed"):
        ci_contract.check_lock(lock)


def test_duplicate_dependency_is_rejected(tmp_path):
    good = "pytest==8.0.0 --hash=sha256:" + "a" * 64 + "\n"
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text(good + good, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        ci_contract.check_lock(lock)


def test_release_and_ci_workflows_parse_as_yaml():
    for name in ("ci.yml", "release-commander.yml", "release-mcp-registry.yml"):
        data = yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))
        assert "jobs" in data
        assert isinstance(data["jobs"], dict)


def test_ci_lanes_gate_windows_canvas_and_web_models():
    data = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert data["permissions"] == {"contents": "read"}
    jobs = data["jobs"]
    assert {"contract", "python", "canvas", "web-models", "ci-required"} <= set(jobs)
    assert jobs["python"]["strategy"]["matrix"]["target"] == [
        "tests/unit", "tests/failure", "tests/integration",
    ]
    assert jobs["ci-required"]["needs"] == ["contract", "python", "canvas", "web-models"]
    assert jobs["canvas"]["runs-on"] == "windows-latest"
    assert jobs["web-models"]["runs-on"] == "windows-latest"
    assert "success" in jobs["ci-required"]["steps"][0]["run"]


def test_release_publishing_uses_separate_minimal_token():
    data = yaml.safe_load((ROOT / ".github/workflows/release-commander.yml").read_text(encoding="utf-8"))
    assert data["permissions"] == {"contents": "read"}
    jobs = data["jobs"]
    assert jobs["publish-release"]["needs"] == "windows-release"
    assert jobs["publish-release"]["permissions"] == {"contents": "write", "actions": "read"}
    assert "permissions" not in jobs["windows-release"]
    build = str(jobs["windows-release"]["steps"])
    assert "sentra-canvas.exe" in build
    assert "test_canvas.ps1" in build


def test_pinned_bun_and_untrusted_pr_permissions():
    install = (ROOT / "scripts/ci/install_bun.ps1").read_text(encoding="utf-8")
    lint = (ROOT / "scripts/ci/install_actionlint.ps1").read_text(encoding="utf-8")
    assert "Get-FileHash" in lint and "433028cf0ba3c42163ea1a668dedce30fcdbe84fe912b1a5e288c006eab8a4f5" in lint
    assert "bun-v1.4.0" in install
    assert "Get-FileHash" in install
    assert "e6f093d39da486b20262ca8cdd5ed6a9e8bc9c2f275b78e6d3a0c5b28cc95901" in install
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pull_request_target:" not in ci
    assert "persist-credentials: false" in ci


def test_upstream_patch_paths_are_consistent():
    ci_contract.check_patch(ROOT, upstream=False)
