from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_web_models_release_is_fail_closed_on_stale_or_incomplete_payload() -> None:
    builder = (ROOT / "scripts" / "commander" / "build_windows.py").read_text(encoding="utf-8")
    release = (ROOT / "scripts" / "commander" / "release_assets.py").read_text(encoding="utf-8")
    installer = (ROOT / "sentra_remote" / "installer.py").read_text(encoding="utf-8")
    msi = (ROOT / "scripts" / "commander" / "build_msi.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release-commander.yml").read_text(encoding="utf-8")
    integration = (ROOT / "scripts" / "integrations" / "Build-CodexChatGPTWebRuntime.ps1").read_text(encoding="utf-8")

    assert "integration-build.json" in integration
    assert "patch_sha256" in integration
    assert "function Test-GitPatchApply" in integration
    assert '$ErrorActionPreference = "SilentlyContinue"' in integration
    assert "$CurrentPatchAlreadyApplied = Test-GitPatchApply" in integration
    assert "if (-not (Test-GitPatchApply -Worktree $Source -PatchPath $Patch))" in integration
    assert "stale SENTRA upstream patch" in builder
    assert "stale SENTRA upstream patch" in release
    assert '"name": str(upstream_manifest["name"])' in release
    assert '"licenses": [{"license": {"id": str(upstream_manifest["license"])}}]' in release
    assert "sentra:upstream_commit" in release
    assert "integration build metadata is missing" in installer
    assert "integration metadata" in msi
    assert "web-models\\integration-build.json" in workflow
    assert "web-models\\licenses\\codex-chatgpt-web\\LICENSE" in workflow
