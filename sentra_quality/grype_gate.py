"""Fail-closed assessment for externally produced Grype JSON vulnerability reports.

Not a scanner or SBOM generator. It neither invokes untrusted binaries nor
fetches CVEs. A report provided by trusted CI must still be bound to a pinned
SBOM and vulnerability database before approving a product release.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

_ID = re.compile(r"^(?:CVE-[0-9]{4}-[0-9]{4,}|GHSA-[a-zA-Z0-9-]{11,})$")
_LEVEL = {"critical": 4, "high": 3, "medium": 2, "low": 1,
          "negligible": 0, "unknown": 5}


class VulnerabilityGateError(ValueError):
    """No reliable vulnerability admission conclusion could be reached."""


@dataclass(frozen=True, slots=True)
class VulnerabilityFinding:
    identifier: str
    severity: str
    package: str
    version: str


@dataclass(frozen=True, slots=True)
class ScanDecision:
    allowed: bool
    reason: str
    findings: tuple[VulnerabilityFinding, ...]
    report_sha256: str
    report_digest_verified: bool = False


def evaluate_grype_json(report: bytes, *, fail_at: str = "high",
                        expected_sha256: str | None = None,
                        max_bytes: int = 8_000_000) -> ScanDecision:
    """Assess Grype matches; reject unknown entries rather than treating as clean.

    An expected report digest proves only byte integrity, not scanner
    provenance, SBOM binding, database freshness or absence of hidden CVEs.
    """
    if not isinstance(report, bytes) or not 0 < len(report) <= max_bytes:
        raise VulnerabilityGateError("Grype report absent or exceeds size limit")
    if not isinstance(fail_at, str) or fail_at.lower() not in {
        "critical", "high", "medium", "low"
    }:
        raise VulnerabilityGateError("unsupported vulnerability threshold")
    digest = hashlib.sha256(report).hexdigest()
    if expected_sha256 is not None:
        if (not isinstance(expected_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
                or expected_sha256 != digest):
            raise VulnerabilityGateError("vulnerability report hash mismatch")
    def reject_constant(_value):
        raise VulnerabilityGateError("non-JSON numeric constant")

    def reject_duplicate(pairs):
        record = {}
        for key, value in pairs:
            if key in record:
                raise VulnerabilityGateError("duplicate JSON field")
            record[key] = value
        return record

    try:
        obj = json.loads(report.decode("utf-8"), parse_constant=reject_constant,
                         object_pairs_hook=reject_duplicate)
    except (ValueError, UnicodeError) as exc:
        raise VulnerabilityGateError("invalid Grype JSON") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("matches"), list):
        raise VulnerabilityGateError("missing Grype match list")
    if len(obj["matches"]) > 100_000:
        raise VulnerabilityGateError("too many vulnerabilities to inspect")
    findings: list[VulnerabilityFinding] = []
    for record in obj["matches"]:
        if not isinstance(record, dict):
            raise VulnerabilityGateError("invalid vulnerability match")
        vuln = record.get("vulnerability")
        artifact = record.get("artifact")
        if not isinstance(vuln, dict) or not isinstance(artifact, dict):
            raise VulnerabilityGateError("missing vulnerability or artifact")
        vid = vuln.get("id")
        sev = vuln.get("severity")
        package = artifact.get("name")
        version = artifact.get("version")
        if (not isinstance(vid, str) or not _ID.fullmatch(vid)
                or not isinstance(sev, str) or sev.lower() not in _LEVEL
                or not isinstance(package, str) or not 0 < len(package) <= 255
                or not isinstance(version, str) or not 0 < len(version) <= 255):
            raise VulnerabilityGateError("unreviewable vulnerability match")
        findings.append(VulnerabilityFinding(vid, sev.lower(), package, version))
    threshold = _LEVEL[fail_at.lower()]
    blocked = any(_LEVEL[f.severity] >= threshold for f in findings)
    return ScanDecision(
        allowed=not blocked,
        reason="blocking vulnerability in report" if blocked else
               "no blocking findings in supplied report",
        findings=tuple(findings),
        report_sha256=digest,
        report_digest_verified=expected_sha256 is not None,
    )
