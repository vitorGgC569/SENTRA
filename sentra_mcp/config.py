"""Security-first configuration for the SENTRA MCP server."""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .errors import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TRANSPORTS = ("stdio", "streamable-http")
DEFAULT_BLOCKED_COMMANDS = (
    "rm",
    "rmdir",
    "del",
    "erase",
    "format",
    "shutdown",
    "reboot",
    "poweroff",
)


def _is_loopback(host: str) -> bool:
    candidate = host.strip().lower()
    if candidate in {"localhost", "localhost."}:
        return True
    candidate = candidate.removeprefix("[").removesuffix("]")
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"invalid boolean value: {value!r}")


def _positive_int(name: str, value: int) -> int:
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class MCPConfig:
    """Configuration with restrictive local-only defaults."""

    allowed_roots: tuple[Path, ...] = field(default_factory=lambda: (PROJECT_ROOT,))
    blocked_commands: tuple[str, ...] = DEFAULT_BLOCKED_COMMANDS
    max_read_bytes: int = 8 * 1024 * 1024
    max_write_bytes: int = 8 * 1024 * 1024
    max_output_bytes: int = 2 * 1024 * 1024
    max_processes: int = 4
    host: str = "127.0.0.1"
    port: int = 8000
    audit_log: Path = field(default_factory=lambda: PROJECT_ROOT / ".sentra" / "mcp-audit.jsonl")
    transport: str = "stdio"
    allow_non_loopback: bool = False

    def __post_init__(self) -> None:
        roots = tuple(Path(root).expanduser().resolve() for root in self.allowed_roots)
        if not roots:
            raise ConfigurationError("allowed_roots must contain at least one explicit root")
        object.__setattr__(self, "allowed_roots", roots)

        blocked = tuple(
            dict.fromkeys(command.strip().casefold() for command in self.blocked_commands if command.strip())
        )
        object.__setattr__(self, "blocked_commands", blocked)
        object.__setattr__(self, "audit_log", Path(self.audit_log).expanduser().resolve())

        _positive_int("max_read_bytes", self.max_read_bytes)
        _positive_int("max_write_bytes", self.max_write_bytes)
        _positive_int("max_output_bytes", self.max_output_bytes)
        _positive_int("max_processes", self.max_processes)
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("port must be between 1 and 65535")
        if self.transport not in ALLOWED_TRANSPORTS:
            raise ConfigurationError(
                f"unsupported transport {self.transport!r}; expected one of {ALLOWED_TRANSPORTS}"
            )
        if not self.allow_non_loopback and not _is_loopback(self.host):
            raise ConfigurationError(
                "non-loopback HTTP host requires explicit allow_non_loopback authorization"
            )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "MCPConfig":
        """Build configuration from SENTRA_MCP_* environment variables."""

        env = os.environ if environ is None else environ
        roots_value = env.get("SENTRA_MCP_ALLOWED_ROOTS")
        roots = (
            tuple(Path(item) for item in roots_value.split(os.pathsep) if item.strip())
            if roots_value
            else (PROJECT_ROOT,)
        )
        blocked_value = env.get("SENTRA_MCP_BLOCKED_COMMANDS")
        blocked = (
            tuple(item.strip() for item in blocked_value.split(",") if item.strip())
            if blocked_value is not None
            else DEFAULT_BLOCKED_COMMANDS
        )
        return cls(
            allowed_roots=roots,
            blocked_commands=blocked,
            max_read_bytes=int(env.get("SENTRA_MCP_MAX_READ_BYTES", 8 * 1024 * 1024)),
            max_write_bytes=int(env.get("SENTRA_MCP_MAX_WRITE_BYTES", 8 * 1024 * 1024)),
            max_output_bytes=int(env.get("SENTRA_MCP_MAX_OUTPUT_BYTES", 2 * 1024 * 1024)),
            max_processes=int(env.get("SENTRA_MCP_MAX_PROCESSES", 4)),
            host=env.get("SENTRA_MCP_HOST", "127.0.0.1"),
            port=int(env.get("SENTRA_MCP_PORT", 8000)),
            audit_log=Path(
                env.get("SENTRA_MCP_AUDIT_LOG", str(PROJECT_ROOT / ".sentra" / "mcp-audit.jsonl"))
            ),
            transport=env.get("SENTRA_MCP_TRANSPORT", "stdio"),
            allow_non_loopback=_parse_bool(env.get("SENTRA_MCP_ALLOW_NON_LOOPBACK")),
        )
