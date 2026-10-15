"""Reusable operational prompts for SENTRA MCP clients."""
from __future__ import annotations

from mcp.server import MCPServer

from .services.oma import OmaService


def register_prompts(mcp: MCPServer, oma: OmaService) -> None:
    @mcp.prompt(
        name="sentra_operator",
        title="Operate SENTRA safely",
        description="Guide a client to inspect, test and operate SENTRA without automatic promotion.",
    )
    def sentra_operator(run_id: str = "") -> str:
        run_context = ""
        if run_id:
            try:
                status = oma.run_status(run_id)
                state = status.get("status", {}).get("status")
                run_context = f"\nTarget run: {run_id} (reported status: {state})."
            except Exception:
                run_context = f"\nTarget run: {run_id} (status unavailable; verify with sentra_oma_status)."
        return (
            "Operate SENTRA through MCP using least privilege. "
            "Inspect with sentra_repo_* and sentra_oma_* before mutating files or starting processes. "
            "Use filesystem tools only inside configured allowed roots. "
            "Use process tools only for managed owner-scoped sessions and terminate children when finished. "
            "Repository TEST is registered pytest execution, never a raw shell. "
            "Do not claim a run is applied merely because it is CANDIDATE_READY. "
            "There is deliberately no MCP tool for automatic candidate promotion; promotion remains an explicit "
            "external/operator action. Never navigate arbitrary .oma paths."
            + run_context
        )
