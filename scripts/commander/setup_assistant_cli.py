"""SENTRA's consent-based local setup entrypoint for human or AI operators.

Call this through Desktop Commander/Codex with the same account authority.
Never pass Runtime API keys on command lines or expose them in chat.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentra_remote.local_runtime import LocalRuntime
from sentra_remote.product import ProductPaths, ProductSettings
from sentra_remote.setup_assistant import SetupAssistant


def execute(
    action: str, *,
    paths: ProductPaths,
    approved: bool = False,
    tunnel_id: str = "",
    runtime_key: str = "",
    optional: str = "",
    workspace: Path | None = None,
    permissions: tuple[str, ...] = ("read",),
) -> dict[str, Any]:
    settings = ProductSettings.load(paths.settings)
    runtime = LocalRuntime(paths, settings)
    assistant = SetupAssistant(paths, settings, runtime)
    if action == "doctor":
        report = assistant.doctor()
        return {"ok": report["ready"], "doctor": report}
    if action == "start-local":
        if not approved:
            return {"ok": False, "reason": "approval_required_to_start_services"}
        return assistant.start_local()
    if action == "connect-openai":
        if not tunnel_id or not runtime_key:
            return {"ok": False, "reason": "provide_tunnel_id_and_runtime_api_key_env"}
        return assistant.connect_openai(tunnel_id, runtime_key, approved=approved)
    if action == "install-optional":
        return assistant.install_optional(optional, approved=approved)
    if action == "workspace":
        if not approved and workspace is not None:
            return {"ok": False, "reason": "approval_required_for_workspace"}
        root = assistant.prepare_workspace(workspace, approved=approved, permissions=permissions)
        return {"ok": True, "workspace": root, "permissions": list(permissions)}
    raise ValueError("unknown setup action")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("doctor", "start-local", "connect-openai", "install-optional", "workspace"),
    )
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--approve", action="store_true", help="Explicit operator approval")
    parser.add_argument("--tunnel-id", default="", help="Public tunnel identifier; not the key")
    parser.add_argument("--runtime-key-env", default="CONTROL_PLANE_API_KEY",
                        help="Environment variable with restricted key, never a CLI argument")
    parser.add_argument("--optional", choices=("git", "docker", "ollama"))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--permission", choices=("read", "write", "execute"),
                        action="append")
    args = parser.parse_args(argv)
    install_dir = args.install_dir or ProductPaths.default().install_dir
    paths = (
        ProductPaths(install_dir.resolve(), args.state_dir.resolve())
        if args.state_dir else ProductPaths.default(install_dir.resolve())
    )
    try:
        result = execute(
            args.action, paths=paths, approved=args.approve,
            tunnel_id=args.tunnel_id,
            runtime_key=os.environ.get(args.runtime_key_env, "") if args.action == "connect-openai" else "",
            optional=args.optional or "", workspace=args.workspace,
            permissions=tuple(args.permission or ("read",)),
        )
    except (PermissionError, OSError, RuntimeError, ValueError) as exc:
        # Never echo exception strings: platform/transport errors may mention
        # sensitive values. The exception type is sufficient for first-line QA.
        result = {"ok": False, "reason": type(exc).__name__}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
