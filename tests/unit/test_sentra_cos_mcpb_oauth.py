"""Real Windows DPAPI ciphertext / central SQLite / PKCE and refresh fencing."""
import base64
import hashlib
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest
from sentra_mcp.services.control_store import SQLiteControlPlaneStore
from sentra_mcp.services.mcpb_oauth import (
    MCPBOAuthPKCE, OAuthDPAPIVault, OAuthAdmissionError, win32crypt
)


@pytest.fixture
def configured(tmp_path):
    if win32crypt is None:
        pytest.skip("Windows DPAPI is unavailable")
    ws = tmp_path / "ws"
    ws.mkdir()
    store = SQLiteControlPlaneStore(tmp_path / "state")
    vault = OAuthDPAPIVault(store)
    broker = MCPBOAuthPKCE(
        authorize_url="https://accounts.example.test/authorize",
        token_url="https://accounts.example.test/token",
        client_id="sentra-test", redirect_uri="http://127.0.0.1:49872/callback",
        scopes=("tool.read",), vault=vault)
    return ws, store, vault, broker


def test_real_dpapi_pkce_one_use_and_no_plaintext_in_sqlite(configured):
    ws, store, vault, broker = configured
    with pytest.raises(OAuthAdmissionError):
        broker.begin("owner", ws, "srv")
    issued = broker.begin("owner", ws, "srv", approved=True)
    q = parse_qs(urlsplit(issued["authorization_url"]).query)
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"] == [issued["state"]]
    assert "code_verifier" not in q
    captured = []
    def exchange(token_url, client_id, code, verifier, redirect_uri):
        captured.append((token_url, client_id, code, verifier, redirect_uri))
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert expected == q["code_challenge"][0]
        return {"token_type":"Bearer", "access_token":"SENTRA_TEST_ACCESS",
                "refresh_token":"SENTRA_TEST_REFRESH", "expires_in":3600}
    with pytest.raises(OAuthAdmissionError):
        broker.finish("owner", ws, "srv", state="forged", code="sample", exchange=exchange, approved=True)
    stored = broker.finish("owner", ws, "srv", state=issued["state"],
                           code="sample", exchange=exchange, approved=True)
    assert stored["status"] == "ACTIVE"
    with pytest.raises(OAuthAdmissionError):
        broker.finish("owner", ws, "srv", state=issued["state"],
                      code="sample", exchange=exchange, approved=True)
    assert len(captured) == 1 and vault.access("owner", ws, "srv") == "SENTRA_TEST_ACCESS"
    db = store.path_for("plugin_bundle").read_bytes()
    assert b"SENTRA_TEST_ACCESS" not in db and b"SENTRA_TEST_REFRESH" not in db
    assert b"SENTRA_TEST_ACCESS" not in str(vault.status("owner", ws, "srv")).encode()
    reopened = OAuthDPAPIVault(store)
    assert reopened.access("owner", ws, "srv") == "SENTRA_TEST_ACCESS"
    with pytest.raises(OAuthAdmissionError):
        reopened.access("another-owner", ws, "srv")
    updated = reopened.refresh("owner", ws, "srv", lambda refresh: {
        "token_type":"Bearer", "access_token":"SENTRA_TEST_ACCESS_2",
        "refresh_token":"SENTRA_TEST_REFRESH_2", "expires_in":300})
    assert updated["status"] == "ACTIVE"
    assert reopened.access("owner", ws, "srv") == "SENTRA_TEST_ACCESS_2"
    assert b"SENTRA_TEST_REFRESH_2" not in store.path_for("plugin_bundle").read_bytes()
    reopened.revoke("owner", ws, "srv", approved=True)
    assert reopened.status("owner", ws, "srv")["status"] == "REVOKED"
    with pytest.raises(OAuthAdmissionError):
        reopened.access("owner", ws, "srv")


