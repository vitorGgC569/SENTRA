"""Per-user launch shortcuts with target ownership checks and literal paths."""
import json
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import shutil
import tempfile


class ShortcutRegistrationError(RuntimeError):
    """The Windows Shell could not persist a per-user launch shortcut."""


def _shortcut_items(install_dir: Path, programs: Path, desktop: Path, desktop_executable: bool):
    items = [(programs / "SENTRA/SENTRA Desktop.lnk", install_dir / "sentra-human.exe"),
             (programs / "SENTRA/SENTRA Canvas.lnk", install_dir / "sentra-canvas.exe")]
    if not desktop_executable:
        items.append((desktop / "SENTRA.lnk", install_dir / "sentra-canvas.exe"))
    return items


def _native_shortcuts(install_dir, remove, programs_dir, desktop_dir, desktop_executable):
    # Every call owns its STA. A caller's GUI/COM apartment is left unchanged.
    import pythoncom
    # GetPath returns native file timestamps. pywin32 loads this helper by
    # name; the explicit import also includes it in the frozen executable.
    import win32timezone  # noqa: F401
    from win32com.shell import shell, shellcon

    def apply():
        programs = Path(programs_dir) if programs_dir is not None else Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, 0, 0))
        desktop = Path(desktop_dir) if desktop_dir is not None else Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, 0, 0))

        def link():
            return pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)

        def target_of(path):
            shortcut = link()
            shortcut.QueryInterface(pythoncom.IID_IPersistFile).Load(str(path), 0)  # STGM_READ
            # Read the stored target; never resolve/search for it or launch it.
            return shortcut.GetPath(shell.SLGP_RAWPATH)[0]

        if desktop_executable and not remove:
            legacy = desktop / "SENTRA.lnk"
            if legacy.is_file() and os.path.normcase(target_of(legacy)) == os.path.normcase(str(install_dir / "sentra-canvas.exe")):
                legacy.unlink()
        changed = []
        for path, target in _shortcut_items(install_dir, programs, desktop, desktop_executable):
            if remove:
                if path.is_file() and os.path.normcase(target_of(path)) == os.path.normcase(str(target)):
                    path.unlink()
                    changed.append(str(path))
            else:
                if not target.is_file():
                    raise FileNotFoundError("Shortcut target is missing: " + target.name)
                path.parent.mkdir(parents=True, exist_ok=True)
                shortcut = link()
                shortcut.SetPath(str(target))
                shortcut.SetWorkingDirectory(str(install_dir))
                shortcut.SetIconLocation(str(target), 0)
                shortcut.SetDescription("SENTRA")
                shortcut.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 1)
                changed.append(str(path))
        return {"paths": changed, "action": "unregister" if remove else "register", "desktop_dir": str(desktop)}

    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    try:
        return apply()
    except pythoncom.com_error as exc:
        raise ShortcutRegistrationError("Windows Shell shortcut registration failed (HRESULT " + str(exc.hresult) + ")") from None
    finally:
        pythoncom.CoUninitialize()


def shortcuts(install_dir: Path, *, remove=False, programs_dir: Path | None = None, desktop_dir: Path | None = None, desktop_executable=False):
    if os.name != "nt":
        return {"paths": [], "supported": False}
    install_dir = Path(install_dir).resolve()
    programs_dir = Path(programs_dir).resolve() if programs_dir is not None else None
    desktop_dir = Path(desktop_dir).resolve() if desktop_dir is not None else None
    # IShellLink/IPersistFile are in-process Shell APIs. PowerShell startup and
    # WScript activation are no longer part of unattended installation.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="SENTRA-shortcuts") as worker:
        value = worker.submit(_native_shortcuts, install_dir, remove, programs_dir, desktop_dir, desktop_executable).result()
    if desktop_executable:
        entry = install_desktop_executable(install_dir, Path(value["desktop_dir"]), remove=remove)
        if entry:
            value["paths"].append(str(entry))
    return value


def check_shortcuts_runtime(report: Path | None = None) -> dict:
    """Exercise frozen native dependencies only in a private disposable folder."""
    result = {"schema": 1, "ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "backend": "IShellLink/IPersistFile", "created": False,
              "idempotent": False, "removed": False, "starts_product_services": False,
              "accesses_browser_or_account": False, "changes_user_shortcut_folders": False}
    try:
        with tempfile.TemporaryDirectory(prefix="sentra-native-shortcuts-check-") as temporary:
            root = Path(temporary).resolve()
            assert root.parent == Path(tempfile.gettempdir()).resolve() and not root.is_symlink() and not root.is_junction()
            install = root / "installed"
            install.mkdir()
            for name in ("sentra-human.exe", "sentra-canvas.exe"):
                (install / name).write_bytes(b"owned shortcut fixture; never executed")
            options = {"programs_dir": root / "programs", "desktop_dir": root / "desktop"}
            initial = shortcuts(install, **options)
            result["created"] = len(initial["paths"]) == 3 and all(Path(p).is_file() for p in initial["paths"])
            result["idempotent"] = shortcuts(install, **options)["paths"] == initial["paths"]
            removed = shortcuts(install, remove=True, **options)
            result["removed"] = removed["paths"] == initial["paths"] and not any(Path(p).exists() for p in initial["paths"])
        result["ok"] = all(result[k] for k in ("created", "idempotent", "removed"))
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    if report is not None:
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def install_desktop_executable(install_dir: Path, desktop_dir: Path, *, remove=False):
    """Publish/remove only our registered launcher; never replace an unrelated EXE."""
    from .installer_preflight import file_hash
    install_dir, desktop_dir = Path(install_dir).resolve(), Path(desktop_dir).resolve()
    target = desktop_dir / "SENTRA.exe"
    receipt = install_dir / "desktop-launcher.json"
    previous = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}
    old_digest = file_hash(target) if target.is_file() and not target.is_symlink() else None
    owned = (previous.get("target") == str(target) and old_digest is not None
             and old_digest in (previous.get("sha256"), previous.get("previous_sha256")))
    if remove:
        if owned:
            target.unlink()
            receipt.unlink(missing_ok=True)
            return target
        return None
    source = install_dir / "sentra-launcher.exe"
    if not source.is_file():
        raise FileNotFoundError("SENTRA desktop executable is missing from the installation")
    if target.exists() and not owned:
        raise FileExistsError("SENTRA.exe already exists on the desktop and is not owned by this installation")
    desktop_dir.mkdir(parents=True, exist_ok=True)
    fd, staged_name = tempfile.mkstemp(prefix=".sentra-launcher-", suffix=".tmp", dir=desktop_dir)
    os.close(fd)
    staged = Path(staged_name)
    try:
        shutil.copy2(source, staged)
        digest = file_hash(staged)
        # Persist identity before publishing, so a crash immediately after
        # replacement remains repairable with these same verified bytes.
        pending = receipt.with_suffix(".tmp")
        pending.write_text(json.dumps({"target": str(target), "sha256": digest,
                                      "previous_sha256": old_digest if owned else None}), encoding="utf-8")
        pending.replace(receipt)
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)
    return target
