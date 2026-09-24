"""Wire/data models for SENTRA Commander remote operation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "UNCERTAIN", "CANCELLED"})
PRE_EXEC_PHASES = frozenset({"leased", "preparing", "ready"})
EXEC_PHASES = frozenset({"executing", "uploading", "finalizing"})


@dataclass(frozen=True, slots=True)
class PairedDevice:
    device_id: str
    user_id: str
    name: str
    platform: str
    allowed_tools: tuple[str, ...]
    status: str
    last_seen: float
    token_expires: float


@dataclass(frozen=True, slots=True)
class LeasedRemoteJob:
    job_id: str
    tool: str
    arguments: dict[str, Any]
    lease_token: str
    deadline: float
