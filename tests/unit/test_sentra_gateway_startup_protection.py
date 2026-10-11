"""Exclusive listener ownership and key preservation under startup failures."""
import socket
from pathlib import Path

import pytest

from sentra_model_gateway.gateway import GatewayConfig, GatewayServer, load_or_create_gateway_admin_token


def test_second_gateway_cannot_touch_state_before_failing_exclusive_bind(tmp_path):
    state = tmp_path / "active"
    first = GatewayServer(GatewayConfig(port=0, state_root=state, browser_descriptor=tmp_path / "descriptor.json"))
    try:
        original = {path.name: path.read_bytes() for path in (state / "web-models").glob("*.token")}
        second_state = tmp_path / "competing"
        with pytest.raises(OSError):
            GatewayServer(GatewayConfig(port=first.server_port, state_root=second_state))
        assert not second_state.exists()
        assert original == {path.name: path.read_bytes() for path in (state / "web-models").glob("*.token")}
    finally:
        first.server_close()


def test_private_key_read_failure_never_rotates_existing_key(tmp_path, monkeypatch):
    original = load_or_create_gateway_admin_token(tmp_path)
    path = tmp_path / "web-models" / "gateway-admin.token"
    read = Path.read_text
    def denied(target, *args, **kwargs):
        if target == path:
            raise PermissionError("injected read failure")
        return read(target, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PermissionError):
        load_or_create_gateway_admin_token(tmp_path)
    assert read(path, encoding="utf-8").strip() == original


def test_invalid_existing_key_requires_repair_and_failed_init_releases_port(tmp_path):
    state = tmp_path / "state"
    token = state / "web-models" / "gateway-admin.token"
    token.parent.mkdir(parents=True)
    token.write_text("invalid-existing-key", encoding="utf-8")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    with pytest.raises(RuntimeError, match="host repair"):
        GatewayServer(GatewayConfig(port=port, state_root=state))
    assert token.read_text(encoding="utf-8") == "invalid-existing-key"
    with socket.socket() as recovered:
        recovered.bind(("127.0.0.1", port))
