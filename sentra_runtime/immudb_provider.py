"""Scoped immutable KV transactions with official immudb proofs and durable anchor."""
import base64
from dataclasses import dataclass,asdict
from urllib.parse import urlsplit

from .audit_delivery import AuditDeliveryStore,AuditBindingConflict,encoded,digest,enqueue_ledger_head,enqueue_audit_entry
from .audit_provider_bridge import OwnedAuditSDKBridge,AuditProviderUnavailable,AuditProviderProofDenied


@dataclass(frozen=True)
class ImmudbAuditConfig:
    owner: str
    workspace_id: str
    endpoint: str
    database: str
    server_uuid: str
    signing_key_file: str
    signing_key_sha256: str
    tls: dict
    def __post_init__(self):
        url=urlsplit(self.endpoint)
        if url.scheme!="https" or not url.hostname or url.port is None or url.username or url.password or url.path or url.query or url.fragment or not self.database or not self.server_uuid:
            raise ValueError("explicit authenticated TLS gRPC/database/UUID profile required")
    def sdk_configuration(self,scope):
        fields=asdict(self);fields.pop("owner");fields.pop("workspace_id"); fields["key_prefix"]="sentra-audit/"+scope+"/";return fields


class ImmudbAuditProvider:
    def __init__(self,*,config,store:AuditDeliveryStore,executable,executable_sha256,credential_provider,enabled=False,bridge=None):
        if not enabled or (config.owner,config.workspace_id)!=(store.owner,store.workspace_id): raise ValueError("immudb owner scope/opt-in mismatch")
        self.config,self.store=config,store
        self.bridge=bridge or OwnedAuditSDKBridge(executable=executable,executable_sha256=executable_sha256,provider="immudb",
            configuration=config.sdk_configuration(store.scope),credential_provider=credential_provider,enabled=True)
    @property
    def profile_sha256(self): return self.bridge.profile_sha256
    async def connect(self): return await self.bridge.start()
    def initialize_trust(self,*,immutable_state_protobuf:bytes):
        if not immutable_state_protobuf or len(immutable_state_protobuf)>65536: raise ValueError("operator-approved native ImmutableState bytes required")
        # First write/read verifies this anchor's signature before network effects.
        # This is an explicit operator seed, never a JSON state fetched then trusted.
        self.store.initialize_head("immudb",self.profile_sha256,{"immutable_state":base64.b64encode(immutable_state_protobuf).decode(),"source":"operator-pinned seed; verify signature on first provider operation"})
    def enqueue_head(self,ledger,*,source_id): return enqueue_ledger_head(self.store,ledger,provider="immudb",profile_sha256=self.profile_sha256,source_id=source_id)
    def enqueue_entry(self,ledger,*,source_id,sequence): return enqueue_audit_entry(self.store,ledger,provider="immudb",profile_sha256=self.profile_sha256,source_id=source_id,sequence=sequence)
    def _row(self,key):
        row=self.store.row(key)
        if (row["provider"],row["profile_sha256"],row["body"].get("scope_sha256"))!=("immudb",self.profile_sha256,self.store.scope): raise AuditBindingConflict("immutable record scope/profile mismatch")
        return row
    def _payload(self,row,head):
        raw_key=(self.config.sdk_configuration(self.store.scope)["key_prefix"]+digest(row["event_id"])).encode()
        return {"key":base64.b64encode(raw_key).decode(),"value":base64.b64encode(encoded(row["body"])).decode(),"anchor":head["value"]["immutable_state"]}
    async def _finish(self,row,result,head,payload):
        if result.get("verified") is not True or result.get("database")!=self.config.database or result.get("server_uuid")!=self.config.server_uuid or type(result.get("tx_id")) is not int:
            raise AuditProviderProofDenied("IMMUTABLE_NATIVE_RECEIPT_INVALID")
        proof=self.store.proof_blob(base64.b64decode(result["proof"],validate=True))
        receipt={"tx_id":result["tx_id"],"database":result["database"],"server_uuid":result["server_uuid"],"proof":proof,"previous_state":payload["anchor"],
            "verified_state":result["anchor"],"body_sha256":row["body_sha256"],"verified_by":result["verified_by"],"proves_core_effect_coverage":False}
        self.store.update(row["id"],state="CONFIRMED",receipt=receipt,head={"immutable_state":result["anchor"]},expected_head_revision=head["revision"])
        return receipt
    async def publish(self,key):
        row=self._row(key)
        if row["state"]=="CONFIRMED": return row["receipt"]
        head=self.store.head("immudb",self.profile_sha256)
        if head is None: raise AuditProviderUnavailable("trusted native signed ImmutableState/genesis seed required")
        if self.bridge.process is None: raise AuditProviderUnavailable("SDK not connected; export remains queued")
        row=self.store.claim(key,provider="immudb",profile_sha256=self.profile_sha256);payload=self._payload(row,head)
        try: result=await self.bridge.call("publish",payload);return await self._finish(row,result,head,payload)
        except AuditProviderProofDenied as exc:
            ref=self.store.divergence("immudb",{"code":exc.code,"evidence":exc.evidence,"previous_state":payload["anchor"]})
            self.store.update(key,state="UNCERTAIN",receipt={"proof_denied":exc.code,"divergence_id":ref,"write_repeated":False});raise
        except BaseException:
            self.store.update(key,state="UNCERTAIN",receipt={"transaction_outcome_unknown":True,"write_repeated":False});raise
    async def observe(self,key):
        row=self._row(key)
        if row["state"]=="CONFIRMED": return row["receipt"]
        if row["state"]=="QUEUED": raise AuditBindingConflict("no attempted write to observe")
        head=self.store.head("immudb",self.profile_sha256)
        if head is None: raise AuditProviderUnavailable("trusted state absent")
        payload=self._payload(row,head)
        if (row["receipt"] or {}).get("tx_id"): payload["at_tx"]=row["receipt"]["tx_id"]
        try: result=await self.bridge.call("observe",payload)
        except AuditProviderProofDenied as exc:
            self.store.divergence("immudb",{"code":exc.code,"evidence":exc.evidence,"previous_state":payload["anchor"]});raise
        return await self._finish(row,result,head,payload)
    async def verify(self,key):
        row=self._row(key);receipt=row["receipt"]
        if row["state"]!="CONFIRMED": raise AuditProviderUnavailable("no verified retained record")
        payload=self._payload(row,{"value":{"immutable_state":receipt["previous_state"]}})
        payload.update(at_tx=receipt["tx_id"],proof=base64.b64encode(self.store.read_blob(receipt["proof"]["blob_id"])).decode())
        return await self.bridge.call("verify_offline",payload)
    async def export_transaction(self,key):
        row=self._row(key)
        if row["state"]!="CONFIRMED": raise AuditProviderUnavailable("only verified committed transaction may export")
        head=self.store.head("immudb",self.profile_sha256);payload=self._payload(row,head);payload["at_tx"]=row["receipt"]["tx_id"]
        result=await self.bridge.call("export_tx",payload)
        exported=base64.b64decode(result.pop("export"),validate=True);blob=self.store.proof_blob(exported)
        reference={**result,"export_blob":blob,"restores_all_sentra_artifacts":False}
        self.store.update(key,state="CONFIRMED",receipt={**row["receipt"],"transaction_export":reference})
        return reference
    async def status(self): return {"local":self.store.status(),"client":self.bridge.local_status(),"database":await self.bridge.call("status")}
    async def close(self): await self.bridge.close()
