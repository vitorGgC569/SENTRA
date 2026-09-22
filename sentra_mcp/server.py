"""Official MCP SDK wiring for SENTRA Commander v1."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from sentra_remote.auth import IntrospectionSettings, IntrospectionTokenVerifier
from sentra_remote.gateway import RemoteGatewayService
from sentra_remote.store import RemoteStore

from .audit import AuditLogger
from .config import MCPConfig
from .models import ResponseEnvelope, SERVER_NAME, SERVER_VERSION
from .prompts import register_prompts
from .resources import capability_document, register_resources
from .services.browser import BrowserControlService
from .services.documents import DocumentService
from .services.filesystem import FilesystemService
from .services.jobs import JobService
from .services.oma import OmaService
from .services.process import ProcessService
from .services.repository import RepositoryService
from .services.research import ResearchService
from .services.runtime_config import RuntimeConfigService
from .services.search_sessions import SearchSessionService
from .services.telemetry import TelemetryService
from .services.workspace_ops import WorkspaceOpsService
from .services.workspaces import WorkspaceRegistry
from .tools.commander import register_commander_tools
from .tools.filesystem import register_filesystem_tools
from .tools.process import register_process_tools
from .tools.remote import register_remote_tools
from .tools.sentra import register_sentra_tools


class SentraMCPServer:
    """SENTRA local/remote MCP server with one policy/lifecycle boundary."""

    def __init__(self, config: MCPConfig | None = None) -> None:
        self.config = config or MCPConfig()
        self.audit = AuditLogger(self.config.audit_log)
        self.workspaces = WorkspaceRegistry(self.config, self.audit)
        self.filesystem = FilesystemService(self.config, self.audit, self.workspaces)
        self.processes = ProcessService(self.config, self.audit, self.workspaces)
        self.repository = RepositoryService(self.config, self.audit, self.workspaces)
        self.oma = OmaService(self.config, self.audit)
        self.search = SearchSessionService(self.config, self.audit, self.workspaces)
        self.telemetry = TelemetryService(self.config)
        self.documents = DocumentService(self.filesystem, self.audit)
        self.browser = BrowserControlService(self.config, self.audit)
        self.workspace_ops = WorkspaceOpsService(self.filesystem, self.audit)
        self.jobs = JobService(self.config, self.audit, self.repository)
        self.research = ResearchService(self.config, self.audit, self.browser)
        self.remote_store = RemoteStore(self.config.remote_store_path)
        self.remote = RemoteGatewayService(self.remote_store)
        self.runtime_config = RuntimeConfigService(
            self._effective_config,
            self._apply_safe_config,
            state_path=self.config.allowed_roots[0] / ".sentra" / "mcp-config.json",
        )

        verifier = None
        auth = None
        if self.config.oauth_enabled:
            verifier = IntrospectionTokenVerifier(
                IntrospectionSettings(
                    url=self.config.oauth_introspection_url,
                    client_id=self.config.oauth_client_id,
                    client_secret=self.config.oauth_client_secret,
                    resource=self.config.oauth_resource_url,
                )
            )
            auth = AuthSettings(
                issuer_url=AnyHttpUrl(self.config.oauth_issuer_url),
                resource_server_url=AnyHttpUrl(self.config.oauth_resource_url),
                required_scopes=list(self.config.oauth_required_scopes),
                validate_token_resource=True,
            )

        @asynccontextmanager
        async def lifespan(_server: MCPServer):
            try:
                yield {}
            finally:
                await self.research.close()
                await self.browser.shutdown()
                self.workspace_ops.shutdown()
                self.jobs.close()
                self.search.close()
                self.processes.shutdown()
                self.remote_store.close()

        self.mcp = MCPServer(
            SERVER_NAME,
            version=SERVER_VERSION,
            description="SENTRA Commander: secure local/remote machine + engineering MCP",
            instructions=(
                "Inspect before mutation. Remote device execution is ACL-bound; "
                "CANDIDATE_READY is not APPLIED and promotion is never implicit."
            ),
            lifespan=lifespan,
            token_verifier=verifier,
            auth=auth,
        )
        self._register_tools()

    def _effective_config(self) -> dict[str, Any]:
        return {
            "allowed_roots": [str(path) for path in self.config.allowed_roots],
            "blocked_commands": list(self.config.blocked_commands),
            "max_read_bytes": self.config.max_read_bytes,
            "max_write_bytes": self.config.max_write_bytes,
            "max_output_bytes": self.config.max_output_bytes,
            "max_processes": self.config.max_processes,
            "process_mode": self.config.process_mode,
            "process_sandbox_image": self.config.process_sandbox_image,
            "process_sandbox_cpus": self.config.process_sandbox_cpus,
            "process_sandbox_memory_mb": self.config.process_sandbox_memory_mb,
            "process_sandbox_pids": self.config.process_sandbox_pids,
            "host": self.config.host,
            "port": self.config.port,
            "transport": self.config.transport,
            "deployment_mode": self.config.deployment_mode,
            "tool_surfaces": list(self.config.tool_surfaces),
            "enabled_surfaces": sorted(self.config.enabled_surfaces),
            "allow_non_loopback": self.config.allow_non_loopback,
            "oauth_enabled": self.config.oauth_enabled,
            "oauth_issuer_url": self.config.oauth_issuer_url or None,
            "oauth_resource_url": self.config.oauth_resource_url or None,
            "remote_store": str(self.config.remote_store_path),
        }

    def _apply_safe_config(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.config = replace(self.config, **changes)
        self.workspaces.update_config(self.config)
        self.filesystem.update_config(self.config)
        self.processes.update_config(self.config)
        self.repository.update_config(self.config)
        self.search.update_config(self.config)
        self.jobs.update_config(self.config)
        self.browser.config = self.config
        self.research.update_config(self.config)
        self.telemetry.config = self.config
        # OMA intentionally remains bound to the primary SENTRA workspace.
        # Extra roots are project grants, not alternate OMA state directories.
        self.oma.max_read_bytes = self.config.max_read_bytes
        return {key: getattr(self.config, key) for key in changes}

    def _register_tools(self) -> None:
        @self.mcp.tool()
        def sentra_health() -> ResponseEnvelope:
            self.audit.emit("tool.sentra_health", "ok", {"transport": self.config.transport})
            return ResponseEnvelope.success({
                "status": "ok",
                "capabilities": capability_document(self.config),
                "remote": {
                    "oauth_enabled": self.config.oauth_enabled,
                    "device_registry": True,
                    "relay_store": True,
                },
            })

        if self.config.deployment_mode == "cloud":
            register_remote_tools(self.mcp, self.remote)
            return

        surfaces = self.config.enabled_surfaces
        if "core" in surfaces:
            register_filesystem_tools(self.mcp, self.filesystem)
            register_process_tools(self.mcp, self.processes)
        if {"developer", "oma"} & surfaces:
            register_sentra_tools(
                self.mcp,
                self.repository,
                self.oma,
                surfaces=surfaces,
            )
        if "remote" in surfaces:
            register_remote_tools(self.mcp, self.remote)
        register_commander_tools(
            self.mcp,
            search=self.search,
            runtime_config=self.runtime_config,
            telemetry=self.telemetry,
            documents=self.documents,
            browser=self.browser,
            workspace_ops=self.workspace_ops,
            workspaces=self.workspaces,
            jobs=self.jobs,
            research=self.research,
            surfaces=surfaces - {"remote"},
        )
        register_resources(self.mcp, self.config, self.repository, self.oma, self.browser)
        if "oma" in surfaces:
            register_prompts(self.mcp, self.oma)

    def run(self, transport: str | None = None) -> None:
        selected = transport or self.config.transport
        if selected not in {"stdio", "streamable-http"}:
            raise ValueError(f"unsupported transport: {selected!r}")
        self.audit.emit("server.start", "ok", {
            "transport": selected,
            "oauth": self.config.oauth_enabled,
        })
        try:
            if selected == "stdio":
                self.mcp.run(transport="stdio")
                return
            self.mcp.run(
                transport="streamable-http",
                host=self.config.host,
                port=self.config.port,
                # Local HTTP keeps MCP sessions so owner-scoped tools can derive
                # identity without a manual owner argument. Cloud remains stateless
                # because OAuth subject/device policy is already the identity boundary.
                stateless_http=self.config.deployment_mode == "cloud",
                json_response=True,
            )
        finally:
            self.processes.shutdown()


def create_server(config: MCPConfig | None = None) -> MCPServer:
    return SentraMCPServer(config).mcp
