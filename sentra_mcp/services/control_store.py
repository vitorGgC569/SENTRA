"""Storage boundary for SENTRA control-plane coordination state.

The local product remains SQLite/WAL. Services depend on this narrow boundary so a
hosted authority can add a transactional backend without changing domain models or
silently weakening local durability.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Protocol, runtime_checkable


CONTROL_PLANE_NAMESPACES = {
    "authorization": "authorization.sqlite3",
    "budget_policy": "budget-policies.sqlite3",
    "event_ingress": "event-ingress.sqlite3",
    "execution_workspace": "execution-workspaces.sqlite3",
    "governance": "governance.sqlite3",
    "plugin_worker": "plugin-workers.sqlite3",
    "session_checkpoint": "session-checkpoints.sqlite3",
    "task_ledger": "tasks.sqlite3",
}


class UnsupportedControlPlaneBackend(ValueError):
    """Raised when a configured backend has no audited SQL adapter."""


@runtime_checkable
class ControlPlaneStore(Protocol):
    """Connection factory used by control-plane services."""

    backend: str

    def path_for(self, namespace: str) -> Path | None:
        """Return a local database path when the backend has one."""

    def connect(self, namespace: str) -> sqlite3.Connection:
        """Return a configured DB-API connection for a logical namespace."""

    def describe(self) -> dict[str, object]:
        """Return non-secret backend metadata for diagnostics."""


class SQLiteControlPlaneStore:
    """SQLite/WAL implementation used by Desktop and single-node SENTRA."""

    backend = "sqlite"

    def __init__(
        self,
        state_root: Path | str,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        root = Path(state_root).resolve() / "durable"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @staticmethod
    def _filename(namespace: str) -> str:
        key = str(namespace or "").strip()
        try:
            return CONTROL_PLANE_NAMESPACES[key]
        except KeyError as exc:
            raise ValueError(f"unknown control-plane store namespace: {key!r}") from exc

    def path_for(self, namespace: str) -> Path:
        return self.root / self._filename(namespace)

    def connect(self, namespace: str) -> sqlite3.Connection:
        db = sqlite3.connect(
            str(self.path_for(namespace)),
            timeout=self.timeout_seconds,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA busy_timeout={int(self.timeout_seconds * 1000)}")
        return db

    def describe(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "root": str(self.root),
            "namespaces": sorted(CONTROL_PLANE_NAMESPACES),
            "wal": True,
            "synchronous": "FULL",
        }


def create_control_plane_store(
    state_root: Path | str,
    *,
    backend: str = "sqlite",
) -> ControlPlaneStore:
    """Create an audited store implementation.

    Postgres is intentionally not emulated by translating SQLite SQL at runtime.
    A hosted adapter must supply native schema/migrations and transaction semantics
    before it can become authoritative.
    """

    selected = str(backend or "sqlite").strip().lower()
    if selected == "sqlite":
        return SQLiteControlPlaneStore(state_root)
    raise UnsupportedControlPlaneBackend(
        f"control-plane backend {selected!r} is not available in this build"
    )
