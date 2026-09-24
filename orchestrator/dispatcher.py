from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from .state_machine import Phase, JobSpec, JobState, StateStore
from .aggregator import Aggregator
from .progress import ProgressTracker
from .stop_conditions import StopConditionChecker
from local_model.qwen_client import QwenLocalClient
from local_model.prompts import PromptBuilder
from browser.pool import BrowserPool
from workspace.git_manager import GitManager
from workspace.command_runner import CommandRunner


class Orchestrator:
    def __init__(
        self,
        spec: JobSpec,
        store: StateStore,
        qwen: QwenLocalClient,
        browser_pool: BrowserPool,
        workspace_path: Path,
    ):
        self.spec = spec
        self.store = store
        self.qwen = qwen
        self.browser_pool = browser_pool
        self.workspace_path = Path(workspace_path)
        self.git_manager = GitManager(self.workspace_path)
        self.cmd_runner = CommandRunner(self.workspace_path)
        self.state = self.store.load() or JobState()

    async def run(self) -> JobState:
        self.state.log(f"Starting SENTRA job: {self.spec.job_id}")
        self.store.save(self.state)

        while self.state.phase not in {Phase.DONE, Phase.FAILED}:
            if StopConditionChecker.is_max_rounds_reached(self.state, self.spec):
                self.state.phase = Phase.FAILED
                break

            await self.run_current_phase()
            self.store.save(self.state)

        self.store.save(self.state)
        self.state.log(f"Job finalized with status: {self.state.phase.value}")
        return self.state

    async def run_current_phase(self) -> None:
        handlers = {
            Phase.ANALYZE: self.analyze,
            Phase.PLAN: self.plan,
            Phase.DISPATCH: self.dispatch,
            Phase.COLLECT: self.collect,
            Phase.CRITIQUE: self.critique,
            Phase.APPLY: self.apply,
            Phase.VALIDATE: self.validate,
        }

        handler = handlers.get(self.state.phase)
        if handler is None:
            raise RuntimeError(f"Unsupported phase: {self.state.phase}")

        await handler()

    async def analyze(self) -> None:
        self.state.log("Phase ANALYZE: Inspecting repository and asking Qwen for task breakdown...")
        repo_summary = await self.git_manager.inspect_repository()

        analysis = await self.qwen.analyze(
            objective=self.spec.entry_prompt,
            repository_summary=repo_summary,
            previous_validation=self.state.validation,
        )

        tasks = analysis.get("tasks", [])
        self.state.pending_tasks = tasks
        self.state.log(f"Analysis completed. Found {len(tasks)} subtasks.")
        self.state.phase = Phase.PLAN

    async def plan(self) -> None:
        self.state.log("Phase PLAN: Refining task execution plan for this round...")
        plan = await self.qwen.create_round_plan(
            objective=self.spec.entry_prompt,
            pending_tasks=self.state.pending_tasks,
            validation=self.state.validation,
        )

        self.state.pending_tasks = plan.get("tasks", self.state.pending_tasks)
        self.state.phase = Phase.DISPATCH

    async def dispatch(self) -> None:
        self.state.log("Phase DISPATCH: Sending prompts to web browser sessions...")
        resource_manifest = (
            self.browser_pool.resource_manifest()
            if hasattr(self.browser_pool, "resource_manifest")
            else {"max_concurrency": self.spec.max_parallel_sessions, "resources": []}
        )
        browser_capacity = max(1, int(resource_manifest.get("max_concurrency") or 1))
        dispatch_limit = min(self.spec.max_parallel_sessions, browser_capacity)
        active_tasks = self.state.pending_tasks[:dispatch_limit]
        self.state.log(
            f"Browser runtime capacity: {browser_capacity}; dispatch limit: {dispatch_limit}"
        )
        if not active_tasks:
            # Fallback if no subtasks defined
            active_tasks = [
                {
                    "id": f"task-{self.state.round_number:03d}",
                    "description": self.spec.entry_prompt,
                    "role": "implementer",
                    "target_files": [],
                }
            ]

        dispatches = []
        state_summary = f"Round {self.state.round_number}. Pending tasks: {len(self.state.pending_tasks)}"

        for task in active_tasks:
            role = task.get("role", "implementer")
            prompt = PromptBuilder.build_envelope(
                job_id=self.spec.job_id,
                round_number=self.state.round_number,
                role=role,
                task_id=task.get("id", "task-01"),
                global_objective=self.spec.entry_prompt,
                task_description=task.get("description", self.spec.entry_prompt),
                relevant_files=task.get("target_files", []),
                current_state_summary=state_summary,
                error_log=self.state.validation.get("stderr", None),
            )

            dispatches.append(
                self.browser_pool.submit(
                    role=role,
                    task=task,
                    prompt=prompt,
                    round_number=self.state.round_number,
                )
            )

        raw_results = await asyncio.gather(*dispatches)
        self.state.browser_results = raw_results
        self.state.phase = Phase.COLLECT

    async def collect(self) -> None:
        self.state.log("Phase COLLECT: Normalizing browser responses...")
        normalized = Aggregator.aggregate_session_results(self.state.browser_results)
        self.state.browser_results = normalized
        self.state.phase = Phase.CRITIQUE

    async def critique(self) -> None:
        self.state.log("Phase CRITIQUE: Qwen evaluating proposed solutions...")
        current_diff = await self.git_manager.current_diff()

        decision = await self.qwen.critique(
            objective=self.spec.entry_prompt,
            acceptance_criteria=self.spec.acceptance_criteria,
            browser_results=self.state.browser_results,
            repository_state=current_diff,
        )

        status = decision.get("status")

        if status == "request_revision":
            self.state.log("Critique decision: Revision requested.")
            self.state.pending_tasks = decision.get("revision_tasks", self.state.pending_tasks)
            self.state.round_number += 1
            self.state.phase = Phase.DISPATCH
            return

        if status == "reject":
            reason = decision.get("reason", "No usable patch provided.")
            self.state.log(f"Critique decision: Rejected. Reason: {reason}")
            if StopConditionChecker.register_failure(self.state, self.spec, reason):
                self.state.phase = Phase.FAILED
                return
            self.state.round_number += 1
            self.state.phase = Phase.PLAN
            return

        self.state.accepted_results = decision.get("accepted_results", self.state.browser_results)

        # Wire the validation commands the LLM proposed (e.g. "pytest foo.py")
        # into the spec, otherwise VALIDATE keeps re-running only the generic
        # default check and never actually exercises the fix.
        for res in self.state.accepted_results:
            for cmd in res.get("validation_commands", []):
                if cmd and cmd not in self.spec.validation_commands:
                    self.spec.validation_commands.append(cmd)

        self.state.phase = Phase.APPLY

    async def apply(self) -> None:
        self.state.log("Phase APPLY: Applying patches to workspace...")
        patches = [res["patch"] for res in self.state.accepted_results if res.get("patch")]

        if not patches:
            self.state.log("No valid patches found to apply.")
            self.state.phase = Phase.PLAN
            self.state.round_number += 1
            return

        application = await self.git_manager.apply_in_isolated_worktree(patches)

        if not application["success"]:
            err = application.get("error", "Failed to apply patch.")
            self.state.log(f"Apply failed: {err}")
            StopConditionChecker.register_failure(self.state, self.spec, err)
            self.state.validation = application
            self.state.round_number += 1
            self.state.phase = Phase.PLAN
            return

        self.state.phase = Phase.VALIDATE

    async def validate(self) -> None:
        self.state.log("Phase VALIDATE: Running validation commands...")
        cmds = self.spec.validation_commands or ["python -c \"print('Build OK')\""]
        val_result = await self.cmd_runner.run_all(cmds)
        self.state.validation = val_result

        current_diff = await self.git_manager.current_diff()
        stagnated = ProgressTracker.update_progress(
            self.state, val_result, current_diff, self.spec.no_progress_limit
        )

        if val_result.get("all_passed", False):
            final_review = await self.qwen.verify_acceptance(
                objective=self.spec.entry_prompt,
                acceptance_criteria=self.spec.acceptance_criteria,
                validation=val_result,
                diff=current_diff,
            )

            if final_review.get("accepted", False):
                await self.git_manager.commit_result()
                self.state.log("Final acceptance verified! Task DONE.")
                self.state.phase = Phase.DONE
                return

        if stagnated:
            self.state.log("Stagnation limit exceeded. Job FAILED.")
            self.state.phase = Phase.FAILED
            return

        self.state.round_number += 1
        self.state.phase = Phase.ANALYZE
