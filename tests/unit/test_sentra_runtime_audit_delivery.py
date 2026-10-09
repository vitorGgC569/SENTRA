"""Prepared projection/outbox tests, not proofs of external providers.

Actual protected SQLite and existing audit ledger are used. Opaque blob
fixtures test retention/integrity only; they are never cryptographic proofs.
"""
import pytest

from sentra_runtime.audit_delivery import AuditDeliveryStore,AuditBindingConflict,AuditBackpressure,digest,enqueue_audit_entry
from sentra_runtime.sqlite_audit import SQLiteAuditLedger


def store(root,*,clock=None,max_pending=10):
    return AuditDeliveryStore(root/"deliveries.sqlite",workspace_root=root,owner="owner",workspace_id="workspace",
        max_pending=max_pending,retention_seconds=60,clock=clock or (lambda:1000))


def test_source_binding_restart_cas_and_pending_export_never_reclaimed(tmp_path):
    local=store(tmp_path); ledger=SQLiteAuditLedger(tmp_path/"existing-audit.sqlite")
    original=ledger.append({"operation_id":"existing-operation-reference","phase":"effect-evidence","private":"not exported"})
    key=enqueue_audit_entry(local,ledger,provider="tessera",profile_sha256="1"*64,source_id="existing-source",sequence=1)
    row=local.claim(key,provider="tessera",profile_sha256="1"*64)
    assert row["body"]["operation_id"]=="existing-operation-reference" and "private" not in row["body"]
    assert row["body"]["creates_operations"] is False and ledger.head==original.digest
    restarted=store(tmp_path)
    assert restarted.row(key)["state"]=="IN_FLIGHT"
    with pytest.raises(AuditBindingConflict): restarted.claim(key,provider="tessera",profile_sha256="1"*64)
    assert enqueue_audit_entry(restarted,ledger,provider="tessera",profile_sha256="1"*64,source_id="existing-source",sequence=1)==key
    with pytest.raises(AuditBindingConflict): restarted.enqueue(provider="tessera",profile_sha256="1"*64,event_id=row["event_id"],body={"changed":True})
    local.initialize_head("tessera","1"*64,{"projection_fixture":"not a signed checkpoint"})
    local.update(key,state="CONFIRMED",receipt={"fixture":"storage-only"},head={"projection_fixture":"new"},expected_head_revision=0)
    with pytest.raises(AuditBindingConflict): local.update(key,state="CONFIRMED",head={"projection_fixture":"stale"},expected_head_revision=0)
    assert local.head("tessera","1"*64)["value"]=={"projection_fixture":"new"}
    with local.db() as db:
        assert db.execute("SELECT protected_body FROM audit_outbox").fetchone()[0].startswith(("dpapi:","keyring:"))


def test_backpressure_can_drain_and_retention_preserves_identity_tombstones(tmp_path):
    clock=[1000]; local=store(tmp_path,clock=lambda:clock[0],max_pending=1)
    key=local.enqueue(provider="nats",profile_sha256="1"*64,event_id="event1",body={"fixture":1})
    with pytest.raises(AuditBackpressure): local.enqueue(provider="nats",profile_sha256="1"*64,event_id="event2",body={"fixture":2})
    local.claim(key,provider="nats",profile_sha256="1"*64)
    # Confirmation drains a full queue instead of getting stuck at max_pending.
    local.update(key,state="CONFIRMED",receipt={"stream":"fixture-stream","sequence":1,"proves_core_effect":False})
    local.enqueue(provider="nats",profile_sha256="1"*64,event_id="event2",body={"fixture":2})
    clock[0]=1100
    result=local.prune(confirmed_before=1039)
    assert result["immutable_event_tombstones_preserved"] and local.row(key)["state"]=="EXPIRED"
    assert local.enqueue(provider="nats",profile_sha256="1"*64,event_id="event1",body={"fixture":1})==key
    with pytest.raises(AuditBindingConflict): local.claim(key,provider="nats",profile_sha256="1"*64)


def test_proof_blob_integrity_scope_and_inbox_dedupe(tmp_path):
    local=store(tmp_path)
    opaque=b"explicit opaque blob fixture; not a cryptographic proof"*20000
    reference=local.proof_blob(opaque)
    assert local.read_blob(reference["blob_id"])==opaque
    other=AuditDeliveryStore(tmp_path/"deliveries.sqlite",workspace_root=tmp_path,owner="other",workspace_id="workspace",retention_seconds=60)
    with pytest.raises(FileNotFoundError): other.read_blob(reference["blob_id"])
    assert not local.inbox(event_id="notice",body={"reference":"existing"},stream_seq=1)["duplicate"]
    assert local.inbox(event_id="notice",body={"reference":"existing"},stream_seq=1)["duplicate"]
    with pytest.raises(AuditBindingConflict): local.inbox(event_id="notice",body={"command":"forged"},stream_seq=2)
    assert local.notifications()[0]["requires_central_reconciliation"] and not local.notifications()[0]["authorizes_effects"]
