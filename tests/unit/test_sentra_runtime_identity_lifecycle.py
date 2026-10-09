"""Prepared OIDC contract tests: real RSA signatures and protected SQLite.

RecordingOIDC is an explicit protocol fixture, not a Keycloak deployment or
evidence of a real login. Tests are authored but not executed in this wave.
"""
import base64
import hashlib
import json
from urllib.parse import urlsplit,parse_qs

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes

from sentra_runtime.identity_state import ProtectedIdentityStore,principal_id,IdentityStateConflict
from sentra_runtime.keycloak_identity import PinnedKeycloakJWTVerifier,IdentityDenied
from sentra_runtime.keycloak_provider import KeycloakOIDCConfig,KeycloakOIDCProvider,KeycloakSessionVeto
from sentra_runtime.contracts import OperationRequest,PolicyDecision


ISSUER="https://identity.example.invalid/realms/sentra"
def b64(value): return base64.urlsafe_b64encode(value).decode().rstrip("=")


@pytest.fixture
def lifecycle(tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=key.public_key().public_numbers()
    jwks={"keys":[{"kid":"key1","kty":"RSA","alg":"RS256","use":"sig",
        "n":b64(public.n.to_bytes((public.n.bit_length()+7)//8,"big")),"e":b64(public.e.to_bytes(3,"big"))}]}
    clock=[1000]
    def sign(claims):
        body=b64(json.dumps({"alg":"RS256","typ":"JWT","kid":"key1"}).encode())+"."+b64(json.dumps(claims).encode())
        return body+"."+b64(key.sign(body.encode(),padding.PKCS1v15(),hashes.SHA256()))
    store=ProtectedIdentityStore(tmp_path/"identity.sqlite",workspace=tmp_path,namespace="oidc")
    config=KeycloakOIDCConfig(ISSUER,"client","sentra-api","https://sentra.example.invalid/oidc/callback",exchange_audiences=("connector-api",))
    verifier=PinnedKeycloakJWTVerifier(issuer=ISSUER,audience="sentra-api",pinned_jwks=jwks)
    class RecordingOIDC:
        base=ISSUER
        active=True
        on_refresh=None
        lose_code=False
        def __init__(self): self.calls=[]; self.vendor_session=0
        def claims(self,*,audience="sentra-api",typ="Bearer",**extra):
            return {"iss":ISSUER,"sub":"subject-1","aud":audience,"azp":"client","sid":"vendor-session-"+str(self.vendor_session),
                "typ":typ,"iat":clock[0],"exp":clock[0]+100,**extra}
        def get(self,path,**kwargs):
            self.calls.append(("GET",path))
            if path.endswith("/certs"): return jwks
            suffixes={"authorization_endpoint":"auth","token_endpoint":"token","jwks_uri":"certs","introspection_endpoint":"token/introspect",
                "revocation_endpoint":"revoke","end_session_endpoint":"logout"}
            return {"issuer":ISSUER,"code_challenge_methods_supported":["S256"],"token_endpoint_auth_methods_supported":["client_secret_post"],
                **{k:ISSUER+"/protocol/openid-connect/"+v for k,v in suffixes.items()}}
        def request(self,method,path,*,form=None,**kwargs):
            self.calls.append((method,path,form))
            if path.endswith("/introspect"): return {"active":self.active,"sub":"subject-1","iss":ISSUER}
            if path.endswith("/revoke") or path.endswith("/logout"): return {}
            grant=form["grant_type"]
            if grant=="urn:ietf:params:oauth:grant-type:token-exchange":
                return {"access_token":sign(self.claims(audience=form["audience"])),"issued_token_type":"urn:ietf:params:oauth:token-type:access_token"}
            if grant=="authorization_code":
                if self.lose_code: raise ConnectionError("explicit fixture lost exchange response")
                self.vendor_session+=1
                pending=next(r["value"] for _,r in store.records("login:") if r["value"]["phase"]=="CONSUMING")
                assert form["code_verifier"]==pending["pkce"]
                ident=sign(self.claims(audience="client",typ="ID",nonce=pending["nonce"]))
            else:
                if self.on_refresh: self.on_refresh()
                ident=sign(self.claims(audience="client",typ="ID"))
            return {"access_token":sign(self.claims()),"id_token":ident,"refresh_token":"opaque-refresh-fixture",
                    "token_type":"Bearer","scope":"openid profile"}
    transport=RecordingOIDC(); notifications=[]
    provider=KeycloakOIDCProvider(config=config,verifier=verifier,store=store,enabled=True,http=transport,
        client_secret_provider=lambda:"secret-from-host",clock=lambda:clock[0],on_invalidate=lambda *args:notifications.append(args))
    return provider,transport,store,clock,sign,notifications


def login(provider):
    started=provider.begin_login(browser_binding="host-cookie-binding-123")
    query=parse_qs(urlsplit(started["authorization_url"]).query)
    assert query["code_challenge_method"]==["S256"] and "pkce" not in started
    return started,provider.complete_login(state=started["state"],code="one-use-code",browser_binding="host-cookie-binding-123")


def test_login_principal_stability_pkce_audience_and_no_grants(lifecycle):
    provider,transport,store,clock,sign,notifications=lifecycle
    assert not transport.calls
    started,result=login(provider); identity=result["principal"]
    assert identity.principal_id==principal_id(ISSUER,"subject-1")
    assert identity.principal_id!=principal_id("https://other.invalid/realms/sentra","subject-1")
    with pytest.raises(IdentityDenied): provider.complete_login(state=started["state"],code="one-use-code",browser_binding="host-cookie-binding-123")
    renewed=provider.refresh(result["session_id"])
    assert renewed.principal_id==identity.principal_id
    exchanged=provider.token_exchange(result["session_id"],audience="connector-api",scopes=("openid",))
    assert exchanged.principal_id==identity.principal_id and "access_token" not in exchanged.public_metadata()
    assert exchanged.access_token not in repr(exchanged)
    with pytest.raises(IdentityDenied): provider.verifier.verify(exchanged.access_token,now=clock[0])
    with pytest.raises(IdentityDenied): provider.token_exchange(result["session_id"],audience="unconfigured")
    request=OperationRequest("op","other-principal","machine","write","work","idem",{"token":"forged"})
    veto=KeycloakSessionVeto(provider,trusted_session_id=lambda:result["session_id"],core_pdp=lambda _:PolicyDecision(True,"core grant",{"roots":["workspace"]}))
    assert veto(request).allowed is False
    request=OperationRequest("op",identity.principal_id,"machine","write","work","idem",{})
    assert veto(request).allowed is True and veto(request).constraints=={"roots":["workspace"]}
    with store.db() as db:
        protected=[row[0] for row in db.execute("SELECT protected_value FROM identity_records")]
    assert all(v.startswith(("dpapi:","keyring:")) for v in protected)
    assert not any("opaque-refresh-fixture" in v for v in protected)


def test_lost_code_reply_cannot_replay_and_browser_binding_required(lifecycle):
    provider,transport,store,clock,sign,notifications=lifecycle
    started=provider.begin_login(browser_binding="host-cookie-binding-123")
    with pytest.raises(IdentityDenied): provider.complete_login(state=started["state"],code="one-use-code",browser_binding="other-cookie-binding-123")
    transport.lose_code=True
    with pytest.raises(ConnectionError): provider.complete_login(state=started["state"],code="one-use-code",browser_binding="host-cookie-binding-123")
    with pytest.raises(IdentityDenied): provider.complete_login(state=started["state"],code="one-use-code",browser_binding="host-cookie-binding-123")
    assert len([c for c in transport.calls if c[0]=="POST" and c[1].endswith("/token")])==1


def test_revocation_logout_and_refresh_race_never_resurrect_identity(lifecycle):
    provider,transport,store,clock,sign,notifications=lifecycle
    _,result=login(provider); session=result["session_id"]
    claims={"iss":ISSUER,"aud":"client","iat":clock[0],"jti":"logout-1","sid":"vendor-session-1",
        "events":{"http://schemas.openid.net/event/backchannel-logout":{}}}
    token=sign(claims)
    transport.on_refresh=lambda:provider.backchannel_logout(token)
    with pytest.raises((IdentityStateConflict,IdentityDenied)): provider.refresh(session)
    with pytest.raises(IdentityDenied): provider.authenticate(session)
    assert provider.backchannel_logout(token)["duplicate"] is True and len(notifications)==1
    _,second=login(provider)
    transport.active=False
    with pytest.raises(IdentityDenied): provider.authenticate(second["session_id"])
    assert store.get("session:"+second["session_id"])["value"]["phase"]=="REVOKED"


def test_expiry_strict_and_local_logout_survives_remote_failure(lifecycle):
    provider,transport,store,clock,sign,notifications=lifecycle
    _,result=login(provider); clock[0]=1100
    with pytest.raises(IdentityDenied): provider.authenticate(result["session_id"])
    clock[0]=1000
    _,second=login(provider)
    original=transport.request
    def failing(method,path,**kwargs):
        if path.endswith("/logout"): raise ConnectionError("fixture provider unavailable")
        return original(method,path,**kwargs)
    transport.request=failing
    report=provider.logout(second["session_id"])
    assert report["remote_logout"]=="UNCERTAIN" and report["new_admissions_allowed"] is False
    with pytest.raises(IdentityDenied): provider.authenticate(second["session_id"])
