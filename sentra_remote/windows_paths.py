"""Filesystem paths usable by deep packaged runtimes without OS policy changes."""
from __future__ import annotations

import os
from pathlib import Path


def filesystem_path(path: Path, *, resolve: bool = True) -> str:
    path = Path(path).expanduser()
    value = str(path.resolve() if resolve else path.absolute())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    return "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value


def resolved_path(path: Path, *, strict: bool = False) -> Path:
    """Resolve through the long-path API, returning ordinary paths for policy.

    Callers must still reject device/ADS inputs and check authorized roots.
    An internal Win32 prefix must never leak into a renderer's path authority.
    """
    path = Path(path)
    if os.name != 'nt':
        return path.resolve(strict=strict)
    value = str(Path(filesystem_path(path)).resolve(strict=strict))
    if value.startswith('\\\\?\\UNC\\'):
        value = '\\\\' + value[8:]
    elif value.startswith('\\\\?\\'):
        value = value[4:]
    return Path(value)
