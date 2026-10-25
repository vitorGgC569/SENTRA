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
from .windows_paths import filesystem_path, resolved_path
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
    root = resolved_path(path.expanduser())
    anchor = Path(root.anchor)
    if root == anchor or root == Path.home().resolve() or len(root.parts) < 3:
        raise ValueError("refusing unsafe install directory")
    if require_marker:
        marker = Path(filesystem_path(root / INSTALL_MARKER))
        if not marker.is_file():
            raise ValueError("refusing operation without SENTRA install marker")
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("SENTRA install marker is unreadable") from exc
        if not isinstance(data, dict) or data.get("product") != "SENTRA Desktop":
            raise ValueError("invalid SENTRA install marker")
    return root


def _state_file(install_dir: Path | None = None, state_dir: Path | None = None) -> Path:
    from .product import ProductPaths
    if state_dir is not None:
        state_root = Path(state_dir).expanduser().resolve()
    elif install_dir is not None:
        state_root = ProductPaths.default(install_dir).state_dir
    else:
        override = os.environ.get("SENTRA_STATE_DIR", "").strip()
        state_root = Path(override).expanduser().resolve() if override else (Path.home() / ".sentra").resolve()
    # Reading metadata must not create an unknown state directory.
    return state_root / "update-state.json"


def _require_offline_migration_contract(state_dir: Path | None, install_dir: Path) -> None:
    """Deny physical version switches that might reinterpret unversioned DBs.

    This helper is intentionally NOT a second grant authority. The future
    central owner-auth orchestration must stage/verify schema migrations and
    provide an explicit controlled handoff before this path is enabled.
    """
    from .product import ProductPaths
    selected = Path(state_dir or ProductPaths.default(install_dir).state_dir).expanduser().resolve()
    if not selected.exists():
        return
    # No DB contents are read. Never follow symbolic directory links.
    if selected.is_symlink():
        raise PermissionError("unsafe migration state directory")
    for current, dirs, files in os.walk(selected, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
        if any(name.lower().endswith((".db", ".sqlite", ".sqlite3")) for name in files):
            raise PermissionError("SQLite migration requires durable owner-auth and an offline staged snapshot")


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"source directory missing: {source}")
    if destination.exists():
        shutil.rmtree(filesystem_path(destination))
    shutil.copytree(filesystem_path(source), filesystem_path(destination))


