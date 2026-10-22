"""Storage boundary for SENTRA control-plane coordination state.

The local product remains SQLite/WAL. Services depend on this narrow boundary so a
hosted authority can add a transactional backend without changing domain models or
silently weakening local durability.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .postgres_store import PostgresConnection


CONTROL_PLANE_NAMESPACES = {
    "interop_projections": "interop-projections.sqlite3",
    "interop_interactions": "interop-interactions.sqlite3",
    "interop_installations": "interop-installations.sqlite3",
    "interop_push": "interop-push.sqlite3",
    "channels": "channels.sqlite3",
    "durable": "durable.sqlite3",
    "context": "context.sqlite3",
    "shell": "shell.sqlite3",
    "machine_input_control": "machine-input-control.sqlite3",
    "authorization": "authorization.sqlite3",
    "chat_access": "chat-access.sqlite3",
    "budget_policy": "budget-policies.sqlite3",
    "event_ingress": "event-ingress.sqlite3",
    "execution_workspace": "execution-workspaces.sqlite3",
    "governance": "governance.sqlite3",
    "plugin_worker": "plugin-workers.sqlite3",
    "plugin_bundle": "plugin-bundles.sqlite3",
    "session_checkpoint": "session-checkpoints.sqlite3",
    "task_ledger": "tasks.sqlite3",
    "canvas_collaboration": "canvas-collaboration.sqlite3",
    "machine_configuration": "machine-configuration.sqlite3",
    "experience_memory": "experience-memory.sqlite3",
    "plan_history": "plan-history.sqlite3",
    "provider_content": "provider-content.sqlite3",
    "telemetry_pipeline": "telemetry-pipeline.sqlite3",
}


class UnsupportedControlPlaneBackend(ValueError):
    """Raised when a configured backend has no audited SQL adapter."""


@runtime_checkable
class ControlPlaneStore(Protocol):
    """Connection factory used by control-plane services."""

    backend: str
    state_root: Path

    def path_for(self, namespace: str) -> Path | None:
        """Return a local database path when the backend has one."""

    def connect(self, namespace: str, *, shared: bool = False) -> sqlite3.Connection | PostgresConnection:
        """Return a configured DB-API connection for a logical namespace."""

    def assert_active(self) -> None:
        """Reject access after the selected authority changes."""

    def describe(self) -> dict[str, object]:
        """Return non-secret backend metadata for diagnostics."""


class AuthoritySQLiteConnection(sqlite3.Connection):
    """Existing connections cannot keep writing after authority cutover."""
    authority_store: SQLiteControlPlaneStore
    def _active(self):
        store = getattr(self,"authority_store",None)
        if store is not None:
            store.assert_active()
    def execute(self, *args, **kwargs):
        self._active()
        return super().execute(*args, **kwargs)
    def executemany(self, *args, **kwargs):
        self._active()
        return super().executemany(*args, **kwargs)
    def executescript(self, *args, **kwargs):
        self._active()
        return super().executescript(*args, **kwargs)
    def commit(self):
        self._active()
        return super().commit()
    def __exit__(self, typ, value, traceback):
        if typ is None:
            try:
                self._active()
            except BaseException:
                self.rollback()
                raise
        return super().__exit__(typ,value,traceback)


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
        self.state_root = root.parent
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
        if namespace == "context":
            return self.root.parent / "context" / "context.sqlite3"
        return self.root / self._filename(namespace)

    def connect(self, namespace: str, *, shared=False) -> sqlite3.Connection:
        self.assert_active()
        target = self.path_for(namespace)
        target.parent.mkdir(parents=True,exist_ok=True)
        db = sqlite3.connect(
            str(target),
            timeout=self.timeout_seconds,
            factory=AuthoritySQLiteConnection,
            check_same_thread=not shared,
        )
        db.authority_store = self
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA busy_timeout={int(self.timeout_seconds * 1000)}")
        return db

    def assert_active(self):
        from .authority_migration import read_selection
        if read_selection(self.root.parent).get("backend") != "sqlite":
            raise RuntimeError("SQLite authority was replaced; reopen the configured Control Plane")

    def assert_principal(self, owner):
        self.assert_active()

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
    backend: str = "configured",
    dsn: str | None = None,
    tenant_id: str | None = None,
    principal_id: str | None = None,
) -> ControlPlaneStore:
    """Create an audited store implementation.

    PostgreSQL uses isolated native schemas, transactional migrations and
    advisory locks. Configuration is explicit; no fallback to SQLite on failure.
    """

    selected = str(backend or "sqlite").strip().lower()
    configured = selected == "configured"
    if selected == "configured":
        from .authority_migration import read_selection
        from sentra_runtime.provider_authority import load_provider_binding
        choice = load_provider_binding(state_root) or read_selection(state_root)
        selected = choice["backend"]
        dsn, tenant_id, principal_id = choice.get("dsn"), choice.get("tenant_id"), choice.get("principal_id")
    if selected == "sqlite":
        return SQLiteControlPlaneStore(state_root)
    if selected in {"postgres", "postgresql"}:
        from .postgres_store import PostgresControlPlaneStore
        result = PostgresControlPlaneStore(state_root, dsn=dsn, tenant_id=tenant_id, principal_id=principal_id)
        if configured and choice.get("conversation_id"):
            result.provider_binding = choice
            result._selection_revision = choice.get("authority_revision")
        elif configured:
            result._selection_revision = choice.get("revision")
        return result
    raise UnsupportedControlPlaneBackend(
        f"control-plane backend {selected!r} is not available in this build"
    )
