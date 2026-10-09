"""Keycloak RS256 JWT + OPA + OpenFGA real local protocol tests.

Services in this suite are controlled HTTP fixtures, not upstream daemons.
Cryptographic verification uses a real RSA key and real signed compact JWT.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, OperationResult, PolicyDecision
from sentra_runtime.executor import AuthorizationRequired, ExecutorRegistry
from sentra_runtime.keycloak_identity import (
    IdentityDenied, KeycloakIdentityVeto, PinnedKeycloakJWTVerifier,
)
from sentra_runtime.opa_pdp import OPAClient, OPADenyVeto
from sentra_runtime.openfga_rebac import OpenFGACheckClient, OpenFGADenyVeto


_SECRET = "a-temporary-test-only-opaque-bearer-secret-123"
_ISS = "https://keycloak.example.invalid/realms/sentra"
_AUD = "sentra-client"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="module")
def rsa_pair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()
    jwks = {"keys": [{
        "kty": "RSA", "alg": "RS256", "use": "sig", "kid": "rot-1",
        "n": _b64(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
        "e": _b64(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big")),
    }]}
    return private, jwks


def _sign(private, *, overrides=None, header_overrides=None):
    claims = {"iss": _ISS, "aud": _AUD, "sub": "agent-1",
              "iat": 1_000_000, "nbf": 1_000_000, "exp": 1_000_300,
              "typ": "Bearer"}
    claims.update(overrides or {})
    header = {"alg": "RS256", "kid": "rot-1", "typ": "JWT"}
    header.update(header_overrides or {})
    first = ".".join((
        _b64(json.dumps(header, separators=(",", ":")).encode()),
        _b64(json.dumps(claims, separators=(",", ":")).encode()),
    ))
    sig = private.sign(first.encode(), padding.PKCS1v15(), hashes.SHA256())
    return first + "." + _b64(sig)


def _verifier(jwks):
    return PinnedKeycloakJWTVerifier(issuer=_ISS, audience=_AUD, pinned_jwks=jwks)


def _req(**changes):
    data = dict(operation_id="op-one", principal_id="agent-1",
                machine_id="lab", capability_id="lab.inspect", work_item_id="WI-1",
                idempotency_key="key-one", arguments={"read": True})
    data.update(changes)
    return OperationRequest(**data)


class _LabBackend:
    def __init__(self):
        self.calls = []

    async def start(self, request):
        self.calls.append(request.operation_id)
        return OperationResult(request.operation_id, "SUCCEEDED")

    async def reconcile(self, operation_id):
        return OperationResult(operation_id, "UNCERTAIN")


def _run(policy, request=None):
    worker = _LabBackend()
    registry = ExecutorRegistry(policy)
    registry.register(Machine("lab", "lab", "owner",
                              (Capability("lab.inspect", "Read lab"),)), worker)
    result = asyncio.run(registry.submit(request or _req()))
    return result, worker


def test_keycloak_rs256_real_signature_and_claims(rsa_pair):
    private, jwks = rsa_pair
    result = _verifier(jwks).verify(_sign(private), now=1_000_100)
    assert result.subject == "agent-1"
    assert result.key_id == "rot-1"
    assert result.audience == _AUD


@pytest.mark.parametrize("mutations", [
    {"iss": "https://evil.invalid/realms/a"},
    {"aud": "other-client"},
    {"sub": ""},
    {"exp": 1_000_000},
    {"nbf": 1_000_200},
    {"iat": 1_000_200},
    {"exp": 1_040_000},
    {"typ": "refresh"},
])
def test_keycloak_wrong_claims_fail_closed(rsa_pair, mutations):
    private, jwks = rsa_pair
    with pytest.raises(IdentityDenied):
        _verifier(jwks).verify(_sign(private, overrides=mutations), now=1_000_100)


def test_keycloak_wrong_key_and_none_algorithm_denied(rsa_pair):
    private, jwks = rsa_pair
    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(IdentityDenied):
        _verifier(jwks).verify(_sign(foreign), now=1_000_100)
    with pytest.raises(IdentityDenied):
        _verifier(jwks).verify(
            _sign(private, header_overrides={"alg": "none"}), now=1_000_100)


def test_keycloak_cannot_grant_without_sentra_and_binds_principal(rsa_pair, monkeypatch):
    private, jwks = rsa_pair
    import sentra_runtime.keycloak_identity as module
    monkeypatch.setattr(module.time, "time", lambda: 1_000_100)
    token = _sign(private)
    verifier = _verifier(jwks)
    denied = KeycloakIdentityVeto(verifier, lambda: token,
                                 lambda req: PolicyDecision(False, "revoked"))
    with pytest.raises(AuthorizationRequired):
        _run(denied)
    allowed = KeycloakIdentityVeto(
        verifier, lambda: token, lambda req: PolicyDecision(True, "grant"),
    )
    result, worker = _run(allowed)
    assert result.state == "SUCCEEDED" and worker.calls == ["op-one"]
    with pytest.raises(AuthorizationRequired):
        _run(allowed, _req(principal_id="admin"))


@contextmanager
def fixture_policy(body, *, status=200):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append((self.path, self.headers.get("Authorization"),
                             json.loads(raw)))
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_opa_real_http_wire_and_base_grant_are_both_required():
    with fixture_policy({"result": True}) as (url, sent):
        opa = OPAClient(endpoint=url, bearer=_SECRET)
        deny = OPADenyVeto(lambda _: PolicyDecision(False, "no SENTRA grant"),
                          opa, trusted_workspace_id="ws1")
        with pytest.raises(AuthorizationRequired):
            _run(deny)
        assert sent == []
        allow = OPADenyVeto(lambda _: PolicyDecision(True, "existing grant"),
                           opa, trusted_workspace_id="ws1")
        output, _ = _run(allow)
        assert output.state == "SUCCEEDED"
        assert len(sent) == 1
        path, auth, data = sent[0]
        assert path == "/v1/data/sentra/allow"
        assert auth == "Bearer " + _SECRET
        assert data["input"]["workspace"] == "ws1"
        assert data["input"]["principal"] == "agent-1"
        assert "read" not in data["input"]  # untrusted arguments never sent


def test_opa_false_or_malformed_policy_response_denied():
    for result in ({"result": False}, {"result": "true"}, {},
                   {"result": True, "secret": "surprise"}):
        with fixture_policy(result) as (url, _):
            policy = OPADenyVeto(
                lambda _: PolicyDecision(True, "SENTRA"), OPAClient(
                    endpoint=url, bearer=_SECRET), trusted_workspace_id="ws1",
            )
            if result == {"result": True, "secret": "surprise"}:
                with pytest.raises(AuthorizationRequired):
                    _run(policy)
            else:
                with pytest.raises(AuthorizationRequired):
                    _run(policy)


def test_openfga_real_check_post_and_principal_scoping():
    with fixture_policy({"allowed": True}) as (url, sent):
        client = OpenFGACheckClient(
            endpoint=url, bearer=_SECRET,
            store_id="store-1", authorization_model_id="model-1",
        )
        check = OpenFGADenyVeto(lambda _: PolicyDecision(True, "SENTRA"), client)
        result, worker = _run(check)
        assert result.state == "SUCCEEDED" and worker.calls == ["op-one"]
        path, auth, payload = sent[0]
        assert path == "/stores/store-1/check"
        assert auth == "Bearer " + _SECRET
        assert payload["authorization_model_id"] == "model-1"
        assert payload["tuple_key"] == {
            "user": "agent:agent-1", "relation": "can_execute",
            "object": "work_item:WI-1",
        }


def test_openfga_denial_error_and_base_grant_never_bypassed():
    for response in ({"allowed": False}, {"allowed": 1},
                     {"allowed": True, "is_admin": True}, {}):
        with fixture_policy(response) as (url, sent):
            client = OpenFGACheckClient(
                endpoint=url, bearer=_SECRET,
                store_id="store-1", authorization_model_id="model-1",
            )
            with pytest.raises(AuthorizationRequired):
                _run(OpenFGADenyVeto(lambda _: PolicyDecision(True, "SENTRA"), client))
    with fixture_policy({"allowed": True}) as (url, sent):
        client = OpenFGACheckClient(
            endpoint=url, bearer=_SECRET,
            store_id="store-1", authorization_model_id="model-1",
        )
        with pytest.raises(AuthorizationRequired):
            _run(OpenFGADenyVeto(lambda _: PolicyDecision(False, "revoked"), client))
        assert sent == []


@pytest.mark.parametrize("invalid_url", [
    "https://policy.example.invalid:8181",
    "http://policy.example.invalid:8181",
    "http://localhost:8181",
    "http://127.0.0.1:8181/path",
    "http://127.0.0.1:8181/?token=secret",
    "http://user:pass@127.0.0.1:8181",
])
def test_opa_and_openfga_never_open_outbound_or_unsafe_urls(invalid_url):
    with pytest.raises(ValueError):
        OPAClient(endpoint=invalid_url, bearer=_SECRET)
    with pytest.raises(ValueError):
        OpenFGACheckClient(endpoint=invalid_url, bearer=_SECRET,
                           store_id="s1", authorization_model_id="m1")


def test_policy_http_redirect_and_upstream_failure_denied():
    for status in (301, 302, 401, 429, 500):
        with fixture_policy({"result": True}, status=status) as (url, sent):
            opa = OPAClient(endpoint=url, bearer=_SECRET)
            with pytest.raises(AuthorizationRequired):
                _run(OPADenyVeto(lambda _: PolicyDecision(True, "grant"),
                                 opa, trusted_workspace_id="ws1"))
            assert len(sent) == 1  # no automatic redirect or retry


@pytest.fixture
def live_sentra_grant(tmp_path):
    """The SAME durable SENTRA policy service used by the application core."""
    from sentra_mcp.services.authorization import AuthorizationService
    from sentra_mcp.services.durable import DurableRunService
    from sentra_mcp.services.governance import GovernanceService
    from sentra_runtime.authority_bridge import BoundWorkItemPolicy
    state = tmp_path / "state"
    auth = AuthorizationService(state)
    durable = DurableRunService(state)
    gov = GovernanceService(state, durable=durable)
    durable.create_run("owner", run_id="run-1")
    gov.create_work_item("run-1", "owner", work_item_id="WI-1",
                         objective="Read-only security check",
                         assignee_agent_id="agent-1",
                         required_capabilities=["lab.inspect"])
    gov.transition_work_item("WI-1", "owner", "RUNNING")
    grant = auth.grant("owner", principal_type="agent",
                       principal_id="agent-1", capability="lab.inspect",
                       scope_type="work_item", scope_id="WI-1")
    base = BoundWorkItemPolicy(owner="owner", principal_type="agent",
                              authorization=auth, governance=gov)
    try:
        yield base, auth, grant["grant_id"]
    finally:
        durable.close()


def test_real_sentra_sqlite_grant_plus_openfga_deny_veto(live_sentra_grant):
    base, auth, grant_id = live_sentra_grant
    with fixture_policy({"allowed": True}) as (url, sent):
        fga = OpenFGACheckClient(endpoint=url, bearer=_SECRET,
                                 store_id="store-1", authorization_model_id="model-1")
        composed = OpenFGADenyVeto(base, fga)
        assert _run(composed)[0].state == "SUCCEEDED"
        assert len(sent) == 1
        auth.revoke(grant_id, "owner")
        with pytest.raises(AuthorizationRequired):
            _run(composed)
        assert len(sent) == 1  # revoked SENTRA grant prevents external access


def test_real_sentra_sqlite_grant_plus_opa_deny_veto(live_sentra_grant):
    base, auth, grant_id = live_sentra_grant
    with fixture_policy({"result": True}) as (url, sent):
        opa = OPAClient(endpoint=url, bearer=_SECRET)
        composed = OPADenyVeto(base, opa, trusted_workspace_id="ws-one")
        assert _run(composed)[0].state == "SUCCEEDED"
        assert len(sent) == 1
        auth.revoke(grant_id, "owner")
        with pytest.raises(AuthorizationRequired):
            _run(composed)
        assert len(sent) == 1


def test_real_sentra_sqlite_grant_plus_keycloak_jwt(live_sentra_grant, rsa_pair, monkeypatch):
    base, auth, grant_id = live_sentra_grant
    private, jwks = rsa_pair
    import sentra_runtime.keycloak_identity as module
    monkeypatch.setattr(module.time, "time", lambda: 1_000_100)
    token = _sign(private)
    policy = KeycloakIdentityVeto(_verifier(jwks), lambda: token, base)
    assert _run(policy)[0].state == "SUCCEEDED"
    auth.revoke(grant_id, "owner")
    with pytest.raises(AuthorizationRequired):
        _run(policy)


def test_keycloak_opa_openfga_full_chain_on_real_sentra_sqlite_grant(
    live_sentra_grant, rsa_pair, monkeypatch,
):
    """Actual RS256 JWS + two HTTP fixture servers + actual SENTRA SQLite grant."""
    base, auth, grant_id = live_sentra_grant
    private, jwks = rsa_pair
    import sentra_runtime.keycloak_identity as module
    monkeypatch.setattr(module.time, "time", lambda: 1_000_100)
    identity = KeycloakIdentityVeto(
        _verifier(jwks), lambda: _sign(private), base,
    )
    with fixture_policy({"result": True}) as (opa_url, opa_calls):
        with fixture_policy({"allowed": True}) as (fga_url, fga_calls):
            opa = OPADenyVeto(identity, OPAClient(
                endpoint=opa_url, bearer=_SECRET), trusted_workspace_id="ws-one")
            all_required = OpenFGADenyVeto(
                opa, OpenFGACheckClient(
                    endpoint=fga_url, bearer=_SECRET, store_id="store-1",
                    authorization_model_id="model-1",
                ),
            )
            result, adapter = _run(all_required)
            assert result.state == "SUCCEEDED"
            assert adapter.calls == ["op-one"]
            # OpenFGA rechecks its composed base after Check, so OPA must
            # veto both before and after the remote relationship decision.
            assert len(opa_calls) == 2 and len(fga_calls) == 1
            auth.revoke(grant_id, "owner")
            with pytest.raises(AuthorizationRequired):
                _run(all_required)
            # Revocation must prevent any further external PDP requests.
            assert len(opa_calls) == 2 and len(fga_calls) == 1
