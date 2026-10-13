"""Selo: Learning/Eval service facade for central composition.

Wraps ReviewedLearningStore (CF17/FF10 suggestions) and LangfuseEvalStore
(prompts/datasets/runs/scores/comparison). Knowledge and scores are advisory
only: skill activation stays with Pacto's SkillLibrary, QualityGate verdicts
stay central, and budget accounting stays authoritative.

Codex composes this service and exposes agreed actions; Pacto consumes
review_bundle()/to_skill_files() output for SkillPack import review.
"""
from __future__ import annotations


def build_client(**trusted_host_configuration):
    from .selo_composition import build_client as compose
    return compose(**trusted_host_configuration)

from pathlib import Path
from typing import Any

from sentra_quality.learning_review import ReviewedLearningStore
from sentra_quality.langfuse_eval import LangfuseEvalStore


class LearningEvalService:
    def __init__(self, state_root: Path | str) -> None:
        self.root = Path(state_root).resolve()
        self.learning = ReviewedLearningStore(self.root)
        self.evals = LangfuseEvalStore(self.root)

    # -- reviewed learning (Pacto handoff) ------------------------------

    def suggest(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.learning.propose(owner, **kwargs)

    def suggestion(self, owner: str, suggestion_id: str) -> dict[str, Any]:
        return self.learning.get(owner, suggestion_id)

    def review_suggestion(self, owner: str, suggestion_id: str,
                          **kwargs: Any) -> dict[str, Any]:
        return self.learning.review(owner, suggestion_id, **kwargs)

    def withdraw_suggestion(self, owner: str, suggestion_id: str,
                            **kwargs: Any) -> dict[str, Any]:
        return self.learning.withdraw(owner, suggestion_id, **kwargs)

    def suggestions(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.learning.list(owner, **kwargs)

    def skill_candidate(self, owner: str, suggestion_id: str) -> dict[str, Any]:
        """APPROVED suggestion -> SkillPack candidate files (activates nothing)."""
        return self.learning.to_skill_files(owner, suggestion_id)

    def skill_review_bundle(self, owner: str, suggestion_id: str) -> dict[str, Any]:
        """Review bundle shaped like SkillLibrary.review for Pacto import."""
        return self.learning.review_bundle(owner, suggestion_id)

    # -- Langfuse evals (Codex telemetry/eval composition) ---------------

    def prompt_create(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.evals.prompt_create(owner, **kwargs)

    def prompt_activate(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.evals.prompt_activate(owner, **kwargs)

    def dataset_create(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.evals.dataset_create(owner, **kwargs)

    def dataset_item_add(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.evals.dataset_item_add(owner, **kwargs)

    def eval_run_create(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.evals.run_create(owner, **kwargs)

    def eval_item_record(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.evals.run_item_record(owner, **kwargs)

    def eval_score_record(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.evals.score_record(owner, **kwargs)

    def eval_compare(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.evals.compare_runs(owner, **kwargs)
