"""Interactive/self-contained Windows installer for SENTRA Desktop."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path
from inspect import signature as _install_signature
from typing import TYPE_CHECKING, Any, Callable, TypedDict

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk

from sentra_version import PRODUCT_VERSION

from .local_runtime import LocalRuntime
from .codex_setup import configure_codex
from .onboarding import OPENAI_API_KEYS_URL, OPENAI_TUNNELS_URL
from .openai_auto_setup import authorize_installer_enrollment
from .windows_paths import filesystem_path as _filesystem_path
from .product import (
    ProductPaths,
    ProductSettings,
    configure_tunnel,
    ensure_browser_token,
)

TUNNEL_VERSION = "0.0.14"
TUNNEL_URL = (
    "https://github.com/openai/tunnel-client/releases/download/"
    "v0.0.14/tunnel-client-v0.0.14-windows-amd64.zip"
)
TUNNEL_SHA256 = "784ab8da7b5a88f0109f1fd8aaf0a1c86067430b896dddf307ef7e3cc49fa1a5"
DEFAULT_MANIFEST_URL = (
    "https://github.com/vitorGgC569/SENTRA/releases/latest/download/release-manifest.json"
)
INSTALL_MARKER = ".sentra-install.json"
# Frozen components can take tens of seconds on a clean, memory-limited VM.
# Keep health/instance/policy checks authoritative, with a bounded cold-start wait.
SERVICE_STARTUP_TIMEOUT_S = 120.0

ProgressCallback = Callable[[str, int], None]


def _display_ready(verification: dict[str, Any]) -> bool:
    return not verification.get("display_required") or ((verification.get("status") or {}).get("display") or {}).get("ok") is True


def _installation_ready(verification: dict[str, Any], *, openai_required: bool = True) -> bool:
    """Setup requires the GPT-WEB tunnel; local health alone is not completion."""
    if not _display_ready(verification):
        return False
    local_ready = bool(verification.get("core_ready") and not verification.get("onboarding_required"))
    if not openai_required:
        # Fresh machines have no account enrollment yet. Local service health
        # must allow Setup to reach that step instead of waiting for itself.
        return bool(verification.get("core_ready"))
    status = verification.get("status") or {}
    web = status.get('web_models') or {}
    if verification.get('web_models_required') and not all(web.get(key) is True for key in ('payload_complete', 'ready', 'catalog_ready', 'turn_ready')):
        return False
    return bool(local_ready and (verification.get("chatgpt_onboarding") or {}).get("ready")
                and (status.get("mcp") or {}).get("ok")
                and (status.get("tunnel") or {}).get("ok")
                and not (status.get("tunnel") or {}).get("reauth_required")
                and ("codex_plugin" not in verification or
                     (verification.get("codex_plugin") or {}).get("ready") is True))


def _verify_installed_display(verification: dict[str, Any], install_dir: Path) -> None:
    from .display_probe import probe_installed_display
    display = probe_installed_display(install_dir)
    verification["display_required"] = True
    verification["status"] = {**(verification.get("status") or {}), "display": display}
    verification["checks"] = [*(verification.get("checks") or []),
                              {"id": "display", "required": True, "ok": display.get("ok") is True}]


def _friendly_install_error(exc: BaseException) -> str:
    """Translate common setup failures into a concrete next action."""
    detail = str(exc).strip() or exc.__class__.__name__
    lowered = detail.lower()
    if "credential_protection_unavailable" in lowered:
        action = "A proteção de credenciais do Windows não está disponível nesta sessão. Execute o Setup na sessão do usuário conectado. A instalação anterior foi preservada."
    elif "sha-256" in lowered or "checksum" in lowered:
        action = "Baixe novamente o instalador oficial. A verificação de integridade falhou; nenhum arquivo não verificado será instalado."
    elif "payload" in lowered and ("missing" in lowered or "stale" in lowered):
        action = "Este pacote está incompleto ou desatualizado. Use uma versão completa do SENTRA Setup. A instalação anterior foi preservada."
    elif "installed process" in lowered or "another installation" in lowered:
        action = "O SENTRA ou outro instalador ainda está em uso. Conclua a atividade e tente novamente; suas sessões não foram encerradas."
    elif "tunnel" in lowered and ("runtime" in lowered or "api key" in lowered):
        action = "Use Conectar minha conta automaticamente pelo Edge para configurar e verificar a conexão."
    elif "workspace" in lowered and "exist" in lowered:
        action = "Deixe Workspace inicial vazio para criar um projeto automaticamente, ou selecione uma pasta existente."
    elif "permission" in lowered or "access is denied" in lowered:
        action = "O Windows impediu o acesso à pasta. Use o destino sugerido no seu perfil e tente novamente."
    elif "url" in lowered or "network" in lowered or "timed out" in lowered:
        action = "Verifique a conexão e tente novamente. Downloads completos e verificados são reutilizados automaticamente."
    else:
        action = "Abra novamente o Setup para reparar. O progresso fica salvo e seus projetos são preservados."
    return f"{detail}\n\nComo continuar: {action}"


PRODUCTS = (
    "sentra-launcher.exe",
    "sentra-mcp.exe", "sentra-browser-relay.exe", "sentra-desktop.exe",
    "sentra-human.exe", "sentra-human-worker.exe", "sentra.exe",
    "sentra-agent.exe", "sentra-diagnostics.exe", "sentra-admin.exe",
    "sentra-update-helper.exe", "sentra-oma.exe", "sentra-cli.exe", "sentra-canvas.exe",
)

def payload_root() -> Path:
    if getattr(sys, "frozen", False):
        embedded = Path(getattr(sys, "_MEIPASS")) / "payload"
        return embedded if embedded.is_dir() else Path(sys.executable).parent / "payload"
    return Path(__file__).resolve().parents[1] / "dist"


def extension_source() -> Path:
    if getattr(sys, "frozen", False):
        embedded = Path(getattr(sys, "_MEIPASS")) / "edge_extension"
        return embedded if embedded.is_dir() else Path(sys.executable).parent / "edge_extension"
    return Path(__file__).resolve().parents[1] / "edge_extension"


def docs_source() -> Path:
    if getattr(sys, "frozen", False):
        embedded = Path(getattr(sys, "_MEIPASS")) / "docs"
        return embedded if embedded.is_dir() else Path(sys.executable).parent / "docs"
    return Path(__file__).resolve().parents[1] / "docs"


def _run(command: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def install_winget_package(package_id: str) -> dict[str, Any]:
    if not command_exists("winget"):
        return {"ok": False, "reason": "winget is not available"}
    result = _run([
        "winget", "install", "--exact", "--id", package_id,
        "--accept-package-agreements", "--accept-source-agreements",
        "--disable-interactivity",
    ])
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "detail": (result.stderr or result.stdout)[-1000:],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_tunnel_archive(cache: Path, archive: Path | None = None) -> Path:
    """Reuse verified bundled/cached bytes; retry only a download, never enrollment."""
    bundled = payload_root() / "prerequisites" / "tunnel-client.zip"
    selected = Path(archive).resolve() if archive else bundled if bundled.is_file() else None
    if selected is not None:
        if _sha256(selected) != TUNNEL_SHA256:
            raise ValueError("tunnel-client archive SHA-256 mismatch")
        return selected
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / ("tunnel-client-" + TUNNEL_SHA256 + ".zip")
    if target.is_file() and _sha256(target) == TUNNEL_SHA256:
        return target
    import urllib.error
    for attempt in range(3):
        fd, name = tempfile.mkstemp(prefix="tunnel-", suffix=".part", dir=cache)
        pending = Path(name)
        try:
            with os.fdopen(fd, "wb") as out:
                req = urllib.request.Request(TUNNEL_URL, headers={"User-Agent": "SENTRA-Installer/1.0"})
                with urllib.request.urlopen(req, timeout=60) as response:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 128 * 1024 * 1024:
                            raise ValueError("tunnel-client archive exceeds size limit")
                        out.write(chunk)
            if _sha256(pending) != TUNNEL_SHA256:
                raise ValueError("tunnel-client archive SHA-256 mismatch")
            pending.replace(target)
            return target
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
        finally:
            pending.unlink(missing_ok=True)
    raise RuntimeError("tunnel download did not finish")


def download_tunnel_client(destination: Path, archive: Path | None = None) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="sentra-tunnel-"))
    try:
        cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SENTRA" / "Downloads"
        source = prepare_tunnel_archive(cache, archive)
        actual = _sha256(source)
        if actual != TUNNEL_SHA256:
            raise ValueError("tunnel-client archive SHA-256 mismatch")
        with zipfile.ZipFile(source) as package:
            members = package.infolist()
            executable = next(
                (item for item in members if Path(item.filename).name.lower() == "tunnel-client.exe"),
                None,
            )
            if executable is None:
                raise ValueError("tunnel-client.exe is missing from archive")
            with package.open(executable) as src, (destination / "tunnel-client.exe").open("wb") as dst:
                shutil.copyfileobj(src, dst)
            licenses = destination / "licenses" / "tunnel-client"
            licenses.mkdir(parents=True, exist_ok=True)
            for item in members:
                base = Path(item.filename).name
                if base.upper() in {"LICENSE", "NOTICE"} or base.endswith((".spdx.json", "-licenses.txt")):
                    with package.open(item) as src, (licenses / base).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        return {
            "ok": True,
            "version": TUNNEL_VERSION,
            "sha256": actual,
            "path": str(destination / "tunnel-client.exe"),
        }
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _owned_tree_files(folder: Path, prefix: str) -> list[str]:
    extended = Path(_filesystem_path(folder))
    return [(Path(prefix) / file.relative_to(extended)).as_posix()
            for file in extended.rglob("*") if file.is_file()]


def _copy_product_files(install_dir: Path) -> list[str]:
    source = payload_root()
    if not source.is_dir():
        raise FileNotFoundError(f"installer payload missing: {source}")
    install_dir.mkdir(parents=True, exist_ok=True)
    support_files = []
    for name in PRODUCTS:
        candidate = source / name
        if not candidate.is_file():
            raise FileNotFoundError(f"release payload missing {name}")
        shutil.copy2(_filesystem_path(candidate), _filesystem_path(install_dir / name))
        from .onedir import copy_support
        support_files.extend(copy_support(source, install_dir, name))
    ext_source = extension_source()
    if not ext_source.is_dir():
        raise FileNotFoundError("Edge extension payload is missing")
    target = install_dir / "edge_extension"
    shutil.copytree(_filesystem_path(ext_source), _filesystem_path(target), dirs_exist_ok=True)
    web_source = source / "web-models" / "win-unpacked"
    if not (web_source / "Codex Web GPT.exe").is_file() or not (web_source / "resources" / "runtime" / "manifest.json").is_file():
        raise FileNotFoundError("packaged Electron Web Models payload is missing")
    if not (source / "web-models" / "licenses" / "codex-chatgpt-web" / "LICENSE").is_file():
        raise FileNotFoundError("codex-chatgpt-web license notice is missing")
    if not (source / "web-models" / "integration-build.json").is_file():
        raise FileNotFoundError("Web Models integration build metadata is missing")
    web_target = (install_dir / "web-models").resolve()
    if not web_target.is_relative_to(install_dir.resolve()):
        raise ValueError("Web Models install target escaped install directory")
    shutil.copytree(_filesystem_path(source / "web-models"), _filesystem_path(web_target), dirs_exist_ok=True)

    # The optional Electron view is not a second control plane. Only the
    # staged, fingerprinted renderer is copied, never node_modules/npm hooks.
    electron_source = source / "sentra-electron"
    if electron_source.exists():
        from scripts.commander.stage_electron import validate_electron_payload
        validate_electron_payload(electron_source)
        electron_target = (install_dir / "sentra-electron").resolve()
        if not electron_target.is_relative_to(install_dir.resolve()):
            raise ValueError("Electron installation escaped product directory")
        shutil.copytree(_filesystem_path(electron_source), _filesystem_path(electron_target),
                        dirs_exist_ok=True)
        validate_electron_payload(electron_target)

    mobile_source = source / 'sentra-mobile'
    if mobile_source.exists():
        from scripts.commander.stage_mobile import validate_mobile_runtime
        validate_mobile_runtime(mobile_source)
        mobile_target = (install_dir / 'sentra-mobile').resolve()
        if not mobile_target.is_relative_to(install_dir.resolve()):
            raise ValueError('Mobile runtime installation escaped product directory')
        shutil.copytree(_filesystem_path(mobile_source), _filesystem_path(mobile_target), dirs_exist_ok=True)
        validate_mobile_runtime(mobile_target)

    terminal_source = source / 'sentra-terminal'
    if terminal_source.exists():
        from scripts.commander.stage_terminal import validate_terminal_runtime
        validate_terminal_runtime(terminal_source)
        terminal_target = (install_dir / 'sentra-terminal').resolve()
        if not terminal_target.is_relative_to(install_dir.resolve()):
            raise ValueError('Terminal runtime installation escaped product directory')
        shutil.copytree(_filesystem_path(terminal_source), _filesystem_path(terminal_target), dirs_exist_ok=True)
        validate_terminal_runtime(terminal_target)

    docs = docs_source()
    start_here = docs / "START_HERE.md"
    if not start_here.is_file():
        raise FileNotFoundError("SENTRA product education docs are missing START_HERE.md")
    if not (docs / "SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md").is_file():
        raise FileNotFoundError("SENTRA ChatGPT app and Canvas onboarding guide is missing")
    docs_target = (install_dir / "docs").resolve()
    if not docs_target.is_relative_to(install_dir.resolve()):
        raise ValueError("docs install target escaped install directory")
    shutil.copytree(_filesystem_path(docs), _filesystem_path(docs_target), dirs_exist_ok=True)

    if getattr(sys, "frozen", False):
        shutil.copy2(_filesystem_path(Path(sys.executable)), _filesystem_path(install_dir / "sentra-installer.exe"))
        from .onedir import copy_support
        support_files.extend(copy_support(Path(sys.executable).parent, install_dir, "sentra-installer.exe"))
    owned = list(PRODUCTS) + support_files
    runtime_source = source / 'runtime'
    if runtime_source.is_dir():
        shutil.copytree(_filesystem_path(runtime_source), _filesystem_path(install_dir / 'runtime'), dirs_exist_ok=True)
    runtime_record = source / 'runtime-components.json'
    if runtime_record.is_file():
        shutil.copy2(_filesystem_path(runtime_record), _filesystem_path(install_dir / runtime_record.name))
        owned.append(runtime_record.name)
    folders = [(ext_source, "edge_extension"), (source / "web-models", "web-models"),
               (runtime_source, "runtime"), (docs, "docs")]
    bridge_source = source / "prerequisites/browser-enrollment"
    bridge_target = install_dir / "browser-enrollment"
    if bridge_source.is_dir():
        shutil.copytree(_filesystem_path(bridge_source), _filesystem_path(bridge_target), dirs_exist_ok=True)
        folders.append((bridge_source, "browser-enrollment"))
    elif not getattr(sys, "frozen", False):
        from .enrollment_extension import stage_extensions
        stage_extensions(Path(__file__).parent / "enrollment_extension", bridge_target)
        folders.append((bridge_target, "browser-enrollment"))
    else:
        raise FileNotFoundError("packaged Setup DOM bridge is missing")
    registration_source = source / "prerequisites/codex-registration"
    if registration_source.exists():
        from .codex_registration_runtime import validate_registration_runtime
        validate_registration_runtime(registration_source)
        registration_target = install_dir / "runtime/codex-registration"
        shutil.copytree(_filesystem_path(registration_source), _filesystem_path(registration_target),
                        dirs_exist_ok=True)
        validate_registration_runtime(registration_target)
        folders.append((registration_source, "runtime/codex-registration"))
    if electron_source.exists():
        folders.append((electron_source, "sentra-electron"))
    if mobile_source.exists():
        folders.append((mobile_source, 'sentra-mobile'))
    if terminal_source.exists():
        folders.append((terminal_source, 'sentra-terminal'))
    for folder, prefix in folders:
        owned.extend(_owned_tree_files(folder, prefix))
    if getattr(sys, "frozen", False):
        owned.append("sentra-installer.exe")
    return owned


def check_install_payload(install_dir: Path | None = None) -> dict[str, Any]:
    from .installer_preflight import inspect_payload
    return inspect_payload(payload_root(), extension_source(), docs_source(), PRODUCTS,
                           version=PRODUCT_VERSION, require_manifest=bool(getattr(sys, "frozen", False)),
                           destination=install_dir)


def _write_install_marker(install_dir: Path, owned_files: list[str] | None = None) -> Path:
    marker = install_dir / INSTALL_MARKER
    existing_id = ""
    existing_owned = []
    if marker.is_file():
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing_id = str(existing.get("installation_id") or "")
                existing_owned = existing.get("owned_files", [])
        except (OSError, json.JSONDecodeError):
            existing_id = ""
    payload = {
        "product": "SENTRA Desktop",
        "version": PRODUCT_VERSION,
        "installation_id": existing_id or str(uuid.uuid4()),
        "installed_at": time.time(),
        "owned_files": sorted(set(existing_owned + (owned_files or []))),
    }
    temp = marker.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(marker)
    return marker


def _validate_sentra_install(install_dir: Path) -> dict[str, Any]:
    root = install_dir.expanduser().resolve()
    anchor = Path(root.anchor)
    if root == anchor or root == Path.home().resolve() or len(root.parts) < 3:
        raise ValueError("refusing unsafe install directory")
    marker = root / INSTALL_MARKER
    if not marker.is_file():
        raise ValueError("refusing to remove directory without SENTRA install marker")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("SENTRA install marker is unreadable") from exc
    if not isinstance(data, dict) or data.get("product") != "SENTRA Desktop":
        raise ValueError("invalid SENTRA install marker")
    return data


def _register_startup(install_dir: Path) -> None:
    if os.name != "nt":
        return
    import winreg
    command = f'"{install_dir / "sentra-desktop.exe"}" --hidden'
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
    ) as key:
        winreg.SetValueEx(key, "SENTRA Desktop", 0, winreg.REG_SZ, command)


def _unregister_startup(install_dir: Path | None = None) -> None:
    if os.name != "nt":
        return
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            if install_dir is not None:
                command,_=winreg.QueryValueEx(key,"SENTRA Desktop")
                expected='"'+str(Path(install_dir).resolve()/"sentra-desktop.exe")+'"'
                if not str(command).casefold().startswith(expected.casefold()):return
            winreg.DeleteValue(key, "SENTRA Desktop")
    except OSError:
        pass


def set_desktop_autostart(install_dir: Path, *, enabled: bool) -> None:
    """Control only the current user's SENTRA startup entry."""
    if enabled:
        launcher = Path(install_dir).expanduser().resolve() / "sentra-desktop.exe"
        if not launcher.is_file():
            raise FileNotFoundError("SENTRA Desktop executable is not installed")
        _register_startup(launcher.parent)
    else:
        _unregister_startup(install_dir)