def _start_desktop(install_dir: Path) -> None:
    canvas = install_dir / "sentra-canvas.exe"
    control = install_dir / "sentra-desktop.exe"
    human = install_dir / "sentra-human.exe"
    target = canvas if canvas.is_file() else (control if control.is_file() else human)
    if target.is_file():
        subprocess.Popen(
            [str(target)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

def _write_state(payload: dict[str, Any], *, install_dir: Path | None = None,
                 state_dir: Path | None = None) -> None:
    path = Path(filesystem_path(_state_file(install_dir, state_dir)))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as out:
        json.dump(payload, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    temp.replace(path)


@serialized_update
def apply_update(
    installer: Path, install_dir: Path, *, parent_pid: int, version: str,
    manifest_url: str, state_dir: Path | None = None, register_system: bool = True,
    mcp_port: int | None = None, relay_port: int | None = None,
    stop_after_doctor: bool = False, restart_desktop: bool = True,
    coordinated_handoff: Path | None = None,
) -> int:
    kwargs = dict(parent_pid=parent_pid, version=version, manifest_url=manifest_url,
        state_dir=state_dir, register_system=register_system, mcp_port=mcp_port,
        relay_port=relay_port, stop_after_doctor=stop_after_doctor,
        restart_desktop=restart_desktop, coordinated_handoff=coordinated_handoff)
    if coordinated_handoff is None:
        return _apply_update(installer, install_dir, **kwargs)
    _wait_pid(parent_pid)
    from .app_exit_update import load_handoff, helper_effect_context, read_helper_outcome
    value = load_handoff(coordinated_handoff, install_dir)
    context = helper_effect_context(value)
    kwargs['parent_pid'] = 0
    # Same central receipt/fence/grant, with the existing OS lock and keepalive.
    from sentra_runtime.contracts import OperationResult
    def persist_outcome():
        evidence = read_helper_outcome(coordinated_handoff, owner=value['owner'],
            operation_id=value['operation_id'], installation_id=value['installation_id'])
        if evidence['state'] not in {'SUCCEEDED', 'FAILED'}:
            raise RuntimeError('update helper outcome uncertain; never relaunch Setup')
        context.checkpoint()
        accepted = context.authority.record_result(context.receipt,
            OperationResult(value['operation_id'], evidence['state'],
                evidence={'handoff_sha256': evidence['handoff_sha256'],
                          'helper_pid': evidence['helper_pid'], 'result': evidence['result']}))
        if accepted is not True:
            raise RuntimeError('update central receipt unconfirmed; observe without reapplying')
    try:
        result = context.run_sync(_apply_update, installer, install_dir, **kwargs)
    except BaseException:
        try: persist_outcome()
        except Exception: pass
        raise
    persist_outcome()
    return result


def _apply_update(
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
    coordinated_handoff: Path | None = None,
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
    # Fail before stopping any process or copying a binary when durable
    # migration of the real SQLite state has not been coordinated by the host.
    if coordinated_handoff is None:
        _require_offline_migration_contract(state_dir, install_dir)
    namespace = hashlib.sha256(identity.encode()).hexdigest()
    rollback_root = install_dir.parent / "Rollback" / namespace
    from .program_stage import (require_no_interrupted_stage, stage_program_backup,
                                mark_program_stage)
    # Check for an earlier crash BEFORE any process is touched.
    require_no_interrupted_stage(rollback_root)
    _wait_pid(parent_pid)
    if coordinated_handoff is not None:
        from .app_exit_update import load_handoff
        handoff = load_handoff(coordinated_handoff, install_dir)
        if handoff['version'] != version or Path(handoff['installer']) != installer:
            raise PermissionError('coordinated update version/package mismatch')
        # Exclusive claim is created BEFORE Setup, never inferred from exit code.
        with coordinated_handoff.with_suffix('.claimed').open('x',encoding='utf-8') as claim:
            json.dump({'helper_pid':os.getpid(),'operation_id':handoff['operation_id']},claim)
            claim.flush();os.fsync(claim.fileno())
    else:
        from .installer import _stop_installed_processes
        _stop_installed_processes(install_dir)
    backup, stage_journal = stage_program_backup(install_dir, rollback_root, identity)
    try:
        mark_program_stage(stage_journal, "APPLYING", identity)
        # Setup merges owned files; unrelated files remain in the destination.
        # Keep installation identity across update, while retaining state outside
        # the replaceable program tree (credentials and protected conversations).
        if Path(filesystem_path(backup / INSTALL_MARKER)).is_file():
            install_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(filesystem_path(backup / INSTALL_MARKER), filesystem_path(install_dir / INSTALL_MARKER))
        command = [
            str(installer), "--silent", "--install-dir", str(install_dir),
            "--upgrade", "--no-launch", "--no-git",
        ]
        if coordinated_handoff is not None:
            command += ['--offline-handoff',str(coordinated_handoff)]
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
        if coordinated_handoff is not None:
            from .lifecycle_effects import checkpoint_effect
            checkpoint_effect()
        from .installer_engine import install_command
        command = install_command(installer, command[1:])
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
        if coordinated_handoff is not None:
            from .app_exit_update import verify_installed_components
            verify_installed_components(install_dir,handoff['components'])
        _write_state({
            "version": version,
            "previous_backup": str(backup),
            "install_dir": str(install_dir),
            "manifest_url": manifest_url,
            "updated_at": time.time(),
        }, install_dir=install_dir, state_dir=state_dir)
        mark_program_stage(stage_journal, "COMMITTED", identity)
        if coordinated_handoff is not None:
            from .app_exit_update import write_helper_outcome
            write_helper_outcome(coordinated_handoff,handoff,state='SUCCEEDED',
                result={'version':version,'phase':'COMMITTED','program_transaction_id':stage_journal.stem})
        if restart_desktop and not stop_after_doctor:
            _start_desktop(install_dir)
        return 0
    except Exception:
        # Crash recovery is an explicit owner action; never auto-run Setup again.
        mark_program_stage(stage_journal, "RECOVERY_REQUIRED", identity)
        from .program_stage import restore_failed_program_tree
        if Path(filesystem_path(backup)).is_dir():
            # Preserve a quarantined copy of the interrupted installer tree;
            # never erase unknown user files or silently retry Setup.
            restore_failed_program_tree(install_dir, backup, identity)
            mark_program_stage(stage_journal, "RESTORED", identity)
            if restart_desktop:
                _start_desktop(install_dir)
        if coordinated_handoff is not None:
            from .app_exit_update import write_helper_outcome
            write_helper_outcome(coordinated_handoff,handoff,state='FAILED',
                result={'phase':'RESTORED','version':version})
        raise


@serialized_update
def rollback_update(
    install_dir: Path,
    *,
    parent_pid: int,
    restart_desktop: bool = True,
) -> int:
    install_dir = _validate_install_dir(install_dir, require_marker=True)
    state_path = Path(filesystem_path(_state_file(install_dir)))
    if not state_path.is_file():
        raise FileNotFoundError("no update rollback metadata is available")
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    if Path(str(state.get("install_dir") or "")).resolve() != install_dir:
        raise ValueError("rollback metadata belongs to another installation")
    backup = resolved_path(Path(str(state.get("previous_backup") or "")).expanduser())
    expected = (install_dir.parent / "Rollback").resolve()
    current_marker = json.loads((install_dir / INSTALL_MARKER).read_text(encoding="utf-8"))
    identity = str(current_marker.get("installation_id") or "")
    if not identity:
        raise ValueError("rollback requires a verified installation identity")
    expected /= hashlib.sha256(identity.encode()).hexdigest()
    if resolved_path(backup.parent) != expected or not Path(filesystem_path(backup)).is_dir():
        raise FileNotFoundError("previous release backup is missing or outside rollback root")
    _validate_install_dir(backup, require_marker=True)
    backup_marker = json.loads(Path(filesystem_path(backup / INSTALL_MARKER)).read_text(encoding="utf-8"))
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
            Path(filesystem_path(destination.parent)).mkdir(parents=True, exist_ok=True)
            shutil.copy2(filesystem_path(file), filesystem_path(destination))
        _write_state({
            "rolled_back_at": time.time(),
            "previous_backup": str(replaced),
            "install_dir": str(install_dir),
        }, install_dir=install_dir)
        if restart_desktop:
            _start_desktop(install_dir)
        return 0
    except Exception:
        if saved_original:
            if install_dir.exists():
                shutil.rmtree(filesystem_path(install_dir))
            if Path(filesystem_path(replaced)).is_dir():
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
    apply.add_argument("--handoff-file", type=Path)
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
                coordinated_handoff=args.handoff_file,
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
