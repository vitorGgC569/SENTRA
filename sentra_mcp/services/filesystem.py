"""Protocol-independent, bounded filesystem operations for SENTRA MCP."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from workspace.paths import PathAccessError, iter_workspace_files, resolve_workspace_path

from ..audit import AuditLogger
from ..config import MCPConfig
from ..errors import sanitize_error
from .workspaces import WorkspaceRegistry

MAX_LIST_DEPTH = 8
MAX_SEARCH_RESULTS = 1000


class FilesystemService:
    """Filesystem service constrained to approved workspace grants."""

    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger,
        workspaces: WorkspaceRegistry | None = None,
    ) -> None:
        self.config = config
        self.allowed_roots = tuple(config.allowed_roots)  # legacy/introspection
        self.max_read_bytes = config.max_read_bytes
        self.max_write_bytes = config.max_write_bytes
        self.audit = audit
        self.workspaces = workspaces

    def update_config(self, config: MCPConfig) -> None:
        self.config = config
        self.allowed_roots = tuple(config.allowed_roots)
        self.max_read_bytes = config.max_read_bytes
        self.max_write_bytes = config.max_write_bytes

    def _legacy_workspace(
        self,
        raw: str,
        permission: str,
    ) -> tuple[int, Path, dict[str, Any]]:
        candidate = Path(raw)
        roots = tuple(Path(root).resolve() for root in self.allowed_roots)
        if not candidate.is_absolute():
            index, root = 0, roots[0]
        else:
            match = None
            for idx, root in enumerate(roots):
                try:
                    candidate.resolve().relative_to(root)
                except ValueError:
                    continue
                match = (idx, root)
                break
            if match is None:
                raise PathAccessError("absolute path is outside configured allowed roots")
            index, root = match
        return index, root, {
            "id": f"root:{index}",
            "workspace_id": f"config:{index}",
            "alias": "sentra" if index == 0 else root.name,
            "path": str(root),
            "permissions": ["execute", "read", "write"],
        }

    def _select_workspace(
        self,
        raw: str,
        *,
        workspace: str | None,
        owner: str | None,
        permission: str,
    ) -> tuple[int, Path, dict[str, Any]]:
        if self.workspaces is None:
            return self._legacy_workspace(raw, permission)
        if workspace is not None and str(workspace).strip():
            view = self.workspaces.resolve(workspace, owner, permission)
        else:
            candidate = Path(raw)
            if candidate.is_absolute():
                try:
                    view = self.workspaces.resolve_path(candidate, owner, permission)
                except PermissionError as exc:
                    raise PathAccessError(str(exc)) from exc
            else:
                view = self.workspaces.resolve(None, owner, permission)
        return int(str(view["id"]).split(":", 1)[1]), Path(view["path"]).resolve(), view

    def _resolve_access(
        self,
        raw: str,
        *,
        workspace: str | None = None,
        owner: str | None = None,
        permission: str = "read",
    ) -> tuple[int, Path, str, dict[str, Any]]:
        if not isinstance(raw, str) or not raw:
            raise PathAccessError("workspace path must be a non-empty string")
        index, root, view = self._select_workspace(
            raw,
            workspace=workspace,
            owner=owner,
            permission=permission,
        )
        candidate = Path(raw)
        if candidate.is_absolute():
            try:
                relative_path = candidate.resolve().relative_to(root)
            except ValueError as exc:
                raise PathAccessError("absolute path is outside selected workspace") from exc
            relative = relative_path.as_posix() or "."
        else:
            relative = raw
        target = resolve_workspace_path(root, relative)
        rel = target.relative_to(root).as_posix() or "."
        return index, target, rel, view

    # Kept for internal/backward compatibility with services created before the
    # workspace registry. New callers should pass workspace/owner explicitly.
    def _resolve(
        self,
        raw: str,
        workspace: str | None = None,
        owner: str | None = None,
        permission: str = "read",
    ) -> tuple[int, Path, str]:
        index, target, relative, _ = self._resolve_access(
            raw,
            workspace=workspace,
            owner=owner,
            permission=permission,
        )
        return index, target, relative

    @staticmethod
    def _workspace_fields(view: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace": view["id"],
            "workspace_id": view["workspace_id"],
            "workspace_alias": view["alias"],
        }

    def _read_text(
        self,
        target: Path,
        offset: int = 0,
        length: int | None = None,
    ) -> tuple[str, int]:
        if offset < 0:
            raise ValueError("offset must be zero or greater")
        if length is not None and length <= 0:
            raise ValueError("length must be greater than zero")
        if not target.is_file():
            raise FileNotFoundError("file does not exist")
        selected: list[bytes] = []
        selected_bytes = 0
        selected_lines = 0
        with target.open("rb") as handle:
            for line_index, raw_line in enumerate(handle):
                if line_index < offset:
                    continue
                if length is not None and selected_lines >= length:
                    break
                selected_bytes += len(raw_line)
                if selected_bytes > self.max_read_bytes:
                    raise ValueError("read exceeds configured byte limit")
                selected.append(raw_line)
                selected_lines += 1
        content = b"".join(selected).decode("utf-8")
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        return content, selected_lines

    def list_directory(
        self,
        path: str = ".",
        depth: int = 2,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        if depth < 1 or depth > MAX_LIST_DEPTH:
            raise ValueError(f"depth must be between 1 and {MAX_LIST_DEPTH}")
        _, base, relative, view = self._resolve_access(
            path, workspace=workspace, owner=owner, permission="read"
        )
        if not base.is_dir():
            raise NotADirectoryError("path is not a directory")
        root = Path(view["path"]).resolve()
        entries: list[dict[str, Any]] = []

        def visit(directory: Path, level: int) -> None:
            for child in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
                lexical_relative = child.relative_to(root).as_posix()
                try:
                    checked = resolve_workspace_path(root, lexical_relative)
                except (PathAccessError, OSError):
                    continue
                if checked.is_dir():
                    kind = "directory"
                elif checked.is_file():
                    kind = "file"
                else:
                    kind = "other"
                entries.append({"path": lexical_relative, "type": kind})
                is_junction = getattr(child, "is_junction", lambda: False)()
                if (
                    kind == "directory"
                    and level < depth
                    and not child.is_symlink()
                    and not is_junction
                ):
                    visit(child, level + 1)

        visit(base, 1)
        return {
            "path": relative,
            "depth": depth,
            "entries": entries,
            "items": entries,
            "page": {
                "offset": 0,
                "limit": len(entries),
                "returned": len(entries),
                "total": len(entries),
                "next_offset": None,
            },
            **self._workspace_fields(view),
        }

    def read_file(
        self,
        path: str,
        offset: int = 0,
        length: int | None = None,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        _, target, relative, view = self._resolve_access(
            path, workspace=workspace, owner=owner, permission="read"
        )
        content, line_count = self._read_text(target, offset, length)
        return {
            "path": relative,
            "offset": offset,
            "line_count": line_count,
            "content": content,
            **self._workspace_fields(view),
        }

    def read_multiple_files(
        self,
        paths: list[str],
        offset: int = 0,
        length: int | None = None,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for path in paths:
            try:
                results.append({
                    "ok": True,
                    **self.read_file(
                        path, offset, length, workspace=workspace, owner=owner
                    ),
                })
            except Exception as exc:
                results.append({"ok": False, "path": path, "error": sanitize_error(exc)})
        return {
            "results": results,
            "items": results,
            "page": {
                "offset": 0,
                "limit": len(results),
                "returned": len(results),
                "total": len(results),
                "next_offset": None,
            },
        }

    def file_info(
        self,
        path: str,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        _, target, relative, view = self._resolve_access(
            path, workspace=workspace, owner=owner, permission="read"
        )
        if not target.exists():
            raise FileNotFoundError("path does not exist")
        stat = target.stat()
        result: dict[str, Any] = {
            "path": relative,
            "type": "directory" if target.is_dir() else "file" if target.is_file() else "other",
            "size": stat.st_size,
            "created_ns": stat.st_ctime_ns,
            "modified_ns": stat.st_mtime_ns,
            **self._workspace_fields(view),
        }
        if target.is_file() and stat.st_size <= self.max_read_bytes:
            try:
                text = target.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                result["line_count"] = None
            else:
                result["line_count"] = len(text.splitlines())
        return result

    def search(
        self,
        path: str,
        pattern: str,
        search_type: str = "names",
        literal: bool = True,
        ignore_case: bool = True,
        max_results: int = 100,
        context: int = 0,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        if search_type not in {"names", "content"}:
            raise ValueError("search_type must be 'names' or 'content'")
        if max_results < 1 or max_results > MAX_SEARCH_RESULTS:
            raise ValueError(f"max_results must be between 1 and {MAX_SEARCH_RESULTS}")
        if context < 0:
            raise ValueError("context must be zero or greater")
        flags = re.IGNORECASE if ignore_case else 0
        matcher = re.compile(re.escape(pattern) if literal else pattern, flags)
        _, base, _, view = self._resolve_access(
            path, workspace=workspace, owner=owner, permission="read"
        )
        root = Path(view["path"]).resolve()
        scope = base.relative_to(root).as_posix() or "."
        results: list[dict[str, Any]] = []
        for file_path in iter_workspace_files(root, scope):
            relative = file_path.relative_to(root).as_posix()
            if search_type == "names":
                if matcher.search(file_path.name):
                    results.append({"path": relative, "type": "name"})
            else:
                try:
                    if file_path.stat().st_size > self.max_read_bytes:
                        continue
                    raw = file_path.read_bytes()
                except OSError:
                    continue
                try:
                    lines = raw.decode("utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
                for index, line in enumerate(lines):
                    if not matcher.search(line):
                        continue
                    item: dict[str, Any] = {
                        "path": relative,
                        "type": "content",
                        "line": index + 1,
                        "text": line,
                    }
                    if context:
                        start = max(0, index - context)
                        end = min(len(lines), index + context + 1)
                        item["context"] = [
                            {"line": line_no + 1, "text": lines[line_no]}
                            for line_no in range(start, end)
                        ]
                    results.append(item)
                    if len(results) >= max_results:
                        return {
                            "results": results,
                            "items": results,
                            "page": {
                                "offset": 0,
                                "limit": max_results,
                                "returned": len(results),
                                "total": len(results),
                                "next_offset": None,
                            },
                            "max_results": max_results,
                            **self._workspace_fields(view),
                        }
            if len(results) >= max_results:
                break
        return {
            "results": results,
            "items": results,
            "page": {
                "offset": 0,
                "limit": max_results,
                "returned": len(results),
                "total": len(results),
                "next_offset": None,
            },
            "max_results": max_results,
            **self._workspace_fields(view),
        }

    def _audit_mutation(self, action: str, outcome: str, details: dict[str, Any]) -> None:
        self.audit.emit(f"filesystem.{action}", outcome, details)

    def create_directory(
        self,
        path: str,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        _, target, relative, view = self._resolve_access(
            path, workspace=workspace, owner=owner, permission="write"
        )
        details = {"path": relative, **self._workspace_fields(view)}
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._audit_mutation("create_directory", "failed", details)
            raise
        self._audit_mutation("create_directory", "ok", details)
        return details

    def move_file(
        self,
        source: str,
        destination: str,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        _, source_path, source_rel, source_view = self._resolve_access(
            source, workspace=workspace, owner=owner, permission="write"
        )
        _, destination_path, destination_rel, destination_view = self._resolve_access(
            destination, workspace=workspace, owner=owner, permission="write"
        )
        details = {
            "source": source_rel,
            "destination": destination_rel,
            "source_workspace": source_view["id"],
            "destination_workspace": destination_view["id"],
        }
        try:
            if not source_path.exists():
                raise FileNotFoundError("source does not exist")
            if not source_path.is_file():
                raise IsADirectoryError("source is not a file")
            if destination_path.exists():
                raise FileExistsError("destination already exists")
            if not destination_path.parent.is_dir():
                raise FileNotFoundError("destination parent does not exist")
            shutil.move(str(source_path), str(destination_path))
        except Exception:
            self._audit_mutation("move_file", "failed", details)
            raise
        self._audit_mutation("move_file", "ok", details)
        return details

    def delete_path(
        self,
        path: str,
        *,
        recursive: bool = False,
        confirm_directory: bool = False,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        _, target, relative, view = self._resolve_access(
            path, workspace=workspace, owner=owner, permission="write"
        )
        root = Path(view["path"]).resolve()
        details = {
            "path": relative,
            "recursive": bool(recursive),
            "confirm_directory": bool(confirm_directory),
            **self._workspace_fields(view),
        }
        try:
            if target == root:
                raise PermissionError("deleting an allowed root is forbidden")
            if not target.exists():
                raise FileNotFoundError("path does not exist")
            if target.is_dir():
                if not recursive:
                    raise IsADirectoryError("directory deletion requires recursive=true")
                if not confirm_directory:
                    raise PermissionError("directory deletion requires confirm_directory=true")
                shutil.rmtree(target)
                details["type"] = "directory"
            else:
                target.unlink()
                details["type"] = "file"
        except Exception:
            self._audit_mutation("delete_path", "failed", details)
            raise
        self._audit_mutation("delete_path", "ok", details)
        return details

    def write_file(
        self,
        path: str,
        content: str,
        mode: str = "rewrite",
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        if mode not in {"rewrite", "append"}:
            raise ValueError("mode must be 'rewrite' or 'append'")
        payload = content.encode("utf-8")
        if len(payload) > self.max_write_bytes:
            raise ValueError("write exceeds configured byte limit")
        _, target, relative, view = self._resolve_access(
            path, workspace=workspace, owner=owner, permission="write"
        )
        details = {
            "path": relative,
            "mode": mode,
            "bytes": len(payload),
            **self._workspace_fields(view),
        }
        try:
            if target.exists() and not target.is_file():
                raise IsADirectoryError("path is not a file")
            if not target.parent.is_dir():
                raise FileNotFoundError("parent directory does not exist")
            existing_size = target.stat().st_size if mode == "append" and target.exists() else 0
            if existing_size + len(payload) > self.max_write_bytes:
                raise ValueError("resulting file exceeds configured byte limit")
            with target.open("w" if mode == "rewrite" else "a", encoding="utf-8", newline="") as handle:
                handle.write(content)
        except Exception:
            self._audit_mutation("write_file", "failed", details)
            raise
        self._audit_mutation("write_file", "ok", details)
        return details

    def edit_block(
        self,
        path: str,
        old: str,
        new: str,
        expected_replacements: int = 1,
        *,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        if not old:
            raise ValueError("old text must not be empty")
        if expected_replacements < 1:
            raise ValueError("expected_replacements must be greater than zero")
        _, target, relative, view = self._resolve_access(
            path, workspace=workspace, owner=owner, permission="write"
        )
        details = {
            "path": relative,
            "expected_replacements": expected_replacements,
            **self._workspace_fields(view),
        }
        try:
            if not target.is_file():
                raise FileNotFoundError("file does not exist")
            if target.stat().st_size > self.max_read_bytes:
                raise ValueError("read exceeds configured byte limit")
            text = target.read_bytes().decode("utf-8")
            matches = text.count(old)
            if expected_replacements == 1 and matches > 1:
                raise ValueError(f"ambiguous replacement: found {matches} matches")
            if matches != expected_replacements:
                raise ValueError(
                    f"replacement count mismatch: expected {expected_replacements}, found {matches}"
                )
            updated = text.replace(old, new, expected_replacements)
            payload = updated.encode("utf-8")
            if len(payload) > self.max_write_bytes:
                raise ValueError("resulting file exceeds configured byte limit")
            target.write_bytes(payload)
        except Exception:
            self._audit_mutation("edit_block", "failed", details)
            raise
        details["replacements"] = expected_replacements
        details["bytes"] = len(payload)
        self._audit_mutation("edit_block", "ok", details)
        return details