def _normalize_windows_path_entry(value: str) -> str:
    return str(value or "").strip().strip('"').replace("/", "\\").rstrip("\\").casefold()


def _with_user_path_entry(current: str, install_dir: Path) -> tuple[str, bool]:
    entries = [item.strip() for item in str(current or "").split(";") if item.strip()]
    wanted = _normalize_windows_path_entry(str(install_dir))
    if any(_normalize_windows_path_entry(item) == wanted for item in entries):
        return ";".join(entries), False
    entries.append(str(install_dir))
    return ";".join(entries), True


def _without_user_path_entry(current: str, install_dir: Path) -> tuple[str, bool]:
    wanted = _normalize_windows_path_entry(str(install_dir))
    entries = [item.strip() for item in str(current or "").split(";") if item.strip()]
    kept = [item for item in entries if _normalize_windows_path_entry(item) != wanted]
    return ";".join(kept), len(kept) != len(entries)


def _broadcast_environment_change() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF,
            0x001A,
            0,
            "Environment",
            0x0002,
            2000,
            ctypes.byref(result),
        )
    except (AttributeError, OSError, TypeError, ValueError):
        # PATH persistence is already complete; notification is best-effort.
        pass


def _register_user_path(install_dir: Path) -> bool:
    if os.name != "nt":
        return False
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        try:
            current, value_type = winreg.QueryValueEx(key, "Path")
        except OSError:
            current, value_type = "", winreg.REG_EXPAND_SZ
        updated, changed = _with_user_path_entry(str(current), install_dir)
        if changed:
            if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                value_type = winreg.REG_EXPAND_SZ
            winreg.SetValueEx(key, "Path", 0, value_type, updated)
    if changed:
        _broadcast_environment_change()
    return changed


