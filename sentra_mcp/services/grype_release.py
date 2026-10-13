"""Selo: Grype release-gate service facade."""
from __future__ import annotations


def build_client(**trusted_host_configuration):
    from .selo_composition import build_client as compose
    return compose(**trusted_host_configuration)

from pathlib import Path
from typing import Any


class GrypeReleaseService:
    def decide(self, *, third_party_root: Path | str, trusted_pins: Path | str,
               sbom: Path | str, expected_sbom_sha256: str,
               scan_receipt: Path | str, fail_at: str = "high",
               database_built: str | None = None,
               max_database_age_hours: int = 120,
               sbom_producer: str | None = None,
               previous_receipt: Path | str | None = None) -> dict[str, Any]:
        from sentra_quality.release_gate import verify_release
        return verify_release(
            third_party_root=Path(third_party_root), trusted_pins=Path(trusted_pins),
            sbom=Path(sbom), expected_sbom_sha256=expected_sbom_sha256,
            scan_receipt=Path(scan_receipt), fail_at=fail_at,
            database_built=database_built,
            max_database_age_hours=max_database_age_hours,
            sbom_producer=sbom_producer,
            previous_receipt=Path(previous_receipt) if previous_receipt else None)

    def freshness(self, database_built: str | None, *,
                  max_age_hours: int = 120) -> dict[str, Any]:
        from sentra_quality.release_gate import check_database_freshness
        return check_database_freshness(database_built, max_age_hours=max_age_hours)

    def diff(self, previous: dict[str, Any],
             current: dict[str, Any]) -> dict[str, Any]:
        from sentra_quality.release_gate import diff_scan_receipts
        return diff_scan_receipts(previous, current)
