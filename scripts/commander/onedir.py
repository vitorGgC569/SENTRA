"""Publish each frozen executable together with its uniquely named runtime."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from sentra_remote.onedir import support_name, support_inventory


def publish_component(bundle: Path, destination: Path, executable: str) -> None:
    bundle, destination = Path(bundle).resolve(), Path(destination).resolve()
    runtime = support_name(executable)
    if (destination / ".sentra-install.json").exists():
        raise PermissionError("build output cannot replace an installed SENTRA; use Setup")
    if not (bundle / executable).is_file() or not (bundle / runtime / "python312.dll").is_file():
        raise RuntimeError("incomplete onedir bundle: " + executable)
    support_inventory(bundle, (executable,))  # Refuse linked dependency trees.
    destination.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=".onedir-backup-", dir=destination))
    moved, published = [], []
    try:
        for name in (runtime, executable):
            target = destination / name
            if target.is_symlink():
                raise ValueError("linked component destination")
            if target.exists():
                os.replace(target, backup / name)
                moved.append(name)
            os.replace(bundle / name, target)
            published.append(name)
    except BaseException:
        # Preserve the old complete component on failures, including a locked EXE.
        for name in reversed(published):
            target = destination / name
            if target.is_dir():
                if target.resolve().parent != destination:
                    raise ValueError("unsafe component rollback path")
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
        for name in reversed(moved):
            os.replace(backup / name, destination / name)
        raise
    finally:
        if backup.exists() and not any(backup.iterdir()):
            backup.rmdir()
    # At success this directory holds only the replaced component's old bytes.
    if backup.resolve().parent != destination:
        raise ValueError("unsafe component backup path")
    if backup.exists():
        shutil.rmtree(backup)
