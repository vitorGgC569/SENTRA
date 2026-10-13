"""Indexed telemetry shared across SENTRA components, with bounded legacy import."""
from __future__ import annotations

from pathlib import Path

from sentra_core.telemetry import EventJournal
from ..config import MCPConfig


class TelemetryService:
    def __init__(self, config: MCPConfig, *, selo_client=None) -> None:
        self.config = config
        self.path = Path(config.audit_log)
        self.journal = EventJournal(self.path.parent)
        self.selo_client = None
        if selo_client is not None:
            self.compose_selo(selo_client)

    def compose_selo(self, client):
        """Host-only injection of the concrete configured client, never a callable."""
        from .selo_composition import SeloHostFacade
        if not isinstance(client, SeloHostFacade):
            raise TypeError("real configured SeloHostFacade required")
        self.selo_client = client

    def _selo_owner(self, owner):
        if self.selo_client is not None and owner != self.selo_client.owner:
            raise PermissionError("telemetry owner differs from configured host")

    def _sync(self):
        return self.journal.import_jsonl(self.path)

    def usage_stats(self):
        imported=self._sync()
        return {**self.journal.stats(),"history_complete":imported["complete"],
                "legacy_pending_bytes":imported["pending_bytes"]}

    def recent_calls(self, limit=100, offset=0):
        if type(limit) is not int or not 1<=limit<=1000 or type(offset) is not int or offset<0:
            raise ValueError("offset must be >=0 and limit must be between 1 and 1000")
        imported=self._sync()
        result=self.journal.query(limit=limit,offset=offset)
        result["items"].reverse()
        result["history_complete"]=imported["complete"]
        result["legacy_pending_bytes"]=imported["pending_bytes"]
        return result

    def query(self, *, action="", outcome="", contains="", limit=200, offset=0,
              component="", correlation_id=""):
        imported=self._sync()
        result=self.journal.query(action=action,outcome=outcome,contains=contains,
            limit=limit,offset=offset,component=component,correlation_id=correlation_id)
        result["history_complete"]=imported["complete"]
        result["legacy_pending_bytes"]=imported["pending_bytes"]
        return result

    # Selo: sanitized OTel/Langfuse + diagnostics composition (fail-safe).
    def selo_enqueue(self, owner, *, name, state, operation_id):
        self._selo_owner(owner)
        if self.selo_client is not None:
            from sentra_runtime.otlp_sink import SafeTelemetryEvent
            return self.selo_client.enqueue(SafeTelemetryEvent(name, state, operation_id))
        from sentra_quality.otel_langfuse import SeloTelemetryExporter
        return SeloTelemetryExporter(self.path.parent).enqueue(
            owner, name=name, state=state, operation_id=operation_id)

    def selo_export_stats(self, owner):
        self._selo_owner(owner)
        if self.selo_client is not None:
            return self.selo_client.status()["telemetry"]
        from sentra_quality.otel_langfuse import SeloTelemetryExporter
        return SeloTelemetryExporter(self.path.parent).stats(owner)

    def selo_flush_otlp(self, owner, *, endpoint, limit=32):
        self._selo_owner(owner)
        if self.selo_client is not None:
            raise PermissionError("configured export requires await selo_dispatch with a central admitted intent")
        from sentra_quality.otel_langfuse import SeloTelemetryExporter
        return SeloTelemetryExporter(self.path.parent).flush_otlp(
            owner, endpoint=endpoint, limit=limit)

    def selo_diagnostics(self, owner):
        self._selo_owner(owner)
        if self.selo_client is not None:
            return {"sections": self.selo_client.status(), "audit_complete": False,
                    "authorizes_effects": False}
        from sentra_quality.diagnostics import DiagnosticsReport
        return DiagnosticsReport(self.path.parent).build(owner)

    async def selo_dispatch(self, owner, *, provider, action, arguments, request_key):
        self._selo_owner(owner)
        if self.selo_client is None:
            raise RuntimeError("configured Selo host not composed")
        return await self.selo_client.dispatch(provider, action, arguments, request_key=request_key)
