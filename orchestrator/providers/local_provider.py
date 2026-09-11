from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Optional
from openai import AsyncOpenAI

from .base import AgentProvider, AgentRequest, AgentResponse
from ..models import TokenUsage


class LocalModelProvider:
    """
    Adapter for local LLM engines (Ollama, vLLM, LMDeploy) with OpenAI compatibility.
    Includes token estimation and response timing.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434/v1",
        model_name: str = "qwen2.5-coder:14b",
        api_key: str = "local",
        temperature: float = 0.1,
    ):
        self.base_url = base_url
        self.model_name = model_name
        self.temperature = temperature
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        raw_json = match.group(1) if match else text
        try:
            return json.loads(raw_json)
        except Exception:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass
        return None

    async def execute(self, request: AgentRequest) -> AgentResponse:
        start_time = time.time()
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt},
                ],
                temperature=request.temperature or self.temperature,
                timeout=request.timeout,
            )
            latency = time.time() - start_time
            choice = response.choices[0]
            content = choice.message.content or ""

            # Extract usage if provided by server, else estimate
            usage = response.usage
            if usage:
                in_tok = usage.prompt_tokens
                out_tok = usage.completion_tokens
            else:
                in_tok = (len(request.system_prompt) + len(request.user_prompt)) // 4
                out_tok = len(content) // 4

            token_usage = TokenUsage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model=self.model_name,
                estimated_cost=0.0,
            )

            structured = self._extract_json(content)

            return AgentResponse(
                content=content,
                structured_data=structured,
                token_usage=token_usage,
                latency=latency,
                success=True,
                model=self.model_name,
            )
        except Exception as e:
            latency = time.time() - start_time
            err_msg = str(e)
            return AgentResponse(
                content="",
                token_usage=TokenUsage(model=self.model_name),
                latency=latency,
                success=False,
                error=err_msg,
                model=self.model_name,
            )
