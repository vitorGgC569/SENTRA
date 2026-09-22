"""Security-first configuration for the SENTRA MCP server."""
from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .errors import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TRANSPORTS = ("stdio", "streamable-http")
ALLOWED_TOOL_SURFACES = ("all", "core", "developer", "browser", "oma", "remote", "admin")
DEFAULT_TOOL_SURFACES = ("core", "developer", "browser")
ALLOWED_PROCESS_MODES = ("sandbox", "workspace", "unrestricted")
DEFAULT_BLOCKED_COMMANDS = (
    "rm", "rmdir", "del", "erase", "format", "shutdown", "reboot", "poweroff",
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


def _approved_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    approved = data.get("approved") if isinstance(data, dict) else {}
    return approved if isinstance(approved, dict) else {}


@dataclass(frozen=True, slots=True)
class MCPConfig:
    """Configuration with restrictive local-only defaults."""

    allowed_roots: tuple[Path, ...] = field(default_factory=lambda: (PROJECT_ROOT,))
    blocked_commands: tuple[str, ...] = DEFAULT_BLOCKED_COMMANDS
    max_read_bytes: int = 8 * 1024 * 1024
    max_write_bytes: int = 8 * 1024 * 1024
    max_output_bytes: int = 2 * 1024 * 1024
    max_processes: int = 4

    # Process privilege ceiling.  A caller can request an equally or more
    # restrictive mode, never a more privileged one.
    process_mode: str = "workspace"
    process_sandbox_image: str = "oma-sandbox:local"
    process_sandbox_cpus: float = 2.0
    process_sandbox_memory_mb: int = 2048
    process_sandbox_pids: int = 256

    host: str = "127.0.0.1"
    port: int = 8000
    audit_log: Path = field(default_factory=lambda: PROJECT_ROOT / ".sentra" / "mcp-audit.jsonl")
    transport: str = "stdio"
    deployment_mode: str = "local"
    tool_surfaces: tuple[str, ...] = DEFAULT_TOOL_SURFACES
    allow_non_loopback: bool = False
    remote_store_path: Path = field(default_factory=lambda: PROJECT_ROOT / ".sentra" / "remote.sqlite3")

    oauth_issuer_url: str = ""
    oauth_resource_url: str = ""
    oauth_introspection_url: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_required_scopes: tuple[str, ...] = ("sentra:mcp",)

    def __post_init__(self) -> None:
        roots = tuple(Path(root).expanduser().resolve() for root in self.allowed_roots)
        if not roots:
            raise ConfigurationError("allowed_roots must contain at least one explicit root")
        object.__setattr__(self, "allowed_roots", roots)

        blocked = tuple(dict.fromkeys(
            command.strip().casefold() for command in self.blocked_commands if command.strip()
        ))
        object.__setattr__(self, "blocked_commands", blocked)
        object.__setattr__(self, "audit_log", Path(self.audit_log).expanduser().resolve())
        object.__setattr__(self, "remote_store_path", Path(self.remote_store_path).expanduser().resolve())

        scopes = tuple(dict.fromkeys(scope.strip() for scope in self.oauth_required_scopes if scope.strip()))
        object.__setattr__(self, "oauth_required_scopes", scopes or ("sentra:mcp",))

        surfaces = tuple(
            dict.fromkeys(
                str(item).strip().lower()
                for item in self.tool_surfaces
                if str(item).strip()
            )
        )
        if not surfaces:
            surfaces = DEFAULT_TOOL_SURFACES
        unknown_surfaces = set(surfaces) - set(ALLOWED_TOOL_SURFACES)
        if unknown_surfaces:
            raise ConfigurationError(
                "unknown MCP tool surfaces: " + ", ".join(sorted(unknown_surfaces))
            )
        if "all" in surfaces and len(surfaces) > 1:
            surfaces = ("all",)
        object.__setattr__(self, "tool_surfaces", surfaces)

        _positive_int("max_read_bytes", self.max_read_bytes)
        _positive_int("max_write_bytes", self.max_write_bytes)
        _positive_int("max_output_bytes", self.max_output_bytes)
        _positive_int("max_processes", self.max_processes)

        if self.process_mode not in ALLOWED_PROCESS_MODES:
            raise ConfigurationError(
                f"process_mode must be one of {ALLOWED_PROCESS_MODES}"
            )
        if not isinstance(self.process_sandbox_image, str) or not self.process_sandbox_image.strip():
            raise ConfigurationError("process_sandbox_image must be a non-empty image name")
        if not 0.25 <= float(self.process_sandbox_cpus) <= 16:
            raise ConfigurationError("process_sandbox_cpus must be between 0.25 and 16")
        if not 128 <= int(self.process_sandbox_memory_mb) <= 32768:
            raise ConfigurationError("process_sandbox_memory_mb must be between 128 and 32768")
        if not 16 <= int(self.process_sandbox_pids) <= 4096:
            raise ConfigurationError("process_sandbox_pids must be between 16 and 4096")

        if not 1 <= self.port <= 65535:
            raise ConfigurationError("port must be between 1 and 65535")
        if self.transport not in ALLOWED_TRANSPORTS:
            raise ConfigurationError(
                f"unsupported transport {self.transport!r}; expected one of {ALLOWED_TRANSPORTS}"
            )
        if self.deployment_mode not in {"local", "cloud"}:
            raise ConfigurationError("deployment_mode must be local or cloud")
        if not self.allow_non_loopback and not _is_loopback(self.host):
            raise ConfigurationError(
                "non-loopback HTTP host requires explicit allow_non_loopback authorization"
            )
        if self.deployment_mode == "cloud":
            if self.transport != "streamable-http":
                raise ConfigurationError("cloud mode requires streamable-http transport")
            if not (
                self.oauth_issuer_url
                and self.oauth_resource_url
                and self.oauth_introspection_url
            ):
                raise ConfigurationError(
                    "cloud mode requires OAuth issuer, resource URL and introspection URL"
                )
        if self.allow_non_loopback and not _is_loopback(self.host):
            if not (
                self.oauth_issuer_url
                and self.oauth_resource_url
                and self.oauth_introspection_url
            ):
                raise ConfigurationError(
                    "non-loopback MCP requires OAuth issuer, resource URL and introspection URL"
                )
            if not self.oauth_resource_url.startswith("https://"):
                raise ConfigurationError(
                    "non-loopback OAuth resource URL must use HTTPS"
                )
            if not self.oauth_issuer_url.startswith("https://"):
                raise ConfigurationError(
                    "non-loopback OAuth issuer must use HTTPS"
                )

    @property
    def oauth_enabled(self) -> bool:
        return bool(
            self.oauth_issuer_url
            and self.oauth_resource_url
            and self.oauth_introspection_url
        )

    @property
    def enabled_surfaces(self) -> set[str]:
        if "all" in self.tool_surfaces:
            return {"core", "developer", "browser", "oma", "remote", "admin"}
        return set(self.tool_surfaces)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "MCPConfig":
        env = os.environ if environ is None else environ
        state_path = Path(
            env.get(
                "SENTRA_MCP_CONFIG_STATE",
                str(PROJECT_ROOT / ".sentra" / "mcp-config.json"),
            )
        )
        approved = _approved_state(state_path)

        roots_value = env.get("SENTRA_MCP_ALLOWED_ROOTS")
        approved_roots = approved.get("allowed_roots")
        roots = (
            tuple(Path(item) for item in roots_value.split(os.pathsep) if item.strip())
            if roots_value
            else tuple(Path(item) for item in approved_roots)
            if isinstance(approved_roots, list) and approved_roots
            else (PROJECT_ROOT,)
        )

        blocked_value = env.get("SENTRA_MCP_BLOCKED_COMMANDS")
        approved_blocked = approved.get("blocked_commands")
        blocked = (
            tuple(item.strip() for item in blocked_value.split(",") if item.strip())
            if blocked_value is not None
            else tuple(str(item) for item in approved_blocked)
            if isinstance(approved_blocked, list)
            else DEFAULT_BLOCKED_COMMANDS
        )

        host = env.get("SENTRA_MCP_HOST", str(approved.get("host", "127.0.0.1")))
        port = int(env.get("SENTRA_MCP_PORT", approved.get("port", 8000)))
        if "SENTRA_MCP_ALLOW_NON_LOOPBACK" in env:
            non_loopback = _parse_bool(env.get("SENTRA_MCP_ALLOW_NON_LOOPBACK"))
        else:
            non_loopback = bool(approved.get("allow_non_loopback", False))

        return cls(
            allowed_roots=roots,
            blocked_commands=blocked,
            max_read_bytes=int(env.get("SENTRA_MCP_MAX_READ_BYTES", 8 * 1024 * 1024)),
            max_write_bytes=int(env.get("SENTRA_MCP_MAX_WRITE_BYTES", 8 * 1024 * 1024)),
            max_output_bytes=int(env.get("SENTRA_MCP_MAX_OUTPUT_BYTES", 2 * 1024 * 1024)),
            max_processes=int(env.get("SENTRA_MCP_MAX_PROCESSES", 4)),
            process_mode=env.get("SENTRA_MCP_PROCESS_MODE", "workspace").strip().lower(),
            process_sandbox_image=env.get(
                "SENTRA_MCP_SANDBOX_IMAGE", "oma-sandbox:local"
            ),
            process_sandbox_cpus=float(env.get("SENTRA_MCP_SANDBOX_CPUS", 2.0)),
            process_sandbox_memory_mb=int(
                env.get("SENTRA_MCP_SANDBOX_MEMORY_MB", 2048)
            ),
            process_sandbox_pids=int(env.get("SENTRA_MCP_SANDBOX_PIDS", 256)),
            host=host,
            port=port,
            audit_log=Path(
                env.get(
                    "SENTRA_MCP_AUDIT_LOG",
                    str(PROJECT_ROOT / ".sentra" / "mcp-audit.jsonl"),
                )
            ),
            transport=env.get("SENTRA_MCP_TRANSPORT", "stdio"),
            deployment_mode=env.get("SENTRA_MCP_MODE", "local"),
            tool_surfaces=tuple(
                item.strip()
                for item in env.get(
                    "SENTRA_MCP_SURFACES",
                    ",".join(DEFAULT_TOOL_SURFACES),
                ).split(",")
                if item.strip()
            ),
            allow_non_loopback=non_loopback,
            remote_store_path=Path(
                env.get(
                    "SENTRA_REMOTE_STORE",
                    str(PROJECT_ROOT / ".sentra" / "remote.sqlite3"),
                )
            ),
            oauth_issuer_url=env.get("SENTRA_OAUTH_ISSUER_URL", ""),
            oauth_resource_url=env.get("SENTRA_OAUTH_RESOURCE_URL", ""),
            oauth_introspection_url=env.get("SENTRA_OAUTH_INTROSPECTION_URL", ""),
            oauth_client_id=env.get("SENTRA_OAUTH_CLIENT_ID", ""),
            oauth_client_secret=env.get("SENTRA_OAUTH_CLIENT_SECRET", ""),
            oauth_required_scopes=tuple(
                item
                for item in env.get(
                    "SENTRA_OAUTH_REQUIRED_SCOPES", "sentra:mcp"
                ).split()
                if item
            ),
        )
