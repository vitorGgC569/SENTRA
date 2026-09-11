from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .events import EventEnvelope
from .models import Candidate, Task, ValidationReport


class PersistenceStore:
    """
    Persistence layer managing Runs, Tasks, Candidates, Validations, Events,
    and Metrics as specified in Section 30 of OMA.
    """

    def __init__(self, run_id: str, base_dir: Path = Path("runs")):
        self.run_id = run_id
        self.run_dir = Path(base_dir) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.tasks_file = self.run_dir / "tasks.json"
        self.candidates_file = self.run_dir / "candidates.json"
        self.validations_file = self.run_dir / "validations.json"
        self.events_file = self.run_dir / "events.jsonl"
        self.run_file = self.run_dir / "run.json"
        self.metrics_file = self.run_dir / "metrics.json"

    def save_run_metadata(self, metadata: Dict[str, Any]) -> None:
        self.run_file.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_run_metadata(self) -> Dict[str, Any]:
        if self.run_file.exists():
            return json.loads(self.run_file.read_text(encoding="utf-8"))
        return {}

    def save_tasks(self, tasks: List[Task]) -> None:
        data = [t.to_dict() for t in tasks]
        self.tasks_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_tasks(self) -> List[Task]:
        if not self.tasks_file.exists():
            return []
        data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
        return [Task.from_dict(d) for d in data]

    def save_candidate(self, candidate: Candidate) -> None:
        existing = self.load_candidates()
        # Update or append
        existing = [c for c in existing if c.candidate_id != candidate.candidate_id]
        existing.append(candidate)
        data = [c.to_dict() for c in existing]
        self.candidates_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_candidates(self) -> List[Candidate]:
        if not self.candidates_file.exists():
            return []
        data = json.loads(self.candidates_file.read_text(encoding="utf-8"))
        return [Candidate.from_dict(d) for d in data]

    def save_validation_report(self, report: ValidationReport) -> None:
        existing = self.load_validation_reports()
        existing = [r for r in existing if r.report_id != report.report_id]
        existing.append(report)
        data = [r.to_dict() for r in existing]
        self.validations_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_validation_reports(self) -> List[ValidationReport]:
        if not self.validations_file.exists():
            return []
        data = json.loads(self.validations_file.read_text(encoding="utf-8"))
        return [ValidationReport.from_dict(d) for d in data]

    def append_event(self, event: EventEnvelope) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_events(self) -> List[EventEnvelope]:
        if not self.events_file.exists():
            return []
        events = []
        with open(self.events_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(EventEnvelope.from_dict(json.loads(line)))
        return events

    def save_metrics(self, metrics: Dict[str, Any]) -> None:
        self.metrics_file.write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_metrics(self) -> Dict[str, Any]:
        if self.metrics_file.exists():
            return json.loads(self.metrics_file.read_text(encoding="utf-8"))
        return {}
