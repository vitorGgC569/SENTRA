from __future__ import annotations

import sqlite3

import pytest

from sentra_mcp.services.control_store import (
    CONTROL_PLANE_NAMESPACES,
    SQLiteControlPlaneStore,
    UnsupportedControlPlaneBackend,
    create_control_plane_store,
)


def test_sqlite_control_plane_store_owns_namespace_paths_and_pragmas(tmp_path) -> None:
    store = SQLiteControlPlaneStore(tmp_path)
    assert store.backend == "sqlite"
    assert set(store.describe()["namespaces"]) == set(CONTROL_PLANE_NAMESPACES)
    assert store.path_for("governance").name == "governance.sqlite3"

    with store.connect("governance") as db:
        assert db.row_factory is sqlite3.Row
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_control_plane_store_fails_closed_for_unknown_backend_or_namespace(tmp_path) -> None:
    with pytest.raises(UnsupportedControlPlaneBackend):
        create_control_plane_store(tmp_path, backend="postgres")

    store = SQLiteControlPlaneStore(tmp_path)
    with pytest.raises(ValueError, match="unknown control-plane store namespace"):
        store.connect("unknown")
