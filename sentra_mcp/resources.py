"""MCP resources exposing bounded SENTRA metadata and run summaries."""
from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer

from .config import MCPConfig
from .models import CapabilityMetadata
from .services.oma import OmaService
from .services.repository import RepositoryService


def capability_document(config: MCPConfig) -> dict[str, Any]:
    metadata = CapabilityMetadata().model_dump(mode="json")
    metadata["security"] = {
        "allowed_root_count": len(config.allowed_roots),
        "blocked_command_count": len(config.blocked_commands),
        "max_read_bytes": config.max_read_bytes,
        "max_write_bytes": config.max_write_bytes,
        "max_output_bytes": config.max_output_bytes,
        "max_processes": config.max_processes,
        "http_loopback_only": not config.allow_non_loopback,
        "automatic_promotion": False,
        "arbitrary_oma_access": False,
    }
    metadata["tool_families"] = [
        "filesystem",
        "processes",
        "repository",
        "oma_observability",
    ]
    return metadata


def register_resources(
    mcp: MCPServer,
    config: MCPConfig,
    repository: RepositoryService,
    oma: OmaService,
) -> None:
    @mcp.resource(
        "sentra://capabilities",
        name="SENTRA MCP capabilities",
        description="Public capability, transport and security metadata.",
        mime_type="application/json",
    )
    def sentra_capabilities() -> str:
        return json.dumps(capability_document(config), ensure_ascii=False, sort_keys=True)

    @mcp.resource(
        "sentra://project/summary",
        name="SENTRA project summary",
        description="Bounded local project status without source disclosure.",
        mime_type="application/json",
    )
    async def sentra_project_summary() -> str:
        status = await repository.status()
        data = {
            "workspace": str(repository.workspace),
            "git_status": status["result"],
            "oma": oma.health(),
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    @mcp.resource(
        "sentra://run/{run_id}/summary",
        name="SENTRA run summary",
        description="Validated read-only OMA run status/handoff summary.",
        mime_type="application/json",
    )
    def sentra_run_summary(run_id: str) -> str:
        data = oma.run_status(run_id)
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