def _unregister_user_path(install_dir: Path) -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            try:
                current, value_type = winreg.QueryValueEx(key, "Path")
            except OSError:
                return False
            updated, changed = _without_user_path_entry(str(current), install_dir)
            if changed:
                if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    value_type = winreg.REG_EXPAND_SZ
                winreg.SetValueEx(key, "Path", 0, value_type, updated)
    except OSError:
        return False
    if changed:
        _broadcast_environment_change()
    return changed


def _desktop_deep_link_command(install_dir: Path) -> str:
    return f'"{install_dir / "sentra-desktop.exe"}" --open-url "%1"'


def _register_url_protocol(install_dir: Path) -> None:
    if os.name != "nt":
        return
    import winreg

    root_path = r"Software\Classes\sentra"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:SENTRA Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        root_path + r"\shell\open\command",
    ) as key:
        winreg.SetValueEx(
            key,
            "",
            0,
            winreg.REG_SZ,
            _desktop_deep_link_command(install_dir),
        )


def _unregister_url_protocol(install_dir: Path | None = None) -> None:
    if os.name != "nt":
        return
    import winreg
    if install_dir is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Classes\sentra\shell\open\command") as key:
                command,_=winreg.QueryValueEx(key,"")
                if str(command).casefold()!=_desktop_deep_link_command(Path(install_dir).resolve()).casefold():return
        except OSError:return

    for key_path in (
        r"Software\Classes\sentra\shell\open\command",
        r"Software\Classes\sentra\shell\open",
        r"Software\Classes\sentra\shell",
        r"Software\Classes\sentra",
    ):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            pass


def _register_uninstall(install_dir: Path) -> None:
    if os.name != "nt":
        return
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SENTRA Desktop"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        values = {
            "DisplayName": "SENTRA Desktop",
            "DisplayVersion": PRODUCT_VERSION,
            "Publisher": "SENTRA",
            "InstallLocation": str(install_dir),
            "DisplayIcon": str(install_dir / "sentra-canvas.exe"),
            "UninstallString": f'"{install_dir / "sentra-installer.exe"}" --uninstall --keep-config --install-dir "{install_dir}"',
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)


def _unregister_uninstall(install_dir: Path | None = None) -> None:
    if os.name != "nt":
        return
    import winreg
    if install_dir is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SENTRA Desktop") as key:
                location,_=winreg.QueryValueEx(key,"InstallLocation")
                if _normalize_windows_path_entry(str(location))!=_normalize_windows_path_entry(str(Path(install_dir).resolve())):return
        except OSError:return
    try:
        winreg.DeleteKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SENTRA Desktop",
        )
    except OSError:
        pass


def _stop_installed_processes(install_dir: Path) -> None:
    if os.name != "nt":
        return
    escaped = str(install_dir).replace("'", "''")
    current_pid = os.getpid()
    parent_pid = os.getppid()
    script = (
        f"$root=[IO.Path]::GetFullPath('{escaped}').TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar;"
        f"$selfPid={current_pid};$selfParent={parent_pid};"
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|"
        "Where-Object{$_.ProcessId -ne $selfPid -and $_.ProcessId -ne $selfParent "
        "-and $_.ExecutablePath -and "
        "$_.ExecutablePath.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)}|"
        "ForEach-Object{try{Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop}catch{}}"
    )
    _run(["powershell.exe", "-NoProfile", "-Command", script], timeout=30)


def _enable_web_models_autostart(paths: ProductPaths, install_dir: Path) -> dict[str, Any]:
    root = install_dir / "web-models"
    launcher = root / "win-unpacked" / "Codex Web GPT.exe"
    manifest = root / "win-unpacked" / "resources" / "runtime" / "manifest.json"
    if not launcher.is_file() or not manifest.is_file():
        return {
            "ok": False,
            "autostart": False,
            "reason": "web_models_payload_missing",
        }
    marker = paths.state_dir / "web-models-enabled"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("enabled\n", encoding="utf-8")
    return {
        "ok": True,
        "autostart": True,
        "marker": str(marker),
        "launcher": str(launcher),
    }


def install(**options) -> dict[str, Any]:
    """Validate/download before touching an existing installation, serialize, then apply."""
    from contextlib import nullcontext
    from .installation_lock import installation_lock
    install_dir = Path(options["install_dir"]).expanduser().resolve()
    # The coordinated update helper owns this same OS lock across its child.
    lock = nullcontext() if options.get("offline_handoff") is not None else installation_lock(install_dir)
    with lock:
        if (install_dir / INSTALL_MARKER).is_file():
            _validate_sentra_install(install_dir)
        elif install_dir.exists() and any(install_dir.iterdir()):
            raise ValueError("choose an empty install directory; destination contains files without SENTRA ownership")
        progress = options.get("progress")
        if progress:
            progress("Verificando os arquivos da instalação…", 2)
        preflight = check_install_payload(install_dir)
        if not preflight["ok"]:
            raise FileNotFoundError("installer payload missing: " + ", ".join(preflight["missing"]))
        if options.get("offline_handoff") is None:
            from .openai_auto_setup import verify_credential_protection
            # Check before downloads, ownership changes, copying or stopping
            # services. An offline update remains deferred to its restart user.
            verify_credential_protection()
        state = (Path(options["state_dir"]).expanduser().resolve() if options.get("state_dir")
                 else ProductPaths.default(install_dir).state_dir)
        if progress:
            progress("Preparando a conexão segura…", 4)
        options["tunnel_archive"] = prepare_tunnel_archive(state / "downloads", options.get("tunnel_archive"))
        state.mkdir(parents=True, exist_ok=True)
        journal = state / "installer-progress.json"

        def record(label, percent, *, status="running"):
            # Only fixed stage labels: credentials and provider output never enter this file.
            document = {"version": PRODUCT_VERSION, "stage": label, "percent": percent,
                        "status": status, "updated_at": time.time()}
            pending = journal.with_suffix(".tmp")
            pending.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            pending.replace(journal)
            if progress:
                progress(label, percent)

        options["progress"] = record
        try:
            result = _install_product(**options)
        except Exception:
            record("Instalação interrompida. Abra o instalador para reparar.", 0, status="failed")
            raise
        result["preflight"] = preflight
        ready = _installation_ready(result.get("connect_verify") or {}, openai_required=not options.get("local_only", False))
        deferred = bool(options.get("offline_handoff"))
        record("Atualização preparada" if deferred else "SENTRA instalado; contas Web podem ser conectadas no aplicativo" if options.get("local_only") and ready else "Túnel verificado; autorize o plugin no ChatGPT" if ready else "A configuração precisa de atenção",
               95 if ready else 85, status="deferred" if deferred else "account_authorization_pending" if ready else "needs_attention")
        return result


