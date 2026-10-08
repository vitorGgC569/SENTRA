"""Indexed telemetry shared across SENTRA components, with bounded legacy import."""
from __future__ import annotations

from pathlib import Path

from sentra_core.telemetry import EventJournal
from ..config import MCPConfig


class TelemetryService:
    def __init__(self, config: MCPConfig) -> None:
        self.config = config
        self.path = Path(config.audit_log)
        self.journal = EventJournal(self.path.parent)

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
