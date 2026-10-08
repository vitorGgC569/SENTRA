"""Non-destructive environment probes for SENTRA installation and Web Models.

Presence of an executable never implies a running daemon or authenticated model.
The probe does not install packages, read cookies, print keys or launch browsers.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _command(name: str, args: list[str], timeout: int = 8) -> dict[str, Any]:
    location = shutil.which(name)
    if not location:
        return {"installed": False, "ready": False, "detail": f"{name} is not installed"}
    try:
        result = subprocess.run(
            [location, *args], capture_output=True, text=True,
            timeout=timeout, check=False, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"installed": True, "ready": False, "detail": type(exc).__name__}
    # Do not return arbitrary CLI stdout/stderr (may embed external secrets).
    return {
        "installed": True, "ready": result.returncode == 0,
        "exit_code": result.returncode,
    }


def _http(url: str, timeout: float = 2.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "SENTRA-Doctor/1"}),
            timeout=timeout,
        ) as response:
            payload = json.load(response)
            return {"online": response.status == 200, "payload": payload}
    except (OSError, urllib.error.URLError, ValueError, TypeError):
        return {"online": False}


def probe(install_dir: Path) -> dict[str, Any]:
    from sentra_remote.product import ProductPaths, ProductSettings
    from sentra_remote.local_runtime import LocalRuntime
    from sentra_remote.setup_assistant import local_model_status
    from sentra_remote.desktop import _codex_route_points_to_sentra
    from sentra_remote.onboarding import chatgpt_plugin_install_plan

    install_dir = install_dir.resolve()
    paths = ProductPaths.default(install_dir)
    try:
        settings = ProductSettings.load(paths.settings)
    except (OSError, ValueError):
        settings = ProductSettings()
    git = _command("git", ["--version"])
    codex = _command("codex", ["--version"], timeout=12)
    docker = _command("docker", ["info", "--format", "{{.ServerVersion}}"], timeout=12)
    ollama = local_model_status()
    launcher = install_dir / "web-models" / "win-unpacked" / "Codex Web GPT.exe"
    if not launcher.is_file():
        launcher = install_dir / "dist" / "web-models" / "win-unpacked" / "Codex Web GPT.exe"
    gateway = _http("http://127.0.0.1:17842/healthz")
    mcp = _http(f"http://127.0.0.1:{settings.mcp_port}/healthz")
    status = {
        "mcp": bool(
            mcp["online"]
            and isinstance(mcp.get("payload"), dict)
            and mcp["payload"].get("service") == "sentra-mcp"
            and mcp["payload"].get("ok") is True
        ),
        "gateway": gateway["online"],
    }

    tunnel_configured = paths.tunnel_config.is_file()
    # Verify the real SENTRA tunnel health from the runtime supervision
    # contract; never infer online state from stored configuration alone.
    try:
        tunnel_online = bool(
            LocalRuntime(paths, settings).status().get("tunnel", {}).get("ok")
        )
    except (OSError, ValueError, RuntimeError):
        tunnel_online = False
    chatgpt = chatgpt_plugin_install_plan(
        {"mcp": {"ok": status["mcp"]},
         "tunnel": {"configured": tunnel_configured, "ok": tunnel_online}},
    )
    results = {
        "git": {"ready": bool(git["ready"]), "detail": (
            "Git available" if git["ready"] else "Install Git for version-control workflows"
        )},
        "codex": {
            "ready": bool(codex["ready"]), "installed": bool(codex["installed"]),
            "model_route_to_sentra": bool(_codex_route_points_to_sentra()),
            "detail": (
                "Codex CLI available; confirm Web Models account and gateway separately"
                if codex["ready"] else "Codex CLI missing or not responding"
            ),
        },
        "docker": {
            "ready": bool(docker["ready"]), "installed": bool(docker["installed"]),
            "detail": (
                "Docker daemon responding" if docker["ready"] else
                "Open Docker Desktop / start daemon before using isolated execution"
                if docker["installed"] else "Install Docker Desktop only with approval"
            ),
        },
        "ollama": {
            "ready": bool(ollama.get("ready")),
            "models": list(ollama.get("models") or []),
            "detail": (
                "Ollama model available" if ollama.get("ready") else
                "Install/start Ollama and download a model with approval"
            ),
        },
        "web_models": {
            "installed": launcher.is_file(),
            "gateway_online": status["gateway"],
            "ready": bool(status["gateway"] and gateway.get("payload", {}).get("accepting_turns")),
            "detail": (
                "Gateway online; verify authenticated model turn before declaring usable"
                if status["gateway"] else "Start Web Models / sign in using the launcher"
            ),
        },
        "chatgpt_plugin": {
            "ready": bool(chatgpt["ready_to_install"]),
            "tunnel_configured": tunnel_configured,
            "mcp_online": status["mcp"],
            "detail": chatgpt["reason"],
            "requires_account_authorization": True,
        },
    }
    return {
        "ok": all(results[key]["ready"] for key in ("git", "codex")),
        "full_integration_ready": all(item.get("ready") for item in results.values()),
        "checks": results,
        "privacy": "No credentials, browser cookies, tokens or personal files returned",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path)
    args = parser.parse_args(argv)
    install_dir = args.install_dir or (
        Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        / "SENTRA" / "Commander"
    )
    report = probe(install_dir)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
