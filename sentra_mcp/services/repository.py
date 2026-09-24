"""Safe adapters over SENTRA's existing repository CommandGateway."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from repository.gateway import CommandGateway

from ..audit import AuditLogger
from ..config import MCPConfig
from .workspaces import WorkspaceRegistry


def _safe_arg(value: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("repository argument must be a string")
    if not value and not allow_empty:
        raise ValueError("repository argument must not be empty")
    if any(token in value for token in ("|", "\r", "\n", "\x00", "[[", "]]")):
        raise ValueError("repository argument contains protocol metacharacters")
    return value


def _registered_operation_passed(operation: str, result: str) -> bool:
    """Read the canonical command status from direct or ResultStore-paged output."""
    lines = result.splitlines()
    if not lines:
        return False
    status_line = lines[0]
    if status_line.startswith("ALIAS="):
        if (
            len(lines) < 4
            or not lines[1].startswith("RESULT_ID=")
            or lines[2] != f"SUMMARY: {operation} paged"
        ):
            return False
        status_line = lines[3]
    parts = status_line.split()
    return bool(
        parts
        and parts[0] == operation
        and len(parts) >= 3
        and parts[-2:] == ["PASS", "exit=0"]
    )


class RepositoryService:
    """Read-only repository access plus registered deterministic executions."""

    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger,
        workspaces: WorkspaceRegistry | None = None,
    ) -> None:
        self.config = config
        self.audit = audit
        self.workspaces = workspaces
        self._gateway_lock = threading.RLock()
        self._gateways: dict[asyncio.AbstractEventLoop, dict[str, CommandGateway]] = {}

    def update_config(self, config: MCPConfig) -> None:
        self.config = config
        if self.workspaces is not None:
            self.workspaces.update_config(config)
        allowed = {str(Path(root).resolve()) for root in config.allowed_roots}
        if self.workspaces is None:
            with self._gateway_lock:
                for loop in list(self._gateways):
                    if loop.is_closed():
                        self._gateways.pop(loop, None)
                        continue
                    self._gateways[loop] = {
                        key: gateway
                        for key, gateway in self._gateways[loop].items()
                        if key in allowed
                    }

    def _legacy_workspaces(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for index, raw in enumerate(self.config.allowed_roots):
            root = Path(raw).resolve()
            items.append({
                "id": f"root:{index}",
                "workspace_id": f"config:{index}",
                "alias": "sentra" if index == 0 else root.name,
                "path": str(root),
                "permissions": ["execute", "read", "write"],
                "scope": "permanent",
                "source": "configured",
                "exists": root.is_dir(),
                "git_repo": (root / ".git").exists() if root.is_dir() else False,
                "default": index == 0,
            })
        return items

    def list_workspaces(self, owner: str | None = None) -> dict[str, Any]:
        if self.workspaces is not None:
            return self.workspaces.list_workspaces(owner)
        items = self._legacy_workspaces()
        return {
            "items": items,
            "workspaces": items,
            "page": {
                "offset": 0,
                "limit": len(items),
                "returned": len(items),
                "total": len(items),
                "next_offset": None,
            },
        }

    def _resolve_workspace(
        self,
        workspace: str | None,
        owner: str | None,
        permission: str,
    ) -> dict[str, Any]:
        if self.workspaces is not None:
            return self.workspaces.resolve(workspace, owner, permission)

        roots = self._legacy_workspaces()
        if workspace is None or not str(workspace).strip():
            item = roots[0]
        else:
            selector = str(workspace).strip()
            matches = [
                item for item in roots
                if selector in {
                    item["id"],
                    item["workspace_id"],
                    item["alias"],
                    item["path"],
                }
            ]
            if not matches:
                raise PermissionError("workspace is not allowlisted")
            if len(matches) > 1:
                raise ValueError("workspace selector is ambiguous")
            item = matches[0]
        if permission not in item["permissions"]:
            raise PermissionError(f"workspace does not grant {permission} permission")
        if not Path(item["path"]).is_dir():
            raise FileNotFoundError("allowlisted workspace directory does not exist")
        return item

    def _gateway(
        self,
        workspace: str | None,
        owner: str | None,
        permission: str,
    ) -> tuple[dict[str, Any], Path, CommandGateway]:
        view = self._resolve_workspace(workspace, owner, permission)
        root = Path(view["path"]).resolve()
        key = str(root)
        loop = asyncio.get_running_loop()
        with self._gateway_lock:
            for existing in list(self._gateways):
                if existing.is_closed():
                    self._gateways.pop(existing, None)
            loop_gateways = self._gateways.setdefault(loop, {})
            gateway = loop_gateways.get(key)
            if gateway is None:
                gateway = CommandGateway(root)
                loop_gateways[key] = gateway
        return view, root, gateway

    async def _execute(
        self,
        directive: str,
        *,
        workspace: str | None = None,
        owner: str | None = None,
        allow_run: bool = False,
    ) -> tuple[str, dict[str, Any], Path]:
        permission = "execute" if allow_run else "read"
        view, root, gateway = self._gateway(workspace, owner, permission)
        session = gateway.open_session(read=True, write=False, run=allow_run)
        try:
            result = await gateway.execute(
                session,
                directive,
                agent_id="mcp.repository",
                task_id="MCP",
                role="validator" if allow_run else "read_only",
            )
        finally:
            gateway.close_session(session)
        if result.startswith("ERROR DENIED:"):
            raise PermissionError(result.removeprefix("ERROR DENIED:").strip())
        if result.startswith("ERROR"):
            raise RuntimeError(result)
        return result, view, root

    @staticmethod
    def _workspace_result(view: dict[str, Any], root: Path) -> dict[str, Any]:
        return {
            "workspace": view["id"],
            "workspace_id": view["workspace_id"],
            "workspace_alias": view["alias"],
            "workspace_path": str(root),
        }

    async def read(
        self,
        path: str,
        start: int = 1,
        end: int | None = None,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        path = _safe_arg(path)
        if start < 1:
            raise ValueError("start must be positive")
        if end is None:
            end = start + 199
        if end < start or end - start >= 5000:
            raise ValueError("line range must be ordered and at most 5000 lines")
        result, view, root = await self._execute(
            f"[[R|{path}|{start}|{end}]]",
            workspace=workspace,
            owner=owner,
        )
        return {
            "operation": "read",
            "path": path,
            "start": start,
            "end": end,
            "result": result,
            **self._workspace_result(view, root),
        }

    async def search(
        self,
        text: str,
        path: str = ".",
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        text = _safe_arg(text)
        path = _safe_arg(path)
        result, view, root = await self._execute(
            f"[[S|{text}|{path}]]",
            workspace=workspace,
            owner=owner,
        )
        return {
            "operation": "search",
            "text": text,
            "path": path,
            "result": result,
            **self._workspace_result(view, root),
        }

    async def tree(
        self,
        path: str = ".",
        depth: int = 3,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        path = _safe_arg(path)
        if not 0 <= depth <= 10:
            raise ValueError("depth must be between 0 and 10")
        result, view, root = await self._execute(
            f"[[T|{path}|{depth}]]",
            workspace=workspace,
            owner=owner,
        )
        return {
            "operation": "tree",
            "path": path,
            "depth": depth,
            "result": result,
            **self._workspace_result(view, root),
        }

    async def symbol(
        self,
        name: str,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError("symbol must be a Python identifier")
        result, view, root = await self._execute(
            f"[[SYM|{name}]]",
            workspace=workspace,
            owner=owner,
        )
        return {
            "operation": "symbol",
            "symbol": name,
            "result": result,
            **self._workspace_result(view, root),
        }

    async def status(
        self,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        result, view, root = await self._execute(
            "[[STATUS]]",
            workspace=workspace,
            owner=owner,
        )
        return {
            "operation": "status",
            "result": result,
            **self._workspace_result(view, root),
        }

    async def diff(
        self,
        path: str | None = None,
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        if path is None:
            directive = "[[DIFF]]"
        else:
            path = _safe_arg(path)
            directive = f"[[DIFF|{path}]]"
        result, view, root = await self._execute(
            directive,
            workspace=workspace,
            owner=owner,
        )
        return {
            "operation": "diff",
            "path": path,
            "result": result,
            **self._workspace_result(view, root),
        }

    async def run_registered(
        self,
        operation: str,
        target: str = "",
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        op = str(operation).strip().upper()
        if op not in {"TEST", "LINT", "TYPECHECK", "BUILD", "BENCH"}:
            raise ValueError("operation must be TEST, LINT, TYPECHECK, BUILD or BENCH")
        if target:
            target = _safe_arg(target)
        if op != "TEST" and target:
            raise ValueError(f"{op} does not accept a target")
        directive = f"[[{op}|{target}]]" if target else f"[[{op}]]"
        result, view, root = await self._execute(
            directive,
            workspace=workspace,
            owner=owner,
            allow_run=True,
        )
        passed = _registered_operation_passed(op, result)
        self.audit.emit(
            f"repository.{op.lower()}",
            "passed" if passed else "failed",
            {"target": target or None, "workspace": view["id"]},
        )
        return {
            "operation": op.lower(),
            "target": target or None,
            "passed": passed,
            "result": result,
            **self._workspace_result(view, root),
        }

    async def test(
        self,
        target: str = "all",
        workspace: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        return await self.run_registered("TEST", target, workspace, owner)
