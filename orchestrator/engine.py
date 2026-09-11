from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    Candidate,
    CandidatePackage,
    MasterDecision,
    Severity,
    Task,
    TaskPriority,
    TaskStatus,
    ValidationReport,
    ValidatorRole,
)
from .state_machine import TaskStateMachine, Phase, JobSpec, JobState
from .events import EventBus, EventEnvelope, EventType
from .queue import PriorityTaskQueue
from .anti_explosion import AntiExplosionGuard, AntiExplosionConfig
from .quality_gate import QualityGate, QuorumPolicy
from .memory import MemoryManager
from .persistence import PersistenceStore
from .observability import MetricsCollector
from .agents.router import ModelRouter
from .agents.planner import TaskPlanner
from .agents.executor import ExecutorAgent
from .agents.validators import ValidatorPool
from .agents.repair import RepairAgent
from .agents.judge import JudgeAgent
from .agents.master import MasterModelAgent
from workspace.tool_gateway import ToolGateway


class OMAEngine:
    """
    Central Deterministic Multi-Agent Engine implementing the complete
    architecture specified in OMA_Orquestrador_Multiagente.md.
    """

    def __init__(
        self,
        run_id: str,
        objective: str,
        workspace_path: Path,
        router: ModelRouter,
        acceptance_criteria: Optional[List[str]] = None,
        validation_commands: Optional[List[str]] = None,
        quorum_policy: Optional[QuorumPolicy] = None,
        anti_explosion_config: Optional[AntiExplosionConfig] = None,
        max_parallel_workers: int = 3,
        token_budget_master: int = 50000,
        token_budget_secondary: int = 1000000,
    ):
        self.run_id = run_id
        self.objective = objective
        self.workspace_path = Path(workspace_path).resolve()
        self.router = router
        self.acceptance_criteria = acceptance_criteria or []
        self.validation_commands = validation_commands or []
        self.max_parallel_workers = max_parallel_workers
        self.token_budget_master = token_budget_master
        self.token_budget_secondary = token_budget_secondary

        # Core subsystems
        self.event_bus = EventBus()
        self.persistence = PersistenceStore(self.run_id)
        self.anti_explosion = AntiExplosionGuard(anti_explosion_config)
        self.task_queue = PriorityTaskQueue(self.anti_explosion)
        self.quality_gate = QualityGate(quorum_policy)
        self.memory = MemoryManager(self.run_id, self.workspace_path / "runs")
        self.metrics = MetricsCollector()
        self.tool_gateway = ToolGateway(self.workspace_path)

        # Wire event persistence listener
        self.event_bus.subscribe_all(self._on_event)

        # Agents
        self.planner = TaskPlanner(self.router)
        self.executor = ExecutorAgent(self.router)
        self.validator_pool = ValidatorPool(self.router)
        self.repair_agent = RepairAgent(self.router)
        self.judge = JudgeAgent(self.router)
        self.master = MasterModelAgent(self.router)

        self.completed_packages: List[CandidatePackage] = []
        self.final_synthesis: Optional[str] = None
        self.is_running: bool = False

    async def _on_event(self, event: EventEnvelope) -> None:
        self.persistence.append_event(event)

    async def initialize(self) -> None:
        await self.event_bus.publish(
            EventEnvelope(
                event_type=EventType.RUN_STARTED,
                correlation_id=self.run_id,
                producer="engine",
                payload={"objective": self.objective},
            )
        )
        self.persistence.save_run_metadata({
            "run_id": self.run_id,
            "objective": self.objective,
            "workspace": str(self.workspace_path),
            "status": "INITIALIZING",
            "start_time": time.time(),
        })

    async def plan_initial_tasks(self) -> List[Task]:
        print(f"\n[+] [OMA Engine] Planning task decomposition for Run: {self.run_id}")
        repo_summary = await self.tool_gateway.git_manager.inspect_repository()
        tasks = await self.planner.plan(
            run_id=self.run_id,
            objective=self.objective,
            acceptance_criteria=self.acceptance_criteria,
            repo_summary=repo_summary,
        )

        for task in tasks:
            success = await self.task_queue.add_task(task)
            if success:
                self.metrics.tasks_total += 1
                await self.event_bus.publish(
                    EventEnvelope(
                        event_type=EventType.TASK_CREATED,
                        correlation_id=self.run_id,
                        task_id=task.id,
                        producer="planner",
                        payload=task.to_dict(),
                    )
                )

        self.persistence.save_tasks(tasks)
        print(f"[+] [OMA Engine] Queued {len(tasks)} subtasks into PriorityTaskQueue.")
        return tasks

    async def process_task(self, task: Task) -> bool:
        """
        Executes the full OMA loop for a single task:
        Execute -> Validate -> Repair (up to max_repair_rounds) -> Quality Gate -> Master Review
        """
        print(f"\n[>] [Task {task.id}] Starting processing: {task.objective}")
        start_time = time.time()

        await self.event_bus.publish(
            EventEnvelope(
                event_type=EventType.TASK_STARTED,
                correlation_id=self.run_id,
                task_id=task.id,
                producer="engine",
            )
        )

        task_mem = self.memory.get_task_memory(task.id)

        # 1. Semantic Cache check
        cached_candidate = self.memory.semantic_cache.lookup(task.objective)
        if cached_candidate:
            print(f"[Task {task.id}] Cache HIT! Reusing candidate {cached_candidate.candidate_id}")
            candidate = cached_candidate
        else:
            # 2. Execution phase
            context_summary = f"Objective: {task.objective}\nDescription: {task.description}"
            candidate = await self.executor.execute_task(task, context_summary=context_summary)
            self.metrics.record_tokens(candidate.token_usage, is_master=False)
            task_mem.add_candidate(candidate)
            self.persistence.save_candidate(candidate)

            await self.event_bus.publish(
                EventEnvelope(
                    event_type=EventType.CANDIDATE_CREATED,
                    correlation_id=self.run_id,
                    task_id=task.id,
                    candidate_id=candidate.candidate_id,
                    producer="executor",
                    payload=candidate.to_dict(),
                )
            )

        # 3. Iterative Validation & Repair Loop
        package: Optional[CandidatePackage] = None
        while task.current_repair_round <= task.max_repair_rounds:
            TaskStateMachine.transition(task, TaskStatus.VALIDATING, reason=f"Validating Candidate V{candidate.version}")

            # Run deterministic verification (commands & tests)
            cmds_to_run = candidate.validation_commands or self.validation_commands or ["python -c \"print('OK')\""]
            test_results = await self.tool_gateway.cmd_runner.run_all(cmds_to_run)

            # Apply cognitive diversity validation
            reports = await self.validator_pool.validate_candidate(
                task=task,
                candidate=candidate,
                test_results=test_results,
            )

            for r in reports:
                self.metrics.record_tokens(r.token_usage, is_master=False)
                self.metrics.record_validation(approved=(r.status == "APPROVED"))
                self.persistence.save_validation_report(r)
                await self.event_bus.publish(
                    EventEnvelope(
                        event_type=EventType.VALIDATION_COMPLETED,
                        correlation_id=self.run_id,
                        task_id=task.id,
                        candidate_id=candidate.candidate_id,
                        producer=r.validator_role,
                        payload=r.to_dict(),
                    )
                )

            # Evaluate through Quality Gate
            TaskStateMachine.transition(task, TaskStatus.QUALITY_GATE, reason="Evaluating quality gate criteria")
            passed_gate, gate_reason, package = self.quality_gate.evaluate(
                task=task,
                candidate=candidate,
                reports=reports,
                test_results=test_results,
            )

            if passed_gate and package is not None:
                print(f"[Task {task.id}] Quality Gate PASSED! (Confidence: {package.calculated_confidence:.2f})")
                await self.event_bus.publish(
                    EventEnvelope(
                        event_type=EventType.QUALITY_GATE_PASSED,
                        correlation_id=self.run_id,
                        task_id=task.id,
                        candidate_id=candidate.candidate_id,
                        producer="quality_gate",
                        payload={"confidence": package.calculated_confidence},
                    )
                )
                break

            # If rejected, attempt repair if rounds remain
            task.current_repair_round += 1
            self.metrics.record_repair_round()
            print(f"[Task {task.id}] Quality Gate rejected ({gate_reason}). Attempting repair {task.current_repair_round}/{task.max_repair_rounds}...")

            await self.event_bus.publish(
                EventEnvelope(
                    event_type=EventType.CANDIDATE_REJECTED,
                    correlation_id=self.run_id,
                    task_id=task.id,
                    candidate_id=candidate.candidate_id,
                    producer="quality_gate",
                    payload={"reason": gate_reason},
                )
            )

            if task.current_repair_round > task.max_repair_rounds:
                print(f"[Task {task.id}] Exceeded max repair rounds! Escalating to Master Model.")
                await self.task_queue.mark_escalated(task.id, reason="Exceeded max repair rounds")
                self.metrics.record_task_escalated()
                return False

            TaskStateMachine.transition(task, TaskStatus.REPAIRING, reason=f"Repair round {task.current_repair_round}")
            await self.event_bus.publish(
                EventEnvelope(
                    event_type=EventType.REPAIR_REQUESTED,
                    correlation_id=self.run_id,
                    task_id=task.id,
                    candidate_id=candidate.candidate_id,
                    producer="engine",
                )
            )

            # Repair Agent produces new candidate version
            candidate = await self.repair_agent.repair_candidate(
                task=task,
                previous_candidate=candidate,
                validation_reports=reports,
                test_results=test_results,
            )
            self.metrics.record_tokens(candidate.token_usage, is_master=False)
            task_mem.add_candidate(candidate)
            self.persistence.save_candidate(candidate)

            await self.event_bus.publish(
                EventEnvelope(
                    event_type=EventType.REPAIR_COMPLETED,
                    correlation_id=self.run_id,
                    task_id=task.id,
                    candidate_id=candidate.candidate_id,
                    producer="repair",
                    payload=candidate.to_dict(),
                )
            )

        if not package:
            await self.task_queue.mark_failed(task.id, "Quality gate not passed within repair rounds")
            self.metrics.record_task_failed()
            return False

        # 4. Master Model Review
        TaskStateMachine.transition(task, TaskStatus.READY_FOR_MASTER, reason="Candidate promoted by Quality Gate")
        await self.event_bus.publish(
            EventEnvelope(
                event_type=EventType.READY_FOR_MASTER,
                correlation_id=self.run_id,
                task_id=task.id,
                candidate_id=candidate.candidate_id,
                producer="quality_gate",
            )
        )

        TaskStateMachine.transition(task, TaskStatus.MASTER_REVIEW, reason="Submitting compressed CandidatePackage to Master")
        await self.event_bus.publish(
            EventEnvelope(
                event_type=EventType.MASTER_REVIEW_STARTED,
                correlation_id=self.run_id,
                task_id=task.id,
                producer="master",
            )
        )

        decision: MasterDecision = await self.master.review_candidate_package(
            global_objective=self.objective,
            package=package,
        )
        self.metrics.record_tokens(decision.token_usage, is_master=True)

        await self.event_bus.publish(
            EventEnvelope(
                event_type=EventType.MASTER_REVIEW_COMPLETED,
                correlation_id=self.run_id,
                task_id=task.id,
                candidate_id=candidate.candidate_id,
                producer="master",
                payload=decision.to_dict(),
            )
        )

        if decision.decision == "APPROVED":
            print(f"[Task {task.id}] Master Model APPROVED! Applying solution to workspace...")
            # Apply patch to workspace
            if candidate.patch:
                patch_res = await self.tool_gateway.execute_patch(
                    role="master",
                    patch_text=candidate.patch,
                    idempotency_key=f"{task.id}_v{candidate.version}",
                )
                if not patch_res.get("success", False):
                    err = patch_res.get("error", "Patch failed to apply")
                    print(f"[Task {task.id}] Patch application error: {err}")
                    await self.task_queue.mark_failed(task.id, err)
                    self.metrics.record_task_failed()
                    return False

            # Mark completed & store in cache
            self.memory.semantic_cache.store(task.objective, candidate)
            self.completed_packages.append(package)
            await self.task_queue.mark_completed(task.id)

            latency = time.time() - start_time
            self.metrics.record_task_completed(latency)

            await self.event_bus.publish(
                EventEnvelope(
                    event_type=EventType.TASK_COMPLETED,
                    correlation_id=self.run_id,
                    task_id=task.id,
                    candidate_id=candidate.candidate_id,
                    producer="engine",
                )
            )
            print(f"[+] [Task {task.id}] COMPLETED successfully in {latency:.2f}s!")
            return True
        else:
            print(f"[Task {task.id}] Master Model REJECTED candidate: {decision.reasoning}")
            await self.task_queue.mark_failed(task.id, f"Master rejected: {decision.reasoning}")
            self.metrics.record_task_failed()
            return False

    async def run(self) -> Dict[str, Any]:
        """
        Executes the overall run until all tasks are completed or queue is empty.
        """
        self.is_running = True
        await self.initialize()

        # Step 1: Decompose
        await self.plan_initial_tasks()

        # Step 2: Main loop processing tasks
        while self.task_queue.has_pending_work() and self.is_running:
            task = await self.task_queue.pop_ready_task()
            if not task:
                # If there are blocked tasks waiting for dependencies or running workers, yield
                if self.task_queue.running_count > 0 or self.task_queue.blocked_count > 0:
                    await asyncio.sleep(0.1)
                    continue
                else:
                    # Deadlock or unfulfillable dependencies
                    print("[!] No ready tasks and no running tasks. Halting.")
                    break

            await self.process_task(task)

            # Display updated live dashboard
            conf = (
                statistics.mean([p.calculated_confidence for p in self.completed_packages])
                if self.completed_packages
                else 1.0
            )
            print("\n" + self.metrics.render_dashboard(current_confidence=conf) + "\n")

        # Step 3: Synthesis & Finalization
        if self.completed_packages:
            print("[+] Generating authoritative final report by Master Model...")
            self.final_synthesis = await self.master.synthesize_final_report(
                global_objective=self.objective,
                completed_packages=self.completed_packages,
            )
            await self.tool_gateway.commit(
                role="master",
                message=f"OMA completed run {self.run_id}: {self.objective[:50]}",
            )

        # Save metrics and run state
        metrics_dict = self.metrics.to_dict()
        self.persistence.save_metrics(metrics_dict)
        self.persistence.save_run_metadata({
            "run_id": self.run_id,
            "objective": self.objective,
            "status": "COMPLETED" if self.task_queue.completed_count == self.metrics.tasks_total else "FAILED",
            "completed_tasks": self.task_queue.completed_count,
            "total_tasks": self.metrics.tasks_total,
            "final_synthesis": self.final_synthesis,
            "metrics": metrics_dict,
        })

        run_evt = (
            EventType.RUN_COMPLETED
            if self.task_queue.completed_count == self.metrics.tasks_total
            else EventType.RUN_FAILED
        )
        await self.event_bus.publish(
            EventEnvelope(
                event_type=run_evt,
                correlation_id=self.run_id,
                producer="engine",
                payload={"metrics": metrics_dict},
            )
        )

        return {
            "run_id": self.run_id,
            "status": "COMPLETED" if self.task_queue.completed_count == self.metrics.tasks_total else "FAILED",
            "completed_tasks": self.task_queue.completed_count,
            "total_tasks": self.metrics.tasks_total,
            "final_synthesis": self.final_synthesis,
            "metrics": metrics_dict,
        }
