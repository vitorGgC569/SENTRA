"""Protocol-independent, bounded filesystem operations for SENTRA MCP."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from workspace.paths import (
    PathAccessError,
    iter_workspace_files,
    resolve_workspace_path,
)

from ..audit import AuditLogger
from ..config import MCPConfig
from ..errors import sanitize_error

MAX_LIST_DEPTH = 8
MAX_SEARCH_RESULTS = 1000


class FilesystemService:
    """Filesystem service constrained to configured SENTRA workspace roots."""

    def __init__(self, config: MCPConfig, audit: AuditLogger) -> None:
        self.allowed_roots = tuple(config.allowed_roots)
        self.max_read_bytes = config.max_read_bytes
        self.max_write_bytes = config.max_write_bytes
        self.audit = audit

    def _select_root(self, raw: str) -> tuple[int, Path, str]:
        if not isinstance(raw, str) or not raw:
            raise PathAccessError("workspace path must be a non-empty string")
        candidate = Path(raw)
        if not candidate.is_absolute():
            return 0, self.allowed_roots[0], raw
        for index, root in enumerate(self.allowed_roots):
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                continue
            return index, root, relative.as_posix() or "."
        raise PathAccessError("absolute path is outside configured allowed roots")

    def _resolve(self, raw: str) -> tuple[int, Path, str]:
        root_index, root, relative = self._select_root(raw)
        target = resolve_workspace_path(root, relative)
        return root_index, target, relative

    def _relative(self, root_index: int, target: Path) -> str:
        relative = target.relative_to(self.allowed_roots[root_index])
        return relative.as_posix() or "."

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
        # MCP text responses are platform-neutral: normalize CRLF/CR to LF while
        # leaving the underlying file bytes untouched.
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        return content, selected_lines

    def list_directory(self, path: str = ".", depth: int = 2) -> dict[str, Any]:
        if depth < 1 or depth > MAX_LIST_DEPTH:
            raise ValueError(f"depth must be between 1 and {MAX_LIST_DEPTH}")
        root_index, base, _ = self._resolve(path)
        if not base.is_dir():
            raise NotADirectoryError("path is not a directory")
        root = self.allowed_roots[root_index]
        entries: list[dict[str, Any]] = []

        def visit(directory: Path, level: int) -> None:
            for child in sorted(
                directory.iterdir(),
                key=lambda item: item.name.casefold(),
            ):
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
            "path": self._relative(root_index, base),
            "depth": depth,
            "entries": entries,
        }

    def read_file(
        self,
        path: str,
        offset: int = 0,
        length: int | None = None,
    ) -> dict[str, Any]:
        root_index, target, _ = self._resolve(path)
        content, line_count = self._read_text(target, offset, length)
        return {
            "path": self._relative(root_index, target),
            "offset": offset,
            "line_count": line_count,
            "content": content,
        }

    def read_multiple_files(
        self,
        paths: list[str],
        offset: int = 0,
        length: int | None = None,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for path in paths:
            try:
                results.append({"ok": True, **self.read_file(path, offset, length)})
            except Exception as exc:
                results.append(
                    {
                        "ok": False,
                        "path": path,
                        "error": sanitize_error(exc),
                    }
                )
        return {"results": results}

    def file_info(self, path: str) -> dict[str, Any]:
        root_index, target, _ = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError("path does not exist")
        stat = target.stat()
        result: dict[str, Any] = {
            "path": self._relative(root_index, target),
            "type": (
                "directory"
                if target.is_dir()
                else "file"
                if target.is_file()
                else "other"
            ),
            "size": stat.st_size,
            "created_ns": stat.st_ctime_ns,
            "modified_ns": stat.st_mtime_ns,
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
    ) -> dict[str, Any]:
        if search_type not in {"names", "content"}:
            raise ValueError("search_type must be 'names' or 'content'")
        if max_results < 1 or max_results > MAX_SEARCH_RESULTS:
            raise ValueError(f"max_results must be between 1 and {MAX_SEARCH_RESULTS}")
        if context < 0:
            raise ValueError("context must be zero or greater")
        flags = re.IGNORECASE if ignore_case else 0
        matcher = re.compile(re.escape(pattern) if literal else pattern, flags)
        root_index, base, _ = self._resolve(path)
        root = self.allowed_roots[root_index]
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
                        return {"results": results, "max_results": max_results}
            if len(results) >= max_results:
                break
        return {"results": results, "max_results": max_results}

    def _audit_mutation(
        self,
        action: str,
        outcome: str,
        details: dict[str, Any],
    ) -> None:
        self.audit.emit(f"filesystem.{action}", outcome, details)

    def create_directory(self, path: str) -> dict[str, Any]:
        root_index, target, _ = self._resolve(path)
        details = {"root_index": root_index, "path": self._relative(root_index, target)}
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._audit_mutation("create_directory", "failed", details)
            raise
        self._audit_mutation("create_directory", "ok", details)
        return details

    def move_file(self, source: str, destination: str) -> dict[str, Any]:
        source_root, source_path, _ = self._resolve(source)
        destination_root, destination_path, _ = self._resolve(destination)
        details = {
            "source_root_index": source_root,
            "source": self._relative(source_root, source_path),
            "destination_root_index": destination_root,
            "destination": self._relative(destination_root, destination_path),
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

    def write_file(
        self,
        path: str,
        content: str,
        mode: str = "rewrite",
    ) -> dict[str, Any]:
        if mode not in {"rewrite", "append"}:
            raise ValueError("mode must be 'rewrite' or 'append'")
        payload = content.encode("utf-8")
        if len(payload) > self.max_write_bytes:
            raise ValueError("write exceeds configured byte limit")
        root_index, target, _ = self._resolve(path)
        details = {
            "root_index": root_index,
            "path": self._relative(root_index, target),
            "mode": mode,
            "bytes": len(payload),
        }
        try:
            if target.exists() and not target.is_file():
                raise IsADirectoryError("path is not a file")
            if not target.parent.is_dir():
                raise FileNotFoundError("parent directory does not exist")
            existing_size = (
                target.stat().st_size
                if mode == "append" and target.exists()
                else 0
            )
            if existing_size + len(payload) > self.max_write_bytes:
                raise ValueError("resulting file exceeds configured byte limit")
            open_mode = "w" if mode == "rewrite" else "a"
            with target.open(open_mode, encoding="utf-8", newline="") as handle:
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
    ) -> dict[str, Any]:
        if not old:
            raise ValueError("old text must not be empty")
        if expected_replacements < 1:
            raise ValueError("expected_replacements must be greater than zero")
        root_index, target, _ = self._resolve(path)
        details = {
            "root_index": root_index,
            "path": self._relative(root_index, target),
            "expected_replacements": expected_replacements,
        }
        try:
            if not target.is_file():
                raise FileNotFoundError("file does not exist")
            if target.stat().st_size > self.max_read_bytes:
                raise ValueError("read exceeds configured byte limit")
            raw = target.read_bytes()
            text = raw.decode("utf-8")
            matches = text.count(old)
            if expected_replacements == 1 and matches > 1:
                raise ValueError(f"ambiguous replacement: found {matches} matches")
            if matches != expected_replacements:
                raise ValueError(
                    "replacement count mismatch: "
                    f"expected {expected_replacements}, found {matches}"
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
