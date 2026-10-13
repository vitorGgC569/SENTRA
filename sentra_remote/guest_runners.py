"""Concrete guest runners for Vitra-owned lifecycle operations.

The lifecycle planners (`coordinated_backup`, `optional_providers`,
`postgres_migration`, `sidecar_manifests`) accept injected callables so the
central host stays the authority. This module provides the REAL default
runners the host can bind — no stubs, no fixtures, no simulation:

- winget install runner (real `winget install --exact`, no shell).
- Binary health probes (`git --version`, `docker info`, Ollama binary/tag API).
- `pg_dump` / `pg_restore` CLI runners (DSN supplied by the host call, never
  read from disk or logged here).
- Sidecar file-hash verifier (re-hashes listed files, returns bool).

Every runner fails explicitly when its prerequisite binary is absent and
never fabricates readiness. Effects (install/repair/remove/restore) are
only invoked after the planner's explicit user approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA = 1
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    from .lifecycle_effects import checkpoint_effect
    checkpoint_effect()
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout,
        check=False, creationflags=_NO_WINDOW,
    )


def winget_runner(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Real winget runner for install/repair/remove of pinned packages."""
    if action not in {"install", "repair", "remove"}:
        raise ValueError("winget runner supports install/repair/remove only")
    package = str((params.get("pin") or {}).get("package") or params.get("package") or "").strip()
    if not package or len(package) > 128:
        raise ValueError("winget runner requires a pinned package id")
    if shutil.which("winget") is None:
        raise ValueError("provider install unavailable: winget is not on PATH")
    if action == "remove":
        argv = ["winget", "uninstall", "--exact", "--id", package,
                "--disable-interactivity"]
    else:
        argv = ["winget", "install", "--exact", "--id", package,
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity"]
        version = str((params.get("pin") or {}).get("pin_version") or "")
        if not version:
            raise ValueError("winget install requires an exact release pin")
        argv += ["--version", version]
    try:
        result = _run(argv, timeout=900)
    except subprocess.TimeoutExpired:
        raise RuntimeError('provider installer outcome uncertain; observe without resending') from None
    except OSError as exc:
        return {"schema": SCHEMA, "ok": False, "reason": type(exc).__name__}
    return {"schema": SCHEMA, "ok": result.returncode == 0,
            "returncode": result.returncode,
            "detail": (result.stderr or result.stdout)[-1000:]}


def probe_git() -> dict[str, Any]:
    try:
        result = _run(["git", "--version"], timeout=10)
    except FileNotFoundError:
        return {"installed": False, "detail": "git CLI not found"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"installed": False, "detail": type(exc).__name__}
    if result.returncode != 0:
        return {"installed": True, "ready": False, "detail": "git CLI failed"}
    return {"installed": True, "ready": True, "detail": result.stdout.strip()[:160]}


def probe_docker() -> dict[str, Any]:
    try:
        result = _run(["docker", "info", "--format", "{{json .ServerVersion}}"], timeout=10)
    except FileNotFoundError:
        return {"installed": False, "detail": "docker CLI not found"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"installed": False, "detail": type(exc).__name__}
    raw = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return {"installed": True, "ready": False,
                "detail": (raw or "docker daemon unavailable")[:160]}
    return {"installed": True, "ready": True,
            "detail": f"docker daemon ready ({raw.strip(chr(34))})"[:160]}


def _ollama_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidate = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def probe_ollama() -> dict[str, Any]:
    binary = _ollama_binary()
    if binary is None:
        return {"installed": False, "detail": "ollama binary not found"}
    try:
        from .lifecycle_effects import checkpoint_effect
        checkpoint_effect()
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return {"installed": True, "ready": False,
                "detail": "ollama installed but daemon not answering loopback"}
    items = payload.get("models") if isinstance(payload, dict) else None
    names = [str(i.get("name")) for i in (items or []) if isinstance(i, dict) and i.get("name")]
    return {"installed": True, "ready": bool(names),
            "detail": f"ollama daemon with {len(names)} model(s)" if names
                      else "ollama daemon has no models"}


def provider_runner(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Host-bindable runner dispatch for optional providers (real effects)."""
    name = str(params.get("provider") or "").strip()
    if action == 'configure':
        from .managed_providers import payload_runner
        return payload_runner(name, action)
    if name in {"git", "docker", "ollama"}:
        if action in {"health", "renew"}:
            from .managed_providers import load_registration, registration
            previous = load_registration(name)
            if previous and previous['state'] in {'revoked', 'removed'}:
                return {'ok': False, 'installed': False, 'state': previous['state']}
            probe = {"git": probe_git, "docker": probe_docker, "ollama": probe_ollama}[name]()
            if action == 'renew':
                registration(name, state='ready' if probe.get('ready') is True else 'degraded',
                    configuration=(previous or {}).get('config', {}))
            return {"schema": SCHEMA, "ok": bool(probe.get("ready")),
                    "action": action, **probe}
        if action == "recovery":
            # Recovery observes first. It never repeats an uncertain installer.
            probe = {"git": probe_git, "docker": probe_docker, "ollama": probe_ollama}[name]()
            return {"schema": SCHEMA, "action": action, "ok": bool(probe.get("ready")), **probe}
        if action == "revoke":
            from .managed_providers import registration, load_registration
            previous = load_registration(name)
            return registration(name, state="revoked", configuration=(previous or {}).get('config', {}))
        if action == "remove":
            from .optional_providers import PROVIDERS
            params = {**params, "pin": PROVIDERS[name]}
        result = winget_runner(action, params)
        if result.get('ok') is True:
            from .managed_providers import registration
            registration(name, state='removed' if action == 'remove' else 'degraded',
                configuration={'pin': params.get('pin', {})})
        return result
    if name in {"tunnel-client", "pdfium", "web-models", "electron"}:
        from .managed_providers import payload_runner
        return payload_runner(name, action)
    raise ValueError(f"no runner for provider action: {name}/{action}")


def _pg_binaries() -> tuple[str | None, str | None]:
    return shutil.which("pg_dump"), shutil.which("pg_restore")


def postgres_dump_runner(database: str, dest_dir: Path, *, dsn: str = "") -> Path:
    """Real pg_dump snapshot. DSN comes from the host call; never logged."""
    pg_dump, _ = _pg_binaries()
    if pg_dump is None:
        raise ValueError("postgres backup unavailable: pg_dump not on PATH")
    name = (database or "").strip()
    if not name or len(name) > 64:
        raise ValueError("postgres database name required")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    target = (dest / (name + ".dump")).absolute()
    if target.exists():
        raise ValueError("postgres dump target already exists")
    argv = [pg_dump, "--format=custom", "--file", str(target)]
    if dsn:
        argv += ["--dbname", dsn]
    else:
        argv += [name]
    try:
        result = _run(argv, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        target.unlink(missing_ok=True)
        raise ValueError(f"pg_dump failed: {type(exc).__name__}") from None
    if result.returncode != 0 or not target.is_file():
        target.unlink(missing_ok=True)
        raise ValueError("pg_dump exited with "
                         f"{result.returncode}; backup refused")
    return target


def postgres_restore_runner(database: str, dump_file: Path, *, dsn: str = "") -> None:
    """Real pg_restore. DSN comes from the host call; never logged."""
    _, pg_restore = _pg_binaries()
    if pg_restore is None:
        raise ValueError("postgres restore unavailable: pg_restore not on PATH")
    name = (database or "").strip()
    dump = Path(dump_file).resolve(strict=True)
    if not name or dump.is_symlink() or not dump.is_file():
        raise ValueError("postgres restore requires a database name and a dump file")
    argv = [pg_restore, "--clean", "--if-exists", "--dbname", dsn or name, str(dump)]
    try:
        result = _run(argv, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"pg_restore failed: {type(exc).__name__}") from None
    if result.returncode != 0:
        raise ValueError(f"pg_restore exited with {result.returncode}; manual review required")


def verify_sidecar_files(manifest: dict[str, Any], *, root: Path) -> bool:
    """Real file-hash verifier for owner-published sidecar manifests.

    Re-hashes every listed file under root and compares with the manifest.
    This verifies integrity/provenance of the bytes on disk; publisher
    identity (PKI/thumbprint) is verified separately at release sealing and
    is NEVER simulated here.
    """
    if not isinstance(manifest, dict):
        return False
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return False
    base = Path(root).resolve(strict=True)
    try:
        for entry in files:
            if not isinstance(entry, dict):
                return False
            relative = str(entry.get("path") or "")
            expected = str(entry.get("sha256") or "").lower()
            if not relative or len(expected) != 64:
                return False
            target = (base / Path(relative)).absolute()
            if (target.is_symlink() or target.resolve() != target
                    or not target.is_relative_to(base) or not target.is_file()):
                return False
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected:
                return False
    except OSError:
        return False
    return True
