from __future__ import annotations

import asyncio
import time
from typing import Optional

from .base import AgentProvider, AgentRequest, AgentResponse
from ..models import TokenUsage
from browser.outcomes import classify_failure
from browser.pool import BrowserPool
from browser.session import BrowserSession


def _classify_browser_error(exc: BaseException) -> str:
    """Map exceptions to the OMA failure taxonomy (Section 73)."""
    if isinstance(exc, asyncio.CancelledError):
        return "CANCELLED"
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "TIMEOUT"
    msg = str(exc).lower()
    if "closed" in msg or "disconnected" in msg or "sessao" in msg:
        return "NETWORK_ERROR"
    if "ausente" in msg or "dom" in msg or "selector" in msg or "login" in msg:
        return "DEPENDENCY_ERROR"
    if "vazia" in msg or "incompleta" in msg or "expirada" in msg:
        return "MODEL_ERROR"
    return "TOOL_ERROR"


class BrowserProvider:
    """
    Adapter that routes requests through chatgpt.com via persistent
    Microsoft Edge (Playwright channel="msedge" / CDP). Responses are
    correlated with task_id for auditability.
    """

    def __init__(
        self,
        pool: Optional[BrowserPool] = None,
        session: Optional[BrowserSession] = None,
    ):
        self.pool = pool
        self.session = session

    async def execute(self, request: AgentRequest) -> AgentResponse:
        start_time = time.time()
        role = request.role
        task_id = request.metadata.get("task_id", "t-001")
        prompt = f"{request.system_prompt}\n\n{request.user_prompt}"
        timeout = max(1, int(request.timeout or 120))

        try:
            if self.pool:
                res = await self.pool.submit(
                    role=role,
                    task={"id": task_id},
                    prompt=prompt,
                    round_number=request.metadata.get("round_number", 0),
                    timeout_seconds=timeout,
                )
                content = res.get("raw_response", "")
            elif self.session:
                content = await asyncio.wait_for(
                    self.session.ask(prompt, timeout_seconds=timeout),
                    timeout=timeout + 10,
                )
            else:
                raise RuntimeError("No BrowserPool or BrowserSession provided to BrowserProvider")

            if not content:
                raise RuntimeError("Empty response from chatgpt.com (resposta incompleta)")

            latency = time.time() - start_time
            in_tok = len(prompt) // 4
            out_tok = len(content) // 4

            return AgentResponse(
                content=content,
                token_usage=TokenUsage(
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    model="browser-chatgpt-edge",
                ),
                latency=latency,
                success=True,
                model="browser-chatgpt-edge",
            )
        except asyncio.CancelledError:
            # RF-017: never swallow cancellation; let the orchestrator observe it.
            raise
        except Exception as e:
            latency = time.time() - start_time
            code = _classify_browser_error(e)
            return AgentResponse(
                content="",
                token_usage=TokenUsage(model="browser-chatgpt-edge"),
                latency=latency,
                success=False,
                error=f"[{code}] task={task_id} {e}",
                model="browser-chatgpt-edge",
                metadata=classify_failure(f"[{code}] {e}"),
            )
