"""Append-only JSONL audit logging for SENTRA MCP."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from .errors import sanitize_error

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

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def emit(
        self,
        action: str,
        outcome: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "outcome": outcome,
            "details": _redact(dict(details or {})),
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
