"""Installed PyInstaller support directories; no launch-time extraction."""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from .windows_paths import filesystem_path


def support_name(executable: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9-]+\.exe", executable):
        raise ValueError("invalid component executable")
    return "_runtime_" + executable[:-4]


def support_inventory(root: Path, executables) -> dict[str, dict]:
    root = Path(filesystem_path(root))
    result = {}
    for executable in executables:
        directory = Path(root) / support_name(executable)
        if not directory.exists():
            continue  # Native launchers and legacy one-file distributions.
        if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()) or not directory.is_dir():
            raise ValueError("invalid component support directory")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("linked component support file")
            if path.is_file():
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                result[path.relative_to(root).as_posix()] = {"sha256": digest, "bytes": path.stat().st_size}
    return result


def copy_support(source: Path, destination: Path, executable: str) -> list[str]:
    name = support_name(executable)
    tree = Path(source) / name
    if not tree.exists():
        return []
    inventory = support_inventory(Path(source), (executable,))
    target = Path(destination) / name
    if target.is_symlink() or not target.resolve().is_relative_to(Path(destination).resolve()):
        raise ValueError("component target escaped installation")
    from functools import partial
    from .product_copy import copy_product_file
    shutil.copytree(filesystem_path(tree), filesystem_path(target), dirs_exist_ok=True,
                    copy_function=partial(copy_product_file, root=destination))
    return list(inventory)
