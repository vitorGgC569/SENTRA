from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .models import Task


class AntiExplosionError(RuntimeError):
    """Raised when task explosion limits are violated."""
    pass


@dataclass
class AntiExplosionConfig:
    branching_factor_limit: int = 5
    max_depth: int = 5
    global_task_budget: int = 200
    marginal_value_threshold: float = 0.05
    enable_deduplication: bool = True
    # Near-duplicate detection is LEXICAL (Jaccard over normalized tokens), not
    # embedding-based semantic similarity. Threshold 0.85 = high overlap.
    # True paraphrases with low lexical overlap ("busca binaria" vs long description)
    # are NOT detected — see tests/failure/test_dedup_semantic_honesty.py.
    similarity_threshold: float = 0.85


class AntiExplosionGuard:
    """
    Guards against exponential task explosion as specified in Sections 71 and 72 of OMA:
    'Sem controle, decomposição recursiva pode gerar: 1 -> 10 -> 100 -> 1000 -> 10000 tarefas'
    """

    def __init__(self, config: Optional[AntiExplosionConfig] = None):
        self.config = config or AntiExplosionConfig()
        self._task_signatures: Set[str] = set()
        self._task_token_sets: List[Set[str]] = []
        self._total_tasks_created: int = 0
        self._parent_child_counts: Dict[str, int] = {}

    def _normalize_text(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        return " ".join(text.split())

    def _tokens(self, text: str) -> Set[str]:
        return set(self._normalize_text(text).split())

    @staticmethod
    def jaccard(a: Set[str], b: Set[str]) -> float:
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def find_most_similar(self, objective: str) -> float:
        """Max Jaccard similarity against registered tasks (0.0-1.0)."""
        cand = self._tokens(objective)
        best = 0.0
        for toks in self._task_token_sets:
            sim = self.jaccard(cand, toks)
            if sim > best:
                best = sim
        return best

    def _task_signature(self, task: Task) -> str:
        norm = self._normalize_text(task.objective)
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    def validate_new_task(self, task: Task, parent_task_id: Optional[str] = None) -> None:
        # Check global task budget
        if self._total_tasks_created >= self.config.global_task_budget:
            raise AntiExplosionError(
                f"Global task budget exceeded! Current: {self._total_tasks_created}, Max: {self.config.global_task_budget}"
            )

        # Check recursion depth limit
        if task.depth > self.config.max_depth:
            raise AntiExplosionError(
                f"Task depth limit exceeded for task {task.id}! Depth: {task.depth}, Max: {self.config.max_depth}"
            )

        # Check branching factor limit per parent
        if parent_task_id:
            current_children = self._parent_child_counts.get(parent_task_id, 0)
            if current_children >= self.config.branching_factor_limit:
                raise AntiExplosionError(
                    f"Branching factor limit reached for parent {parent_task_id}! Children: {current_children}, Limit: {self.config.branching_factor_limit}"
                )

        # Check duplicate / near-duplicate detection (lexical, honest naming)
        if self.config.enable_deduplication:
            sig = self._task_signature(task)
            if sig in self._task_signatures:
                raise AntiExplosionError(
                    f"Duplicate task rejected: Task '{task.objective[:50]}...' is textually identical to an existing task."
                )
            sim = self.find_most_similar(task.objective)
            if sim >= self.config.similarity_threshold:
                raise AntiExplosionError(
                    f"Near-duplicate task rejected: Jaccard similarity {sim:.2f} >= "
                    f"{self.config.similarity_threshold:.2f} (lexical overlap, not embedding semantics)."
                )

    def register_task(self, task: Task, parent_task_id: Optional[str] = None) -> None:
        self.validate_new_task(task, parent_task_id)
        sig = self._task_signature(task)
        self._task_signatures.add(sig)
        self._task_token_sets.append(self._tokens(task.objective))
        self._total_tasks_created += 1
        if parent_task_id:
            self._parent_child_counts[parent_task_id] = self._parent_child_counts.get(parent_task_id, 0) + 1

    def is_duplicate(self, objective: str) -> bool:
        norm = self._normalize_text(objective)
        sig = hashlib.sha256(norm.encode("utf-8")).hexdigest()
        if sig in self._task_signatures:
            return True
        return self.find_most_similar(objective) >= self.config.similarity_threshold

    @property
    def total_tasks_created(self) -> int:
        return self._total_tasks_created
