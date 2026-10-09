"""Real Tessera add/tiles proof client, retaining signed roots and divergences."""
import base64
import json
from dataclasses import dataclass,asdict
from urllib.parse import urlsplit

from .audit_delivery import AuditDeliveryStore,AuditBindingConflict,encoded,enqueue_ledger_head,enqueue_audit_entry
from .audit_provider_bridge import OwnedAuditSDKBridge,AuditProviderUnavailable,AuditProviderProofDenied


@dataclass(frozen=True)
class TesseraConfig:
    owner: str
    workspace_id: str
    read_url: str
    write_url: str
    origin: str
    log_key: str
    witnesses: tuple
    witness_quorum: int
    tls: dict
    api_profile: str = "tessera-conformance-add-tiles-v1"
    max_leaf_bytes: int = 4096
    def __post_init__(self):
        urls=[urlsplit(v) for v in (self.read_url,self.write_url)]
        if any(v.scheme!="https" or not v.hostname or v.username or v.password or v.query or v.fragment for v in urls) or urls[0].netloc!=urls[1].netloc:
            raise ValueError("pinned same-origin Tessera HTTPS profile required")
        object.__setattr__(self,"witnesses",tuple(self.witnesses))
        if self.api_profile!="tessera-conformance-add-tiles-v1" or not self.origin or not self.log_key or not 1<=self.witness_quorum<=len(self.witnesses) or not 1<=self.max_leaf_bytes<=65535:
            raise ValueError("real add/tiles profile and nonzero witness quorum required")
        if not all(isinstance(w,dict) and set(w)=={"key","url"} for w in self.witnesses): raise ValueError("explicit independent witness keys/endpoints required")
    def sdk_configuration(self):
        fields=asdict(self); fields.pop("owner");fields.pop("workspace_id"); return fields


