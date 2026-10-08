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
from typing import Any, Callable

from sentra_version import PRODUCT_VERSION

from .local_runtime import LocalRuntime
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

ProgressCallback = Callable[[str, int], None]


def _installation_ready(verification: dict[str, Any], *, openai_required: bool) -> bool:
    local_ready = bool(verification.get("core_ready") and not verification.get("onboarding_required"))
    if not openai_required:
        return local_ready
    status = verification.get("status") or {}
    return bool(local_ready and (verification.get("chatgpt_onboarding") or {}).get("ready")
                and (status.get("mcp") or {}).get("ok")
                and (status.get("tunnel") or {}).get("ok"))


def _friendly_install_error(exc: BaseException) -> str:
    """Translate common setup failures into a concrete next action."""
    detail = str(exc).strip() or exc.__class__.__name__
    lowered = detail.lower()
    if "sha-256" in lowered or "checksum" in lowered:
        action = "Re-download the official Setup release; the tunnel-client archive failed integrity validation."
    elif "payload" in lowered and ("missing" in lowered or "stale" in lowered):
        action = "Re-download the current SENTRA Setup release. This installer payload is incomplete or stale."
    elif "tunnel" in lowered and ("runtime" in lowered or "api key" in lowered):
        action = "Open OpenAI Platform, create/select a tunnel and a Runtime API key with All permissions, then try again."
    elif "workspace" in lowered and "exist" in lowered:
        action = "Choose an existing project folder, or leave Initial workspace empty and add it later in Advanced settings."
    elif "permission" in lowered or "access is denied" in lowered:
        action = "Close running SENTRA components and retry. If Windows blocked the install folder, choose a folder under your user profile."
    elif "url" in lowered or "network" in lowered or "timed out" in lowered:
        action = "Check internet access and retry. Setup needs to download the pinned OpenAI tunnel client."
    else:
        action = "Retry Setup. If it fails again, open SENTRA Desktop → Status → Doctor and copy the visible error detail."
    return f"{detail}\n\nWhat to do: {action}"


PRODUCTS = (
    "sentra-mcp.exe", "sentra-browser-relay.exe", "sentra-desktop.exe",
    "sentra-human.exe", "sentra-human-worker.exe", "sentra.exe",
    "sentra-agent.exe", "sentra-diagnostics.exe", "sentra-admin.exe",
    "sentra-update-helper.exe", "sentra-oma.exe", "sentra-cli.exe", "sentra-canvas.exe",
)

def payload_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "payload"
    return Path(__file__).resolve().parents[1] / "dist"


def extension_source() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "edge_extension"
    return Path(__file__).resolve().parents[1] / "edge_extension"


def docs_source() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "docs"
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


def download_tunnel_client(destination: Path, archive: Path | None = None) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="sentra-tunnel-"))
    try:
        source = Path(archive).resolve() if archive else temp_root / "tunnel-client.zip"
        if archive is None:
            req = urllib.request.Request(TUNNEL_URL, headers={"User-Agent": "SENTRA-Installer/1.0"})
            with urllib.request.urlopen(req, timeout=60) as response, source.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
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
    for name in PRODUCTS:
        candidate = source / name
        if not candidate.is_file():
            raise FileNotFoundError(f"release payload missing {name}")
        shutil.copy2(_filesystem_path(candidate), _filesystem_path(install_dir / name))
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

    docs = docs_source()
    start_here = docs / "START_HERE.md"
    if not start_here.is_file():
        raise FileNotFoundError("SENTRA product education docs are missing START_HERE.md")
    docs_target = (install_dir / "docs").resolve()
    if not docs_target.is_relative_to(install_dir.resolve()):
        raise ValueError("docs install target escaped install directory")
    shutil.copytree(_filesystem_path(docs), _filesystem_path(docs_target), dirs_exist_ok=True)

    if getattr(sys, "frozen", False):
        shutil.copy2(_filesystem_path(Path(sys.executable)), _filesystem_path(install_dir / "sentra-installer.exe"))
    owned = list(PRODUCTS)
    for folder, prefix in ((ext_source, "edge_extension"), (source / "web-models", "web-models"), (docs, "docs")):
        owned.extend(_owned_tree_files(folder, prefix))
    if getattr(sys, "frozen", False):
        owned.append("sentra-installer.exe")
    return owned


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
            "DisplayIcon": str(install_dir / "sentra-human.exe"),
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


