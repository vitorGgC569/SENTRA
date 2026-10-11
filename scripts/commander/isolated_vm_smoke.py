"""Disposable Windows VM smoke runner. NEVER run on the shared development host.

QA only. Requires explicit authorization, Windows VM evidence and a verified
publisher. It emits non-secret evidence and never asserts ChatGPT approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.commander.release_doctor import audit_release
from sentra_remote.installer import TUNNEL_SHA256
from sentra_remote.updater import verify_authenticode

VM_MARKERS = ("virtual machine", "vmware", "virtualbox", "qemu", "kvm", "hyper-v", "xen")


def vm_evidence() -> bool:
    if os.name != "nt":
        return False
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "$p=Get-CimInstance Win32_ComputerSystem; "
         "($p.Manufacturer+' '+$p.Model).ToLowerInvariant()"],
        capture_output=True, text=True, timeout=20, check=True,
    )
    return any(marker in proc.stdout.lower() for marker in VM_MARKERS)


def preflight(*, execute: bool, acknowledged: bool, trusted_signer: str) -> None:
    if not execute or not acknowledged:
        raise PermissionError("smoke is DRY RUN; explicit VM execution authorization required")
    if not trusted_signer:
        raise PermissionError("release smoke needs independently trusted Authenticode signer")
    if not vm_evidence():
        raise PermissionError("refusing clean installation outside a disposable Windows VM")


def _msi_vm_roundtrip(msi: Path, isolated_install: Path, *,
                      execute: bool, acknowledged: bool, trusted_signer: str) -> dict:
    """Only after fresh disposable VM and owner-approval preflight, even standalone."""
    preflight(execute=execute, acknowledged=acknowledged, trusted_signer=trusted_signer)
    verify_authenticode(msi, trusted_signer)
    if os.name != "nt" or not msi.is_file():
        raise PermissionError("MSI QA requires Windows and signed release media")
    if isolated_install.exists():
        raise PermissionError("MSI QA must start with an empty installation path")
    install_cmd = [
        "msiexec.exe", "/i", str(msi), "/qn", "/norestart",
        "ALLUSERS=2", "MSIINSTALLPERUSER=1", f"INSTALLDIR={isolated_install}",
    ]
    result = subprocess.run(install_cmd, timeout=600, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"disposable VM MSI installation failed: exit={result.returncode}")
    checked = (isolated_install / "sentra-canvas.exe", isolated_install / "sentra-cli.exe",
               isolated_install / "sentra-mcp.exe", isolated_install / "edge_extension" / "manifest.json",
               isolated_install / "web-models" / "win-unpacked" / "Codex Web GPT.exe",
               isolated_install / "sentra-electron" / "electron.exe")
    errors = [item.name for item in checked if not item.is_file()]
    if errors:
        raise RuntimeError("MSI installed payload is incomplete: " + ", ".join(errors))
    uninstall = subprocess.run(
        ["msiexec.exe", "/x", str(msi), "/qn", "/norestart"],
        timeout=600, capture_output=True,
    )
    if uninstall.returncode != 0:
        raise RuntimeError(f"disposable VM MSI uninstall failed: exit={uninstall.returncode}")
    deadline = time.monotonic() + 90
    while isolated_install.exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    if isolated_install.exists():
        raise RuntimeError("MSI uninstall left files in isolated install location")
    return {"msi_install_executed": True, "msi_uninstall_clean": True,
            "checked_components": len(checked)}


def run_vm_smoke(release: Path, tunnel_archive: Path, *,
                 version: str, trusted_signer: str, execute: bool, acknowledged: bool) -> dict:
    preflight(execute=execute, acknowledged=acknowledged, trusted_signer=trusted_signer)
    release = release.resolve(strict=True)
    report = audit_release(release, version=version, expected_signer=trusted_signer)
    if report["result"] != "pass":
        raise RuntimeError("release artifact preflight failed")
    from scripts.commander.pdfium_pin import verify_wheel
    # PDFium is packaged into sentra-canvas.exe; never call pip on target VM.
    if not tunnel_archive.is_file() or hashlib.sha256(tunnel_archive.read_bytes()).hexdigest() != TUNNEL_SHA256:
        raise ValueError("pinned tunnel archive mismatch")
    setup = release / f"SENTRA-Setup-{version}.exe"
    verify_authenticode(setup, trusted_signer)
    # All artifacts under this unique temp directory, no global registrations.
    with tempfile.TemporaryDirectory(prefix="sentra-disposable-vm-smoke-") as base:
        root = Path(base)
        installed, state = root / "Commander", root / "state"
        command = [str(setup), "--silent", "--install-dir", str(installed),
                   "--state-dir", str(state), "--tunnel-archive", str(tunnel_archive),
                   "--no-launch", "--no-system-registration", "--no-git",
                   "--stop-after-doctor"]
        result = subprocess.run(command, timeout=600, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"VM isolated Setup exit={result.returncode}")
        required = (
            "sentra-canvas.exe", "sentra-cli.exe", "sentra-mcp.exe",
            "sentra-electron/electron.exe", "sentra-electron/sentra-surface-build.json",
            "edge_extension/manifest.json",
            "web-models/win-unpacked/Codex Web GPT.exe",
            "docs/START_HERE.md",
        )
        missing = [name for name in required if not (installed / name).is_file()]
        if missing:
            raise RuntimeError("VM first install missing components: " + ", ".join(missing))
        uninstall = subprocess.run(
            [str(installed / "sentra-installer.exe"), "--uninstall",
             "--install-dir", str(installed), "--state-dir", str(state),
             "--no-system-registration"],
            timeout=120, capture_output=True,
        )
        if uninstall.returncode:
            raise RuntimeError("VM uninstall failed")
        deadline = time.monotonic() + 120
        while (installed.exists() or state.exists()) and time.monotonic() < deadline:
            time.sleep(0.5)
        if installed.exists() or state.exists():
            raise RuntimeError("VM uninstall left install/state residuals")
        # MSI writes per-user registry entries; only execute inside the
        # authorized disposable VM. Never invoke msiexec on the dev checkout.
        msi = release / f"SENTRA-Desktop-{version}-x64.msi"
        verify_authenticode(msi, trusted_signer)
        msi_proof = _msi_vm_roundtrip(
            msi, root / "MSI-Commander", execute=execute,
            acknowledged=acknowledged, trusted_signer=trusted_signer)
        return {
            "schema": 1, "version": version, "smoke": "pass",
            "setup_sha256": hashlib.sha256(setup.read_bytes()).hexdigest(),
            "msi_sha256": hashlib.sha256(msi.read_bytes()).hexdigest(),
            "vm_asserted": True, "file_checks": len(required),
            "uninstall_clean": True,
            **msi_proof,
            "native_canvas_window_verified": False,
            "chatgpt_external_account_verified": False,
            "homologated": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--tunnel-archive", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--trusted-signer", default="")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack-disposable-vm", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_vm_smoke(args.release, args.tunnel_archive,
            version=args.version, trusted_signer=args.trusted_signer,
            execute=args.execute, acknowledged=args.ack_disposable_vm)
    except (ValueError, PermissionError, RuntimeError, OSError) as exc:
        print(json.dumps({"smoke": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
