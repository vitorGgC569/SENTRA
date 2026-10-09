"""Workspace path authority excludes nested central storage."""
from pathlib import Path

from sentra_executors.rpa import AuthorizedPaths


def workspace_paths(workspace_root,central_root):
    workspace=Path(workspace_root).resolve(strict=True)
    private=Path(central_root).resolve(strict=True)
    if workspace==private:raise ValueError("machine workspace cannot be central storage")
    excluded=(str(private),) if private.is_relative_to(workspace) else ()
    return AuthorizedPaths((str(workspace),),(str(workspace),),excluded_roots=excluded)
