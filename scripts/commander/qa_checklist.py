"""Friends-distribution + QA-final checklist emitter (Vitra-owned, planning only).

Emits a reviewable JSON checklist for distribution between friends and the
final QA run. NEVER downloads, installs, signs, launches or transmits
anything: every item is a gate for the future run that the Codex principal
will liberate. Unsigned builds are explicitly marked NOT FOR DISTRIBUTION.
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


def qa_checklist(*, release_dir: Path, trusted_signer: str = "") -> dict:
    setup = f"SENTRA-Setup-{PRODUCT_VERSION}.exe"
    signed = bool((trusted_signer or "").strip())
    return {
        "schema": SCHEMA,
        "goal": "friends distribution + final QA (gates only, nothing executed)",
        "release_dir": str(release_dir),
        "distribution": {
            "allowed": signed,
            "assets": [setup, "SHA256SUMS.txt", f"SENTRA-Desktop-{PRODUCT_VERSION}.cdx.json"],
            "rule": ("share ONLY the signed Setup + SHA256SUMS.txt + SBOM "
                     if signed else
                     "UNSIGNED BUILD — NOT FOR DISTRIBUTION. Sign first via release_signing."),
            "channel": "direct file share between friends; no auto-update channel until signed",
        },
        "gates": [
            {"id": "release_doctor",
             "detail": "release_doctor --release <dir> --dist <dir> --trusted-signer <real> passes"},
            {"id": "signing",
             "detail": "release_signing --trusted-signer <real> [--seal]; simulation refused"},
            {"id": "sbom_notice",
             "detail": "per-file SBOM + NOTICE present (provider_pins inventory, payload licenses)"},
            {"id": "sidecars",
             "detail": "Lume/Pulso/Selo signed manifests collected; combined digest in manifest"},
            {"id": "clean_install",
             "detail": "clean_install_plan in a disposable VM; Doctor reviewed; clean uninstall"},
            {"id": "backup_restore",
             "detail": "coordinated backup/restore CAS drill on a scratch stage (SQLite+config)"},
            {"id": "staged_update",
             "detail": "staged product update defers with live ConPTY, applies on app exit"},
            {"id": "setup_axes",
             "detail": "local-ready/tunnel-online/account-app-observed/tools-authorized/"
                       "version-current + extension state verified independently"},
            {"id": "doctor_preview",
             "detail": "diagnostics export preview redacted + reviewed locally before sharing"},
            {"id": "artwork_license_provenance",
             "detail": "OpenDots mascots + guacamole-common-js LICENSE/NOTICE + PROVENANCE "
                       "under docs/opendots/ + docs/guacamole/; PNG bytes match provenance; "
                       "MIT/Atai Barkai + Apache-2.0/SRI in release manifest"},
        ],
        "homologated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the friends/QA-final checklist (no execution)")
    parser.add_argument("--release", type=Path, default=ROOT / "release")
    parser.add_argument("--trusted-signer", default="")
    args = parser.parse_args(argv)
    print(json.dumps(qa_checklist(release_dir=args.release,
                                  trusted_signer=args.trusted_signer),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
