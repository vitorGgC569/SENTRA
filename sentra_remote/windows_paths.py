"""Filesystem paths usable by deep packaged runtimes without OS policy changes."""
from __future__ import annotations

import os
from pathlib import Path


def filesystem_path(path: Path) -> str:
    value = str(path.expanduser().resolve())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    return "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
