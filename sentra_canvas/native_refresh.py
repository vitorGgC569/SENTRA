"""Host-owned, fail-closed desktop frontend update.

No network downloads, dependency installs, service kills, or backend restarts.
The native-only bridge checks the central operation ledger and browser relay
before touching shared built assets. It never retries UNCERTAIN operations.
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import threading
import urllib.request
import json
import getpass

_REFRESH_LOCK = threading.Lock()
_BUSY_STATES = ("STARTING", "RUNNING", "WAITING_EXTERNAL", "QUEUED")


def frontend_source_mtime(root: Path) -> int:
    ui = root / "sentra_canvas" / "desktop_ui"
    paths = [ui / "package.json", ui / "vite.config.js", ui / "index.html",
             ui / "scripts" / "materialize.mjs"]
    for folder in (ui / "src", ui / "public"):
        if folder.is_dir():
            paths.extend(p for p in folder.rglob("*") if p.is_file() and
                         p.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".json", ".svg"})
    return max((p.stat().st_mtime_ns for p in paths if p.is_file()), default=0)


def code_reload_identity(root: Path) -> dict:
    """Frontend bundle freshness. Never an installed-product update."""
    status = version_status(root)
    if "installation_id" in status:
        raise RuntimeError("code reload must not carry an installation id")
    return {"kind": "code_reload", "installation_id": None, "installed_update": False, **status}


def installed_update_identity(marker: dict) -> dict:
    """Installed Windows update identity. A frontend timestamp is a different operation."""
    if not isinstance(marker, dict):
        raise ValueError("installation marker required")
    installation_id = marker.get("installation_id")
    if (not isinstance(installation_id, str) or not installation_id
            or "frontend_source_time_ns" in marker or "frontend_stale" in marker):
        raise ValueError("installed update is not a code reload")
    return {"kind": "installed_update", "installation_id": installation_id,
            "code_reload": False, "frontend_stale": None}


def assert_distinct_maintenance(code: dict, installed: dict, dot: dict) -> None:
    if code.get("kind") == installed.get("kind") or code.get("kind") == dot.get("kind"):
        raise RuntimeError("code reload, installed update, and Dot window collapsed")
    if code.get("installation_id") or installed.get("code_reload") or dot.get("installation_id"):
        raise RuntimeError("maintenance identities crossed")
    if code.get("kind") != "code_reload" or installed.get("kind") != "installed_update" or dot.get("kind") != "dot_identity":
        raise RuntimeError("maintenance identity mismatch")


def version_status(root: Path) -> dict:
    root = Path(root).resolve(strict=True)
    bundle = root / "sentra_canvas" / "static" / "desktop-assets" / "desktop.js"
    built = bundle.stat().st_mtime_ns if bundle.is_file() else 0
    source = frontend_source_mtime(root)
    return {"frontend_stale": source > built, "bundle_present": bool(built),
            "frontend_source_time_ns": source, "bundle_time_ns": built}


def quiescence(root: Path, *, relay_url="http://127.0.0.1:8765/health") -> dict:
    # Any failure is unknown, not an invitation to restart.
    from sentra_mcp.services.control_store import create_control_plane_store
    store = create_control_plane_store(root / ".sentra", backend="configured")
    # A frontend-only refresh touches this Canvas user's UI, not other
    # persistent sessions in the host's shared central operation ledger.
    owner = "canvas:" + getpass.getuser().casefold()
    with store.connect("durable") as db:
        active = db.execute(
            "SELECT COUNT(*) FROM operations WHERE owner=? AND state IN (?,?,?,?)",
            (owner, *_BUSY_STATES)).fetchone()[0]
        unrelated = db.execute(
            "SELECT COUNT(*) FROM operations WHERE owner<>? AND state IN (?,?,?,?)",
            (owner, *_BUSY_STATES)).fetchone()[0]
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            relay_url, timeout=4) as response:
        relay = json.load(response)
    if relay.get("ok") is not True:
        raise RuntimeError("Estado do relay não confirmado")
    queued = relay.get("queued")
    leased = relay.get("leased")
    if not isinstance(queued, int) or not isinstance(leased, int):
        raise RuntimeError("Fila do relay sem contagens verificáveis")
    # Browser relay can be idle while a ChatGPT Web turn is active.
    return {"active_operations": active, "other_owners_unfinished": unrelated, "relay_queued": queued, "relay_leased": leased,
            "safe": active == 0 and queued == 0 and leased == 0}


def check(root: Path) -> dict:
    result = version_status(root)
    try:
        result.update(quiescence(Path(root).resolve()))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        result.update(safe=False, reason="Não foi possível verificar a segurança dos serviços: " + type(exc).__name__)
    return result


def apply(root: Path, *, runner=None) -> dict:
    """Build only a changed frontend, after two observations and under a mutex.

    The caller is responsible for reloading its own WebView after receiving
    'built'. The controller never restarts an active relay, backend, VM or CLI.
    """
    root = Path(root).resolve(strict=True)
    if not _REFRESH_LOCK.acquire(blocking=False):
        return {"status": "busy", "reason": "Outra atualização está em andamento"}
    try:
        before = check(root)
        if not before.get("safe"):
            return {"status": "blocked", **before}
        if not before["frontend_stale"]:
            return {"status": "unchanged", **before}
        executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if runner is None and not executable:
            return {"status": "blocked", "reason": "npm não está disponível"}
        ui = root / "sentra_canvas" / "desktop_ui"
        if not (ui / "node_modules").is_dir():
            return {"status": "blocked", "reason": "Dependências de build ausentes"}
        second = check(root)
        if not second.get("safe") or second["frontend_source_time_ns"] != before["frontend_source_time_ns"]:
            return {"status": "blocked", "reason": "Alteração concorrente ou operações ativas; não compilar"}
        invoke = runner or subprocess.run
        try:
            completed = invoke([executable or "npm", "run", "build"], cwd=ui,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return {"status": "failed", "reason": "Compilação não confirmada"}
        if completed.returncode:
            return {"status": "failed", "reason": "Compilação falhou; assets antigos preservados quando possível"}
        after = version_status(root)
        if after["frontend_stale"] or after["frontend_source_time_ns"] != before["frontend_source_time_ns"]:
            return {"status": "blocked", "reason": "Fonte alterada durante o build; recarregamento adiado"}
        safe_after = check(root)
        if not safe_after.get("safe"):
            return {"status": "built_deferred", "reason": "Operação começou durante o build; não recarregar",
                    **safe_after}
        return {"status": "built", "frontend_stale": False}
    finally:
        _REFRESH_LOCK.release()
