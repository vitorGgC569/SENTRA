"""ToolHive/MCP pre-dispatch boundary: SENTRA remains the authorization PDP.

A caller must inject an already connected, authenticated MCP client. ToolHive
is optional and *not* discovered, installed, or launched by this module.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import DispatchOutcome, InteropGate
from .requests import InteropMappingDenied, _bounded, _normalized_key


def _deny_obvious_secret_values(value: Any) -> None:
    """Fail-closed response screening, not a replacement for DLP/egress policy."""
    if isinstance(value, str):
        lower = value.lower()
        if any(marker in lower for marker in (
            "-----begin private key", "-----begin rsa private key",
            "authorization: bearer ", "bearer sk-", "sk-proj-",
            "ghp_", "github_pat_", "refresh_token=",
        )):
            raise ValueError("credential-like MCP response rejected")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and _normalized_key(key) in {
                "password", "secret", "api_key", "apikey", "access_token",
                "refresh_token", "authorization", "client_secret", "private_key",
            }:
                raise ValueError("credential-like MCP response rejected")
            _deny_obvious_secret_values(item)
    elif isinstance(value, list):
        for item in value:
            _deny_obvious_secret_values(item)


class MCPClient(Protocol):
    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MCPToolGrant:
    server_id: str
    tool_name: str
    capability_id: str

    def __post_init__(self) -> None:
        for item in (self.server_id, self.tool_name, self.capability_id):
            if not isinstance(item, str) or not item or len(item) > 128:
                raise ValueError("invalid MCP tool grant")


class ToolHiveMCPBoundary:
    """Deny unknown server/tool/capability. No implicit provider fallbacks."""

    def __init__(
        self,
        gate: InteropGate,
        clients: Mapping[str, MCPClient] | None = None,
        grants: tuple[MCPToolGrant, ...] = (),
    ) -> None:
        self.gate = gate
        self._clients = dict(clients or {})
        self._grants = {(g.server_id, g.tool_name): g for g in grants}
        if len(self._grants) != len(grants):
            raise ValueError("duplicate MCP grants")

    async def call(
        self,
        request: OperationRequest,
        *,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        timeout: float = 30,
    ) -> DispatchOutcome:
        grant = self._grants.get((server_id, tool_name))
        client = self._clients.get(server_id)
        if grant is None or client is None or request.capability_id != grant.capability_id:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="MCP tool not admitted"))
        if not isinstance(arguments, Mapping):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="invalid MCP arguments"))
        try:
            _bounded(arguments)
            payload_size = len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError, RecursionError, InteropMappingDenied):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="invalid MCP arguments"))
        if payload_size > 65536:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="MCP input too large"))
        # Scope parameters are part of the signed/authorized SENTRA request;
        # caller cannot swap tool args after policy admission.
        if request.arguments != {"server_id": server_id, "tool_name": tool_name, "arguments": dict(arguments)}:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="MCP request mismatch"))

        async def invoke() -> Mapping[str, Any]:
            if getattr(client, "requires_authorized_call", False) is True:
                result = await client.call_tool_authorized(request, tool_name, dict(arguments))
            else:
                result = await client.call_tool(tool_name, dict(arguments))
            if not isinstance(result, Mapping):
                raise TypeError("invalid MCP result")
            if not set(result).issubset({"content", "isError", "structuredContent", "_meta"}):
                raise TypeError("unexpected MCP result fields")
            if "isError" in result and type(result["isError"]) is not bool:
                raise TypeError("invalid MCP result error indicator")
            if "structuredContent" in result and not isinstance(result["structuredContent"], Mapping):
                raise TypeError("invalid MCP structuredContent")
            if "_meta" in result and not isinstance(result["_meta"], Mapping):
                raise TypeError("invalid MCP metadata")
            content = result.get("content")
            if not isinstance(content, list) or len(content) > 128:
                raise TypeError("invalid MCP content")
            for item in content:
                if not isinstance(item, Mapping):
                    raise TypeError("invalid MCP content item")
                # First-stage boundary is intentionally text/data-only; image,
                # embedded resources and remote links require a separate review.
                if item.get("type") != "text" or not isinstance(item.get("text"), str):
                    raise TypeError("unsupported MCP content type")
                if set(item) - {"type", "text", "annotations", "_meta"}:
                    raise TypeError("unexpected MCP content fields")
            try:
                size = len(json.dumps(result, allow_nan=False).encode("utf-8"))
            except (TypeError, ValueError, RecursionError) as exc:
                raise TypeError("invalid MCP tool result") from exc
            if size > 262144:
                raise TypeError("MCP result too large")
            _deny_obvious_secret_values(result)
            return dict(result)

        return await self.gate.execute(request, invoke, timeout=timeout)


@dataclass(frozen=True, slots=True)
class ToolHiveEndpoint:
    """Describes a pre-authorized ToolHive MCP endpoint; performs no network IO."""

    server_id: str
    url: str

    def __post_init__(self) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(self.url)
        if (not self.server_id or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.query or parsed.scheme not in {"https", "http"}):
            raise ValueError("invalid ToolHive endpoint")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("unencrypted non-loopback ToolHive endpoint rejected")
