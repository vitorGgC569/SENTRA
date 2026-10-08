"""Transactional updater helper executed outside the installed directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from .windows_paths import filesystem_path
from .installation_lock import serialized_update

INSTALL_MARKER = ".sentra-install.json"


def _wait_pid(pid: int, timeout_s: float = 60.0) -> None:
    if pid <= 0:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if os.name == "nt":
            probe = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if str(pid) not in probe.stdout:
                return
        else:
            try:
                os.kill(pid, 0)
            except OSError:
                return
        time.sleep(0.25)
    raise TimeoutError(f"process {pid} did not exit")

def _validate_install_dir(path: Path, *, require_marker: bool = False) -> Path:
    root = path.expanduser().resolve()
    anchor = Path(root.anchor)
    if root == anchor or root == Path.home().resolve() or len(root.parts) < 3:
        raise ValueError("refusing unsafe install directory")
    if require_marker:
        marker = root / INSTALL_MARKER
        if not marker.is_file():
            raise ValueError("refusing operation without SENTRA install marker")
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("SENTRA install marker is unreadable") from exc
        if not isinstance(data, dict) or data.get("product") != "SENTRA Desktop":
            raise ValueError("invalid SENTRA install marker")
    return root


def _state_file() -> Path:
    override = os.environ.get("SENTRA_STATE_DIR", "").strip()
    state_root = Path(override).expanduser().resolve() if override else (Path.home() / ".sentra").resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    return state_root / "update-state.json"


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"source directory missing: {source}")
    if destination.exists():
        shutil.rmtree(filesystem_path(destination))
    shutil.copytree(filesystem_path(source), filesystem_path(destination))


def _start_desktop(install_dir: Path) -> None:
    human = install_dir / "sentra-human.exe"
    control = install_dir / "sentra-desktop.exe"
    target = human if human.is_file() else control
    if target.is_file():
        subprocess.Popen(
            [str(target)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

def _write_state(payload: dict[str, Any]) -> None:
    path = _state_file()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(path)


@serialized_update
def apply_update(
    installer: Path,
    install_dir: Path,
    *,
    parent_pid: int,
    version: str,
    manifest_url: str,
    state_dir: Path | None = None,
    register_system: bool = True,
    mcp_port: int | None = None,
    relay_port: int | None = None,
    stop_after_doctor: bool = False,
    restart_desktop: bool = True,
) -> int:
    install_dir = _validate_install_dir(
        install_dir,
        require_marker=install_dir.expanduser().resolve().exists(),
    )
    installer = installer.expanduser().resolve()
    if not installer.is_file() or installer.suffix.lower() != ".exe":
        raise FileNotFoundError("signed SENTRA setup executable is missing")
    marker = json.loads((install_dir / INSTALL_MARKER).read_text(encoding="utf-8"))
    identity = str(marker.get("installation_id") or "")
    if not identity:
        raise ValueError("repair installation identity with Setup before updating")
    _wait_pid(parent_pid)
    from .installer import _stop_installed_processes
    _stop_installed_processes(install_dir)
    namespace = hashlib.sha256((identity or str(install_dir)).encode()).hexdigest()
    rollback_root = install_dir.parent / "Rollback" / namespace
    backup = rollback_root / "previous"
    rollback_root.mkdir(parents=True, exist_ok=True)
    if install_dir.is_dir():
        _copy_tree(install_dir, backup)
    try:
        # Setup merges owned files; unrelated files remain in the destination.
        # Keep installation identity across update, while retaining state outside
        # the replaceable program tree (credentials and protected conversations).
        if (backup / INSTALL_MARKER).is_file():
            install_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / INSTALL_MARKER, install_dir / INSTALL_MARKER)
        command = [
            str(installer), "--silent", "--install-dir", str(install_dir),
            "--upgrade", "--no-launch", "--no-git",
        ]
        if mcp_port is not None:
            command += ["--mcp-port", str(mcp_port)]
        if relay_port is not None:
            command += ["--relay-port", str(relay_port)]
        if state_dir is not None:
            command += ["--state-dir", str(state_dir.expanduser().resolve())]
        if not register_system:
            command.append("--no-system-registration")
        if stop_after_doctor:
            command.append("--stop-after-doctor")
        tunnel_archives = list(installer.parent.glob("tunnel-client-v*-windows-amd64.zip"))
        if len(tunnel_archives) == 1:
            command += ["--tunnel-archive", str(tunnel_archives[0])]
        result = subprocess.run(
            command,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError(f"SENTRA setup exited with {result.returncode}")
        desktop = install_dir / "sentra-desktop.exe"
        if not desktop.is_file():
            raise RuntimeError("update completed without sentra-desktop.exe")
        _write_state({
            "version": version,
            "previous_backup": str(backup),
            "install_dir": str(install_dir),
            "manifest_url": manifest_url,
            "updated_at": time.time(),
        })
        if restart_desktop and not stop_after_doctor:
            _start_desktop(install_dir)
        return 0
    except Exception:
        if install_dir.exists():
            shutil.rmtree(filesystem_path(install_dir))
        if backup.is_dir():
            shutil.copytree(filesystem_path(backup), filesystem_path(install_dir))
            if restart_desktop:
                _start_desktop(install_dir)
        raise


@serialized_update
def rollback_update(
    install_dir: Path,
    *,
    parent_pid: int,
    restart_desktop: bool = True,
) -> int:
    install_dir = _validate_install_dir(install_dir, require_marker=True)
    state_path = _state_file()
    if not state_path.is_file():
        raise FileNotFoundError("no update rollback metadata is available")
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    if Path(str(state.get("install_dir") or "")).resolve() != install_dir:
        raise ValueError("rollback metadata belongs to another installation")
    backup = Path(str(state.get("previous_backup") or "")).expanduser().resolve()
    expected = (install_dir.parent / "Rollback").resolve()
    current_marker = json.loads((install_dir / INSTALL_MARKER).read_text(encoding="utf-8"))
    identity = str(current_marker.get("installation_id") or "")
    if not identity:
        raise ValueError("rollback requires a verified installation identity")
    expected /= hashlib.sha256(identity.encode()).hexdigest()
    if backup.parent.resolve() != expected or not backup.is_dir():
        raise FileNotFoundError("previous release backup is missing or outside rollback root")
    _validate_install_dir(backup, require_marker=True)
    backup_marker = json.loads((backup / INSTALL_MARKER).read_text(encoding="utf-8"))
    if backup_marker.get("installation_id") != current_marker.get("installation_id"):
        raise ValueError("rollback backup belongs to another installation identity")
    _wait_pid(parent_pid)
    from .installer import _stop_installed_processes
    _stop_installed_processes(install_dir)
    replaced = expected / ("replaced-" + uuid.uuid4().hex)
    saved_original = False
    try:
        if install_dir.is_dir():
            os.rename(filesystem_path(install_dir), filesystem_path(replaced))
            saved_original = True
        shutil.copytree(filesystem_path(backup), filesystem_path(install_dir))
        # Files added by the user after the update are outside the product
        # manifest and must survive switching program versions.
        owned = set(current_marker.get("owned_files") or []) | {INSTALL_MARKER}
        extended_replaced = Path(filesystem_path(replaced))
        for file in extended_replaced.rglob("*"):
            if not file.is_file() or not file.resolve().is_relative_to(extended_replaced.resolve()):
                continue
            relative = file.relative_to(extended_replaced)
            if relative.as_posix() in owned:
                continue
            destination = (install_dir / relative).resolve()
            if not destination.is_relative_to(install_dir):
                raise ValueError("rollback content escaped installation directory")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(filesystem_path(file), filesystem_path(destination))
        _write_state({
            "rolled_back_at": time.time(),
            "previous_backup": str(replaced),
            "install_dir": str(install_dir),
        })
        if restart_desktop:
            _start_desktop(install_dir)
        return 0
    except Exception:
        if saved_original:
            if install_dir.exists():
                shutil.rmtree(filesystem_path(install_dir))
            if replaced.is_dir():
                os.rename(filesystem_path(replaced), filesystem_path(install_dir))
        raise


def cleanup_install(install_dir: Path, *, parent_pid: int) -> int:
    root = _validate_install_dir(install_dir, require_marker=True)
    _wait_pid(parent_pid)
    from .installer import _stop_installed_processes
    _stop_installed_processes(root)
    marker = json.loads((root / INSTALL_MARKER).read_text(encoding="utf-8"))
    owned = marker.get("owned_files")
    if not isinstance(owned, list) or not owned:
        # Legacy markers prove the product identity, not ownership of every file.
        from .installer import PRODUCTS
        owned = [*PRODUCTS, "sentra-installer.exe", "tunnel-client.exe"]
    targets = []
    for name in owned:
        if not isinstance(name, str):
            raise ValueError("invalid installed file manifest")
        relative = Path(name)
        target = (root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not target.is_relative_to(root):
            raise ValueError("installed file manifest escaped install directory")
        if any((parent / INSTALL_MARKER).is_file() for parent in target.parents
               if parent != root and parent.is_relative_to(root)):
            continue
        targets.append(target)
    last_error: OSError | None = None
    for _ in range(30):
        try:
            for target in targets:
                Path(filesystem_path(target)).unlink(missing_ok=True)
            (root / INSTALL_MARKER).unlink(missing_ok=True)
            for folder in sorted((p for p in Path(filesystem_path(root)).rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                try: folder.rmdir()
                except OSError: pass
            try: root.rmdir()
            except OSError: pass
            return 0
        except OSError as exc:
            last_error = exc
        time.sleep(0.5)
    if last_error is not None:
        raise last_error
    raise RuntimeError("install directory remained after cleanup")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentra-update-helper")
    sub = parser.add_subparsers(dest="command", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--installer", required=True)
    apply.add_argument("--install-dir", required=True)
    apply.add_argument("--parent-pid", type=int, required=True)
    apply.add_argument("--version", required=True)
    apply.add_argument("--manifest-url", default="")
    apply.add_argument("--state-dir")
    apply.add_argument("--no-system-registration", action="store_true")
    apply.add_argument("--mcp-port", type=int)
    apply.add_argument("--relay-port", type=int)
    apply.add_argument("--stop-after-doctor", action="store_true")
    apply.add_argument("--no-desktop-restart", action="store_true")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--install-dir", required=True)
    rollback.add_argument("--parent-pid", type=int, required=True)
    rollback.add_argument("--state-dir")
    rollback.add_argument("--no-desktop-restart", action="store_true")
    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("--install-dir", required=True)
    cleanup.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    state_dir_value = getattr(args, "state_dir", None)
    if state_dir_value:
        os.environ["SENTRA_STATE_DIR"] = str(Path(state_dir_value).expanduser().resolve())
    try:
        if args.command == "apply":
            return apply_update(
                Path(args.installer),
                Path(args.install_dir),
                parent_pid=args.parent_pid,
                version=args.version,
                manifest_url=args.manifest_url,
                state_dir=Path(args.state_dir) if args.state_dir else None,
                register_system=not args.no_system_registration,
                mcp_port=args.mcp_port,
                relay_port=args.relay_port,
                stop_after_doctor=args.stop_after_doctor,
                restart_desktop=not args.no_desktop_restart,
            )
        if args.command == "rollback":
            return rollback_update(
                Path(args.install_dir),
                parent_pid=args.parent_pid,
                restart_desktop=not args.no_desktop_restart,
            )
        return cleanup_install(Path(args.install_dir), parent_pid=args.parent_pid)
    except Exception as exc:
        print(f"SENTRA update helper failed: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
