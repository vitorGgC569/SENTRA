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
from typing import Any

from sentra_version import PRODUCT_VERSION

from .local_runtime import LocalRuntime
from .product import ProductPaths, ProductSettings, configure_tunnel, ensure_browser_token

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

PRODUCTS = (
    "sentra-mcp.exe", "sentra-browser-relay.exe", "sentra-desktop.exe",
    "sentra-agent.exe", "sentra-diagnostics.exe", "sentra-admin.exe",
    "sentra-update-helper.exe", "sentra-oma.exe",
)

def payload_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "payload"
    return Path(__file__).resolve().parents[1] / "dist"


def extension_source() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "edge_extension"
    return Path(__file__).resolve().parents[1] / "edge_extension"


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


def _copy_product_files(install_dir: Path) -> None:
    source = payload_root()
    if not source.is_dir():
        raise FileNotFoundError(f"installer payload missing: {source}")
    install_dir.mkdir(parents=True, exist_ok=True)
    for name in PRODUCTS:
        candidate = source / name
        if not candidate.is_file():
            raise FileNotFoundError(f"release payload missing {name}")
        shutil.copy2(candidate, install_dir / name)
    ext_source = extension_source()
    if not ext_source.is_dir():
        raise FileNotFoundError("Edge extension payload is missing")
    target = install_dir / "edge_extension"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(ext_source, target)
    if getattr(sys, "frozen", False):
        shutil.copy2(Path(sys.executable), install_dir / "sentra-installer.exe")


def _write_install_marker(install_dir: Path) -> Path:
    marker = install_dir / INSTALL_MARKER
    existing_id = ""
    if marker.is_file():
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing_id = str(existing.get("installation_id") or "")
        except (OSError, json.JSONDecodeError):
            existing_id = ""
    payload = {
        "product": "SENTRA Desktop",
        "version": PRODUCT_VERSION,
        "installation_id": existing_id or str(uuid.uuid4()),
        "installed_at": time.time(),
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


def _unregister_startup() -> None:
    if os.name != "nt":
        return
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, "SENTRA Desktop")
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
            "DisplayIcon": str(install_dir / "sentra-desktop.exe"),
            "UninstallString": f'"{install_dir / "sentra-installer.exe"}" --uninstall',
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)


def _unregister_uninstall() -> None:
    if os.name != "nt":
        return
    import winreg
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
        f"$root=[IO.Path]::GetFullPath('{escaped}');"
        f"$selfPid={current_pid};$selfParent={parent_pid};"
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|"
        "Where-Object{$_.ProcessId -ne $selfPid -and $_.ProcessId -ne $selfParent "
        "-and $_.ExecutablePath -and "
        "$_.ExecutablePath.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)}|"
        "ForEach-Object{try{Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop}catch{}}"
    )
    _run(["powershell.exe", "-NoProfile", "-Command", script], timeout=30)


