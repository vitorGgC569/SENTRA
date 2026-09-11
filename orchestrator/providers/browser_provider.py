from __future__ import annotations

import time
from typing import Optional

from .base import AgentProvider, AgentRequest, AgentResponse
from ..models import TokenUsage
from browser.pool import BrowserPool
from browser.session import BrowserSession


class BrowserProvider:
    """
    Adapter that routes requests through ChatGPT Web via Playwright / CDP.
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
        prompt = f"{request.system_prompt}\n\n{request.user_prompt}"

        try:
            if self.pool:
                res = await self.pool.submit(
                    role=role,
                    task={"id": request.metadata.get("task_id", "t-001")},
                    prompt=prompt,
                    round_number=request.metadata.get("round_number", 0),
                    timeout_seconds=request.timeout,
                )
                content = res.get("raw_response", "")
            elif self.session:
                content = await self.session.ask(prompt, timeout_seconds=request.timeout)
            else:
                raise RuntimeError("No BrowserPool or BrowserSession provided to BrowserProvider")

            latency = time.time() - start_time
            in_tok = len(prompt) // 4
            out_tok = len(content) // 4

            return AgentResponse(
                content=content,
                token_usage=TokenUsage(
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    model="browser-chatgpt",
                ),
                latency=latency,
                success=True,
                model="browser-chatgpt",
            )
        except Exception as e:
            latency = time.time() - start_time
            return AgentResponse(
                content="",
                token_usage=TokenUsage(model="browser-chatgpt"),
                latency=latency,
                success=False,
                error=str(e),
                model="browser-chatgpt",
            )
