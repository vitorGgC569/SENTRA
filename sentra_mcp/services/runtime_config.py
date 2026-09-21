"""Runtime configuration with an offline approval boundary for privileged changes."""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any, Callable


SAFE_FIELDS = {
    "max_read_bytes": (1024, 256 * 1024 * 1024),
    "max_write_bytes": (1024, 256 * 1024 * 1024),
    "max_output_bytes": (1024, 64 * 1024 * 1024),
    "max_processes": (1, 64),
}
PRIVILEGED_FIELDS = {
    "allowed_roots",
    "blocked_commands",
    "host",
    "port",
    "allow_non_loopback",
}


class RuntimeConfigService:
    def __init__(
        self,
        get_effective: Callable[[], dict[str, Any]],
        apply_safe: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        state_path: Path,
    ) -> None:
        self.get_effective = get_effective
        self.apply_safe = apply_safe
        self.state_path = Path(state_path)

    def get_config(self) -> dict[str, Any]:
        effective = self.get_effective()
        effective["safe_runtime_fields"] = sorted(SAFE_FIELDS)
        effective["privileged_fields"] = sorted(PRIVILEGED_FIELDS)
        effective["approval_boundary"] = "local_cli_only"
        return effective

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"pending": {}, "approved": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"pending": {}, "approved": {}}
        if not isinstance(data, dict):
            return {"pending": {}, "approved": {}}
        data.setdefault("pending", {})
        data.setdefault("approved", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, dict) or not changes:
            raise ValueError("changes must be a non-empty object")
        unknown = set(changes) - SAFE_FIELDS.keys() - PRIVILEGED_FIELDS
        if unknown:
            raise ValueError("unknown config fields: " + ", ".join(sorted(unknown)))
        safe: dict[str, Any] = {}
        privileged: dict[str, Any] = {}
        for key, value in changes.items():
            if key in SAFE_FIELDS:
                lo, hi = SAFE_FIELDS[key]
                if not isinstance(value, int) or not lo <= value <= hi:
                    raise ValueError(f"{key} must be integer in range {lo}..{hi}")
                safe[key] = value
            else:
                privileged[key] = value
        result: dict[str, Any] = {"applied": {}, "approval_required": None}
        if safe:
            result["applied"] = self.apply_safe(safe)
        if privileged:
            request_id = secrets.token_urlsafe(12)
            data = self._load()
            data["pending"][request_id] = {
                "changes": privileged,
                "created": time.time(),
                "status": "PENDING",
            }
            self._save(data)
            result["approval_required"] = {
                "request_id": request_id,
                "changes": privileged,
                "command": f"python -m sentra_remote.admin approve-config {request_id}",
                "note": "Privileged changes are never approved through MCP.",
            }
        return result

    def list_pending(self) -> dict[str, Any]:
        return {"pending": self._load()["pending"]}

    def approve_local(self, request_id: str) -> dict[str, Any]:
        data = self._load()
        item = data["pending"].pop(request_id, None)
        if item is None:
            raise FileNotFoundError("pending config request not found")
        approved = {
            "changes": item["changes"],
            "approved": time.time(),
            "restart_required": True,
        }
        data["approved"].update(item["changes"])
        data.setdefault("history", []).append({"request_id": request_id, **approved})
        self._save(data)
        return approved

    def reject_local(self, request_id: str) -> dict[str, Any]:
        data = self._load()
        item = data["pending"].pop(request_id, None)
        if item is None:
            raise FileNotFoundError("pending config request not found")
        data.setdefault("history", []).append({
            "request_id": request_id,
            "changes": item["changes"],
            "rejected": time.time(),
        })
        self._save(data)
        return {"request_id": request_id, "status": "REJECTED"}

    def approved_overrides(self) -> dict[str, Any]:
        return dict(self._load().get("approved") or {})
