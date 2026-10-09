"""Offline, fail-closed CI/CD source and packaging contract checks."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = (
    ".github/workflows/ci.yml", ".github/workflows/release-commander.yml",
    ".github/workflows/release-mcp-registry.yml",
    "scripts/ci/verify_release_contract.py", "scripts/ci/install_bun.ps1",
    "scripts/ci/install_actionlint.ps1",
    "scripts/ci/test_web_models.ps1", "scripts/ci/test_canvas.ps1",
    "scripts/commander/build_windows.py", "scripts/commander/build_canvas.py",
    "scripts/commander/release_assets.py",
    "scripts/integrations/Build-CodexChatGPTWebRuntime.ps1",
    "scripts/integrations/Bootstrap-CodexChatGPTWeb.ps1",
    "sentra_canvas/__main__.py", "sentra_canvas/native_entry.py",
    "sentra_canvas/graph.py", "sentra_canvas/service.py",
    "sentra_canvas/static/native.html", "sentra_canvas/static/native.css",
    "sentra_canvas/static/native.js", "sentra_canvas/static/fractal-grid.js",
    "sentra_canvas/static/rope-physics.js",
    "sentra_cli/agent.py", "sentra_cli/client.py", "sentra_cli/canvas.py",
    "sentra_model_gateway/gateway.py", "sentra_remote/installer.py",
    "tests/unit/test_canvas_web_peer_transport.py",
    "tests/unit/test_canvas_cli_coordination.py",
    "tests/unit/test_sentra_cli_model_effort.py",
    "tests/unit/test_ci_pipeline_contract.py",
    "tests/js/canvas_cable_physics.cjs",
    "tests/e2e/test_canvas_web_cult_ui.py",
    "tests/e2e/test_sentra_canvas_native_ui.py",
    "integrations/codex_chatgpt_web/upstream.json",
    "integrations/codex_chatgpt_web/sentra-upstream.patch",
    "requirements.lock.txt", "sentra_version.py", "docs/CI_CD.md",
)
FORBIDDEN = ("auth.json", "browser_profiles/", "dist/", "release/", ".sentra/", ".oma/", ".maestri/", ".tmp/")
LOCK = re.compile(r"^[A-Za-z0-9_.-]+==[^\s;]+\s+--hash=sha256:[0-9a-f]{64}(?:\s+--hash=sha256:[0-9a-f]{64})*$")
PATCH = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
ACTION = re.compile(r"^\s*(?:-\s*)?uses:\s*([^#\s]+)", re.MULTILINE)
PIN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


def require(check: bool, reason: str) -> None:
    if not check:
        raise ValueError(reason)


def check_files(root: Path, tracked: bool) -> None:
    missing = [p for p in REQUIRED if not (root / p).is_file()]
    require(not missing, f"Missing release inputs: {missing}")
    if not tracked:
        return
    proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True)
    paths = {b.decode("utf-8") for b in proc.stdout.split(b"\0") if b}
    require(set(REQUIRED) <= paths, f"Untracked release inputs: {sorted(set(REQUIRED) - paths)}")
    unsafe = sorted(p for p in paths if any(p == f or p.startswith(f) for f in FORBIDDEN)
                    or p.lower().endswith((".pfx", ".p12", ".key", ".pem")))
    require(not unsafe, f"Tracked private data / generated outputs: {unsafe[:12]}")


def check_lock(path: Path) -> None:
    reqs = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    require(bool(reqs) and all(LOCK.fullmatch(r) for r in reqs), "Dependency lock has unhashed/unpinned entries")
    names = [r.split("==")[0].lower().replace("_", "-") for r in reqs]
    require(len(names) == len(set(names)), "Duplicate locked dependency")


def check_patch(root: Path, upstream: bool) -> None:
    manifest = json.loads((root / "integrations/codex_chatgpt_web/upstream.json").read_text(encoding="utf-8"))
    require(manifest["repository"] == "https://github.com/miuuyy/codex-chatgpt-web.git", "Upstream source drift")
    require(re.fullmatch(r"v\d+\.\d+\.\d+", manifest["ref"]) is not None, "Upstream ref not semver")
    require(re.fullmatch(r"[0-9a-f]{40}", manifest["commit"]) is not None, "Upstream commit not pinned")
    diff = root / manifest["integration_patch"]
    headers = PATCH.findall(diff.read_text(encoding="utf-8"))
    paths = [b for a, b in headers if a == b]
    require(len(paths) == len(headers) and len(set(paths)) == len(paths)
            and set(paths) == set(manifest["patch_files"]), "Patch/manifest path drift")
    require(all(not any(f in p for f in ("../", "\\", ".git/", ".sentra/")) for p in paths), "Unsafe patch path")
    if upstream:
        checkout = root / manifest["development_checkout"]
        require((checkout / ".git").exists(), "Pinned checkout missing")
        def git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True)
        require(git("rev-parse", "HEAD").stdout.strip() == manifest["commit"], "Upstream commit drift")
        require(not git("status", "--porcelain").stdout.strip(), "Upstream checkout dirty")
        result = git("apply", "--check", "--unidiff-zero", str(diff))
        require(result.returncode == 0, f"Patch does not apply: {result.stderr[:450]}")


def check_workflows(root: Path) -> None:
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = (root / ".github/workflows/release-commander.yml").read_text(encoding="utf-8")
    registry = (root / ".github/workflows/release-mcp-registry.yml").read_text(encoding="utf-8")
    for name, value in (("ci", ci), ("release", release), ("registry", registry)):
        actions = ACTION.findall(value)
        require(bool(actions) and all(PIN.fullmatch(a) for a in actions), f"{name} contains unpinned GitHub Actions")
        require("pull_request_target:" not in value, f"{name} allows privileged PR code")
    for required in ("permissions:", "contents: read", "concurrency:", "--require-tracked",
                     "test_web_models.ps1", "test_canvas.ps1", "tests/unit", "tests/failure", "tests/integration"):
        require(required in ci, f"CI missing {required}")
    for required in ("windows-release:", "publish-release:", "needs: windows-release",
                     "contents: write", "WINDOWS_CERTIFICATE_B64", "Get-AuthenticodeSignature",
                     "SHA256SUMS.txt", "sentra-canvas.exe", "Real Setup install/uninstall roundtrip",
                     "gh release create", "integration-build.json"):
        require(required in release, f"Release missing {required}")


def check_package(root: Path) -> None:
    builder = (root / "scripts/commander/build_windows.py").read_text(encoding="utf-8")
    installer = (root / "sentra_remote/installer.py").read_text(encoding="utf-8")
    canvas = (root / "scripts/commander/build_canvas.py").read_text(encoding="utf-8")
    require(all('"'+p+'"' in builder and '"'+p+'"' in installer
                for p in ("sentra-canvas.exe", "sentra-cli.exe")), "CLI/Canvas omitted from Setup")
    require('"native.js"' in canvas and '"native.css"' in canvas, "Canvas assets omitted")
    require("build_web_models(dist)" in builder, "Web Models build omitted")
    require("patch_sha256" in (root / "scripts/commander/release_assets.py").read_text(encoding="utf-8"),
            "Release does not validate Web Models patch provenance")


def verify(root: Path = ROOT, *, tracked: bool = False, upstream: bool = False) -> None:
    check_files(root, tracked)
    check_lock(root / "requirements.lock.txt")
    check_patch(root, upstream)
    check_workflows(root)
    check_package(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--verify-upstream", action="store_true")
    args = parser.parse_args()
    verify(tracked=args.require_tracked, upstream=args.verify_upstream)
    print("SENTRA_CICD_CONTRACT_OK")
