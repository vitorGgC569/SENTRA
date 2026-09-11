from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .models import TaskStatus, TaskPriority, Task


class Phase(str, Enum):
    ANALYZE = "ANALYZE"
    PLAN = "PLAN"
    DISPATCH = "DISPATCH"
    COLLECT = "COLLECT"
    CRITIQUE = "CRITIQUE"
    APPLY = "APPLY"
    VALIDATE = "VALIDATE"
    DONE = "DONE"
    FAILED = "FAILED"


# Valid state transitions for tasks as specified in Section 7 of OMA specification
VALID_TASK_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.VALIDATING, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.VALIDATING: {
        TaskStatus.READY,
        TaskStatus.QUALITY_GATE,
        TaskStatus.REJECTED,
        TaskStatus.DISPUTED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.REJECTED: {TaskStatus.REPAIRING, TaskStatus.ESCALATED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.REPAIRING: {TaskStatus.VALIDATING, TaskStatus.FAILED, TaskStatus.ESCALATED, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.QUALITY_GATE, TaskStatus.READY_FOR_MASTER, TaskStatus.CANCELLED},
    TaskStatus.DISPUTED: {TaskStatus.ESCALATED, TaskStatus.REPAIRING, TaskStatus.CANCELLED},
    TaskStatus.QUALITY_GATE: {TaskStatus.READY_FOR_MASTER, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.READY_FOR_MASTER: {TaskStatus.MASTER_REVIEW, TaskStatus.COMPLETED, TaskStatus.CANCELLED},
    TaskStatus.MASTER_REVIEW: {TaskStatus.COMPLETED, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.FAILED: {TaskStatus.RETRYING, TaskStatus.ESCALATED, TaskStatus.CANCELLED},
    TaskStatus.RETRYING: {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.ESCALATED: {TaskStatus.MASTER_REVIEW, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
}


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal task state transition is attempted."""
    pass


class TaskStateMachine:
    """
    Deterministic state machine for Task lifecycle.
    Enforces rules from Section 7 & 8 of OMA specification:
    'LLMs não devem ser responsáveis por controlar diretamente regras críticas do sistema.'
    """

    @staticmethod
    def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
        if current == target:
            return True
        allowed = VALID_TASK_TRANSITIONS.get(current, set())
        return target in allowed

    @staticmethod
    def transition(task: Task, target: TaskStatus, reason: str = "") -> Task:
        current = task.status
        if not TaskStateMachine.can_transition(current, target):
            raise InvalidStateTransitionError(
                f"Cannot transition task {task.id} from {current.value} to {target.value}. Allowed: {[s.value for s in VALID_TASK_TRANSITIONS.get(current, set())]}"
            )
        task.status = target
        if "transition_history" not in task.metadata:
            task.metadata["transition_history"] = []
        task.metadata["transition_history"].append({
            "from": current.value,
            "to": target.value,
            "reason": reason,
        })
        return task


@dataclass
class JobSpec:
    job_id: str
    entry_prompt: str
    acceptance_criteria: List[str] = field(default_factory=list)
    validation_commands: List[str] = field(default_factory=list)
    max_rounds: int = 20
    no_progress_limit: int = 3
    repeated_failure_limit: int = 3
    max_parallel_sessions: int = 3
    # OMA enhancements
    token_budget_master: int = 50000
    token_budget_secondary: int = 1000000
    max_repair_rounds: int = 4
    validators_required: int = 3
    minimum_approvals: int = 2
    critical_rejection_blocks: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "entry_prompt": self.entry_prompt,
            "acceptance_criteria": self.acceptance_criteria,
            "validation_commands": self.validation_commands,
            "max_rounds": self.max_rounds,
            "no_progress_limit": self.no_progress_limit,
            "repeated_failure_limit": self.repeated_failure_limit,
            "max_parallel_sessions": self.max_parallel_sessions,
            "token_budget_master": self.token_budget_master,
            "token_budget_secondary": self.token_budget_secondary,
            "max_repair_rounds": self.max_repair_rounds,
            "validators_required": self.validators_required,
            "minimum_approvals": self.minimum_approvals,
            "critical_rejection_blocks": self.critical_rejection_blocks,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JobSpec:
        clean = {k: v for k, v in data.items() if k in cls.__annotations__}
        return cls(**clean)


@dataclass
class JobState:
    phase: Phase = Phase.ANALYZE
    round_number: int = 0
    pending_tasks: List[Dict[str, Any]] = field(default_factory=list)
    completed_tasks: List[str] = field(default_factory=list)
    browser_results: List[Dict[str, Any]] = field(default_factory=list)
    accepted_results: List[Dict[str, Any]] = field(default_factory=list)
    failure_signatures: Dict[str, int] = field(default_factory=dict)
    no_progress_rounds: int = 0
    last_progress_hash: Optional[str] = None
    validation: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    # OMA additions
    run_id: str = ""
    tasks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    candidates: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tokens_master: int = 0
    tokens_secondary: int = 0

    def log(self, message: str) -> None:
        entry = f"[Round {self.round_number}][{self.phase.value}] {message}"
        self.logs.append(entry)
        print(entry, flush=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "round_number": self.round_number,
            "pending_tasks": self.pending_tasks,
            "completed_tasks": self.completed_tasks,
            "browser_results": self.browser_results,
            "accepted_results": self.accepted_results,
            "failure_signatures": self.failure_signatures,
            "no_progress_rounds": self.no_progress_rounds,
            "last_progress_hash": self.last_progress_hash,
            "validation": self.validation,
            "logs": self.logs[-200:],  # keep last 200 log entries
            "run_id": self.run_id,
            "tasks": self.tasks,
            "candidates": self.candidates,
            "tokens_master": self.tokens_master,
            "tokens_secondary": self.tokens_secondary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JobState:
        data_copy = dict(data)
        data_copy["phase"] = Phase(data_copy["phase"])
        clean = {k: v for k, v in data_copy.items() if k in cls.__annotations__}
        return cls(**clean)


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, state: JobState) -> None:
        payload = state.to_dict()
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self) -> Optional[JobState]:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return JobState.from_dict(payload)
        except Exception:
            return None


def stable_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()
