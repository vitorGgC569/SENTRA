"""Registration-time per-tool policy for SENTRA MCP."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ToolPolicyProxy:
    """Wrap an MCP server and skip tool registration outside an allowlist.

    An empty allowlist means unrestricted registration. Health stays registered
    by SentraMCPServer itself so operators can always inspect effective policy.
    """

    def __init__(self, server: Any, allowlist: tuple[str, ...]) -> None:
        self._server = server
        self._allowed = frozenset(allowlist)

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        original = self._server.tool(*args, **kwargs)

        def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
            name = str(kwargs.get("name") or func.__name__)
            if self._allowed and name not in self._allowed:
                return func
            return original(func)

        return decorate
    def __getattr__(self, name: str) -> Any:
        return getattr(self._server, name)


def filter_tool_names(names: list[str], allowlist: tuple[str, ...]) -> list[str]:
    """Pure helper used by the desktop and tests."""
    if not allowlist:
        return list(names)
    allowed = frozenset(allowlist)
    return [name for name in names if name in allowed]
