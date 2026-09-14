"""Failure-injection doubles for timeout/cancel/concurrency tests.

Regra do projeto: nada aqui finge ser integração real. Estes doubles exercem
o código determinístico REAL (wait_for, retry, circuit breaker, DLQ,
cancelamento) com condições de falha reais: hang de verdade (sleep longo
interrompido pelo timeout real), atraso real, falhas reais. O código sob teste
é 100% o de produção; o double só controla o comportamento do outro lado do fio.
Nenhum deles é usado como prova de integração com modelos/browsers reais.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional

from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.models import TokenUsage


class HangingProvider:
    """Never responds (simulates provider travado). Must trigger TIMEOUT."""

    def __init__(self, model_name: str = "hanging"):
        self.model_name = model_name
        self.calls = 0

    async def execute(self, request: AgentRequest) -> AgentResponse:
        self.calls += 1
        await asyncio.sleep(3600)  # hangs until cancelled/timed out by caller
        return AgentResponse(content="", success=False, error="unreachable", model=self.model_name)


class SlowProvider:
    """Responds after delay_seconds (used for timeout boundary tests)."""

    def __init__(self, delay_seconds: float = 5.0, model_name: str = "slow"):
        self.delay_seconds = delay_seconds
        self.model_name = model_name

    async def execute(self, request: AgentRequest) -> AgentResponse:
        await asyncio.sleep(self.delay_seconds)
        return AgentResponse(
            content='{"status": "APPROVED", "confidence": 0.9, "summary": "slow ok", "findings": []}',
            structured_data={"status": "APPROVED", "confidence": 0.9, "summary": "slow ok", "findings": []},
            token_usage=TokenUsage(input_tokens=10, output_tokens=10, model=self.model_name),
            latency=self.delay_seconds,
            success=True,
            model=self.model_name,
        )


class FlakyProvider:
    """Fails `fail_times` then succeeds (retry/circuit-breaker tests)."""

    def __init__(self, fail_times: int = 2, model_name: str = "flaky"):
        self.fail_times = fail_times
        self.calls = 0
        self.model_name = model_name

    async def execute(self, request: AgentRequest) -> AgentResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            return AgentResponse(
                content="", success=False, error="Flaky simulated failure", model=self.model_name
            )
        return AgentResponse(
            content='{"status": "APPROVED", "confidence": 0.9, "summary": "recovered", "findings": []}',
            structured_data={"status": "APPROVED", "confidence": 0.9, "summary": "recovered", "findings": []},
            token_usage=TokenUsage(input_tokens=10, output_tokens=10, model=self.model_name),
            success=True,
            model=self.model_name,
        )


class ScriptedProvider:
    """Returns pre-programmed contents in order (E2E-scripted diversity)."""

    def __init__(self, script: List[str], model_name: str = "scripted"):
        self.script = list(script)
        self.model_name = model_name
        self.calls = 0

    async def execute(self, request: AgentRequest) -> AgentResponse:
        idx = min(self.calls, len(self.script) - 1)
        self.calls += 1
        content = self.script[idx]
        structured = None
        try:
            structured = json.loads(content)
        except Exception:
            pass
        return AgentResponse(
            content=content,
            structured_data=structured,
            token_usage=TokenUsage(
                input_tokens=len(request.user_prompt) // 4,
                output_tokens=len(content) // 4,
                model=self.model_name,
            ),
            latency=0.001,
            success=True,
            model=self.model_name,
        )
