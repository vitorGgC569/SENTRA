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


class QueueFullError(RuntimeError):
    """Raised when a bounded queue rejects a task due to backpressure (Section 49)."""


class PriorityTaskQueue:
    """
    Deterministic Priority Task Queue with DAG dependency resolution,
    bounded backpressure, cancellation, and Dead-Letter Queue (DLQ).
    """

    def __init__(
        self,
        anti_explosion: Optional[AntiExplosionGuard] = None,
        max_queue_size: int = 10000,
    ):
        self.anti_explosion = anti_explosion or AntiExplosionGuard()
        self.max_queue_size = max_queue_size
        self._lock = asyncio.Lock()
        self._all_tasks: Dict[str, Task] = {}
        self._ready_queue: List[str] = []
        self._blocked_tasks: Dict[str, Set[str]] = {}  # task_id -> set of unfulfilled dep_ids
        self._running_tasks: Dict[str, Task] = {}
        self._completed_tasks: Dict[str, Task] = {}
        self._cancelled_tasks: Dict[str, Task] = {}
        self._failed_tasks: Dict[str, Task] = {}
        self._dlq: List[Dict[str, Any]] = []
        self.dropped_due_to_backpressure: int = 0

    def _sort_ready_queue(self) -> None:
        def sort_key(task_id: str):
            task = self._all_tasks[task_id]
            weight = PRIORITY_WEIGHTS.get(task.priority, 2)
            # higher weight first, earlier creation time first
            return (-weight, task.created_at)

        self._ready_queue.sort(key=sort_key)

    def queue_size(self) -> int:
        return len(self._ready_queue) + len(self._running_tasks) + len(self._blocked_tasks)

    async def add_task(
        self, task: Task, parent_id: Optional[str] = None, block_on_backpressure: bool = False
    ) -> bool:
        # Backpressure (Section 49): bounded queue. By default reject fast with
        # QueueFullError accounting; callers may opt into bounded waiting.
        if self.queue_size() >= self.max_queue_size and task.id not in self._all_tasks:
            if not block_on_backpressure:
                self.dropped_due_to_backpressure += 1
                raise QueueFullError(
                    f"Queue saturated ({self.queue_size()}/{self.max_queue_size}); "
                    f"task {task.id} rejected by backpressure policy"
                )
        if block_on_backpressure:
            while self.queue_size() >= self.max_queue_size and task.id not in self._all_tasks:
                await asyncio.sleep(0.05)
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
                self._failed_tasks[task.id] = task
                self._fail_dependents_locked(task.id, f"dependency {task.id} failed permanently")
                return False

    def _fail_dependents_locked(self, terminal_task_id: str, reason: str) -> List[str]:
        """Release tasks blocked on a terminal task as FAILED (cascade to fixpoint).

        Isolation: only tasks blocked (directly or transitively) on the terminal
        task fail here with DEPENDENCY_ERROR. Ready siblings without a
        dependency path to the failure are never touched; the run continues.

        Must be called with the queue lock held. A run must never deadlock on
        dependents of ESCALATED/FAILED/CANCELLED tasks.
        """
        failed_now: List[str] = []
        changed = True
        while changed:
            changed = False
            for blocked_id, deps in list(self._blocked_tasks.items()):
                if terminal_task_id not in deps and not any(
                    self._all_tasks.get(d) is not None and self._all_tasks[d].status in (
                        TaskStatus.FAILED, TaskStatus.ESCALATED, TaskStatus.CANCELLED)
                    for d in deps
                ):
                    continue
                blocked = self._all_tasks.get(blocked_id)
                if blocked is None:
                    del self._blocked_tasks[blocked_id]
                    changed = True
                    continue
                del self._blocked_tasks[blocked_id]
                try:
                    TaskStateMachine.transition(blocked, TaskStatus.FAILED, reason=reason)
                except Exception:
                    blocked.status = TaskStatus.FAILED
                self._failed_tasks[blocked_id] = blocked
                self._dlq.append({
                    "task_id": blocked_id,
                    "task": blocked.to_dict(),
                    "error": f"[DEPENDENCY_ERROR] {reason}",
                    "attempts": blocked.retry_count,
                    "timestamp": time.time(),
                })
                failed_now.append(blocked_id)
                changed = True
        return failed_now

    async def fail_unfulfillable_blocked(self) -> List[str]:
        """Fail blocked tasks whose deps are unknown or terminal. Run-loop guard."""
        async with self._lock:
            out: List[str] = []
            for blocked_id, deps in list(self._blocked_tasks.items()):
                unfulfillable = True
                for d in deps:
                    dep = self._all_tasks.get(d)
                    if dep is None:
                        continue  # unknown dep -> unfulfillable
                    if dep.status not in (TaskStatus.FAILED, TaskStatus.ESCALATED, TaskStatus.CANCELLED):
                        unfulfillable = False
                        break
                if unfulfillable:
                    out += self._fail_dependents_locked(blocked_id, "unfulfillable dependencies")
                    # _fail_dependents_locked keys off terminal statuses; force this one too
                    if blocked_id in self._blocked_tasks:
                        blocked = self._all_tasks.get(blocked_id)
                        del self._blocked_tasks[blocked_id]
                        if blocked is not None:
                            try:
                                TaskStateMachine.transition(blocked, TaskStatus.FAILED,
                                                            reason="unfulfillable dependencies")
                            except Exception:
                                blocked.status = TaskStatus.FAILED
                            self._failed_tasks[blocked_id] = blocked
                            out.append(blocked_id)
            return out

    async def mark_escalated(self, task_id: str, reason: str = "") -> None:
        from .state_machine import InvalidStateTransitionError
        async with self._lock:
            task = self._all_tasks.get(task_id)
            if task:
                self._running_tasks.pop(task_id, None)
                if task_id in self._ready_queue:
                    self._ready_queue.remove(task_id)
                self._blocked_tasks.pop(task_id, None)
                try:
                    TaskStateMachine.transition(task, TaskStatus.ESCALATED, reason=reason)
                except InvalidStateTransitionError:
                    # Escalation from states like RUNNING routes via FAILED first,
                    # preserving the strict machine + a full audit trail.
                    TaskStateMachine.transition(task, TaskStatus.FAILED,
                                                reason=f"escalating: {reason}")
                    TaskStateMachine.transition(task, TaskStatus.ESCALATED, reason=reason)
                self._fail_dependents_locked(task_id, f"dependency {task_id} escalated")

    async def mark_cancelled(self, task_id: str, reason: str = "cancel requested") -> bool:
        """RF-017: cancel a queued/running/blocked task. No retry afterwards."""
        async with self._lock:
            task = self._all_tasks.get(task_id)
            if not task:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                return False
            self._running_tasks.pop(task_id, None)
            if task_id in self._ready_queue:
                self._ready_queue.remove(task_id)
            self._blocked_tasks.pop(task_id, None)
            TaskStateMachine.transition(task, TaskStatus.CANCELLED, reason=reason)
            self._cancelled_tasks[task_id] = task
            # Cancelled tasks never complete: release dependents as FAILED so the
            # run cannot deadlock on them (no silent stuck-blocked tasks).
            self._fail_dependents_locked(task_id, f"dependency {task_id} cancelled")
            return True

    async def cancel_all(self, reason: str = "run cancelled") -> int:
        """Cancel every non-terminal task in the run. Returns count cancelled."""
        async with self._lock:
            ids = [
                tid for tid, t in self._all_tasks.items()
                if t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.ESCALATED)
            ]
        count = 0
        for tid in ids:
            if await self.mark_cancelled(tid, reason=reason):
                count += 1
        return count

    def recover_incomplete_tasks(self) -> List[str]:
        """Crash recovery: RUNNING/VALIDATING/REPAIRING/RETRYING -> QUEUED (retry).

        Must be called at startup after loading persisted tasks, before workers start.
        Returns the list of recovered task ids. Idempotent and duplicate-safe.
        """
        recovered: List[str] = []
        for task_id, task in self._all_tasks.items():
            if task.status in (
                TaskStatus.RUNNING,
                TaskStatus.VALIDATING,
                TaskStatus.REPAIRING,
                TaskStatus.QUALITY_GATE,
                TaskStatus.MASTER_REVIEW,
                TaskStatus.READY_FOR_MASTER,
                TaskStatus.RETRYING,
            ):
                # Reset to QUEUED without bumping retry_count (crash != failure).
                task.status = TaskStatus.QUEUED
                if "transition_history" not in task.metadata:
                    task.metadata["transition_history"] = []
                task.metadata["transition_history"].append({
                    "from": "CRASH",
                    "to": TaskStatus.QUEUED.value,
                    "reason": "recovered after restart",
                })
                self._running_tasks.pop(task_id, None)
                if task_id not in self._ready_queue:
                    self._ready_queue.append(task_id)
                recovered.append(task_id)
        # Rebuild dependency indexes after all tasks are loaded, irrespective of file order.
        self._ready_queue.clear()
        self._blocked_tasks.clear()
        for tid, task in self._all_tasks.items():
            if task.status in (TaskStatus.QUEUED, TaskStatus.PENDING):
                remaining = set(task.dependencies) - self._completed_tasks.keys()
                if remaining:
                    task.status = TaskStatus.PENDING
                    self._blocked_tasks[tid] = remaining
                else:
                    task.status = TaskStatus.QUEUED
                    self._ready_queue.append(tid)
        self._sort_ready_queue()
        return recovered

    def restore_task(self, task: Task) -> None:
        """Rehydrate a persisted task without re-running anti-explosion accounting twice."""
        self._all_tasks[task.id] = task
        if task.status == TaskStatus.COMPLETED:
            self._completed_tasks[task.id] = task
        elif task.status == TaskStatus.CANCELLED:
            self._cancelled_tasks[task.id] = task
        elif task.status in (TaskStatus.FAILED, TaskStatus.ESCALATED):
            self._failed_tasks[task.id] = task
        elif task.status in (TaskStatus.QUEUED, TaskStatus.RETRYING):
            if task.id not in self._ready_queue:
                self._ready_queue.append(task.id)
        elif task.status == TaskStatus.PENDING:
            unfulfilled = {d for d in task.dependencies if d not in self._completed_tasks}
            if unfulfilled:
                self._blocked_tasks[task.id] = unfulfilled
            elif task.id not in self._ready_queue:
                self._ready_queue.append(task.id)
        elif task.status in (TaskStatus.RUNNING, TaskStatus.VALIDATING, TaskStatus.REPAIRING,
                              TaskStatus.QUALITY_GATE, TaskStatus.MASTER_REVIEW, TaskStatus.READY_FOR_MASTER):
            self._running_tasks[task.id] = task
        self._sort_ready_queue()

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
    def cancelled_count(self) -> int:
        return len(self._cancelled_tasks)

    @property
    def failed_count(self) -> int:
        return len(self._failed_tasks)

    @property
    def escalated_count(self) -> int:
        return sum(1 for t in self._all_tasks.values() if t.status == TaskStatus.ESCALATED)

    def task_error_map(self) -> Dict[str, str]:
        """Per-task errors for partial-run reporting. DLQ reason wins,
        otherwise the last state-machine reason is used."""
        dlq: Dict[str, str] = {}
        for entry in self._dlq:
            tid = entry.get("task_id")
            if tid and tid not in dlq:
                dlq[tid] = str(entry.get("error", ""))
        out: Dict[str, str] = {}
        for tid, task in self._all_tasks.items():
            if task.status not in (TaskStatus.FAILED, TaskStatus.ESCALATED, TaskStatus.CANCELLED):
                continue
            reason = dlq.get(tid, "")
            if not reason:
                try:
                    hist = (task.metadata or {}).get("transition_history", []) or []
                    if hist:
                        reason = str(hist[-1].get("reason", "") or hist[-1].get("to", ""))
                except Exception:
                    reason = ""
            out[tid] = reason or task.status.value
        return out

    @property
    def dlq_count(self) -> int:
        return len(self._dlq)

    def get_dlq(self) -> List[Dict[str, Any]]:
        return list(self._dlq)
