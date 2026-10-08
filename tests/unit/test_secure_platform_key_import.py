"""Sensitive key replacement never leaks secrets or loses previous config."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from sentra_remote.product import (
    ProductPaths, configure_tunnel, load_tunnel_config,
)
from scripts.commander.secure_platform_key_import import rotate_runtime_key

TUNNEL = "tunnel_testrealaccountabcdefghijkl"
OLD = "sk-proj_synthetic_old_abcdefghijklmnopqrstuvwxyz012345"
NEW = "sk-proj_synthetic_new_abcdefghijklmnopqrstuvwxyz012345"


def _paths(tmp_path: Path) -> ProductPaths:
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    configure_tunnel(paths, TUNNEL, OLD)
    return paths


def test_rotation_replaces_key_only_after_validated_tunnel(tmp_path):
    paths = _paths(tmp_path)
    runtime = Mock()
    runtime.status.return_value = {"tunnel": {"ok": True}}
    runtime.stop.return_value = True
    runtime.start_tunnel.return_value = {"ok": True}
    result = rotate_runtime_key(paths, NEW, approved=True, runtime=runtime)
    assert result == {
        "ok": True, "rotated": True,
        "dpapi": True, "tunnel_verified": True,
        "old_tunnel_replaced": True,
    }
    assert load_tunnel_config(paths, reveal_secret=True)["runtime_key"] == NEW
    data = paths.tunnel_config.read_text(encoding="utf-8")
    assert OLD not in data and NEW not in data
    assert not paths.tunnel_config.with_name(
        paths.tunnel_config.name + ".rotation-rollback"
    ).exists()


def test_rotation_failure_restores_previous_dpapi_protected_key(tmp_path):
    paths = _paths(tmp_path)
    prior = paths.tunnel_config.read_bytes()
    runtime = Mock()
    runtime.status.return_value = {"tunnel": {"ok": True}}
    runtime.stop.return_value = True
    runtime.start_tunnel.side_effect = [
        {"ok": False}, {"ok": True},
    ]
    result = rotate_runtime_key(paths, NEW, approved=True, runtime=runtime)
    assert result["ok"] is False
    assert result["rollback_restored"] is True
    assert paths.tunnel_config.read_bytes() == prior
    assert load_tunnel_config(paths, reveal_secret=True)["runtime_key"] == OLD


def test_rejects_unapproved_and_unexpected_key_formats(tmp_path):
    paths = _paths(tmp_path)
    runtime = Mock()
    with pytest.raises(PermissionError):
        rotate_runtime_key(paths, NEW, approved=False, runtime=runtime)
    with pytest.raises(ValueError):
        rotate_runtime_key(paths, "not-a-key", approved=True, runtime=runtime)
    runtime.assert_not_called()


def test_existing_incomplete_rotation_is_never_overwritten(tmp_path):
    paths = _paths(tmp_path)
    backup = paths.tunnel_config.with_name(
        paths.tunnel_config.name + ".rotation-rollback"
    )
    backup.write_bytes(b"previous ciphertext retained")
    with pytest.raises(RuntimeError, match="incomplete rotation"):
        rotate_runtime_key(paths, NEW, approved=True, runtime=Mock())
    assert backup.read_bytes() == b"previous ciphertext retained"
