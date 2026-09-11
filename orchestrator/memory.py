from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Candidate, Task


@dataclass
class WorkingMemory:
    """Immediate turn-level context for an active agent."""
    messages: List[Dict[str, str]] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def clear(self) -> None:
        self.messages.clear()
        self.variables.clear()


@dataclass
class TaskMemory:
    """History and intermediate candidate versions for a specific subtask."""
    task_id: str
    candidates: List[Candidate] = field(default_factory=list)
    findings_history: List[Dict[str, Any]] = field(default_factory=list)
    iterations: int = 0

    def add_candidate(self, candidate: Candidate) -> None:
        self.candidates.append(candidate)
        self.iterations += 1

    def get_latest_candidate(self) -> Optional[Candidate]:
        return self.candidates[-1] if self.candidates else None


class ArtifactStore:
    """
    Stores bulky artifacts (code diffs, test logs, full file snapshots) on disk
    and provides lightweight IDs/URIs for agent context as specified in Section 42.
    """

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def store_artifact(self, artifact_type: str, content: str, extension: str = "txt") -> str:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        filename = f"{artifact_type}_{content_hash}.{extension}"
        filepath = self.storage_dir / filename
        filepath.write_text(content, encoding="utf-8", errors="replace")
        return str(filepath.resolve())

    def retrieve_artifact(self, filepath: str) -> str:
        p = Path(filepath)
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        return ""


class SemanticCache:
    """
    Cache for reusable candidate solutions and task outcomes as specified in Section 43-44.
    """

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _hash_objective(self, objective: str) -> str:
        norm = re.sub(r"[^\w\s]", "", objective.lower())
        norm = " ".join(norm.split())
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    def store(self, objective: str, candidate: Candidate) -> None:
        key = self._hash_objective(objective)
        self._cache[key] = {
            "candidate": candidate.to_dict(),
            "timestamp": time.time(),
        }

    def lookup(self, objective: str) -> Optional[Candidate]:
        key = self._hash_objective(objective)
        entry = self._cache.get(key)
        if entry:
            return Candidate.from_dict(entry["candidate"])
        return None


class MemoryManager:
    """
    Central Memory Architecture coordinating Working, Task, Run, and Long-Term Memory.
    """

    def __init__(self, run_id: str, storage_root: Path):
        self.run_id = run_id
        self.storage_root = Path(storage_root) / "memory" / run_id
        self.storage_root.mkdir(parents=True, exist_ok=True)

        self.working_memories: Dict[str, WorkingMemory] = {}
        self.task_memories: Dict[str, TaskMemory] = {}
        self.artifact_store = ArtifactStore(self.storage_root / "artifacts")
        self.semantic_cache = SemanticCache()
        self.run_knowledge: Dict[str, Any] = {}

    def get_working_memory(self, agent_id: str) -> WorkingMemory:
        if agent_id not in self.working_memories:
            self.working_memories[agent_id] = WorkingMemory()
        return self.working_memories[agent_id]

    def get_task_memory(self, task_id: str) -> TaskMemory:
        if task_id not in self.task_memories:
            self.task_memories[task_id] = TaskMemory(task_id=task_id)
        return self.task_memories[task_id]

    def record_run_insight(self, key: str, value: Any) -> None:
        self.run_knowledge[key] = value

    def get_run_insights(self) -> Dict[str, Any]:
        return dict(self.run_knowledge)
