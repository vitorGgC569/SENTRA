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
from .resources import NodeCapabilityManifest, ResourceCapabilityRegistry
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
from .convergence import ConvergencePolicy


# WS1: explicit transient vs permanent classification. Transient delivery
# failures retry with exponential backoff without consuming repair rounds
# or quorum; exhausted retries fail isolated per task. Permanent is the rest.
TRANSIENT_MARKERS = (
    "STALE_CONVERSATION",
    "DELIVERY_EXPIRED",
    "DELIVERY_UNCERTAIN",
    "SUBMISSION_UNCERTAIN",
    # SUBMIT_FAILED é transitório por construção: o gate de aceite só falha
    # com o composer ainda retendo o texto integral após duas tentativas, ou
    # seja, NADA foi enviado e retentar não duplica. Cobre throttling
    # transitório (ex.: cooldown de plano Free após geração longa).
    "SUBMIT_FAILED",
    # FILL_FAILED idem, com mais razão: o submit sequer foi tentado, logo
    # nenhuma mensagem existe para duplicar. Retentar é sempre seguro.
    "FILL_FAILED",
    # NOTA: CONVERSATION_BLOCKED foi removido de propósito — assento travado
    # exige reconcile do operador e nenhum retry automático pode destravar;
    # retentar queimava ~3min de backoff para falhar igual (visto em run live).
    # Falha rápido e isolado com o motivo, operador reconcilia.
    "IN_FLIGHT",
    # NOTA: "UNCERTAIN" puro foi removido de propósito — DELIVERY_UNCERTAIN e
    # SUBMISSION_UNCERTAIN acima já cobrem os casos reais; o marcador genérico
    # reclassificava como transitório qualquer texto com "uncertain" (ex: um
    # veredito de qualidade), adiando o repair correto em retries inúteis.
    "TIMEOUT",
    "TIMED OUT",
    "LEASE_LOST",
    "LEASE_EXPIRED",
    "TAB_STALE",
)


def classify_error(message: str) -> str:
    """Return TRANSIENT for retriable delivery/timeout/lease failures."""
    text = str(message or "").upper()
    for marker in TRANSIENT_MARKERS:
        if marker in text:
            return "TRANSIENT"
    return "PERMANENT"


def is_transient_error(message: str) -> bool:
    return classify_error(message) == "TRANSIENT"


