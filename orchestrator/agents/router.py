from __future__ import annotations

import time
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

    def can_attempt(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN allows single probe
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
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

    def get_provider_for_complexity(self, complexity: TaskPriority | str) -> str:
        comp_str = complexity.value if isinstance(complexity, TaskPriority) else str(complexity).upper()
        if comp_str == "CRITICAL" and "master" in self.providers:
            return "master"
        if comp_str in {"HIGH", "MEDIUM"} and self.primary_name in self.providers:
            return self.primary_name
        if comp_str == "LOW" and "cheap" in self.providers:
            return "cheap"
        return self.primary_name

    async def execute(
        self,
        request: AgentRequest,
        preferred_provider: Optional[str] = None,
    ) -> AgentResponse:
        target_name = preferred_provider or self.primary_name
        if target_name not in self.providers:
            target_name = next(iter(self.providers))

        breaker = self.circuit_breakers[target_name]

        # Check circuit
        if not breaker.can_attempt():
            # Trip to fallback if available
            if self.fallback_name and self.fallback_name in self.providers:
                target_name = self.fallback_name
                breaker = self.circuit_breakers[target_name]
            else:
                return AgentResponse(
                    content="",
                    latency=0.0,
                    success=False,
                    error=f"Circuit for provider '{target_name}' is OPEN and no fallback is available.",
                )

        provider = self.providers[target_name]
        self.total_counts[target_name] = self.total_counts.get(target_name, 0) + 1
        resp = await provider.execute(request)

        if resp.success:
            breaker.record_success()
            self.success_counts[target_name] = self.success_counts.get(target_name, 0) + 1
            return resp

        # Primary failed: record failure and try fallback if available
        breaker.record_failure()
        if self.fallback_name and self.fallback_name in self.providers and target_name != self.fallback_name:
            fallback_breaker = self.circuit_breakers[self.fallback_name]
            if fallback_breaker.can_attempt():
                self.total_counts[self.fallback_name] = self.total_counts.get(self.fallback_name, 0) + 1
                fallback_provider = self.providers[self.fallback_name]
                fb_resp = await fallback_provider.execute(request)
                if fb_resp.success:
                    fallback_breaker.record_success()
                    self.success_counts[self.fallback_name] = self.success_counts.get(self.fallback_name, 0) + 1
                    return fb_resp
                fallback_breaker.record_failure()

        return resp

    def get_reliability_score(self, provider_name: str) -> float:
        total = self.total_counts.get(provider_name, 0)
        if total == 0:
            return 1.0
        return self.success_counts.get(provider_name, 0) / total
