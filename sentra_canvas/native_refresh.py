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


def _backend_source_mtime(root: Path) -> int:
    """Version detector for Python services, independent of the React bundle."""
    folders = ("sentra_canvas", "sentra_executors", "sentra_runtime", "sentra_mcp",
               "sentra_core", "sentra_federation", "sentra_remote")
    return max((p.stat().st_mtime_ns for name in folders
                for p in (root / name).rglob("*.py") if p.is_file()
                and "__pycache__" not in p.parts), default=0)


def check_all(root: Path) -> dict:
    """Read-only status of the *local checkout*, not an installed release."""
    root = Path(root).resolve(strict=True)
    base = check(root)
    exe = root / "dist" / "sentra-canvas.exe"
    built = exe.stat().st_mtime_ns if exe.is_file() else 0
    source = _backend_source_mtime(root)
    return {
        **base,
        "kind": "local_checkout_update",
        "backend_source_time_ns": source,
        "native_executable_time_ns": built,
        "native_executable_stale": not built or source > built,
        "installed_update_available": False,
        "installed_version_changed": False,
        "external_services_unchanged": True,
        "reason": base.get("reason") or (
            "Código local pode ser recompilado e o broker reiniciado. A versão instalada "
            "exige release/Setup assinados e não é atualizada por este fluxo."),
    }



def available_local_update(root: Path, *, running_backend_source_ns: int) -> dict:
    """Read-only code-change trigger. Not an installed-release or download offer.

    The backend baseline belongs to the running native window; a stale signed
    EXE alone must not display an install button the application cannot fulfill.
    This method never touches the control plane or active operations.
    """
    root = Path(root).resolve(strict=True)
    frontend = version_status(root)
    current_backend = _backend_source_mtime(root)
    changed_backend = current_backend > running_backend_source_ns
    changed_frontend = bool(frontend["frontend_stale"])
    available = changed_frontend or changed_backend
    return {
        "kind": "local_checkout_code",
        "available": available,
        "frontend_stale": changed_frontend,
        "backend_changed": changed_backend,
        "action": ("apply_full_updates" if changed_backend
                   else "apply_code_updates" if changed_frontend else None),
        "revision": f'{frontend["frontend_source_time_ns"]}:{current_backend}',
        "installed_update_available": False,
        "requires_confirmation": True,
        "reason": (
            "Código dos serviços locais mudou; atualização coordenada pode exigir reinício seguro do Canvas."
            if changed_backend else
            "Mudanças da interface prontas para compilação local."
            if changed_frontend else
            "O código local já está atualizado para esta janela."
        ),
    }

