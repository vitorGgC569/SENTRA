from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Dict, List, Optional

from ..providers.base import AgentProvider, AgentRequest, AgentResponse
from ..models import TaskPriority


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Circuit breaker protecting against failing or rate-limited model providers.
    Implements CLOSED -> OPEN -> HALF_OPEN states as specified in Section 47 of OMA.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self._probe_in_flight = False

    def can_attempt(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self._probe_in_flight = True
                return True
            return False
        if self._probe_in_flight:
            return False
        self._probe_in_flight = True
        return True

    def release_probe(self):
        self._probe_in_flight = False

    def record_success(self) -> None:
        self.release_probe()
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.release_probe()
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN


class ModelRouter:
    """
    Model Router and Fallback orchestrator as specified in Section 32 of OMA.
    Routes tasks by complexity and automatically switches to fallbacks when primary fails.
    """

    def __init__(
        self,
        providers: Dict[str, AgentProvider],
        primary_provider_name: str = "primary",
        fallback_provider_name: Optional[str] = "fallback",
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ):
        self.providers = providers
        self.primary_name = primary_provider_name
        self.fallback_name = fallback_provider_name
        self.circuit_breakers: Dict[str, CircuitBreaker] = {
            name: CircuitBreaker(failure_threshold, recovery_timeout)
            for name in providers
        }
        self.success_counts: Dict[str, int] = {name: 0 for name in providers}
        self.total_counts: Dict[str, int] = {name: 0 for name in providers}
        self._repository_context = ContextVar(f"repository-{id(self)}", default=None)
        self._provider_boundary = ContextVar(f"provider-boundary-{id(self)}", default=None)
        self.budget = None
        self.role_routes = {}
        self.request_timeout = None
        self.max_output_tokens = None
        self.max_inflight_requests = 0
        self._admission_semaphore = None
        self.response_sink = None
        # Optional typed decision model (Kev/Jev/System One). Disabled by default.
        # It may recommend a route, but deterministic policy remains the fallback
        # and explicit/critical routing is never overridden.
        self.decision_controller = None
        self.decision_routing_enabled = False
        self.decision_retry_enabled = False
        self.decision_validator_selection_enabled = False
        self.decision_quality_advisory_enabled = False
        self.decision_min_confidence = 0.35
        self.decision_trace_sink = None

    @contextmanager
    def provider_scope(self, boundary):
        """Observe every provider attempt, including repository rounds/fallbacks."""
        token = self._provider_boundary.set(boundary)
        try:
            yield
        finally:
            self._provider_boundary.reset(token)

    @contextmanager
    def repository_scope(self, root, event_sink=None):
        token = self._repository_context.set((root, event_sink))
        try:
            yield
        finally:
            self._repository_context.reset(token)

    def get_provider_for_complexity(self, complexity: TaskPriority | str) -> str:
        comp_str = complexity.value if isinstance(complexity, TaskPriority) else str(complexity).upper()
        if comp_str == "CRITICAL" and "master" in self.providers:
            return "master"
        if comp_str in {"HIGH", "MEDIUM"} and self.primary_name in self.providers:
            return self.primary_name
        if comp_str == "LOW" and "cheap" in self.providers:
            return "cheap"
        return self.primary_name

    def _deterministic_target(
        self, request: AgentRequest, preferred_provider: Optional[str] = None,
    ) -> str:
        return preferred_provider or self.role_routes.get(
            request.role,
            self.role_routes.get(request.role.split(".")[0], self.primary_name),
        )

    async def _decision_target(
        self,
        request: AgentRequest,
        preferred_provider: Optional[str],
        baseline: str,
    ) -> str:
        controller = self.decision_controller
        if preferred_provider is not None or not self.decision_routing_enabled or controller is None:
            return baseline
        metadata = request.metadata or {}
        priority = str(metadata.get("priority") or "").upper()
        risk = str(metadata.get("risk") or "").upper()
        if request.role == "master" or priority == "CRITICAL" or risk == "CRITICAL":
            return baseline

        candidates = [baseline]
        for name in self.providers:
            if name == "master" and baseline != "master":
                continue
            if name not in candidates:
                candidates.append(name)
        criteria = {
            name: (
                "Current deterministic route; prefer unless the task state gives a clear reason to switch."
                if name == baseline else
                f"Available provider '{name}'. Use only when its observed reliability/capability is a better fit."
            )
            for name in candidates
        }
        state = {
            "role": request.role,
            "priority": priority or "UNSPECIFIED",
            "risk": risk or "UNSPECIFIED",
            "deterministic_route": baseline,
            "request": request.user_prompt[:4000],
            "providers": {
                name: {
                    "reliability": round(self.get_reliability_score(name), 4),
                    "circuit": self.circuit_breakers[name].state.value,
                }
                for name in candidates
            },
        }
        selection = await controller.choose(
            state=state,
            instructions=(
                "Choose the model provider for this request. Preserve the deterministic route unless another "
                "available provider is clearly more appropriate. Do not infer capabilities not present in the state."
            ),
            criteria=criteria,
            default=baseline,
            question_id="provider",
            min_confidence=self.decision_min_confidence,
        )
        if self.decision_trace_sink is not None:
            try:
                self.decision_trace_sink({
                    "kind": "model_route",
                    "role": request.role,
                    "task_id": request.metadata.get("task_id"),
                    "candidate_id": request.metadata.get("candidate_id"),
                    "baseline": baseline,
                    "selected": selection.value,
                    "confidence": selection.confidence,
                    "source": selection.source,
                    "model": selection.model,
                    "deterministic_fallback": selection.used_deterministic_fallback,
                    "probabilities": dict(selection.probabilities),
                })
            except Exception:
                pass
        return selection.value if selection.value in self.providers else baseline

    async def execute(
        self, request: AgentRequest, preferred_provider: Optional[str] = None,
    ) -> AgentResponse:
        from dataclasses import replace
        from .contracts import contract, VERSION
        request = replace(request, system_prompt=request.system_prompt + "\n" + contract(request.role),
                          metadata={**request.metadata, "run_id": getattr(self, "run_id", None),
                                    "role_contract_version": VERSION})
        context = self._repository_context.get()
        if context is None:
            return await self._execute_once(request, preferred_provider)
        from repository.agent_loop import AgentToolLoop
        from repository.gateway import CommandGateway
        root, event_sink = context
        loop = AgentToolLoop(CommandGateway(root, event_sink=event_sink))
        return await loop.run(request, lambda turn: self._execute_once(turn, preferred_provider))

    async def _execute_once(self, request: AgentRequest,
                            preferred_provider: Optional[str] = None) -> AgentResponse:
        import asyncio
        from dataclasses import replace
        if self.request_timeout:
            request = replace(request, timeout=self.request_timeout)
        if self.max_output_tokens:
            request = replace(request, max_output_tokens=self.max_output_tokens)
        if self.max_inflight_requests:
            if self._admission_semaphore is None:
                self._admission_semaphore = asyncio.Semaphore(self.max_inflight_requests)
            async with self._admission_semaphore:
                return await self._dispatch_once(request, preferred_provider)
        return await self._dispatch_once(request, preferred_provider)

    async def _dispatch_once(self, request: AgentRequest,
                             preferred_provider: Optional[str] = None) -> AgentResponse:
        import asyncio
        from ..budgets import BudgetExceeded, estimate_input_tokens

        baseline_target = self._deterministic_target(request, preferred_provider)
        if baseline_target not in self.providers:
            return AgentResponse(content="", success=False,
                                 error=f"[POLICY_ERROR] unknown provider {baseline_target}")
        target = await self._decision_target(request, preferred_provider, baseline_target)
        names = [target]
        # A decision model may only reorder attempts. The deterministic route stays
        # immediately behind it, so an advisory mistake cannot remove the known path.
        if (target != baseline_target and baseline_target in self.providers
                and self.providers[baseline_target] is not self.providers[target]):
            names.append(baseline_target)
        if (self.fallback_name in self.providers and self.fallback_name not in names
                and all(self.providers[self.fallback_name] is not self.providers[name] for name in names)):
            names.append(self.fallback_name)
        last = None
        timeout = max(1, int(request.timeout or 120))
        # Grace para o timeout interno do provider disparar primeiro e classificar
        # a falha (retry_safe/delivery_state); o timeout do router é backstop.
        dispatch_timeout = timeout + 5
        for name in names:
            breaker = self.circuit_breakers[name]
            if not breaker.can_attempt():
                continue
            reservation = None
            if self.budget is not None:
                messages = request.metadata.get("messages") or [
                    {"content": request.system_prompt}, {"content": request.user_prompt}]
                input_bound = estimate_input_tokens(messages)
                try:
                    reservation = self.budget.reserve(request.role, request.metadata.get("task_id", "__run__"),
                                                      input_bound, request.max_output_tokens)
                except BudgetExceeded as exc:
                    breaker.release_probe()
                    return AgentResponse(content="", success=False, error=f"[BUDGET_EXCEEDED] {exc}")
            self.total_counts[name] += 1
            try:
                async def invoke(turn):
                    return await asyncio.wait_for(self.providers[name].execute(turn), timeout=dispatch_timeout)

                boundary = self._provider_boundary.get()
                response = (await boundary(request, name, invoke) if boundary is not None
                            else await invoke(request))
            except asyncio.CancelledError:
                if reservation:
                    self.budget.settle(reservation, uncertain=True)
                breaker.release_probe()
                raise
            except (TimeoutError, asyncio.TimeoutError) as exc:
                response = AgentResponse(content="", success=False, error=f"[TIMEOUT] provider '{name}': {exc}",
                                         metadata=self._external_failure_metadata(name))
            except Exception as exc:
                response = AgentResponse(content="", success=False, error=f"[PROVIDER_ERROR] '{name}': {exc}",
                                         metadata=self._external_failure_metadata(name))
            if reservation:
                try:
                    self.budget.settle(reservation, response.token_usage, uncertain=not response.success)
                except BudgetExceeded as exc:
                    breaker.release_probe()
                    return AgentResponse(content="", success=False, token_usage=response.token_usage,
                                         error=f"[BUDGET_EXCEEDED] {exc}")
            if self.response_sink is not None:
                import hashlib
                self.response_sink({"task_id": request.metadata.get("task_id"), "role": request.role,
                                    "provider": name, "model": response.model, "success": response.success,
                                    "candidate_id": request.metadata.get("candidate_id"),
                                    "role_contract_version": request.metadata.get("role_contract_version"),
                                    "latency_s": response.latency,
                                    "error": response.error, "token_usage": response.token_usage.to_dict(),
                                    "conversation_key": request.metadata.get("conversation_key"),
                                    "conversation": response.metadata,
                                    "response_sha256": hashlib.sha256(response.content.encode()).hexdigest()})
            if response.success:
                breaker.record_success()
                self.success_counts[name] += 1
                return response
            breaker.record_failure()
            last = response
            # Um side effect externo incerto não pode ser repetido num fallback
            # (double-send). Quota/UI bloqueada exige diagnóstico, não outra conta.
            # Mas timeout PURO sem metadados de incerteza (ex. modelo local travado,
            # sem side effect possível) DEVE fazer failover (RF-016/RF-019).
            if (response.metadata.get("retry_safe") is False or
                    response.metadata.get("delivery_state") in {"UNCERTAIN", "BLOCKED"} or
                    any(code in (response.error or "") for code in ("SUBMISSION_UNCERTAIN", "DELIVERY_EXPIRED"))):
                return response
        return last or AgentResponse(content="", success=False,
                                     error="[POLICY_ERROR] all eligible provider circuits are OPEN")

    def _external_failure_metadata(self, name):
        if getattr(self.providers[name], "persistent_conversations", False):
            return {"delivery_state": "UNCERTAIN", "retry_safe": False}
        return {}

    def get_reliability_score(self, provider_name: str) -> float:
        total = self.total_counts.get(provider_name, 0)
        if total == 0:
            return 1.0
        return self.success_counts.get(provider_name, 0) / total
