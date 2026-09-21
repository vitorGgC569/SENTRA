"""Read-only SENTRA/OMA observability adapters."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from ..audit import AuditLogger
from ..config import MCPConfig

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
_SECRET_KEYS = {"authorization", "api_key", "apikey", "token", "password", "secret", "cookie", "client_secret"}


def _redact(value: Any, key: str | None = None) -> Any:
    normalized = (key or "").casefold().replace("-", "_")
    if normalized in _SECRET_KEYS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class OmaService:
    """Expose run evidence without exposing arbitrary runtime storage."""

    def __init__(self, config: MCPConfig, audit: AuditLogger) -> None:
        self.workspace = config.allowed_roots[0].resolve()
        self.runs_root = self.workspace / "runs"
        self.max_read_bytes = config.max_read_bytes
        self.audit = audit

    @staticmethod
    def _is_link(path: Path) -> bool:
        return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())

    def _validate_run_id(self, run_id: str) -> str:
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise ValueError("invalid run_id")
        return run_id

    def _run_dir(self, run_id: str, *, must_exist: bool = True) -> Path:
        run_id = self._validate_run_id(run_id)
        if self.runs_root.exists() and self._is_link(self.runs_root):
            raise PermissionError("run storage may not be a filesystem link")
        run_dir = self.runs_root / run_id
        if self._is_link(run_dir):
            raise PermissionError("run directory may not be a filesystem link")
        if must_exist and not run_dir.is_dir():
            raise FileNotFoundError("run not found")
        return run_dir

    def _safe_file(self, run_id: str, name: str) -> Path:
        if name not in {"run.json", "handoff.json", "handoff.md", "events.jsonl", "tasks.json", "metrics.json"}:
            raise PermissionError("run artifact is not allowlisted")
        path = self._run_dir(run_id) / name
        if self._is_link(path):
            raise PermissionError("run artifact may not be a filesystem link")
        if path.exists() and path.is_file() and path.stat().st_nlink > 1:
            raise PermissionError("hard-linked run artifact blocked")
        return path

    def _read_bytes(self, path: Path) -> bytes:
        if not path.is_file():
            raise FileNotFoundError(f"{path.name} not found")
        size = path.stat().st_size
        if size > self.max_read_bytes:
            raise ValueError("run artifact exceeds configured read limit")
        data = path.read_bytes()
        if len(data) > self.max_read_bytes:
            raise ValueError("run artifact exceeds configured read limit")
        return data

    def _read_json(self, run_id: str, name: str) -> Any:
        raw = self._read_bytes(self._safe_file(run_id, name))
        return _redact(json.loads(raw.decode("utf-8-sig")))

    def health(self) -> dict[str, Any]:
        runs = 0
        if self.runs_root.is_dir() and not self._is_link(self.runs_root):
            for item in self.runs_root.iterdir():
                if item.is_dir() and not self._is_link(item) and _RUN_ID.fullmatch(item.name):
                    runs += 1
        return {
            "status": "ok",
            "workspace": str(self.workspace),
            "workspace_exists": self.workspace.is_dir(),
            "runs_available": runs,
            "python": sys.version.split()[0],
            "mutation_policy": "explicit external action required",
            "automatic_promotion": False,
            "arbitrary_oma_access": False,
        }

    def list_runs(self, limit: int = 100) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if not self.runs_root.exists():
            return {"runs": [], "limit": limit}
        if self._is_link(self.runs_root):
            raise PermissionError("run storage may not be a filesystem link")
        candidates = [
            item for item in self.runs_root.iterdir()
            if item.is_dir() and not self._is_link(item) and _RUN_ID.fullmatch(item.name)
        ]
        candidates.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
        rows: list[dict[str, Any]] = []
        for run_dir in candidates[:limit]:
            row: dict[str, Any] = {"run_id": run_dir.name}
            for name in ("handoff.json", "run.json"):
                try:
                    data = self._read_json(run_dir.name, name)
                except (FileNotFoundError, ValueError, json.JSONDecodeError, PermissionError):
                    continue
                if isinstance(data, dict):
                    row["status"] = data.get("status")
                    row["objective"] = data.get("objective")
                    break
            rows.append(row)
        return {"runs": rows, "limit": limit}

    def run_status(self, run_id: str) -> dict[str, Any]:
        for name in ("handoff.json", "run.json"):
            try:
                data = self._read_json(run_id, name)
            except FileNotFoundError:
                continue
            if not isinstance(data, dict):
                raise ValueError(f"{name} must contain a JSON object")
            return {"run_id": run_id, "source": name, "status": data}
        raise FileNotFoundError("run status not found")

    def read_events(self, run_id: str, offset: int = 0, length: int = 100) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= length <= 500:
            raise ValueError("length must be between 1 and 500")
        path = self._safe_file(run_id, "events.jsonl")
        raw = self._read_bytes(path)
        text = raw.decode("utf-8-sig")
        lines = text.splitlines()
        selected = lines[offset : offset + length]
        events: list[Any] = []
        for line in selected:
            try:
                events.append(_redact(json.loads(line)))
            except json.JSONDecodeError:
                events.append({"malformed": True})
        return {
            "run_id": run_id,
            "offset": offset,
            "returned": len(events),
            "total": len(lines),
            "more": offset + len(events) < len(lines),
            "events": events,
        }

    def read_handoff(self, run_id: str) -> dict[str, Any]:
        try:
            data = self._read_json(run_id, "handoff.json")
            return {"run_id": run_id, "format": "json", "handoff": data}
        except FileNotFoundError:
            path = self._safe_file(run_id, "handoff.md")
            text = self._read_bytes(path).decode("utf-8-sig")
            return {"run_id": run_id, "format": "markdown", "handoff": text}

    def queue_status(self) -> dict[str, Any]:
        from orchestrator.master_queue import MasterQueue

        result = MasterQueue(self.workspace).status()
        return {"queue": _redact(result)}

    def reconcile_status(self, run_id: str) -> dict[str, Any]:
        from orchestrator.reconcile import blocked_seats

        run_dir = self._run_dir(run_id)
        return {"run_id": run_id, "blocked_seats": _redact(blocked_seats(run_dir))}
