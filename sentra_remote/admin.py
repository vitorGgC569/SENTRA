"""Local-only administrative commands for SENTRA Commander."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sentra_mcp.config import MCPConfig, PROJECT_ROOT
from sentra_mcp.services.runtime_config import RuntimeConfigService


def _service(path: Path) -> RuntimeConfigService:
    return RuntimeConfigService(lambda: {}, lambda _: {}, state_path=path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentra-admin")
    parser.add_argument(
        "--state",
        default=str(PROJECT_ROOT / ".sentra" / "mcp-config.json"),
        help="Privileged config approval state file",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    approve = sub.add_parser("approve-config")
    approve.add_argument("request_id")
    reject = sub.add_parser("reject-config")
    reject.add_argument("request_id")
    sub.add_parser("pending-config")
    args = parser.parse_args(argv)
    service = _service(Path(args.state).expanduser())
    if args.command == "approve-config":
        print(json.dumps(service.approve_local(args.request_id), indent=2))
    elif args.command == "reject-config":
        print(json.dumps(service.reject_local(args.request_id), indent=2))
    else:
        print(json.dumps(service.list_pending(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
