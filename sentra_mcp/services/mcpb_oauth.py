"""Host-only OAuth2 PKCE broker and Windows DPAPI vault for MCP providers.

Tokens are never returned from a public catalog/API or logged. A pending
authorization lives only in this process. Refresh intents are durably fenced:
a crash or ambiguous HTTP response leaves UNCERTAIN and cannot retry.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import secrets
import ssl
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

try:
    import win32crypt
except ImportError:
    win32crypt = None

_DOMAIN = re.compile(r"(?=.{1,253}$)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_TOKEN_LIMIT = 8192


class OAuthAdmissionError(PermissionError):
    pass


def _url(url):
    if not isinstance(url, str) or len(url) > 2048:
        raise OAuthAdmissionError("invalid OAuth endpoint")
    part = urlsplit(url)
    try:
        port = part.port
    except ValueError as exc:
        raise OAuthAdmissionError("invalid OAuth origin") from exc
    if (part.scheme != "https" or not _DOMAIN.fullmatch(part.hostname or "")
            or port not in (None, 443) or part.username or part.password
            or part.query or part.fragment or not part.path.startswith("/")):
        raise OAuthAdmissionError("OAuth requires pinned HTTPS DNS endpoint")
    return part


def _loopback(uri):
    part = urlsplit(uri)
    try:
        port = part.port
    except ValueError as exc:
        raise OAuthAdmissionError("invalid loopback callback") from exc
    if (part.scheme != "http" or part.hostname not in ("127.0.0.1", "::1")
            or port is None or part.query or part.fragment or part.username
            or part.password or not part.path.endswith("/callback")):
        raise OAuthAdmissionError("OAuth callback must be approved literal loopback")
    return uri


def _token_response(response):
    if (not isinstance(response, dict) or response.get("token_type", "").lower() != "bearer"
            or type(response.get("expires_in")) is not int
            or not 1 <= response["expires_in"] <= 86400):
        raise OAuthAdmissionError("OAuth token response invalid")
    for key in ("access_token", "refresh_token"):
        value = response.get(key)
        if key == "refresh_token" and value is None:
            continue
        if (not isinstance(value, str) or not 1 <= len(value) <= _TOKEN_LIMIT
                or not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            raise OAuthAdmissionError("OAuth credential response invalid")
    return response


class OAuthDPAPIVault:
    """DPAPI CurrentUser ciphertext in existing SENTRA plugin-bundle SQLite."""

    def __init__(self, store):
        if win32crypt is None:
            raise OAuthAdmissionError("Windows DPAPI unavailable: OAuth disabled")
        self.store = store
        with self.store.connect("plugin_bundle") as db:
            db.execute("""CREATE TABLE IF NOT EXISTS mcp_oauth_credentials (
                owner TEXT NOT NULL, workspace TEXT NOT NULL, server_id TEXT NOT NULL,
                ciphertext BLOB, expires_at REAL NOT NULL, status TEXT NOT NULL,
                revision INTEGER NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(owner,workspace,server_id))""")

    @staticmethod
    def _binding(owner, workspace, server_id):
        if not isinstance(owner, str) or not _ID.fullmatch(server_id or ""):
            raise OAuthAdmissionError("invalid OAuth credential identity")
        root = str(Path(workspace).resolve(strict=True))
        return (owner, root, server_id)

    @staticmethod
    def _entropy(binding):
        return hashlib.sha256(json.dumps(binding, separators=(",", ":")).encode()).digest()

    def put(self, owner, workspace, server_id, response, *, approved=False):
        if approved is not True:
            raise OAuthAdmissionError("host operator consent required")
        value = _token_response(response)
        binding = self._binding(owner, workspace, server_id)
        raw = json.dumps({"access_token": value["access_token"],
                          "refresh_token": value.get("refresh_token")},
                         separators=(",", ":")).encode()
        encrypted = win32crypt.CryptProtectData(raw, "SENTRA-MCP-OAuth",
                                                self._entropy(binding), None, None, 0)
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,revision FROM mcp_oauth_credentials "
                             "WHERE owner=? AND workspace=? AND server_id=?", binding).fetchone()
            if row and row["status"] != "ACTIVE":
                raise OAuthAdmissionError("OAuth credential requires new approved identity")
            revision = (row["revision"] + 1) if row else 1
            db.execute("""INSERT INTO mcp_oauth_credentials VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(owner,workspace,server_id) DO UPDATE SET
                ciphertext=excluded.ciphertext,expires_at=excluded.expires_at,
                status=excluded.status,revision=excluded.revision,updated=excluded.updated""",
                (*binding, encrypted, time.time() + value["expires_in"],
                 "ACTIVE", revision, time.time()))
        return {"status": "ACTIVE", "revision": revision, "credential_exposed": False}

    def _row(self, binding):
        with self.store.connect("plugin_bundle") as db:
            row = db.execute("SELECT * FROM mcp_oauth_credentials "
                             "WHERE owner=? AND workspace=? AND server_id=?", binding).fetchone()
        if row is None:
            raise OAuthAdmissionError("OAuth credential missing")
        return dict(row)

    def _read_secret(self, binding, row):
        if row["ciphertext"] is None:
            raise OAuthAdmissionError("OAuth credential unavailable")
        try:
            raw = win32crypt.CryptUnprotectData(
                row["ciphertext"], self._entropy(binding), None, None, 0)[1]
            values = json.loads(raw)
        except Exception as exc:
            raise OAuthAdmissionError("OAuth credential integrity denied") from None
        return values

    def access(self, owner, workspace, server_id):
        binding = self._binding(owner, workspace, server_id)
        row = self._row(binding)
        if row["status"] != "ACTIVE" or row["expires_at"] <= time.time() + 10:
            raise OAuthAdmissionError("OAuth credential expired, revoked or uncertain")
        return self._read_secret(binding, row)["access_token"]

    def status(self, owner, workspace, server_id):
        row = self._row(self._binding(owner, workspace, server_id))
        return {"status": row["status"], "revision": row["revision"],
                "expires_at": row["expires_at"], "credential_exposed": False}

    def revoke(self, owner, workspace, server_id, *, approved=False):
        if approved is not True:
            raise OAuthAdmissionError("operator approval required for OAuth revoke")
        binding = self._binding(owner, workspace, server_id)
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE mcp_oauth_credentials SET ciphertext=NULL,"
                "status='REVOKED',revision=revision+1,updated=? "
                "WHERE owner=? AND workspace=? AND server_id=?",
                (time.time(), *binding)).rowcount
            if not changed:
                raise OAuthAdmissionError("OAuth credential missing")
        return self.status(*binding)

    def refresh(self, owner, workspace, server_id, exchange):
        """One refresh effect only, fenced in central SQLite before network IO."""
        binding = self._binding(owner, workspace, server_id)
        if not callable(exchange):
            raise OAuthAdmissionError("trusted refresh transport required")
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM mcp_oauth_credentials "
                             "WHERE owner=? AND workspace=? AND server_id=?", binding).fetchone()
            if not row or row["status"] != "ACTIVE":
                raise OAuthAdmissionError("OAuth refresh already attempted, revoked or unavailable")
            previous = self._read_secret(binding, dict(row))
            refresh_token = previous.get("refresh_token")
            if not refresh_token:
                raise OAuthAdmissionError("OAuth refresh token unavailable")
            db.execute("UPDATE mcp_oauth_credentials SET status='REFRESHING',"
                       "revision=revision+1,updated=? WHERE owner=? AND workspace=? AND server_id=?",
                       (time.time(), *binding))
        try:
            updated = _token_response(exchange(refresh_token))
            if updated.get("refresh_token") is None:
                updated = {**updated, "refresh_token": refresh_token}
            raw = json.dumps({"access_token": updated["access_token"],
                              "refresh_token": updated["refresh_token"]}).encode()
            encrypted = win32crypt.CryptProtectData(
                raw, "SENTRA-MCP-OAuth", self._entropy(binding), None, None, 0)
            with self.store.connect("plugin_bundle") as db:
                db.execute("BEGIN IMMEDIATE")
                count = db.execute("UPDATE mcp_oauth_credentials SET ciphertext=?,"
                    "status='ACTIVE',expires_at=?,revision=revision+1,updated=? "
                    "WHERE owner=? AND workspace=? AND server_id=? AND status='REFRESHING'",
                    (encrypted, time.time() + updated["expires_in"], time.time(),
                     *binding)).rowcount
                if count != 1:
                    raise OAuthAdmissionError("OAuth credential revoked during refresh")
            return self.status(*binding)
        except BaseException:
            # A remote refresh_token may already have rotated: never retry.
            with self.store.connect("plugin_bundle") as db:
                db.execute("UPDATE mcp_oauth_credentials SET ciphertext=NULL,"
                           "status='UNCERTAIN',revision=revision+1,updated=? "
                           "WHERE owner=? AND workspace=? AND server_id=? AND status='REFRESHING'",
                           (time.time(), *binding))
            raise OAuthAdmissionError("OAuth refresh outcome uncertain; new consent required") from None

    def revoke_remote(self, owner, workspace, server_id, send, *, approved=False):
        """Local revocation commits BEFORE the single remote token revoke effect.

        A crash or transport failure cannot restore a usable local bearer.
        Remote status remains unconfirmed, never transparently retried.
        """
        if approved is not True or not callable(send):
            raise OAuthAdmissionError("operator approval and reviewed token revoker required")
        binding = self._binding(owner, workspace, server_id)
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM mcp_oauth_credentials "
                             "WHERE owner=? AND workspace=? AND server_id=?", binding).fetchone()
            if not row or row["status"] != "ACTIVE":
                raise OAuthAdmissionError("OAuth remote revocation requires active credential")
            secret = self._read_secret(binding, dict(row))
            token = secret.get("refresh_token") or secret["access_token"]
            db.execute("UPDATE mcp_oauth_credentials SET ciphertext=NULL,status='REVOKING',"
                       "revision=revision+1,updated=? WHERE owner=? AND workspace=? AND server_id=?",
                       (time.time(), *binding))
        try:
            confirmed = send(token) is True
        except Exception:
            confirmed = False
        state = "REVOKED" if confirmed else "REVOKED_UNCONFIRMED"
        with self.store.connect("plugin_bundle") as db:
            db.execute("UPDATE mcp_oauth_credentials SET status=?,revision=revision+1,"
                       "updated=? WHERE owner=? AND workspace=? AND server_id=? AND status='REVOKING'",
                       (state, time.time(), *binding))
        return {"local_revoked": True, "remote_confirmed": confirmed,
                "status": state, "retry_permitted": False}


class MCPBOAuthPKCE:
    """In-memory one-use PKCE states; host verifies callback and user consent."""

    def __init__(self, *, authorize_url, token_url, client_id, redirect_uri,
                 scopes, vault: OAuthDPAPIVault, clock=time.time):
        first, second = _url(authorize_url), _url(token_url)
        if first.hostname != second.hostname:
            raise OAuthAdmissionError("OAuth authorization/token host mismatch")
        if not _ID.fullmatch(client_id or ""):
            raise OAuthAdmissionError("invalid OAuth public client")
        if (not isinstance(scopes, tuple) or len(scopes) > 16 or
                any(not re.fullmatch(r"[A-Za-z0-9:./_-]{1,100}", x) for x in scopes)):
            raise OAuthAdmissionError("invalid OAuth scopes")
        self.authorize_url, self.token_url = authorize_url, token_url
        self.client_id, self.redirect_uri = client_id, _loopback(redirect_uri)
        self.scopes, self.vault, self.clock = scopes, vault, clock
        self.pending = {}
        self.lock = threading.RLock()

    def begin(self, owner, workspace, server_id, *, approved=False):
        if approved is not True:
            raise OAuthAdmissionError("human authorization required")
        identity = self.vault._binding(owner, workspace, server_id)
        with self.lock:
            now = self.clock()
            self.pending = {k:v for k,v in self.pending.items() if v[2] > now}
            if len(self.pending) >= 32:
                raise OAuthAdmissionError("OAuth pending capacity exhausted")
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            self.pending[state] = (identity, verifier, now + 300)
        part = urlsplit(self.authorize_url)
        query = urlencode({"response_type": "code", "client_id": self.client_id,
            "redirect_uri": self.redirect_uri, "scope": " ".join(self.scopes),
            "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256"})
        return {"authorization_url": urlunsplit((part.scheme, part.netloc,
                        part.path, query, "")), "state": state, "expires_in": 300}

    def finish(self, owner, workspace, server_id, *, state, code, exchange, approved=False):
        identity = self.vault._binding(owner, workspace, server_id)
        with self.lock:
            entry = self.pending.pop(state, None) if isinstance(state, str) else None
        if (approved is not True or not entry or entry[0] != identity
                or entry[2] <= self.clock() or not callable(exchange)
                or not isinstance(code, str) or not 1 <= len(code) <= 2048
                or not code.isascii() or any(ord(c) < 33 for c in code)):
            raise OAuthAdmissionError("OAuth callback state/approval denied")
        result = exchange(self.token_url, self.client_id, code, entry[1], self.redirect_uri)
        return self.vault.put(owner, workspace, server_id, result, approved=True)


class PinnedOAuthHTTPS:
    """Public-client OAuth token transport with DNS/IP pinning and verified TLS.

    No redirects, ambient proxy, cookie jar, retry, HTTP credentials in
    errors, or acceptance of private/reserved DNS resolutions. Every request
    opens one validated direct HTTPS connection and then closes it.
    """

    def __init__(self, token_url: str, *, revoke_url: str | None = None, timeout=5):
        self.token_url = token_url
        self.part = _url(token_url)
        self.revoke_url = revoke_url
        if revoke_url is not None and _url(revoke_url).hostname != self.part.hostname:
            raise OAuthAdmissionError("OAuth revocation origin mismatch")
        if type(timeout) not in (int, float) or not 0 < timeout <= 15:
            raise OAuthAdmissionError("invalid OAuth transport timeout")
        self.timeout = timeout

    def _request(self, url, form, *, revocation=False):
        import ipaddress
        import socket
        part = _url(url)
        if part.hostname != self.part.hostname or not isinstance(form, dict):
            raise OAuthAdmissionError("OAuth unapproved transport endpoint")
        addresses = socket.getaddrinfo(part.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or len(addresses) > 32:
            raise OAuthAdmissionError("OAuth DNS resolution unavailable")
        selected = []
        for entry in addresses:
            address = ipaddress.ip_address(entry[4][0])
            if not address.is_global:
                raise OAuthAdmissionError("OAuth DNS resolved to private or reserved IP")
            selected.append(entry[4][0])
        body = urlencode(form).encode("ascii")
        if len(body) > 12_000:
            raise OAuthAdmissionError("OAuth request exceeds limit")
        connection = http.client.HTTPSConnection(
            part.hostname, 443, context=ssl.create_default_context(), timeout=self.timeout)
        try:
            # Use pre-resolved public IP, but TLS SNI and certificate validate
            # against original approved host. Never resolve again on connect.
            sock = socket.create_connection((selected[0], 443), timeout=self.timeout)
            try:
                connection.sock = connection._context.wrap_socket(
                    sock, server_hostname=part.hostname)
            except BaseException:
                sock.close()
                raise
            connection.request("POST", part.path, body=body, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json", "Cache-Control": "no-store"})
            response = connection.getresponse()
            if revocation:
                if response.status not in (200, 204) or response.read(1):
                    raise OAuthAdmissionError("OAuth remote revocation unconfirmed")
                return True
            if response.status != 200:
                raise OAuthAdmissionError("OAuth remote token request unconfirmed")
            content_type = response.getheader("Content-Type", "").split(";")[0].strip().lower()
            if content_type != "application/json":
                raise OAuthAdmissionError("OAuth remote content-type unsupported")
            data = response.read(16_385)
            if len(data) > 16_384:
                raise OAuthAdmissionError("OAuth remote payload oversized")
            def unique(pairs):
                out = {}
                for key, value in pairs:
                    if key in out:
                        raise OAuthAdmissionError("OAuth ambiguous JSON response")
                    out[key] = value
                return out
            result = json.loads(data, object_pairs_hook=unique)
            return _token_response(result)
        except OAuthAdmissionError:
            raise
        except Exception:
            raise OAuthAdmissionError("OAuth HTTPS result uncertain; do not replay") from None
        finally:
            connection.close()

    def exchange_code(self, token_url, client_id, code, verifier, redirect_uri):
        if token_url != self.token_url:
            raise OAuthAdmissionError("OAuth issuer changed during callback")
        return self._request(self.token_url, {
            "grant_type": "authorization_code", "client_id": client_id,
            "code": code, "code_verifier": verifier, "redirect_uri": redirect_uri})

    def refresh(self, client_id, refresh_token):
        if not _ID.fullmatch(client_id or ""):
            raise OAuthAdmissionError("OAuth client identity invalid")
        return self._request(self.token_url, {
            "grant_type": "refresh_token", "client_id": client_id,
            "refresh_token": refresh_token})

    def revoke(self, token):
        if self.revoke_url is None:
            raise OAuthAdmissionError("OAuth provider revocation endpoint not approved")
        if (not isinstance(token, str) or not 1 <= len(token) <= _TOKEN_LIMIT
                or not token.isascii() or any(ord(c) < 33 for c in token)):
            raise OAuthAdmissionError("OAuth revocation credential invalid")
        return self._request(self.revoke_url,
                             {"token": token, "token_type_hint": "refresh_token"},
                             revocation=True)
