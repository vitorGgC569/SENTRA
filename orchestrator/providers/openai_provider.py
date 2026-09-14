"""Explicit opt-in API provider. No UI-model guessing or automatic SDK retries."""
import asyncio
import time

from openai import AsyncOpenAI

from .base import AgentResponse
from ..models import TokenUsage


class OpenAIProvider:
    def __init__(self, model, api_key):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("routing.openai_model must explicitly identify the model")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured; no live API calls were made")
        self.model_name = model
        self.client = AsyncOpenAI(api_key=api_key, base_url="https://api.openai.com/v1", max_retries=0)

    async def execute(self, request):
        started = time.monotonic()
        try:
            result = await self.client.responses.create(
                model=self.model_name,
                input=request.metadata.get("messages") or [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt}],
                max_output_tokens=request.max_output_tokens, timeout=request.timeout, store=False)
            usage = result.usage
            identity = {"requested": self.model_name, "observed": result.model,
                        "source": "openai_response", "response_id": result.id}
            tokens = TokenUsage(input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                # Responses output_tokens already includes reasoning; do not count twice.
                model=result.model, accounting="provider" if usage else "estimated")
            ok = result.status == "completed" and bool(result.output_text) and usage is not None
            return AgentResponse(content=result.output_text or "", success=ok, model=result.model,
                token_usage=tokens, latency=time.monotonic() - started,
                error=None if ok else "[MODEL_INCOMPLETE] incomplete output or missing usage",
                metadata={"model_identity": identity, "retry_safe": False})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not log server bodies, credentials or request content.
            return AgentResponse(content="", success=False, model=self.model_name,
                error=f"[OPENAI_ERROR] {type(exc).__name__}", latency=time.monotonic() - started,
                metadata={"retry_safe": False, "delivery_state": "UNCERTAIN"})
