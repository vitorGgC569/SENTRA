"""SENTRA Commander remote agent/relay package with lazy public exports."""
from __future__ import annotations

__all__ = ["RemoteStore", "RemoteGatewayService"]


def __getattr__(name: str):
    if name == "RemoteStore":
        from .store import RemoteStore
        return RemoteStore
    if name == "RemoteGatewayService":
        from .gateway import RemoteGatewayService
        return RemoteGatewayService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
