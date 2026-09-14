"""Registered handlers; model payloads are arguments, never shell code."""
from __future__ import annotations

import ast
import asyncio
import hashlib
from pathlib import Path
from typing import Any, Dict

from workspace.command_runner import CommandRunner
from workspace.paths import iter_workspace_files
from .parser import Directive
from .session import RepositorySession

MAX_FILE_BYTES = 1_000_000


class CommandContext:
    def __init__(self, session: RepositorySession, agent_id: str = "executor",
                 task_id: str = "T-000", gateway=None):
        self.session, self.agent_id, self.task_id, self.gateway = session, agent_id, task_id, gateway


def read_text(path: Path) -> str:
    if not path.is_file():
        raise ValueError("file not found")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file exceeds 1 MB read budget")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
        raise ValueError("oversized or binary file")
    return raw.decode("utf-8-sig")


def line_range(args, first=1):
    values = args[first:]
    if len(values) > 2 or any(not v.isascii() or not v.isdigit() for v in values):
        raise ValueError("line range requires positive integers")
    start = int(values[0]) if values else 1
    end = int(values[1]) if len(values) > 1 else start + 199
    if start < 1 or end < start or end - start >= 5000:
        raise ValueError("range must be positive, ordered and at most 5000 lines")
    return start, end


class ReadCommand:
    async def execute(self, directive: Directive, ctx: CommandContext) -> str:
        if not directive.args:
            return "ERROR: usage [[R|path|start|end]]"
        start, end = line_range(directive.args)
        target = ctx.session.resolve_path(directive.args[0])
        content = await asyncio.to_thread(read_text, target)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        relative = target.relative_to(ctx.session.repository_root).as_posix()
        alias = ctx.session.register_alias("F", relative)
        cache_key = f"{ctx.agent_id}:{ctx.task_id}:{relative}#{start}-{end}"
        if ctx.session.read_cache.get(cache_key) == digest:
            return f"CACHE_HIT {alias}={relative} hash={digest}"
        lines = content.splitlines()
        chunk = lines[start - 1:end]
        body = "\n".join(f"{idx:5d}: {line}" for idx, line in enumerate(chunk, start=start))
        ctx.session.read_cache[cache_key] = digest
        return (f"{alias} = {relative} LINES {start}-{min(end, len(lines))}/{len(lines)} "
                f"MORE={str(end < len(lines)).lower()} HASH={digest}\n{body}")


class SearchCommand:
    async def execute(self, directive: Directive, ctx: CommandContext) -> str:
        if not 1 <= len(directive.args) <= 2 or not directive.args[0]:
            return "ERROR: usage [[S|literal text|path]]"
        pattern = directive.args[0]
        scope = directive.args[1] if len(directive.args) == 2 else "."
        ctx.session.resolve_path(scope)

        def search():
            hits = []
            # Literal matching has a bounded cost, including malicious patterns.
            for p in iter_workspace_files(ctx.session.repository_root, scope):
                try:
                    text = read_text(p)
                except (ValueError, UnicodeError, OSError):
                    continue
                for idx, line in enumerate(text.splitlines(), 1):
                    if pattern in line:
                        hits.append((p.relative_to(ctx.session.repository_root).as_posix(), idx,
                                     line.strip()[:240]))
                        if len(hits) >= 101:
                            return hits
            return hits

        hits = await asyncio.to_thread(search)
        rows = []
        for path, idx, line in hits[:100]:
            alias = ctx.session.register_alias("F", path)
            rows.append(f"{alias} {path}:{idx}: {line}")
        return (f"MATCHES={len(rows)} MODE=literal MORE={str(len(hits) > 100).lower()}\n"
                + "\n".join(rows)) if hits else "NO_MATCHES MODE=literal"


class TreeCommand:
    async def execute(self, directive: Directive, ctx: CommandContext) -> str:
        if len(directive.args) > 2:
            return "ERROR: usage [[T|path|depth]]"
        scope = directive.args[0] if directive.args else "."
        depth = int(directive.args[1]) if len(directive.args) > 1 else 3
        if not 0 <= depth <= 10:
            return "ERROR: tree depth must be 0..10"
        base = ctx.session.resolve_path(scope)

        def tree():
            rows = [base.name + "/"]
            seen = set()
            for path in iter_workspace_files(ctx.session.repository_root, scope):
                relative = path.relative_to(base) if base.is_dir() else Path(path.name)
                for index, part in enumerate(relative.parts):
                    if index > depth:
                        break
                    key = relative.parts[:index + 1]
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append("  " * (index + 1) + part +
                                ("/" if index < len(relative.parts) - 1 else ""))
                    if len(rows) >= 300:
                        return "\n".join(rows) + "\nTRUNCATED: narrow the scope"
            return "\n".join(rows)
        return await asyncio.to_thread(tree)


class SymbolCommand:
    async def execute(self, directive: Directive, ctx: CommandContext) -> str:
        if len(directive.args) != 1 or not directive.args[0].isidentifier():
            return "ERROR: usage [[SYM|symbol]]"
        name = directive.args[0]

        def symbols():
            hits = []
            for path in iter_workspace_files(ctx.session.repository_root):
                if path.suffix != ".py":
                    continue
                try:
                    tree = ast.parse(read_text(path))
                except (SyntaxError, ValueError, UnicodeError, OSError):
                    continue
                found = set()
                for node in ast.walk(tree):
                    definition = isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    matches = ((definition and node.name == name) or
                               (isinstance(node, ast.Name) and node.id == name) or
                               (isinstance(node, ast.Attribute) and node.attr == name))
                    if matches:
                        found.add((node.lineno, "definition" if definition else "reference"))
                for line, kind in sorted(found):
                    hits.append((path.relative_to(ctx.session.repository_root).as_posix(), line, kind))
                    if len(hits) >= 100:
                        return hits
            return hits

        hits = await asyncio.to_thread(symbols)
        return "\n".join(f"{ctx.session.register_alias('F', path)} {path}:{line}: {kind} {name}"
                         for path, line, kind in hits) or "SYMBOL_NOT_FOUND"


class ExecutionCommand:
    async def execute(self, directive: Directive, ctx: CommandContext) -> str:
        from workspace.docker_runner import create_runner
        runner = create_runner(ctx.session.repository_root,
                               profiles=getattr(ctx.gateway, "profiles", None),
                               execution=getattr(ctx.gateway, "execution", None))
        res = await runner.run_command(directive.raw, timeout=600)
        status = "PASS" if res["passed"] else "FAIL"
        target = directive.args[0] if directive.args else ("all" if directive.operation == "TEST" else "")
        return (f"{directive.operation} {target} {status} exit={res['exit_code']}\n"
                f"{res['stdout']}{res['stderr']}")


# Public names retained for callers importing the original handler classes.
TestCommand = LintCommand = TypecheckCommand = BuildCommand = ExecutionCommand


class CommandRegistry:
    def __init__(self):
        self.handlers: Dict[str, Any] = {
            "R": ReadCommand(), "S": SearchCommand(), "T": TreeCommand(), "SYM": SymbolCommand(),
            **{op: ExecutionCommand() for op in ("TEST", "LINT", "TYPECHECK", "BUILD")},
        }

    def register(self, op: str, handler: Any) -> None:
        self.handlers[op] = handler

    def get(self, op: str) -> Any:
        return self.handlers.get(op)
