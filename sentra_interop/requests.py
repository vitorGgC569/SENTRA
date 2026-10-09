"""Pure, scope-pinned protocol -> SENTRA OperationRequest admission mapping.

Mapping never grants authority or executes a tool. The same request must be
submitted to InteropGate / the SENTRA policy authority before any effect.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sentra_runtime.contracts import OperationRequest
from .gate import InteropGate

MAX_ARGUMENT_BYTES = 65536
PATH_KEYS = frozenset({"path", "file_path", "cwd", "workspace", "directory"})
DENIED_KEYS = frozenset({
    "password", "passwd", "passphrase", "secret", "secrets",
    "token", "access_token", "refresh_token", "api_key", "apikey",
    "authorization", "cookie", "set-cookie", "private_key", "credential",
    "credentials", "client_secret",
})


class InteropMappingDenied(ValueError):
    pass


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()).strip("_")


def _inspect(value: Any, *, depth: int = 0) -> None:
    if depth > 12:
        raise InteropMappingDenied("payload nested too deeply")
    if isinstance(value, Mapping):
        if len(value) > 256:
            raise InteropMappingDenied("too many payload fields")
        for key, item in value.items():
            if not isinstance(key, str):
                raise InteropMappingDenied("non-text payload key")
            normalized = _normalized_key(key)
            if normalized in DENIED_KEYS:
                raise InteropMappingDenied("credential-like field rejected")
            _inspect(item, depth=depth+1)
    elif isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise InteropMappingDenied("too many payload entries")
        for item in value:
            _inspect(item, depth=depth+1)
    elif value is None or type(value) in (bool, int, float, str):
        return
    else:
        raise InteropMappingDenied("non-JSON payload type")


def _bounded(value: Mapping[str, Any]) -> dict[str, Any]:
    _inspect(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise InteropMappingDenied("invalid JSON payload") from exc
    if len(encoded) > MAX_ARGUMENT_BYTES:
        raise InteropMappingDenied("payload exceeds bounded capacity")
    # Freeze the mapped input by roundtrip copy: mutations to the caller's
    # original dictionary must never silently change admitted work.
    return json.loads(encoded.decode("utf-8"))


@dataclass(frozen=True, slots=True)
class InteropRequestMapper:
    """Caller-attested context. Never derive principal/workspace from remote data."""

    machine_id: str
    principal_id: str
    work_item_id: str
    workspace_root: str
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        for value in (self.machine_id, self.principal_id, self.work_item_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise InteropMappingDenied("missing trusted SENTRA scope")
        if (not isinstance(self.workspace_root, str)
            or not Path(self.workspace_root).is_absolute()
            or not isinstance(self.capabilities, frozenset)
            or not self.capabilities):
            raise InteropMappingDenied("trusted workspace/capabilities required")

    def make(
        self, *, operation_id: str, idempotency_key: str,
        capability_id: str, arguments: Mapping[str, Any],
    ) -> OperationRequest:
        for name in (operation_id, idempotency_key, capability_id):
            if not isinstance(name, str) or not name.strip() or len(name) > 256:
                raise InteropMappingDenied("invalid operation identity")
        if capability_id not in self.capabilities:
            raise InteropMappingDenied("unadvertised operation capability")
        if not isinstance(arguments, Mapping):
            raise InteropMappingDenied("invalid operation arguments")
        clean = _bounded(arguments)
        return OperationRequest(
            operation_id, self.principal_id, self.machine_id, capability_id,
            self.work_item_id, idempotency_key, clean,
        )

    def acp_session(self, *, operation_id: str, idempotency_key: str,
                    cwd: str) -> OperationRequest:
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise InteropMappingDenied("absolute ACP cwd required")
        workspace = Path(self.workspace_root).resolve()
        directory = Path(cwd).resolve()
        if not directory.is_relative_to(workspace) or not directory.is_dir():
            raise InteropMappingDenied("ACP directory outside trusted workspace")
        return self.make(operation_id=operation_id, idempotency_key=idempotency_key,
                         capability_id="acp:session", arguments={"cwd": str(directory)})

    def acp_prompt(self, *, operation_id: str, idempotency_key: str,
                   session_id: str, text: str) -> OperationRequest:
        if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
            raise InteropMappingDenied("invalid ACP session identity")
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 32768:
            raise InteropMappingDenied("invalid ACP prompt")
        return self.make(operation_id=operation_id, idempotency_key=idempotency_key,
                         capability_id="acp:prompt",
                         arguments={"session_id": session_id, "text": text})

    def mcp_call(self, *, operation_id: str, idempotency_key: str,
                 capability_id: str, server_id: str, tool_name: str,
                 arguments: Mapping[str, Any]) -> OperationRequest:
        if not server_id or not tool_name or any(
            not isinstance(v, str) or len(v) > 128 for v in (server_id, tool_name)
        ):
            raise InteropMappingDenied("invalid MCP tool identity")
        if not isinstance(arguments, Mapping):
            raise InteropMappingDenied("invalid MCP arguments")
        workspace = Path(self.workspace_root).resolve()
        def check_paths(item: Any) -> None:
            if isinstance(item, Mapping):
                for key, value in item.items():
                    if isinstance(key, str) and _normalized_key(key) in PATH_KEYS:
                        if (not isinstance(value, str) or not Path(value).is_absolute()
                            or not Path(value).resolve().is_relative_to(workspace)):
                            raise InteropMappingDenied("MCP path outside trusted workspace")
                    check_paths(value)
            elif isinstance(item, (list, tuple)):
                for value in item:
                    check_paths(value)
        _inspect(arguments)
        check_paths(arguments)
        return self.make(operation_id=operation_id, idempotency_key=idempotency_key,
                         capability_id=capability_id,
                         arguments={"server_id": server_id, "tool_name": tool_name,
                                    "arguments": dict(arguments)})

    def a2a_event(self, *, operation_id: str, idempotency_key: str,
                  event: Any) -> OperationRequest:
        from .a2a import A2AEnvelope, operation_arguments
        if not isinstance(event, A2AEnvelope):
            raise InteropMappingDenied("invalid A2A event")
        if event.context_id != self.work_item_id or event.identity.principal_id != self.principal_id:
            raise InteropMappingDenied("untrusted A2A scope")
        return self.make(operation_id=operation_id, idempotency_key=idempotency_key,
                         capability_id="a2a:ingest", arguments=operation_arguments(event))

    def openhands_event(self, *, operation_id: str, idempotency_key: str,
                        event: Any) -> OperationRequest:
        from .openhands import OpenHandsEvent
        if not isinstance(event, OpenHandsEvent) or event.conversation_id != self.work_item_id:
            raise InteropMappingDenied("OpenHands event not scoped to workspace")
        return self.make(operation_id=operation_id, idempotency_key=idempotency_key,
                         capability_id="openhands:event", arguments=event.metadata())

    async def authorize(self, request: OperationRequest, gate: InteropGate) -> OperationRequest:
        if (request.principal_id != self.principal_id
            or request.machine_id != self.machine_id
            or request.work_item_id != self.work_item_id
            or request.capability_id not in self.capabilities):
            raise InteropMappingDenied("SENTRA identity or workspace mismatch")
        decision = await gate.decision(request)
        if not decision.allowed:
            raise InteropMappingDenied("SENTRA policy denied")
        # Caller must still use gate.execute/registry.submit immediately before
        # effect; this method is a preflight and never a durable privilege grant.
        return request
