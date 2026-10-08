"""Append-only JSONL audit logging for SENTRA MCP."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from .errors import sanitize_error
from sentra_core.telemetry import EventJournal, redact

_SECRET_KEYS = {"authorization", "api_key", "apikey", "token", "password", "secret", "client_secret"}


def _secret_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_").replace(" ", "_")
    return normalized in _SECRET_KEYS


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _secret_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return sanitize_error(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_error(repr(value))


class AuditLogger:
    """Small synchronized JSONL writer with recursive secret redaction."""

    def __init__(self, path: Path, *, component: str = "mcp") -> None:
        self.path = Path(path)
        self._lock = Lock()
        self.component = component
        self.last_error = None
        self._journal = None

    def emit(
        self,
        action: str,
        outcome: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.last_error = None
            saved = False
            try:
                if self._journal is None:
                    self._journal = EventJournal(self.path.parent)
                info = dict(details or {})
                correlation = info.get("correlation_id") or info.get("turn_id") or info.get("run_id")
                record = self._journal.append(self.component,action,outcome,info,correlation_id=correlation)
                saved = True
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                self.last_error = "journal:" + type(exc).__name__
                import uuid
                record = {"event_id":uuid.uuid4().hex,"timestamp":datetime.now(timezone.utc).isoformat(),
                          "component":self.component,"action":sanitize_error(action),
                          "outcome":sanitize_error(outcome),"details":redact(dict(details or {}))}
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
            except OSError as exc:
                self.last_error = "jsonl:" + type(exc).__name__
                if not saved:
                    raise RuntimeError("operational audit could not be persisted") from exc
