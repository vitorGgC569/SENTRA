"""Owned official Go SPIFFE client; identity from agent-attested process only.

No constructor contacts SPIRE. start() is explicit host bootstrap after final
deployment validation. Caller selectors/PIDs are never accepted or sent.
"""
import asyncio
import base64
import hashlib
import os
import threading
import time
import uuid
import copy
from dataclasses import dataclass,field
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from sentra_interop.acp_process import spawn_owned
from ._policy_http import strict_json
from .identity_state import AuthenticatedPrincipal,principal_id,identity_digest
from .keycloak_identity import IdentityDenied
from .contracts import PolicyDecision


@dataclass(frozen=True)
class SpireWorkloadConfig:
    executable: str
    executable_sha256: str
    endpoint: str
    expected_spiffe_ids: tuple
    trust_domains: tuple
    audiences: tuple = ()
    max_ttl_seconds: int = 3600
    def __post_init__(self):
        for name in ("expected_spiffe_ids","trust_domains","audiences"): object.__setattr__(self,name,tuple(getattr(self,name)))
        if not Path(self.executable).is_absolute() or not self.expected_spiffe_ids or not self.trust_domains or not 30<=self.max_ttl_seconds<=86400:
            raise ValueError("explicit pinned SPIFFE workload profile required")
        if os.name=="nt":
            if not self.endpoint or self.endpoint.startswith("\\\\") or any(c in self.endpoint for c in ":\r\n\0") or ".." in self.endpoint:
                raise ValueError("local SPIRE pipe name required")
        elif not Path(self.endpoint).is_absolute(): raise ValueError("absolute local Workload API socket required")
        for ident in self.expected_spiffe_ids:
            url=urlsplit(ident)
            if url.scheme!="spiffe" or url.netloc not in self.trust_domains or not url.path or url.query or url.fragment or url.username or url.password:
                raise ValueError("SPIFFE identity outside configured trust domain")


@dataclass(frozen=True)
class X509WorkloadCredential:
    spiffe_id: str
    expires_at: int
    not_before: int
    certificates: tuple = field(repr=False)
    private_key_pkcs8: bytes = field(repr=False)
    verification_expires_at: int | None = None
    def public_metadata(self):
        return {"spiffe_id":self.spiffe_id,"expires_at":self.expires_at,"verification_expires_at":self.verification_expires_at,
                "certificate_sha256":hashlib.sha256(self.certificates[0]).hexdigest()}


@dataclass(frozen=True)
class JWTWorkloadCredential:
    spiffe_id: str
    audience: str
    expires_at: int
    token: str = field(repr=False)
    def public_metadata(self): return {"spiffe_id":self.spiffe_id,"audience":self.audience,"expires_at":self.expires_at}


