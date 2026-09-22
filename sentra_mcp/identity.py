"""Request/session identity helpers for owner-scoped MCP tools."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.context import Context

_OWNER_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,120}$")
_SESSION_TOKEN_RE = re.compile(r"^st1\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)$")
_SESSION_SECRET_PATH = Path(
    os.environ.get(
        "SENTRA_SESSION_SECRET_PATH",
        str(Path.home() / ".sentra" / "mcp-session-secret"),
    )
)


def _opaque(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _session_secret() -> bytes:
    path = _SESSION_SECRET_PATH
    try:
        raw = path.read_bytes()
        if len(raw) >= 32:
            return raw
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_bytes(32)
    # Best-effort atomic create. A concurrent creator wins; use its key.
    try:
        with path.open("xb") as stream:
            stream.write(raw)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return raw
    except FileExistsError:
        existing = path.read_bytes()
        if len(existing) < 32:
            raise RuntimeError("SENTRA session secret is invalid")
        return existing


def _transport_kind(ctx: Context | None) -> str | None:
    if ctx is None:
        return None
    try:
        outbound = getattr(ctx.session, "_request_outbound", None)
        transport = getattr(outbound, "transport", None)
        kind = getattr(transport, "kind", None)
        return str(kind) if kind else None
    except Exception:
        return None


def _is_modern_stateless_http(ctx: Context | None) -> bool:
    if ctx is None:
        return False
    return (
        _transport_kind(ctx) == "streamable-http"
        and str(getattr(ctx, "protocol_version", "") or "") >= "2026-07-28"
        and _sdk_session_identity(ctx) is None
        and _http_session_identity(ctx) is None
    )


def _principal_binding(ctx: Context | None) -> str:
    """Stable authentication principal used to bind application session tokens."""
    token = get_access_token()
    if token is not None:
        subject = token.subject or token.client_id
        if not subject:
            raise PermissionError("authenticated caller has no subject")
        return f"oauth:{subject}"
    # Local unauthenticated tunnel/stdio is already inside the operator trust
    # boundary. Conversation isolation is supplied by the signed session token.
    return "local-operator"


def open_conversation_session(
    ctx: Context | None,
    *,
    ttl_hours: int = 24,
) -> dict[str, Any]:
    if not 1 <= ttl_hours <= 24 * 30:
        raise ValueError("ttl_hours must be between 1 and 720")
    now = int(time.time())
    expires = now + ttl_hours * 3600
    jti = secrets.token_urlsafe(24)
    payload = {
        "v": 1,
        "jti": jti,
        "sub": _principal_binding(ctx),
        "iat": now,
        "exp": expires,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body = _b64e(raw)
    signature = _b64e(hmac.new(_session_secret(), body.encode("ascii"), hashlib.sha256).digest())
    token = f"st1.{body}.{signature}"
    return {
        "session_token": token,
        "session_owner": f"session:{jti}",
        "created_at": now,
        "expires_at": expires,
        "ttl_hours": ttl_hours,
        "transport": _transport_kind(ctx),
        "stateless_http": _is_modern_stateless_http(ctx),
    }


def verify_conversation_session(ctx: Context | None, token: str) -> str:
    if not isinstance(token, str) or not token:
        raise PermissionError("conversation session token is required")
    match = _SESSION_TOKEN_RE.fullmatch(token)
    if not match:
        raise PermissionError("invalid conversation session token")
    body, signature = match.groups()
    expected = _b64e(
        hmac.new(_session_secret(), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("invalid conversation session token")
    try:
        payload = json.loads(_b64d(body))
    except Exception as exc:
        raise PermissionError("invalid conversation session token") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise PermissionError("unsupported conversation session token")
    if payload.get("sub") != _principal_binding(ctx):
        raise PermissionError("conversation session token belongs to another principal")
    try:
        expires = int(payload["exp"])
        jti = str(payload["jti"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError("invalid conversation session token") from exc
    if expires <= int(time.time()):
        raise PermissionError("conversation session token has expired")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", jti):
        raise PermissionError("invalid conversation session token")
    return f"session:{jti}"


def _http_session_identity(ctx: Context | None) -> str | None:
    if ctx is None:
        return None
    try:
        request = ctx.request_context.request
    except Exception:
        return None
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    try:
        session_id = headers.get("mcp-session-id")
    except Exception:
        return None
    if not session_id:
        return None
    return _opaque("mcp", str(session_id))


def _explicit_meta_identity(ctx: Context | None) -> str | None:
    if ctx is None:
        return None
    try:
        meta = ctx.request_context.meta
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    for key in (
        "sentra/session-id",
        "sentra.session_id",
        "io.sentra/sessionId",
    ):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return _opaque("mcp-meta", value.strip())
    return None


def _sdk_session_identity(ctx: Context | None) -> str | None:
    if ctx is None:
        return None
    try:
        session = ctx.session
    except Exception:
        return None
    connection = getattr(session, "_connection", None)
    value = getattr(connection, "session_id", None) if connection is not None else None
    if value:
        return _opaque("mcp", str(value))
    for name in ("session_id", "_session_id"):
        value = getattr(session, name, None)
        if value:
            return _opaque("mcp", str(value))
    return None


def _direct_transport_identity(ctx: Context | None) -> str | None:
    """Deterministic fallback for direct/stdio and modern stateless clients."""
    if ctx is None:
        return None
    try:
        params = ctx.session.client_params
    except Exception:
        return None
    if params is None:
        return None
    try:
        client_info = params.client_info.model_dump(mode="json")
        capabilities = params.capabilities.model_dump(mode="json")
        protocol = str(params.protocol_version)
    except Exception:
        return None
    payload = json.dumps(
        {
            "client_info": client_info,
            "capabilities": capabilities,
            "protocol": protocol,
            "transport": _transport_kind(ctx),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    prefix = "mcp-stateless" if _is_modern_stateless_http(ctx) else "mcp-direct"
    return _opaque(prefix, payload)


def request_identity(ctx: Context | None = None) -> tuple[str, list[str]]:
    """Return the best available transport/auth identity for the current caller.

    MCP 2026-07-28 HTTP is intentionally stateless and has no Mcp-Session-Id.
    Stateful SENTRA resources therefore use a signed application session token
    from sentra_session_open on that transport.
    """
    token = get_access_token()
    if token is not None:
        subject = token.subject or token.client_id
        if not subject:
            raise PermissionError("authenticated caller has no subject")
        return f"oauth:{subject}", list(token.scopes or [])

    for resolver in (
        _http_session_identity,
        _explicit_meta_identity,
        _sdk_session_identity,
        _direct_transport_identity,
    ):
        identity = resolver(ctx)
        if identity:
            return identity, []
    return "local-operator", []


def resolve_owner(
    ctx: Context | None,
    requested: str | None = None,
    *,
    session_token: str | None = None,
    require_session: bool = False,
) -> str:
    """Resolve an owner, using an application session on stateless modern HTTP."""
    if session_token:
        base = verify_conversation_session(ctx, session_token)
    elif require_session and _is_modern_stateless_http(ctx):
        raise PermissionError(
            "conversation session required on MCP 2026-07-28 HTTP; "
            "call sentra_session_open once in this conversation and pass session_token"
        )
    else:
        base, _ = request_identity(ctx)

    if requested is None or not requested.strip():
        return base
    label = requested.strip()
    if not _OWNER_RE.fullmatch(label):
        raise ValueError(
            "owner label must be 1..120 characters using letters, numbers, . _ : @ / -"
        )
    return f"{base}:{label}"


def authorization_principal(
    ctx: Context | None = None,
    required_scope: str | None = None,
) -> tuple[str, list[str], str]:
    token = get_access_token()
    owner, _ = request_identity(ctx)
    if token is None:
        return (
            "local-operator",
            [
                "sentra:admin",
                "sentra:devices:read",
                "sentra:devices:write",
                "sentra:execute",
            ],
            owner,
        )
    scopes = list(token.scopes or [])
    if required_scope and required_scope not in scopes and "sentra:admin" not in scopes:
        raise PermissionError(f"OAuth scope required: {required_scope}")
    subject = token.subject or token.client_id
    if not subject:
        raise PermissionError("authenticated caller has no subject")
    return str(subject), scopes, owner


def require_scope(
    required_scope: str | None = None,
    ctx: Context | None = None,
) -> tuple[str, list[str]]:
    principal, scopes, _ = authorization_principal(ctx, required_scope)
    return principal, scopes