def apply_all(root: Path, *, restart_broker=True) -> dict:
    """Apply local React/Python changes without pretending to replace an installed EXE.

    This endpoint executes only in source mode. It never kills a CLI, VM,
    tunnel, MCP process, or in-flight operation. Broker shutdown is through
    the authenticated owner API and followed by a *verified* new owner.
    """
    import sys
    import time

    root = Path(root).resolve(strict=True)
    if getattr(sys, "frozen", False):
        return {"status": "blocked", "installed_version_changed": False,
                "reason": "Aplicação empacotada: atualização integral exige release validado e helper externo."}
    before = check_all(root)
    if not before.get("safe"):
        return {"status": "blocked", **before}
    frontend = "unchanged"
    if before["frontend_stale"]:
        built = apply(root)
        frontend = built["status"]
        if frontend not in {"built", "unchanged"}:
            return {"status": "blocked", "frontend": frontend,
                    "installed_version_changed": False, "reason": built.get("reason") or frontend}
    latest = check_all(root)
    if not latest.get("safe"):
        return {"status": "blocked", "frontend": frontend,
                "installed_version_changed": False,
                "reason": "Operações surgiram após o build; broker preservado."}
    if not restart_broker:
        return {"status": "local_code_ready", "frontend": frontend,
                "broker_restarted": False, "reload_required": True,
                "installed_version_changed": False}
    from .broker import read_endpoint, connect_or_start
    state = root / ".sentra" / "canvas"
    old = read_endpoint(state)
    if old is None:
        return {"status": "blocked", "frontend": frontend, "broker_restarted": False,
                "installed_version_changed": False,
                "reason": "Broker proprietário não pôde ser autenticado; nenhum processo foi encerrado."}
    # Never restart the verified owner if central operations or relay became busy.
    if not check_all(root).get("safe"):
        return {"status": "blocked", "frontend": frontend, "broker_restarted": False,
                "installed_version_changed": False, "reason": "Novas operações ativas; preservar broker."}
    try:
        canvas_idle = _canvas_runtime_idle(root)
    except (OSError, RuntimeError, ValueError, KeyError, TimeoutError):
        canvas_idle = False
    if not canvas_idle:
        return {"status": "blocked", "frontend": frontend, "broker_restarted": False,
                "installed_version_changed": False,
                "reason": "Sessões/terminais ativos ou inventário ConPTY não verificável; preservar broker."}
    accepted = old.request("/api/runtime/shutdown", {"confirm": True})
    if accepted.get("requested") is not True:
        return {"status": "blocked", "frontend": frontend, "broker_restarted": False,
                "installed_version_changed": False, "reason": "Broker recusou o encerramento ordenado."}
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if read_endpoint(state) is None:
            break
        time.sleep(.1)
    else:
        return {"status": "uncertain", "frontend": frontend, "broker_restarted": False,
                "installed_version_changed": False,
                "reason": "Broker anterior não encerrou; nenhum segundo proprietário foi iniciado."}
    # The already-open WebView uses this loopback URL. Rebind the *same*
    # verified port, otherwise window.location.reload would point at a dead
    # server even though a new broker appeared on another random port.
    import socket
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(.25)
            if probe.connect_ex(("127.0.0.1", old.server_port)) != 0:
                break
        time.sleep(.1)
    else:
        return {"status": "uncertain", "frontend": frontend, "broker_restarted": False,
                "installed_version_changed": False,
                "reason": "Porta anterior permanece ocupada; recarga suspensa."}
    try:
        current = connect_or_start(root, state_dir=state, port=old.server_port, timeout=20)
        identity_changed = current.runtime_id != old.runtime_id
        healthy = (current.server_port == old.server_port
                   and current.request("/api/health").get("ok") is True)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"status": "uncertain", "frontend": frontend, "broker_restarted": False,
                "installed_version_changed": False,
                "reason": "Broker não comprovou reinício: " + type(exc).__name__}
    if not (identity_changed and healthy):
        return {"status": "uncertain", "frontend": frontend, "broker_restarted": False,
                "installed_version_changed": False,
                "reason": "Prova de troca de proprietário ausente."}
    return {"status": "local_code_updated", "kind": "local_checkout_update",
            "frontend": frontend, "broker_restarted": True,
            "reload_required": True, "installed_version_changed": False,
            "native_executable_stale": latest["native_executable_stale"],
            "external_services_unchanged": True,
            "reason": "React e broker atualizados. Executável instalado, CLI, MCP, túnel e VMs "
                      "permanecem inalterados até um release integral homologado."}


def _canvas_runtime_idle(root: Path) -> bool:
    """Independent ConPTY/task inventory; ledger-idle alone is insufficient."""
    from .broker import read_endpoint
    from urllib.parse import urlencode

    endpoint = read_endpoint(root / ".sentra" / "canvas")
    if endpoint is None:
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:" + str(endpoint.server_port)

    def get(path):
        request = urllib.request.Request(base + path, headers={
            "Authorization": "Bearer " + endpoint.secret})
        with opener.open(request, timeout=5) as response:
            return json.loads(response.read(2_000_000))

    workspaces = get("/api/workspaces")
    if not isinstance(workspaces, list) or len(workspaces) > 250:
        return False
    for item in workspaces:
        ws = item.get("id") if isinstance(item, dict) else None
        if not isinstance(ws, str) or not (1 <= len(ws) <= 96) or not ws.isalnum():
            return False
        data = get("/api/workspace?" + urlencode({"ws": ws}))
        if not isinstance(data, dict):
            return False
        for table in ("terminals", "tasks"):
            rows = data.get(table)
            if not isinstance(rows, list):
                return False
            if any(not isinstance(row, dict) or
                   str(row.get("status", "")).lower() in {
                       "running", "starting", "queued", "waiting_external"} for row in rows):
                return False
    return True
