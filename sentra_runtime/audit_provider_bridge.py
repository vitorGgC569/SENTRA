"""Bounded owned IPC to genuine NATS/immudb/Tessera SDK clients.

Not a compatibility server. No constructor launches a process or contacts a
provider. Credentials are supplied by trusted host callback over private stdin.
"""
import asyncio
import hashlib
import json
import inspect
import uuid
import time
import math
from pathlib import Path

from sentra_interop.acp_process import spawn_owned
from .audit_delivery import digest


class AuditProviderUnavailable(RuntimeError): pass
class AuditProviderProofDenied(PermissionError):
    def __init__(self,code,evidence=None): self.code=code; self.evidence=evidence or {}; super().__init__(code)


class OwnedAuditSDKBridge:
    METHODS={"nats":{"configure","status","publish","lookup","pull","ack","nak","term","progress"},
        "immudb":{"status","publish","observe","export_tx","verify_offline"},
        "tessera":{"status","publish","observe","find","verify_checkpoint","verify_offline"}}
    def __init__(self,*,executable,executable_sha256,provider,configuration,credential_provider,enabled=False,timeout=15):
        if not enabled or provider not in self.METHODS or not Path(executable).is_absolute() or not callable(credential_provider) or not 1<=timeout<=120:
            raise ValueError("explicit pinned SDK/host credentials required")
        self.executable,self.executable_sha256,self.provider=Path(executable),executable_sha256,provider
        self.configuration=json.loads(json.dumps(configuration,allow_nan=False)); self.credential_provider=credential_provider
        self.timeout=timeout; self.process=self.owner=None; self._lock=asyncio.Lock(); self._tainted=False
        self._credential_deadline=None
    @property
    def profile_sha256(self): return digest({"provider":self.provider,"binary_sha256":self.executable_sha256,"config":self.configuration})
    async def start(self):
        if self.process is not None: raise AuditProviderUnavailable("SDK process already started")
        if self.executable.is_symlink() or not self.executable.is_file() or hashlib.sha256(self.executable.read_bytes()).hexdigest()!=self.executable_sha256:
            raise AuditProviderUnavailable("SDK binary dependency missing/pin mismatch")
        credentials=self.credential_provider(self.provider,self.profile_sha256)
        if inspect.isawaitable(credentials): credentials=await credentials
        if not isinstance(credentials,dict): raise ValueError("host credential callback must return secret object")
        credentials=dict(credentials)
        deadline=credentials.pop("_expires_at",None)
        if deadline is not None:
            if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<=time.time(): raise AuditProviderUnavailable("host credential expired")
            self._credential_deadline=deadline
        else: self._credential_deadline=None
        if any(not isinstance(v,str) for v in credentials.values()): raise ValueError("SDK credential values must be strings")
        self.process,self.owner=await spawn_owned(str(self.executable),(),env={},stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=32_000_001,checkpoint=self._checkpoint)
        try:
            await self._write({"version":1,"provider":self.provider,"configuration":self.configuration,"credentials":credentials})
            frame=await asyncio.wait_for(self._read(),self.timeout)
            if frame.get("type")!="ready": raise AuditProviderUnavailable("real SDK provider initialization unavailable")
        except BaseException: await self.close(); raise
        self._tainted=False
        return {"sdk_client_started":True,"profile_sha256":self.profile_sha256,"provider":self.provider,"remote_service_verified":False}
    async def _write(self,value):
        self._checkpoint()
        raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()+b"\n"
        if len(raw)>32_000_000: raise ValueError("SDK request exceeds frame bound")
        self.process.stdin.write(raw); await self.process.stdin.drain()
    async def _read(self):
        raw=await self.process.stdout.readline()
        if not raw or len(raw)>32_000_000: raise AuditProviderUnavailable("SDK response disconnected/bound exceeded")
        def unique(pairs):
            obj={}
            for key,value in pairs:
                if key in obj: raise AuditProviderUnavailable("duplicate SDK response field")
                obj[key]=value
            return obj
        value=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(AuditProviderUnavailable("nonfinite SDK response")))
        if not isinstance(value,dict): raise AuditProviderUnavailable("invalid SDK response")
        return value
    async def call(self,method,payload=None):
        self._checkpoint()
        if method not in self.METHODS[self.provider]: raise ValueError("unknown provider method; arbitrary commands refused")
        if self.process is None or self._tainted: raise AuditProviderUnavailable("SDK bridge not started or response uncertain")
        if self._credential_deadline is not None and self._credential_deadline<=time.time():
            await self.close(); raise AuditProviderUnavailable("host credential expired; explicit reauthentication required")
        async with self._lock:
            key=uuid.uuid4().hex
            try:
                await self._write({"id":key,"method":method,"payload":payload or {}})
                frame=await asyncio.wait_for(self._read(),self.timeout)
                if frame.get("id")!=key: raise AuditProviderUnavailable("SDK response identity mismatch")
                if frame.get("type")=="proof_denied": raise AuditProviderProofDenied(frame.get("code","PROOF_DENIED"),frame.get("evidence",{}))
                if frame.get("type")!="result": raise AuditProviderUnavailable(frame.get("code","PROVIDER_UNAVAILABLE"))
                self._checkpoint()
                return frame.get("result")
            except AuditProviderProofDenied: raise
            except BaseException:
                self._tainted=True; await self.close(); raise
    async def close(self):
        if self.owner: await asyncio.shield(self.owner.close())
        self.process=self.owner=None
    @staticmethod
    def _checkpoint():
        # Borrow an enclosing host physical scope if one exists. Never reserve
        # an Operation/lock/ack of our own for auxiliary transport delivery.
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        if context is not None: context.checkpoint()
    def local_status(self):
        return {"provider":self.provider,"profile_sha256":self.profile_sha256,"client_running":self.process is not None,
                "completion_uncertain":self._tainted,"service_operational_claimed":False}
