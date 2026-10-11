"""Registration and invocation-time policy for SENTRA MCP.

Conversation trust/blocks are an additional denial boundary, never a
replacement for the authorization service or operation admission gate.
"""
from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import inspect
from typing import Any


def _invocation_origin(function, args, kwargs):
    """Read SDK Context and HTTP request ID without taking caller-supplied chat ID."""
    bound=inspect.signature(function).bind_partial(*args,**kwargs)
    ctx=bound.arguments.get("ctx")
    if ctx is None:
        return "local-operator",None
    from .identity import _principal_binding
    principal=_principal_binding(ctx)
    try:
        request=ctx.request_context.request
        headers=getattr(request,"headers",None)
        value=headers.get("x-request-id") if headers is not None else None
    except (AttributeError,RuntimeError):
        value=None
    if not isinstance(value,str) or not value:
        return principal,None
    # Unrecognized request ID is never an attribution proof. It is not
    # evidence for rejecting a previously valid local client in nonstrict mode.
    from .services.chat_access import _ID
    if not _ID.fullmatch(value):
        return principal,None
    return principal,value


class ToolPolicyProxy:
    """Wrap registrations under the configured allowlist and central chat denials.

    An empty allowlist means all tools *can be registered*. Invocation still
    requires the existing per-tool and durable authorization gates.
    """

    def __init__(self, server: Any, allowlist: tuple[str, ...], *,
                 chat_access=None, request_observer=None):
        self._server = server
        self._allowed = frozenset(allowlist)
        self._chat_access = chat_access
        self._request_observer = request_observer

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        original=self._server.tool(*args,**kwargs)

        def decorate(func):
            name=str(kwargs.get("name") or func.__name__)
            if self._allowed and name not in self._allowed:
                return func
            if self._chat_access is None:
                return original(func)

            def enforce(call_args,call_kwargs):
                principal,request_id=_invocation_origin(func,call_args,call_kwargs)
                self._chat_access.require_allowed(principal,request_id)
                if self._request_observer is not None:
                    context=inspect.signature(func).bind_partial(*call_args,**call_kwargs).arguments.get("ctx")
                    self._request_observer(context,name)

            if inspect.iscoroutinefunction(func):
                @wraps(func)
                async def checked(*call_args,**call_kwargs):
                    enforce(call_args,call_kwargs)
                    return await func(*call_args,**call_kwargs)
            else:
                @wraps(func)
                def checked(*call_args,**call_kwargs):
                    enforce(call_args,call_kwargs)
                    return func(*call_args,**call_kwargs)
            return original(checked)

        return decorate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._server,name)


def filter_tool_names(names: list[str], allowlist: tuple[str, ...]) -> list[str]:
    if not allowlist:
        return list(names)
    allowed = frozenset(allowlist)
    return [name for name in names if name in allowed]
