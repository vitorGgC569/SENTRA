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
    assert "apply --check --unidiff-zero" in integration
    assert "apply --reverse --check --unidiff-zero" in integration
    assert "git -c core.autocrlf=false -c core.whitespace=cr-at-eol -C $Source diff --check" in integration
    assert "add --intent-to-add -- @NewFiles" in integration
    assert "ls-files --others --exclude-standard" in integration
    assert "Copy-Item -Force -LiteralPath $Patch -Destination $Applied" in integration
    assert 'tests/gemini-web.test.ts' in integration
    assert 'tests/gemini-web-adapter.test.ts' in integration
    assert "Patched Gemini Web integration tests failed" in integration
    # Build output is transactional: never clean/package directly over the live
    # Web Models tree used by a running launcher.
    assert '$FinalOutput' in integration
    assert '".staging-"' in integration
    assert '$BackupOutput' in integration
    assert "Transactional Web Models publish failed" in integration
    assert "Staged Web Models payload is incomplete" in integration
    assert 'electron = $FinalExecutable' in integration
    assert "Move-Item -LiteralPath $Output -Destination $FinalOutput" in integration
    assert "Move-Item -LiteralPath $BackupOutput -Destination $FinalOutput" in integration
    assert "Get-LiveWebModelsProcesses" in integration
    assert "Invoke-SentraWebRuntimeControl -Action Stop" in integration
    assert "Invoke-SentraWebRuntimeControl -Action Start" in integration
    assert "active_http_turns" in integration
    assert "active_browser_turns" in integration
    assert "Refusing live Web Models publish while turns are active" in integration
    assert "SENTRA does not exclusively own" in integration
    assert "stale SENTRA upstream patch" in builder
    assert "def build_web_models(dist: Path)" in builder
    assert '"Build-CodexChatGPTWebRuntime.ps1"' in builder
    assert '"-Dist", str(dist)' in builder
    assert "build_web_models(dist)" in builder
    assert "stale SENTRA upstream patch" in release
    assert '"name": str(upstream_manifest["name"])' in release
    assert '"licenses": [{"license": {"id": str(upstream_manifest["license"])}}]' in release
    assert "sentra:upstream_commit" in release
    assert "integration build metadata is missing" in installer
    assert "integration metadata" in msi
    assert "web-models\\integration-build.json" in workflow
    assert "web-models\\licenses\\codex-chatgpt-web\\LICENSE" in workflow


def test_web_models_version_is_manifest_driven() -> None:
    manifest = __import__("json").loads(
        (ROOT / "integrations" / "codex_chatgpt_web" / "upstream.json").read_text(encoding="utf-8")
    )
    version = str(manifest["ref"]).removeprefix("v")
    integration = (ROOT / "scripts" / "integrations" / "Build-CodexChatGPTWebRuntime.ps1").read_text(encoding="utf-8")
    gateway = (ROOT / "sentra_model_gateway" / "gateway.py").read_text(encoding="utf-8")
    assert '$UpstreamVersion = $Matches.version' in integration
    assert 'source\\6.0.0' not in integration
    assert 'runtime\\6.0.0' not in integration
    assert 'EXPECTED_UPSTREAM_VERSION = "6.0.0"' not in gateway
    assert '/ "source"\n            / self.expected_upstream_version()' in gateway
    assert version
