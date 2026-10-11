"""Production factories and dispatch composition with real temporary SQLite.

Page evidence is controlled test data, never a real ChatGPT account proof.
"""
from types import SimpleNamespace
from pathlib import Path
import shutil

import pytest

from sentra_mcp.config import MCPConfig
from sentra_mcp.server import SentraMCPServer
from sentra_remote.browser_relay import create_relay
from test_sentra_cos_chat2_dispatch_round2 import EXT, SHA, REQ, observe


def test_installed_relay_uses_central_control_and_same_evidence(tmp_path):
    extension = tmp_path / "extension"
    shutil.copytree(Path(__file__).resolve().parents[2] / "edge_extension", extension)
    relay = create_relay(state_dir=tmp_path / "state", extension_dir=extension, port=0)
    control = relay.state.authenticated_control
    try:
        assert control is not None
        assert relay.state.browser_evidence is control.browser_evidence
        assert relay.state.authenticated_receipt_broker is not None
        assert control.authorization.list_grants("local-operator")["items"] == []
        with pytest.raises(ValueError, match="same state"):
            create_relay(state_dir=tmp_path / "other", extension_dir=extension,
                         port=0, control=control)
    finally:
        relay.server.server_close()
        relay.state.close()
        control.context.close()
        control.durable.close()


def test_server_dispatch_preserves_local_and_denies_unbound_browser(tmp_path):
    server = SentraMCPServer(MCPConfig(
        allowed_roots=(tmp_path,), state_root=tmp_path / "state",
        audit_log=tmp_path / "audit.jsonl", remote_store_path=tmp_path / "remote.sqlite3",
    ))
    seen = []
    server._observe_mcp_request = lambda ctx, name: seen.append(name)
    ctx = SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={"x-request-id": REQ})))
    try:
        server._enforce_web_mcp_request(None, "local-tool")
        server._enforce_web_mcp_request(ctx, "unattributed-local-tool")
        assert seen == ["local-tool", "unattributed-local-tool"]
        evidence = server.control_plane.browser_evidence
        evidence.configure(extension_id=EXT, source_sha256=SHA,
                           principal="local-operator", workspace=str(tmp_path),
                           enabled=True, expected_revision=0)
        observe(evidence)
        with pytest.raises(PermissionError, match="authenticated host job"):
            server._enforce_web_mcp_request(ctx, "web-tool")
        assert seen == ["local-tool", "unattributed-local-tool"]
    finally:
        server.context.close()
        server.durable.close()
