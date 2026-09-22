"""MCP tool registration for persistent SENTRA process sessions."""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from ..errors import sanitize_error
from ..identity import resolve_owner
from ..models import ResponseEnvelope
from ..services.process import ProcessService

_T = TypeVar("_T")


def _call(operation: Callable[[], _T]) -> ResponseEnvelope:
    try:
        result = operation()
    except PermissionError as exc:
        return ResponseEnvelope.failure("forbidden", sanitize_error(exc))
    except KeyError as exc:
        return ResponseEnvelope.failure("not_found", sanitize_error(exc))
    except ValueError as exc:
        return ResponseEnvelope.failure("invalid_request", sanitize_error(exc))
    except (OSError, RuntimeError) as exc:
        return ResponseEnvelope.failure("process_error", sanitize_error(exc))

    if isinstance(result, dict):
        return ResponseEnvelope.success(result)
    return ResponseEnvelope.success({"items": result})


def register_process_tools(mcp: MCPServer, service: ProcessService) -> None:
    """Register caller/session-scoped persistent process tools."""

    @mcp.tool()
    def sentra_process_sandbox_status(
        image: str | None = None,
    ) -> ResponseEnvelope:
        """Check whether the local trusted Docker sandbox boundary is available."""
        return _call(lambda: service.sandbox_status(image))

    @mcp.tool()
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
        ))

    @mcp.tool()
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
    def sentra_list_sessions(
        ctx: Context,
        owner: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """List process sessions owned by this MCP conversation/session."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: {"sessions": service.list_sessions(effective_owner)})

    @mcp.tool()
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
    def sentra_list_processes(
        ctx: Context,
        owner: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """List managed processes visible to this MCP session."""
        effective_owner = resolve_owner(
            ctx, owner, session_token=session_token, require_session=True
        )
        return _call(lambda: {"processes": service.list_processes(effective_owner)})

    @mcp.tool()
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
