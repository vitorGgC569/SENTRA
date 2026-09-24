"""Read-only telemetry over SENTRA MCP audit JSONL."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..config import MCPConfig


class TelemetryService:
    def __init__(self, config: MCPConfig) -> None:
        self.config = config
        self.path = Path(config.audit_log)

    def _records(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        if limit is not None:
            lines = lines[-limit:]
        out: list[dict[str, Any]] = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def usage_stats(self) -> dict[str, Any]:
        records = self._records()
        by_action = Counter(str(r.get("action", "unknown")) for r in records)
        by_outcome = Counter(str(r.get("outcome", "unknown")) for r in records)
        security_denials = sum(
            1 for r in records
            if str(r.get("outcome", "")).lower() not in {"ok", "success"}
            or any(word in str(r.get("action", "")).lower() for word in ("denied", "forbidden", "blocked"))
        )
        read_bytes = 0
        write_bytes = 0
        process_started = 0
        process_ended = 0
        for record in records:
            details = record.get("details") or {}
            action = str(record.get("action", ""))
            if "read" in action:
                read_bytes += int(details.get("bytes", 0) or 0)
            if "write" in action or "edit" in action:
                write_bytes += int(details.get("bytes", details.get("stdin_bytes", 0)) or 0)
            if action == "process.start":
                process_started += 1
            if action in {"process.kill", "process.terminate", "process.cleanup", "process.timeout"}:
                process_ended += 1
        return {
            "calls_total": len(records),
            "by_action": dict(sorted(by_action.items())),
            "by_outcome": dict(sorted(by_outcome.items())),
            "bytes_read_observed": read_bytes,
            "bytes_written_observed": write_bytes,
            "processes_started": process_started,
            "process_end_events": process_ended,
            "security_denials": security_denials,
        }

    def recent_calls(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset must be >=0 and limit must be between 1 and 1000")
        records = self._records()
        total = len(records)
        end = max(0, total - offset)
        start = max(0, end - limit)
        items = records[start:end]
        next_offset = offset + len(items)
        return {
            "items": items,
            "records": items,
            "page": {
                "offset": offset,
                "limit": limit,
                "returned": len(items),
                "total": total,
                "next_offset": next_offset if start > 0 else None,
            },
        }

    def query(
        self,
        *,
        action: str = "",
        outcome: str = "",
        contains: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 5000:
            raise ValueError("offset must be >=0 and limit must be between 1 and 5000")
        records = self._records()
        filtered: list[dict[str, Any]] = []
        for record in reversed(records):
            if action and action.casefold() not in str(record.get("action", "")).casefold():
                continue
            if outcome and outcome.casefold() != str(record.get("outcome", "")).casefold():
                continue
            if contains and contains.casefold() not in json.dumps(record, ensure_ascii=False).casefold():
                continue
            filtered.append(record)
        total = len(filtered)
        items = filtered[offset: offset + limit]
        next_offset = offset + len(items)
        return {
            "items": items,
            "records": items,
            "page": {
                "offset": offset,
                "limit": limit,
                "returned": len(items),
                "total": total,
                "next_offset": next_offset if next_offset < total else None,
            },
        }
