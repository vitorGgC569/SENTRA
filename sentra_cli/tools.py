"""Native engineering tools for the SENTRA CLI."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from workspace.paths import resolve_workspace_path
from workspace.patch_manager import PatchManager


def read_file(workspace: Path, rel_path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Read a text file from the workspace with optional 1-based line slicing."""
    try:
        target = resolve_workspace_path(workspace, rel_path)
    except Exception as exc:
        return f"Error: Path access denied: {exc}"

    if not target.is_file():
        return f"Error: File not found: {rel_path}"

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Error reading file: {exc}"

    lines = text.splitlines()
    total_lines = len(lines)

    s = max(1, start_line or 1)
    e = min(total_lines, end_line or total_lines)

    if s > total_lines:
        return f"(File has {total_lines} lines; start_line {s} is out of range)"

    selected = lines[s - 1:e]
    formatted = [f"{s + idx}: {line}" for idx, line in enumerate(selected)]
    header = f"[{rel_path} | lines {s}-{e} of {total_lines}]\n"
    return header + "\n".join(formatted)


def write_file(workspace: Path, rel_path: str, content: str) -> str:
    """Write content to a file within the workspace safely."""
    try:
        target = resolve_workspace_path(workspace, rel_path)
    except Exception as exc:
        return f"Error: Path access denied: {exc}"

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content.encode('utf-8'))} bytes to {rel_path}"
    except Exception as exc:
        return f"Error writing file: {exc}"


def apply_patch(workspace: Path, patch_text: str) -> str:
    """Apply a unified diff patch to the workspace with atomic validation."""
    try:
        files = PatchManager.parse_files(patch_text)
        if not files:
            return "Error: No valid file patches found in diff"
        result = PatchManager.apply_patch(workspace, patch_text)
        if not isinstance(result, dict) or result.get("success") is not True:
            detail = result.get("error") if isinstance(result, dict) else "invalid patch result"
            return f"Patch application failed: {detail or 'patch was not applied'}"
        return f"Patch applied successfully: modified {len(result.get('applied_files', files))} file(s)"
    except Exception as exc:
        return f"Patch application failed: {exc}"


def list_files(workspace: Path, rel_path: str = ".", max_items: int = 50) -> str:
    """List directory contents within the workspace."""
    try:
        target = resolve_workspace_path(workspace, rel_path)
    except Exception as exc:
        return f"Error: Path access denied: {exc}"

    if not target.is_dir():
        return f"Error: Not a directory: {rel_path}"

    items = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith((".", "__pycache__")):
                continue
            kind = "[DIR]" if entry.is_dir() else "[FILE]"
            size = f"({entry.stat().st_size} B)" if entry.is_file() else ""
            items.append(f"{kind} {entry.name} {size}".strip())
            if len(items) >= max_items:
                items.append(f"... (truncated after {max_items} items)")
                break
        return "\n".join(items) if items else "(empty directory)"
    except Exception as exc:
        return f"Error listing directory: {exc}"


def git_diff(workspace: Path) -> str:
    """Get the current uncommitted git diff in the workspace."""
    try:
        res = subprocess.run(
            ["git", "diff"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = res.stdout.strip()
        return output if output else "(clean working tree - no changes)"
    except Exception as exc:
        return f"Git diff error: {exc}"


def git_status(workspace: Path) -> str:
    """Get the git status summary in the workspace."""
    try:
        res = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = res.stdout.strip()
        return output if output else "(clean working tree)"
    except Exception as exc:
        return f"Git status error: {exc}"


def run_tests(workspace: Path, target: str = "all", timeout: float = 60.0) -> str:
    """Run pytest in the workspace."""
    try:
        cmd = [sys.executable, "-B", "-m", "pytest", "-q"]
        if target != "all":
            cmd.append(target)
        res = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        combined = (res.stdout + "\n" + res.stderr).strip()
        status = "PASSED" if res.returncode == 0 else f"FAILED (exit {res.returncode})"
        return f"Test status: {status}\n\n{combined}"
    except subprocess.TimeoutExpired:
        return f"Tests timed out after {timeout} seconds"
    except Exception as exc:
        return f"Test execution error: {exc}"


def search_text(
    workspace: Path,
    pattern: str,
    rel_path: str = ".",
    file_pattern: str = "*",
    max_results: int = 100,
) -> str:
    """Literal, bounded workspace text search with line-number evidence."""
    if not pattern:
        return "Error: empty search pattern"
    try:
        root = resolve_workspace_path(workspace, rel_path)
    except Exception as exc:
        return f"Error: Path access denied: {exc}"
    if not root.is_dir():
        return f"Error: Not a directory: {rel_path}"

    skipped = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tmp"}
    hits: list[str] = []
    for candidate in root.rglob("*"):
        if len(hits) >= max_results:
            break
        try:
            relative_parts = candidate.relative_to(root).parts
            if any(part in skipped for part in relative_parts):
                continue
            if not candidate.is_file() or candidate.stat().st_size > 2_000_000:
                continue
            if file_pattern != "*" and not candidate.match(file_pattern):
                continue
            data = candidate.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            continue
        for line_no, line in enumerate(data.splitlines(), start=1):
            if pattern.casefold() not in line.casefold():
                continue
            rel = candidate.relative_to(workspace)
            preview = line.strip()
            if len(preview) > 300:
                preview = preview[:297] + "..."
            hits.append(f"{rel}:{line_no}: {preview}")
            if len(hits) >= max_results:
                break

    if not hits:
        return "(no matches)"
    suffix = (
        f"\n... (truncated after {max_results} matches)"
        if len(hits) >= max_results else ""
    )
    return "\n".join(hits) + suffix


def run_registered(
    workspace: Path,
    operation: str,
    timeout: float = 180.0,
) -> str:
    """Run a policy-registered quality command through SENTRA CommandRunner."""
    from workspace.command_runner import CommandRunner

    directive = f"[[{operation.upper()}]]"
    try:
        result = asyncio.run(
            CommandRunner(workspace).run_command(directive, timeout=timeout)
        )
    except Exception as exc:
        return f"Execution error: {type(exc).__name__}: {exc}"

    refused = bool(result.get("refused"))
    passed = bool(result.get("passed"))
    status = "REFUSED" if refused else ("PASSED" if passed else "FAILED")
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    body = "\n".join(part for part in (stdout, stderr) if part)
    return f"{operation.upper()} status: {status}\n\n{body}".rstrip()