class SpireWorkloadIdentityClient:
    def __init__(self,config:SpireWorkloadConfig,*,enabled=False,on_identity_change=None,clock=time.time):
        if not enabled: raise ValueError("SPIRE workload identity requires explicit opt-in")
        self.config,self.clock,self.on_identity_change=config,clock,on_identity_change
        self.process=self.owner=self.reader=None
        self._lock=threading.RLock(); self._write_lock=asyncio.Lock()
        self._credentials={}; self._x509_bundles={}; self._jwt_bundles={}; self._pending={}; self._ready=asyncio.Event()
        self._healthy=False; self._error=None
    @property
    def configuration_sha256(self): return identity_digest(self.config.__dict__)
    async def start(self,*,timeout=10):
        if self.process is not None: raise IdentityDenied("SPIRE client already started; retain existing stream")
        binary=Path(self.config.executable)
        if binary.is_symlink() or not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest()!=self.config.executable_sha256:
            raise IdentityDenied("official SDK helper missing or pin mismatch; build/deploy prerequisite pending")
        self._ready.clear()
        self.process,self.owner=await spawn_owned(str(binary),(),env={},stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=8_000_001)
        self.reader=asyncio.create_task(self._read())
        try:
            await self._send({"version":1,"endpoint":self.config.endpoint,"expected_ids":self.config.expected_spiffe_ids,
                "audiences":self.config.audiences,"max_ttl_seconds":self.config.max_ttl_seconds})
            await asyncio.wait_for(self._ready.wait(),timeout)
            if not self._healthy: raise IdentityDenied("Workload API did not issue the configured identity")
        except BaseException:
            await self.close(); raise
        return {"connected":True,"configuration_sha256":self.configuration_sha256,"attested_process_pid":self.process.pid,
                "caller_selectors_accepted":False}
    async def _send(self,value):
        import json
        if self.process is None or self.process.returncode is not None: raise IdentityDenied("SPIRE client disconnected")
        raw=json.dumps(value,allow_nan=False,separators=(",",":")).encode()+b"\n"
        if len(raw)>1_000_000: raise ValueError("SPIRE helper frame exceeds bound")
        async with self._write_lock: self.process.stdin.write(raw); await self.process.stdin.drain()
    def _unavailable(self,reason):
        with self._lock: self._healthy=False; self._credentials={}; self._error=reason
        self._ready.set()
        if callable(self.on_identity_change): self.on_identity_change({"available":False,"reason":reason})
    def _x509_update(self,frame):
        identities=frame.get("identities"); bundles=frame.get("bundles")
        if not isinstance(identities,list) or not isinstance(bundles,dict) or len(identities)>32 or len(bundles)>64: raise IdentityDenied("invalid X509 workload context")
        parsed={}
        for value in identities:
            ident=value.get("spiffe_id")
            if ident not in self.config.expected_spiffe_ids or value.get("verified_by")!="go-spiffe.x509svid.Verify": raise IdentityDenied("X509 identity not verified by pinned SDK")
            chain=tuple(base64.b64decode(v,validate=True) for v in value["certificates"])
            if not 1<=len(chain)<=16: raise IdentityDenied("invalid workload chain")
            leaf=x509.load_der_x509_certificate(chain[0]); key=base64.b64decode(value["private_key_pkcs8"],validate=True)
            signer=serialization.load_der_private_key(key,password=None)
            cert_key=leaf.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
            own_key=signer.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
            uris=leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.UniformResourceIdentifier)
            expiry=int(leaf.not_valid_after_utc.timestamp()); before=int(leaf.not_valid_before_utc.timestamp())
            if uris!=[ident] or cert_key!=own_key or expiry!=value["expires_at"] or before!=value["not_before"] or expiry-before>self.config.max_ttl_seconds:
                raise IdentityDenied("workload certificate/key/TTL mismatch")
            if not before<=self.clock()<expiry: raise IdentityDenied("workload certificate outside validity window")
            chain_expiry=value.get("verification_expires_at",expiry)
            if type(chain_expiry) is not int or not self.clock()<chain_expiry<=expiry: raise IdentityDenied("verified trust path expired")
            parsed[ident]=X509WorkloadCredential(ident,expiry,before,chain,key,chain_expiry)
        selected={}
        for domain,certs in bundles.items():
            if domain not in self.config.trust_domains: continue
            if not isinstance(certs,list) or not 1<=len(certs)<=64: raise IdentityDenied("invalid trust bundle")
            selected[domain]=tuple(base64.b64decode(v,validate=True) for v in certs)
            for cert in selected[domain]: x509.load_der_x509_certificate(cert)
        if any(urlsplit(ident).netloc not in selected for ident in parsed): raise IdentityDenied("issued workload trust bundle missing")
        with self._lock: self._credentials=parsed; self._x509_bundles=selected; self._healthy=bool(parsed); self._error=None
        self._ready.set()
        if callable(self.on_identity_change): self.on_identity_change({"available":bool(parsed),"identities":[v.public_metadata() for v in parsed.values()],
            "trust_bundle_sha256":identity_digest({k:[hashlib.sha256(v).hexdigest() for v in values] for k,values in selected.items()})})
    async def _read(self):
        try:
            while True:
                raw=await self.process.stdout.readline()
                if not raw or len(raw)>8_000_000: raise IdentityDenied("SPIRE helper disconnected/bound exceeded")
                frame=strict_json(raw); kind=frame.get("type")
                if kind=="x509_context": self._x509_update(frame)
                elif kind=="jwt_bundles":
                    bundles=frame.get("bundles")
                    if not isinstance(bundles,dict) or len(bundles)>64: raise IdentityDenied("invalid JWT bundles")
                    chosen={k:strict_json(base64.b64decode(v,validate=True)) for k,v in bundles.items() if k in self.config.trust_domains}
                    with self._lock: self._jwt_bundles=chosen
                elif kind in {"jwt_svid","error"} and frame.get("id"):
                    future=self._pending.get(frame["id"])
                    if future is None or future.done(): continue
                    if kind=="error": future.set_exception(IdentityDenied("SPIRE JWT identity unavailable"))
                    else: future.set_result(frame)
                elif kind=="watch_error":
                    if frame.get("stream")=="x509": self._unavailable("WORKLOAD_SUBSCRIPTION_UNAVAILABLE")
                    else:
                        with self._lock: self._jwt_bundles={}
                elif kind=="error": self._unavailable("SDK_VERIFICATION_DENIED")
                else: raise IdentityDenied("unexpected SPIRE helper frame")
        except asyncio.CancelledError: raise
        except Exception: self._unavailable("WORKLOAD_CHANNEL_UNAVAILABLE")
        finally:
            for future in self._pending.values():
                if not future.done(): future.set_exception(IdentityDenied("Workload API channel ended"))
            if self.owner: await asyncio.shield(self.owner.close())
    def credential(self,spiffe_id):
        with self._lock:
            value=self._credentials.get(spiffe_id)
            if not self._healthy or value is None or not value.not_before<=self.clock()<min(value.expires_at,value.verification_expires_at or value.expires_at):
                raise IdentityDenied("workload identity missing/revoked/expired")
            return value
    def authenticate(self,spiffe_id):
        value=self.credential(spiffe_id); issuer="spiffe://"+urlsplit(spiffe_id).netloc
        return AuthenticatedPrincipal(principal_id(issuer,spiffe_id,kind="spiffe"),issuer,spiffe_id,"spiffe",min(value.expires_at,value.verification_expires_at or value.expires_at))
    async def jwt_svid(self,*,spiffe_id,audience,timeout=6):
        self.authenticate(spiffe_id)
        if audience not in self.config.audiences: raise IdentityDenied("workload JWT audience not configured")
        request_id=uuid.uuid4().hex; future=asyncio.get_running_loop().create_future(); self._pending[request_id]=future
        try:
            await self._send({"id":request_id,"method":"fetch_jwt","spiffe_id":spiffe_id,"audience":audience})
            frame=await asyncio.wait_for(future,timeout)
            if (frame.get("spiffe_id")!=spiffe_id or frame.get("audience")!=audience or frame.get("verified_by")!="SPIRE.ValidateJWTSVID"
                or type(frame.get("expires_at")) is not int or not self.clock()<frame["expires_at"]<=self.clock()+self.config.max_ttl_seconds
                or not isinstance(frame.get("token"),str) or len(frame["token"])>16384): raise IdentityDenied("workload JWT receipt mismatch")
            self.authenticate(spiffe_id)
            return JWTWorkloadCredential(spiffe_id,audience,frame["expires_at"],frame["token"])
        finally: self._pending.pop(request_id,None)
    def trust_bundles(self):
        with self._lock:
            if not self._healthy: raise IdentityDenied("workload subscription unavailable")
            return {"x509":dict(self._x509_bundles),"jwt":copy.deepcopy(self._jwt_bundles)}
    async def close(self):
        if self.reader and not self.reader.done(): self.reader.cancel(); await asyncio.gather(self.reader,return_exceptions=True)
        if self.owner: await asyncio.shield(self.owner.close())
        self.process=self.owner=self.reader=None
        self._unavailable("HOST_CLIENT_CLOSED")


class SpireIdentityVeto:
    def __init__(self,client,*,trusted_spiffe_id,core_pdp):
        if trusted_spiffe_id not in client.config.expected_spiffe_ids or not callable(core_pdp): raise ValueError("host-derived SPIFFE identity/CorePDP required")
        self.client,self.spiffe_id,self.core=client,trusted_spiffe_id,core_pdp
    def __call__(self,request):
        try:
            identity=self.client.authenticate(self.spiffe_id)
            if request.principal_id!=identity.principal_id: return PolicyDecision(False,"workload principal mismatch")
            decision=self.core(request)
            if not isinstance(decision,PolicyDecision) or decision.allowed is not True: return PolicyDecision(False,"CorePDP denied")
            self.client.authenticate(self.spiffe_id)
            return PolicyDecision(True,"attested workload and CorePDP permit",decision.constraints)
        except Exception: return PolicyDecision(False,"SPIRE workload identity unavailable")
