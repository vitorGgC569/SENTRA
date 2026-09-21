"""Official MCP SDK wiring for the SENTRA v2 core."""
from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from .audit import AuditLogger
from .config import MCPConfig
from .models import CapabilityMetadata, ResponseEnvelope, SERVER_NAME, SERVER_VERSION


def capability_document(config: MCPConfig) -> dict[str, Any]:
    """Return public, non-secret capability metadata and configured limits."""

    metadata = CapabilityMetadata().model_dump(mode="json")
    metadata["security"] = {
        "allowed_root_count": len(config.allowed_roots),
        "blocked_command_count": len(config.blocked_commands),
        "max_read_bytes": config.max_read_bytes,
        "max_write_bytes": config.max_write_bytes,
        "max_output_bytes": config.max_output_bytes,
        "max_processes": config.max_processes,
        "http_loopback_only": not config.allow_non_loopback,
    }
    return metadata


class SentraMCPServer:
    """SENTRA wrapper around the official MCPServer."""

    def __init__(self, config: MCPConfig | None = None) -> None:
        self.config = config or MCPConfig()
        self.audit = AuditLogger(self.config.audit_log)
        self.mcp = MCPServer(
            SERVER_NAME,
            version=SERVER_VERSION,
            description="SENTRA secure local MCP core",
            instructions="Use sentra_health to inspect capabilities and safe runtime limits.",
        )
        self._register_tools()

    def _register_tools(self) -> None:
        audit = self.audit
        config = self.config

        @self.mcp.tool()
        def sentra_health() -> ResponseEnvelope:
            """Return server health, protocol metadata and non-secret capability limits."""

            audit.emit("tool.sentra_health", "ok", {"transport": config.transport})
            return ResponseEnvelope.success(
                {
                    "status": "ok",
                    "capabilities": capability_document(config),
                }
            )

    def run(self, transport: str | None = None) -> None:
        selected = transport or self.config.transport
        if selected not in {"stdio", "streamable-http"}:
            raise ValueError(f"unsupported transport: {selected!r}")
        self.audit.emit("server.start", "ok", {"transport": selected})
        if selected == "stdio":
            self.mcp.run(transport="stdio")
            return
        self.mcp.run(
            transport="streamable-http",
            host=self.config.host,
            port=self.config.port,
            stateless_http=True,
            json_response=True,
        )


def create_server(config: MCPConfig | None = None) -> MCPServer:
    """Create the raw SDK server for embedding or in-process clients."""

    return SentraMCPServer(config).mcp
