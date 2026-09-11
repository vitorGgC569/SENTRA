from __future__ import annotations

import asyncio
import datetime
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set


class EventType(str, Enum):
    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"

    TASK_CREATED = "TASK_CREATED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_ESCALATED = "TASK_ESCALATED"
    TASK_CANCELLED = "TASK_CANCELLED"

    CANDIDATE_CREATED = "CANDIDATE_CREATED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"

    VALIDATION_REQUESTED = "VALIDATION_REQUESTED"
    VALIDATION_COMPLETED = "VALIDATION_COMPLETED"

    REPAIR_REQUESTED = "REPAIR_REQUESTED"
    REPAIR_COMPLETED = "REPAIR_COMPLETED"

    QUALITY_GATE_PASSED = "QUALITY_GATE_PASSED"
    QUALITY_GATE_FAILED = "QUALITY_GATE_FAILED"

    READY_FOR_MASTER = "READY_FOR_MASTER"
    MASTER_REVIEW_STARTED = "MASTER_REVIEW_STARTED"
    MASTER_REVIEW_COMPLETED = "MASTER_REVIEW_COMPLETED"


@dataclass
class EventEnvelope:
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:8]}")
    event_type: EventType = EventType.TASK_CREATED
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    correlation_id: str = ""  # run_id
    task_id: Optional[str] = None
    candidate_id: Optional[str] = None
    producer: str = "orchestrator"
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else str(self.event_type),
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "task_id": self.task_id,
            "candidate_id": self.candidate_id,
            "producer": self.producer,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EventEnvelope:
        data_copy = dict(data)
        if "event_type" in data_copy and isinstance(data_copy["event_type"], str):
            try:
                data_copy["event_type"] = EventType(data_copy["event_type"])
            except ValueError:
                pass
        return cls(**{k: v for k, v in data_copy.items() if k in cls.__annotations__})


EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class EventBus:
    """
    Event Bus for asynchronous, decoupled communication and telemetry
    as specified in Sections 27-29 of OMA.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._history: List[EventEnvelope] = []
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str | EventType, handler: EventHandler) -> None:
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        if key not in self._subscribers:
            self._subscribers[key] = []
        self._subscribers[key].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        self.subscribe("*", handler)

    async def publish(self, event: EventEnvelope) -> None:
        async with self._lock:
            self._history.append(event)

        key = event.event_type.value if isinstance(event.event_type, EventType) else str(event.event_type)
        handlers = list(self._subscribers.get(key, [])) + list(self._subscribers.get("*", []))

        for handler in handlers:
            try:
                res = handler(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                # Event dispatch errors should not crash the core engine
                print(f"[EventBus] Error dispatching event {key}: {e}", flush=True)

    def get_history(self, correlation_id: Optional[str] = None) -> List[EventEnvelope]:
        if correlation_id:
            return [e for e in self._history if e.correlation_id == correlation_id]
        return list(self._history)

    def clear(self) -> None:
        self._history.clear()