def _has_usable_tasks(tasks) -> bool:
    """Resume poison guard: True when at least one persisted task can be
    recovered or preserves completed work. Empty or only terminal failures
    without any completion means there is nothing to recover."""
    if not tasks:
        return False
    usable = {
        TaskStatus.COMPLETED,
        TaskStatus.PENDING,
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.VALIDATING,
        TaskStatus.REPAIRING,
        TaskStatus.QUALITY_GATE,
        TaskStatus.READY_FOR_MASTER,
        TaskStatus.MASTER_REVIEW,
        TaskStatus.RETRYING,
    }
    for t in tasks:
        try:
            if t.status in usable:
                return True
        except Exception:
            continue
    return False


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
        chat_project: str | None = None,
        conversation_pool_dir=None,
        conversation_namespace=None,
        transient_max_retries: int = 3,
        transient_backoff_base_s: float = 30.0,
        shared_context_bridge=None,
        resource_manifest=None,
        convergence_policy=None,
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
        if convergence_policy is None:
            self.convergence_policy = ConvergencePolicy(
                max_rounds=max_rounds,
                no_progress_limit=no_progress_limit,
            )
        elif isinstance(convergence_policy, dict):
            self.convergence_policy = ConvergencePolicy(
                max_rounds=max_rounds,
                no_progress_limit=no_progress_limit,
                **convergence_policy,
            )
        elif isinstance(convergence_policy, ConvergencePolicy):
            self.convergence_policy = convergence_policy
        else:
            raise TypeError("convergence_policy must be a ConvergencePolicy or dict")
        if type(transient_max_retries) is not int or not 0 <= transient_max_retries <= 10:
            raise ValueError("transient_max_retries must be an int 0..10")
        if not isinstance(transient_backoff_base_s, (int, float)) or not 0 <= float(transient_backoff_base_s) <= 600:
            raise ValueError("transient_backoff_base_s must be 0..600 seconds")
        self.transient_max_retries = transient_max_retries
        self.transient_backoff_base_s = float(transient_backoff_base_s)
        self._running_futures = {}
        self._timeout_cancellations: set[str] = set()
        self.checkpoint_callback = checkpoint_callback
        self.task_token_budget = task_token_budget
        self.max_repair_rounds = max_repair_rounds
        self.compute_policy = compute_policy
        self._task_roles = {}
        if resource_manifest is None:
            extra_capabilities = {"browser", "persistent_conversations"} if fixed_conversations else set()
            self.resource_manifest = NodeCapabilityManifest.probe_local(
                self.workspace_path,
                max_concurrency=max_parallel_workers,
                extra=extra_capabilities,
            )
        elif isinstance(resource_manifest, dict):
            self.resource_manifest = NodeCapabilityManifest.from_dict(resource_manifest)
        elif isinstance(resource_manifest, NodeCapabilityManifest):
            self.resource_manifest = resource_manifest
        else:
            raise TypeError("resource_manifest must be a NodeCapabilityManifest or dict")
        self.resource_registry = ResourceCapabilityRegistry()
        self.resource_registry.upsert(self.resource_manifest)

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
        self.router.decision_trace_sink = lambda data: self.persistence.append_event(EventEnvelope(
            event_type=EventType.DECISION_ADVISORY, correlation_id=self.run_id,
            task_id=data.get("task_id"), candidate_id=data.get("candidate_id"),
            producer="decisioning", payload=data))
        # Five initial seats plus cause-based standby validators. Wrap BEFORE
        # agents are built: they keep this reference, including planner/repair.
        # max_seats é o TETO DE CRIAÇÃO DE CHATS (rate limit conta conversas,
        # não mensagens) — deliberadamente desacoplado de compute_policy.max_agents.
        self.fixed_conversations = bool(fixed_conversations)
        self.inter_call_delay_s = max(0.0, float(inter_call_delay_s or 0.0))
        if type(max_seats) is not int or not 1 <= max_seats <= 8:
            raise ValueError("max_seats must be an int 1..8")
        self.max_seats = max_seats
        self.chat_project = str(chat_project or "").strip() or None
        if self.fixed_conversations:
            from .conversation_pool import FixedConversationRouter
            self.router = FixedConversationRouter(
                self.router, run_id=conversation_namespace or self.run_id,
                store_dir=conversation_pool_dir or self.persistence.run_dir,
                inter_call_delay_s=self.inter_call_delay_s,
                max_seats=self.max_seats,
                chat_project=self.chat_project,
                shared_context_bridge=shared_context_bridge,
            )

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
        if (
            event.task_id
            and event.event_type not in {EventType.TASK_HEARTBEAT, EventType.TASK_STALLED}
        ):
            task = self.task_queue.get_task(event.task_id)
            if task is not None:
                now = time.time()
                was_stalled = task.metadata.get("scheduler_state") == "SUSPECTED_STALL"
                task.metadata["heartbeat_at"] = now
                task.metadata["heartbeat_stage"] = (
                    event.event_type.value
                    if isinstance(event.event_type, EventType)
                    else str(event.event_type)
                )
                if was_stalled:
                    task.metadata["scheduler_state"] = "RUNNING"
                    task.metadata["stall_recovered_at"] = now
                    task.metadata.pop("heartbeat_stale_at", None)

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

    def _transient_delay(self, attempt: int) -> float:
        """Exponential backoff for transient retries: base * 2**attempt."""
        try:
            base = float(self.transient_backoff_base_s)
        except Exception:
            base = 30.0
        return max(0.0, base * (2.0 ** max(0, attempt)))

    async def _decision_allows_transient_retry(
        self, label: str, attempt: int, error: Exception,
    ) -> bool:
        """Optional System One advisory that may only *reduce* safe retries.

        Deterministic SENTRA policy classifies the error first. This hook is
        never called for UNCERTAIN/BLOCKED/reconcile paths and can never expand
        the configured retry budget.
        """
        controller = getattr(self.router, "decision_controller", None)
        enabled = bool(getattr(self.router, "decision_retry_enabled", False))
        if controller is None or not enabled:
            return True
        selection = await controller.choose(
            state={
                "operation": label,
                "attempt": attempt + 1,
                "max_retries": self.transient_max_retries,
                "next_backoff_s": self._transient_delay(attempt),
                "error": str(error)[:1000],
                "classification": "SAFE_TRANSIENT",
            },
            instructions=(
                "This failure has already been classified by deterministic SENTRA policy as safe to retry. "
                "Choose retry only if another bounded attempt is worthwhile; choose abort to stop early. "
                "You cannot increase the retry budget or override delivery-safety policy."
            ),
            criteria={
                "retry": "Use the existing bounded retry with configured exponential backoff.",
                "abort": "Stop retrying this operation early and surface the failure.",
            },
            default="retry",
            question_id="retry_action",
            min_confidence=getattr(self.router, "decision_min_confidence", 0.35),
        )
        sink = getattr(self.router, "decision_trace_sink", None)
        if sink is not None:
            try:
                sink({
                    "kind": "transient_retry",
                    "operation": label,
                    "attempt": attempt + 1,
                    "selected": selection.value,
                    "confidence": selection.confidence,
                    "source": selection.source,
                    "model": selection.model,
                    "deterministic_fallback": selection.used_deterministic_fallback,
                })
            except Exception:
                pass
        return selection.value != "abort"

    async def _with_transient_retry(self, label: str, func, *args, **kwargs):
        """Retry transient delivery failures with backoff without consuming
        repair rounds or quorum. Permanent errors raise immediately. A typed
        decision model may stop a retry early, but can never authorize one that
        deterministic policy did not already classify as safe."""
        attempt = 0
        while True:
            try:
                return await func(*args, **kwargs)
            except asyncio.CancelledError:
                raise
            except (TimeoutError, asyncio.TimeoutError) as exc:
                if attempt >= self.transient_max_retries:
                    raise RuntimeError(f"[TIMEOUT] {label}: {exc}") from exc
                if not await self._decision_allows_transient_retry(label, attempt, exc):
                    raise RuntimeError(f"[DECISION_ABORT] {label}: {exc}") from exc
                delay = self._transient_delay(attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                attempt += 1
                continue
            except Exception as exc:
                if not is_transient_error(str(exc)):
                    raise
                if attempt >= self.transient_max_retries:
                    raise
                if not await self._decision_allows_transient_retry(label, attempt, exc):
                    raise RuntimeError(f"[DECISION_ABORT] {label}: {exc}") from exc
                delay = self._transient_delay(attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                attempt += 1
                continue

    def _collect_task_errors(self) -> Dict[str, str]:
        """Per-task error map for partial runs. Siblings keep their own
        outcome; only strictly unreachable dependents carry DEPENDENCY_ERROR."""
        dlq = {}
        try:
            for entry in self.task_queue.get_dlq():
                tid = entry.get("task_id")
                if tid and tid not in dlq:
                    dlq[tid] = str(entry.get("error", ""))
        except Exception:
            pass
        out: Dict[str, str] = {}
        for tid, task in list(self.task_queue._all_tasks.items()):
            try:
                st = task.status
            except Exception:
                continue
            if st not in (TaskStatus.FAILED, TaskStatus.ESCALATED, TaskStatus.CANCELLED):
                continue
            reason = dlq.get(tid, "")
            if not reason:
                try:
                    hist = (task.metadata or {}).get("transition_history", []) or []
                    if hist:
                        reason = str(hist[-1].get("reason", "") or hist[-1].get("to", ""))
                except Exception:
                    reason = ""
            if not reason:
                try:
                    reason = st.value
                except Exception:
                    reason = str(st)
            out[tid] = reason
        return out

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

    @staticmethod
    def _critical_task(task: Task) -> bool:
        priority = str(getattr(getattr(task, "priority", ""), "value",
                               getattr(task, "priority", "")) or "").upper()
        risk = str(getattr(task, "risk", "") or "").upper()
        return priority == "CRITICAL" or risk in {"HIGH", "CRITICAL"}

    async def _decision_select_validator_expansion(
        self,
        task: Task,
        active: List[ValidatorRole],
        expanded: List[ValidatorRole],
        reports: List[ValidationReport],
        gate_reason: str,
    ) -> List[ValidatorRole]:
        """Optionally add one model-selected standby validator this round.

        Existing validators are never removed. Critical/high-risk tasks keep the
        full deterministic expansion. If the decision backend is unavailable,
        malformed or below confidence, the historical full expansion is kept.
        """
        controller = getattr(self.router, "decision_controller", None)
        enabled = bool(getattr(self.router, "decision_validator_selection_enabled", False))
        current = list(active)
        added = [role for role in expanded if role not in current]
        if (not enabled or controller is None or len(added) <= 1
                or self._critical_task(task)):
            return expanded

        descriptions = {
            ValidatorRole.EDGE_CASES: "Boundary conditions, null/empty values, concurrency and interruption.",
            ValidatorRole.SECURITY: "Trust boundaries, least privilege, secret handling and abuse resistance.",
            ValidatorRole.PERFORMANCE: "Unbounded work, latency, I/O and memory behavior.",
            ValidatorRole.LOGIC: "State transitions, invariants and falsifiable logic defects.",
            ValidatorRole.REQUIREMENTS: "Acceptance criteria, missing behavior and scope drift.",
            ValidatorRole.ADVERSARIAL: "Hostile inputs, bypasses, stale state and retry scenarios.",
        }
        criteria = {
            role.value: descriptions.get(role, role.value)
            for role in added
        }
        selection = await controller.choose(
            state={
                "task": {
                    "id": task.id,
                    "objective": str(getattr(task, "objective", ""))[:3000],
                    "priority": str(getattr(getattr(task, "priority", ""), "value",
                                            getattr(task, "priority", ""))),
                    "risk": str(getattr(task, "risk", "")),
                },
                "gate_reason": gate_reason[:2000],
                "active_validators": [role.value for role in current],
                "candidate_standby": [role.value for role in added],
                "reports": [
                    {
                        "role": report.validator_role,
                        "status": report.status,
                        "confidence": report.confidence,
                        "score": report.score,
                        "findings": len(report.findings),
                    }
                    for report in reports if report.ran
                ],
            },
            instructions=(
                "Choose the single most useful additional validator for the next round. "
                "The deterministic quality gate remains authoritative; do not remove or replace "
                "validators already active."
            ),
            criteria=criteria,
            default=added[0].value,
            question_id="next_validator",
            min_confidence=getattr(self.router, "decision_min_confidence", 0.35),
        )
        if selection.used_deterministic_fallback:
            return expanded
        chosen = next((role for role in added if role.value == selection.value), None)
        if chosen is None:
            return expanded

        result = current + [chosen]
        sink = getattr(self.router, "decision_trace_sink", None)
        if sink is not None:
            try:
                sink({
                    "kind": "validator_selection",
                    "task_id": task.id,
                    "candidate_id": reports[0].candidate_id if reports else None,
                    "selected": chosen.value,
                    "deferred": [role.value for role in added if role != chosen],
                    "active": [role.value for role in current],
                    "confidence": selection.confidence,
                    "probabilities": dict(selection.probabilities),
                    "source": selection.source,
                    "model": selection.model,
                    "deterministic_fallback": False,
                    "safety": "existing validators preserved; critical tasks bypass model reduction",
                })
            except Exception:
                pass
        return result

    async def _decision_quality_advisory(
        self,
        task: Task,
        candidate: Candidate,
        reports: List[ValidationReport],
        test_results: Dict[str, Any],
        passed_gate: bool,
        gate_reason: str,
    ) -> Optional[Dict[str, Any]]:
        """Record a typed readiness score without changing gate authority."""
        controller = getattr(self.router, "decision_controller", None)
        enabled = bool(getattr(self.router, "decision_quality_advisory_enabled", False))
        if not enabled or controller is None:
            return None
        levels = [
            "not ready; substantial correctness or evidence gaps",
            "weak; major review still required",
            "mixed; some evidence but important uncertainty remains",
            "strong; likely ready pending deterministic gate",
            "very strong; evidence is internally consistent and complete",
        ]
        score, confidence, source = await controller.score(
            state={
                "task": {
                    "id": task.id,
                    "objective": str(getattr(task, "objective", ""))[:3000],
                    "priority": str(getattr(getattr(task, "priority", ""), "value",
                                            getattr(task, "priority", ""))),
                    "risk": str(getattr(task, "risk", "")),
                },
                "deterministic_gate": {
                    "passed": bool(passed_gate),
                    "reason": gate_reason[:2000],
                },
                "tests": {
                    "all_passed": bool((test_results or {}).get("all_passed")),
                    "checks_ran": (test_results or {}).get("checks_ran"),
                    "failed_commands": (test_results or {}).get("failed_commands", []),
                },
                "validators": [
                    {
                        "role": report.validator_role,
                        "status": report.status,
                        "ran": report.ran,
                        "confidence": report.confidence,
                        "score": report.score,
                        "critical_findings": report.has_critical_findings(),
                    }
                    for report in reports
                ],
            },
            instructions=(
                "Rate candidate readiness as an advisory signal only. The deterministic SENTRA "
                "Quality Gate is authoritative and this score must not override it."
            ),
            criteria=levels,
            default_score=4.0 if passed_gate else 0.0,
            question_id="candidate_readiness",
        )
        payload = {
            "kind": "quality_readiness",
            "task_id": task.id,
            "candidate_id": candidate.candidate_id,
            "score": score,
            "max_score": float(len(levels) - 1),
            "normalized_score": score / float(len(levels) - 1),
            "confidence": confidence,
            "source": source,
            "deterministic_gate_passed": bool(passed_gate),
            "gate_reason": gate_reason,
            "authoritative": False,
        }
        sink = getattr(self.router, "decision_trace_sink", None)
        if sink is not None:
            try:
                sink(payload)
            except Exception:
                pass
        return payload

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
        recovered = self.task_queue.recover_incomplete_tasks()
        self.persistence.save_tasks(list(self.task_queue._all_tasks.values()))
        for task in self.task_queue._all_tasks.values():
            if task.status == TaskStatus.ESCALATED and task.metadata.get("recovery_required"):
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.TASK_ESCALATED,
                    correlation_id=self.run_id,
                    task_id=task.id,
                    producer="reconciler",
                    payload={
                        "reason": task.metadata.get("recovery_reason"),
                        "idempotency_key": task.idempotency_key,
                        "side_effect_scope": task.side_effect_scope,
                        "recovery_required": True,
                    },
                ))
        return recovered

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

    def _program_memory_brief(self) -> str:
        """Recall program memory (ADRs + lessons) for the planner context.

        Fail-open: empty/corrupt memory contributes nothing, never raises.
        """
        try:
            from .program_memory import ProgramMemory
            hits = ProgramMemory(self.workspace_path).recall(self.objective, limit=5)
        except Exception:
            return ""
        lines = [f"- [{h.get('kind', '?')}:{h.get('ref', '?')}] "
                 f"{h.get('snippet', '')}"[:400] for h in hits or []]
        brief = "\n".join(lines)[:2000]
        return f"\n\n## Program memory (decisoes e licoes de runs anteriores)\n{brief}\n" if brief else ""

    async def plan_initial_tasks(self) -> List[Task]:
        print(f"\n[+] [OMA Engine] Planning task decomposition for Run: {self.run_id}")
        repo_summary = await self.tool_gateway.git_manager.inspect_repository()
        repo_summary = (repo_summary or "") + self._program_memory_brief()
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
        from .milestones import validate_contracts
        violations = validate_contracts(tasks)
        if violations:
            detail = "; ".join(
                f"{v.consumer_id}:{v.kind}:{v.artifact}" for v in violations[:10])
            raise ValueError(f"DEPENDENCY_ERROR: task contract violations: {detail}")
        print(f"[+] [OMA Engine] Queued {len(tasks)} subtasks into PriorityTaskQueue.")
        return tasks

    def _capture_candidate_renders(self, task, candidate, root, evidence) -> None:
        """Render HTML targets of the applied candidate for validator review.

        Best-effort visual evidence: captures land in runs/<id>/evidence/ and
        their paths go to task.metadata["images"] (attached to validator
        calls) plus evidence["visual_evidence"] (machine-readable manifest).
        Absence is recorded honestly, never raised.
        """
        try:
            from .visual_evidence import capture_task_renders
            from pathlib import Path as _Path
            targets = [t for t in (getattr(task, "target_files", None) or [])
                       if str(t).lower().endswith((".html", ".htm"))]
            if not targets:
                evidence["visual_evidence"] = {"files": [], "note": "no HTML targets"}
                return
            dest = self.persistence.run_dir / "evidence"
            recs = capture_task_renders(
                [str(_Path(root) / t) for t in targets], dest)
            paths = [r["path"] for r in recs if r.get("path")]
            if paths:
                task.metadata["images"] = paths
            evidence["visual_evidence"] = {
                "files": [{"path": r["path"], "sha256": r.get("sha256", ""),
                           "bytes": r.get("bytes", 0)} for r in recs]}
        except Exception as exc:  # noqa: BLE001 - evidence must never break verification
            try:
                evidence["visual_evidence"] = {"files": [], "error": str(exc)[:200]}
            except Exception:
                pass

    def _reset_provider_breakers(self) -> None:
        """Isolation: one task tripping the provider circuit must not poison
        siblings. Each task starts with a fresh breaker view; the breaker still
        protects within a task (rapid consecutive failures still open it for
        that task's remaining attempts)."""
        try:
            router = self.router
            inner = getattr(router, "_inner", None)
            target = inner if inner is not None else router
            breakers = getattr(target, "circuit_breakers", None)
            if isinstance(breakers, dict):
                for breaker in breakers.values():
                    try:
                        breaker.record_success()
                    except Exception:
                        pass
        except Exception:
            pass

    async def _task_heartbeat(self, task: Task, stage: str) -> None:
        """Record scheduler progress without treating a stale heartbeat as abort proof."""
        now = time.time()
        previous_stage = str(task.metadata.get("heartbeat_stage") or "")
        was_stalled = task.metadata.get("scheduler_state") == "SUSPECTED_STALL"
        task.metadata["heartbeat_at"] = now
        task.metadata["heartbeat_stage"] = str(stage)
        if was_stalled:
            task.metadata["scheduler_state"] = "RUNNING"
            task.metadata["stall_recovered_at"] = now
            task.metadata.pop("heartbeat_stale_at", None)
        if previous_stage != stage or was_stalled:
            await self.event_bus.publish(EventEnvelope(
                event_type=EventType.TASK_HEARTBEAT,
                correlation_id=self.run_id,
                task_id=task.id,
                producer="scheduler",
                payload={
                    "stage": str(stage),
                    "recovered_from_stall": was_stalled,
                },
            ))

    async def _mark_task_stalled(self, task: Task, *, stale_for_s: float) -> None:
        if task.metadata.get("scheduler_state") == "SUSPECTED_STALL":
            return
        now = time.time()
        task.metadata["scheduler_state"] = "SUSPECTED_STALL"
        task.metadata["heartbeat_stale_at"] = now
        await self.event_bus.publish(EventEnvelope(
            event_type=EventType.TASK_STALLED,
            correlation_id=self.run_id,
            task_id=task.id,
            producer="scheduler",
            payload={
                "stage": task.metadata.get("heartbeat_stage"),
                "stale_for_s": stale_for_s,
                "heartbeat_timeout_s": float(
                    getattr(task, "heartbeat_timeout_s", 120.0) or 120.0
                ),
                "action": "observe_only",
                "reason": (
                    "heartbeat stale; no cancellation or retry is authorized "
                    "until total timeout/reconciliation"
                ),
            },
        ))

    async def process_task(self, task: Task) -> bool:
        self.budget.register_task(task.id, task.token_budget)
        self._reset_provider_breakers()
        timeout_s = float(getattr(task, "timeout_s", 900.0) or 900.0)
        task.metadata["scheduler_started_at"] = time.time()
        task.metadata["heartbeat_at"] = task.metadata["scheduler_started_at"]
        task.metadata["scheduler_state"] = "RUNNING"
        with self.router.repository_scope(self.workspace_path, self._repository_event):
            inner = asyncio.create_task(self._process_task(task), name=f"oma-inner-{task.id}")
            try:
                heartbeat_timeout_s = float(
                    getattr(task, "heartbeat_timeout_s", 120.0) or 120.0
                )
                probe_interval_s = max(
                    0.01,
                    min(5.0, heartbeat_timeout_s / 3.0),
                )
                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout_s
                done: set[asyncio.Task] = set()
                while loop.time() < deadline:
                    remaining = max(0.0, deadline - loop.time())
                    done, _ = await asyncio.wait(
                        {inner},
                        timeout=min(probe_interval_s, remaining),
                    )
                    if inner in done:
                        result = await inner
                        if task.metadata.get("scheduler_state") == "SUSPECTED_STALL":
                            task.metadata["stall_recovered_at"] = time.time()
                        task.metadata["scheduler_state"] = "FINISHED"
                        task.metadata["heartbeat_at"] = time.time()
                        return result
                    stale_for_s = max(
                        0.0,
                        time.time() - float(
                            task.metadata.get("heartbeat_at")
                            or task.metadata["scheduler_started_at"]
                        ),
                    )
                    if stale_for_s >= heartbeat_timeout_s:
                        await self._mark_task_stalled(
                            task,
                            stale_for_s=stale_for_s,
                        )

                # A timeout is not proof that a remote/model side effect stopped.
                # Mark the local coroutine as timeout-driven before cancelling it,
                # so nested CancelledError handlers do not report operator cancel.
                self._timeout_cancellations.add(task.id)
                task.metadata["timeout_uncertain"] = True
                task.metadata["timeout_s"] = timeout_s
                task.metadata["scheduler_state"] = "TIMEOUT_UNCERTAIN"
                task.metadata["heartbeat_at"] = time.time()
                inner.cancel()
                await asyncio.gather(inner, return_exceptions=True)
                reason = (
                    f"TIMEOUT_UNCERTAIN: task exceeded {timeout_s:g}s; "
                    "remote side effects must be reconciled before retry"
                )
                await self.task_queue.mark_escalated(task.id, reason=reason)
                self.metrics.record_task_escalated()
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.TASK_ESCALATED,
                    correlation_id=self.run_id,
                    task_id=task.id,
                    producer="scheduler",
                    payload={
                        "reason": reason,
                        "timeout_s": timeout_s,
                        "side_effect_scope": getattr(task, "side_effect_scope", "ISOLATED"),
                        "resource_locks": sorted(getattr(task, "resource_locks", [])),
                    },
                ))
                return False
            except asyncio.CancelledError:
                if not inner.done():
                    inner.cancel()
                    await asyncio.gather(inner, return_exceptions=True)
                await self.cancel_task(task.id, reason="cancelled")
                raise
            except Exception as exc:
                if not inner.done():
                    inner.cancel()
                    await asyncio.gather(inner, return_exceptions=True)
                await self.task_queue.mark_failed(task.id, str(exc), retryable=False)
                self.metrics.record_task_failed()
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.TASK_FAILED, correlation_id=self.run_id,
                    task_id=task.id, producer="engine", payload={"reason": str(exc)}))
                return False
            finally:
                self._timeout_cancellations.discard(task.id)
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
        await self._task_heartbeat(task, "started")

        task_mem = self.memory.get_task_memory(task.id)

        # 1. Semantic Cache check
        # Objective-only caches cannot safely reuse patches from a different baseline.
        cached_candidate = None
        if cached_candidate:
            print(f"[Task {task.id}] Cache HIT! Reusing candidate {cached_candidate.candidate_id}")
            candidate = cached_candidate
        else:
            # 2. Execution phase (CancelledError propagates -> caller handles RF-017)
            # Transient delivery failures retry with backoff here without
            # consuming repair rounds or quorum; exhausted retries raise for
            # isolated per-task failure.
            try:
                await self._task_heartbeat(task, "executor")
                context_summary = f"Objective: {task.objective}\nDescription: {task.description}"
                candidate = await self._with_transient_retry(
                    "executor", self.executor.execute_task, task, context_summary=context_summary)
                await self._task_heartbeat(task, "candidate_created")
            except asyncio.CancelledError:
                if task.id not in self._timeout_cancellations:
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
                        self._capture_candidate_renders(task, candidate, root, evidence)
                        return await self.validator_pool.validate_candidate(
                            task=task, candidate=candidate, roles=active_roles,
                            test_results=evidence)
                try:
                    await self._task_heartbeat(task, "validation")
                    test_results = await self.verifier.verify(candidate, inspect=inspect_candidate,
                                                             event_sink=self._repository_event)
                    reports = test_results.pop("_reports")
                    await self._task_heartbeat(task, "validation_complete")
                    self.persistence._atomic_write_json(
                        self.persistence.run_dir / f"verification-{candidate.candidate_id}.json", test_results)
                except asyncio.CancelledError:
                    if task.id not in self._timeout_cancellations:
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
                await self._decision_quality_advisory(
                    task, candidate, reports, test_results, passed_gate, gate_reason
                )

            # 3b. Validators abstained (infra failure, not evidence): retry the
            # VALIDATION boundedly. Never burns a repair round on the candidate.
            # Transient delivery failures use oma.transient_* budget with backoff;
            # permanent infra keeps the historic bound of 2 retries.
            if gate_reason.startswith("INSUFFICIENT_VALIDATION"):
                await self.event_bus.publish(EventEnvelope(
                    event_type=EventType.QUALITY_GATE_FAILED, correlation_id=self.run_id,
                    task_id=task.id, candidate_id=candidate.candidate_id, producer="quality_gate",
                    payload={"reason": gate_reason}))
                transient_validation = is_transient_error(gate_reason) or any(
                    (not r.ran) and is_transient_error(getattr(r, "error", ""))
                    for r in reports)
                allowed_validation = self.transient_max_retries if transient_validation else max_validation_retries
                if validation_retries < allowed_validation and not self._check_cancelled(task):
                    validation_retries += 1
                    if transient_validation:
                        delay = self._transient_delay(validation_retries - 1)
                        if delay > 0:
                            await asyncio.sleep(delay)
                    print(f"[Task {task.id}] {gate_reason} Retrying validation "
                          f"({validation_retries}/{allowed_validation}) without consuming a repair round...")
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
                current_roles = list(
                    active_roles
                    or self._task_roles.get(task.id)
                    or self.compute_policy.initial_for_task(task)
                )
                expanded = self._expand_validators(task, reports, gate_reason)
                expanded = await self._decision_select_validator_expansion(
                    task, current_roles, expanded, reports, gate_reason
                )
                if len(expanded) > len(current_roles):
                    added = [r.value for r in expanded if r not in current_roles]
                    print(f"[Task {task.id}] Escalating compute: "
                          f"{len(current_roles)} -> {len(expanded)} validators ({', '.join(added)})")
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

            # Repair Agent produces new candidate version. Transient delivery
            # failures retry here with backoff without consuming an extra
            # repair round beyond the one already counted above.
            try:
                await self._task_heartbeat(task, "repair")
                candidate = await self._with_transient_retry(
                    "repair",
                    self.repair_agent.repair_candidate,
                    task=task,
                    previous_candidate=candidate,
                    validation_reports=reports,
                    test_results=test_results,
                    release_bar=self.quality_gate.policy.min_release_score,
                )
                await self._task_heartbeat(task, "repair_complete")
            except asyncio.CancelledError:
                if task.id not in self._timeout_cancellations:
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
        attempt = 0
        await self._task_heartbeat(task, "master_review")
        while True:
            try:
                with self.verifier.reviewed_snapshot(candidate, test_results) as root:
                    with self.router.repository_scope(root, self._repository_event):
                        decision = await self.master.review_candidate_package(self.objective, package)
                await self._task_heartbeat(task, "master_review_complete")
                break
            except asyncio.CancelledError:
                if task.id not in self._timeout_cancellations:
                    await self.cancel_task(task.id, reason="cancelled during master review")
                raise
            except (ReviewProtocolError, ValueError, TimeoutError, asyncio.TimeoutError) as exc:
                if is_transient_error(str(exc)) and attempt < self.transient_max_retries:
                    delay = self._transient_delay(attempt)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    attempt += 1
                    continue
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

    def _evaluate_convergence(
        self,
        *,
        dispatched: int,
        no_progress_rounds: int,
        marginal_gain: float | None,
    ):
        terminal = {
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
            TaskStatus.FAILED,
            TaskStatus.ESCALATED,
        }
        tasks = list(self.task_queue._all_tasks.values())
        unfinished = [task for task in tasks if task.status not in terminal]
        objective_satisfied = bool(tasks) and all(
            task.status == TaskStatus.COMPLETED for task in tasks
        )
        requires_human = any(
            bool(task.metadata.get("requires_human_decision"))
            for task in unfinished
        )
        speculative_only = bool(unfinished) and all(
            bool(task.metadata.get("speculative_only"))
            for task in unfinished
        )
        return self.convergence_policy.evaluate(
            objective_satisfied=objective_satisfied,
            dispatched=dispatched,
            pending_work=self.task_queue.has_pending_work(),
            ready_work=bool(self.task_queue._ready_queue),
            in_flight=bool(self._running_futures),
            no_progress_rounds=no_progress_rounds,
            marginal_gain=marginal_gain,
            budget_exhausted=self.budget.exhausted("secondary"),
            speculative_only=speculative_only,
            requires_human=requires_human,
        )

    async def _record_convergence(self, decision) -> dict[str, Any]:
        payload = {
            "stop": bool(decision.stop),
            "code": str(decision.code),
            "reason": str(decision.reason),
            "details": dict(decision.details),
            "policy": self.convergence_policy.to_dict(),
            "recorded_at": time.time(),
        }
        self.persistence._atomic_write_json(
            self.persistence.run_dir / "convergence.json",
            payload,
        )
        await self.event_bus.publish(EventEnvelope(
            event_type=EventType.CONVERGENCE_STOPPED,
            correlation_id=self.run_id,
            producer="convergence_policy",
            payload=payload,
        ))
        return payload

    async def run(self, resume: bool = False) -> Dict[str, Any]:
        """Bounded concurrent DAG execution. No git commit or external publication.

        Isolation: one task failure never fails DAG siblings; only strictly
        unreachable dependents fail with DEPENDENCY_ERROR. Partial runs report
        PARTIAL with per-task errors. Resume with missing/empty/unusable
        tasks.json replans from the objective instead of silent FAILED.
        """
        self.is_running = True
        previous = self.persistence.load_run_metadata()
        if previous and not resume:
            raise ValueError("run already exists; use resume or a new run ID")
        if previous and previous.get("objective") != self.objective:
            raise ValueError("resume objective differs from persisted run")
        dispatch_file = self.persistence.run_dir / "dispatch.json"
        dispatched = self.persistence._load_json(dispatch_file, {}).get("dispatched", 0)
        errors: List[str] = []
        no_progress = 0
        convergence_stop: dict[str, Any] | None = None
        try:
            if resume:
                # Poisoned resume guard: missing, empty or without any usable
                # task means there is nothing to recover, replan from objective.
                needs_replan = False
                if not self.persistence.tasks_file.exists():
                    needs_replan = True
                else:
                    persisted = self.persistence.load_tasks()
                    if not _has_usable_tasks(persisted):
                        needs_replan = True
                if needs_replan:
                    await self.initialize()
                    await self.plan_initial_tasks()
                    dispatched = 0
                    self.persistence._atomic_write_json(dispatch_file, {"dispatched": dispatched})
                else:
                    await self.load_and_recover()
            else:
                await self.initialize()
                await self.plan_initial_tasks()
            while self.task_queue.has_pending_work() and not self._cancel_requested:
                while len(self._running_futures) < self.max_parallel_workers and dispatched < self.max_rounds:
                    task = await self.task_queue.pop_ready_task(
                        available_capabilities=set(self.resource_manifest.capabilities),
                        node_id=self.resource_manifest.node_id,
                    )
                    if task is None:
                        break
                    dispatched += 1
                    self.persistence._atomic_write_json(dispatch_file, {"dispatched": dispatched})
                    future = asyncio.create_task(self.process_task(task), name=f"oma-{task.id}")
                    self._running_futures[future] = task.id
                if not self._running_futures:
                    missing_by_task = self.task_queue.unsatisfied_capabilities(
                        set(self.resource_manifest.capabilities)
                    )
                    if missing_by_task:
                        for task_id, missing in sorted(missing_by_task.items()):
                            reason = (
                                "CAPABILITY_MISSING: "
                                + ",".join(missing)
                                + f" on node {self.resource_manifest.node_id}"
                            )
                            await self.task_queue.mark_escalated(task_id, reason=reason)
                            self.metrics.record_task_escalated()
                            await self.event_bus.publish(EventEnvelope(
                                event_type=EventType.TASK_ESCALATED,
                                correlation_id=self.run_id,
                                task_id=task_id,
                                producer="scheduler",
                                payload={
                                    "reason": reason,
                                    "missing_capabilities": missing,
                                    "node": self.resource_manifest.to_dict(),
                                },
                            ))
                            errors.append(f"{task_id}: {reason}")
                        continue
                    decision = self._evaluate_convergence(
                        dispatched=dispatched,
                        no_progress_rounds=no_progress,
                        marginal_gain=None,
                    )
                    if decision.stop:
                        convergence_stop = await self._record_convergence(decision)
                        if decision.code != "OBJECTIVE_SATISFIED":
                            errors.append(f"{decision.code}: {decision.reason}")
                        break
                    if self.task_queue.blocked_count:
                        await self.task_queue.fail_unfulfillable_blocked()
                        errors.append("DEPENDENCY_ERROR: no runnable tasks remain")
                    break
                completed_before = self.task_queue.completed_count
                finished, _ = await asyncio.wait(self._running_futures, return_when=asyncio.FIRST_COMPLETED)
                made_progress = False
                for future in finished:
                    self._running_futures.pop(future, None)
                    made_progress = bool(await future) or made_progress
                no_progress = 0 if made_progress else no_progress + 1
                completed_after = self.task_queue.completed_count
                total_known = max(1, len(self.task_queue._all_tasks))
                marginal_gain = max(
                    0.0,
                    (completed_after - completed_before) / total_known,
                )
                self.persistence.save_tasks(list(self.task_queue._all_tasks.values()))
                decision = self._evaluate_convergence(
                    dispatched=dispatched,
                    no_progress_rounds=no_progress,
                    marginal_gain=marginal_gain,
                )
                if decision.stop:
                    convergence_stop = await self._record_convergence(decision)
                    if decision.code != "OBJECTIVE_SATISFIED":
                        errors.append(f"{decision.code}: {decision.reason}")
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

        if convergence_stop is None and not self._cancel_requested:
            final_decision = self._evaluate_convergence(
                dispatched=dispatched,
                no_progress_rounds=no_progress,
                marginal_gain=None,
            )
            if final_decision.stop:
                convergence_stop = await self._record_convergence(final_decision)
                if final_decision.code != "OBJECTIVE_SATISFIED":
                    marker = f"{final_decision.code}: {final_decision.reason}"
                    if marker not in errors:
                        errors.append(marker)

        task_error_map = self._collect_task_errors()
        for tid in sorted(task_error_map):
            errors.append(f"{tid}: {task_error_map[tid]}")
        completed_count = self.task_queue.completed_count
        total_tasks = self.metrics.tasks_total
        if self._cancel_requested:
            status = "CANCELLED"
            complete = False
        elif total_tasks > 0 and completed_count == total_tasks and not errors:
            status = "COMPLETED"
            complete = True
        elif completed_count > 0 and completed_count < total_tasks:
            status = "PARTIAL"
            complete = False
        else:
            status = "FAILED"
            complete = False
        # A deterministic handoff does not spend another model call to narrate facts.
        self.final_synthesis = "\n".join(
            f"{p.task_id}: {p.solution_summary} | verification profiles {p.tests_passed}/{p.tests_total}; "
            f"validator approvals {p.approvals_count}/{p.validators_count}"
            for p in self.completed_packages) or None
        self.metrics.tasks_completed = self.task_queue.completed_count
        self.metrics.tasks_failed = self.task_queue.failed_count
        metrics = self.metrics.to_dict()
        metrics["budget_accounting"] = self.budget.to_dict()
        metrics["convergence_policy"] = self.convergence_policy.to_dict()
        metrics["convergence_stop"] = convergence_stop
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
            "completed_tasks": completed_count, "total_tasks": total_tasks,
            "final_synthesis": self.final_synthesis, "errors": errors,
            "task_errors": dict(task_error_map), "metrics": metrics,
            "convergence": convergence_stop,
        }
        self.persistence.save_run_metadata(result)
        await self.event_bus.publish(EventEnvelope(
            event_type=EventType.RUN_COMPLETED if complete else EventType.RUN_FAILED,
            correlation_id=self.run_id, producer="engine", payload={"status": status, "errors": errors}))
        return result
