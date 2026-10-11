"""Stable publication is blocked until independently reviewed VM QA evidence.

An integrity hash supplied out-of-band binds an externally produced QA report
to this release. Local unit tests or file-presence checks cannot grant approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


REQUIRED_PROOFS = (
    "clean_setup_install_verified",
    "clean_msi_install_verified",
    "uninstall_residuals_absent",
    "native_canvas_window_verified",
    "web_models_runtime_verified",
    "mcp_extension_integration_verified",
    "signed_artifacts_verified",
    "reviewed_by_release_owner",
)


def check_publication(release: Path, evidence: Path, *,
                      expected_sha256: str, version: str) -> dict:
    expected_sha256 = expected_sha256.lower().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise PermissionError("missing independently supplied VM QA evidence digest")
    if not evidence.is_file() or evidence.stat().st_size > 32768 or evidence.is_symlink():
        raise PermissionError("no independent VM QA evidence artifact")
    if _sha(evidence) != expected_sha256:
        raise PermissionError("VM QA evidence digest mismatch")
    data = json.loads(evidence.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("version") != version:
        raise ValueError("VM QA release identity mismatch")
    if any(data.get(key) is not True for key in REQUIRED_PROOFS):
        raise PermissionError("VM QA is incomplete; stable publication denied")
    manifest = json.loads((release / "release-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version or manifest.get("setup") != f"SENTRA-Setup-{version}.exe":
        raise ValueError("release manifest version mismatch")
    setup_hash = _sha(release / manifest["setup"])
    if data.get("setup_sha256") != setup_hash:
        raise PermissionError("VM QA tested a different Setup executable")
    msi = release / f"SENTRA-Desktop-{version}-x64.msi"
    if not msi.is_file() or data.get("msi_sha256") != _sha(msi):
        raise PermissionError("VM QA tested a different MSI installer")
    return {"release_gate": "pass", "version": version, "vm_evidence": "bound",
            "independent_review": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        result = check_publication(args.release, args.evidence,
            expected_sha256=args.expected_sha256, version=args.version)
    except (ValueError, OSError, PermissionError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"release_gate": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
