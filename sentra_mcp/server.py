"""Official MCP SDK wiring for the SENTRA v2 core."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer

from .audit import AuditLogger
from .config import MCPConfig
from .models import ResponseEnvelope, SERVER_NAME, SERVER_VERSION
from .prompts import register_prompts
from .resources import capability_document, register_resources
from .services.filesystem import FilesystemService
from .services.oma import OmaService
from .services.process import ProcessService
from .services.repository import RepositoryService
from .tools.filesystem import register_filesystem_tools
from .tools.process import register_process_tools
from .tools.sentra import register_sentra_tools


class SentraMCPServer:
    """SENTRA wrapper around the official MCPServer."""

    def __init__(self, config: MCPConfig | None = None) -> None:
        self.config = config or MCPConfig()
        self.audit = AuditLogger(self.config.audit_log)
        self.filesystem = FilesystemService(self.config, self.audit)
        self.processes = ProcessService(self.config, self.audit)
        self.repository = RepositoryService(self.config, self.audit)
        self.oma = OmaService(self.config, self.audit)

        @asynccontextmanager
        async def lifespan(_server: MCPServer):
            try:
                yield {}
            finally:
                self.processes.shutdown()

        self.mcp = MCPServer(
            SERVER_NAME,
            version=SERVER_VERSION,
            description="SENTRA secure local MCP core",
            instructions="Use sentra_health to inspect capabilities and safe runtime limits.",
            lifespan=lifespan,
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

        register_filesystem_tools(self.mcp, self.filesystem)
        register_process_tools(self.mcp, self.processes)
        register_sentra_tools(self.mcp, self.repository, self.oma)
        register_resources(self.mcp, self.config, self.repository, self.oma)
        register_prompts(self.mcp, self.oma)

    def run(self, transport: str | None = None) -> None:
        selected = transport or self.config.transport
        if selected not in {"stdio", "streamable-http"}:
            raise ValueError(f"unsupported transport: {selected!r}")
        self.audit.emit("server.start", "ok", {"transport": selected})
        try:
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
        finally:
            self.processes.shutdown()


def create_server(config: MCPConfig | None = None) -> MCPServer:
    """Create the raw SDK server for embedding or in-process clients."""

    return SentraMCPServer(config).mcp
