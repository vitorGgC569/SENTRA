"""Public lazy exports for the SENTRA MCP package.

Keeping package import lightweight prevents utilities such as the tray/updater from
pulling the full MCP/browser stack merely to read version metadata.
"""
from __future__ import annotations

__all__ = [
    "ALLOWED_TRANSPORTS",
    "MCPConfig",
    "PROJECT_ROOT",
    "PROTOCOL_VERSION",
    "ResponseEnvelope",
    "SERVER_NAME",
    "SERVER_VERSION",
    "SentraMCPServer",
    "create_server",
]


def __getattr__(name: str):
    if name in {"ALLOWED_TRANSPORTS", "MCPConfig", "PROJECT_ROOT"}:
        from . import config as _config
        return getattr(_config, name)
    if name in {"PROTOCOL_VERSION", "SERVER_NAME", "SERVER_VERSION"}:
        from . import version as _version
        return getattr(_version, name)
    if name == "ResponseEnvelope":
        from . import models as _models
        return _models.ResponseEnvelope
    if name in {"SentraMCPServer", "create_server"}:
        from . import server as _server
        return getattr(_server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
