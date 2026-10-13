"""Selo: release gate binding source provenance + Grype scan receipts.

A release is approved only when:
- every pinned source verifies (SourceGate.verify_all),
- the SBOM digest matches the declared artifact,
- the Grype report digest matches and evaluate_grype_json allows it,
- no ignored matches are present (checked by scan receipt).

This module never runs untrusted binaries itself; scanning stays in
grype_scan.scan_sbom with an explicitly pinned executable. Here we verify
already-produced receipts for a release decision.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

_HEX64 = re.compile(r"[0-9a-f]{64}")


class ReleaseGateError(ValueError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseGateError(f"unreadable JSON document: {path}") from exc


def check_database_freshness(database_built_iso: str | None, *,
                             max_age_hours: int = 120,
                             now: float | None = None) -> dict[str, Any]:
    """Diagnose Grype DB freshness (DBCheck evidence). Fail-closed on doubt.

    A missing or unparseable build timestamp, a future-dated DB, or a DB
    older than ``max_age_hours`` refuses the release. Freshness alone never
    approves: it is one conjunct of verify_release.
    """
    import time as _time
    from datetime import datetime, timezone
    if type(max_age_hours) is not int or not 1 <= max_age_hours <= 720:
        raise ReleaseGateError("max database age must be 1..720h")
    if not isinstance(database_built_iso, str) or not database_built_iso.strip():
        return {"fresh": False, "reason": "database build timestamp absent"}
    try:
        built = datetime.fromisoformat(database_built_iso.strip().replace("Z", "+00:00"))
    except ValueError:
        return {"fresh": False, "reason": "database build timestamp invalid"}
    if built.tzinfo is None:
        return {"fresh": False, "reason": "database build timestamp not timezone aware"}
    age_s = (_time.time() if now is None else float(now)) - built.timestamp()
    if age_s < 0:
        return {"fresh": False, "reason": "database build is future dated"}
    if age_s > max_age_hours * 3600:
        return {"fresh": False, "reason": "database obsolete",
                "age_hours": round(age_s / 3600, 2),
                "max_age_hours": max_age_hours}
    return {"fresh": True, "age_hours": round(age_s / 3600, 2),
            "max_age_hours": max_age_hours}


def fix_advice(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Split findings into fixable vs no-fix (Fix state evidence).

    Uses the recorded fix state/versions per finding (fixed/not-fixed/
    wont-fix/unknown). A fixable finding names fixed versions; anything
    else is reported without inventing an upgrade path.
    """
    fixable: list[dict[str, Any]] = []
    unfixable: list[dict[str, Any]] = []
    for finding in findings:
        state = str(finding.get("fix_state", "unknown")).lower()
        versions = finding.get("fixed_versions") or []
        entry = {"id": finding.get("id"), "package": finding.get("package"),
                 "installed_version": finding.get("installed_version"),
                 "fix_state": state,
                 "fixed_versions": list(versions)[:8]}
        if state == "fixed" and versions:
            fixable.append(entry)
        else:
            unfixable.append(entry)
    return {"fixable": fixable, "without_fix": unfixable,
            "fixable_count": len(fixable), "without_fix_count": len(unfixable)}


def diff_scan_receipts(previous: dict[str, Any],
                       current: dict[str, Any]) -> dict[str, Any]:
    """Diff two scan receipts by (id, package, installed_version)."""
    from .grype_scan import scan_diff
    for label, receipt in (("previous", previous), ("current", current)):
        if not isinstance(receipt, dict) or not isinstance(
                receipt.get("recommendations"), list):
            raise ReleaseGateError(f"{label} receipt lacks recommendations")
        if not isinstance(receipt.get("sbom_sha256"), str):
            raise ReleaseGateError(f"{label} receipt lacks sbom binding")
    return scan_diff(previous, current)


