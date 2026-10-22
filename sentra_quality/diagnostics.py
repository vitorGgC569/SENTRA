"""Selo: safe diagnostics report (redacted, bounded, never authoritative)."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _safe(value: Any, limit: int = 2000) -> Any:
    try:
        from sentra_core.telemetry import redact
        return redact(value if isinstance(value, dict) else {"value": value})
    except Exception:
        text = str(value).replace("\r", " ").replace("\n", " ")
        return text[:limit]


class DiagnosticsReport:
    """Compose a redacted health snapshot from Selo-owned stores only."""

    def __init__(self, state_root: Path | str) -> None:
        self.root = Path(state_root).resolve()

    def build(self, owner: str) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("owner is required")
        snapshot: dict[str, Any] = {"owner": owner, "sections": {}}
        try:
            from sentra_core.telemetry import EventJournal
            journal = EventJournal(self.root)
            snapshot["sections"]["telemetry"] = _safe(journal.stats())
        except Exception as exc:
            snapshot["sections"]["telemetry"] = {"unavailable": str(exc)[:200]}
        try:
            from memory.costs import CostLedger
            ledger = CostLedger(self.root)
            snapshot["sections"]["costs"] = _safe(ledger.totals(owner))
        except Exception as exc:
            snapshot["sections"]["costs"] = {"unavailable": str(exc)[:200]}
        try:
            from sentra_quality.otel_langfuse import SeloTelemetryExporter
            exporter = SeloTelemetryExporter(self.root)
            snapshot["sections"]["telemetry_export"] = _safe(exporter.stats(owner))
        except Exception as exc:
            snapshot["sections"]["telemetry_export"] = {"unavailable": str(exc)[:200]}
        try:
            from sentra_quality.audit_anchor import AuditAnchorStore
            store = AuditAnchorStore(self.root)
            snapshot["sections"]["audit_divergences"] = _safe(
                store.divergences(owner, limit=20))
        except Exception as exc:
            snapshot["sections"]["audit_divergences"] = {"unavailable": str(exc)[:200]}
        try:
            from sentra_quality.identity_registry import IdentityRegistry
            registry = IdentityRegistry(self.root)
            snapshot["sections"]["identity"] = {"note": "session listing withheld; use session_status per id"}
        except Exception as exc:
            snapshot["sections"]["identity"] = {"unavailable": str(exc)[:200]}
        try:
            from sentra_quality.learning_review import ReviewedLearningStore
            learning_store = ReviewedLearningStore(self.root)
            counts: dict[str, int] = {}
            for status in ("PROPOSED", "APPROVED", "REJECTED", "WITHDRAWN"):
                try:
                    counts[status.lower()] = learning_store.list(owner, status=status,
                                                       limit=1)["total"]
                except Exception:
                    counts[status.lower()] = -1
            snapshot["sections"]["learning"] = _safe({"suggestions": counts})
        except Exception as exc:
            snapshot["sections"]["learning"] = {"unavailable": str(exc)[:200]}
        try:
            from sentra_quality.otel_langfuse import OTelPipeline
            snapshot["sections"]["otel_pipeline"] = _safe(
                OTelPipeline(self.root).stats(owner))
        except Exception as exc:
            snapshot["sections"]["otel_pipeline"] = {"unavailable": str(exc)[:200]}
        snapshot["audit_complete"] = False
        snapshot["authorizes_effects"] = False
        return snapshot
