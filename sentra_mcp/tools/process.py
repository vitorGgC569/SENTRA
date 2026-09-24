"""MCP tool registration for persistent SENTRA process sessions."""
from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Annotated, Any, Literal, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from ..errors import SentraSemanticError, error_envelope, sanitize_error
from ..identity import resolve_owner
from ..models import ResponseEnvelope
from ..services.process import ProcessService

_T = TypeVar("_T")


def _collection(key: str, items: list[dict[str, object]]) -> dict[str, object]:
    return {
        key: items,
        "items": items,
        "page": {
            "offset": 0,
            "limit": len(items),
            "returned": len(items),
            "total": len(items),
            "next_offset": None,
        },
    }


def _failure(exc: Exception) -> ResponseEnvelope:
    if isinstance(exc, SentraSemanticError):
        return error_envelope(exc)
    if isinstance(exc, PermissionError):
        code = "forbidden"
    elif isinstance(exc, KeyError):
        code = "not_found"
    elif isinstance(exc, ValueError):
        code = "invalid_request"
    else:
        code = "process_error"
    return ResponseEnvelope.failure(code, sanitize_error(exc))


def _guard_tool_errors(fn):
    """Keep tool exceptions inside SENTRA's structured response envelope."""
    @wraps(fn)
    def guarded(*args: Any, **kwargs: Any):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return _failure(exc)
    return guarded


def _call(operation: Callable[[], _T]) -> ResponseEnvelope:
    try:
        result = operation()
    except Exception as exc:
        return _failure(exc)

    if isinstance(result, dict):
        return ResponseEnvelope.success(result)
    return ResponseEnvelope.success({"items": result})


def register_process_tools(mcp: MCPServer, service: ProcessService) -> None:
    """Register caller/session-scoped persistent process tools."""

    @mcp.tool()
    @_guard_tool_errors
    def sentra_process_sandbox_status(
        image: str | None = None,
    ) -> ResponseEnvelope:
        """Check whether the local trusted Docker sandbox boundary is available."""
        return _call(lambda: service.sandbox_status(image))

    @mcp.tool()
    @_guard_tool_errors
    def sentra_start_process(
        command: str | list[str],
        ctx: Context,
        owner: Annotated[
            str | None,
            Field(description="Optional label namespaced under the SENTRA conversation session."),
        ] = None,
        session_token: str | None = None,
        timeout: Annotated[
            float | None,
            Field(description="Optional process timeout in seconds. Must be greater than zero."),
        ] = None,
        cwd: Annotated[
            str | None,
            Field(description="Working directory relative to the selected workspace."),
        ] = None,
        workspace: Annotated[
            str | None,
            Field(description="Allowlisted workspace alias/root:N. Requires execute permission."),
        ] = None,
        mode: Annotated[
            Literal["sandbox", "workspace", "unrestricted"] | None,
            Field(
                description=(
                    "Execution isolation. sandbox=copy-on-write Docker; "
                    "workspace=approved project bind-mounted into Docker; "
                    "unrestricted=host process. Cannot exceed server privilege ceiling."
                )
            ),
        ] = None,
        image: Annotated[
            str | None,
            Field(description="Optional locally trusted sandbox image carrying org.oma.sandbox=1."),
        ] = None,
        run_id: Annotated[
            str | None,
            Field(description="Optional durable Run id. If omitted, an owner/workspace Run is created."),
        ] = None,
        idempotency_key: Annotated[
            str | None,
            Field(description="Stable key preventing duplicate process side effects after client timeouts."),
        ] = None,
        cleanup_policy: Literal["terminate_on_run_end", "preserve", "manual"] = "terminate_on_run_end",
        readiness_probe: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Optional real readiness probe. Supported keys: tcp_host/tcp_port, "
                    "http_url, stdout_contains, timeout_s. Loopback-only for network probes."
                )
            ),
        ] = None,
    ) -> ResponseEnvelope:
        """Start a persistent managed process with workspace permission enforcement."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: service.start_process(
            command,
            effective_owner,
            timeout,
            cwd,
            workspace=workspace,
            mode=mode,
            image=image,
            run_id=run_id,
            idempotency_key=idempotency_key,
            cleanup_policy=cleanup_policy,
            readiness_probe=readiness_probe,
        ))

    @mcp.tool()
    @_guard_tool_errors
    def sentra_read_process_output(
        session_id: str,
        ctx: Context,
        owner: Annotated[
            str | None,
            Field(description="Optional owner label under the SENTRA conversation session."),
        ] = None,
        session_token: str | None = None,
        offset: Annotated[
            int,
            Field(ge=0, description="Zero-based byte offset into retained stdout/stderr."),
        ] = 0,
        length: Annotated[
            int,
            Field(gt=0, description="Maximum bytes returned from each stream."),
        ] = 65536,
    ) -> ResponseEnvelope:
        """Read a bounded byte page of stdout/stderr from an owned session."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: service.read_process_output(
            session_id, effective_owner, offset, length
        ))

    @mcp.tool()
    @_guard_tool_errors
    def sentra_interact_process(
        session_id: str,
        stdin: str,
        ctx: Context,
        owner: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Write UTF-8 text to stdin of a running owned process/container."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: service.interact_with_process(
            session_id, effective_owner, stdin
        ))

    @mcp.tool()
    @_guard_tool_errors
    def sentra_list_sessions(
        ctx: Context,
        owner: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """List process sessions owned by this MCP conversation/session."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: _collection(
            "sessions", service.list_sessions(effective_owner)
        ))

    @mcp.tool()
    @_guard_tool_errors
    def sentra_terminate_session(
        session_id: str,
        ctx: Context,
        owner: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Terminate an owned process/container and its process tree."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: service.terminate_session(session_id, effective_owner))

    @mcp.tool()
    @_guard_tool_errors
    def sentra_list_processes(
        ctx: Context,
        owner: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """List managed processes visible to this MCP session."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: _collection(
            "processes", service.list_processes(effective_owner)
        ))

    @mcp.tool()
    @_guard_tool_errors
    def sentra_kill_process(
        pid: int,
        ctx: Context,
        owner: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Kill only a SENTRA-managed PID owned by this MCP session."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: service.kill_process(pid, effective_owner))
