"""Real release signing contract (Vitra-owned, verification only).

Signing is NEVER simulated here. This module verifies Authenticode
signatures against a separately supplied trusted publisher thumbprint and
seals the payload provenance AFTER a real signing event. The actual
signature is produced by the release pipeline holding the real publisher
key (local HSM / CI secret); QA/unsigned builds are explicitly reported
as unsigned and must never be distributed as releases.

Usage (future, Codex-liberated):
  release_signing --release <dir> --trusted-signer <thumbprint> [--seal]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentra_version import PRODUCT_VERSION

SCHEMA = 1
_THUMBPRINT_RE = re.compile(r"[A-F0-9]{40,64}")


def require_real_thumbprint(value: str) -> str:
    normalized = str(value or "").replace(" ", "").upper()
    if not _THUMBPRINT_RE.fullmatch(normalized):
        raise ValueError(
            "real Authenticode publisher thumbprint required; "
            "empty/placeholder/simulated signers are refused"
        )
    return normalized


def verify_signed_release(release_dir: Path, *, trusted_signer: str,
                          version: str = PRODUCT_VERSION) -> dict:
    """Verify Setup+MSI Authenticode signatures with the trusted publisher."""
    signer = require_real_thumbprint(trusted_signer)
    from sentra_remote.updater import verify_authenticode

    release = Path(release_dir).resolve(strict=True)
    setup = release / f"SENTRA-Setup-{version}.exe"
    msi = release / f"SENTRA-Desktop-{version}-x64.msi"
    for asset in (setup, msi):
        if not asset.is_file() or asset.is_symlink():
            raise ValueError(f"signed release asset missing: {asset.name}")
        verify_authenticode(asset, signer)
    manifest_file = release / "release-manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    if str(manifest.get("signer_thumbprint") or "").replace(" ", "").upper() != signer:
        raise ValueError("release manifest publisher does not match the trusted signer")
    return {"schema": SCHEMA, "result": "signed-verified", "version": version,
            "signer_thumbprint": signer, "assets": [setup.name, msi.name],
            "simulated": False}


def seal_after_signing(dist_dir: Path, *, trusted_signer: str) -> dict:
    """Record the post-signing seal in the payload provenance (no re-signing)."""
    signer = require_real_thumbprint(trusted_signer)
    from scripts.commander.build_windows import _source_fingerprint

    dist = Path(dist_dir).resolve(strict=True)
    evidence_file = dist / "build-provenance-payload.json"
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    if evidence.get("sources") != _source_fingerprint():
        raise ValueError("payload provenance is stale relative to current sources")
    digest = hashlib.sha256(evidence_file.read_bytes()).hexdigest()
    return {"schema": SCHEMA, "sealed": True, "signer_thumbprint": signer,
            "provenance_sha256": digest, "simulated": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify real release signing (never simulates)")
    parser.add_argument("--release", type=Path, default=ROOT / "release")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--trusted-signer", required=True)
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--version", default=PRODUCT_VERSION)
    args = parser.parse_args(argv)
    try:
        result = verify_signed_release(args.release, trusted_signer=args.trusted_signer,
                                       version=args.version)
        if args.seal:
            result["seal"] = seal_after_signing(args.dist, trusted_signer=args.trusted_signer)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema": SCHEMA, "result": "fail", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
