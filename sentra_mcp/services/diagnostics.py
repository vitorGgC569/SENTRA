"""Selo: Diagnostics + telemetry-export service facade."""
from __future__ import annotations


def build_client(**trusted_host_configuration):
    from .selo_composition import build_client as compose
    return compose(**trusted_host_configuration)

from pathlib import Path
from typing import Any

from sentra_quality.diagnostics import DiagnosticsReport
from sentra_quality.otel_langfuse import LangfuseConfig, SeloTelemetryExporter


class DiagnosticsService:
    def __init__(self, state_root: Path | str) -> None:
        self.root = Path(state_root).resolve()
        self.report = DiagnosticsReport(self.root)
        self.exporter = SeloTelemetryExporter(self.root)

    def snapshot(self, owner: str) -> dict[str, Any]:
        return self.report.build(owner)

    def telemetry_enqueue(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.exporter.enqueue(owner, **kwargs)

    def telemetry_stats(self, owner: str) -> dict[str, Any]:
        return self.exporter.stats(owner)

    def telemetry_flush_otlp(self, owner: str, *, endpoint: str,
                             limit: int = 32) -> dict[str, Any]:
        return self.exporter.flush_otlp(owner, endpoint=endpoint, limit=limit)

    def telemetry_flush_langfuse(self, owner: str, *, base_url: str,
                                 credential_provider,
                                 limit: int = 32) -> dict[str, Any]:
        return self.exporter.flush_langfuse(
            owner, config=LangfuseConfig(base_url=base_url),
            credential_provider=credential_provider, limit=limit)

    def pipeline_configure(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        from sentra_quality.otel_langfuse import OTelPipeline, OTelPipelineConfig
        return OTelPipeline(self.root).configure(owner, OTelPipelineConfig(**kwargs))

    def pipeline_stats(self, owner: str) -> dict[str, Any]:
        from sentra_quality.otel_langfuse import OTelPipeline
        return OTelPipeline(self.root).stats(owner)

    def pipeline_prune(self, owner: str) -> dict[str, Any]:
        from sentra_quality.otel_langfuse import OTelPipeline
        pipeline = OTelPipeline(self.root)
        return {"expired_pruned": pipeline.prune_expired(owner)}
