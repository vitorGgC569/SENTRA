"""Local-only administrative commands for SENTRA Commander."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sentra_mcp.config import PROJECT_ROOT
from sentra_mcp.services.runtime_config import RuntimeConfigService
from sentra_mcp.services.workspaces import WorkspaceRegistry


def _config_service(path: Path) -> RuntimeConfigService:
    return RuntimeConfigService(lambda: {}, lambda _: {}, state_path=path)


def _workspace_service(path: Path) -> WorkspaceRegistry:
    # Local approval only needs the persistent registry state. Configured roots
    # are still loaded so attempts to remove the primary SENTRA root remain
    # protected consistently with the running MCP.
    from sentra_mcp.config import MCPConfig
    return WorkspaceRegistry(
        MCPConfig(),
        state_path=path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentra-admin")
    parser.add_argument(
        "--state",
        default=str(PROJECT_ROOT / ".sentra" / "mcp-config.json"),
        help="Privileged config approval state file",
    )
    parser.add_argument(
        "--workspace-state",
        default=str(PROJECT_ROOT / ".sentra" / "workspaces.json"),
        help="Workspace approval state file",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    approve = sub.add_parser("approve-config")
    approve.add_argument("request_id")
    reject = sub.add_parser("reject-config")
    reject.add_argument("request_id")
    sub.add_parser("pending-config")

    approve_ws = sub.add_parser("approve-workspace")
    approve_ws.add_argument("request_id")
    reject_ws = sub.add_parser("reject-workspace")
    reject_ws.add_argument("request_id")
    sub.add_parser("pending-workspaces")

    args = parser.parse_args(argv)
    if args.command in {"approve-config", "reject-config", "pending-config"}:
        service = _config_service(Path(args.state).expanduser())
        if args.command == "approve-config":
            result = service.approve_local(args.request_id)
        elif args.command == "reject-config":
            result = service.reject_local(args.request_id)
        else:
            result = service.list_pending()
    else:
        service = _workspace_service(Path(args.workspace_state).expanduser())
        if args.command == "approve-workspace":
            result = service.approve_local(args.request_id)
        elif args.command == "reject-workspace":
            result = service.reject_local(args.request_id)
        else:
            result = service.pending()

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
