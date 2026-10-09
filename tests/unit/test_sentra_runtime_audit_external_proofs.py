"""Prepared proof-denial lifecycle and opt-in official SDK evidence tests.

No positive cryptographic claim is produced by a JSON/scripted proof fixture.
"""
import asyncio
import base64
import json
import os
from pathlib import Path

import pytest

from sentra_runtime.audit_delivery import AuditDeliveryStore
from sentra_runtime.audit_provider_bridge import AuditProviderProofDenied,OwnedAuditSDKBridge
from sentra_runtime.tessera_provider import TesseraConfig,TesseraAuditProvider
from sentra_runtime.sqlite_audit import SQLiteAuditLedger


class RejectProofOnly:
    profile_sha256="1"*64
    process=object()
    def __init__(self): self.calls=[]
    async def call(self,method,payload):
        self.calls.append((method,payload))
        if method=="publish": return {"status":"PENDING_INCLUSION","index":4,"cryptographic_inclusion_verified":False}
        raise AuditProviderProofDenied("EXPLICIT_NEGATIVE_PROOF_FIXTURE",{"checkpoint":"not a valid signed note"})


def test_tessera_divergence_keeps_anchor_and_never_implicitly_appends_again(tmp_path):
    local=AuditDeliveryStore(tmp_path/"audit.sqlite",workspace_root=tmp_path,owner="owner",workspace_id="workspace",retention_seconds=60)
    cfg=TesseraConfig("owner","workspace","https://log.example.invalid/","https://log.example.invalid/","origin","not-real-key",
        ({"key":"not-real-witness","url":"https://witness.example.invalid/"},),1,{})
    wire=RejectProofOnly()
    provider=TesseraAuditProvider(config=cfg,store=local,executable=str(tmp_path/"missing.exe"),executable_sha256="0"*64,credential_provider=lambda *args:{},enabled=True,bridge=wire)
    # Local projection fixture, never accepted via the real SDK verifier.
    previous={"checkpoint":base64.b64encode(b"explicit fixture only").decode(),"tree_size":4,"root_hash":"not a Merkle root"}
    local.initialize_head("tessera",wire.profile_sha256,previous)
    ledger=SQLiteAuditLedger(tmp_path/"existing-ledger.sqlite");ledger.append({"operation_id":"existing-op"})
    key=provider.enqueue_entry(ledger,source_id="source",sequence=1)
    async def case():
        assert (await provider.publish(key))["cryptographic_inclusion_verified"] is False
        with pytest.raises(AuditProviderProofDenied): await provider.observe(key)
        assert local.row(key)["state"]=="UNCERTAIN" and local.head("tessera",wire.profile_sha256)["value"]==previous
        assert local.row(key)["receipt"]["divergence_id"]
        assert len([c for c in wire.calls if c[0]=="publish"])==1
    asyncio.run(case())


def test_real_sdk_offline_retained_proof_opt_in():
    path=os.environ.get("SENTRA_ACCEPTANCE_AUDIT_PROOF_PROFILE")
    if not path: pytest.skip("requires built pinned official SDK + authentic retained proof artifacts; never JSON-only success")
    from sentra_remote.secrets import unprotect_secret
    profile=json.loads(Path(path).read_text(encoding="utf8"))
    bridge=OwnedAuditSDKBridge(executable=profile["executable"],executable_sha256=profile["executable_sha256"],provider=profile["provider"],
        configuration=profile["configuration"],credential_provider=lambda *args:json.loads(unprotect_secret(profile["protected_credentials"])),enabled=True)
    payload=json.loads(Path(profile["verification_payload_file"]).read_text(encoding="utf8"))
    async def case():
        await bridge.start()
        try:
            assert (await bridge.call("verify_offline",payload))["verified"] is True
            tampered=json.loads(json.dumps(payload))
            if profile["provider"]=="tessera": tampered["evidence"]["leaf"]=base64.b64encode(b"tampered leaf").decode()
            else: tampered["value"]=base64.b64encode(b"tampered value").decode()
            with pytest.raises(AuditProviderProofDenied): await bridge.call("verify_offline",tampered)
        finally: await bridge.close()
    asyncio.run(case())


def test_real_immudb_signed_state_write_read_export_opt_in(tmp_path):
    path=os.environ.get("SENTRA_ACCEPTANCE_IMMUDB_PROFILE")
    if not path: pytest.skip("requires real TLS immudb, pinned UUID/signing key, native trusted state and SDK; no mock proof success")
    from sentra_runtime.immudb_provider import ImmudbAuditConfig,ImmudbAuditProvider
    from sentra_remote.secrets import unprotect_secret
    profile=json.loads(Path(path).read_text(encoding="utf8"));cfg=ImmudbAuditConfig(**profile["configuration"])
    local=AuditDeliveryStore(tmp_path/"real-delivery.sqlite",workspace_root=tmp_path,owner=cfg.owner,workspace_id=cfg.workspace_id)
    provider=ImmudbAuditProvider(config=cfg,store=local,executable=profile["executable"],executable_sha256=profile["executable_sha256"],
        credential_provider=lambda *args:json.loads(unprotect_secret(profile["protected_credentials"])),enabled=True)
    # Native protobuf seed approved by operator; never generated from JSON here.
    provider.initialize_trust(immutable_state_protobuf=Path(profile["trusted_state_protobuf_file"]).read_bytes())
    ledger=SQLiteAuditLedger(tmp_path/"source.sqlite");ledger.append({"operation_id":"existing-test-reference","acceptance":"actual source entry"})
    key=provider.enqueue_entry(ledger,source_id="acceptance-source-"+str(int(local.clock())),sequence=1)
    async def case():
        await provider.connect()
        try:
            receipt=await provider.publish(key)
            assert receipt["tx_id"]>0 and receipt["verified_by"].startswith("immudb official")
            assert (await provider.verify(key))["verified"] is True
            exported=await provider.export_transaction(key)
            assert exported["raw_export_independently_verified"] is True and exported["replication_executed"] is False
            assert local.read_blob(exported["export_blob"]["blob_id"])
            assert local.row(key)["receipt"]["transaction_export"]["tx_id"]==receipt["tx_id"]
        finally: await provider.close()
    asyncio.run(case())
