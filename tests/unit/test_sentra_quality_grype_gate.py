"""Offline fixture-based Grype report parser tests; no Grype CLI claimed."""
from __future__ import annotations

import hashlib
import json

import pytest

from sentra_quality.grype_gate import (
    VulnerabilityGateError, evaluate_grype_json,
)


def payload(*, severity="high", vid="CVE-2026-12345", name="lib",
            version="1.0"):
    return json.dumps({
        "matches": [{
            "vulnerability": {"id": vid, "severity": severity},
            "artifact": {"name": name, "version": version},
        }]
    }).encode("utf-8")


def test_high_blocks_and_low_is_allowed_with_default_threshold():
    high = evaluate_grype_json(payload())
    assert not high.allowed
    assert high.findings[0].identifier == "CVE-2026-12345"
    low = evaluate_grype_json(payload(severity="low"))
    assert low.allowed
    assert low.report_digest_verified is False


def test_critical_blocks_even_at_high_threshold():
    result = evaluate_grype_json(payload(severity="critical"), fail_at="high")
    assert result.allowed is False


def test_medium_can_block_in_stricter_policy():
    result = evaluate_grype_json(payload(severity="medium"), fail_at="medium")
    assert result.allowed is False


def test_unknown_severity_never_treated_as_safe():
    assert evaluate_grype_json(payload(severity="unknown")).allowed is False


def test_report_digest_pin_does_not_imply_scanner_provenance():
    report = payload(severity="low")
    digest = hashlib.sha256(report).hexdigest()
    result = evaluate_grype_json(report, expected_sha256=digest)
    assert result.allowed
    assert result.report_digest_verified
    with pytest.raises(VulnerabilityGateError, match="hash mismatch"):
        evaluate_grype_json(report, expected_sha256="0" * 64)


def test_empty_matches_are_not_scanner_attestation():
    result = evaluate_grype_json(b'{"matches":[]}')
    assert result.allowed and result.findings == ()
    assert result.report_digest_verified is False


@pytest.mark.parametrize("invalid", [
    b"", b"not-json", b"[]", b"{}", b'{"matches":{}}',
    b'{"matches":[null]}',
    b'{"matches":[{"vulnerability":{},"artifact":{}}]}',
    b'{"matches":[{"vulnerability":{"id":"BOGUS","severity":"low"},"artifact":{"name":"pkg","version":"1"}}]}',
    b'{"matches":[{"vulnerability":{"id":"CVE-2026-12345","severity":"mystery"},"artifact":{"name":"pkg","version":"1"}}]}',
])
def test_malformed_json_fail_closed(invalid):
    with pytest.raises(VulnerabilityGateError):
        evaluate_grype_json(invalid)


def test_threshold_invalid():
    with pytest.raises(VulnerabilityGateError):
        evaluate_grype_json(payload(), fail_at="ignore-all")


def test_report_size_limit():
    with pytest.raises(VulnerabilityGateError, match="size"):
        evaluate_grype_json(payload(), max_bytes=3)


def test_duplicate_json_keys_and_nan_denied():
    with pytest.raises(VulnerabilityGateError):
        evaluate_grype_json(b'{"matches":[],"matches":[]}')
    with pytest.raises(VulnerabilityGateError):
        evaluate_grype_json(b'{"matches":[],"meta":NaN}')


def test_pinned_cli_result_exit_statuses(tmp_path):
    import subprocess
    import sys
    for severity, expected_exit in (("low", 0), ("critical", 3)):
        report = payload(severity=severity)
        file = tmp_path / "grype.json"
        file.write_bytes(report)
        pinned = hashlib.sha256(report).hexdigest()
        result = subprocess.run([
            sys.executable, "-B", "-m", "sentra_quality",
            "grype-check", "--report", str(file),
            "--sha256", pinned, "--fail-at", "high",
        ], capture_output=True, text=True, timeout=10, check=False)
        assert result.returncode == expected_exit, result.stderr
        body = json.loads(result.stdout)
        assert body["ok"] is (expected_exit == 0)
        assert body["digest_verified"]


def test_grype_cli_rejects_tampered_report(tmp_path):
    import subprocess
    import sys
    report = tmp_path / "grype.json"
    report.write_bytes(payload(severity="low"))
    bad = subprocess.run([
        sys.executable, "-B", "-m", "sentra_quality", "grype-check",
        "--report", str(report), "--sha256", "0" * 64,
    ], capture_output=True, text=True, timeout=10, check=False)
    assert bad.returncode == 2
    assert "mismatch" in bad.stderr