def install(
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
        _stop_installed_processes(install_dir)
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
    result["web_models"] = _enable_web_models_autostart(paths, install_dir)
    notify("Installing secure tunnel client", 45)
    result["tunnel_client"] = download_tunnel_client(install_dir, tunnel_archive)
    _write_install_marker(install_dir, owned_files + ["tunnel-client.exe"])
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
        if settings.autostart_desktop:
            _register_startup(install_dir)
        else:
            _unregister_startup(install_dir)
        result["user_path_registered"] = _register_user_path(install_dir)
        _register_url_protocol(install_dir)
        _register_uninstall(install_dir)
        from .windows_integration import shortcuts
        result["shortcuts"]=shortcuts(install_dir)

    notify("Connect & Verify", 88)
    runtime = LocalRuntime(paths, settings)
    verification = runtime.connect_and_verify(timeout_s=12.0)
    result["startup"] = verification["started"]
    result["connect_verify"] = verification
    result["doctor"] = verification["status"]
    ready = _installation_ready(verification, openai_required=bool(tunnel_id))
    notify("Ready" if ready else "Installed — local services need attention", 100 if ready else 90)

    if stop_after_doctor:
        runtime.stop_all()

    human = install_dir / "sentra-human.exe"
    control = install_dir / "sentra-desktop.exe"
    if launch and not stop_after_doctor:
        launch_result: dict[str, Any] = {
            "requested": True,
            "deep_link": verification.get("next_url"),
        }
        if control.is_file():
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
    verification = runtime.connect_and_verify(timeout_s=12.0)
    ready = _installation_ready(verification, openai_required=True)
    notify("Ready" if ready else "Connection needs attention", 100 if ready else 85)

    result: dict[str, Any] = {
        "version": PRODUCT_VERSION,
        "install_dir": str(install_dir),
        "startup": verification.get("started"),
        "connect_verify": verification,
        "doctor": verification.get("status") or {},
        "web_models": web_models,
        "reused_install": True,
    }

    if launch:
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
        _unregister_startup(install_dir)
        _unregister_user_path(install_dir)
        _unregister_url_protocol(install_dir)
        _unregister_uninstall(install_dir)
        from .windows_integration import shortcuts
        shortcuts(install_dir,remove=True)
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


class InstallerWizard:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

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
        self.browser_setup_var = tk.BooleanVar(value=False)
        self.git_var = tk.BooleanVar(value=False)
        self.docker_var = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Install SENTRA — local use works without OpenAI")
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
            text="Recolher  ⌃" if self.openai_expanded else "Configurar  ⌄"
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
        """Resume already-installed SENTRA without reinstalling the payload."""
        from tkinter import messagebox
        try:
            _validate_sentra_install(install_dir)
            launcher = install_dir / "sentra-desktop.exe"
            if not launcher.is_file():
                raise FileNotFoundError("SENTRA Desktop launcher is missing; repair Setup first")
            target_view = (
                "sentra://openai-enroll"
                if self.browser_setup_var.get() else "sentra://onboarding"
            )
            if self.browser_setup_var.get():
                paths = ProductPaths.default(install_dir)
                settings = ProductSettings.load(paths.settings)
                selected_profile = self.profile.get()
                selected_scope = self.access_scope.get()
                changed = (settings.profile != selected_profile or settings.access_scope != selected_scope)
                settings.profile = selected_profile
                settings.access_scope = selected_scope
                if selected_profile == "Full":
                    changed = changed or bool(settings.tool_allowlist)
                    changed = changed or any(
                        set(settings.workspace_permissions.get(root) or ()) != {"read", "write", "execute"}
                        for root in settings.allowed_roots
                    )
                    settings.tool_allowlist = []
                    settings.workspace_permissions = {
                        root: ["read", "write", "execute"] for root in settings.allowed_roots
                    }
                settings.autostart_mcp = settings.autostart_relay = settings.autostart_tunnel = True
                settings.save(paths.settings)
                if changed:
                    LocalRuntime(paths, settings).stop_all()
                authorize_installer_enrollment(ProductPaths.default(install_dir))
            subprocess.Popen(
                [str(launcher), "--open-url", target_view],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.root.destroy()
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("SENTRA Setup", _friendly_install_error(exc))

    def _primary_action(self) -> None:
        """Reuse installed artifacts; local use never demands an OpenAI key."""
        has_tunnel = bool(self.tunnel_id.get().strip())
        has_key = bool(self.runtime_key.get().strip())
        if has_tunnel != has_key:
            from tkinter import messagebox

            messagebox.showerror(
                "SENTRA Setup",
                "Tunnel ID and Runtime API key are a pair. Fill both values to install and connect now, "
                "or clear both to install SENTRA first and connect later.",
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
                _validate_sentra_install(install_dir)
            except (OSError, ValueError, RuntimeError) as exc:
                from tkinter import messagebox
                messagebox.showerror("SENTRA Setup", _friendly_install_error(exc))
                return
            self._installed = all(
                (install_dir / name).is_file()
                for name in (*PRODUCTS, "tunnel-client.exe")
            )
        if self._installed and not has_tunnel:
            self._open_existing_install(install_dir)
        else:
            self._install(require_openai=has_tunnel and has_key)

    def _install(self, require_openai: bool = True) -> None:
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

        def worker() -> None:
            try:
                if require_openai and self._installed:
                    result = connect_installed_openai(
                        install_dir=Path(self.install_dir.get()),
                        tunnel_id=tunnel_id,
                        runtime_key=runtime_key,
                        launch=False,
                        progress=self._progress_callback,
                    )
                    self.root.after(0, lambda: self.runtime_key.set(""))
                    verification = result["connect_verify"]
                    install_dir = Path(self.install_dir.get()).expanduser().resolve()
                    control = install_dir / "sentra-desktop.exe"
                    if control.is_file():
                        ready = _installation_ready(verification, openai_required=True)
                        command = [str(control), "--hidden"] if ready else [
                            str(control), "--open-url", str(verification.get("next_url") or "sentra://onboarding")
                        ]
                        subprocess.Popen(
                            command,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                else:
                    result = install(
                        install_dir=Path(self.install_dir.get()),
                        workspace=Path(self.workspace.get()) if self.workspace.get().strip() else None,
                        profile=self.profile.get(),
                        access_scope=self.access_scope.get(),
                        tunnel_id=tunnel_id,
                        runtime_key=runtime_key,
                        install_git=self.git_var.get(),
                        install_docker=self.docker_var.get(),
                        # If the user opted into browser enrollment, the
                        # installer launches that one deep link after local
                        # installation instead of opening a duplicate Desktop.
                        launch=not (
                            bool(self.browser_setup_var.get()) and not require_openai
                        ),
                        progress=self._progress_callback,
                    )
                    verification = result["connect_verify"]
                if not require_openai:
                    def installed() -> None:
                        self._installed = True
                        self.status.set(
                            "SENTRA installed. Local tools are available; connect ChatGPT later if desired."
                        )
                        self.progress_value.set(100 if verification.get("core_ready") else 80)
                        if self.browser_setup_var.get():
                            desktop = Path(self.install_dir.get()).expanduser().resolve() / "sentra-desktop.exe"
                            try:
                                if not desktop.is_file():
                                    raise FileNotFoundError("SENTRA Desktop launcher is missing; repair Setup first")
                                authorize_installer_enrollment(ProductPaths.default(desktop.parent))
                                subprocess.Popen(
                                    [str(desktop), "--open-url", "sentra://openai-enroll"],
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                )
                            except (OSError, ValueError, RuntimeError) as exc:
                                error = _friendly_install_error(exc)
                                self.status.set("SENTRA local instalado. A configuração automática precisa de atenção.")
                                self.connect_hint.configure(text=error.replace("\n\n", " — "))
                                # This callback executes after the worker's try
                                # block. Always unlock before showing the error.
                                self.install_button.configure(
                                    state="normal", text="Tentar configuração novamente  →",
                                    command=self._primary_action,
                                )
                                messagebox.showerror("SENTRA Setup", error)
                                return
                            self.connect_hint.configure(
                                text="Installer consent saved. SENTRA Desktop will create the key with All permissions and verify the connection after login."
                            )
                        else:
                            self.connect_hint.configure(
                                text="Local setup finished. To enable ChatGPT, open SENTRA Desktop → Quick Start."
                            )
                        self.install_button.configure(
                            state="normal", text="Finish", command=self.root.destroy,
                        )

                    self.root.after(0, installed)
                    return

                ready = _installation_ready(verification, openai_required=True)
                if ready:
                    text = (
                        "Local MCP and the secure OpenAI tunnel are verified. Complete or verify the ChatGPT plugin connection. "
                        "The optional Edge browser plugin can be enabled later from Advanced."
                    )
                elif verification.get("core_ready"):
                    text = (
                        "SENTRA local is ready. ChatGPT connection can be repaired later "
                        "without blocking local work."
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
                    if ready:
                        self.progress_value.set(100)
                        self.status.set(f"Step 3 of 3 — Ready. {text}")
                        self.install_button.configure(
                            state="normal",
                            text="Finish",
                            command=self.root.destroy,
                        )
                    else:
                        self.progress_value.set(75)
                        self.status.set(f"Step 2 of 3 — Connection needs attention. {text}")
                        self.install_button.configure(
                            state="normal",
                            text="Retry Connect OpenAI",
                            command=lambda: self._install(require_openai=True),
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

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="sentra-installer")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--keep-config", action="store_true")
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
    args = parser.parse_args(argv)
    if args.uninstall:
        print(json.dumps(uninstall(
            Path(args.install_dir),
            keep_config=args.keep_config,
            state_dir=Path(args.state_dir) if args.state_dir else None,
            unregister_system=not args.no_system_registration,
        )))
        return 0
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
            launch=not args.no_launch,
            state_dir=Path(args.state_dir) if args.state_dir else None,
            register_system=not args.no_system_registration,
            mcp_port=args.mcp_port,
            relay_port=args.relay_port,
            stop_after_doctor=args.stop_after_doctor,
        )
    except Exception as exc:
        from sentra_mcp.errors import sanitize_error
        failure = {"ok": False, "error_type": type(exc).__name__,
                   "message": sanitize_error(_friendly_install_error(exc))[:2000]}
        print(json.dumps(failure), file=sys.stderr)
        # Windowed PyInstaller has no stderr. Persist a bounded diagnostic and
        # return normally so --silent never leaves an unattended error dialog.
        error_root = Path(args.state_dir) if args.state_dir else ProductPaths.default(Path(args.install_dir)).state_dir
        try:
            error_root.mkdir(parents=True, exist_ok=True)
            (error_root / "installer-error.json").write_text(json.dumps(failure), encoding="utf-8")
        except OSError:
            pass
        return 2
    print(json.dumps(result, indent=2))
    verification = result.get("connect_verify") or {}
    if verification:
        core_ready = bool(verification.get("core_ready"))
    else:
        doctor = result.get("doctor") or {}
        core_ready = bool(doctor.get("mcp", {}).get("ok")) and bool(
            doctor.get("relay", {}).get("ok")
        )
    return 0 if core_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
