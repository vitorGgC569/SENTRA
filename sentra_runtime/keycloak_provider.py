"""Explicit Keycloak OIDC lifecycle with PKCE, protected state and no auto-login.

Constructors are inert. Network happens only in explicit host lifecycle calls.
This authenticates a Principal; CorePDP remains the only grants authority.
"""
import base64
import hashlib
import secrets
import time
from dataclasses import dataclass,field
from urllib.parse import urlencode, urlsplit

from ._policy_http import PinnedProviderHTTP
from .identity_state import ProtectedIdentityStore, AuthenticatedPrincipal, principal_id, identity_digest
from .keycloak_identity import IdentityDenied, PinnedKeycloakJWTVerifier
from .contracts import PolicyDecision


@dataclass(frozen=True)
class KeycloakOIDCConfig:
    issuer: str
    client_id: str
    audience: str
    redirect_uri: str
    scopes: tuple = ("openid","profile")
    exchange_audiences: tuple = ()
    revocation_strategy: str = "introspection"
    pending_seconds: int = 300
    def __post_init__(self):
        object.__setattr__(self,"scopes",tuple(self.scopes)); object.__setattr__(self,"exchange_audiences",tuple(self.exchange_audiences))
        url,redirect=urlsplit(self.issuer),urlsplit(self.redirect_uri)
        if (url.scheme!="https" or not url.hostname or url.username or url.password or url.query or url.fragment or "/realms/" not in url.path
            or redirect.scheme not in {"https","http"} or redirect.scheme=="http" and redirect.hostname not in {"127.0.0.1","::1"}
            or redirect.username or redirect.password or redirect.fragment or not self.client_id or not self.audience
            or "openid" not in self.scopes or self.revocation_strategy not in {"introspection","local_session"}
            or type(self.pending_seconds) is not int or not 30<=self.pending_seconds<=600):
            raise ValueError("invalid explicit OIDC profile")
        if any(not isinstance(s,str) or not s or any(c.isspace() for c in s) for s in (*self.scopes,*self.exchange_audiences)):
            raise ValueError("invalid OIDC scope/audience")


@dataclass(frozen=True)
class ExchangedAudienceCredential:
    principal_id: str
    audience: str
    expires_at: int
    access_token: str = field(repr=False)
    def public_metadata(self): return {"principal_id":self.principal_id,"audience":self.audience,"expires_at":self.expires_at}


