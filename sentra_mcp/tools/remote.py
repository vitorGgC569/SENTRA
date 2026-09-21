"""Cloud-safe remote device MCP tools only."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token

from sentra_remote.gateway import RemoteGatewayService

from ..errors import sanitize_error
from ..models import ResponseEnvelope


def _failure(exc: Exception) -> ResponseEnvelope:
    if isinstance(exc, PermissionError):
        code = "forbidden"
    elif isinstance(exc, FileNotFoundError):
        code = "not_found"
    elif isinstance(exc, (ValueError, TypeError)):
        code = "invalid_request"
    else:
        code = "remote_error"
    return ResponseEnvelope.failure(code, sanitize_error(exc))


def _sync(fn: Callable[[], dict[str, Any]]) -> ResponseEnvelope:
    try:
        return ResponseEnvelope.success(fn())
    except Exception as exc:
        return _failure(exc)


def _identity(required_scope: str | None = None) -> tuple[str, list[str]]:
    token = get_access_token()
    if token is None:
        return "local-operator", ["sentra:admin", "sentra:devices:read", "sentra:devices:write", "sentra:execute"]
    scopes = list(token.scopes or [])
    if required_scope and required_scope not in scopes and "sentra:admin" not in scopes:
        raise PermissionError(f"OAuth scope required: {required_scope}")
    subject = token.subject or token.client_id
    if not subject:
        raise PermissionError("authenticated caller has no subject")
    return str(subject), scopes


def register_remote_tools(mcp: MCPServer, remote: RemoteGatewayService) -> None:
    @mcp.tool()
    def sentra_pair_device(name: str, platform: str, allowed_tools: list[str], ttl_s: int = 300) -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:devices:write")
            return remote.start_pairing(subject, name, platform, allowed_tools, ttl_s)
        return _sync(op)

    @mcp.tool()
    def sentra_list_devices() -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:devices:read")
            return remote.list_devices(subject)
        return _sync(op)

    @mcp.tool()
    def sentra_ping(device_id: str) -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:devices:read")
            return remote.ping(subject, device_id)
        return _sync(op)

    @mcp.tool()
    def sentra_who_am_i() -> ResponseEnvelope:
        def op():
            subject, scopes = _identity()
            return remote.who_am_i(subject, scopes)
        return _sync(op)

    @mcp.tool()
    def sentra_set_device_tools(device_id: str, allowed_tools: list[str]) -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:devices:write")
            return remote.set_permissions(subject, device_id, allowed_tools)
        return _sync(op)

    @mcp.tool()
    def sentra_disconnect_device(device_id: str) -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:devices:write")
            return remote.disconnect(subject, device_id)
        return _sync(op)

    @mcp.tool()
    def sentra_shutdown_remote(device_id: str, timeout_s: int = 30) -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:devices:write")
            return remote.shutdown_agent(subject, device_id, timeout_s=timeout_s)
        return _sync(op)

    @mcp.tool()
    def sentra_remote_call(
        device_id: str,
        tool: str,
        arguments: dict[str, Any],
        timeout_s: int = 180,
        wait_s: float | None = None,
    ) -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:execute")
            return remote.invoke(subject, device_id, tool, arguments, timeout_s=timeout_s, wait_s=wait_s)
        return _sync(op)

    @mcp.tool()
    def sentra_remote_result(job_id: str) -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:execute")
            return remote.result(subject, job_id)
        return _sync(op)

    @mcp.tool()
    def sentra_remote_cancel(job_id: str) -> ResponseEnvelope:
        def op():
            subject, _ = _identity("sentra:execute")
            return remote.cancel(subject, job_id)
        return _sync(op)

    @mcp.tool()
    def sentra_remote_read_file(device_id: str, path: str, offset: int = 0, length: int | None = None) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_read_file", {"path": path, "offset": offset, "length": length})

    @mcp.tool()
    def sentra_remote_write_file(device_id: str, path: str, content: str, mode: str = "rewrite") -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_write_file", {"path": path, "content": content, "mode": mode})

    @mcp.tool()
    def sentra_remote_start_process(
        device_id: str,
        command: str | list[str],
        owner: str,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_start_process", {
            "command": command, "owner": owner, "timeout": timeout, "cwd": cwd,
        })

    @mcp.tool()
    def sentra_remote_read_process_output(
        device_id: str,
        session_id: str,
        owner: str,
        offset: int = 0,
        length: int = 65536,
    ) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_read_process_output", {
            "session_id": session_id, "owner": owner, "offset": offset, "length": length,
        })

    @mcp.tool()
    def sentra_remote_interact_process(device_id: str, session_id: str, owner: str, stdin: str) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_interact_process", {
            "session_id": session_id, "owner": owner, "stdin": stdin,
        })

    @mcp.tool()
    def sentra_remote_repo_status(device_id: str) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_repo_status", {})

    @mcp.tool()
    def sentra_remote_oma_status(device_id: str, run_id: str) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_oma_status", {"run_id": run_id})
