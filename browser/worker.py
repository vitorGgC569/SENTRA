"""BrowserWorker — 1 tab real = 1 worker lógico do OMA."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

WorkerState = Literal["IDLE", "BUSY", "WAITING_RESPONSE"]


@dataclass
class BrowserWorker:
    worker_id: str  # BROWSER_WORKER_01
    state: WorkerState = "IDLE"
    current_task_id: Optional[str] = None
    current_conversation_id: Optional[str] = None
    completed: int = 0
    failed: int = 0
