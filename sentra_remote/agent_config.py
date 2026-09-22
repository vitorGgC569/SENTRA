"""Local SENTRA Agent configuration with OS-protected device credentials."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .secrets import protect_secret, unprotect_secret


@dataclass(slots=True)
class AgentConfig:
    relay_url: str
    device_id: str
    device_token: str
    name: str
    allowed_roots: list[str]
    audit_log: str
    process_mode: str = "workspace"

    @classmethod
    def load(cls, path: Path) -> "AgentConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("agent config must be a JSON object")
        data["device_token"] = unprotect_secret(str(data.get("device_token", "")))
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["device_token"] = protect_secret(self.device_token)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
