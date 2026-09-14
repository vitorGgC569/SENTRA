"""One path boundary shared by repository reads, patches and sandbox copies."""
from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath
from typing import Iterator


class PathAccessError(PermissionError):
    pass


EXCLUDED_DIRS = frozenset({
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules",
    "auxiliares", "runs", "browser_profiles", ".edge-profile", ".ssh", ".aws",
    ".azure", ".gnupg", ".codex", ".claude", ".docker", ".oma",
})
SECRET_NAMES = frozenset({"auth.json", "credentials.json", "credentials", "cookies.json",
                          "storage_state.json", "id_rsa", "id_ed25519", ".netrc"})


def is_private_path(relative: Path) -> bool:
    parts = [p.casefold() for p in relative.parts]
    if any(p in EXCLUDED_DIRS for p in parts):
        return True
    name = parts[-1] if parts else ""
    return (name in SECRET_NAMES or name == ".env" or name.startswith(".env.")
            or name.endswith((".pem", ".key", ".p12", ".pfx")))


def resolve_workspace_path(root: Path, raw: str, *, working_directory: str = ".",
                           allow_private: bool = False) -> Path:
    """Reject absolute/drive/UNC/device paths and resolve links before containment.

    Windows syntax is rejected on every host, including alternate data streams
    and reserved devices. No caller can grant itself a root through a directive.
    """
    root = Path(root).resolve(strict=True)
    for value in (raw, working_directory):
        if not isinstance(value, str):
            raise PathAccessError("workspace path must be a string")
        win = PureWindowsPath(value)
        if (not value or "\x00" in value
                or Path(value).is_absolute() or win.drive or win.root or ":" in value):
            raise PathAccessError(f"workspace escape: absolute/device path blocked: {value!r}")
        for part in value.replace("\\", "/").split("/"):
            if part in ("", ".", ".."):
                continue
            if part.endswith((".", " ")) or re.fullmatch(
                    r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
                raise PathAccessError(f"workspace escape: device/ambiguous path: {value!r}")
    lexical = root / working_directory.replace("\\", "/") / raw.replace("\\", "/")
    target = lexical.resolve()
    try:
        relative = target.relative_to(root)
        lexical_relative = lexical.relative_to(root)
    except ValueError as exc:
        raise PathAccessError(f"workspace escape blocked: {raw!r}") from exc
    if not allow_private and (is_private_path(relative) or is_private_path(lexical_relative)):
        raise PathAccessError(f"private/runtime path blocked: {raw!r}")
    # Never expose a credential or mutate a file through another hardlink.
    if target.is_file() and target.stat().st_nlink > 1:
        raise PathAccessError(f"hard-linked file blocked: {raw!r}")
    return target


def iter_workspace_files(root: Path, scope: str = ".", *, max_files: int = 10000) -> Iterator[Path]:
    root = Path(root).resolve()
    base = resolve_workspace_path(root, scope)
    if base.is_file():
        yield base
        return
    count = 0
    for directory, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.casefold() not in EXCLUDED_DIRS
                         and not (Path(directory) / d).is_symlink()
                         and not getattr(Path(directory) / d, "is_junction", lambda: False)())
        for name in sorted(files):
            p = Path(directory) / name
            try:
                checked = resolve_workspace_path(root, p.relative_to(root).as_posix())
            except (PathAccessError, OSError):
                continue
            if p.is_symlink() or not checked.is_file():
                continue
            yield checked
            count += 1
            if count >= max_files:
                return