def _install_product(
    *,
    install_dir: Path,
    workspace: Path | None = None,
    profile: str | None = None,
    access_scope: str | None = None,
    tunnel_id: str = "",
    runtime_key: str = "",
    tunnel_archive: Path | None = None,
    install_git: bool = False,
    install_docker: bool = False,
    launch: bool = True,
    state_dir: Path | None = None,
    register_system: bool = True,
    mcp_port: int | None = None,
    relay_port: int | None = None,
    stop_after_doctor: bool = False,
    progress: ProgressCallback | None = None,
    offline_handoff: Path | None = None,
    local_only: bool = False,
) -> dict[str, Any]:
    install_dir = install_dir.expanduser().resolve()
    paths = (
        ProductPaths(install_dir, state_dir.expanduser().resolve())
        if state_dir is not None
        else ProductPaths.default(install_dir)
    )
    result: dict[str, Any] = {"version": PRODUCT_VERSION, "install_dir": str(install_dir)}
    from sentra_mcp.audit import AuditLogger
    audit = AuditLogger(paths.audit_log, component="installer")
    last_stage = None

    def notify(label: str, percent: int) -> None:
        nonlocal last_stage
        if label != last_stage:
            audit.emit("installation.stage", "ok", {
                "stage": label, "percent": percent, "version": PRODUCT_VERSION,
            })
            last_stage = label
        if progress is not None:
            progress(label, max(0, min(100, int(percent))))

    notify("Preparing installation", 5)
    if (install_dir / INSTALL_MARKER).is_file():
        _validate_sentra_install(install_dir)
        if offline_handoff is not None:
            from .app_exit_update import load_handoff
            load_handoff(offline_handoff, install_dir)
            if not offline_handoff.with_suffix('.claimed').is_file():
                raise PermissionError('offline Setup requires the helper single-use claim')
        else:
            # Re-running Setup must not kill a broker, terminal or VM session.
            # Live upgrades use the existing coordinated application-exit path.
            if os.name == "nt":
                from .app_exit_update import assert_installation_offline
                assert_installation_offline(install_dir)
    elif install_dir.exists() and any(install_dir.iterdir()):
        raise ValueError("choose an empty install directory; destination contains files without SENTRA ownership")
    if install_git and not command_exists("git"):
        result["git_install"] = install_winget_package("Git.Git")
    if install_docker and not command_exists("docker"):
        result["docker_install"] = install_winget_package("Docker.DockerDesktop")
    notify("Installing SENTRA components", 25)
    # Ownership is claimed only after the destination was proved empty or ours.
    # Persist it before copying so an interrupted first installation is repairable.
    install_dir.mkdir(parents=True, exist_ok=True)
    _write_install_marker(install_dir)
    owned_files = _copy_product_files(install_dir) or []
    result["install_marker"] = str(_write_install_marker(install_dir, owned_files))
    if local_only:
        # Repair a journal-proven global route left by older failed installers,
        # even when the owner postpones Web account setup. Never invent a
        # provider baseline or overwrite conflicting user changes.
        try:
            from sentra_model_gateway.gateway import GatewayConfig, LauncherSupervisor
            adapter = LauncherSupervisor(GatewayConfig(
                checkout=install_dir / "third_party/codex-chatgpt-web",
                launcher_executable=install_dir / "web-models/win-unpacked/Codex Web GPT.exe",
                state_root=paths.state_dir))
            recovery = adapter.route("recover-native")
            result["native_route_recovery"] = {"ok": True, "restored": recovery.get("nativeRouteRestored") is True}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            result["native_route_recovery"] = {"ok": False, "needs_review": True}
    result["web_models"] = ({"deferred": "account_setup_in_sentra"} if local_only
                            else _enable_web_models_autostart(paths, install_dir))
    notify("Installing secure tunnel client", 45)
    result["tunnel_client"] = download_tunnel_client(install_dir, tunnel_archive)
    tunnel_license_dir = install_dir / "licenses" / "tunnel-client"
    tunnel_license_files = _owned_tree_files(
        tunnel_license_dir, "licenses/tunnel-client"
    ) if tunnel_license_dir.is_dir() else []
    _write_install_marker(
        install_dir, owned_files + ["tunnel-client.exe"] + tunnel_license_files
    )
    notify("Applying local settings", 60)
    fresh_settings = not paths.settings.is_file()
    settings = ProductSettings.load(paths.settings)
    if fresh_settings and profile is None:
        profile = "Full"
    if fresh_settings and access_scope is None:
        access_scope = "computer"
    if profile is not None:
        settings.profile = profile
        if profile == "Full":
            settings.tool_allowlist = []
            settings.workspace_permissions = {
                root: ["read", "write", "execute"] for root in settings.allowed_roots
            }
    if access_scope is not None:
        settings.access_scope = ProductSettings._normalize_access_scope(access_scope)
    if workspace:
        root = workspace.expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError("selected workspace does not exist")
        if str(root) not in settings.allowed_roots:
            settings.allowed_roots.append(str(root))
    settings.update_manifest_url = settings.update_manifest_url or DEFAULT_MANIFEST_URL
    settings.auto_update = True
    if mcp_port is not None:
        settings.mcp_port = int(mcp_port)
    if relay_port is not None:
        settings.relay_port = int(relay_port)
    settings.save(paths.settings)
    if not settings.allowed_roots:
        # Fresh users can work immediately in a confined starter project.
        from .setup_assistant import first_workspace
        result["starter_workspace"] = str(first_workspace(paths, settings))
    ensure_browser_token(paths)
    if tunnel_id or runtime_key:
        notify("Connecting OpenAI secure tunnel", 72)
        if not (tunnel_id and runtime_key):
            raise ValueError("both tunnel_id and Runtime API key are required")
        configure_tunnel(paths, tunnel_id, runtime_key)
    if register_system:
        notify("Registering SENTRA for this Windows user", 80)
        from .enrollment_extension import register_native_host
        result["browser_bridge"] = register_native_host(install_dir, paths.state_dir)
        _write_install_marker(install_dir, ["browser-enrollment/native-config.json",
            "browser-enrollment/native-chromium.json", "browser-enrollment/native-firefox.json"])
        if settings.autostart_desktop:
            _register_startup(install_dir)
        else:
            _unregister_startup(install_dir)
        result["user_path_registered"] = _register_user_path(install_dir)
        _register_url_protocol(install_dir)
        _register_uninstall(install_dir)
        from .windows_integration import shortcuts
        result["shortcuts"]=shortcuts(install_dir, desktop_executable=True)
        _write_install_marker(install_dir, ["desktop-launcher.json"])

    notify("Connect & Verify" if offline_handoff is None else "Service verification deferred until restart", 88)
    runtime = None
    if offline_handoff is None:
        runtime = LocalRuntime(paths, settings)
        verification = runtime.connect_and_verify(timeout_s=SERVICE_STARTUP_TIMEOUT_S)
        notify("Verificando a interface instalada…", 89)
        _verify_installed_display(verification, install_dir)
    else:
        # Coordinated apply keeps the installation quiesced. Starting services
        # here would invalidate the helper's actual offline proof and rollback.
        verification = {'started': {}, 'status': {}, 'next_url': None,
                        'deferred': 'post_update_restart', 'external_completion_claimed': False}
    result["startup"] = verification["started"]
    verification['web_models_required'] = not local_only
    if register_system and offline_handoff is None:
        notify("Registrando o plugin SENTRA no Codex…", 90)
        verification["codex_plugin"] = configure_codex(paths.state_dir, settings.mcp_port,
            registration_root=install_dir / "runtime/codex-registration")
    if runtime is not None:
        runtime.refresh_verification(verification)
    result["connect_verify"] = verification
    result["doctor"] = verification["status"]
    # The native Canvas and CLI are shipped regardless of OpenAI login.
    # ChatGPT plugin connection is an account-owned action, never silently
    # marked installed merely because an MCP tunnel responds.
    from .onboarding import chatgpt_plugin_install_plan
    result["canvas"] = {
        "installed": (install_dir / "sentra-canvas.exe").is_file(),
        "launcher": str(install_dir / "sentra-canvas.exe"),
        "desktop_shortcut": "SENTRA",
    }
    result["chatgpt_plugin"] = chatgpt_plugin_install_plan(
        verification.get("status") or {}, tunnel_id=tunnel_id,
    )
    ready = _installation_ready(verification, openai_required=not local_only)
    result["tunnel_required"] = not local_only
    result["external_completion_claimed"] = False
    notify("SENTRA instalado; conexão Web opcional" if local_only and ready else "Túnel verificado; autorize o plugin no ChatGPT" if ready else "A configuração precisa de atenção", 95 if ready else 85)

    if stop_after_doctor and runtime is not None:
        runtime.stop_all()

    human = install_dir / "sentra-human.exe"
    control = install_dir / "sentra-desktop.exe"
    if launch and not stop_after_doctor and offline_handoff is None and _display_ready(verification):
        launch_result: dict[str, Any] = {
            "requested": True,
            "deep_link": verification.get("next_url"),
        }
        canvas = install_dir / "sentra-canvas.exe"
        if ready and not tunnel_id and canvas.is_file():
            proc = subprocess.Popen([str(canvas)], cwd=install_dir,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            launch_result.update({"canvas_pid": proc.pid, "launched": True})
        elif control.is_file():
            if not ready or not tunnel_id:
                command = [str(control), "--open-url", "sentra://onboarding"]
            else:
                command = [str(control), "--hidden"]
            proc = subprocess.Popen(
                command,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            launch_result.update({"desktop_pid": proc.pid, "desktop_command": command[1:]})
            if ready and tunnel_id and human.is_file():
                human_proc = subprocess.Popen(
                    [str(human)],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                launch_result["human_pid"] = human_proc.pid
        elif human.is_file():
            human_proc = subprocess.Popen(
                [str(human)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            launch_result["human_pid"] = human_proc.pid
        else:
            launch_result.update({"requested": True, "launched": False})
        result["launch"] = launch_result
    return result


# The guarded facade accepts **options to pass through to the existing product
# installer. Preserve its public parameter/default contract for setup clients.
setattr(install, "__signature__", _install_signature(_install_product))


def verify_installed_local(*, install_dir: Path, launch: bool = True, state_dir: Path | None = None,
                           stop_after_doctor: bool = False,
                           progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Retry required tunnel/plugin readiness without reinstalling or stopping work."""
    install_dir = install_dir.expanduser().resolve()
    _validate_sentra_install(install_dir)
    paths = ProductPaths(install_dir, state_dir.expanduser().resolve()) if state_dir is not None else ProductPaths.default(install_dir)
    if progress:
        progress("Verificando os serviços do SENTRA…", 88)
    settings = ProductSettings.load(paths.settings)
    runtime = LocalRuntime(paths, settings)
    verification = runtime.connect_and_verify(timeout_s=SERVICE_STARTUP_TIMEOUT_S)
    _verify_installed_display(verification, install_dir)
    verification['web_models_required'] = True
    verification["codex_plugin"] = configure_codex(paths.state_dir, settings.mcp_port,
        registration_root=install_dir / "runtime/codex-registration")
    runtime.refresh_verification(verification)
    ready = _installation_ready(verification)
    if stop_after_doctor:
        runtime.stop_all()
    if ready and launch and not stop_after_doctor:
        subprocess.Popen([str(install_dir / "sentra-canvas.exe")], cwd=install_dir,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"version": PRODUCT_VERSION, "install_dir": str(install_dir),
            "connect_verify": verification, "reused_install": True}


def connect_installed_openai(
    *,
    install_dir: Path,
    tunnel_id: str,
    runtime_key: str,
    state_dir: Path | None = None,
    launch: bool = True,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Connect an already-installed SENTRA without replaying the install payload."""
    install_dir = install_dir.expanduser().resolve()
    paths = (
        ProductPaths(install_dir, state_dir.expanduser().resolve())
        if state_dir is not None
        else ProductPaths.default(install_dir)
    )

    def notify(label: str, percent: int) -> None:
        if progress is not None:
            progress(label, max(0, min(100, int(percent))))

    _validate_sentra_install(install_dir)
    tunnel_id = str(tunnel_id or "").strip()
    runtime_key = str(runtime_key or "").strip()
    if not tunnel_id or not runtime_key:
        raise ValueError("both tunnel_id and Runtime API key are required")

    notify("Protecting OpenAI credentials", 55)
    configure_tunnel(paths, tunnel_id, runtime_key)
    settings = ProductSettings.load(paths.settings)
    web_models = _enable_web_models_autostart(paths, install_dir)
    notify("Connecting OpenAI secure tunnel", 72)
    runtime = LocalRuntime(paths, settings)
    verification = runtime.connect_and_verify(timeout_s=SERVICE_STARTUP_TIMEOUT_S)
    _verify_installed_display(verification, install_dir)
    verification['web_models_required'] = True
    verification["codex_plugin"] = configure_codex(paths.state_dir, settings.mcp_port,
        registration_root=install_dir / "runtime/codex-registration")
    runtime.refresh_verification(verification)
    ready = _installation_ready(verification, openai_required=True)
    notify("Túnel verificado; autorize o plugin no ChatGPT" if ready else "Connection needs attention", 95 if ready else 85)

    result: dict[str, Any] = {
        "version": PRODUCT_VERSION,
        "install_dir": str(install_dir),
        "startup": verification.get("started"),
        "connect_verify": verification,
        "doctor": verification.get("status") or {},
        "web_models": web_models,
        "reused_install": True,
    }

    if launch and _display_ready(verification):
        control = install_dir / "sentra-desktop.exe"
        human = install_dir / "sentra-human.exe"
        launch_result: dict[str, Any] = {
            "requested": True,
            "deep_link": verification.get("next_url"),
        }
        if control.is_file():
            command = (
                [str(control), "--hidden"]
                if ready
                else [str(control), "--open-url", str(verification.get("next_url") or "sentra://onboarding")]
            )
            proc = subprocess.Popen(
                command,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            launch_result.update({"desktop_pid": proc.pid, "desktop_command": command[1:]})
            if ready and tunnel_id and human.is_file():
                human_proc = subprocess.Popen(
                    [str(human)],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                launch_result["human_pid"] = human_proc.pid
        else:
            launch_result["launched"] = False
        result["launch"] = launch_result

    return result


def uninstall(
    install_dir: Path,
    *,
    keep_config: bool = False,
    state_dir: Path | None = None,
    unregister_system: bool = True,
) -> dict[str, Any]:
    install_dir = install_dir.expanduser().resolve()
    paths = (
        ProductPaths(install_dir, state_dir.expanduser().resolve())
        if state_dir is not None
        else ProductPaths.default(install_dir)
    )
    _validate_sentra_install(install_dir)
    _stop_installed_processes(install_dir)
    if unregister_system:
        from .enrollment_extension import unregister_native_host
        unregister_native_host(install_dir)
        _unregister_startup(install_dir)
        _unregister_user_path(install_dir)
        _unregister_url_protocol(install_dir)
        _unregister_uninstall(install_dir)
        from .windows_integration import shortcuts
        shortcuts(install_dir,remove=True,desktop_executable=True)
    # State can be shared by installations and contain pre-existing credentials.
    # A program-tree marker does not establish exclusive ownership of that state.
    keep_config = True
    bundled_helper = payload_root() / "sentra-update-helper.exe"
    helper = (bundled_helper if getattr(sys, "frozen", False) and bundled_helper.is_file()
              else install_dir / "sentra-update-helper.exe")
    if os.name == "nt" and helper.is_file():
        temp_root = Path(tempfile.mkdtemp(prefix="sentra-uninstall-"))
        external_helper = temp_root / "sentra-update-helper.exe"
        shutil.copy2(helper, external_helper)
        from .onedir import copy_support
        copy_support(helper.parent, temp_root, "sentra-update-helper.exe")
        subprocess.Popen(
            [
                str(external_helper),
                "cleanup",
                "--install-dir", str(install_dir),
                "--parent-pid", str(os.getpid()),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {
            "ok": True,
            "kept_config": keep_config,
            "cleanup_scheduled": True,
        }

    running_from_install = False
    try:
        running_from_install = Path(sys.executable).resolve().is_relative_to(install_dir)
    except (ValueError, AttributeError):
        running_from_install = False
    if running_from_install and os.name == "nt":
        raise RuntimeError("sentra-update-helper.exe is required for installed cleanup")
    from .update_helper import cleanup_install
    cleanup_install(install_dir, parent_pid=0)
    return {"ok": True, "kept_config": keep_config, "cleanup_scheduled": False}


class _InstallerSelection(TypedDict):
    """UI-thread snapshot passed unchanged to the installation worker."""
    install_dir: Path
    workspace: Path | None
    profile: str
    access_scope: str
    install_git: bool
    install_docker: bool


class InstallerWizard:
    # installer_ui.build creates these controls before the window is shown.
    openai_expanded: bool
    openai_fields: list[tk.Widget]
    openai_toggle: ttk.Button
    advanced_frame: tk.Frame
    advanced_button: ttk.Button
    install_button: ttk.Button
    connect_hint: tk.Label

    def __init__(self) -> None:
        from .gui_runtime import prepare_gui_runtime
        prepare_gui_runtime()
        import tkinter as tk
        from tkinter import ttk

        from .installer_appearance import enable_native_dpi
        enable_native_dpi()
        self.tk, self.ttk = tk, ttk
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(f"SENTRA Setup {PRODUCT_VERSION}")
        self.root.geometry("780x650")
        self.root.minsize(720, 600)
        self.install_dir = tk.StringVar(value=str(ProductPaths.default().install_dir))
        self.workspace = tk.StringVar()
        self.profile = tk.StringVar(value="Full")
        self.access_scope = tk.StringVar(value="computer")
        self.tunnel_id = tk.StringVar()
        self.runtime_key = tk.StringVar()
        self.browser_setup_var = tk.BooleanVar(value=True)
        self.git_var = tk.BooleanVar(value=False)
        self.docker_var = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Tudo pronto. O instalador prepara o ambiente e abre o SENTRA automaticamente.")
        self.progress_value = tk.IntVar(value=0)
        self.advanced_visible = False
        self._installed = False
        self._build()
        self.root.deiconify()

    def _build(self) -> None:
        from .installer_ui import build
        build(self)

    def _open_setup_tutorial(self) -> None:
        """Play the shipped guide before installation, including frozen Setup."""
        from tkinter import messagebox
        import webbrowser
        media = docs_source() / "onboarding_media"
        guide = media / "SENTRA_SETUP_GUIDE.html"
        try:
            from .onboarding import TUTORIAL_MEDIA
            if not guide.is_file() or any(not (media / name).is_file() for name in TUTORIAL_MEDIA.values()):
                raise FileNotFoundError("O tutorial do SENTRA está incompleto. Baixe o Setup completo novamente.")
            # Frozen Setup removes its extraction directory on exit. Keep the
            # tutorial playable while the user completes login in the browser.
            names = [*TUTORIAL_MEDIA.values(), guide.name]
            digest = hashlib.sha256()
            for name in names:
                digest.update((media / name).read_bytes())
            cache = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "SENTRA" / "Tutorials" / digest.hexdigest()
            cache.mkdir(parents=True, exist_ok=True)
            for name in names:
                target = cache / name
                staged = cache / (name + "." + uuid.uuid4().hex + ".tmp")
                try:
                    shutil.copy2(media / name, staged)
                    os.replace(staged, target)
                finally:
                    staged.unlink(missing_ok=True)
            if not webbrowser.open((cache / guide.name).resolve().as_uri()):
                raise RuntimeError("Não foi possível abrir o navegador para reproduzir o tutorial.")
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Tutorial de instalação do SENTRA", str(exc))

    def _toggle_openai(self) -> None:
        self.openai_expanded = not self.openai_expanded
        for widget in self.openai_fields:
            if self.openai_expanded:
                widget.pack(fill="x", pady=(14, 0))
            else:
                widget.pack_forget()
        self.openai_toggle.configure(
            text="Recolher  ⌃" if self.openai_expanded else "Configuração manual  ⌄"
        )

    def _browse(self) -> None:
        from tkinter import filedialog

        value = filedialog.askdirectory()
        if value:
            self.workspace.set(value)

    def _toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.pack(fill="x", pady=(12, 0))
        else:
            self.advanced_frame.pack_forget()
        self.advanced_button.configure(
            text="⚙  Opções avançadas  " + ("⌃" if self.advanced_visible else "⌄")
        )

    def _progress_callback(self, label: str, percent: int) -> None:
        def apply() -> None:
            self.progress_value.set(percent)
            self.status.set(label)

        self.root.after(0, apply)

    def _open_existing_install(self, install_dir: Path) -> None:
        """Verify the installed services without copying files or stopping sessions."""
        self._install(require_openai=False, verify_only=True)

    def _primary_action(self) -> None:
        """Install locally first, then require the tunnel before setup completion."""
        has_tunnel = bool(self.tunnel_id.get().strip())
        has_key = bool(self.runtime_key.get().strip())
        if has_tunnel != has_key:
            from tkinter import messagebox

            messagebox.showerror(
                "SENTRA Setup",
                "Tunnel ID and Runtime API key are a pair. Fill both values to install and connect now, "
                "or clear both to configure the required tunnel using Edge after installation.",
            )
            self.status.set("ChatGPT setup: complete both fields or leave both empty")
            self.progress_value.set(10)
            return

        if not hasattr(self, "install_dir"):
            # Support minimal programmatic wizard consumers without a UI path.
            self._install(require_openai=has_tunnel and has_key)
            return
        install_dir = Path(self.install_dir.get()).expanduser().resolve()
        # A marker proves ownership, not that an interrupted copy finished.
        # Reset when the selected destination changes or needs repair.
        self._installed = False
        if (install_dir / INSTALL_MARKER).is_file():
            try:
                marker = _validate_sentra_install(install_dir)
            except (OSError, ValueError, RuntimeError) as exc:
                from tkinter import messagebox
                messagebox.showerror("SENTRA Setup", _friendly_install_error(exc))
                return
            self._installed = marker.get("version") == PRODUCT_VERSION and all(
                (install_dir / name).is_file()
                for name in (*PRODUCTS, "tunnel-client.exe")
            )
        if self._installed and not has_tunnel:
            self._open_existing_install(install_dir)
        else:
            self._install(require_openai=has_tunnel and has_key)

    def _install(self, require_openai: bool = True, *, verify_only: bool = False, enroll: bool = True) -> None:
        from tkinter import messagebox

        tunnel_id = self.tunnel_id.get().strip()
        runtime_key = self.runtime_key.get().strip()
        if not require_openai:
            tunnel_id = ""
            runtime_key = ""
        if require_openai and (not tunnel_id or not runtime_key):
            messagebox.showerror(
                "SENTRA Setup",
                "Connect OpenAI first: enter both the Tunnel ID and Runtime API key. "
                "Use the buttons above to create them in OpenAI Platform.",
            )
            self.status.set("Step 2 of 3 — Connect OpenAI to continue")
            self.progress_value.set(10)
            return

        self.install_button.configure(state="disabled")
        if require_openai and self._installed:
            self.status.set("Step 2 of 3 — Connecting OpenAI")
            self.progress_value.set(60)
        else:
            self.status.set("Preparing installation")
            self.progress_value.set(5)
        self.root.update_idletasks()

        # Tk variables must be read on the UI thread, not by the worker.
        selected: _InstallerSelection = {"install_dir": Path(self.install_dir.get()),
                    "workspace": Path(self.workspace.get()) if self.workspace.get().strip() else None,
                    "profile": self.profile.get(), "access_scope": self.access_scope.get(),
                    "install_git": self.git_var.get(), "install_docker": self.docker_var.get()}
        browser_setup = bool(self.browser_setup_var.get())

        def worker() -> None:
            try:
                if verify_only:
                    result = verify_installed_local(
                        install_dir=selected["install_dir"], launch=not browser_setup,
                        progress=self._progress_callback,
                    )
                    verification = result["connect_verify"]
                elif require_openai and self._installed:
                    result = connect_installed_openai(
                        install_dir=selected["install_dir"],
                        tunnel_id=tunnel_id,
                        runtime_key=runtime_key,
                        launch=False,
                        progress=self._progress_callback,
                    )
                    self.root.after(0, lambda: self.runtime_key.set(""))
                    self.root.after(0, lambda: self.tunnel_id.set(""))
                    verification = result["connect_verify"]
                    # Setup remains the owner of account onboarding. Do not
                    # launch a second Quick Start window on a partial result.
                else:
                    result = install(
                        **selected,
                        tunnel_id=tunnel_id,
                        runtime_key=runtime_key,
                        # If the user opted into browser enrollment, the
                        # installer launches that one deep link after local
                        # installation instead of opening a duplicate Desktop.
                        launch=not (
                            browser_setup and not require_openai
                        ),
                        progress=self._progress_callback,
                    )
                    verification = result["connect_verify"]
                if not require_openai:
                    def installed() -> None:
                        self._installed = True
                        if not _installation_ready(verification, openai_required=False):
                            display_failed = not _display_ready(verification)
                            self.status.set("Instalado. A interface não passou na verificação." if display_failed else
                                            "Instalado. A verificação dos serviços ainda precisa de atenção.")
                            self.progress_value.set(90)
                            self.connect_hint.configure(text="Seus arquivos foram preservados. Tente verificar novamente.")
                            self.install_button.configure(state="normal", text="Verificar novamente  →",
                                                          command=lambda: self._install(require_openai=False, verify_only=True))
                            return
                        if _installation_ready(verification):
                            self._show_tunnel_verified(verification)
                            return
                        self.status.set("SENTRA instalado. Configure a conexão Web se desejar.")
                        self.progress_value.set(85)
                        if browser_setup and enroll:
                            self._start_browser_setup()
                            return
                        else:
                            self.connect_hint.configure(
                                text="O uso local e os modelos oficiais não dependem desta conexão. Você pode conectar os modelos Web mais tarde."
                            )
                            self.install_button.configure(state="normal", text="Abrir SENTRA", command=self._open_main_app)
                            return
                        self.install_button.configure(
                            state="normal", text="Verificar conexão  →",
                            command=lambda: self._install(require_openai=False, verify_only=True, enroll=False),
                        )
                        self._schedule_connection_check()

                    self.root.after(0, installed)
                    return

                ready = _installation_ready(verification, openai_required=True)
                if ready:
                    text = (
                        "MCP e túnel verificados. Falta autorizar o plugin no ChatGPT e confirmar uma chamada de ferramenta pela conta."
                    )
                elif not _display_ready(verification):
                    text = "A interface instalada não passou na verificação. Reabra o Setup para reparar e verificar novamente."
                elif verification.get("core_ready"):
                    text = (
                        "SENTRA local instalado. A conexão obrigatória para GPT6-WEB ainda precisa de atenção."
                    )
                elif tunnel_id:
                    text = (
                        "Installed, but Connect & Verify found a required service that is not Ready. "
                        "Quick Start was opened with the next action."
                    )
                else:
                    text = (
                        "SENTRA installed. Quick Start was opened so you can connect OpenAI "
                        "when you are ready."
                    )

                def complete() -> None:
                    self._installed = True
                    if ready:
                        self._show_tunnel_verified(verification)
                    else:
                        self.progress_value.set(75)
                        self.status.set(f"Step 2 of 3 — Connection needs attention. {text}")
                        self.install_button.configure(
                            state="normal",
                            text="Retry Connect OpenAI",
                            command=lambda: self._install(require_openai=False, verify_only=True, enroll=False),
                        )
                    messagebox.showinfo("SENTRA Setup", text) if ready else messagebox.showerror("SENTRA Setup", text)

                self.root.after(0, complete)
            except Exception as exc:
                error = _friendly_install_error(exc)

                def failed() -> None:
                    step = "Connect OpenAI" if self._installed else "Install"
                    self.status.set(f"{step} needs attention — follow the action in the error dialog, then retry")
                    self.connect_hint.configure(text=error.replace("\n\n", " — "))
                    self.install_button.configure(state="normal")
                    messagebox.showerror("SENTRA Setup", error)

                self.root.after(0, failed)

        __import__("threading").Thread(target=worker, daemon=True).start()

    def _start_browser_setup(self) -> None:
        """Own the browser step inside Setup instead of handing it to Desktop."""
        from .openai_auto_setup import run_setup_enrollment
        if getattr(self, "_browser_setup_running", False):
            return
        self._browser_setup_running = True
        install_dir = Path(self.install_dir.get()).expanduser().resolve()
        browser_options = {}
        if hasattr(self, "browser_choice"):
            browser = self.browser_choices[self.browser_choice.get()]
            browser_options = {"browser": browser, "allow_setup_profile": browser in {"edge", "chrome"}}
        self.install_button.configure(state="disabled")
        self.status.set("Configurando a conexão pelo navegador neste Setup…")
        self.connect_hint.configure(text="Usando uma conexão DOM disponível. Conclua login ou consentimento no navegador se solicitado.")

        def notify(event: str, message: str) -> None:
            if event == "verification_prompt":
                def show_test():
                    self.connection_test_prompt = message
                    self.copy_connection_test.pack(anchor="w", pady=(8, 0))
                self.root.after(0, show_test)
            if event in {"browser_session", "opened", "progress", "workspace_required"}:
                def update_hint(text: str = message) -> None:
                    self.connect_hint.configure(text=text)
                self.root.after(0, update_hint)

        def worker() -> None:
            try:
                result = run_setup_enrollment(ProductPaths.default(install_dir), notify, **browser_options)
            except Exception:
                result = {"ok": False, "reason": "browser_enrollment_needs_attention"}

            def finished() -> None:
                self._browser_setup_running = False
                if result.get("ok"):
                    self._account_roundtrip_verified = result.get("mcp_roundtrip_verified") is True
                    self._install(require_openai=False, verify_only=True, enroll=False)
                    return
                messages = {
                    "credential_protection_unavailable": "O Windows não disponibilizou a proteção de credenciais. A configuração da conta não foi iniciada.",
                    "browser_enrollment_timeout": "A conexão não foi concluída no prazo. Verifique o navegador antes de tentar novamente.",
                    "manual_recovery_required": "Existe uma configuração anterior que precisa ser recuperada antes de continuar.",
                    "browser_account_selection_required": "Mais de um navegador está conectado. Mantenha conectada a sessão Platform desejada e tente novamente.",
                    "browser_extension_required": "Habilite a ponte DOM no navegador com a conta já conectada. O Setup inclui a extensão Firefox assinada pela Mozilla para uso privado. A confirmação de instalação pertence ao navegador.",
                    "browser_enrollment_already_running": "Há outra configuração pelo navegador em andamento. Conclua ou feche o outro Setup antes de tentar novamente.",
                    "login_required": "Entre na conta Platform no navegador para continuar a configuração.",
                    "chatgpt_workspace_required": "Selecione o workspace ChatGPT desejado no formulário do navegador.",
                    "workspace_association_unverified": "O provedor não confirmou a associação do workspace. Verifique essa etapa na Platform.",
                    "chatgpt_browser_required": "MCP e túnel verificados. Para concluir o app no ChatGPT, selecione Edge ou Chrome; a ponte Firefox atual só permite configurar a Platform.",
                    "chatgpt_call_pending": "MCP e túnel configurados. Conclua a instalação/autorização do app SENTRA no ChatGPT e use Copiar teste de conexão para verificar a chamada real.",
                    "chatgpt_setup_cancelled": "A etapa ChatGPT foi interrompida. O túnel foi preservado; tente novamente para continuar sem criar outra chave.",
                }
                self.status.set("A configuração automática precisa de atenção.")
                self.connect_hint.configure(text=messages.get(result.get("reason"), "Verifique a etapa indicada no navegador e tente novamente pelo Setup."))
                self.install_button.configure(state="normal", text="Tentar configuração novamente  →", command=self._start_browser_setup)
                if result.get("reason") == "browser_extension_required" and browser_options.get("browser", "auto") in {"auto", "firefox"}:
                    from .enrollment_extension import installed_firefox_package
                    try:
                        installed_firefox_package(install_dir)
                    except (OSError, ValueError):
                        pass
                    else:
                        self.install_button.configure(text="Habilitar ponte no Firefox  →", command=self._open_firefox_bridge)

            self.root.after(0, finished)

        __import__("threading").Thread(target=worker, daemon=True).start()

    def _open_firefox_bridge(self) -> None:
        from tkinter import messagebox
        from .enrollment_extension import open_firefox_bridge_installation
        try:
            open_firefox_bridge_installation(Path(self.install_dir.get()).expanduser().resolve())
        except (OSError, ValueError):
            messagebox.showerror("SENTRA Setup", "Não foi possível abrir o pacote assinado do Firefox. Verifique ou repare a instalação.")
            return
        messagebox.showinfo("Habilitar no Firefox",
            "No Firefox, em Extensões, abra a engrenagem e escolha Instalar extensão de um arquivo. "
            "Selecione firefox-signed.xpi na pasta que foi aberta e confirme a instalação no navegador. "
            "Mantenha aberta a sessão Platform que deseja usar. "
            "Quando concluir, feche este aviso: o Setup continuará automaticamente.")
        self._start_browser_setup()

    def _show_tunnel_verified(self, verification: dict) -> None:
        self._connection_deadline = 0
        if getattr(self, "_account_roundtrip_verified", False):
            self.progress_value.set(100)
            self.status.set("Conexão verificada — o ChatGPT chamou o MCP desta instalação.")
            self.connect_hint.configure(text="MCP, túnel e teste de ida e volta verificados. Modelos oficiais preservam suas configurações.")
            self.install_button.configure(state="normal", text="Abrir SENTRA", command=self._open_main_app)
            return
        self.progress_value.set(95)
        self.status.set("Etapa 3 de 3 — túnel verificado; autorização no ChatGPT pendente.")
        self.connect_hint.configure(text="O plugin local foi verificado. No ChatGPT, conecte o túnel SENTRA, "
                                        "autorize o plugin e confirme uma chamada. A instalação na conta ainda não foi comprovada.")
        self.install_button.configure(state="normal", text="Conectar plugin no ChatGPT  →",
                                      command=self._open_chatgpt_plugin)

    def _schedule_connection_check(self) -> None:
        """Observe Edge enrollment for ten minutes without duplicate enrollment."""
        if time.monotonic() >= getattr(self, "_connection_deadline", 0):
            return
        if getattr(self, "_connection_timer", None) is not None:
            return

        def check():
            self._connection_timer = None
            if time.monotonic() >= getattr(self, "_connection_deadline", 0):
                return
            if str(self.install_button.cget("state")) == "disabled":
                self._schedule_connection_check()
            else:
                self._install(require_openai=False, verify_only=True, enroll=False)

        self._connection_timer = self.root.after(10000, check)

    def _open_chatgpt_plugin(self) -> None:
        self._start_browser_setup()

    def _open_main_app(self) -> None:
        launcher = Path(self.install_dir.get()).expanduser().resolve() / "sentra-launcher.exe"
        subprocess.Popen([str(launcher)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _open_web_models(self) -> None:
        from tkinter import messagebox
        desktop = Path(self.install_dir.get()).expanduser().resolve() / "sentra-desktop.exe"
        if not desktop.is_file():
            messagebox.showinfo("SENTRA Setup", "Instale os componentes primeiro para abrir os modelos WEB.")
            return
        subprocess.Popen([str(desktop), "--open-url", "sentra://web-models"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def run(self) -> int:
        self.root.mainloop()
        return 0


def _write_setup_report(path: Path, operation: str, result: dict[str, Any], code: int) -> None:
    """Persist fixed verification axes even when the windowed EXE has no console.

    Provider responses and configuration are deliberately excluded: a report
    must be safe to attach to clean-machine QA without exporting credentials.
    """
    verification = result.get("connect_verify") or {}
    status = verification.get("status") or {}
    preflight = result if operation == "check" else result.get("preflight") or {}
    browser = result.get("browser_automation") or {}
    failure_type = result.get("error_type")
    known_failures = {"TimeoutExpired", "TimeoutError", "PermissionError", "FileNotFoundError",
                      "FileExistsError", "ValueError", "RuntimeError", "OSError",
                      "CredentialProtectionUnavailable", "ShortcutRegistrationError"}
    failure = None
    if failure_type:
        safe_type = failure_type if failure_type in known_failures else "installation_error"
        failure = {"error_type": safe_type, "stage": (
            "windows_shortcuts" if safe_type == "ShortcutRegistrationError" else
            "credential_protection" if safe_type == "CredentialProtectionUnavailable" else operation)}
    browser_reason = browser.get("reason")
    if browser_reason not in {"credential_protection_unavailable", "manual_recovery_required",
                              "browser_extension_required", "browser_account_selection_required", "browser_enrollment_already_running",
                              "browser_enrollment_needs_attention", "browser_enrollment_incomplete",
                              "browser_enrollment_timeout", "tunnel_verified", "mcp_roundtrip_verified",
                              "chatgpt_browser_required", "chatgpt_call_pending", "chatgpt_setup_cancelled"}:
        browser_reason = None
    report = {
        "schema": 1, "version": PRODUCT_VERSION, "operation": operation,
        "exit_code": code, "recorded_at": time.time(),
        "failure": failure,
        "payload_ok": preflight.get("ok") is True,
        "payload_verified": preflight.get("verified") is True,
        "preflight_failure": ("credential_protection_unavailable"
                              if result.get("reason") == "credential_protection_unavailable" else None),
        "local_ready": verification.get("core_ready") is True,
        "ready": code == 0 and operation == "install" and _installation_ready(verification, openai_required=result.get("tunnel_required", True)),
        "verification_deferred": verification.get("deferred") == "post_update_restart",
        "browser_enrollment": {"attempted": "browser_automation" in result,
                               "ok": browser.get("ok") is True, "reason": browser_reason},
        "checks": {
            name: (status.get(name) or {}).get("ok") is True
            for name in ("mcp", "tunnel", "display")
        },
        "display_required": verification.get("display_required") is True,
        "web_models": {
            name: (status.get("web_models") or {}).get(name) is True
            for name in ("payload_complete", "ready", "catalog_ready", "turn_ready")
        },
        "account_authorization_verified": False,
        "native_route_recovery": result.get("native_route_recovery"),
        "mcp_roundtrip_verified": browser.get("mcp_roundtrip_verified") is True,
        "homologated": False,
    }
    target = Path(_filesystem_path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="sentra-installer")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--keep-config", action="store_true")
    parser.add_argument("--local-only", action="store_true", help="Install local services; configure Web accounts later inside SENTRA.")
    parser.add_argument("--install-dir", default=str(ProductPaths.default().install_dir))
    parser.add_argument("--state-dir")
    parser.add_argument("--workspace")
    parser.add_argument("--profile", choices=("Safe", "Developer", "Full"))
    parser.add_argument(
        "--access-scope",
        choices=("workspace", "user", "computer"),
        default=None,
        help="Filesystem scope; fresh installs default to computer.",
    )
    parser.add_argument("--tunnel-id", default="")
    parser.add_argument(
        "--runtime-key-env",
        default="CONTROL_PLANE_API_KEY",
        help="Environment variable containing the Runtime API key; never pass the secret on the command line.",
    )
    parser.add_argument("--tunnel-archive")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--report-file", type=Path,
                        help="Write a credential-free JSON verification report (check/silent mode).")
    parser.add_argument("--browser-setup", action="store_true",
                        help="Complete account enrollment through DOM inside Setup, reusing an available browser connection.")
    parser.add_argument("--check", action="store_true", help="Verify this Setup payload without installing or starting services.")
    parser.add_argument("--gui-check", action="store_true", help="Create and destroy a hidden Tk/ttk window without installing or starting services.")
    parser.add_argument("--gui-check-report", type=Path)
    parser.add_argument("--install-git", action="store_true")
    parser.add_argument("--install-docker", action="store_true")
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Deprecated compatibility flag; Git is already lazy by default.",
    )
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--no-system-registration", action="store_true")
    parser.add_argument("--mcp-port", type=int)
    parser.add_argument("--relay-port", type=int)
    parser.add_argument("--stop-after-doctor", action="store_true")
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("--offline-handoff", type=Path)
    args = parser.parse_args(argv)
    if args.gui_check_report and not args.gui_check:
        parser.error("--gui-check-report requires --gui-check")
    if args.gui_check:
        from .gui_runtime import check_gui_runtime
        return 0 if check_gui_runtime(args.gui_check_report)["ok"] else 2
    if args.browser_setup and (args.offline_handoff or args.uninstall):
        parser.error("browser enrollment requires an online installation")
    if args.report_file and not (args.check or args.silent):
        parser.error("--report-file requires --check or --silent")
    if args.silent and args.local_only and not args.report_file:
        report_root = Path(args.state_dir) if args.state_dir else ProductPaths.default(Path(args.install_dir)).state_dir
        args.report_file = str(report_root / "installer-last-run.json")

    def finish(operation: str, result: dict[str, Any], code: int) -> int:
        if args.report_file:
            try:
                _write_setup_report(args.report_file, operation, result, code)
            except OSError:
                # Unrecorded runs cannot pass an unattended evidence gate.
                return 2
        return code
    if args.check:
        try:
            result = check_install_payload(Path(args.install_dir))
        except (OSError, ValueError) as exc:
            result = {"ok": False, "error_type": type(exc).__name__, "message": str(exc)}
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return finish("check", result, 0 if result.get("ok") else 2)
    if args.uninstall:
        result = uninstall(
            Path(args.install_dir),
            keep_config=args.keep_config,
            state_dir=Path(args.state_dir) if args.state_dir else None,
            unregister_system=not args.no_system_registration,
        )
        print(json.dumps(result))
        return finish("uninstall", result, 0)
    if not args.silent:
        return InstallerWizard().run()
    try:
        result = install(
            install_dir=Path(args.install_dir),
            workspace=Path(args.workspace) if args.workspace else None,
            profile=args.profile,
            access_scope=args.access_scope,
            tunnel_id=args.tunnel_id,
            runtime_key=os.environ.get(args.runtime_key_env, "") if args.tunnel_id else "",
            tunnel_archive=Path(args.tunnel_archive) if args.tunnel_archive else None,
            install_git=args.install_git and not args.no_git,
            install_docker=args.install_docker,
            launch=not args.no_launch and not args.browser_setup,
            state_dir=Path(args.state_dir) if args.state_dir else None,
            register_system=not args.no_system_registration,
            mcp_port=args.mcp_port,
            relay_port=args.relay_port,
            stop_after_doctor=args.stop_after_doctor,
            offline_handoff=args.offline_handoff,
            local_only=args.local_only,
        )
    except Exception as exc:
        from sentra_mcp.errors import sanitize_error
        failure = {"ok": False, "error_type": type(exc).__name__,
                   "message": sanitize_error(_friendly_install_error(exc))[:2000]}
        from .openai_auto_setup import CredentialProtectionUnavailable
        if isinstance(exc, CredentialProtectionUnavailable):
            failure["reason"] = "credential_protection_unavailable"
        print(json.dumps(failure), file=sys.stderr)
        # Windowed PyInstaller has no stderr. Persist a bounded diagnostic and
        # return normally so --silent never leaves an unattended error dialog.
        error_root = Path(args.state_dir) if args.state_dir else ProductPaths.default(Path(args.install_dir)).state_dir
        try:
            error_root.mkdir(parents=True, exist_ok=True)
            (error_root / "installer-error.json").write_text(json.dumps(failure), encoding="utf-8")
        except OSError:
            pass
        return finish("install", failure, 2)
    if args.browser_setup:
        if not _installation_ready(result.get("connect_verify") or {}, openai_required=False):
            return finish("install", result, 2)
        from .openai_auto_setup import run_setup_enrollment
        enrolled = ProductPaths(
            Path(args.install_dir),
            Path(args.state_dir) if args.state_dir else ProductPaths.default(Path(args.install_dir)).state_dir,
        )
        try:
            browser_result = run_setup_enrollment(enrolled, lambda *_: None)
            result["browser_automation"] = browser_result
            if not browser_result.get("ok"):
                return finish("install", result, 2)
            checked = verify_installed_local(
                install_dir=enrolled.install_dir, state_dir=enrolled.state_dir,
                launch=not args.no_launch, stop_after_doctor=args.stop_after_doctor,
            )
            result["connect_verify"] = checked["connect_verify"]
        except Exception:
            result["browser_automation"] = {"ok": False, "reason": "browser_enrollment_needs_attention"}
            return finish("install", result, 2)
    print(json.dumps(result, indent=2))
    verification = result.get("connect_verify") or {}
    if args.offline_handoff and verification.get("deferred") == "post_update_restart":
        return finish("install", result, 0)  # The authenticated update helper verifies after restart.
    return finish("install", result, 0 if _installation_ready(verification, openai_required=not args.local_only) else 2)



if __name__ == "__main__":
    raise SystemExit(main())
