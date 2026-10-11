"""Internal diagnostics and safe, separately consented support export for SENTRA.

Internal operational reports are *never* sent automatically. Shared reports use
an allowlist, not regex-only blacklisting: arbitrary error strings and remote
service payloads cannot leak identifying material.
"""
from __future__ import annotations

import json
import platform
import sys
import urllib.request
from pathlib import Path
from typing import Any

from .agent_config import AgentConfig


def collect(config_path: Path) -> dict[str, Any]:
    """Internal-only details, permitted for an authenticated local operator."""
    result: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "hostname": platform.node(),
        "config_exists": config_path.is_file(),
    }
    if not config_path.is_file():
        return result
    try:
        config = AgentConfig.load(config_path)
    except Exception as exc:
        result["config_error"] = str(exc)[:300]
        return result
    result["device"] = {
        "device_id": config.device_id,
        "name": config.name,
        "relay_url": config.relay_url,
        "allowed_roots": list(config.allowed_roots),
        "audit_log": config.audit_log,
        "process_mode": config.process_mode,
        "profile": config.profile,
        "access_scope": config.access_scope,
        "tool_surfaces": list(config.tool_surfaces),
        "token_present": bool(config.device_token),
    }
    try:
        with urllib.request.urlopen(config.relay_url.rstrip("/") + "/health", timeout=3) as response:
            result["relay"] = json.loads(response.read(65536))
    except Exception as exc:
        result["relay"] = {"ok": False, "error": str(exc)[:300]}
    audit = Path(config.audit_log)
    result["audit_exists"] = audit.is_file()
    result["audit_size"] = audit.stat().st_size if audit.is_file() else 0
    return result


def shareable_report(raw: dict[str, Any]) -> dict[str, Any]:
    """Strict bounded projection for a report someone can safely review.

    Excludes identifiers, user paths, hostnames, URLs, chat/task content,
    arbitrary exception messages and upstream health payloads. Caller reviews
    the resulting JSON before sharing; even the report itself stays local.
    """
    device = raw.get("device") if isinstance(raw.get("device"), dict) else {}
    public: dict[str, Any] = {
        "schema_version": 1,
        "kind": "sentra_shareable_diagnostics",
        "config_present": raw.get("config_exists") is True,
        "config_parse_ok": bool(raw.get("config_exists") and "config_error" not in raw),
        "python_major_minor": "",
        "platform_family": "unknown",
        "device": {
            "token_configured": device.get("token_present") is True,
            "audit_present": raw.get("audit_exists") is True,
        },
        "relay": {"healthy": False, "reachable": False},
    }
    python = raw.get("python")
    if isinstance(python, str):
        parts = python.split(".")
        if len(parts) >= 2 and all(part.isdigit() and len(part) <= 3 for part in parts[:2]):
            public["python_major_minor"] = ".".join(parts[:2])
    platform_str = raw.get("platform")
    if isinstance(platform_str, str):
        family = platform_str.split("-", 1)[0].casefold()
        if family.startswith("windows"):
            public["platform_family"] = "windows"
        elif family.startswith("linux"):
            public["platform_family"] = "linux"
        elif family.startswith("darwin") or family.startswith("macos"):
            public["platform_family"] = "macos"
    for name, allowed in (
        ("process_mode", {"disabled", "read_only", "sandbox", "restricted", "native", "docker", "host", "isolated"}),
        ("profile", {"safe", "full", "balanced", "developer"}),
        ("access_scope", {"workspace", "all", "selected", "read_only", "none"}),
    ):
        value = device.get(name)
        if isinstance(value, str) and value.casefold() in allowed:
            public["device"][name] = value.casefold()
    surfaces = device.get("tool_surfaces")
    if isinstance(surfaces, list):
        public["device"]["surface_count"] = min(len(surfaces), 1000)
    roots = device.get("allowed_roots")
    if isinstance(roots, list):
        public["device"]["workspace_count"] = min(len(roots), 1000)
    relay = raw.get("relay")
    if isinstance(relay, dict):
        public["relay"]["reachable"] = "error" not in relay
        public["relay"]["healthy"] = relay.get("ok") is True
    return public


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="sentra-diagnostics")
    parser.add_argument("--config", default=str(Path.home() / ".sentra" / "agent.json"))
    parser.add_argument("--output", help="Write to a local file; review it before sharing")
    parser.add_argument("--internal", action="store_true",
                        help="Include private machine metadata (local troubleshooting ONLY)")
    args = parser.parse_args(argv)
    raw = collect(Path(args.config).expanduser())
    data = raw if args.internal else shareable_report(raw)
    encoded = json.dumps(data, indent=2, ensure_ascii=False)
    if args.output:
        destination = Path(args.output).expanduser()
        if destination.exists():
            parser.error("refusing to overwrite an existing diagnostics report")
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
