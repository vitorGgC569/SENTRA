"""MCP tools for safe repository access and OMA observability."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server import MCPServer

from ..errors import sanitize_error
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
) -> None:
    @mcp.tool()
    async def sentra_repo_read(path: str, start: int = 1, end: int | None = None) -> ResponseEnvelope:
        """Read source through SENTRA's repository gateway."""
        return await _async_call(lambda: repository.read(path, start, end))

    @mcp.tool()
    async def sentra_repo_search(text: str, path: str = ".") -> ResponseEnvelope:
        """Literal repository search through the existing gateway."""
        return await _async_call(lambda: repository.search(text, path))

    @mcp.tool()
    async def sentra_repo_tree(path: str = ".", depth: int = 3) -> ResponseEnvelope:
        """Return a bounded repository tree."""
        return await _async_call(lambda: repository.tree(path, depth))

    @mcp.tool()
    async def sentra_repo_symbol(name: str) -> ResponseEnvelope:
        """Find Python definitions/references using the repository symbol command."""
        return await _async_call(lambda: repository.symbol(name))

    @mcp.tool()
    async def sentra_repo_status() -> ResponseEnvelope:
        """Return Git status through CommandGateway."""
        return await _async_call(repository.status)

    @mcp.tool()
    async def sentra_repo_diff(path: str | None = None) -> ResponseEnvelope:
        """Return Git diff through CommandGateway."""
        return await _async_call(lambda: repository.diff(path))

    @mcp.tool()
    async def sentra_repo_test(target: str = "all") -> ResponseEnvelope:
        """Run only SENTRA's registered pytest TEST operation; never a raw shell command."""
        return await _async_call(lambda: repository.test(target))

    @mcp.tool()
    def sentra_oma_health() -> ResponseEnvelope:
        """Report local SENTRA/OMA health and mutation policy."""
        return _sync_call(oma.health)

    @mcp.tool()
    def sentra_oma_runs(limit: int = 100) -> ResponseEnvelope:
        """List bounded run summaries from the workspace runs directory."""
        return _sync_call(lambda: oma.list_runs(limit))

    @mcp.tool()
    def sentra_oma_status(run_id: str) -> ResponseEnvelope:
        """Read a validated run status/handoff summary."""
        return _sync_call(lambda: oma.run_status(run_id))

    @mcp.tool()
    def sentra_oma_events(run_id: str, offset: int = 0, length: int = 100) -> ResponseEnvelope:
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
