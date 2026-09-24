"""OAuth 2.1 resource-server token verification for remote SENTRA MCP."""
from __future__ import annotations

import asyncio
import base64
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from mcp.server.auth.provider import AccessToken, TokenVerifier


@dataclass(frozen=True, slots=True)
class IntrospectionSettings:
    url: str
    client_id: str = ""
    client_secret: str = ""
    timeout_s: float = 5.0
    resource: str | None = None


class IntrospectionTokenVerifier(TokenVerifier):
    """RFC 7662 verifier for an external OAuth/OIDC authorization server."""

    def __init__(self, settings: IntrospectionSettings) -> None:
        if not settings.url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("OAuth introspection must use HTTPS unless it is loopback")
        self.settings = settings

    def _verify_sync(self, token: str) -> AccessToken | None:
        if not token or len(token) > 16384:
            return None
        data = urllib.parse.urlencode({"token": token}).encode("ascii")
        req = urllib.request.Request(
            self.settings.url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        if self.settings.client_id:
            raw = f"{self.settings.client_id}:{self.settings.client_secret}".encode("utf-8")
            req.add_header("Authorization", "Basic " + base64.b64encode(raw).decode("ascii"))
        try:
            with urllib.request.urlopen(req, timeout=self.settings.timeout_s) as response:
                if response.status != 200:
                    return None
                payload = json.loads(response.read(1024 * 1024))
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("active") is not True:
            return None
        exp = payload.get("exp")
        if exp is not None:
            try:
                exp = int(exp)
            except (TypeError, ValueError):
                return None
            if exp <= int(time.time()):
                return None
        resource = payload.get("aud") or payload.get("resource")
        if isinstance(resource, list):
            resource = resource[0] if resource else None
        if self.settings.resource and resource and self.settings.resource != resource:
            return None
        raw_scope = payload.get("scope", "")
        scopes = raw_scope.split() if isinstance(raw_scope, str) else list(raw_scope or [])
        subject = payload.get("sub") or payload.get("username") or payload.get("client_id")
        if not subject:
            return None
        return AccessToken(
            token=token,
            client_id=str(payload.get("client_id") or "unknown"),
            scopes=[str(scope) for scope in scopes],
            expires_at=exp,
            resource=str(resource) if resource else self.settings.resource,
            subject=str(subject),
            claims={k: v for k, v in payload.items() if k not in {"access_token", "refresh_token"}},
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        return await asyncio.to_thread(self._verify_sync, token)


class StaticTokenVerifier(TokenVerifier):
    """Test/development verifier; never enabled implicitly."""

    def __init__(self, token: str, *, subject: str = "local-test", scopes: tuple[str, ...] = ("sentra:mcp",)) -> None:
        if len(token) < 24:
            raise ValueError("static development token must be at least 24 characters")
        self._token = token
        self._subject = subject
        self._scopes = list(scopes)

    async def verify_token(self, token: str) -> AccessToken | None:
        import secrets
        if not secrets.compare_digest(token, self._token):
            return None
        return AccessToken(token=token, client_id="sentra-dev", scopes=self._scopes, subject=self._subject)