def install(
    *,
    install_dir: Path,
    workspace: Path | None = None,
    profile: str | None = None,
    tunnel_id: str = "",
    runtime_key: str = "",
    tunnel_archive: Path | None = None,
    install_git: bool = True,
    install_docker: bool = False,
    launch: bool = True,
    state_dir: Path | None = None,
    register_system: bool = True,
    mcp_port: int | None = None,
    relay_port: int | None = None,
    stop_after_doctor: bool = False,
) -> dict[str, Any]:
    install_dir = install_dir.expanduser().resolve()
    paths = (
        ProductPaths(install_dir, state_dir.expanduser().resolve())
        if state_dir is not None
        else ProductPaths.default(install_dir)
    )
    result: dict[str, Any] = {"version": PRODUCT_VERSION, "install_dir": str(install_dir)}
    if install_git and not command_exists("git"):
        result["git_install"] = install_winget_package("Git.Git")
    if install_docker and not command_exists("docker"):
        result["docker_install"] = install_winget_package("Docker.DockerDesktop")
    _copy_product_files(install_dir)
    result["install_marker"] = str(_write_install_marker(install_dir))
    result["tunnel_client"] = download_tunnel_client(install_dir, tunnel_archive)
    settings = ProductSettings.load(paths.settings)
    if profile is not None:
        settings.profile = profile
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
    ensure_browser_token(paths)
    if tunnel_id or runtime_key:
        if not (tunnel_id and runtime_key):
            raise ValueError("both tunnel_id and Runtime API key are required")
        configure_tunnel(paths, tunnel_id, runtime_key)
    if register_system:
        _register_startup(install_dir)
        _register_uninstall(install_dir)
    runtime = LocalRuntime(paths, settings)
    startup = runtime.start_all()
    result["startup"] = startup
    deadline = time.time() + 12
    while time.time() < deadline:
        status = runtime.status()
        if status.get("mcp", {}).get("ok") and status.get("relay", {}).get("ok", True):
            break
        time.sleep(0.5)
    result["doctor"] = runtime.status()
    if stop_after_doctor:
        runtime.stop_all()
    if launch and not stop_after_doctor and (install_dir / "sentra-desktop.exe").is_file():
        subprocess.Popen(
            [str(install_dir / "sentra-desktop.exe")],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
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
        _unregister_startup()
        _unregister_uninstall()
    if not keep_config:
        shutil.rmtree(paths.state_dir, ignore_errors=True)
    helper = install_dir / "sentra-update-helper.exe"
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
    shutil.rmtree(install_dir, ignore_errors=False)
    return {"ok": True, "kept_config": keep_config, "cleanup_scheduled": False}


class InstallerWizard:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = tk.Tk()
        self.root.title(f"SENTRA Setup {PRODUCT_VERSION}")
        self.root.geometry("720x600")
        self.install_dir = tk.StringVar(value=str(ProductPaths.default().install_dir))
        self.workspace = tk.StringVar()
        self.profile = tk.StringVar(value="Developer")
        self.tunnel_id = tk.StringVar()
        self.runtime_key = tk.StringVar()
        self.git_var = tk.BooleanVar(value=True)
        self.docker_var = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready to install")
        self._build()
    def _build(self) -> None:
        from tkinter import ttk
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="SENTRA Desktop", font=("Segoe UI", 20, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text="Install → secure tunnel → doctor → Ready", font=("Segoe UI", 10)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 18))
        rows = [
            ("Install folder", self.install_dir, False),
            ("Workspace", self.workspace, False),
            ("Tunnel ID", self.tunnel_id, False),
            ("Runtime API key", self.runtime_key, True),
        ]
        for row, (label, variable, secret) in enumerate(rows, start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=variable, show="•" if secret else "").grid(row=row, column=1, sticky="ew", padx=6)
            if label == "Workspace":
                ttk.Button(frame, text="Browse", command=self._browse).grid(row=row, column=2)
        ttk.Label(frame, text="Profile").grid(row=6, column=0, sticky="w", pady=5)
        ttk.Combobox(frame, textvariable=self.profile, values=("Safe", "Developer", "Full"), state="readonly").grid(row=6, column=1, sticky="ew", padx=6)
        ttk.Checkbutton(frame, text="Install Git with winget if missing", variable=self.git_var).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(frame, text="Install Docker Desktop with winget if missing", variable=self.docker_var).grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="The Runtime API key is stored with Windows DPAPI and is never written in plaintext.", wraplength=620).grid(row=9, column=0, columnspan=3, sticky="w", pady=12)
        ttk.Button(frame, text="Open OpenAI Tunnels", command=lambda: __import__("webbrowser").open("https://platform.openai.com/settings/organization/tunnels")).grid(row=10, column=0, sticky="w")
        ttk.Button(frame, text="Install SENTRA", command=self._install).grid(row=10, column=2, sticky="e")
        ttk.Label(frame, textvariable=self.status, wraplength=650).grid(row=11, column=0, columnspan=3, sticky="w", pady=18)
        frame.columnconfigure(1, weight=1)

    def _browse(self) -> None:
        from tkinter import filedialog
        value = filedialog.askdirectory()
        if value:
            self.workspace.set(value)

    def _install(self) -> None:
        from tkinter import messagebox
        self.status.set("Installing real components…")
        self.root.update_idletasks()

        def worker() -> None:
            try:
                result = install(
                    install_dir=Path(self.install_dir.get()),
                    workspace=Path(self.workspace.get()) if self.workspace.get().strip() else None,
                    profile=self.profile.get(),
                    tunnel_id=self.tunnel_id.get().strip(),
                    runtime_key=self.runtime_key.get().strip(),
                    install_git=self.git_var.get(),
                    install_docker=self.docker_var.get(),
                )
                doctor = result["doctor"]
                ready = doctor.get("mcp", {}).get("ok") and doctor.get("tunnel", {}).get("ok")
                text = "SENTRA Ready" if ready else "Installed. Complete Edge/tunnel onboarding shown in SENTRA Desktop."
                self.root.after(0, lambda: self.status.set(text))
                self.root.after(0, lambda: messagebox.showinfo("SENTRA Setup", text))
            except Exception as exc:
                self.root.after(0, lambda: self.status.set("Installation failed"))
                self.root.after(0, lambda: messagebox.showerror("SENTRA Setup", str(exc)))
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
    parser.add_argument("--tunnel-id", default="")
    parser.add_argument(
        "--runtime-key-env",
        default="CONTROL_PLANE_API_KEY",
        help="Environment variable containing the Runtime API key; never pass the secret on the command line.",
    )
    parser.add_argument("--tunnel-archive")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--install-docker", action="store_true")
    parser.add_argument("--no-git", action="store_true")
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
    result = install(
        install_dir=Path(args.install_dir),
        workspace=Path(args.workspace) if args.workspace else None,
        profile=args.profile,
        tunnel_id=args.tunnel_id,
        runtime_key=os.environ.get(args.runtime_key_env, "") if args.tunnel_id else "",
        tunnel_archive=Path(args.tunnel_archive) if args.tunnel_archive else None,
        install_git=not args.no_git,
        install_docker=args.install_docker,
        launch=not args.no_launch,
        state_dir=Path(args.state_dir) if args.state_dir else None,
        register_system=not args.no_system_registration,
        mcp_port=args.mcp_port,
        relay_port=args.relay_port,
        stop_after_doctor=args.stop_after_doctor,
    )
    print(json.dumps(result, indent=2))
    doctor = result.get("doctor") or {}
    core_ready = bool(doctor.get("mcp", {}).get("ok")) and bool(
        doctor.get("relay", {}).get("ok")
    )
    return 0 if core_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