class KeycloakOIDCProvider:
    def __init__(self,*,config:KeycloakOIDCConfig,verifier:PinnedKeycloakJWTVerifier,store:ProtectedIdentityStore,
                 enabled=False,client_secret_provider=None,http=None,on_invalidate=None,clock=time.time):
        if not enabled or verifier.issuer!=config.issuer.rstrip("/") or verifier.audience!=config.audience:
            raise ValueError("OIDC profile/verifier mismatch or opt-in missing")
        self.config,self.verifier,self.store,self.clock=config,verifier,store,clock
        self.http=http or PinnedProviderHTTP(base=config.issuer,enabled=True)
        if self.http.base!=config.issuer.rstrip("/"): raise ValueError("OIDC origin not pinned")
        self.secret_provider,self.on_invalidate=client_secret_provider,on_invalidate
        self.profile_sha256=identity_digest(config.__dict__)
        self._metadata=None

    def discover(self):
        document=self.http.get("/.well-known/openid-configuration")
        if document.get("issuer")!=self.config.issuer.rstrip("/") or "S256" not in document.get("code_challenge_methods_supported",[]):
            raise IdentityDenied("OIDC issuer/PKCE discovery mismatch")
        suffixes={"authorization_endpoint":"/protocol/openid-connect/auth","token_endpoint":"/protocol/openid-connect/token",
            "jwks_uri":"/protocol/openid-connect/certs","introspection_endpoint":"/protocol/openid-connect/token/introspect",
            "revocation_endpoint":"/protocol/openid-connect/revoke","end_session_endpoint":"/protocol/openid-connect/logout"}
        for key,suffix in suffixes.items():
            if document.get(key)!=self.http.base+suffix: raise IdentityDenied("Keycloak discovered endpoint not pinned")
        if self.secret_provider is not None and "client_secret_post" not in document.get("token_endpoint_auth_methods_supported",[]):
            raise IdentityDenied("configured OAuth client authentication not advertised")
        self._metadata=document
        return {k:document[k] for k in ("issuer",*suffixes)}

    def fetch_jwks_candidate(self):
        """Return verified-origin candidate only; owner activates a new verifier."""
        if self._metadata is None: self.discover()
        jwks=self.http.get("/protocol/openid-connect/certs")
        PinnedKeycloakJWTVerifier(issuer=self.config.issuer,audience=self.config.audience,pinned_jwks=jwks)
        return {"jwks":jwks,"sha256":identity_digest(jwks),"activated":False}

    def _auth(self):
        result={"client_id":self.config.client_id}
        if self.secret_provider is not None:
            secret=self.secret_provider()
            if not isinstance(secret,str) or not secret or any(c in secret for c in "\r\n\0"): raise IdentityDenied("client credential unavailable")
            result["client_secret"]=secret
        return result

    def _check_revoked_claims(self,claims):
        sid=claims.get("sid")
        if sid and self.store.get("revoked-sid:"+identity_digest({"issuer":self.verifier.issuer,"sid":sid})):
            raise IdentityDenied("identity provider session previously revoked")
        subject=claims.get("sub")
        cutoff=self.store.get("subject-not-before:"+identity_digest({"issuer":self.verifier.issuer,"subject":subject})) if subject else None
        if cutoff and claims.get("iat",0)<=cutoff["value"]["iat"]: raise IdentityDenied("identity predates subject revocation")

    def begin_login(self,*,browser_binding,prompt=None):
        if self._metadata is None: self.discover()
        if not isinstance(browser_binding,str) or len(browser_binding)<16: raise IdentityDenied("trusted host browser binding required")
        if prompt not in {None,"login","consent","select_account","none"}: raise ValueError("invalid OIDC prompt")
        state,nonce,verifier=(secrets.token_urlsafe(32) for _ in range(3))
        value={"phase":"PENDING","browser_sha256":identity_digest(browser_binding),"nonce":nonce,"pkce":verifier,
               "expires_at":int(self.clock())+self.config.pending_seconds}
        self.store.put("login:"+state,value)
        params={"client_id":self.config.client_id,"redirect_uri":self.config.redirect_uri,"response_type":"code",
            "scope":" ".join(self.config.scopes),"state":state,"nonce":nonce,"code_challenge_method":"S256",
            "code_challenge":base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
        if prompt: params["prompt"]=prompt
        return {"authorization_url":self._metadata["authorization_endpoint"]+"?"+urlencode(params),"state":state,"expires_at":value["expires_at"]}

    def complete_login(self,*,state,code,browser_binding):
        record=self.store.get("login:"+state)
        if record is None: raise IdentityDenied("login state missing")
        value=record["value"]
        if (value["phase"]!="PENDING" or value["expires_at"]<=self.clock() or value["browser_sha256"]!=identity_digest(browser_binding)
            or not isinstance(code,str) or not 1<=len(code)<=8192): raise IdentityDenied("login callback binding expired/consumed/mismatched")
        value["phase"]="CONSUMING"
        self.store.put("login:"+state,value,expected_revision=record["revision"])
        # Mark before POST; lost exchange response cannot replay this code.
        response=self.http.request("POST","/protocol/openid-connect/token",form={**self._auth(),"grant_type":"authorization_code",
            "code":code,"redirect_uri":self.config.redirect_uri,"code_verifier":value["pkce"]})
        access=self.verifier.verified_claims(response.get("access_token"),now=int(self.clock()))
        self._check_revoked_claims(access)
        ident=self.verifier.verified_claims(response.get("id_token"),audience=self.config.client_id,kind="id",now=int(self.clock()))
        if (ident.get("nonce")!=value["nonce"] or access["sub"]!=ident["sub"] or access.get("azp")!=self.config.client_id
            or response.get("token_type","").lower()!="bearer" or access.get("sid") and ident.get("sid") and access["sid"]!=ident["sid"]):
            raise IdentityDenied("OIDC nonce/subject/client/session mismatch")
        session=secrets.token_urlsafe(32)
        saved={"phase":"ACTIVE","subject":access["sub"],"principal_id":principal_id(self.verifier.issuer,access["sub"]),
            "profile_sha256":self.profile_sha256,
            "login_nonce":value["nonce"],
            "sid":access.get("sid") or ident.get("sid"),"access_token":response["access_token"],"id_token":response["id_token"],
            "refresh_token":response.get("refresh_token"),"expires_at":access["exp"],"audience":self.config.audience,"scopes":response.get("scope","")}
        self.store.put("session:"+session,saved)
        current=self.store.get("login:"+state); consumed={"phase":"COMPLETED","session_id":session,"expires_at":value["expires_at"]}
        self.store.put("login:"+state,consumed,expected_revision=current["revision"])
        return {"session_id":session,"principal":self.authenticate(session),"consent_scopes":saved["scopes"]}

    def _session(self,session_id):
        record=self.store.get("session:"+session_id)
        if record is None or record["value"]["phase"]!="ACTIVE" or record["value"].get("profile_sha256")!=self.profile_sha256:
            raise IdentityDenied("identity session inactive/profile mismatch")
        return record

    def authenticate(self,session_id):
        record=self._session(session_id); value=record["value"]
        claims=self.verifier.verified_claims(value["access_token"],now=int(self.clock()))
        self._check_revoked_claims(claims)
        if claims["exp"]<=self.clock() or claims["sub"]!=value["subject"]: raise IdentityDenied("identity session expired/changed")
        if self.config.revocation_strategy=="introspection":
            if self.secret_provider is None: raise IdentityDenied("online revocation needs confidential client authentication")
            live=self.http.request("POST","/protocol/openid-connect/token/introspect",form={**self._auth(),"token":value["access_token"],"token_type_hint":"access_token"})
            if live.get("active") is not True or live.get("sub")!=value["subject"] or live.get("iss",self.verifier.issuer)!=self.verifier.issuer:
                self.invalidate(session_id,reason="external_revocation"); raise IdentityDenied("identity externally revoked")
        latest=self._session(session_id)
        if latest["revision"]!=record["revision"]: raise IdentityDenied("identity session changed during admission")
        return AuthenticatedPrincipal(value["principal_id"],self.verifier.issuer,value["subject"],"oidc",claims["exp"])

    def access_token(self,session_id):
        self.authenticate(session_id); return self._session(session_id)["value"]["access_token"]

    def invalidate(self,session_id,*,reason="logout"):
        record=self.store.get("session:"+session_id)
        if record is None: return {"invalidated":False}
        value=record["value"]
        if value.get("profile_sha256")!=self.profile_sha256: raise IdentityDenied("identity invalidation profile mismatch")
        value["phase"]="REVOKED"; value["revocation_reason"]=reason
        if value.get("sid"):
            marker="revoked-sid:"+identity_digest({"issuer":self.verifier.issuer,"sid":value["sid"]})
            if self.store.get(marker) is None: self.store.put(marker,{"sid":value["sid"],"reason":reason})
        value["invalidation_notified"]=False
        revision=self.store.put("session:"+session_id,value,expected_revision=record["revision"])
        notified=False
        if callable(self.on_invalidate):
            try:
                self.on_invalidate(value["principal_id"],session_id,reason)
                value["invalidation_notified"]=True
                self.store.put("session:"+session_id,value,expected_revision=revision); notified=True
            except Exception: pass  # durable REVOKED state remains; host delivery is retryable explicitly
        return {"invalidated":True,"principal_id":value["principal_id"],"new_admissions_allowed":False,"host_notified":notified}

    def refresh(self,session_id):
        record=self._session(session_id); value=record["value"]
        if not value.get("refresh_token"): raise IdentityDenied("no refresh credential")
        value["phase"]="REFRESHING"
        revision=self.store.put("session:"+session_id,value,expected_revision=record["revision"])
        try:
            response=self.http.request("POST","/protocol/openid-connect/token",form={**self._auth(),"grant_type":"refresh_token","refresh_token":value["refresh_token"]})
        except Exception as exc:
            value["phase"]="UNCERTAIN"
            self.store.put("session:"+session_id,value,expected_revision=revision)
            if callable(self.on_invalidate):
                try: self.on_invalidate(value["principal_id"],session_id,"refresh_response_uncertain")
                except Exception: pass
            raise IdentityDenied("refresh completion uncertain; never replay rotated credential") from exc
        claims=self.verifier.verified_claims(response.get("access_token"),now=int(self.clock()))
        self._check_revoked_claims(claims)
        if claims["sub"]!=value["subject"] or claims.get("azp")!=self.config.client_id or value.get("sid") and claims.get("sid")!=value["sid"]:
            raise IdentityDenied("refreshed principal/session changed")
        if response.get("id_token"):
            ident=self.verifier.verified_claims(response["id_token"],audience=self.config.client_id,kind="id",now=int(self.clock()))
            if ident["sub"]!=value["subject"] or ident.get("nonce",value["login_nonce"])!=value["login_nonce"] or ident.get("sid") and ident["sid"]!=claims.get("sid"):
                raise IdentityDenied("refreshed ID token principal/nonce/session changed")
        value.update(phase="ACTIVE",access_token=response["access_token"],expires_at=claims["exp"],refresh_token=response.get("refresh_token",value["refresh_token"]),
                     id_token=response.get("id_token",value["id_token"]))
        self.store.put("session:"+session_id,value,expected_revision=revision)
        return self.authenticate(session_id)

    def token_exchange(self,session_id,*,audience,scopes=()):
        if audience not in self.config.exchange_audiences or set(scopes)-set(self.config.scopes): raise IdentityDenied("exchange audience/scopes not configured")
        principal=self.authenticate(session_id); value=self._session(session_id)["value"]
        response=self.http.request("POST","/protocol/openid-connect/token",form={**self._auth(),
            "grant_type":"urn:ietf:params:oauth:grant-type:token-exchange","subject_token":value["access_token"],
            "subject_token_type":"urn:ietf:params:oauth:token-type:access_token","requested_token_type":"urn:ietf:params:oauth:token-type:access_token",
            "audience":audience,"scope":" ".join(scopes)})
        claims=self.verifier.verified_claims(response.get("access_token"),audience=audience,now=int(self.clock()))
        if claims["sub"]!=principal.subject or claims["exp"]<=self.clock() or response.get("issued_token_type")!="urn:ietf:params:oauth:token-type:access_token":
            raise IdentityDenied("exchange principal/type mismatch")
        self.authenticate(session_id)
        # Host-only secret result; never put it in operation evidence/logs.
        return ExchangedAudienceCredential(principal.principal_id,audience,claims["exp"],response["access_token"])

    def logout(self,session_id):
        record=self._session(session_id); value=record["value"]
        local=self.invalidate(session_id,reason="logout")
        if not value.get("refresh_token"): return {**local,"remote_logout":"REFRESH_TOKEN_UNAVAILABLE","connections_closed_by_host":False}
        # Local new admissions are denied even when remote logout is uncertain.
        try:
            self.http.request("POST","/protocol/openid-connect/logout",form={**self._auth(),"refresh_token":value.get("refresh_token","")},expected=(200,204))
            return {**local,"remote_logout":"ACKNOWLEDGED","connections_closed_by_host":False}
        except Exception:
            return {**local,"remote_logout":"UNCERTAIN","connections_closed_by_host":False}

    def revoke(self,session_id,*,token_kind="refresh"):
        if token_kind not in {"refresh","access"}: raise ValueError("invalid revocation token kind")
        record=self._session(session_id); value=record["value"]
        local=self.invalidate(session_id,reason="revocation")
        token=value.get(token_kind+"_token")
        if not token: return {**local,"remote_revocation":"TOKEN_UNAVAILABLE"}
        try:
            self.http.request("POST","/protocol/openid-connect/revoke",form={**self._auth(),"token":token,"token_type_hint":token_kind+"_token"},expected=(200,204))
            return {**local,"remote_revocation":"ACKNOWLEDGED"}
        except Exception: return {**local,"remote_revocation":"UNCERTAIN"}

    def session_status(self,session_id):
        record=self.store.get("session:"+session_id)
        if record is None or record["value"].get("profile_sha256")!=self.profile_sha256: raise IdentityDenied("identity session not accessible")
        value=record["value"]
        eligible=value["phase"]=="ACTIVE" and value["expires_at"]>self.clock()
        if eligible:
            try: self._check_revoked_claims(self.verifier.verified_claims(value["access_token"],now=int(self.clock())))
            except IdentityDenied: eligible=False
        return {"session_id":session_id,"principal_id":value["principal_id"],"phase":value["phase"],"expires_at":value["expires_at"],
                "locally_active":eligible,"authorizes_operations":False,"new_admissions_require_authentication":True,
                "host_notification_pending":value.get("invalidation_notified") is False,"revocation_strategy":self.config.revocation_strategy}

    def backchannel_logout(self,logout_token):
        claims=self.verifier.verified_claims(logout_token,audience=self.config.client_id,kind="logout",now=int(self.clock()))
        marker="logout-jti:"+identity_digest({"issuer":self.verifier.issuer,"client":self.config.client_id,"jti":claims["jti"]})
        prior=self.store.get(marker)
        if prior and prior["value"].get("phase")=="COMPLETED": return {"duplicate":True,"invalidated":0}
        if prior is None: self.store.put(marker,{"phase":"ADMITTED","claims":claims})
        return self.recover_backchannel_logout(claims["jti"])

    def recover_backchannel_logout(self,jti):
        marker="logout-jti:"+identity_digest({"issuer":self.verifier.issuer,"client":self.config.client_id,"jti":jti}); admitted=self.store.get(marker)
        if admitted is None: raise IdentityDenied("no authenticated logout event to recover")
        if admitted["value"]["phase"]=="COMPLETED": return {"duplicate":True,"invalidated":0}
        claims=admitted["value"]["claims"]
        if claims.get("sid"):
            key="revoked-sid:"+identity_digest({"issuer":self.verifier.issuer,"sid":claims["sid"]})
            if self.store.get(key) is None: self.store.put(key,{"sid":claims["sid"],"reason":"backchannel_logout"})
        elif claims.get("sub"):
            key="subject-not-before:"+identity_digest({"issuer":self.verifier.issuer,"subject":claims["sub"]}); prior=self.store.get(key)
            if prior is None or prior["value"]["iat"]<claims["iat"]:
                self.store.put(key,{"iat":claims["iat"]},expected_revision=prior["revision"] if prior else None)
        count=0
        for key,record in self.store.records("session:"):
            value=record["value"]
            if value.get("profile_sha256")!=self.profile_sha256: continue
            if value["phase"] in {"ACTIVE","REFRESHING"} and (not claims.get("sid") or value.get("sid")==claims["sid"]) and (not claims.get("sub") or value["subject"]==claims["sub"]):
                self.invalidate(key[len("session:"):],reason="backchannel_logout"); count+=1
        self.store.put(marker,{"phase":"COMPLETED","claims":claims},expected_revision=admitted["revision"])
        return {"duplicate":False,"invalidated":count}

    def retry_invalidation_notifications(self):
        if not callable(self.on_invalidate): raise IdentityDenied("host revocation callback unavailable")
        count=0
        for key,record in self.store.records("session:"):
            value=record["value"]
            if value.get("profile_sha256")!=self.profile_sha256 or value["phase"]!="REVOKED" or value.get("invalidation_notified") is True: continue
            self.on_invalidate(value["principal_id"],key[len("session:"):],value["revocation_reason"])
            value["invalidation_notified"]=True
            self.store.put(key,value,expected_revision=record["revision"]); count+=1
        return {"host_notifications":count,"new_admissions_allowed":False}


class KeycloakSessionVeto:
    def __init__(self,provider,*,trusted_session_id,core_pdp):
        if not isinstance(provider,KeycloakOIDCProvider) or not callable(trusted_session_id) or not callable(core_pdp): raise ValueError("trusted session/CorePDP required")
        self.provider,self.session,self.core=provider,trusted_session_id,core_pdp
    def __call__(self,request):
        try:
            session_id=self.session(); identity=self.provider.authenticate(session_id)
            if request.principal_id!=identity.principal_id: return PolicyDecision(False,"authenticated principal mismatch")
            decision=self.core(request)
            if not isinstance(decision,PolicyDecision) or decision.allowed is not True: return PolicyDecision(False,"CorePDP denied")
            if self.session()!=session_id or not self.provider.session_status(session_id)["locally_active"]:
                return PolicyDecision(False,"OIDC session changed during CorePDP admission")
            return PolicyDecision(True,"OIDC identity and CorePDP permit",decision.constraints)
        except Exception: return PolicyDecision(False,"OIDC session unavailable/revoked")
