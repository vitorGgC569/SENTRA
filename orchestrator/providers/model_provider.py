"""Event preserving model transport below the OMA AgentProvider interface."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

import httpx


@dataclass(frozen=True)
class ModelEvent:
    type: str
    data: dict[str, Any]

    @property
    def kind(self) -> str:
        """Stable SENTRA category while retaining the exact Responses event name."""
        name = self.type
        if name == "response.created":
            return "response.started"
        if name == "response.output_text.delta":
            return "text.delta"
        if "reasoning" in name and name.endswith(".delta"):
            return "reasoning.delta"
        if name.endswith(".delta") and "function_call" in name:
            return "tool.call"
        if name == "response.completed":
            return "response.completed"
        if name in {"response.failed", "error"}:
            return "response.failed"
        if name == "response.in_progress":
            return "status"
        return name


class ModelProvider(Protocol):
    async def list_models(self) -> list[dict[str, Any]]: ...
    async def create_response(self, request: dict[str, Any]) -> AsyncIterator[ModelEvent]: ...
    async def compact(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def health(self) -> dict[str, Any]: ...
    async def cancel(self, thread_id: str, turn_id: str) -> dict[str, Any]: ...
    def capabilities(self) -> dict[str, Any]: ...


class ChatGPTWebModelProvider:
    """Responses/SSE transport. Event payloads remain native upstream objects."""

    def __init__(self, base_url: str, *, api_key: str = "sentra-local", gateway_admin_token: str = "") -> None:
        from urllib.parse import urlsplit
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Web model endpoint must be loopback-only")
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.client = httpx.AsyncClient(base_url=self.base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=httpx.Timeout(900, connect=10))
        self.gateway_admin_token = gateway_admin_token

    async def close(self) -> None:
        await self.client.aclose()

    async def list_models(self) -> list[dict[str, Any]]:
        response = await self.client.get("/v1/models")
        response.raise_for_status()
        catalog = response.json()
        return list(catalog.get("models") or catalog.get("data") or [])

    async def health(self) -> dict[str, Any]:
        response = await self.client.get("/healthz")
        response.raise_for_status()
        return response.json()

    def capabilities(self) -> dict[str, Any]:
        return {"responses": True, "sse": True, "compact": True, "cancel_on_disconnect": True, "native_turn_cancel": bool(self.gateway_admin_token)}

    async def cancel(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        if not self.gateway_admin_token:
            raise RuntimeError("SENTRA Gateway admin token is required to interrupt a native turn")
        response = await self.client.post(
            "/sentra/upstream/interrupt-turn",
            json={"threadId": thread_id, "turnId": turn_id},
            headers={"Authorization": f"Bearer {self.gateway_admin_token}"},
        )
        response.raise_for_status()
        return response.json()

    async def compact(self, request: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post("/v1/responses/compact", json=request)
        response.raise_for_status()
        return response.json()

    async def create_response(self, request: dict[str, Any]) -> AsyncIterator[ModelEvent]:
        body = {**request, "stream": True}
        async with self.client.stream("POST", "/v1/responses", json=body) as response:
            response.raise_for_status()
            name = ""
            data: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    raw = "\n".join(data)
                    if raw == "[DONE]":
                        return
                    value = json.loads(raw)
                    if isinstance(value, dict):
                        yield ModelEvent(name or str(value.get("type") or "message"), value)
                    name, data = "", []
            if data and "\n".join(data) != "[DONE]":
                value = json.loads("\n".join(data))
                if isinstance(value, dict):
                    yield ModelEvent(name or str(value.get("type") or "message"), value)
