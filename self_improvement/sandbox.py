"""Sandbox — nunca experimentar na versão ativa. main -> branch/isolated -> tests -> DISCARD/CANDIDATE."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from workspace.sandbox import WorkspaceSandbox


@asynccontextmanager
async def isolated_copy(repo_root: Path):
    """Copia isolada do repo para experimentação; descarta no fim (DISCARD por padrão)."""
    sandbox = WorkspaceSandbox(repo_root)
    try:
        yield sandbox.root
    finally:
        sandbox.close()
