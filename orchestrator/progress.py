from __future__ import annotations

from typing import Any, Dict
from .state_machine import JobState, stable_hash


class ProgressTracker:
    @staticmethod
    def calculate_progress_hash(
        completed_tasks: list[str],
        validation: Dict[str, Any],
        current_diff: str,
    ) -> str:
        data = {
            "completed": sorted(completed_tasks),
            "validation_passed": validation.get("all_passed", False),
            "passed_commands": validation.get("passed_commands", []),
            "diff_hash": stable_hash(current_diff),
        }
        return stable_hash(data)

    @staticmethod
    def update_progress(
        state: JobState,
        validation: Dict[str, Any],
        current_diff: str,
        no_progress_limit: int,
    ) -> bool:
        current_hash = ProgressTracker.calculate_progress_hash(
            state.completed_tasks, validation, current_diff
        )

        if current_hash == state.last_progress_hash:
            state.no_progress_rounds += 1
            state.log(f"Stagnation detected. Rounds without progress: {state.no_progress_rounds}/{no_progress_limit}")
        else:
            state.no_progress_rounds = 0
            state.last_progress_hash = current_hash
            state.log("Progress detected. Stagnation counter reset.")

        return state.no_progress_rounds >= no_progress_limit
