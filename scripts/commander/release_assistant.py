"""SENTRA local release assistant: explicit, non-publishing QA/build workflow.

Safe to invoke from Desktop Commander, Codex, or an interactive terminal.
This tool never signs, creates tags, uploads assets, or modifies remote accounts.
The existing signed GitHub workflow remains the authoritative publisher.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import socket
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_REPORT = ROOT / ".tmp" / "release-assistant" / "last-run.json"
DEFAULT_CANDIDATE_DIST = (
    Path(os.environ.get("LOCALAPPDATA") or str(ROOT / ".tmp"))
    / "SENTRA" / "Build" / "ReleaseCandidate" / "dist"
)
SECRET_PATTERN = re.compile(r"(?i)(sk-[a-z0-9_-]{12,}|(?:api[_-]?key|token|password)\s*[:=]\s*[^\s]+)")


def _safe(text: str) -> str:
    return SECRET_PATTERN.sub("[REDACTED]", text)[-6000:]


def _run(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
        check=False, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preflight(root: Path = ROOT) -> dict[str, Any]:
    """Read-only; never enumerate or print secret values."""
    checks: list[dict[str, Any]] = []
    def check(name: str, passed: bool, *, detail: str = "", required: bool = True) -> None:
        checks.append({"id": name, "ok": passed, "required": required, "detail": detail})
    check("windows", os.name == "nt", detail=platform.system())
    check("python", sys.version_info >= (3, 11), detail=sys.version.split()[0])
    try:
        process = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
            capture_output=True, text=True, timeout=15, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        clean = process.returncode == 0 and not process.stdout.strip()
        git_detail = "clean" if clean else (
            "changes present" if process.returncode == 0 else "git status failed"
        )
        check("clean_tree", clean, detail=git_detail, required=False)
        check("git", process.returncode == 0)
    except (OSError, subprocess.SubprocessError):
        clean = False
        check("clean_tree", False, detail="git status unavailable", required=False)
        check("git", False)
    required_paths = [
        "scripts/commander/build_windows.py",
        "scripts/commander/release_assets.py",
        ".github/workflows/release-commander.yml",
        "docs/onboarding_media/mcp-create-tunnel.mp4",
        "docs/onboarding_media/mcp-connect-connector.mp4",
        "edge_extension/manifest.json",
        "integrations/codex_chatgpt_web/upstream.json",
        "integrations/codex_chatgpt_web/sentra-upstream.patch",
    ]
    missing = [name for name in required_paths if not (root / name).is_file()]
    check("release_inputs", not missing, detail=", ".join(missing))
    try:
        import pytest  # noqa: F401
        check("pytest", True)
    except ImportError:
        check("pytest", False)
    try:
        import PyInstaller  # noqa: F401
        check("pyinstaller", True)
    except ImportError:
        check("pyinstaller", False, required=False)
    return {
        "ok": all(item["ok"] for item in checks if item["required"]),
        "clean_tree": clean,
        "checks": checks,
        "candidate_only": True,
        "publishing": "not_supported_here_use_signed_release_ci",
    }


def verify_candidate(dist: Path) -> dict[str, Any]:
    from scripts.commander.build_windows import EXPECTED

    files: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in EXPECTED:
        path = dist / name
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(name)
            continue
        files.append({"name": name, "bytes": path.stat().st_size, "sha256": _digest(path)})
    videos = [
        ROOT / "docs" / "onboarding_media" / "mcp-create-tunnel.mp4",
        ROOT / "docs" / "onboarding_media" / "mcp-connect-connector.mp4",
    ]
    for path in videos:
        if not path.is_file() or not path.stat().st_size:
            missing.append(str(path.relative_to(ROOT)))
    return {
        "ok": not missing,
        "candidate_only": True,
        "missing": missing,
        "files": files,
        "note": "Hash presence is not an Authenticode signature or a functional install test",
    }


def run_qa(*, full: bool = True, timeout_s: int = 2400) -> dict[str, Any]:
    suite = ["tests"] if full else [
        "tests/unit/test_setup_assistant.py",
        "tests/unit/test_setup_assistant_cli.py",
        "tests/unit/test_onboarding.py",
        "tests/unit/test_commander_release.py",
        "tests/unit/test_desktop_v1.py",
        "tests/unit/test_release_assistant.py",
        "tests/unit/test_edge_store_assistant.py",
        "tests/unit/test_extension_versions.py",
    ]
    command = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *suite]
    result = _run(command, timeout=timeout_s)
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "scope": "all" if full else "targeted",
        "output_tail": _safe((result.stdout or "") + "\n" + (result.stderr or "")),
    }


def make_candidate(
    dist: Path, *, timeout_s: int = 9000,
    tunnel_archive: Path | None = None,
) -> dict[str, Any]:
    command = [
        sys.executable, "scripts/commander/build_windows.py",
        "--dist", str(dist), "--phase", "all",
    ]
    result = _run(command, timeout=timeout_s)
    if result.returncode:
        return {
            "ok": False, "exit_code": result.returncode,
            "output_tail": _safe((result.stdout or "") + "\n" + (result.stderr or "")),
        }
    candidate = verify_candidate(dist)
    if not candidate["ok"]:
        return candidate
    if tunnel_archive is None:
        candidate["ok"] = False
        candidate["msi"] = {"ok": False, "reason": "pinned tunnel archive not supplied"}
        return candidate
    from sentra_remote.installer import TUNNEL_SHA256

    if not tunnel_archive.is_file() or _digest(tunnel_archive).lower() != TUNNEL_SHA256.lower():
        candidate["ok"] = False
        candidate["msi"] = {"ok": False, "reason": "pinned tunnel archive missing or SHA-256 mismatch"}
        return candidate
    release_dir = dist.parent / "candidate-release"
    result = _run(
        [
            sys.executable, "scripts/commander/release_assets.py",
            "--dist", str(dist), "--release", str(release_dir),
            "--tunnel-archive", str(tunnel_archive),
        ],
        timeout=1800,
    )
    from sentra_version import PRODUCT_VERSION

    msi = release_dir / f"SENTRA-Desktop-{PRODUCT_VERSION}-x64.msi"
    setup = release_dir / f"SENTRA-Setup-{PRODUCT_VERSION}.exe"
    candidate["msi"] = {
        "ok": result.returncode == 0 and msi.is_file() and setup.is_file(),
        "path": str(msi) if msi.is_file() else None,
        "sha256": _digest(msi) if msi.is_file() else None,
        "output_tail": _safe((result.stdout or "") + "\n" + (result.stderr or "")),
        "unsigned_candidate": True,
    }
    candidate["ok"] = bool(candidate["msi"]["ok"])
    return candidate


def _free_local_ports() -> tuple[int, int]:
    ports: list[int] = []
    for _ in range(2):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
            handle.bind(("127.0.0.1", 0))
            ports.append(int(handle.getsockname()[1]))
    if ports[0] == ports[1]:
        raise RuntimeError("unable to select distinct local smoke ports")
    return ports[0], ports[1]


def smoke_candidate(
    dist: Path, tunnel_archive: Path, *, approved: bool,
    timeout_s: int = 420,
) -> dict[str, Any]:
    """Install/uninstall an EXE in disposable per-user paths, without OS registration."""
    if not approved:
        raise PermissionError("smoke test requires explicit operator approval")
    from sentra_remote.installer import TUNNEL_SHA256

    if not tunnel_archive.is_file() or _digest(tunnel_archive).lower() != TUNNEL_SHA256.lower():
        return {"ok": False, "reason": "pinned_tunnel_client_missing_or_mismatch"}
    setup = dist / "SENTRA-Setup.exe"
    if not setup.is_file() or not setup.stat().st_size:
        return {"ok": False, "reason": "setup_executable_missing"}

    with tempfile.TemporaryDirectory(prefix="sentra-qa-install-") as folder:
        parent = Path(folder).resolve()
        install = parent / "Install" / "Commander"
        state = parent / "State"
        user_project = parent / "UserProject"
        user_project.mkdir()
        sentinel = user_project / "keep-my-code.txt"
        sentinel.write_text("USER_PROJECT_MUST_SURVIVE", encoding="utf-8")
        mcp_port, relay_port = _free_local_ports()
        command = [
            str(setup.resolve()), "--silent",
            "--install-dir", str(install),
            "--state-dir", str(state),
            "--tunnel-archive", str(tunnel_archive.resolve()),
            "--no-git", "--no-launch", "--no-system-registration",
            "--mcp-port", str(mcp_port), "--relay-port", str(relay_port),
            "--stop-after-doctor",
        ]
        install_result = _run(command, timeout=timeout_s)
        expected = (
            "sentra-desktop.exe", "sentra-cli.exe", "sentra-installer.exe",
            "docs/START_HERE.md",
            "docs/onboarding_media/SENTRA_SETUP_GUIDE.html",
            "docs/onboarding_media/mcp-create-tunnel.mp4",
            "docs/onboarding_media/mcp-connect-connector.mp4",
        )
        present = {
            path: (install / Path(path)).is_file() for path in expected
        }
        if install_result.returncode != 0 or not all(present.values()):
            return {
                "ok": False, "stage": "install",
                "exit_code": install_result.returncode,
                "files": present,
                "output_tail": _safe(
                    (install_result.stdout or "") + "\n" + (install_result.stderr or "")
                ),
            }
        helper = install / "sentra-installer.exe"
        uninstall = _run(
            [str(helper), "--uninstall",
             "--install-dir", str(install),
             "--state-dir", str(state), "--no-system-registration"],
            timeout=180,
        )
        # Deferred cleanup may complete slightly after the helper exits.
        if uninstall.returncode == 0:
            for _ in range(20):
                if not install.exists():
                    break
                time.sleep(0.25)
        removed = not install.exists()
        project_preserved = (
            sentinel.is_file()
            and sentinel.read_text(encoding="utf-8") == "USER_PROJECT_MUST_SURVIVE"
        )
        return {
            "ok": uninstall.returncode == 0 and removed and project_preserved,
            "stage": "complete" if uninstall.returncode == 0 and removed else "uninstall",
            "install_exit": install_result.returncode,
            "uninstall_exit": uninstall.returncode,
            "files": present,
            "removed": removed,
            "user_project_preserved": project_preserved,
            "unsigned_candidate_only": True,
        }


def _pinned_tunnel_sha256() -> str:
    from sentra_remote.installer import TUNNEL_SHA256
    return TUNNEL_SHA256


def run_workflow(
    mode: str, *, root: Path = ROOT, dist: Path | None = None,
    approved: bool = False, allow_dirty: bool = False,
    full: bool = True, tunnel_archive: Path | None = None,
) -> dict[str, Any]:
    dist = dist or DEFAULT_CANDIDATE_DIST
    report = {"mode": mode, "time": int(time.time()), "preflight": preflight(root)}
    pre = report["preflight"]
    if mode == "doctor":
        report["ok"] = bool(pre["ok"])
    elif mode == "verify":
        report["verification"] = verify_candidate(dist)
        report["ok"] = bool(report["verification"]["ok"])
    elif mode == "smoke":
        if not approved:
            report.update(ok=False, blocker="--approve-run required for disposable install test")
        elif tunnel_archive is None:
            report.update(ok=False, blocker="--tunnel-archive required for install test")
        elif not pre["ok"]:
            report.update(ok=False, blocker="preflight checks failed")
        else:
            report["smoke"] = smoke_candidate(dist, tunnel_archive, approved=approved)
            report["ok"] = bool(report["smoke"]["ok"])
    elif mode in {"qa", "candidate"}:
        if not approved:
            report.update(ok=False, blocker="--approve-run is required for tests/build")
        elif not pre["ok"]:
            report.update(ok=False, blocker="preflight checks failed")
        elif mode == "candidate" and not pre["clean_tree"] and not allow_dirty:
            report.update(ok=False, blocker="dirty tree: use --allow-dirty for unsigned local QA only")
        elif mode == "candidate" and tunnel_archive is None:
            report.update(ok=False, blocker="--tunnel-archive is required for complete EXE/MSI candidate")
        elif mode == "candidate" and not (
            tunnel_archive.is_file() and
            _digest(tunnel_archive).lower() == _pinned_tunnel_sha256()
        ):
            report.update(ok=False, blocker="official tunnel client missing or SHA-256 mismatch")
        else:
            report["tests"] = run_qa(full=full)
            if report["tests"]["ok"] and mode == "candidate":
                report["verification"] = make_candidate(dist, tunnel_archive=tunnel_archive)
            report["ok"] = bool(report.get("verification", report["tests"])["ok"])
    else:
        raise ValueError("invalid mode")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("doctor", "qa", "candidate", "verify", "smoke"))
    parser.add_argument("--approve-run", action="store_true",
                        help="Explicit consent before tests or building binaries")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="Allow dirty tree for unsigned QA candidates, never for stable releases")
    parser.add_argument("--targeted-tests", action="store_true")
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--tunnel-archive", type=Path,
                        help="Pinned SHA-256 verified archive enables unsigned MSI candidate")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = run_workflow(
            args.mode, dist=args.dist, approved=args.approve_run,
            allow_dirty=args.allow_dirty, full=not args.targeted_tests,
            tunnel_archive=args.tunnel_archive,
        )
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
        report = {"mode": args.mode, "ok": False, "blocker": type(exc).__name__,
                  "detail": _safe(str(exc))}
    target = args.report.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(target)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
