"""MCP wrappers for the protocol-independent filesystem service."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer

from workspace.paths import PathAccessError

from ..errors import error_envelope
from ..models import ResponseEnvelope
from ..services.filesystem import FilesystemService


def _call(operation: Callable[[], dict[str, Any]]) -> ResponseEnvelope:
    try:
        return ResponseEnvelope.success(operation())
    except PathAccessError as exc:
        return error_envelope(exc, code="path_denied")
    except FileNotFoundError as exc:
        return error_envelope(exc, code="not_found")
    except FileExistsError as exc:
        return error_envelope(exc, code="conflict")
    except UnicodeDecodeError as exc:
        return error_envelope(exc, code="invalid_text")
    except (ValueError, re.error) as exc:
        return error_envelope(exc, code="invalid_request")
    except OSError as exc:
        return error_envelope(exc, code="filesystem_error")
    except Exception as exc:
        return error_envelope(exc, code="internal_error")


def register_filesystem_tools(mcp: MCPServer, service: FilesystemService) -> None:
    """Register the bounded SENTRA filesystem tools on an MCP server."""

    @mcp.tool()
    def sentra_list_directory(path: str = ".", depth: int = 2) -> ResponseEnvelope:
        """List a directory recursively up to the requested bounded depth."""

        return _call(lambda: service.list_directory(path, depth))

    @mcp.tool()
    def sentra_read_file(
        path: str,
        offset: int = 0,
        length: int | None = None,
    ) -> ResponseEnvelope:
        """Read UTF-8 text by line offset/length under the configured byte limit."""

        return _call(lambda: service.read_file(path, offset, length))

    @mcp.tool()
    def sentra_read_multiple_files(
        paths: list[str],
        offset: int = 0,
        length: int | None = None,
    ) -> ResponseEnvelope:
        """Read several UTF-8 text files without aborting on one failed item."""

        return _call(lambda: service.read_multiple_files(paths, offset, length))

    @mcp.tool()
    def sentra_file_info(path: str) -> ResponseEnvelope:
        """Return bounded metadata for a file or directory."""

        return _call(lambda: service.file_info(path))

    @mcp.tool()
    def sentra_search(
        path: str,
        pattern: str,
        search_type: str = "names",
        literal: bool = True,
        ignore_case: bool = True,
        max_results: int = 100,
        context: int = 0,
    ) -> ResponseEnvelope:
        """Search file names or UTF-8 content with literal or regex matching."""

        return _call(
            lambda: service.search(
                path,
                pattern,
                search_type,
                literal,
                ignore_case,
                max_results,
                context,
            )
        )

    @mcp.tool()
    def sentra_create_directory(path: str) -> ResponseEnvelope:
        """Create a directory inside an allowed root."""

        return _call(lambda: service.create_directory(path))

    @mcp.tool()
    def sentra_move_file(source: str, destination: str) -> ResponseEnvelope:
        """Move or rename a file or directory between allowed locations."""

        return _call(lambda: service.move_file(source, destination))

    @mcp.tool()
    def sentra_write_file(
        path: str,
        content: str,
        mode: str = "rewrite",
    ) -> ResponseEnvelope:
        """Rewrite or append UTF-8 text within the configured write limit."""

        return _call(lambda: service.write_file(path, content, mode))

    @mcp.tool()
    def sentra_edit_block(
        path: str,
        old: str,
        new: str,
        expected_replacements: int = 1,
    ) -> ResponseEnvelope:
        """Apply an exact, deterministic text replacement."""

        return _call(
            lambda: service.edit_block(
                path,
                old,
                new,
                expected_replacements,
            )
        )