def test_refresh_uncertain_no_retry_across_restart(configured):
    ws, store, vault, broker = configured
    vault.put("owner", ws, "srv", {
        "token_type":"Bearer", "access_token":"temporary",
        "refresh_token":"refresh-value", "expires_in":3600}, approved=True)
    attempts = []
    def ambiguous(value):
        attempts.append(value)
        raise TimeoutError("ambiguous remote response")
    with pytest.raises(OAuthAdmissionError, match="uncertain"):
        vault.refresh("owner", ws, "srv", ambiguous)
    assert len(attempts) == 1
    reopened = OAuthDPAPIVault(store)
    with pytest.raises(OAuthAdmissionError):
        reopened.refresh("owner", ws, "srv", ambiguous)
    assert len(attempts) == 1
    assert reopened.status("owner", ws, "srv")["status"] == "UNCERTAIN"
    with pytest.raises(OAuthAdmissionError):
        reopened.access("owner", ws, "srv")
    with pytest.raises(OAuthAdmissionError):
        reopened.put("owner", ws, "srv", {
            "token_type":"Bearer", "access_token":"new", "expires_in":100}, approved=True)


def test_pkce_rejects_unsafe_issuer_callback_and_token_log(configured):
    ws, _, vault, broker = configured
    for origin in ("http://bad.example.test/token",
                   "https://127.0.0.1/token",
                   "https://evil.example.test/token?token=x"):
        with pytest.raises(OAuthAdmissionError):
            MCPBOAuthPKCE(authorize_url="https://accounts.example.test/authorize",
                          token_url=origin, client_id="test",
                          redirect_uri="http://127.0.0.1:49872/callback",
                          scopes=("read",), vault=vault)
    with pytest.raises(OAuthAdmissionError):
        vault.put("owner", ws, "srv", {
            "token_type":"Bearer", "access_token":"secret", "expires_in":60})


def test_remote_oauth_revocation_is_single_attempt_and_crash_safe(configured):
    ws, store, vault, broker = configured
    tokens = {"token_type":"Bearer", "access_token":"access-one",
              "refresh_token":"refresh-one", "expires_in":3600}
    vault.put("owner", ws, "srv-good", tokens, approved=True)
    calls = []
    def accepted(secret):
        calls.append(secret)
        # The local ciphertext is gone before the network effect.
        with pytest.raises(OAuthAdmissionError):
            vault.access("owner", ws, "srv-good")
        return True
    result = vault.revoke_remote("owner", ws, "srv-good", accepted, approved=True)
    assert result["remote_confirmed"] and result["local_revoked"]
    assert len(calls) == 1 and calls[0] == "refresh-one"
    with pytest.raises(OAuthAdmissionError):
        vault.revoke_remote("owner", ws, "srv-good", accepted, approved=True)
    assert len(calls) == 1
    vault.put("owner", ws, "srv-ambiguous", tokens, approved=True)
    attempts = []
    def failed(secret):
        attempts.append("called")
        raise TimeoutError("indeterminate")
    outcome = vault.revoke_remote("owner", ws, "srv-ambiguous", failed, approved=True)
    assert outcome["status"] == "REVOKED_UNCONFIRMED"
    assert not outcome["retry_permitted"]
    new_vault = OAuthDPAPIVault(store)
    with pytest.raises(OAuthAdmissionError):
        new_vault.access("owner", ws, "srv-ambiguous")
    with pytest.raises(OAuthAdmissionError):
        new_vault.revoke_remote("owner", ws, "srv-ambiguous", failed, approved=True)
    assert len(attempts) == 1


def test_pinned_https_revocation_requires_reviewed_same_origin(configured):
    from sentra_mcp.services.mcpb_oauth import PinnedOAuthHTTPS
    with pytest.raises(OAuthAdmissionError):
        PinnedOAuthHTTPS("https://accounts.example.test/token",
                         revoke_url="https://unexpected.example.test/revoke")
    transport = PinnedOAuthHTTPS("https://accounts.example.test/token")
    with pytest.raises(OAuthAdmissionError):
        transport.revoke("sample")
    transport = PinnedOAuthHTTPS("https://accounts.example.test/token",
                                 revoke_url="https://accounts.example.test/revoke")
    requests = []
    def fixture_request(url, body, *, revocation=False):
        requests.append((url, body, revocation))
        return True
    transport._request = fixture_request
    assert transport.revoke("fixture-refresh-token") is True
    assert requests == [("https://accounts.example.test/revoke",
                         {"token": "fixture-refresh-token",
                          "token_type_hint": "refresh_token"}, True)]
