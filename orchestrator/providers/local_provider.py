from __future__ import annotations

import json
import re
import time
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from openai import AsyncOpenAI

from .base import AgentProvider, AgentRequest, AgentResponse
from ..models import TokenUsage


def _is_loopback_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost"}


def _http_get_json(url: str, timeout_s: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read(8192).decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except Exception:
        data = {"_raw": raw[:500]}
    if not isinstance(data, dict):
        return {"_raw": str(data)[:500]}
    return data


def probe_local_endpoint(
    base_url: str = "http://127.0.0.1:11434/v1",
    timeout_s: float = 3.0,
) -> Dict[str, Any]:
    """Read-only reachability probe for a local OpenAI-compatible endpoint.

    Only performs GET of version/model metadata (Ollama /api/version and
    /v1/models). Never sends prompts, never downloads models. Loopback only.
    Returns {"reachable", "checked", "version", "models", "error"}.
    """
    if not _is_loopback_url(base_url):
        raise ValueError("local probe must use loopback HTTP")
    base = base_url.rstrip("/")
    root = base.split("/v1")[0].rstrip("/")
    candidates = [root + "/api/version", base + "/models"]
    checked: List[str] = []
    version: Optional[str] = None
    models: Optional[list] = None
    last_error = ""
    for url in candidates:
        checked.append(url)
        try:
            data = _http_get_json(url, max(0.5, float(timeout_s)))
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:300]
            continue
        if "version" in data and version is None:
            try:
                version = str(data.get("version"))[:100]
            except Exception:
                pass
        items = data.get("data") if isinstance(data.get("data"), list) else None
        if items is not None and models is None:
            try:
                models = [str(m.get("id", ""))[:120] for m in items[:50]
                          if isinstance(m, dict)][:50]
            except Exception:
                models = []
        # Any well-formed JSON answer proves the endpoint is alive.
        return {"reachable": True, "checked": checked, "version": version,
                "models": models, "error": ""}
    return {"reachable": False, "checked": checked, "version": version,
            "models": models, "error": last_error}


def mark_as_degraded(response: AgentResponse, original_error: Any) -> AgentResponse:
    """Label a local answer as weak evidence (honest degradation).

    Thin wrapper over degradation.mark_degraded so local answers always
    carry metadata {degraded: True, original_error}. Import is local to
    avoid any import cycle at module load.
    """
    from .degradation import mark_degraded as _mark

    return _mark(response, original_error)


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

    def probe(self, timeout_s: float = 3.0) -> Dict[str, Any]:
        """Read-only liveness check for this instance (GET version, no prompts)."""
        return probe_local_endpoint(self.base_url, timeout_s=timeout_s)

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
        import asyncio as _asyncio

        start_time = time.time()
        timeout = max(1, int(request.timeout or 120))
        try:
            response = await _asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model_name,
                    messages=request.metadata.get("messages") or [
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.user_prompt},
                    ],
                    temperature=request.temperature or self.temperature,
                    max_tokens=request.max_output_tokens,
                    timeout=timeout,
                ),
                timeout=timeout + 10,
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
                accounting="provider" if usage else "estimated",
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
        except _asyncio.CancelledError:
            raise
        except Exception as e:
            import asyncio as _a2

            latency = time.time() - start_time
            if isinstance(e, (_a2.TimeoutError, TimeoutError)) or "timed out" in str(e).lower() or "timeout" in str(e).lower():
                err_msg = f"[TIMEOUT] local model '{self.model_name}' exceeded {timeout}s: {e}"
            elif "connect" in str(e).lower() or "refused" in str(e).lower() or "unreachable" in str(e).lower():
                err_msg = f"[NETWORK_ERROR] local model unavailable: {e}"
            elif "model" in str(e).lower() and "not found" in str(e).lower():
                err_msg = f"[DEPENDENCY_ERROR] {e}"
            else:
                err_msg = f"[MODEL_ERROR] {e}"
            return AgentResponse(
                content="",
                token_usage=TokenUsage(model=self.model_name),
                latency=latency,
                success=False,
                error=err_msg,
                model=self.model_name,
            )
