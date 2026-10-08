"""Least-privilege, resumable local setup coordinator.

No external credential, package installation, Codex routing or filesystem
permission change occurs during capability discovery. Explicit user consent
is required at the action boundary.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .onboarding import build_onboarding_snapshot
from .product import (
    ProductPaths, ProductSettings, configure_tunnel, load_tunnel_config,
    sync_agent_policy, sync_workspace_registry,
)

STARTER_LOCAL_MODEL = "qwen2.5:0.5b-instruct-q4_K_M"


def _ollama_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        installed = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
        if installed.is_file():
            return str(installed.resolve())
    return None


def local_model_status() -> dict[str, Any]:
    """Probe loopback only; do not infer readiness from a binary on PATH."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=0.7) as response:
            payload = json.load(response)
        items = payload.get("models") if isinstance(payload, dict) else None
        names = sorted(
            str(item.get("name")) for item in (items or [])
            if isinstance(item, dict) and item.get("name")
        )
        return {
            "ready": bool(names), "daemon_ready": True,
            "models": names, "starter_installed": STARTER_LOCAL_MODEL in names,
        }
    except (OSError, ValueError, TypeError):
        return {"ready": False, "daemon_ready": False, "models": []}


@dataclass(frozen=True, slots=True)
class SetupCapability:
    id: str
    state: str  # ready, attention, optional
    title: str
    explanation: str
    action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def first_workspace(paths: ProductPaths, settings: ProductSettings) -> Path:
    """Create only SENTRA-owned starter data; never grant access to user home."""
    if settings.allowed_roots:
        return Path(settings.allowed_roots[0])
    # Never store user projects inside install_dir or state_dir: uninstalling
    # SENTRA may remove those directories (unless config retention is chosen).
    base = paths.state_dir.resolve().parent
    install = paths.install_dir.resolve()
    if base == install or base.is_relative_to(install):
        base = Path.home().resolve()
    root = (base / "SENTRA Projects" / "Starter").resolve()
    if not root.is_relative_to(base) or root.is_relative_to(paths.state_dir.resolve()) or root.is_relative_to(install):
        raise ValueError("starter workspace must live outside removable SENTRA files")
    root.mkdir(parents=True, exist_ok=True)
    settings.allowed_roots.append(str(root))
    # Starter project is writable for project workflows, not global filesystem.
    settings.workspace_permissions[str(root)] = (
        ["read"] if settings.profile == "Safe" else ["read", "write", "execute"]
    )
    settings.save(paths.settings)
    return root


def grant_workspace(
    paths: ProductPaths, settings: ProductSettings, folder: Path,
    *, permissions: tuple[str, ...] = ("read",), approved: bool = False
) -> str:
    """Use just-in-time scoped grants; requests outside the starter need consent."""
    if not approved:
        raise PermissionError("workspace access requires explicit user approval")
    root = Path(folder).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    allowed = {"read", "write", "execute"}
    if not permissions or any(p not in allowed for p in permissions):
        raise ValueError("invalid workspace permissions")
    perms = ["read"] + [p for p in ("write", "execute") if p in permissions]
    if str(root) not in settings.allowed_roots:
        settings.allowed_roots.append(str(root))
    settings.workspace_permissions[str(root)] = perms
    settings.save(paths.settings)
    sync_workspace_registry(paths, settings)
    sync_agent_policy(paths, settings)
    return str(root)


def detect_capabilities(
    status: dict[str, Any], *, paths: ProductPaths | None = None,
    settings: ProductSettings | None = None
) -> dict[str, Any]:
    """Pure discovery from verified health, without starting processes."""
    snapshot = build_onboarding_snapshot(status)
    core = {item.id: item for item in snapshot.surfaces}
    external = {
        "git": shutil.which("git"),
        "docker": shutil.which("docker"),
        "ollama": _ollama_binary(),
        "winget": shutil.which("winget"),
    }
    model = status.get("local_model") or {}
    web_health = status.get("web_models") or {}
    # A listening Gateway alone does not prove an authenticated model turn
    # is possible. Require a catalog and accepting upstream, or the
    # verified starter Ollama model selected by SENTRA CLI.
    ai_ready = bool(
        model.get("starter_installed")
        or (web_health.get("catalog_ready") and web_health.get("turn_ready"))
    )
    capabilities = [
        SetupCapability(
            "local", "ready" if core["terminal"].ready else "attention",
            "SENTRA local", core["terminal"].detail,
            None if core["terminal"].ready else "start_local",
        ),
        SetupCapability(
            "chatgpt", "ready" if core["chatgpt"].ready else "optional",
            "ChatGPT / Secure MCP Tunnel", core["chatgpt"].detail,
            None if core["chatgpt"].ready else "connect_openai",
        ),
        SetupCapability(
            "codex", "ready" if core["codex"].ready else "optional",
            "Codex / Web Models", core["codex"].detail,
            None if core["codex"].ready else "connect_codex",
        ),
        SetupCapability(
            "edge", "ready" if core["browser"].ready else "optional",
            "Microsoft Edge", core["browser"].detail,
            None if core["browser"].ready else "connect_edge",
        ),
        SetupCapability(
            "ai_model", "ready" if ai_ready else "optional",
            "AI model",
            "Web or local model is available." if ai_ready else
            "Sign in to Web Models or install a local model on demand.",
            None if ai_ready else "connect_codex_or_local_model",
        ),
        SetupCapability(
            "ollama", "ready" if model.get("ready") else "optional",
            "Ollama local models",
            "Local model server has at least one model." if model.get("ready") else
            "Optional: install Ollama and download the starter model with consent.",
            None if model.get("ready") else "install_local_model",
        ),
        SetupCapability(
            "git", "ready" if external["git"] else "optional",
            "Git", "Already on PATH." if external["git"]
            else "Can be installed with approval for Git workflows.",
            None if external["git"] else "install_git",
        ),
        SetupCapability(
            "docker", "ready" if bool((status.get("sandbox") or {}).get("ok")) else "optional",
            "Docker sandbox",
            "Daemon ready." if bool((status.get("sandbox") or {}).get("ok"))
            else "Isolated runs require a working Docker daemon; never silently execute on the host.",
            None if bool((status.get("sandbox") or {}).get("ok")) else "install_docker",
        ),
    ]
    roots = list(settings.allowed_roots) if settings else []
    return {
        "ready": bool(snapshot.ready),
        "stage": snapshot.stage,
        "capabilities": [item.to_dict() for item in capabilities],
        "workspace": roots[0] if roots else None,
        "actions": [item.id for item in snapshot.actions],
        "install_root": str(paths.install_dir) if paths else None,
        "package_manager": "winget" if external["winget"] else None,
    }


