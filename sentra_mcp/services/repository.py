"""Safe adapters over SENTRA's existing repository CommandGateway."""
from __future__ import annotations

from typing import Any

from repository.gateway import CommandGateway

from ..audit import AuditLogger
from ..config import MCPConfig


def _safe_arg(value: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("repository argument must be a string")
    if not value and not allow_empty:
        raise ValueError("repository argument must not be empty")
    if any(token in value for token in ("|", "\r", "\n", "\x00", "[[", "]]")):
        raise ValueError("repository argument contains protocol metacharacters")
    return value


class RepositoryService:
    """Read-only repository access plus registered TEST execution.

    All operations are delegated to CommandGateway. No shell or raw-command
    endpoint is exposed through this adapter.
    """

    def __init__(self, config: MCPConfig, audit: AuditLogger) -> None:
        self.workspace = config.allowed_roots[0]
        self.audit = audit
        self.gateway = CommandGateway(self.workspace)

    async def _execute(self, directive: str, *, allow_run: bool = False) -> str:
        session = self.gateway.open_session(read=True, write=False, run=allow_run)
        try:
            result = await self.gateway.execute(
                session,
                directive,
                agent_id="mcp.repository",
                task_id="MCP",
                role="validator" if allow_run else "read_only",
            )
        finally:
            self.gateway.close_session(session)
        if result.startswith("ERROR DENIED:"):
            raise PermissionError(result.removeprefix("ERROR DENIED:").strip())
        if result.startswith("ERROR"):
            raise RuntimeError(result)
        return result

    async def read(self, path: str, start: int = 1, end: int | None = None) -> dict[str, Any]:
        path = _safe_arg(path)
        if start < 1:
            raise ValueError("start must be positive")
        if end is None:
            end = start + 199
        if end < start or end - start >= 5000:
            raise ValueError("line range must be ordered and at most 5000 lines")
        result = await self._execute(f"[[R|{path}|{start}|{end}]]")
        return {"operation": "read", "path": path, "start": start, "end": end, "result": result}

    async def search(self, text: str, path: str = ".") -> dict[str, Any]:
        text = _safe_arg(text)
        path = _safe_arg(path)
        result = await self._execute(f"[[S|{text}|{path}]]")
        return {"operation": "search", "text": text, "path": path, "result": result}

    async def tree(self, path: str = ".", depth: int = 3) -> dict[str, Any]:
        path = _safe_arg(path)
        if not 0 <= depth <= 10:
            raise ValueError("depth must be between 0 and 10")
        result = await self._execute(f"[[T|{path}|{depth}]]")
        return {"operation": "tree", "path": path, "depth": depth, "result": result}

    async def symbol(self, name: str) -> dict[str, Any]:
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError("symbol must be a Python identifier")
        result = await self._execute(f"[[SYM|{name}]]")
        return {"operation": "symbol", "symbol": name, "result": result}

    async def status(self) -> dict[str, Any]:
        return {"operation": "status", "result": await self._execute("[[STATUS]]")}

    async def diff(self, path: str | None = None) -> dict[str, Any]:
        if path is None:
            directive = "[[DIFF]]"
        else:
            path = _safe_arg(path)
            directive = f"[[DIFF|{path}]]"
        return {"operation": "diff", "path": path, "result": await self._execute(directive)}

    async def test(self, target: str = "all") -> dict[str, Any]:
        target = _safe_arg(target)
        result = await self._execute(f"[[TEST|{target}]]", allow_run=True)
        first = result.splitlines()[0] if result else ""
        passed = " PASS exit=0" in first
        self.audit.emit(
            "repository.test",
            "passed" if passed else "failed",
            {"target": target},
        )
        return {"operation": "test", "target": target, "passed": passed, "result": result}