def verify_release(*, third_party_root: Path, trusted_pins: Path,
                   sbom: Path, expected_sbom_sha256: str,
                   scan_receipt: Path, fail_at: str = "high",
                   database_built: str | None = None,
                   max_database_age_hours: int = 120,
                   sbom_producer: str | None = None,
                   previous_receipt: Path | None = None) -> dict[str, Any]:
    if not isinstance(expected_sbom_sha256, str) or not _HEX64.fullmatch(expected_sbom_sha256):
        raise ReleaseGateError("invalid expected SBOM digest")
    if fail_at not in {"critical", "high", "medium", "low"}:
        raise ReleaseGateError("unsupported vulnerability threshold")

    from .source_gate import GateFailure, SourceGate
    from .grype_gate import VulnerabilityGateError, evaluate_grype_json

    try:
        gate = SourceGate(third_party_root, trusted_pins=trusted_pins)
        sources = gate.verify_all()
    except GateFailure as exc:
        raise ReleaseGateError("source provenance failed: " + str(exc)) from exc

    sbom_path = Path(sbom).resolve(strict=True)
    if not sbom_path.is_file():
        raise ReleaseGateError("SBOM artifact missing")
    digest = hashlib.sha256()
    try:
        with sbom_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ReleaseGateError("SBOM unreadable") from exc
    if digest.hexdigest() != expected_sbom_sha256:
        raise ReleaseGateError("SBOM digest mismatch")

    receipt = _load_json(scan_receipt)
    if not isinstance(receipt, dict):
        raise ReleaseGateError("scan receipt must be an object")
    if receipt.get("sbom_sha256") != expected_sbom_sha256:
        raise ReleaseGateError("scan receipt not bound to this SBOM")
    decision = receipt.get("decision") or {}
    report_sha = decision.get("report_sha256")
    if not isinstance(report_sha, str) or not _HEX64.fullmatch(report_sha):
        raise ReleaseGateError("scan receipt missing report digest")

    # The raw Grype JSON report must accompany the receipt for re-evaluation;
    # receipts alone are not trusted without the digest-bound report bytes.
    sibling_candidates = [
        Path(str(scan_receipt) + ".report.json"),
        Path(scan_receipt).with_suffix(""),
        Path(scan_receipt).parent / "grype-report.json",
    ]
    report_bytes: bytes | None = None
    embedded = receipt.get("report_sha256") or decision.get("report_sha256")
    _ = embedded
    for candidate in sibling_candidates:
        try:
            if candidate.is_file():
                data = candidate.read_bytes()
                if hashlib.sha256(data).hexdigest() == report_sha:
                    report_bytes = data
                    break
        except OSError:
            continue
    # Fallback: receipt may embed a bounded report copy.
    if report_bytes is None and isinstance(receipt.get("report"), str):
        try:
            data = receipt["report"].encode("utf-8")
            if hashlib.sha256(data).hexdigest() == report_sha:
                report_bytes = data
        except (ValueError, AttributeError):
            report_bytes = None
    if report_bytes is None:
        raise ReleaseGateError("digest-bound Grype report not available for re-evaluation")
    try:
        outcome = evaluate_grype_json(report_bytes, fail_at=fail_at,
                                      expected_sha256=report_sha,
                                      max_bytes=32_000_000)
    except VulnerabilityGateError as exc:
        raise ReleaseGateError("vulnerability gate failed: " + str(exc)) from exc

    findings = [asdict(f) for f in outcome.findings]
    freshness = check_database_freshness(
        receipt.get("database_built") or database_built,
        max_age_hours=max_database_age_hours)
    if not freshness["fresh"]:
        raise ReleaseGateError("grype database not fresh: " + freshness["reason"])
    advice = fix_advice([
        {"id": f.identifier, "package": f.package,
         "installed_version": f.version,
         "fix_state": next((r.get("fix_state", "unknown")
                            for r in receipt.get("recommendations", [])
                            if r.get("id") == f.identifier), "unknown"),
         "fixed_versions": next((r.get("fixed_versions", [])
                                 for r in receipt.get("recommendations", [])
                                 if r.get("id") == f.identifier), [])}
        for f in outcome.findings
    ])
    diff = None
    if previous_receipt is not None:
        diff = diff_scan_receipts(_load_json(previous_receipt), receipt)

    return {
        "approved": bool(outcome.allowed),
        "reason": outcome.reason,
        "sources_verified": [{"name": s.name, "revision": s.revision,
                              "tracked_files": s.tracked_files} for s in sources],
        "sbom_sha256": expected_sbom_sha256,
        "sbom_producer": (sbom_producer or receipt.get("sbom_producer"
                          ) or "unrecorded: scanning a checkout never equals "
                          "scanning the final installer artifact"),
        "report_sha256": outcome.report_sha256,
        "findings": findings,
        "fail_at": fail_at,
        "database_freshness": freshness,
        "fix_advice": advice,
        "receipt_diff": diff,
    }