class TesseraAuditProvider:
    def __init__(self,*,config,store:AuditDeliveryStore,executable,executable_sha256,credential_provider,enabled=False,bridge=None):
        if not enabled or (config.owner,config.workspace_id)!=(store.owner,store.workspace_id): raise ValueError("Tessera host scope/opt-in mismatch")
        self.config,self.store=config,store
        self.bridge=bridge or OwnedAuditSDKBridge(executable=executable,executable_sha256=executable_sha256,provider="tessera",configuration=config.sdk_configuration(),credential_provider=credential_provider,enabled=True)
    @property
    def profile_sha256(self): return self.bridge.profile_sha256
    async def connect(self): return await self.bridge.start()
    async def initialize_trust(self,*,checkpoint:bytes):
        result=await self.bridge.call("verify_checkpoint",{"previous_checkpoint":base64.b64encode(checkpoint).decode()})
        if result.get("verified") is not True: raise AuditProviderProofDenied("CHECKPOINT_NOT_VERIFIED")
        self.store.initialize_head("tessera",self.profile_sha256,{"checkpoint":base64.b64encode(checkpoint).decode(),"tree_size":result["tree_size"],"root_hash":result["root_hash"]})
        return {"trusted_checkpoint_initialized":True,"witness_quorum":self.config.witness_quorum}
    def enqueue_head(self,ledger,*,source_id): return enqueue_ledger_head(self.store,ledger,provider="tessera",profile_sha256=self.profile_sha256,source_id=source_id)
    def enqueue_entry(self,ledger,*,source_id,sequence): return enqueue_audit_entry(self.store,ledger,provider="tessera",profile_sha256=self.profile_sha256,source_id=source_id,sequence=sequence)
    def _row(self,key):
        row=self.store.row(key)
        if (row["provider"],row["profile_sha256"],row["body"].get("scope_sha256"))!=("tessera",self.profile_sha256,self.store.scope): raise AuditBindingConflict("Tessera source/profile/scope mismatch")
        if len(encoded(row["body"]))>self.config.max_leaf_bytes: raise ValueError("log entry bundle leaf bound")
        return row
    async def publish(self,key):
        row=self._row(key)
        if row["state"]=="CONFIRMED": return row["receipt"]
        head=self.store.head("tessera",self.profile_sha256)
        if head is None: raise AuditProviderUnavailable("verified operator checkpoint must initialize trust before append")
        if self.bridge.process is None: raise AuditProviderUnavailable("real client not started; export remains queued")
        row=self.store.claim(key,provider="tessera",profile_sha256=self.profile_sha256)
        before={"previous_checkpoint":head["value"]["checkpoint"],"scan_start":head["value"]["tree_size"],"append_repeated":False}
        self.store.update(key,state="UNCERTAIN",receipt=before)
        try:
            result=await self.bridge.call("publish",{"leaf":base64.b64encode(encoded(row["body"])).decode(),"previous_checkpoint":head["value"]["checkpoint"]})
            if type(result.get("index")) is not int or result["index"]<0: raise AuditProviderUnavailable("Tessera native decimal commit index missing")
            receipt={**before,**result,"cryptographic_inclusion_verified":False,"proves_core_effect_coverage":False}
            self.store.update(key,state="PENDING_INCLUSION",receipt=receipt);return receipt
        except BaseException: raise  # persisted uncertain append identity is never silently retried
    async def observe(self,key,*,max_scan=256):
        row=self._row(key)
        if row["state"]=="CONFIRMED": return row["receipt"]
        previous=self.store.head("tessera",self.profile_sha256)
        if previous is None: raise AuditProviderUnavailable("trusted checkpoint absent")
        reference=row["receipt"] or {}
        payload={"leaf":base64.b64encode(encoded(row["body"])).decode(),"previous_checkpoint":previous["value"]["checkpoint"]}
        method="observe"
        if "index" in reference: payload["index"]=reference["index"]
        else:
            if "scan_start" not in reference: raise AuditBindingConflict("append never admitted; do not invent an index")
            method="find";payload.update(start_index=reference["scan_start"],max_scan=max_scan)
        try: result=await self.bridge.call(method,payload)
        except AuditProviderProofDenied as exc:
            ref=self.store.divergence("tessera",{"code":exc.code,"evidence":exc.evidence,"previous_checkpoint":previous["value"]["checkpoint"]})
            self.store.update(key,state="UNCERTAIN",receipt={**reference,"divergence_id":ref,"proof_denied":exc.code});raise
        if result.get("status")!="VERIFIED": return {**reference,**result,"verified":False,"append_repeated":False}
        evidence=result["evidence"]
        if evidence.get("leaf")!=payload["leaf"] or evidence.get("previous_checkpoint")!=payload["previous_checkpoint"]:
            raise AuditProviderProofDenied("RETAINED_EVIDENCE_BINDING_MISMATCH")
        blob=self.store.proof_blob(json.dumps(evidence,allow_nan=False,separators=(",",":")).encode())
        receipt={"status":"VERIFIED","index":result["index"],"tree_size":result["tree_size"],"root_hash":result["root_hash"],"proof":blob,
            "verified_by":result["verified_by"],"witness_quorum":result["witness_quorum"],"body_sha256":row["body_sha256"],"proves_core_effect_coverage":False}
        head={"checkpoint":evidence["checkpoint"],"tree_size":result["tree_size"],"root_hash":result["root_hash"]}
        self.store.update(key,state="CONFIRMED",receipt=receipt,head=head,expected_head_revision=previous["revision"]);return receipt
    async def verify(self,key):
        row=self._row(key)
        if row["state"]!="CONFIRMED": raise AuditProviderUnavailable("no retained verified proof")
        evidence=json.loads(self.store.read_blob(row["receipt"]["proof"]["blob_id"]))
        if evidence.get("leaf")!=base64.b64encode(encoded(row["body"])).decode(): raise AuditProviderProofDenied("PROOF_BODY_CHANGED")
        return await self.bridge.call("verify_offline",{"evidence":evidence})
    async def status(self): return {"local":self.store.status(),"client":self.bridge.local_status(),"log":await self.bridge.call("status")}
    async def close(self): await self.bridge.close()
