"""Command line entry point for python -m sentra_mcp."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from .config import ALLOWED_TRANSPORTS, MCPConfig
from .errors import ConfigurationError, sanitize_error
from .server import SentraMCPServer


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="SENTRA Commander MCP server")
    cli.add_argument("--transport", choices=ALLOWED_TRANSPORTS)
    cli.add_argument("--mode", choices=("local", "cloud"), dest="deployment_mode")
    cli.add_argument("--host")
    cli.add_argument("--port", type=int)
    cli.add_argument("--allowed-root", action="append", dest="allowed_roots")
    cli.add_argument("--blocked-command", action="append", dest="blocked_commands")
    cli.add_argument("--max-read-bytes", type=int)
    cli.add_argument("--max-write-bytes", type=int)
    cli.add_argument("--max-output-bytes", type=int)
    cli.add_argument("--max-processes", type=int)
    cli.add_argument("--audit-log")
    cli.add_argument("--remote-store")
    cli.add_argument("--oauth-issuer-url")
    cli.add_argument("--oauth-resource-url")
    cli.add_argument("--oauth-introspection-url")
    cli.add_argument("--oauth-client-id")
    cli.add_argument("--oauth-client-secret")
    cli.add_argument("--oauth-required-scope", action="append", dest="oauth_required_scopes")
    cli.add_argument("--allow-non-loopback", action="store_true")
    return cli


def config_from_args(args: argparse.Namespace, base: MCPConfig | None = None) -> MCPConfig:
    config = base or MCPConfig.from_env()
    overrides: dict[str, object] = {}
    for name in (
        "transport", "deployment_mode", "host", "port", "max_read_bytes", "max_write_bytes",
        "max_output_bytes", "max_processes", "oauth_issuer_url",
        "oauth_resource_url", "oauth_introspection_url", "oauth_client_id",
        "oauth_client_secret",
    ):
        value = getattr(args, name)
        if value is not None:
            overrides[name] = value
    if args.allowed_roots is not None:
        overrides["allowed_roots"] = tuple(Path(value) for value in args.allowed_roots)
    if args.blocked_commands is not None:
        overrides["blocked_commands"] = tuple(args.blocked_commands)
    if args.audit_log is not None:
        overrides["audit_log"] = Path(args.audit_log)
    if args.remote_store is not None:
        overrides["remote_store_path"] = Path(args.remote_store)
    if args.oauth_required_scopes is not None:
        overrides["oauth_required_scopes"] = tuple(args.oauth_required_scopes)
    if args.allow_non_loopback:
        overrides["allow_non_loopback"] = True
    return replace(config, **overrides)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = config_from_args(args)
        SentraMCPServer(config).run()
    except (ConfigurationError, ValueError) as exc:
        print(f"SENTRA MCP configuration error: {sanitize_error(exc)}", file=sys.stderr)
        return 2
    return 0
