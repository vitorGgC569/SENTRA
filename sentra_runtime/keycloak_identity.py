"""Opt-in Keycloak-compatible OIDC JWT identity verification.

Uses cryptography for genuine RS256 signature verification with pre-pinned
JWKS from a trusted administrator. No Keycloak server is installed/contacted.
Identity is NOT an authorization grant: SENTRA AuthorizationService and
WorkItem/Operation policy must additionally permit all effects.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import re
import time
from typing import Mapping, Any

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes


class IdentityDenied(PermissionError):
    pass


def _json(blob: bytes) -> dict:
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise IdentityDenied("duplicate JSON field")
            obj[key] = value
        return obj
    try:
        data = json.loads(blob.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              IdentityDenied("nonfinite JSON constant")))
    except (ValueError, UnicodeError) as exc:
        raise IdentityDenied("invalid identity JSON") from exc
    if not isinstance(data, dict):
        raise IdentityDenied("identity must be a JSON object")
    return data


def _b64(value: str) -> bytes:
    if (not isinstance(value, str) or not value
            or not re.fullmatch(r"[A-Za-z0-9_-]+", value)):
        raise IdentityDenied("invalid base64url")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise IdentityDenied("malformed base64url") from exc


@dataclass(frozen=True, slots=True)
class VerifiedKeycloakIdentity:
    subject: str
    issuer: str
    audience: str
    expires_at: int
    issued_at: int
    key_id: str


class PinnedKeycloakJWTVerifier:
    """Verify RS256 access tokens using a trusted, strictly scoped JWKS snapshot."""

    def __init__(
        self, *, issuer: str, audience: str, pinned_jwks: Mapping[str, Any],
        max_token_seconds: int = 3600, clock_skew_seconds: int = 30,
    ):
        if (not isinstance(issuer, str) or not issuer.startswith("https://")
                or not issuer.rstrip("/").endswith("/protocol/openid-connect")
                and "/realms/" not in issuer):
            raise ValueError("explicit HTTPS Keycloak realm issuer required")
        if not isinstance(audience, str) or not audience or len(audience) > 128:
            raise ValueError("explicit OIDC audience required")
        if not 60 <= max_token_seconds <= 86400 or not 0 <= clock_skew_seconds <= 60:
            raise ValueError("invalid token acceptance bounds")
        if not isinstance(pinned_jwks, Mapping) or not isinstance(pinned_jwks.get("keys"), list):
            raise ValueError("trusted JWKS key list required")
        self.issuer, self.audience = issuer.rstrip("/"), audience
        self.max_token_seconds, self.clock_skew_seconds = max_token_seconds, clock_skew_seconds
        self._keys = {}
        for entry in pinned_jwks["keys"]:
            if (not isinstance(entry, dict) or entry.get("kty") != "RSA"
                    or entry.get("alg", "RS256") != "RS256"
                    or entry.get("use", "sig") != "sig"):
                raise ValueError("unsupported pinned Keycloak key")
            kid = entry.get("kid")
            if (not isinstance(kid, str) or not 0 < len(kid) <= 128
                    or kid in self._keys):
                raise ValueError("duplicate or invalid trusted Keycloak kid")
            try:
                exponent = int.from_bytes(_b64(entry["e"]), "big")
                modulus = int.from_bytes(_b64(entry["n"]), "big")
                if exponent < 3 or exponent % 2 == 0 or modulus.bit_length() < 2048:
                    raise ValueError("weak public key")
                self._keys[kid] = rsa.RSAPublicNumbers(exponent, modulus).public_key()
            except (ValueError, TypeError, KeyError, IdentityDenied) as exc:
                raise ValueError("invalid trusted Keycloak key parameters") from exc
        if not self._keys or len(self._keys) > 32:
            raise ValueError("invalid number of pinned Keycloak keys")

    def verify(self, token: str, *, now: int | None = None) -> VerifiedKeycloakIdentity:
        claims,header=self._signed_claims(token)
        self._window(claims,now=now,audience=self.audience)
        subject=claims.get("sub")
        if (not isinstance(subject,str) or not 0<len(subject)<=256 or claims.get("typ","Bearer") not in {"Bearer","bearer"}
            or any(k in claims for k in ("cnf","act","may_act"))):
            raise IdentityDenied("JWT subject/type denied")
        return VerifiedKeycloakIdentity(subject,self.issuer,self.audience,claims["exp"],claims["iat"],header["kid"])

    def _signed_claims(self,token):
        if not isinstance(token, str) or not 0 < len(token) <= 16_384:
            raise IdentityDenied("token absent or oversized")
        parts = token.split(".")
        if len(parts) != 3:
            raise IdentityDenied("invalid compact JWS")
        header = _json(_b64(parts[0]))
        claims = _json(_b64(parts[1]))
        if (header.get("alg") != "RS256" or header.get("typ", "JWT") != "JWT"
                or header.get("crit") or "jwk" in header or "jku" in header
                or "x5u" in header or not isinstance(header.get("kid"), str)):
            raise IdentityDenied("unsupported JWT header")
        key = self._keys.get(header["kid"])
        if key is None:
            raise IdentityDenied("JWT key not trusted")
        try:
            key.verify(_b64(parts[2]), (parts[0] + "." + parts[1]).encode("ascii"),
                       padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise IdentityDenied("JWT signature invalid") from exc
        return claims,header

    def _window(self,claims,*,now=None,audience):
        current = int(time.time()) if now is None else now
        issued, expiry, not_before = claims.get("iat"), claims.get("exp"), claims.get("nbf")
        if (type(current) is not int or type(issued) is not int or type(expiry) is not int
                or (not_before is not None and type(not_before) is not int)
                or issued > current + self.clock_skew_seconds
                or expiry <= current - self.clock_skew_seconds
                or expiry <= issued
                or expiry - issued > self.max_token_seconds
                or (not_before is not None and not_before > current + self.clock_skew_seconds)):
            raise IdentityDenied("JWT validity window denied")
        advertised = claims.get("aud")
        if not (advertised == audience or isinstance(advertised, list)
                and audience in advertised and all(isinstance(x, str) for x in advertised)):
            raise IdentityDenied("JWT audience mismatch")
        if claims.get("iss") != self.issuer:
            raise IdentityDenied("JWT issuer mismatch")

    def verified_claims(self,token,*,audience=None,kind="access",now=None):
        """Host-selected token kind/audience; never infer authority from claims."""
        target=audience or self.audience
        if kind=="access":
            claims,_=self._signed_claims(token); self._window(claims,now=now,audience=target)
            if claims.get("typ","Bearer") not in {"Bearer","bearer"} or any(k in claims for k in ("cnf","act","may_act")):
                raise IdentityDenied("access token type/holder proof/delegation unsupported")
        elif kind=="id":
            claims,_=self._signed_claims(token); self._window(claims,now=now,audience=target)
            if claims.get("typ","ID") not in {"ID","id"}: raise IdentityDenied("ID token type denied")
            if isinstance(claims.get("aud"),list) and len(claims["aud"])>1 and claims.get("azp")!=target:
                raise IdentityDenied("ID token authorized party mismatch")
        elif kind=="logout":
            claims,_=self._signed_claims(token)
            issued=claims.get("iat"); current=int(time.time()) if now is None else now
            if type(issued) is not int or issued>current+self.clock_skew_seconds or current-issued>300:
                raise IdentityDenied("stale backchannel logout")
            # Backchannel logout need not have exp. Bound by iat freshness.
            bounded=dict(claims); bounded["exp"]=claims.get("exp",issued+300)
            self._window(bounded,now=now,audience=target)
            events=claims.get("events")
            if ("nonce" in claims or not isinstance(events,dict) or events.get("http://schemas.openid.net/event/backchannel-logout")!={}
                or not isinstance(claims.get("jti"),str) or not claims["jti"] or not (claims.get("sid") or claims.get("sub"))):
                raise IdentityDenied("invalid backchannel logout claims")
        else: raise ValueError("unrecognized OIDC token kind")
        if kind!="logout" and (not isinstance(claims.get("sub"),str) or not 0<len(claims["sub"])<=256):
            raise IdentityDenied("token subject missing")
        return claims


class KeycloakIdentityVeto:
    """AND-compose authenticated user identity with an existing SENTRA grant.

    A Keycloak subject never by itself authorizes an OperationRequest. The
    host supplies a bearer token from its trusted authenticated session;
    request.arguments cannot override that token.
    """

    def __init__(self, verifier: PinnedKeycloakJWTVerifier, trusted_token_provider,
                 base_grant):
        if (not isinstance(verifier, PinnedKeycloakJWTVerifier)
                or not callable(trusted_token_provider) or not callable(base_grant)):
            raise ValueError("trusted identity and grant authorities required")
        self.verifier = verifier
        self.trusted_token_provider = trusted_token_provider
        self.base_grant = base_grant

    def __call__(self, request):
        from .contracts import OperationRequest, PolicyDecision
        try:
            if not isinstance(request, OperationRequest):
                raise IdentityDenied("invalid operation")
            token = self.trusted_token_provider()
            identity = self.verifier.verify(token)
            # Caller cannot obtain another principal's SENTRA grant by
            # supplying a different request.principal_id.
            if request.principal_id != identity.subject:
                raise IdentityDenied("identity and SENTRA principal mismatch")
            decision = self.base_grant(request)
            if not isinstance(decision, PolicyDecision) or decision.allowed is not True:
                return PolicyDecision(False, "SENTRA grant denied")
            if decision.constraints:
                return PolicyDecision(False, "constrained grant requires validated adapter")
            return PolicyDecision(True, "Keycloak identity and SENTRA grant accepted")
        except Exception:
            return PolicyDecision(False, "Keycloak identity/grant validation failed")