class SetupAssistant:
    """Single orchestration boundary for Desktop, installer and future CLI."""

    def __init__(self, paths: ProductPaths, settings: ProductSettings, runtime: Any) -> None:
        self.paths = paths
        self.settings = settings
        self.runtime = runtime

    def doctor(self) -> dict[str, Any]:
        status = self.runtime.status()
        status["local_model"] = local_model_status()
        return detect_capabilities(status, paths=self.paths, settings=self.settings)

    def start_local(self) -> dict[str, Any]:
        """Start owned local services and wait briefly for a real health result."""
        import time

        started = {"mcp": self.runtime.start_mcp()}
        if self.settings.autostart_relay:
            started["relay"] = self.runtime.start_relay()
        doctor = self.doctor()
        deadline = time.monotonic() + 6
        while not doctor["ready"] and started["mcp"].get("ok") and time.monotonic() < deadline:
            time.sleep(0.2)
            doctor = self.doctor()
        return {"ok": doctor["ready"], "started": started, "doctor": doctor}

    def connect_openai(
        self, tunnel_id: str, runtime_key: str, *, approved: bool = False
    ) -> dict[str, Any]:
        if not approved:
            raise PermissionError("OpenAI connection requires explicit consent")
        # Must not log, print, return or persist the plaintext credential.
        configure_tunnel(self.paths, tunnel_id, runtime_key)
        result = self.runtime.connect_and_verify(timeout_s=15)
        return {
            "ok": any(
                item.get("id") == "tunnel" and item.get("ok")
                for item in result.get("checks", ())
            ),
            "onboarding": result.get("chatgpt_onboarding", {}),
        }

    def install_optional(self, name: str, *, approved: bool = False) -> dict[str, Any]:
        if name not in {"git", "docker", "ollama"}:
            raise ValueError("only Git, Docker and Ollama can be installed on demand")
        if not approved:
            raise PermissionError("installing host dependencies requires user approval")
        from .installer import install_winget_package
        if name == "git" and shutil.which("git"):
            return {"ok": True, "already_installed": True}
        if name == "docker" and shutil.which("docker"):
            return {"ok": True, "already_installed": True,
                    "note": "Docker daemon health must be verified separately"}
        if name == "ollama" and _ollama_binary():
            return {"ok": True, "already_installed": True}
        package = {
            "git": "Git.Git", "docker": "Docker.DockerDesktop", "ollama": "Ollama.Ollama",
        }[name]
        return install_winget_package(package)

    def install_local_model(self, *, approved: bool = False) -> dict[str, Any]:
        """Download only the vetted starter model after explicit consent."""
        if not approved:
            raise PermissionError("local model download requires approval")
        binary = _ollama_binary()
        if not binary:
            return {"ok": False, "reason": "install_ollama_first"}
        try:
            result = subprocess.run(
                [binary, "pull", STARTER_LOCAL_MODEL],
                capture_output=True, text=True, check=False, timeout=900,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "reason": type(exc).__name__}
        return {
            "ok": result.returncode == 0,
            "model": STARTER_LOCAL_MODEL,
            "detail": (result.stderr or result.stdout or "")[-350:],
        }

    def prepare_workspace(
        self, folder: Path | None = None, *, approved: bool = False,
        permissions: tuple[str, ...] = ("read",)
    ) -> str:
        if folder is None:
            return str(first_workspace(self.paths, self.settings))
        return grant_workspace(
            self.paths, self.settings, folder,
            approved=approved, permissions=permissions,
        )

    def needs_openai_connection(self) -> bool:
        return not bool(load_tunnel_config(self.paths))
