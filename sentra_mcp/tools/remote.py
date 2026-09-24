"""Cloud-safe remote device MCP tools."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from sentra_remote.gateway import RemoteGatewayService

from ..errors import SentraSemanticError, error_envelope, sanitize_error
from ..identity import authorization_principal
from ..models import ResponseEnvelope


def _failure(exc: Exception) -> ResponseEnvelope:
    if isinstance(exc, SentraSemanticError):
        return error_envelope(exc)
    semantic_code = getattr(exc, "code", None)
    if isinstance(semantic_code, str) and semantic_code:
        raw_details = getattr(exc, "details", None)
        details = raw_details if isinstance(raw_details, dict) else None
        return error_envelope(SentraSemanticError(
            semantic_code,
            sanitize_error(exc),
            category=str(getattr(exc, "category", "runtime")),
            retryable=bool(getattr(exc, "retryable", False)),
            details=details,
        ))
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


def register_remote_tools(mcp: MCPServer, remote: RemoteGatewayService) -> None:
    @mcp.tool()
    def sentra_pair_device(
        name: str,
        platform: str,
        allowed_tools: list[str],
        ctx: Context,
        ttl_s: int = 300,
    ) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:devices:write")
            return remote.start_pairing(principal, name, platform, allowed_tools, ttl_s)
        return _sync(op)

    @mcp.tool()
    def sentra_list_devices(ctx: Context) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:devices:read")
            return remote.list_devices(principal)
        return _sync(op)

    @mcp.tool()
    def sentra_ping(device_id: str, ctx: Context) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:devices:read")
            return remote.ping(principal, device_id)
        return _sync(op)

    @mcp.tool()
    def sentra_who_am_i(ctx: Context) -> ResponseEnvelope:
        def op():
            principal, scopes, owner = authorization_principal(ctx)
            data = remote.who_am_i(principal, scopes)
            data["principal"] = principal
            data["session_owner"] = owner
            data["subject"] = principal
            return data
        return _sync(op)

    @mcp.tool()
    def sentra_set_device_tools(
        device_id: str,
        allowed_tools: list[str],
        ctx: Context,
    ) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:devices:write")
            return remote.set_permissions(principal, device_id, allowed_tools)
        return _sync(op)

    @mcp.tool()
    def sentra_disconnect_device(device_id: str, ctx: Context) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:devices:write")
            return remote.disconnect(principal, device_id)
        return _sync(op)

    @mcp.tool()
    def sentra_shutdown_remote(
        device_id: str,
        ctx: Context,
        timeout_s: int = 30,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:devices:write")
            return remote.shutdown_agent(
                principal,
                device_id,
                timeout_s=timeout_s,
                run_id=run_id,
                idempotency_key=idempotency_key,
            )
        return _sync(op)

    @mcp.tool()
    def sentra_remote_call(
        device_id: str,
        tool: str,
        arguments: dict[str, Any],
        ctx: Context,
        timeout_s: int = 180,
        wait_s: float | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:execute")
            return remote.invoke(
                principal,
                device_id,
                tool,
                arguments,
                timeout_s=timeout_s,
                wait_s=wait_s,
                run_id=run_id,
                idempotency_key=idempotency_key,
            )
        return _sync(op)

    @mcp.tool()
    def sentra_remote_result(job_id: str, ctx: Context) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:execute")
            return remote.result(principal, job_id)
        return _sync(op)

    @mcp.tool()
    def sentra_remote_cancel(job_id: str, ctx: Context) -> ResponseEnvelope:
        def op():
            principal, _, _ = authorization_principal(ctx, "sentra:execute")
            return remote.cancel(principal, job_id)
        return _sync(op)

    @mcp.tool()
    def sentra_remote_read_file(
        device_id: str,
        path: str,
        ctx: Context,
        offset: int = 0,
        length: int | None = None,
        workspace: str | None = None,
    ) -> ResponseEnvelope:
        return sentra_remote_call(
            device_id,
            "sentra_read_file",
            {"path": path, "offset": offset, "length": length, "workspace": workspace},
            ctx,
        )

    @mcp.tool()
    def sentra_remote_write_file(
        device_id: str,
        path: str,
        content: str,
        ctx: Context,
        mode: str = "rewrite",
        workspace: str | None = None,
    ) -> ResponseEnvelope:
        return sentra_remote_call(
            device_id,
            "sentra_write_file",
            {"path": path, "content": content, "mode": mode, "workspace": workspace},
            ctx,
        )

    @mcp.tool()
    def sentra_remote_start_process(
        device_id: str,
        command: str | list[str],
        ctx: Context,
        timeout: float | None = None,
        cwd: str | None = None,
        workspace: str | None = None,
        mode: str | None = None,
        image: str | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
        cleanup_policy: str = "terminate_on_run_end",
    ) -> ResponseEnvelope:
        return sentra_remote_call(
            device_id,
            "sentra_start_process",
            {
                "command": command,
                "timeout": timeout,
                "cwd": cwd,
                "workspace": workspace,
                "mode": mode,
                "image": image,
                "idempotency_key": idempotency_key,
                "cleanup_policy": cleanup_policy,
            },
            ctx,
            run_id=run_id,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def sentra_remote_read_process_output(
        device_id: str,
        session_id: str,
        ctx: Context,
        offset: int = 0,
        length: int = 65536,
    ) -> ResponseEnvelope:
        return sentra_remote_call(
            device_id,
            "sentra_read_process_output",
            {"session_id": session_id, "offset": offset, "length": length},
            ctx,
        )

    @mcp.tool()
    def sentra_remote_interact_process(
        device_id: str,
        session_id: str,
        stdin: str,
        ctx: Context,
    ) -> ResponseEnvelope:
        return sentra_remote_call(
            device_id,
            "sentra_interact_process",
            {"session_id": session_id, "stdin": stdin},
            ctx,
        )

    @mcp.tool()
    def sentra_remote_repo_status(
        device_id: str,
        ctx: Context,
        workspace: str | None = None,
    ) -> ResponseEnvelope:
        return sentra_remote_call(
            device_id,
            "sentra_repo_status",
            {"workspace": workspace},
            ctx,
        )

    @mcp.tool()
    def sentra_remote_oma_status(
        device_id: str,
        run_id: str,
        ctx: Context,
    ) -> ResponseEnvelope:
        return sentra_remote_call(
            device_id,
            "sentra_oma_status",
            {"run_id": run_id},
            ctx,
        )
