"""MCP tool registration for persistent SENTRA process sessions."""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from mcp.server import MCPServer

from ..errors import sanitize_error
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
    """Register the owner-scoped persistent process tool surface."""

    @mcp.tool()
    def sentra_start_process(
        command: str | list[str],
        owner: str,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ResponseEnvelope:
        """Start a persistent managed process without invoking a shell."""

        return _call(lambda: service.start_process(command, owner, timeout, cwd))

    @mcp.tool()
    def sentra_read_process_output(
        session_id: str,
        owner: str,
        offset: int = 0,
        length: int = 65536,
    ) -> ResponseEnvelope:
        """Read a bounded page of stdout and stderr from an owned session."""

        return _call(lambda: service.read_process_output(session_id, owner, offset, length))

    @mcp.tool()
    def sentra_interact_process(
        session_id: str,
        owner: str,
        stdin: str,
    ) -> ResponseEnvelope:
        """Write text to stdin of a running owned process."""

        return _call(lambda: service.interact_with_process(session_id, owner, stdin))

    @mcp.tool()
    def sentra_list_sessions(owner: str) -> ResponseEnvelope:
        """List process sessions visible to an owner."""

        return _call(lambda: {"sessions": service.list_sessions(owner)})

    @mcp.tool()
    def sentra_terminate_session(session_id: str, owner: str) -> ResponseEnvelope:
        """Terminate an owned process session and its process tree."""

        return _call(lambda: service.terminate_session(session_id, owner))

    @mcp.tool()
    def sentra_list_processes(owner: str) -> ResponseEnvelope:
        """List managed processes visible to an owner."""

        return _call(lambda: {"processes": service.list_processes(owner)})

    @mcp.tool()
    def sentra_kill_process(pid: int, owner: str) -> ResponseEnvelope:
        """Kill only a process PID managed by SENTRA and owned by the caller."""

        return _call(lambda: service.kill_process(pid, owner))
