"""Clean-install plan for disposable-VM QA (Vitra-owned, planning only).

Emits a reviewable JSON plan for a clean install + clean uninstall cycle.
This module NEVER installs, uninstalls, signs, downloads or launches
anything: every step is a description for the future QA run that the Codex
principal will liberate. Distribution between friends reuses the same
signed Setup asset verified by release_doctor.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentra_version import PRODUCT_VERSION

SCHEMA = 1


def clean_install_plan(*, release_dir: Path, vm_snapshot: str = "",
                       installer_options: list[str] | None = None) -> dict:
    setup = f"SENTRA-Setup-{PRODUCT_VERSION}.exe"
    return {
        "schema": SCHEMA,
        "goal": "clean install + clean uninstall in a disposable VM, then friends distribution",
        "release_dir": str(release_dir),
        "vm": {
            "snapshot": vm_snapshot or "disposable-windows-11-snapshot (operator-provided)",
            "network": "default (Setup downloads only the pinned tunnel-client archive)",
            "rollback": "restore VM snapshot afterwards; never reuse the VM for production",
        },
        "steps": [
            {"n": 1, "action": "verify_release",
             "detail": f"release_doctor --release {release_dir} --trusted-signer <real-thumbprint>"},
            {"n": 2, "action": "backup_existing_state",
             "detail": "coordinated_backup over state root to an offline sibling stage"},
            {"n": 3, "action": "clean_install",
             "detail": f"{setup} " + " ".join(
                 installer_options or ["--no-system-registration", "--no-launch",
                                       "--stop-after-doctor"])},
            {"n": 4, "action": "doctor",
             "detail": "Setup stops after Doctor; review local-ready/tunnel-online/version axes"},
            {"n": 5, "action": "first_launch",
             "detail": "launch Desktop once; verify shell-first surface with Canvas fallback"},
            {"n": 6, "action": "clean_uninstall",
             "detail": "uninstall --keep-config=false in VM; confirm owned files removed, state retained"},
            {"n": 7, "action": "distribute",
             "detail": "share only the signed Setup + SHA256SUMS.txt + SBOM; never unsigned QA builds"},
        ],
        "forbidden": ["unsigned distribution", "production-machine QA", "simulated signing"],
        "homologated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the clean-install QA plan (no execution)")
    parser.add_argument("--release", type=Path, default=ROOT / "release")
    parser.add_argument("--vm-snapshot", default="")
    args = parser.parse_args(argv)
    print(json.dumps(clean_install_plan(release_dir=args.release, vm_snapshot=args.vm_snapshot),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
