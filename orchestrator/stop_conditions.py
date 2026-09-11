from __future__ import annotations

from typing import Dict, Any, List
from .state_machine import JobState, JobSpec, stable_hash


class StopConditionChecker:
    @staticmethod
    def register_failure(state: JobState, spec: JobSpec, error_msg: str) -> bool:
        signature = stable_hash(error_msg)[:16]
        count = state.failure_signatures.get(signature, 0) + 1
        state.failure_signatures[signature] = count
        state.log(f"Registered failure [{signature}]. Count: {count}/{spec.repeated_failure_limit}")

        if count >= spec.repeated_failure_limit:
            state.log(f"Repeated failure limit exceeded for signature {signature}.")
            return True
        return False

    @staticmethod
    def is_max_rounds_reached(state: JobState, spec: JobSpec) -> bool:
        if state.round_number >= spec.max_rounds:
            state.log(f"Max rounds limit reached ({state.round_number}/{spec.max_rounds}).")
            return True
        return False

    @staticmethod
    def is_stagnated(state: JobState, spec: JobSpec) -> bool:
        if state.no_progress_rounds >= spec.no_progress_limit:
            state.log(f"Stagnation limit reached ({state.no_progress_rounds}/{spec.no_progress_limit}).")
            return True
        return False
