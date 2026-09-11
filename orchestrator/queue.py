from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Set

from .models import Task, TaskPriority, TaskStatus
from .state_machine import TaskStateMachine
from .anti_explosion import AntiExplosionGuard, AntiExplosionError


PRIORITY_WEIGHTS = {
    TaskPriority.CRITICAL: 4,
    TaskPriority.HIGH: 3,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 1,
}


class PriorityTaskQueue:
    """
    Deterministic Priority Task Queue with DAG dependency resolution,
    backpressure support, and Dead-Letter Queue (DLQ).
    """

    def __init__(self, anti_explosion: Optional[AntiExplosionGuard] = None):
        self.anti_explosion = anti_explosion or AntiExplosionGuard()
        self._lock = asyncio.Lock()
        self._all_tasks: Dict[str, Task] = {}
        self._ready_queue: List[str] = []
        self._blocked_tasks: Dict[str, Set[str]] = {}  # task_id -> set of unfulfilled dep_ids
        self._running_tasks: Dict[str, Task] = {}
        self._completed_tasks: Dict[str, Task] = {}
        self._dlq: List[Dict[str, Any]] = []

    def _sort_ready_queue(self) -> None:
        def sort_key(task_id: str):
            task = self._all_tasks[task_id]
            weight = PRIORITY_WEIGHTS.get(task.priority, 2)
            # higher weight first, earlier creation time first
            return (-weight, task.created_at)

        self._ready_queue.sort(key=sort_key)

    async def add_task(self, task: Task, parent_id: Optional[str] = None) -> bool:
        async with self._lock:
            # Enforce anti-explosion limits
            try:
                self.anti_explosion.register_task(task, parent_id)
            except AntiExplosionError as e:
                print(f"[PriorityQueue] Task rejected by anti-explosion guard: {e}")
                return False

            self._all_tasks[task.id] = task

            # Check dependencies
            unfulfilled = set()
            for dep_id in task.dependencies:
                if dep_id not in self._completed_tasks:
                    unfulfilled.add(dep_id)

            if not unfulfilled:
                TaskStateMachine.transition(task, TaskStatus.QUEUED, reason="All dependencies satisfied")
                self._ready_queue.append(task.id)
                self._sort_ready_queue()
            else:
                self._blocked_tasks[task.id] = unfulfilled
                task.status = TaskStatus.PENDING

            return True

    async def pop_ready_task(self) -> Optional[Task]:
        async with self._lock:
            if not self._ready_queue:
                return None
            task_id = self._ready_queue.pop(0)
            task = self._all_tasks[task_id]
            TaskStateMachine.transition(task, TaskStatus.RUNNING, reason="Dispatched to worker")
            self._running_tasks[task.id] = task
            return task

    async def mark_completed(self, task_id: str) -> None:
        async with self._lock:
            task = self._all_tasks.get(task_id)
            if not task:
                return

            self._running_tasks.pop(task_id, None)
            TaskStateMachine.transition(task, TaskStatus.COMPLETED, reason="Task finished successfully")
            self._completed_tasks[task_id] = task

            # Check newly unblocked tasks
            newly_ready = []
            for blocked_id, deps in list(self._blocked_tasks.items()):
                deps.discard(task_id)
                if not deps:
                    newly_ready.append(blocked_id)
                    del self._blocked_tasks[blocked_id]

            for ready_id in newly_ready:
                ready_task = self._all_tasks[ready_id]
                TaskStateMachine.transition(ready_task, TaskStatus.QUEUED, reason="All dependencies completed")
                self._ready_queue.append(ready_id)

            if newly_ready:
                self._sort_ready_queue()

    async def mark_failed(
        self,
        task_id: str,
        error_msg: str,
        retryable: bool = True,
    ) -> bool:
        """
        Handles task failure. If retries remain and retryable, re-enqueues.
        Otherwise moves to Dead Letter Queue (DLQ).
        Returns True if re-queued for retry, False if permanently failed.
        """
        async with self._lock:
            task = self._all_tasks.get(task_id)
            if not task:
                return False

            self._running_tasks.pop(task_id, None)
            task.retry_count += 1

            if retryable and task.retry_count <= task.max_retries:
                TaskStateMachine.transition(task, TaskStatus.FAILED, reason=error_msg)
                TaskStateMachine.transition(task, TaskStatus.RETRYING, reason=f"Attempt {task.retry_count}/{task.max_retries}")
                TaskStateMachine.transition(task, TaskStatus.QUEUED, reason="Re-queued for retry")
                self._ready_queue.append(task.id)
                self._sort_ready_queue()
                return True
            else:
                TaskStateMachine.transition(task, TaskStatus.FAILED, reason=f"Max retries exceeded: {error_msg}")
                self._dlq.append({
                    "task_id": task.id,
                    "task": task.to_dict(),
                    "error": error_msg,
                    "attempts": task.retry_count,
                    "timestamp": time.time(),
                })
                return False

    async def mark_escalated(self, task_id: str, reason: str = "") -> None:
        async with self._lock:
            task = self._all_tasks.get(task_id)
            if task:
                self._running_tasks.pop(task_id, None)
                TaskStateMachine.transition(task, TaskStatus.ESCALATED, reason=reason)

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._all_tasks.get(task_id)

    def has_pending_work(self) -> bool:
        return bool(self._ready_queue or self._running_tasks or self._blocked_tasks)

    @property
    def ready_count(self) -> int:
        return len(self._ready_queue)

    @property
    def running_count(self) -> int:
        return len(self._running_tasks)

    @property
    def blocked_count(self) -> int:
        return len(self._blocked_tasks)

    @property
    def completed_count(self) -> int:
        return len(self._completed_tasks)

    @property
    def dlq_count(self) -> int:
        return len(self._dlq)

    def get_dlq(self) -> List[Dict[str, Any]]:
        return list(self._dlq)
