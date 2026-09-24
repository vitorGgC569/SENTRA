"""Provider adapter for the upstream miuuyy/codex-chatgpt-web Responses daemon.

SENTRA deliberately treats the upstream launcher/browser/Responses bridge as a
sidecar. Control-plane authority remains in SENTRA; this provider only transports
one model turn through the loopback Responses API.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from .base import AgentRequest, AgentResponse
from .model_provider import ChatGPTWebModelProvider
from ..models import TokenUsage


class CodexChatGPTWebProvider:
    persistent_conversations = False

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key: str = "sentra-local",
        gateway_admin_token: str = "",
        require_web_namespace: bool = True,
    ) -> None:
        base = str(base_url or "").strip().rstrip("/")
        model = str(model_name or "").strip()
        if not base.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("codex_web.base_url must be loopback-only")
        if not model:
            raise ValueError("codex_web.model_name is required")
        if require_web_namespace and not model.startswith("sentra/chatgpt-web/"):
            raise ValueError("codex_web model must use the sentra/chatgpt-web/ namespace")
        self.base_url = base
        self.model_name = model
        self.model_provider = ChatGPTWebModelProvider(
            base,
            api_key=api_key or "sentra-local",
            gateway_admin_token=gateway_admin_token,
        )
        self._catalog_verified = False
        self._catalog_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.model_provider.close()

    async def probe(self) -> dict[str, Any]:
        models = await self.model_provider.list_models()
        ids = sorted(
            str(item.get("slug") or item.get("id") or "")
            for item in models
            if str(item.get("slug") or item.get("id") or "").strip()
        )
        available = self.model_name in ids
        return {
            "provider": "codex-chatgpt-web",
            "base_url": self.base_url,
            "model": self.model_name,
            "available": available,
            "catalog_size": len(ids),
            "web_models": [item for item in ids if item.startswith("sentra/chatgpt-web/")],
        }

    async def _ensure_model_available(self) -> None:
        if self._catalog_verified:
            return
        async with self._catalog_lock:
            if self._catalog_verified:
                return
            result = await self.probe()
            if not result["available"]:
                raise RuntimeError(
                    f"configured Web model is not advertised by upstream: {self.model_name}"
                )
            self._catalog_verified = True

    @staticmethod
    def _messages(request: AgentRequest) -> list[dict[str, Any]]:
        messages = request.metadata.get("messages")
        if isinstance(messages, list) and messages:
            return messages
        result: list[dict[str, Any]] = []
        if request.system_prompt:
            result.append({"role": "system", "content": request.system_prompt})
        if request.user_prompt:
            result.append({"role": "user", "content": request.user_prompt})
        return result

    @staticmethod
    def _turn_metadata(request: AgentRequest) -> tuple[dict[str, Any], str | None]:
        conversation_uri = request.metadata.get("conversation_uri")
        if not isinstance(conversation_uri, str) or not conversation_uri.startswith("conversation://"):
            return {}, None
        thread_id = "sentra-thread-" + hashlib.sha256(conversation_uri.encode()).hexdigest()[:32]
        stable = str(
            request.metadata.get("idempotency_key")
            or request.metadata.get("task_id")
            or ""
        )
        fingerprint = hashlib.sha256(
            (
                stable + "\0" + request.role + "\0"
                + request.system_prompt + "\0" + request.user_prompt
            ).encode()
        ).hexdigest()[:32]
        turn_id = "sentra-turn-" + fingerprint
        codex_metadata = json.dumps(
            {
                "request_kind": "turn",
                "thread_id": thread_id,
                "turn_id": turn_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "client_metadata": {
                "sentra_conversation_uri": conversation_uri,
                "x-codex-turn-metadata": codex_metadata,
            },
            "prompt_cache_key": thread_id,
        }, turn_id

    async def execute(self, request: AgentRequest) -> AgentResponse:
        started = time.monotonic()
        try:
            await self._ensure_model_available()
            completed = None
            fragments: list[str] = []
            transport_metadata, turn_id = self._turn_metadata(request)
            async for event in self.model_provider.create_response({
                "model": self.model_name,
                "input": self._messages(request),
                "max_output_tokens": request.max_output_tokens,
                "store": False,
                **transport_metadata,
            }):
                if event.type == "response.output_text.delta":
                    fragments.append(str(event.data.get("delta") or ""))
                elif event.type == "response.completed":
                    completed = event.data.get("response") or event.data
                elif event.type in {"response.failed", "error"}:
                    raise RuntimeError("Web response failed")
            response = completed if isinstance(completed, dict) else {}
            usage = response.get("usage") or {}
            model = str(response.get("model") or self.model_name)
            text = "".join(fragments)
            if not text:
                text = "".join(
                    str(part.get("text") or "")
                    for item in response.get("output") or [] if isinstance(item, dict)
                    for part in item.get("content") or [] if isinstance(part, dict)
                    and part.get("type") == "output_text"
                )
            status = str(response.get("status") or "")
            tokens = TokenUsage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                model=model,
                accounting="provider" if usage else "estimated",
            )
            ok = status == "completed" and bool(text)
            return AgentResponse(
                content=text,
                success=ok,
                model=model,
                token_usage=tokens,
                latency=time.monotonic() - started,
                error=None if ok else "[CODEX_WEB_INCOMPLETE] incomplete Web response",
                metadata={
                    "provider": "codex-chatgpt-web",
                    "requested_model": self.model_name,
                    "observed_model": model,
                    "response_id": response.get("id"),
                    "delivery_state": "CONFIRMED" if ok else "UNCERTAIN",
                    "retry_safe": False,
                    "transport": "responses-loopback",
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return AgentResponse(
                content="",
                success=False,
                model=self.model_name,
                latency=time.monotonic() - started,
                error=f"[CODEX_WEB_ERROR] {type(exc).__name__}",
                metadata={
                    "provider": "codex-chatgpt-web",
                    "delivery_state": "UNCERTAIN",
                    "retry_safe": False,
                },
            )
