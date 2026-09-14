from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .events import EventEnvelope, EventType
from .models import Candidate, Task, ValidationReport


class PersistenceCorruptionError(RuntimeError):
    """Raised when a persisted JSON file is partially written or corrupted."""


class PersistenceStore:
    """
    Persistence layer managing Runs, Tasks, Candidates, Validations, Events,
    and Metrics as specified in Section 30 of OMA.
    """

    def __init__(self, run_id: str, base_dir: Path = Path("runs")):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
            raise ValueError("run_id must be 1..80 letters, digits, hyphens or underscores")
        base_dir = Path(base_dir).absolute()
        if base_dir.is_symlink() or (hasattr(base_dir, "is_junction") and base_dir.is_junction()):
            raise ValueError("run storage cannot be a filesystem link")
        self.run_id = run_id
        self.run_dir = Path(base_dir) / run_id
        if self.run_dir.is_symlink() or (hasattr(self.run_dir, "is_junction") and self.run_dir.is_junction()):
            raise ValueError("run directory cannot be a filesystem link")
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.tasks_file = self.run_dir / "tasks.json"
        self.candidates_file = self.run_dir / "candidates.json"
        self.validations_file = self.run_dir / "validations.json"
        self.events_file = self.run_dir / "events.jsonl"
        self.run_file = self.run_dir / "run.json"
        self.metrics_file = self.run_dir / "metrics.json"

    # -- atomic, corruption-safe IO -------------------------------------
    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        """Atomic write (tmp + os.replace) so interrupted writes never corrupt state."""
        tmp_fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp.")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            # Never allow silent corruption: quarantine the bad file and raise.
            quarantine = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}.bak")
            try:
                os.replace(str(path), str(quarantine))
            except Exception:
                pass
            raise PersistenceCorruptionError(
                f"Persisted file {path} is corrupted ({e}); quarantined as {quarantine}"
            )

    def save_run_metadata(self, metadata: Dict[str, Any]) -> None:
        self._atomic_write_json(self.run_file, metadata)

    def load_run_metadata(self) -> Dict[str, Any]:
        return self._load_json(self.run_file, {})

    def save_tasks(self, tasks: List[Task]) -> None:
        data = [t.to_dict() for t in tasks]
        self._atomic_write_json(self.tasks_file, data)

    def upsert_task(self, task: Task) -> None:
        """Idempotent per-task write: duplicates update instead of duplicating."""
        existing = self.load_tasks()
        existing = [t for t in existing if t.id != task.id]
        existing.append(task)
        self._atomic_write_json(self.tasks_file, [t.to_dict() for t in existing])

    def load_tasks(self) -> List[Task]:
        data = self._load_json(self.tasks_file, [])
        return [Task.from_dict(d) for d in data]

    def save_candidate(self, candidate: Candidate) -> None:
        existing = self.load_candidates()
        # Update or append (idempotent on candidate_id)
        existing = [c for c in existing if c.candidate_id != candidate.candidate_id]
        existing.append(candidate)
        data = [c.to_dict() for c in existing]
        self._atomic_write_json(self.candidates_file, data)

    def load_candidates(self) -> List[Candidate]:
        data = self._load_json(self.candidates_file, [])
        return [Candidate.from_dict(d) for d in data]

    def save_validation_report(self, report: ValidationReport) -> None:
        existing = self.load_validation_reports()
        existing = [r for r in existing if r.report_id != report.report_id]
        existing.append(report)
        data = [r.to_dict() for r in existing]
        self._atomic_write_json(self.validations_file, data)

    def load_validation_reports(self) -> List[ValidationReport]:
        data = self._load_json(self.validations_file, [])
        return [ValidationReport.from_dict(d) for d in data]

    def append_event(self, event: EventEnvelope) -> None:
        # Deduplicate on event_id (idempotent replay-safe) without full scan:
        # events are append-only; duplicates are filtered at load/replay time.
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            try:
                f.flush()
            except Exception:
                pass

    def load_events(self) -> List[EventEnvelope]:
        if not self.events_file.exists():
            return []
        events: List[EventEnvelope] = []
        seen_ids = set()
        with open(self.events_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    env = EventEnvelope.from_dict(json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Skip a single torn line (partial crash write) but keep the log usable.
                    continue
                if env.event_id in seen_ids:
                    continue  # idempotent: duplicate delivery ignored
                seen_ids.add(env.event_id)
                events.append(env)
        return events

    def save_metrics(self, metrics: Dict[str, Any]) -> None:
        self._atomic_write_json(self.metrics_file, metrics)

    def load_metrics(self) -> Dict[str, Any]:
        return self._load_json(self.metrics_file, {})

    # -- event-sourced reconstruction (Section 64) -----------------------
    def replay_events(self) -> Dict[str, Any]:
        """Rebuild materialized state purely from events.jsonl.

        Returns {'tasks': {id: status}, 'candidates': [...], 'validations': n,
        'completed': [...], 'failed': [...], 'events_replayed': n}.
        This is what makes the log a true event source rather than an audit trail:
        deleting tasks.json/candidates.json and replaying must yield equivalent state.
        """
        events = self.load_events()
        task_status: Dict[str, str] = {}
        candidates: List[str] = []
        validations = 0
        completed: List[str] = []
        failed: List[str] = []
        for e in events:
            et = e.event_type.value if isinstance(e.event_type, EventType) else str(e.event_type)
            tid = e.task_id
            if et == "TASK_CREATED" and tid:
                task_status[tid] = "PENDING"
            elif et == "TASK_STARTED" and tid:
                task_status[tid] = "RUNNING"
            elif et == "CANDIDATE_CREATED" and e.candidate_id:
                candidates.append(e.candidate_id)
                if tid:
                    task_status[tid] = "VALIDATING"
            elif et == "CANDIDATE_REJECTED" and tid:
                task_status[tid] = "REJECTED"
            elif et == "REPAIR_COMPLETED" and e.candidate_id:
                candidates.append(e.candidate_id)
            elif et == "QUALITY_GATE_PASSED" and tid:
                task_status[tid] = "READY_FOR_MASTER"
            elif et == "READY_FOR_MASTER" and tid:
                task_status[tid] = "READY_FOR_MASTER"
            elif et == "TASK_COMPLETED" and tid:
                task_status[tid] = "COMPLETED"
                if tid not in completed:
                    completed.append(tid)
            elif et == "TASK_FAILED" and tid:
                task_status[tid] = "FAILED"
                if tid not in failed:
                    failed.append(tid)
            elif et == "TASK_CANCELLED" and tid:
                task_status[tid] = "CANCELLED"
            elif et == "TASK_ESCALATED" and tid:
                task_status[tid] = "ESCALATED"
            elif et == "VALIDATION_COMPLETED":
                validations += 1
        return {
            "tasks": task_status,
            "candidates": candidates,
            "validations": validations,
            "completed": completed,
            "failed": failed,
            "events_replayed": len(events),
        }
