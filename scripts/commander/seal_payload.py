"""Seal signed Windows payload provenance after Authenticode changes EXE hashes.

Signing occurs after the payload build. The original build proof must match
current sources and expected binaries before any signed hash is published.
This has NO signing keys and never signs/installs anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.commander.build_windows import PAYLOAD_NAMES, _source_fingerprint
from sentra_remote.updater import verify_authenticode


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def seal_signed_payload(dist: Path, trusted_signer: str) -> dict:
    """Update ONLY payload proof, after checking every legitimate signed binary."""
    dist = Path(dist).resolve(strict=True)
    proof_file = dist / "build-provenance-payload.json"
    data = json.loads(proof_file.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("phase") != "payload":
        raise ValueError("missing verified payload provenance")
    if data.get("sources") != _source_fingerprint():
        raise ValueError("product sources changed since payload build")
    existing = data.get("executables")
    if not isinstance(existing, dict) or set(existing) != set(PAYLOAD_NAMES):
        raise ValueError("payload inventory mismatch")
    signer = str(trusted_signer).replace(" ", "").upper()
    import re
    if not re.fullmatch(r"[A-F0-9]{40,64}", signer):
        raise ValueError("a trusted signer thumbprint is required")
    if data.get("signed_seal"):
        raise ValueError("payload provenance already sealed")
    sealed = {}
    for name in PAYLOAD_NAMES:
        target = dist / name
        if target.is_symlink() or not target.is_file():
            raise FileNotFoundError("missing payload binary: " + name)
        verify_authenticode(target, signer)
        sealed[name] = {
            "sha256": _sha(target), "bytes": target.stat().st_size,
            "before_sign_sha256": existing[name]["sha256"],
        }
    data["executables"] = sealed
    data["signed_seal"] = {"schema": 1, "signer_thumbprint": signer}
    pending = proof_file.with_name(proof_file.name + ".sealed.tmp")
    try:
        with pending.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        pending.replace(proof_file)
    finally:
        pending.unlink(missing_ok=True)
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--trusted-signer", required=True)
    args = parser.parse_args()
    seal_signed_payload(args.dist, args.trusted_signer)
    print("SIGNED_PAYLOAD_PROVENANCE_SEALED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
