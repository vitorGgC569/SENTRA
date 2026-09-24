"""MCP tools for safe repository access and OMA observability."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from ..errors import sanitize_error
from ..identity import resolve_owner
from ..models import ResponseEnvelope
from ..services.oma import OmaService
from ..services.repository import RepositoryService


def _failure(exc: Exception) -> ResponseEnvelope:
    if isinstance(exc, PermissionError):
        code = "forbidden"
    elif isinstance(exc, FileNotFoundError):
        code = "not_found"
    elif isinstance(exc, (ValueError, TypeError)):
        code = "invalid_request"
    else:
        code = "sentra_error"
    return ResponseEnvelope.failure(code, sanitize_error(exc))


async def _async_call(operation: Callable[[], Awaitable[dict[str, Any]]]) -> ResponseEnvelope:
    try:
        return ResponseEnvelope.success(await operation())
    except Exception as exc:
        return _failure(exc)


def _sync_call(operation: Callable[[], dict[str, Any]]) -> ResponseEnvelope:
    try:
        return ResponseEnvelope.success(operation())
    except Exception as exc:
        return _failure(exc)


def register_sentra_tools(
    mcp: MCPServer,
    repository: RepositoryService,
    oma: OmaService,
    *,
    surfaces: set[str] | None = None,
) -> None:
    enabled = set(surfaces or {"developer", "oma"})

    if "developer" in enabled:
        @mcp.tool()
        def sentra_repo_workspaces(ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """List repository workspaces visible to this MCP session."""
            owner = resolve_owner(ctx, session_token=session_token)
            return _sync_call(lambda: repository.list_workspaces(owner))

        @mcp.tool()
        async def sentra_repo_read(
            path: str,
            ctx: Context,
            start: int = 1,
            end: int | None = None,
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Read source from a readable allowlisted repository workspace."""
            owner = resolve_owner(ctx, session_token=session_token)
            return await _async_call(
                lambda: repository.read(path, start, end, workspace, owner)
            )

        @mcp.tool()
        async def sentra_repo_search(
            text: str,
            ctx: Context,
            path: str = ".",
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Literal repository search in a readable allowlisted workspace."""
            owner = resolve_owner(ctx, session_token=session_token)
            return await _async_call(
                lambda: repository.search(text, path, workspace, owner)
            )

        @mcp.tool()
        async def sentra_repo_tree(
            ctx: Context,
            path: str = ".",
            depth: int = 3,
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Return a bounded repository tree from a readable workspace."""
            owner = resolve_owner(ctx, session_token=session_token)
            return await _async_call(
                lambda: repository.tree(path, depth, workspace, owner)
            )

        @mcp.tool()
        async def sentra_repo_symbol(
            name: str,
            ctx: Context,
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Find Python definitions/references in a readable workspace."""
            owner = resolve_owner(ctx, session_token=session_token)
            return await _async_call(
                lambda: repository.symbol(name, workspace, owner)
            )

        @mcp.tool()
        async def sentra_repo_status(
            ctx: Context,
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Return Git status for a readable allowlisted workspace."""
            owner = resolve_owner(ctx, session_token=session_token)
            return await _async_call(
                lambda: repository.status(workspace, owner)
            )

        @mcp.tool()
        async def sentra_repo_diff(
            ctx: Context,
            path: str | None = None,
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Return Git diff for a readable allowlisted workspace."""
            owner = resolve_owner(ctx, session_token=session_token)
            return await _async_call(
                lambda: repository.diff(path, workspace, owner)
            )

        @mcp.tool()
        async def sentra_repo_test(
            ctx: Context,
            target: str = "all",
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Compatibility synchronous TEST operation.

            Prefer sentra_test_start for suites that may exceed connector timeouts.
            Requires execute permission on the selected workspace.
            """
            owner = resolve_owner(ctx, session_token=session_token)
            return await _async_call(
                lambda: repository.test(target, workspace, owner)
            )

    if "oma" in enabled:
        @mcp.tool()
        def sentra_oma_health() -> ResponseEnvelope:
            """Report local SENTRA/OMA health and mutation policy."""
            return _sync_call(oma.health)

        @mcp.tool()
        def sentra_oma_runs(limit: int = 100) -> ResponseEnvelope:
            """List bounded run summaries from the primary SENTRA workspace."""
            return _sync_call(lambda: oma.list_runs(limit))

        @mcp.tool()
        def sentra_oma_status(run_id: str) -> ResponseEnvelope:
            """Read a validated run status/handoff summary."""
            return _sync_call(lambda: oma.run_status(run_id))

        @mcp.tool()
        def sentra_oma_events(
            run_id: str,
            offset: int = 0,
            length: int = 100,
        ) -> ResponseEnvelope:
            """Read a bounded page of structured run events."""
            return _sync_call(lambda: oma.read_events(run_id, offset, length))

        @mcp.tool()
        def sentra_oma_handoff(run_id: str) -> ResponseEnvelope:
            """Read only the allowlisted handoff artifact for a validated run."""
            return _sync_call(lambda: oma.read_handoff(run_id))

        @mcp.tool()
        def sentra_oma_queue_status() -> ResponseEnvelope:
            """Read MasterQueue status; does not mutate or promote candidates."""
            return _sync_call(oma.queue_status)

        @mcp.tool()
        def sentra_oma_reconcile_status(run_id: str) -> ResponseEnvelope:
            """Inspect blocked conversation seats without dropping/replaying them."""
            return _sync_call(lambda: oma.reconcile_status(run_id))
