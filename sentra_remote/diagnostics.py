"""Local diagnostics for SENTRA Commander without exposing secrets."""
from __future__ import annotations

import json
import platform
import sys
import urllib.request
from pathlib import Path
from typing import Any

from .agent_config import AgentConfig


def collect(config_path: Path) -> dict[str, Any]:
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


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="sentra-diagnostics")
    parser.add_argument("--config", default=str(Path.home() / ".sentra" / "agent.json"))
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    data = collect(Path(args.config).expanduser())
    encoded = json.dumps(data, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
