"""Unified local Commander MCP tool surface."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from ..errors import sanitize_error
from ..identity import resolve_owner
from ..models import ResponseEnvelope
from ..services.browser import BrowserControlService
from ..services.documents import DocumentService
from ..services.jobs import JobService
from ..services.research import ResearchService
from ..services.runtime_config import RuntimeConfigService
from ..services.search_sessions import SearchSessionService
from ..services.telemetry import TelemetryService
from ..services.workspace_ops import WorkspaceOpsService
from ..services.workspaces import WorkspaceRegistry


def _failure(exc: Exception) -> ResponseEnvelope:
    if isinstance(exc, PermissionError):
        code = "forbidden"
    elif isinstance(exc, FileNotFoundError):
        code = "not_found"
    elif isinstance(exc, FileExistsError):
        code = "conflict"
    elif isinstance(exc, (ValueError, TypeError, NotADirectoryError)):
        code = "invalid_request"
    else:
        code = "commander_error"
    return ResponseEnvelope.failure(code, sanitize_error(exc))


def _sync(fn: Callable[[], dict[str, Any]]) -> ResponseEnvelope:
    try:
        return ResponseEnvelope.success(fn())
    except Exception as exc:
        return _failure(exc)


async def _async(fn: Callable[[], Awaitable[dict[str, Any]]]) -> ResponseEnvelope:
    try:
        return ResponseEnvelope.success(await fn())
    except Exception as exc:
        return _failure(exc)


def register_commander_tools(
    mcp: MCPServer,
    *,
    search: SearchSessionService,
    runtime_config: RuntimeConfigService,
    telemetry: TelemetryService,
    documents: DocumentService,
    browser: BrowserControlService,
    workspace_ops: WorkspaceOpsService,
    workspaces: WorkspaceRegistry,
    jobs: JobService,
    research: ResearchService,
    surfaces: set[str] | None = None,
) -> None:
    enabled = set(surfaces or {"core", "developer", "browser"})

    if "core" in enabled:
        @mcp.tool()
        def sentra_start_search(
            path: str,
            pattern: str,
            ctx: Context,
            workspace: str | None = None,
            search_type: Literal["names", "content"] = "names",
            literal: bool = True,
            ignore_case: bool = True,
            context: Annotated[
                int,
                Field(ge=0, le=20, description="Context lines around content matches."),
            ] = 0,
            max_results: Annotated[
                int,
                Field(ge=1, le=100000, description="Maximum persisted matches."),
            ] = 10000,
            max_files: Annotated[
                int,
                Field(ge=1, le=500000, description="Maximum files scanned."),
            ] = 100000,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Start an owner-isolated persistent search in a readable workspace."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: search.start(
                path,
                pattern,
                owner=owner,
                workspace=workspace,
                search_type=search_type,
                literal=literal,
                ignore_case=ignore_case,
                context=context,
                max_results=max_results,
                max_files=max_files,
            ))

        @mcp.tool()
        def sentra_get_search_results(
            search_id: str,
            ctx: Context,
            offset: Annotated[
                int,
                Field(ge=0, description="Zero-based match offset."),
            ] = 0,
            length: Annotated[
                int,
                Field(ge=1, le=1000, description="Maximum matches returned."),
            ] = 100,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Read one page from a search owned by this MCP session."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: search.get_results(search_id, owner, offset, length))

        @mcp.tool()
        async def sentra_search_wait(
            search_id: str,
            ctx: Context,
            offset: Annotated[int, Field(ge=0)] = 0,
            length: Annotated[int, Field(ge=1, le=1000)] = 100,
            timeout_s: Annotated[
                float,
                Field(gt=0, le=25, description="Maximum connector-friendly wait."),
            ] = 5.0,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Wait briefly for a persistent search without client polling loops."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            try:
                deadline = time.monotonic() + timeout_s
                while True:
                    page = search.get_results(search_id, owner, offset, length)
                    if page["state"] not in {"RUNNING", "CANCELLING"}:
                        page["timed_out"] = False
                        return ResponseEnvelope.success(page)
                    if time.monotonic() >= deadline:
                        page["timed_out"] = True
                        return ResponseEnvelope.success(page)
                    await asyncio.sleep(
                        min(0.1, max(0.01, deadline - time.monotonic()))
                    )
            except Exception as exc:
                return _failure(exc)

        @mcp.tool()
        def sentra_list_searches(
            ctx: Context,
            limit: Annotated[int, Field(ge=1, le=1000)] = 100,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """List persistent searches owned by this MCP session."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: search.list_searches(owner, limit))

        @mcp.tool()
        def sentra_stop_search(search_id: str, ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Cancel a search owned by this MCP session."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: search.stop(search_id, owner))

        @mcp.tool()
        def sentra_document_info(
            path: str,
            ctx: Context,
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Return bounded metadata for a document in a readable workspace."""
            owner = resolve_owner(ctx, session_token=session_token)
            return _sync(lambda: documents.document_info(
                path,
                workspace=workspace,
                owner=owner,
            ))

        @mcp.tool()
        def sentra_read_document(
            path: str,
            ctx: Context,
            workspace: str | None = None,
            offset: Annotated[int, Field(ge=0)] = 0,
            limit: Annotated[int, Field(ge=1, le=1000)] = 100,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Read PDF, DOCX, CSV, Parquet, JSONL or ipynb structurally."""
            owner = resolve_owner(ctx, session_token=session_token)
            return _sync(lambda: documents.read_document(
                path,
                workspace=workspace,
                owner=owner,
                offset=offset,
                limit=limit,
            ))

        @mcp.tool()
        def sentra_write_pdf(
            path: str,
            text: str,
            ctx: Context,
            title: str = "SENTRA Document",
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Create a text PDF only in a workspace granting write permission."""
            owner = resolve_owner(ctx, session_token=session_token)
            return _sync(lambda: documents.write_pdf(
                path,
                text,
                title,
                workspace=workspace,
                owner=owner,
            ))

    if "developer" in enabled:
        @mcp.tool()
        def sentra_workspaces(ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """List workspace grants visible to this MCP session."""
            owner = resolve_owner(ctx, session_token=session_token)
            return _sync(lambda: workspaces.list_workspaces(owner))

        @mcp.tool()
        def sentra_request_workspace(
            path: str,
            ctx: Context,
            alias: str | None = None,
            permissions: list[Literal["read", "write", "execute"]] = ["read"],
            lifetime: str = "permanent",
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Request a new workspace grant.

            This tool never approves access. The local operator must approve the
            returned request_id with sentra_remote.admin.
            """
            owner = resolve_owner(ctx, session_token=session_token, require_session=lifetime.strip().lower() == "session")
            return _sync(lambda: workspaces.request_add(
                path=path,
                owner=owner,
                alias=alias,
                permissions=permissions,
                lifetime=lifetime,
            ))

        @mcp.tool()
        def sentra_request_allowed_root(
            path: str,
            ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Compatibility alias requesting permanent read/write/execute access."""
            owner = resolve_owner(ctx, session_token=session_token)
            return _sync(lambda: workspaces.request_add(
                path=path,
                owner=owner,
                alias=None,
                permissions=("read", "write", "execute"),
                lifetime="permanent",
            ))

        @mcp.tool()
        def sentra_request_remove_workspace(
            workspace: str,
            ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Request removal of a dynamic workspace grant; local approval is required."""
            owner = resolve_owner(ctx, session_token=session_token)
            return _sync(lambda: workspaces.request_remove(workspace, owner))

        @mcp.tool()
        def sentra_pending_workspaces() -> ResponseEnvelope:
            """List locally pending workspace add/remove requests."""
            return _sync(workspaces.pending)

        @mcp.tool()
        def sentra_create_workspace(
            path: str,
            ctx: Context,
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Create a directory inside a writable workspace."""
            owner = resolve_owner(ctx, session_token=session_token)
            return _sync(lambda: workspace_ops.create_workspace(
                path,
                owner,
                workspace,
            ))

        @mcp.tool()
        def sentra_create_sandbox(
            source_path: str,
            ctx: Context,
            workspace: str | None = None,
            owner: Annotated[
                str | None,
                Field(description="Optional label namespaced under this MCP session."),
            ] = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Create an owner-isolated filesystem snapshot from a readable workspace."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return _sync(lambda: workspace_ops.create_sandbox(
                source_path,
                effective_owner,
                workspace,
            ))

        @mcp.tool()
        def sentra_apply_candidate(
            sandbox_id: str,
            patch: str,
            ctx: Context,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Apply a candidate patch inside a managed sandbox only."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return _sync(lambda: workspace_ops.apply_candidate(
                sandbox_id,
                effective_owner,
                patch,
            ))

        @mcp.tool()
        async def sentra_verify_candidate(
            sandbox_id: str,
            ctx: Context,
            commands: list[str] | None = None,
            timeout: float = 120,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Run registered deterministic validation commands in a sandbox."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: workspace_ops.verify_candidate(
                sandbox_id,
                effective_owner,
                commands,
                timeout,
            ))

        @mcp.tool()
        def sentra_get_evidence(
            sandbox_id: str,
            ctx: Context,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Read latest deterministic sandbox evidence."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return _sync(lambda: workspace_ops.get_evidence(
                sandbox_id,
                effective_owner,
            ))

        @mcp.tool()
        def sentra_rollback(
            sandbox_id: str,
            ctx: Context,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Reset a managed sandbox to baseline."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return _sync(lambda: workspace_ops.rollback(
                sandbox_id,
                effective_owner,
            ))

        @mcp.tool()
        def sentra_close_sandbox(
            sandbox_id: str,
            ctx: Context,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Destroy a managed sandbox."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return _sync(lambda: workspace_ops.close_sandbox(
                sandbox_id,
                effective_owner,
            ))

        @mcp.tool()
        def sentra_run_quality_gate(
            task: dict[str, Any],
            candidate: dict[str, Any],
            reports: list[dict[str, Any]],
            test_results: dict[str, Any],
            min_release_score: float = 9.5,
        ) -> ResponseEnvelope:
            """Evaluate SENTRA's deterministic QualityGate from explicit evidence."""
            return _sync(lambda: workspace_ops.run_quality_gate(
                task,
                candidate,
                reports,
                test_results,
                min_release_score=min_release_score,
            ))

        @mcp.tool()
        def sentra_job_start(
            operation: Literal["TEST", "LINT", "TYPECHECK", "BUILD", "BENCH"],
            ctx: Context,
            workspace: str | None = None,
            target: str = "",
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Start a registered long-running repository operation asynchronously."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: jobs.start(
                operation,
                owner,
                target=target,
                workspace=workspace,
            ))

        @mcp.tool()
        def sentra_test_start(
            ctx: Context,
            target: str = "all",
            workspace: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Start pytest asynchronously and return immediately with a job_id."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: jobs.start(
                "TEST",
                owner,
                target=target,
                workspace=workspace,
            ))

        @mcp.tool()
        def sentra_job_status(job_id: str, ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Return status for a job owned by this MCP session."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: jobs.status(job_id, owner))

        @mcp.tool()
        async def sentra_job_wait(
            job_id: str,
            ctx: Context,
            timeout_s: Annotated[float, Field(gt=0, le=25)] = 5.0,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Wait connector-safely for an asynchronous repository job."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return await _async(lambda: asyncio.to_thread(
                jobs.wait,
                job_id,
                owner,
                timeout_s,
            ))

        @mcp.tool()
        def sentra_job_result(job_id: str, ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Return final output for a completed repository job."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: jobs.result(job_id, owner))

        @mcp.tool()
        def sentra_job_cancel(job_id: str, ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Cancel an asynchronous job and its underlying registered operation."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: jobs.cancel(job_id, owner))

        @mcp.tool()
        def sentra_list_jobs(
            ctx: Context,
            limit: Annotated[int, Field(ge=1, le=1000)] = 100,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """List asynchronous jobs owned by this MCP session."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: jobs.list_jobs(owner, limit))

    if "browser" in enabled:
        @mcp.tool()
        async def sentra_browser_open(
            ctx: Context,
            url: str = "https://chatgpt.com",
            backend: Literal["auto", "playwright", "edge"] = "auto",
            headless: bool = False,
            cdp_url: str | None = None,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Open a browser session; Edge auto-selection uses READY workers only."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: browser.open(
                effective_owner,
                url,
                backend=backend,
                headless=headless,
                cdp_url=cdp_url,
            ))

        @mcp.tool()
        async def sentra_browser_tabs(
            ctx: Context,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """List Playwright sessions and Edge workers with explicit health states."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: browser.tabs(effective_owner))

        @mcp.tool()
        async def sentra_browser_navigate(
            session_id: str,
            url: str,
            ctx: Context,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Navigate either an edge:* or playwright:* session."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: browser.navigate(
                session_id,
                effective_owner,
                url,
            ))

        @mcp.tool()
        async def sentra_browser_extract(
            session_id: str,
            ctx: Context,
            selector: str = "body",
            max_chars: Annotated[int, Field(ge=1, le=1000000)] = 200000,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Extract visible text from a browser selector."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: browser.extract(
                session_id,
                effective_owner,
                selector,
                max_chars,
            ))

        @mcp.tool()
        async def sentra_browser_screenshot(
            session_id: str,
            ctx: Context,
            full_page: bool = True,
            include_base64: bool = False,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Capture a Playwright screenshot; base64 is opt-in."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: browser.screenshot(
                session_id,
                effective_owner,
                full_page=full_page,
                include_base64=include_base64,
            ))

        @mcp.tool()
        async def sentra_browser_click(
            session_id: str,
            selector: str,
            ctx: Context,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Click a selector in either browser backend."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: browser.click(
                session_id,
                effective_owner,
                selector,
            ))

        @mcp.tool()
        async def sentra_browser_type(
            session_id: str,
            selector: str,
            text: str,
            ctx: Context,
            clear: bool = False,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Type bounded text into a browser selector."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: browser.type_text(
                session_id,
                effective_owner,
                selector,
                text,
                clear=clear,
            ))

        @mcp.tool()
        async def sentra_browser_close(
            session_id: str,
            ctx: Context,
            owner: str | None = None,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Close/release a browser session."""
            effective_owner = resolve_owner(ctx, owner, session_token=session_token, require_session=True)
            return await _async(lambda: browser.close(
                session_id,
                effective_owner,
            ))

    if {"developer", "browser"} <= enabled:
        @mcp.tool()
        async def sentra_research_start(
            objective: str,
            ctx: Context,
            strategy: Literal["single", "parallel", "mcts"] = "parallel",
            temporary: bool = True,
            branches: Annotated[int, Field(ge=1, le=4)] = 3,
            max_depth: Annotated[int, Field(ge=1, le=3)] = 2,
            beam_width: Annotated[int, Field(ge=1, le=3)] = 2,
            timeout_s: Annotated[int, Field(ge=30, le=600)] = 300,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Start bounded research in temporary independent ChatGPT conversations.

            mcts is a bounded MCTS-inspired beam search, not full UCT.
            """
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return await _async(lambda: research.start(
                objective,
                owner,
                strategy=strategy,
                temporary=temporary,
                branches=branches,
                max_depth=max_depth,
                beam_width=beam_width,
                timeout_s=timeout_s,
            ))

        @mcp.tool()
        def sentra_research_status(run_id: str, ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Return status for an owned research run."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: research.status(run_id, owner))

        @mcp.tool()
        async def sentra_research_wait(
            run_id: str,
            ctx: Context,
            timeout_s: Annotated[float, Field(gt=0, le=25)] = 5.0,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Wait briefly for a research run."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return await _async(lambda: research.wait(
                run_id,
                owner,
                timeout_s,
            ))

        @mcp.tool()
        def sentra_research_result(run_id: str, ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Return final research synthesis and branch evidence."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: research.result(run_id, owner))

        @mcp.tool()
        def sentra_research_cancel(run_id: str, ctx: Context,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """Cancel a research run and clean temporary chats where possible."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: research.cancel(run_id, owner))

        @mcp.tool()
        def sentra_list_research_runs(
            ctx: Context,
            limit: Annotated[int, Field(ge=1, le=1000)] = 100,
            session_token: str | None = None,
        ) -> ResponseEnvelope:
            """List research runs owned by this MCP session."""
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            return _sync(lambda: research.list_runs(owner, limit))

    if "admin" in enabled:
        @mcp.tool()
        def sentra_get_config() -> ResponseEnvelope:
            """Read effective non-secret runtime configuration."""
            return _sync(runtime_config.get_config)

        @mcp.tool()
        def sentra_update_config(changes: dict[str, Any]) -> ResponseEnvelope:
            """Apply safe settings; privileged settings require local CLI approval."""
            return _sync(lambda: runtime_config.update(changes))

        @mcp.tool()
        def sentra_reload_approved_config() -> ResponseEnvelope:
            """Activate locally approved static config fields without granting new access."""
            return _sync(runtime_config.reload_approved)

        @mcp.tool()
        def sentra_pending_config() -> ResponseEnvelope:
            """List privileged static config requests waiting for local approval."""
            return _sync(runtime_config.list_pending)

        @mcp.tool()
        def sentra_usage_stats() -> ResponseEnvelope:
            """Aggregate local MCP audit/usage statistics."""
            return _sync(telemetry.usage_stats)

        @mcp.tool()
        def sentra_recent_tool_calls(
            limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        ) -> ResponseEnvelope:
            """Read recent redacted audit records."""
            return _sync(lambda: telemetry.recent_calls(limit))

        @mcp.tool()
        def sentra_audit_query(
            action: str = "",
            outcome: str = "",
            contains: str = "",
            limit: Annotated[int, Field(ge=1, le=5000)] = 200,
        ) -> ResponseEnvelope:
            """Query redacted audit records."""
            return _sync(lambda: telemetry.query(
                action=action,
                outcome=outcome,
                contains=contains,
                limit=limit,
            ))
