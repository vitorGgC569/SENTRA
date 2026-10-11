"""Physical 127.0.0.1 browser callback, one-use PKCE, owner session and DPAPI SQLite."""
import http.client
import socket
from urllib.parse import urlencode, urlsplit

import pytest
from test_sentra_cos_mcpb_oauth import configured
from sentra_mcp.services.mcpb_oauth import MCPBOAuthPKCE, OAuthAdmissionError
from sentra_mcp.services.mcpb_oauth_callback import OAuthLoopbackReceiver


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _configured(ws, vault, port):
    return MCPBOAuthPKCE(
        authorize_url="https://accounts.example.test/authorize",
        token_url="https://accounts.example.test/token",
        client_id="sentra-operator",
        redirect_uri=f"http://127.0.0.1:{port}/oauth/callback",
        scopes=("tools.read",), vault=vault)


def _get(port, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read().decode(), dict(response.getheaders())
    finally:
        conn.close()


def test_browser_loopback_owner_session_csrf_dpapi_replay_and_no_code_leak(configured):
    ws, store, vault, _ = configured
    port = _port()
    broker = _configured(ws, vault, port)
    active = {"yes": True}
    checked = []
    exchanges = []
    def verify(owner, workspace, server_id, session, ticket):
        checked.append((owner, workspace, server_id, session, ticket))
        return active["yes"] and (owner, str(workspace), server_id, session, ticket) == (
            "owner", str(ws), "srv", "host-owner-session", "consent-reviewed")
    def exchange(url, client_id, code, verifier, redirect):
        exchanges.append((code, verifier))
        assert redirect == f"http://127.0.0.1:{port}/oauth/callback"
        return {"token_type": "Bearer", "access_token": "fixture-callback-access",
                "refresh_token": "fixture-callback-refresh", "expires_in": 300}
    receiver = OAuthLoopbackReceiver(
        broker, owner="owner", workspace=ws, server_id="srv",
        host_session="host-owner-session", consent_ref="consent-reviewed",
        verify_host_consent=verify, exchange=exchange)
    try:
        auth = receiver.start()
        params = urlencode({"state": auth["state"], "code": "single-use-code"})
        status, body, headers = _get(port, f"/oauth/callback?{params}",
                                     headers={"Cookie": "not-permitted"})
        assert status == 403
        assert not exchanges
        assert headers["Cache-Control"] == "no-store"
        status, body, _ = _get(port, f"/oauth/callback?{params}")
        assert status == 200 and "single-use-code" not in body
        assert len(exchanges) == 1
        assert vault.access("owner", ws, "srv") == "fixture-callback-access"
        assert b"fixture-callback-access" not in store.path_for("plugin_bundle").read_bytes()
        assert receiver.status() == {"active": True, "consumed": True,
                                      "approved": True, "credentials_exposed": False}
        again, body, _ = _get(port, f"/oauth/callback?{params}")
        assert again == 403 and len(exchanges) == 1
        assert "single-use-code" not in body
        assert checked
    finally:
        receiver.close()


def test_callback_does_not_finish_when_host_session_revoked(configured):
    ws, _, vault, _ = configured
    port = _port()
    broker = _configured(ws, vault, port)
    state = {"session_active": True}
    exchanges = []
    def approval(*args):
        return state["session_active"]
    receiver = OAuthLoopbackReceiver(
        broker, owner="owner", workspace=ws, server_id="srv-other",
        host_session="host-session", consent_ref="consent-ref",
        verify_host_consent=approval,
        exchange=lambda *args: exchanges.append(args))
    try:
        info = receiver.start()
        state["session_active"] = False
        status, _, _ = _get(port, "/oauth/callback?" +
                          urlencode({"state": info["state"], "code": "code"}))
        assert status == 403 and not exchanges
        with pytest.raises(OAuthAdmissionError):
            vault.access("owner", ws, "srv-other")
    finally:
        receiver.close()


def test_callback_rejects_unapproved_listener_and_foreign_host(configured):
    ws, _, vault, _ = configured
    port = _port()
    broker = _configured(ws, vault, port)
    deny = OAuthLoopbackReceiver(
        broker, owner="owner", workspace=ws, server_id="srv",
        host_session="owner-session", consent_ref="ticket",
        verify_host_consent=lambda *args: False, exchange=lambda *args: None)
    with pytest.raises(OAuthAdmissionError):
        deny.start()
    receiver = OAuthLoopbackReceiver(
        broker, owner="owner", workspace=ws, server_id="srv",
        host_session="owner-session", consent_ref="ticket",
        verify_host_consent=lambda *args: True, exchange=lambda *args: None)
    try:
        receipt = receiver.start()
        path = "/oauth/callback?" + urlencode({"state": receipt["state"], "code": "secret"})
        for headers in ({"Host": "attacker.invalid"}, {"Origin": "https://evil.example"},
                        {"Referer": "https://evil.example/"}):
            status, _, _ = _get(port, path, headers)
            assert status == 403
        assert not receiver.status()["consumed"]
    finally:
        receiver.close()
