from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    Candidate,
    CandidatePackage,
    Finding,
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
from .agents.master import MasterModelAgent, ReviewProtocolError
from workspace.tool_gateway import ToolGateway
from workspace.patch_manager import PatchManager
from workspace.sandbox import fingerprint, source_files
from .verification import CandidateVerifier
from .budgets import TokenBudget


def _rejection_signature(gate_reason: str, reports, test_results) -> tuple:
    """Assinatura estável de uma rejeição: classe do motivo + comandos falhos +
    categorias/severidades dos findings. Rejeições idênticas seguidas = repair
    travado (nada muda entre rounds) → quebrar cedo em vez de queimar budget."""
    reason_class = (gate_reason or "").split(":")[0].strip()
    failed = tuple(sorted((test_results or {}).get("failed_commands", [])))
    findings = []
    for r in reports or []:
        for f in getattr(r, "findings", []) or []:
            sev = getattr(getattr(f, "severity", ""), "value", f.severity)
            findings.append((str(sev), str(getattr(f, "category", ""))))
    return (reason_class, failed, tuple(sorted(findings)))


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
        max_rounds: int = 20,
        no_progress_limit: int = 3,
        persistence_base: Optional[Path] = None,
        checkpoint_callback=None,
        task_token_budget: int = 120000,
        max_repair_rounds: int = 15,
        stagnation_limit: int = 5,
        command_profiles=None,
        test_timeout: float = 120,
        execution=None,
        allowed_patch_paths=None,
        compute_policy=None,
        fixed_conversations: bool = False,
        inter_call_delay_s: float = 0.0,
        max_seats: int = 8,
        conversation_pool_dir=None,
        conversation_namespace=None,
    ):
        self.run_id = run_id
        self.objective = objective
        self.workspace_path = Path(workspace_path).resolve()
        self.router = router
        self.acceptance_criteria = acceptance_criteria or []
        self.validation_commands = validation_commands if validation_commands is not None else ["[[TEST|all]]"]
        self.max_parallel_workers = max_parallel_workers
        self.token_budget_master = token_budget_master
        self.token_budget_secondary = token_budget_secondary
        if min(max_parallel_workers, max_rounds, no_progress_limit) <= 0:
            raise ValueError("worker and loop limits must be positive")
        if type(stagnation_limit) is not int or not 1 <= stagnation_limit <= 20:
            raise ValueError("stagnation_limit must be a positive int")
        self.max_rounds, self.no_progress_limit = max_rounds, no_progress_limit
        self.stagnation_limit = stagnation_limit
        self._running_futures = {}
        self.checkpoint_callback = checkpoint_callback
        self.task_token_budget = task_token_budget
        self.max_repair_rounds = max_repair_rounds
        self.compute_policy = compute_policy
        self._task_roles = {}

        # Core subsystems
        self.event_bus = EventBus()
        self.persistence = PersistenceStore(self.run_id, base_dir=persistence_base or self.workspace_path / "runs")
        self.anti_explosion = AntiExplosionGuard(anti_explosion_config)
        self.task_queue = PriorityTaskQueue(self.anti_explosion)
        self.quality_gate = QualityGate(quorum_policy)
        self.memory = MemoryManager(self.run_id, self.workspace_path / "runs")
        self.metrics = MetricsCollector()
        self.tool_gateway = ToolGateway(self.workspace_path, execution=execution, profiles=command_profiles)
        self.verifier = CandidateVerifier(self.workspace_path, self.validation_commands, command_profiles, test_timeout,
                                          execution, allowed_patch_paths)
        self._promotion_lock = asyncio.Lock()
        budget_file = self.persistence.run_dir / "budgets.json"
        self.budget = TokenBudget(token_budget_master, token_budget_secondary,
                                 state=self.persistence._load_json(budget_file, {}),
                                 save=lambda state: self.persistence._atomic_write_json(budget_file, state))
        self.router.budget = self.budget
        self.router.run_id = self.run_id
        self.router.response_sink = lambda data: self.persistence.append_event(EventEnvelope(
            event_type=EventType.MODEL_RESPONSE, correlation_id=self.run_id,
            task_id=data.get("task_id"), producer=data["role"], payload=data))
        # Five initial seats plus cause-based standby validators. Wrap BEFORE
        # agents are built: they keep this reference, including planner/repair.
        # max_seats é o TETO DE CRIAÇÃO DE CHATS (rate limit conta conversas,
        # não mensagens) — deliberadamente desacoplado de compute_policy.max_agents.
        self.fixed_conversations = bool(fixed_conversations)
        self.inter_call_delay_s = max(0.0, float(inter_call_delay_s or 0.0))
        if type(max_seats) is not int or not 1 <= max_seats <= 8:
            raise ValueError("max_seats must be an int 1..8")
        self.max_seats = max_seats
        if self.fixed_conversations:
            from .conversation_pool import FixedConversationRouter
            self.router = FixedConversationRouter(
                self.router, run_id=conversation_namespace or self.run_id,
                store_dir=conversation_pool_dir or self.persistence.run_dir,
                inter_call_delay_s=self.inter_call_delay_s,
                max_seats=self.max_seats)

        # Wire event persistence listener
        self.event_bus.subscribe_all(self._on_event)

        # Agents
        self.planner = TaskPlanner(self.router)
        self.executor = ExecutorAgent(self.router)
        self.validator_pool = ValidatorPool(self.router,
            require_explicit_scores=self.quality_gate.policy.require_explicit_scores)
        self.repair_agent = RepairAgent(self.router)
        self.judge = JudgeAgent(self.router)
        self.master = MasterModelAgent(self.router)

        self.completed_packages: List[CandidatePackage] = []
        self.final_synthesis: Optional[str] = None
        self.is_running: bool = False
        self._cancel_requested: bool = False

    async def _on_event(self, event: EventEnvelope) -> None:
        self.persistence.append_event(event)

    def _repository_event(self, entry) -> None:
        self.persistence.append_event(EventEnvelope(
            event_type=EventType.REPOSITORY_COMMAND, correlation_id=self.run_id,
            task_id=entry.get("task_id"), producer=entry.get("agent_id", "repository"), payload=entry))

    # -- RF-017 cancellation ------------------------------------------------
    def request_cancel(self, reason: str = "user requested cancel") -> None:
        """Signal the run loop to stop dispatching and abort in-flight work ASAP."""
        self._cancel_requested = True
        self.is_running = False
        for future in list(self._running_futures):
            future.cancel()

    async def cancel_task(self, task_id: str, reason: str = "cancel requested") -> bool:
        ok = await self.task_queue.mark_cancelled(task_id, reason=reason)
        if ok:
            await self.event_bus.publish(
                EventEnvelope(
                    event_type=EventType.TASK_CANCELLED,
                    correlation_id=self.run_id,
                    task_id=task_id,
                    producer="engine",
                    payload={"reason": reason},
                )
            )
        return ok

    async def cancel_run(self, reason: str = "run cancelled") -> int:
        self.request_cancel(reason=reason)
        count = await self.task_queue.cancel_all(reason=reason)
        await self.event_bus.publish(
            EventEnvelope(
                event_type=EventType.RUN_FAILED,
                correlation_id=self.run_id,
                producer="engine",
                payload={"reason": reason, "cancelled_tasks": count},
            )
        )
        return count

    def _check_cancelled(self, task: Task) -> bool:
        return self._cancel_requested or task.status == TaskStatus.CANCELLED

    def _expand_validators(self, task: Task, reports: List[ValidationReport],
                           gate_reason: str) -> List[ValidatorRole]:
        """Compute-policy escalation: standby roles join on disagreement
        (DISPUTED votes) or low confidence (gate confidence failure). Pure
        w.r.t. limits: never exceeds max_agents, never duplicates."""
        policy = self.compute_policy
        active = self._task_roles.get(task.id) or policy.initial_for_task(task)
        ran = [r for r in reports if r.ran]
        if any(r.status == "DISPUTED" for r in ran):
            return policy.expand(active, policy.disagreement_add)
        if gate_reason.startswith("Confidence below threshold"):
            return policy.expand(active, policy.low_confidence_add)
        return active

    # -- crash recovery ------------------------------------------------------
    async def load_and_recover(self) -> List[str]:
        """Reload persisted tasks/candidates and re-queue interrupted work.

        Returns recovered task ids. Safe to call on a fresh engine for the same run_id.
        """
        persisted = self.persistence.load_tasks()
        for t in persisted:
            self.task_queue.restore_task(t)
            self.anti_explosion.register_task(t)
        self.metrics.tasks_total = len(persisted)
        self.metrics.tasks_completed = self.task_queue.completed_count
        packages = self.persistence._load_json(self.persistence.run_dir / "packages.json", [])
        self.completed_packages = [CandidatePackage.from_dict(p) for p in packages]
        return self.task_queue.recover_incomplete_tasks()

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
        with self.router.repository_scope(self.workspace_path, self._repository_event):
            tasks = await self.planner.plan(
                run_id=self.run_id, objective=self.objective,
                acceptance_criteria=self.acceptance_criteria, repo_summary=repo_summary)

        for task in tasks:
            task.token_budget = self.task_token_budget
            task.max_repair_rounds = self.max_repair_rounds
            task.metadata["acceptance_criteria"] = [task.objective]
            success = await self.task_queue.add_task(task)
            if not success:
                raise ValueError(f"planner task {task.id} rejected by queue policy; plan not executed")
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
        self.budget.register_task(task.id, task.token_budget)
        with self.router.repository_scope(self.workspace_path, self._repository_event):
            try:
                return await self._process_task(task)
            except asyncio.CancelledError:
                await self.cancel_task(task.id, reason="cancelled")
                raise
            except Exception as exc:
                await self.task_queue.mark_failed(task.id, str(exc), retryable=False)
                self.metrics.record_task_failed()
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.TASK_FAILED, correlation_id=self.run_id,
                    task_id=task.id, producer="engine", payload={"reason": str(exc)}))
                return False
            finally:
                self.persistence.save_tasks(list(self.task_queue._all_tasks.values()))
                self.persistence.save_metrics(self.metrics.to_dict())

    async def _process_task(self, task: Task) -> bool:
        """
        Executes the full OMA loop for a single task:
        Execute -> Validate -> Repair (up to max_repair_rounds) -> Quality Gate -> Master Review
        Cancellation (RF-017) and timeouts (RF-016) propagate; no retry after cancel.
        """
        print(f"\n[>] [Task {task.id}] Starting processing: {task.objective}")
        start_time = time.time()

        if self._check_cancelled(task):
            await self.cancel_task(task.id, reason="cancelled before start")
            return False

        await self.event_bus.publish(
            EventEnvelope(
                event_type=EventType.TASK_STARTED,
                correlation_id=self.run_id,
                task_id=task.id,
                producer="engine",
            )
        )
        try:
            self.persistence.upsert_task(task)
        except Exception:
            pass

        task_mem = self.memory.get_task_memory(task.id)

        # 1. Semantic Cache check
        # Objective-only caches cannot safely reuse patches from a different baseline.
        cached_candidate = None
        if cached_candidate:
            print(f"[Task {task.id}] Cache HIT! Reusing candidate {cached_candidate.candidate_id}")
            candidate = cached_candidate
        else:
            # 2. Execution phase (CancelledError propagates -> caller handles RF-017)
            try:
                context_summary = f"Objective: {task.objective}\nDescription: {task.description}"
                candidate = await self.executor.execute_task(task, context_summary=context_summary)
            except asyncio.CancelledError:
                await self.cancel_task(task.id, reason="cancelled during execution")
                raise
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
        if self._check_cancelled(task):
            await self.cancel_task(task.id, reason="cancelled after execution")
            return False

        # 3. Iterative Validation & Repair Loop
        package: Optional[CandidatePackage] = None
        validation_retries = 0
        max_validation_retries = 2
        last_rejection_sig = None
        stagnant_rounds = 0
        reports: List[ValidationReport] = []
        test_results: Dict[str, Any] = {"all_passed": False, "failed_commands": [], "results": [],
                                        "checks_ran": 0, "refused_commands": []}
        # Compute policy: fixed initial validator set per task; standby roles
        # join only on disagreement / low confidence (bounded by max_agents).
        if self.compute_policy is not None:
            active_roles: Optional[List[ValidatorRole]] = self._task_roles.get(task.id) or \
                self.compute_policy.initial_for_task(task)
            self._task_roles[task.id] = list(active_roles)
        else:
            active_roles = None
        while task.current_repair_round <= task.max_repair_rounds:
            if self._check_cancelled(task):
                await self.cancel_task(task.id, reason="cancelled during validation loop")
                return False
            TaskStateMachine.transition(task, TaskStatus.VALIDATING, reason=f"Validating Candidate V{candidate.version}")

            # 3a. Patch pre-check (cheap, local, zero token budget): a malformed
            # or inapplicable NON-EMPTY diff goes straight to repair WITHOUT a
            # validator round. Empty patch is a legitimate no-op candidate
            # (verification-only tasks); only garbage is rejected here.
            try:
                if (candidate.patch or "").strip():
                    PatchManager.check_applies(self.workspace_path, candidate.patch)
                parse_error = ""
            except Exception as exc:
                parse_error = str(exc)[:300]
            if parse_error:
                reports = []
                test_results = {"all_passed": False, "failed_commands": ["PATCH_SYNTAX"],
                                "results": [], "checks_ran": 0, "refused_commands": [],
                                "parse_error": parse_error}
                # Sintaxe também é veredito do gate: mantém a cadeia
                # VALIDATING -> QUALITY_GATE -> REPAIRING exigida pela máquina.
                TaskStateMachine.transition(task, TaskStatus.QUALITY_GATE,
                                            reason="Patch syntax rejected before validators")
                passed_gate, gate_reason, package = (
                    False, f"PATCH_SYNTAX: {parse_error}", None)
            else:
                # Test the applied candidate in an isolated copy, never the baseline.
                async def inspect_candidate(root, evidence):
                    with self.router.repository_scope(root, self._repository_event):
                        return await self.validator_pool.validate_candidate(
                            task=task, candidate=candidate, roles=active_roles,
                            test_results=evidence)
                try:
                    test_results = await self.verifier.verify(candidate, inspect=inspect_candidate,
                                                             event_sink=self._repository_event)
                    reports = test_results.pop("_reports")
                    self.persistence._atomic_write_json(
                        self.persistence.run_dir / f"verification-{candidate.candidate_id}.json", test_results)
                except asyncio.CancelledError:
                    await self.cancel_task(task.id, reason="cancelled during deterministic verification")
                    raise

                for r in reports:
                    self.metrics.record_tokens(r.token_usage, is_master=False)
                    self.metrics.record_validation(approved=(r.status == "APPROVED"), ran=r.ran)
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

            # 3b. Validators abstained (infra failure, not evidence): retry the
            # VALIDATION boundedly. Never burns a repair round on the candidate.
            if gate_reason.startswith("INSUFFICIENT_VALIDATION"):
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.QUALITY_GATE_FAILED, correlation_id=self.run_id,
                    task_id=task.id, candidate_id=candidate.candidate_id, producer="quality_gate",
                    payload={"reason": gate_reason}))
                if validation_retries < max_validation_retries and not self._check_cancelled(task):
                    validation_retries += 1
                    print(f"[Task {task.id}] {gate_reason} Retrying validation "
                          f"({validation_retries}/{max_validation_retries}) without consuming a repair round...")
                    continue
                print(f"[Task {task.id}] Validators never ran; escalating.")
                await self.task_queue.mark_escalated(task.id, reason=gate_reason)
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.TASK_ESCALATED, correlation_id=self.run_id,
                    task_id=task.id, producer="engine", payload={"reason": gate_reason}))
                self.metrics.record_task_escalated()
                return False

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
                decision = await self._review_package(task, candidate, package, test_results)
                if decision is None:
                    return False  # protocol/transport failure: preserve, do not regenerate
                if decision.decision == "APPROVED":
                    break
                # A substantive final objection returns to the SAME repair loop,
                # preserving the candidate and the remaining repair budget.
                gate_reason = f"MASTER_REJECTED: {decision.reasoning}"
                reports = reports + [ValidationReport(
                    task_id=task.id, candidate_id=candidate.candidate_id,
                    validator_role="master", status="REJECTED", confidence=decision.confidence,
                    score=7.0, findings=[Finding(severity=Severity.MAJOR,
                        category="MASTER_REVIEW", description=decision.reasoning,
                        suggested_fix="Address the final review without discarding verified behavior.")])]
                passed_gate, package = False, None

            # If rejected, attempt repair if rounds remain
            await self.event_bus.publish(EventEnvelope(
                event_type=EventType.QUALITY_GATE_FAILED, correlation_id=self.run_id,
                task_id=task.id, candidate_id=candidate.candidate_id, producer="quality_gate",
                payload={"reason": gate_reason}))
            # Stagnation: mesma rejeição repetida = repair travado. Para cedo
            # com motivo honesto em vez de queimar rounds restantes à toa.
            # (Limites diferentes de exaustão: aqui nada muda entre rounds.)
            sig = _rejection_signature(gate_reason, reports, test_results)
            if sig == last_rejection_sig:
                stagnant_rounds += 1
            else:
                last_rejection_sig, stagnant_rounds = sig, 0
            if stagnant_rounds >= self.stagnation_limit:
                print(f"[Task {task.id}] STAGNANT: same rejection "
                      f"{stagnant_rounds + 1}x ({sig[0]}). Escalating.")
                await self.task_queue.mark_escalated(task.id, reason=f"STAGNANT: {gate_reason}")
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.TASK_ESCALATED, correlation_id=self.run_id,
                    task_id=task.id, producer="engine",
                    payload={"reason": f"STAGNANT: {gate_reason}"}))
                self.metrics.record_task_escalated()
                return False
            # Compute-policy escalation BEFORE repairing: disagreement or low
            # confidence adds standby validators for the next round.
            if self.compute_policy is not None:
                expanded = self._expand_validators(task, reports, gate_reason)
                if len(expanded) > len(active_roles or []):
                    added = [r.value for r in expanded if r not in (active_roles or [])]
                    print(f"[Task {task.id}] Escalating compute: "
                          f"{len(active_roles or [])} -> {len(expanded)} validators ({', '.join(added)})")
                    active_roles = self._task_roles[task.id] = expanded
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
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.TASK_ESCALATED, correlation_id=self.run_id,
                    task_id=task.id, producer="engine", payload={"reason": gate_reason}))
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
            try:
                candidate = await self.repair_agent.repair_candidate(
                    task=task,
                    previous_candidate=candidate,
                    validation_reports=reports,
                    test_results=test_results,
                    release_bar=self.quality_gate.policy.min_release_score,
                )
            except asyncio.CancelledError:
                await self.cancel_task(task.id, reason="cancelled during repair")
                raise
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

        if self._check_cancelled(task):
            await self.cancel_task(task.id, reason="cancelled before master review")
            return False

        if decision.decision == "APPROVED":
            print(f"[Task {task.id}] Internal reviewer approved; integrating verified candidate.")
            async with self._promotion_lock:
                if fingerprint(source_files(self.workspace_path)) != test_results["base_hash"]:
                    # A different task committed while this one was validating.
                    # Re-execute against the new baseline (bounded by retry/dispatch budgets).
                    await self.task_queue.mark_failed(task.id, "STALE_BASE: replan against updated integration workspace")
                    return False
                if not test_results["all_passed"]:
                    raise ValueError("candidate lacks passing objective evidence")
                if candidate.patch:
                    patch_res = await self.tool_gateway.execute_patch(
                        role="master", patch_text=candidate.patch,
                        idempotency_key=f"{task.id}_{candidate.candidate_id}")
                    if not patch_res.get("success"):
                        await self.task_queue.mark_failed(task.id, patch_res.get("error", "integration failed"))
                        return False
                self.completed_packages.append(package)
                if self.checkpoint_callback is not None:
                    self.checkpoint_callback(self.completed_packages)
                self.persistence._atomic_write_json(self.persistence.run_dir / "packages.json",
                                                     [p.to_dict() for p in self.completed_packages])
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

    async def _review_package(self, task, candidate, package, test_results):
        for state, event in ((TaskStatus.READY_FOR_MASTER, EventType.READY_FOR_MASTER),
                             (TaskStatus.MASTER_REVIEW, EventType.MASTER_REVIEW_STARTED)):
            TaskStateMachine.transition(task, state, reason="Reviewing the verified candidate")
            await self.event_bus.publish(EventEnvelope(event_type=event,
                correlation_id=self.run_id, task_id=task.id,
                candidate_id=candidate.candidate_id, producer="master"))
        path = self.persistence.run_dir / f"review-{candidate.candidate_id}.json"
        pending = {"status": "PENDING_REVIEW", "candidate": candidate.to_dict(),
                   "package": package.to_dict(), "verification": test_results}
        self.persistence._atomic_write_json(path, pending)
        try:
            with self.verifier.reviewed_snapshot(candidate, test_results) as root:
                with self.router.repository_scope(root, self._repository_event):
                    decision = await self.master.review_candidate_package(self.objective, package)
        except asyncio.CancelledError:
            await self.cancel_task(task.id, reason="cancelled during master review")
            raise
        except (ReviewProtocolError, ValueError) as exc:
            reason = f"REVIEW_BLOCKED: {exc}"
            self.persistence._atomic_write_json(path, {**pending, "status": "BLOCKED", "reason": reason})
            await self.task_queue.mark_escalated(task.id, reason=reason)
            await self.event_bus.publish(EventEnvelope(event_type=EventType.TASK_ESCALATED,
                correlation_id=self.run_id, task_id=task.id, candidate_id=candidate.candidate_id,
                producer="master", payload={"reason": reason, "preserved_candidate": str(path)}))
            self.metrics.record_task_escalated()
            return None
        self.persistence._atomic_write_json(path,
            {**pending, "status": decision.decision, "decision": decision.to_dict()})
        self.metrics.record_tokens(decision.token_usage, is_master=True)
        await self.event_bus.publish(EventEnvelope(event_type=EventType.MASTER_REVIEW_COMPLETED,
            correlation_id=self.run_id, task_id=task.id, candidate_id=candidate.candidate_id,
            producer="master", payload=decision.to_dict()))
        return decision

    async def run(self, resume: bool = False) -> Dict[str, Any]:
        """Bounded concurrent DAG execution. No git commit or external publication."""
        self.is_running = True
        previous = self.persistence.load_run_metadata()
        if previous and not resume:
            raise ValueError("run already exists; use resume or a new run ID")
        if previous and previous.get("objective") != self.objective:
            raise ValueError("resume objective differs from persisted run")
        dispatch_file = self.persistence.run_dir / "dispatch.json"
        dispatched = self.persistence._load_json(dispatch_file, {}).get("dispatched", 0)
        errors = []
        no_progress = 0
        try:
            if resume and self.persistence.tasks_file.exists():
                await self.load_and_recover()
            else:
                await self.initialize()
                await self.plan_initial_tasks()
            while self.task_queue.has_pending_work() and not self._cancel_requested:
                while len(self._running_futures) < self.max_parallel_workers and dispatched < self.max_rounds:
                    task = await self.task_queue.pop_ready_task()
                    if task is None:
                        break
                    dispatched += 1
                    self.persistence._atomic_write_json(dispatch_file, {"dispatched": dispatched})
                    future = asyncio.create_task(self.process_task(task), name=f"oma-{task.id}")
                    self._running_futures[future] = task.id
                if not self._running_futures:
                    if dispatched >= self.max_rounds and self.task_queue.has_pending_work():
                        errors.append("DISPATCH_LIMIT: maximum task attempts reached")
                    elif self.task_queue.blocked_count:
                        await self.task_queue.fail_unfulfillable_blocked()
                        errors.append("DEPENDENCY_ERROR: no runnable tasks remain")
                    break
                finished, _ = await asyncio.wait(self._running_futures, return_when=asyncio.FIRST_COMPLETED)
                made_progress = False
                for future in finished:
                    self._running_futures.pop(future, None)
                    made_progress = bool(await future) or made_progress
                no_progress = 0 if made_progress else no_progress + 1
                self.persistence.save_tasks(list(self.task_queue._all_tasks.values()))
                if no_progress >= self.no_progress_limit:
                    errors.append("NO_PROGRESS: consecutive unsuccessful dispatch batches")
                    break
        except asyncio.CancelledError:
            self.request_cancel("operator interrupt")
            errors.append("CANCELLED: operator interrupt")
        except Exception as exc:
            errors.append(str(exc))
        finally:
            for future in self._running_futures:
                future.cancel()
            await asyncio.gather(*self._running_futures, return_exceptions=True)
            self._running_futures.clear()
            if self.task_queue.has_pending_work():
                await self.task_queue.cancel_all("run stopped")
            self.persistence.save_tasks(list(self.task_queue._all_tasks.values()))
            self.is_running = False

        complete = (self.metrics.tasks_total > 0 and
                    self.task_queue.completed_count == self.metrics.tasks_total and not errors)
        status = "COMPLETED" if complete else ("CANCELLED" if self._cancel_requested else "FAILED")
        # A deterministic handoff does not spend another model call to narrate facts.
        self.final_synthesis = "\n".join(
            f"{p.task_id}: {p.solution_summary} | verification profiles {p.tests_passed}/{p.tests_total}; "
            f"validator approvals {p.approvals_count}/{p.validators_count}"
            for p in self.completed_packages) or None
        self.metrics.tasks_completed = self.task_queue.completed_count
        self.metrics.tasks_failed = self.task_queue.failed_count
        metrics = self.metrics.to_dict()
        metrics["budget_accounting"] = self.budget.to_dict()
        history = self.persistence.load_events()
        validations = [e.payload for e in history if e.event_type == EventType.VALIDATION_COMPLETED]
        actual = [r for r in validations if r.get("ran", True)]
        metrics["run_history"] = {
            "scope": "all persisted events across process restarts",
            "validation_attempts": len(actual), "validation_abstentions": len(validations) - len(actual),
            "validation_pass_rate": sum(r.get("status") == "APPROVED" for r in actual) / len(actual) if actual else None,
            "repair_completions": sum(e.event_type == EventType.REPAIR_COMPLETED for e in history),
            "model_calls": sum(e.event_type == EventType.MODEL_RESPONSE for e in history)}
        self.persistence.save_metrics(metrics)
        result = {
            "run_id": self.run_id, "objective": self.objective, "status": status,
            "completed_tasks": self.task_queue.completed_count, "total_tasks": self.metrics.tasks_total,
            "final_synthesis": self.final_synthesis, "errors": errors, "metrics": metrics,
        }
        self.persistence.save_run_metadata(result)
        await self.event_bus.publish(EventEnvelope(
            event_type=EventType.RUN_COMPLETED if complete else EventType.RUN_FAILED,
            correlation_id=self.run_id, producer="engine", payload={"status": status, "errors": errors}))
        return result
