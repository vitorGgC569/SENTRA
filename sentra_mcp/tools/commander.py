"""Commander-v1 MCP tool surface."""
from __future__ import annotations
from collections.abc import Awaitable, Callable
from typing import Any
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from ..errors import sanitize_error
from ..models import ResponseEnvelope
from ..services.browser import BrowserControlService
from ..services.documents import DocumentService
from ..services.runtime_config import RuntimeConfigService
from ..services.search_sessions import SearchSessionService
from ..services.telemetry import TelemetryService
from ..services.workspace_ops import WorkspaceOpsService
from sentra_remote.gateway import RemoteGatewayService


def _failure(exc: Exception) -> ResponseEnvelope:
    if isinstance(exc, PermissionError):
        code = "forbidden"
    elif isinstance(exc, FileNotFoundError):
        code = "not_found"
    elif isinstance(exc, (ValueError, TypeError)):
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


def register_commander_tools(
    mcp: MCPServer,
    *,
    search: SearchSessionService,
    runtime_config: RuntimeConfigService,
    telemetry: TelemetryService,
    documents: DocumentService,
    browser: BrowserControlService,
    workspace_ops: WorkspaceOpsService,
    remote: RemoteGatewayService,
) -> None:
    @mcp.tool()
    def sentra_start_search(path: str, pattern: str, search_type: str = "names", literal: bool = True,
                            ignore_case: bool = True, context: int = 0, max_results: int = 10000,
                            max_files: int = 100000) -> ResponseEnvelope:
        return _sync(lambda: search.start(path, pattern, search_type=search_type, literal=literal,
                                          ignore_case=ignore_case, context=context,
                                          max_results=max_results, max_files=max_files))

    @mcp.tool()
    def sentra_get_search_results(search_id: str, offset: int = 0, length: int = 100) -> ResponseEnvelope:
        return _sync(lambda: search.get_results(search_id, offset, length))

    @mcp.tool()
    def sentra_list_searches(limit: int = 100) -> ResponseEnvelope:
        return _sync(lambda: search.list_searches(limit))

    @mcp.tool()
    def sentra_stop_search(search_id: str) -> ResponseEnvelope:
        return _sync(lambda: search.stop(search_id))

    @mcp.tool()
    def sentra_get_config() -> ResponseEnvelope:
        return _sync(runtime_config.get_config)

    @mcp.tool()
    def sentra_update_config(changes: dict[str, Any]) -> ResponseEnvelope:
        return _sync(lambda: runtime_config.update(changes))

    @mcp.tool()
    def sentra_pending_config() -> ResponseEnvelope:
        return _sync(runtime_config.list_pending)

    @mcp.tool()
    def sentra_usage_stats() -> ResponseEnvelope:
        return _sync(telemetry.usage_stats)

    @mcp.tool()
    def sentra_recent_tool_calls(limit: int = 100) -> ResponseEnvelope:
        return _sync(lambda: telemetry.recent_calls(limit))

    @mcp.tool()
    def sentra_audit_query(action: str = "", outcome: str = "", contains: str = "", limit: int = 200) -> ResponseEnvelope:
        return _sync(lambda: telemetry.query(action=action, outcome=outcome, contains=contains, limit=limit))

    @mcp.tool()
    def sentra_document_info(path: str) -> ResponseEnvelope:
        return _sync(lambda: documents.document_info(path))

    @mcp.tool()
    def sentra_write_pdf(path: str, text: str, title: str = "SENTRA Document") -> ResponseEnvelope:
        return _sync(lambda: documents.write_pdf(path, text, title))

    @mcp.tool()
    async def sentra_browser_open(owner: str, url: str = "https://chatgpt.com",
                                  headless: bool = False, cdp_url: str | None = None) -> ResponseEnvelope:
        return await _async(lambda: browser.open(owner, url, headless=headless, cdp_url=cdp_url))

    @mcp.tool()
    async def sentra_browser_tabs(owner: str) -> ResponseEnvelope:
        return await _async(lambda: browser.tabs(owner))

    @mcp.tool()
    async def sentra_browser_navigate(session_id: str, owner: str, url: str) -> ResponseEnvelope:
        return await _async(lambda: browser.navigate(session_id, owner, url))

    @mcp.tool()
    async def sentra_browser_extract(session_id: str, owner: str, selector: str = "body",
                                     max_chars: int = 200000) -> ResponseEnvelope:
        return await _async(lambda: browser.extract(session_id, owner, selector, max_chars))

    @mcp.tool()
    async def sentra_browser_screenshot(session_id: str, owner: str, full_page: bool = True) -> ResponseEnvelope:
        return await _async(lambda: browser.screenshot(session_id, owner, full_page=full_page))

    @mcp.tool()
    async def sentra_browser_click(session_id: str, owner: str, selector: str) -> ResponseEnvelope:
        return await _async(lambda: browser.click(session_id, owner, selector))

    @mcp.tool()
    async def sentra_browser_type(session_id: str, owner: str, selector: str, text: str,
                                  clear: bool = False) -> ResponseEnvelope:
        return await _async(lambda: browser.type_text(session_id, owner, selector, text, clear=clear))

    @mcp.tool()
    async def sentra_browser_close(session_id: str, owner: str) -> ResponseEnvelope:
        return await _async(lambda: browser.close(session_id, owner))

    @mcp.tool()
    def sentra_create_workspace(path: str) -> ResponseEnvelope:
        return _sync(lambda: workspace_ops.create_workspace(path))

    @mcp.tool()
    def sentra_create_sandbox(source_path: str, owner: str) -> ResponseEnvelope:
        return _sync(lambda: workspace_ops.create_sandbox(source_path, owner))

    @mcp.tool()
    def sentra_apply_candidate(sandbox_id: str, owner: str, patch: str) -> ResponseEnvelope:
        return _sync(lambda: workspace_ops.apply_candidate(sandbox_id, owner, patch))

    @mcp.tool()
    async def sentra_verify_candidate(sandbox_id: str, owner: str,
                                      commands: list[str] | None = None,
                                      timeout: float = 120) -> ResponseEnvelope:
        return await _async(lambda: workspace_ops.verify_candidate(sandbox_id, owner, commands, timeout))

    @mcp.tool()
    def sentra_get_evidence(sandbox_id: str, owner: str) -> ResponseEnvelope:
        return _sync(lambda: workspace_ops.get_evidence(sandbox_id, owner))

    @mcp.tool()
    def sentra_rollback(sandbox_id: str, owner: str) -> ResponseEnvelope:
        return _sync(lambda: workspace_ops.rollback(sandbox_id, owner))

    @mcp.tool()
    def sentra_close_sandbox(sandbox_id: str, owner: str) -> ResponseEnvelope:
        return _sync(lambda: workspace_ops.close_sandbox(sandbox_id, owner))

    @mcp.tool()
    def sentra_run_quality_gate(task: dict[str, Any], candidate: dict[str, Any],
                                reports: list[dict[str, Any]], test_results: dict[str, Any],
                                min_release_score: float = 9.5) -> ResponseEnvelope:
        return _sync(lambda: workspace_ops.run_quality_gate(
            task, candidate, reports, test_results, min_release_score=min_release_score))

    @mcp.tool()
    def sentra_pair_device(name: str, platform: str, allowed_tools: list[str],
                           ttl_s: int = 300) -> ResponseEnvelope:
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
    def sentra_remote_call(device_id: str, tool: str, arguments: dict[str, Any],
                           timeout_s: int = 180, wait_s: float | None = None) -> ResponseEnvelope:
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
    def sentra_remote_read_file(device_id: str, path: str, offset: int = 0,
                                length: int | None = None) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_read_file",
                                  {"path": path, "offset": offset, "length": length})

    @mcp.tool()
    def sentra_remote_write_file(device_id: str, path: str, content: str,
                                 mode: str = "rewrite") -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_write_file",
                                  {"path": path, "content": content, "mode": mode})

    @mcp.tool()
    def sentra_remote_start_process(device_id: str, command: str | list[str], owner: str,
                                    timeout: float | None = None,
                                    cwd: str | None = None) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_start_process",
                                  {"command": command, "owner": owner, "timeout": timeout, "cwd": cwd})

    @mcp.tool()
    def sentra_remote_read_process_output(device_id: str, session_id: str, owner: str,
                                          offset: int = 0, length: int = 65536) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_read_process_output",
                                  {"session_id": session_id, "owner": owner,
                                   "offset": offset, "length": length})

    @mcp.tool()
    def sentra_remote_interact_process(device_id: str, session_id: str, owner: str,
                                       stdin: str) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_interact_process",
                                  {"session_id": session_id, "owner": owner, "stdin": stdin})

    @mcp.tool()
    def sentra_remote_repo_status(device_id: str) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_repo_status", {})

    @mcp.tool()
    def sentra_remote_oma_status(device_id: str, run_id: str) -> ResponseEnvelope:
        return sentra_remote_call(device_id, "sentra_oma_status", {"run_id": run_id})
