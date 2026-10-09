"""Prepared decoder/scope tests; local certs are NOT SPIRE attestation.

The opt-in integration test requires a real SPIRE deployment and official SDK
helper binary. Missing profile skips it; selectors are never sent by the client.
"""
import asyncio
import base64
import datetime
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from sentra_runtime.spire_identity import SpireWorkloadConfig,SpireWorkloadIdentityClient,SpireIdentityVeto
from sentra_runtime.keycloak_identity import IdentityDenied
from sentra_runtime.contracts import OperationRequest,PolicyDecision


def config(tmp_path):
    endpoint="\\spire-agent\\public\\api" if os.name=="nt" else "/run/spire/agent.sock"
    return SpireWorkloadConfig(str(tmp_path/"not-built-sdk-helper.exe"),"0"*64,endpoint,("spiffe://sentra.example/host",),("sentra.example",),("sentra-api",),300)


def context_frame():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"explicit protocol fixture")])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1)
        .not_valid_before(now-datetime.timedelta(seconds=1)).not_valid_after(now+datetime.timedelta(seconds=100))
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier("spiffe://sentra.example/host")]),critical=False)
        .sign(key,hashes.SHA256()))
    der=cert.public_bytes(serialization.Encoding.DER)
    b64=lambda value:base64.b64encode(value).decode()
    return {"type":"x509_context","identities":[{"spiffe_id":"spiffe://sentra.example/host","not_before":int(cert.not_valid_before_utc.timestamp()),
        "expires_at":int(cert.not_valid_after_utc.timestamp()),"certificates":[b64(der)],"private_key_pkcs8":b64(key.private_bytes(
            serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())),"verified_by":"go-spiffe.x509svid.Verify"}],
        "bundles":{"sentra.example":[b64(der)]}}


def test_decoder_fixture_principal_stable_expiry_and_no_selector_authorization(tmp_path):
    cfg=config(tmp_path); client=SpireWorkloadIdentityClient(cfg,enabled=True)
    frame=context_frame()
    # Private decoder fixture: production frames come ONLY from pinned owned helper.
    client._x509_update(frame)
    first=client.authenticate(cfg.expected_spiffe_ids[0])
    client._x509_update(frame)
    assert client.authenticate(first.subject).principal_id==first.principal_id
    request=OperationRequest("op",first.principal_id,"machine","read","work","idem",{"selectors":["windows:user_sid:forged"]})
    veto=SpireIdentityVeto(client,trusted_spiffe_id=first.subject,core_pdp=lambda _:PolicyDecision(False,"no CorePDP grant"))
    assert veto(request).allowed is False
    forged=replace(request,principal_id="attacker")
    allow=SpireIdentityVeto(client,trusted_spiffe_id=first.subject,core_pdp=lambda _:PolicyDecision(True,"existing grant",{"root":"workspace"}))
    assert allow(forged).allowed is False
    assert allow(request).constraints=={"root":"workspace"}
    credential=client.credential(first.subject)
    assert "private_key" not in credential.public_metadata() and "private_key_pkcs8" not in repr(credential)
    client.clock=lambda:credential.expires_at
    with pytest.raises(IdentityDenied): client.authenticate(first.subject)
    client._unavailable("fixture stream loss")
    with pytest.raises(IdentityDenied): client.trust_bundles()


def test_wrong_uri_and_dependency_missing_never_issue_identity(tmp_path):
    cfg=config(tmp_path); client=SpireWorkloadIdentityClient(cfg,enabled=True)
    frame=context_frame(); frame["identities"][0]["spiffe_id"]="spiffe://other.example/host"
    with pytest.raises(IdentityDenied): client._x509_update(frame)
    with pytest.raises(ValueError): SpireWorkloadConfig(cfg.executable,cfg.executable_sha256,cfg.endpoint,("spiffe://foreign/host",),cfg.trust_domains)
    async def case():
        with pytest.raises(IdentityDenied): await client.start()
        assert client.process is None and not client._credentials
    asyncio.run(case())


def test_real_workload_api_subscription_jwt_and_bundle_opt_in():
    profile=os.environ.get("SENTRA_ACCEPTANCE_SPIRE_PROFILE")
    if not profile: pytest.skip("requires real SPIRE/SDK binary and attested workload registration; no simulated fallback")
    settings=json.loads(Path(profile).read_text(encoding="utf8"))
    cfg=SpireWorkloadConfig(**settings)
    updates=asyncio.Queue()
    client=SpireWorkloadIdentityClient(cfg,enabled=True,on_identity_change=updates.put_nowait)
    async def case():
        started=await client.start(timeout=15)
        try:
            assert started["caller_selectors_accepted"] is False
            identity=client.authenticate(cfg.expected_spiffe_ids[0])
            assert identity.expires_at>client.clock()
            token=await client.jwt_svid(spiffe_id=identity.subject,audience=cfg.audiences[0])
            assert token.expires_at>client.clock() and token.token not in repr(token)
            assert cfg.trust_domains[0] in client.trust_bundles()["x509"]
            renew_wait=int(os.environ.get("SENTRA_ACCEPTANCE_SPIRE_RENEW_WAIT_SECONDS","0"))
            if renew_wait:
                assert 1<=renew_wait<=120
                previous=client.credential(identity.subject).public_metadata()["certificate_sha256"]
                async def renewed():
                    while True:
                        event=await updates.get()
                        for item in event.get("identities",[]):
                            if item["spiffe_id"]==identity.subject and item["certificate_sha256"]!=previous: return item
                replacement=await asyncio.wait_for(renewed(),renew_wait)
                assert client.authenticate(identity.subject).principal_id==identity.principal_id
                assert replacement["expires_at"]>client.clock()
        finally: await client.close()
        assert client.process is None and not client._healthy
    asyncio.run(case())
