"""MCP wrappers for the protocol-independent filesystem service."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from workspace.paths import PathAccessError

from ..errors import error_envelope
from ..identity import open_conversation_session, resolve_owner
from ..models import ResponseEnvelope
from ..services.filesystem import FilesystemService
from ..version import CAPABILITY_VERSION, PROTOCOL_VERSION, SERVER_VERSION


def _call(operation: Callable[[], dict[str, Any]]) -> ResponseEnvelope:
    try:
        return ResponseEnvelope.success(operation())
    except PathAccessError as exc:
        return error_envelope(exc, code="path_denied")
    except PermissionError as exc:
        return error_envelope(exc, code="forbidden")
    except FileNotFoundError as exc:
        return error_envelope(exc, code="not_found")
    except FileExistsError as exc:
        return error_envelope(exc, code="conflict")
    except IsADirectoryError as exc:
        return error_envelope(exc, code="invalid_request")
    except UnicodeDecodeError as exc:
        return error_envelope(exc, code="invalid_text")
    except (ValueError, re.error) as exc:
        return error_envelope(exc, code="invalid_request")
    except OSError as exc:
        return error_envelope(exc, code="filesystem_error")
    except Exception as exc:
        return error_envelope(exc, code="internal_error")


def register_filesystem_tools(
    mcp: MCPServer,
    service: FilesystemService,
    capabilities: Any | None = None,
) -> None:
    """Register bounded, workspace-aware filesystem tools."""

    @mcp.tool()
    def sentra_session_open(
        ctx: Context,
        ttl_hours: Annotated[
            int,
            Field(ge=1, le=720, description="Conversation-session lifetime in hours."),
        ] = 24,
    ) -> ResponseEnvelope:
        """Open an opaque SENTRA conversation session.

        MCP 2026-07-28 HTTP is stateless. Call this once per ChatGPT
        conversation and pass session_token to owner-scoped tools. The token is
        signed locally and can be reused after HTTP reconnects until expiry.
        """
        def open_with_contract() -> dict[str, Any]:
            result = open_conversation_session(ctx, ttl_hours=ttl_hours)
            if capabilities is not None:
                schema = capabilities.schema()
                build = dict(getattr(capabilities, "build_identity", {}) or {})
                result["contract"] = {
                    "protocol_version": PROTOCOL_VERSION,
                    "server_version": SERVER_VERSION,
                    "capability_version": CAPABILITY_VERSION,
                    "schema_hash": schema["schema_hash"],
                    "tool_count": schema["tool_count"],
                    "build_id": build.get("build_id"),
                    "source_hash": build.get("source_hash"),
                    "fingerprint": build.get("fingerprint"),
                }
            return result
        return _call(open_with_contract)

    @mcp.tool()
    def sentra_list_directory(
        ctx: Context,
        path: str = ".",
        depth: Annotated[int, Field(ge=1, le=8, description="Recursive directory depth, 1 through 8.")] = 2,
        workspace: Annotated[
            str | None,
            Field(description="Optional allowlisted workspace alias/root:N. Relative paths default to root:0."),
        ] = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """List a directory recursively inside a readable workspace."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.list_directory(path, depth, workspace=workspace, owner=owner))

    @mcp.tool()
    def sentra_read_file(
        path: str,
        ctx: Context,
        offset: Annotated[int, Field(ge=0, description="Zero-based line offset.")] = 0,
        length: Annotated[
            int | None,
            Field(gt=0, description="Maximum number of text lines; null means until EOF within byte limits."),
        ] = None,
        workspace: Annotated[
            str | None,
            Field(description="Optional allowlisted workspace alias/root:N."),
        ] = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Read UTF-8 text from a workspace granting read permission."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.read_file(
            path, offset, length, workspace=workspace, owner=owner
        ))

    @mcp.tool()
    def sentra_read_multiple_files(
        paths: list[str],
        ctx: Context,
        offset: Annotated[int, Field(ge=0, description="Zero-based line offset applied to every file.")] = 0,
        length: Annotated[
            int | None,
            Field(gt=0, description="Maximum lines per file; null means until EOF within byte limits."),
        ] = None,
        workspace: Annotated[
            str | None,
            Field(description="Optional allowlisted workspace alias/root:N applied to relative paths."),
        ] = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Read several UTF-8 files without aborting on one failed item."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.read_multiple_files(
            paths, offset, length, workspace=workspace, owner=owner
        ))

    @mcp.tool()
    def sentra_file_info(
        path: str,
        ctx: Context,
        workspace: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Return bounded metadata for a file or directory in a readable workspace."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.file_info(path, workspace=workspace, owner=owner))

    @mcp.tool()
    def sentra_search(
        path: str,
        pattern: str,
        ctx: Context,
        search_type: Literal["names", "content"] = "names",
        literal: bool = True,
        ignore_case: bool = True,
        max_results: Annotated[int, Field(ge=1, le=1000, description="Maximum matches returned.")] = 100,
        context: Annotated[int, Field(ge=0, description="Context lines around content matches.")] = 0,
        workspace: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Search file names or UTF-8 content inside a readable workspace."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.search(
            path,
            pattern,
            search_type,
            literal,
            ignore_case,
            max_results,
            context,
            workspace=workspace,
            owner=owner,
        ))

    @mcp.tool()
    def sentra_create_directory(
        path: str,
        ctx: Context,
        workspace: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Create a directory only in a workspace granting write permission."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.create_directory(path, workspace=workspace, owner=owner))

    @mcp.tool()
    def sentra_move_file(
        source: str,
        destination: str,
        ctx: Context,
        workspace: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Move/rename a file where source and destination both grant write permission."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.move_file(
            source, destination, workspace=workspace, owner=owner
        ))

    @mcp.tool()
    def sentra_delete_path(
        path: str,
        ctx: Context,
        recursive: bool = False,
        confirm_directory: bool = False,
        workspace: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Delete a path only from a writable workspace.

        Directory deletion requires both recursive=true and
        confirm_directory=true. Workspace roots themselves cannot be deleted.
        """
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.delete_path(
            path,
            recursive=recursive,
            confirm_directory=confirm_directory,
            workspace=workspace,
            owner=owner,
        ))

    @mcp.tool()
    def sentra_write_file(
        path: str,
        content: str,
        ctx: Context,
        mode: Literal["rewrite", "append"] = "rewrite",
        workspace: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Write UTF-8 text only in a workspace granting write permission."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.write_file(
            path, content, mode, workspace=workspace, owner=owner
        ))

    @mcp.tool()
    def sentra_edit_block(
        path: str,
        old: str,
        new: str,
        ctx: Context,
        expected_replacements: Annotated[
            int,
            Field(ge=1, description="Exact replacement count required before mutation."),
        ] = 1,
        workspace: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Replace an exact text block only in a writable workspace."""
        owner = resolve_owner(ctx, session_token=session_token)
        return _call(lambda: service.edit_block(
            path,
            old,
            new,
            expected_replacements,
            workspace=workspace,
            owner=owner,
        ))
