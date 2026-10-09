"""Prepared wire-contract fixture tests. RecordingJetStream is NOT a broker.

Opt-in real SDK/broker acceptance is separate and skips without owner profile.
"""
import asyncio
import base64
import json
import os
from pathlib import Path

import pytest

from sentra_runtime.audit_delivery import AuditDeliveryStore,AuditBindingConflict
from sentra_runtime.audit_provider_bridge import AuditProviderUnavailable
from sentra_runtime.nats_jetstream import NATSJetStreamConfig,NATSJetStreamProvider


def config():
    return NATSJetStreamConfig("tls://nats.example.invalid:4222","SENTRA_EVENTS","SENTRA_HOST","owner","workspace",
        {"ca_file":"C:/unconfigured/ca.pem","ca_sha256":"0"*64,"server_name":"nats.example.invalid","spki_sha256":"0"*64},
        max_age_seconds=60,duplicate_window_seconds=10,batch=1,max_ack_pending=2)


class RecordingJetStream:
    """Only validates provider call sequencing; never external service evidence."""
    profile_sha256="1"*64
    process=object()
    lose_ack=False
    def __init__(self): self.calls=[];self.events={};self.messages=[];self.store=None
    async def call(self,method,payload=None):
        self.calls.append((method,payload))
        if method=="publish":
            self.events[payload["subject"]]=payload
            if self.lose_ack: raise AuditProviderUnavailable("explicit protocol fixture lost ACK")
            return {"stream":"SENTRA_EVENTS","sequence":1,"duplicate":False}
        if method=="lookup":
            found=self.events.get(payload["subject"])
            return {"found":bool(found),"data":base64.b64encode(json.dumps(found["body"]).encode()).decode() if found else "",
                "message_id":found["message_id"] if found else None,"sequence":1}
        if method=="pull": return {"messages":self.messages}
        if method=="ack": assert self.store.notifications(),"inbox must persist before ack"
        return {"sent":True,"broker_ack_confirmed":method=="ack","fixture_only":True}
    async def close(self): self.process=None


def fixture_provider(root):
    local=AuditDeliveryStore(root/"nats.sqlite",workspace_root=root,owner="owner",workspace_id="workspace",retention_seconds=60,clock=lambda:1000)
    wire=RecordingJetStream();wire.store=local
    provider=NATSJetStreamProvider(config=config(),store=local,executable=str(root/"not-built.exe"),executable_sha256="0"*64,
        credential_provider=lambda *args:{},enabled=True,bridge=wire)
    return provider,wire,local


def test_puback_persists_and_lost_ack_lookup_never_republishes(tmp_path):
    provider,wire,local=fixture_provider(tmp_path)
    async def case():
        key=provider.enqueue(event_id="existing-status-notice",kind="operation_status",references={"operation_id":"existing-op","state":"UNCERTAIN"})
        assert provider.enqueue(event_id="existing-status-notice",kind="operation_status",references={"operation_id":"existing-op","state":"UNCERTAIN"})==key
        wire.lose_ack=True
        with pytest.raises(AuditProviderUnavailable): await provider.publish(key)
        assert local.row(key)["state"]=="UNCERTAIN"
        with pytest.raises(AuditBindingConflict): await provider.publish(key)
        result=await provider.reconcile(key)
        assert not result["proves_core_effect"] and local.row(key)["state"]=="CONFIRMED"
        assert len([c for c in wire.calls if c[0]=="publish"])==1
    asyncio.run(case())


def test_pull_persists_before_ack_dedupe_and_commands_term_without_execution(tmp_path):
    provider,wire,local=fixture_provider(tmp_path)
    key=provider.enqueue(event_id="notice1",kind="provider_health",references={"provider_id":"provider1","status":"offline"})
    body=local.row(key)["body"]
    wire.messages=[{"handle":"handle1","data":base64.b64encode(json.dumps(body).encode()).decode(),"subject":provider.subject(body),"stream_sequence":1,"deliveries":1}]
    async def case():
        first=await provider.pull();second=await provider.pull()
        assert not first[0]["duplicate"] and second[0]["duplicate"] and not second[0]["effects_executed"]
        malicious={**body,"command":"delete files"}
        wire.messages=[{"handle":"bad","data":base64.b64encode(json.dumps(malicious).encode()).decode(),"subject":provider.subject(body),"stream_sequence":2,"deliveries":2}]
        denied=await provider.pull()
        assert denied[0]["quarantined"] and not denied[0]["effects_executed"]
        assert wire.calls[-1][0]=="term"
        assert all(method not in {"execute","create_run","create_work_item","grant"} for method,_ in wire.calls)
    asyncio.run(case())


def test_real_jetstream_sdk_opt_in(tmp_path):
    profile_path=os.environ.get("SENTRA_ACCEPTANCE_NATS_PROFILE")
    if not profile_path: pytest.skip("requires real TLS broker + pinned SDK + scoped credentials; no simulated broker fallback")
    from sentra_remote.secrets import unprotect_secret
    profile=json.loads(Path(profile_path).read_text(encoding="utf8"));cfg=NATSJetStreamConfig(**profile["configuration"])
    local=AuditDeliveryStore(tmp_path/"real-nats.sqlite",workspace_root=tmp_path,owner=cfg.owner,workspace_id=cfg.workspace_id,retention_seconds=cfg.max_age_seconds)
    def credentials(*args): return json.loads(unprotect_secret(profile["protected_credentials"]))
    provider=NATSJetStreamProvider(config=cfg,store=local,executable=profile["executable"],executable_sha256=profile["executable_sha256"],credential_provider=credentials,enabled=True)
    async def case():
        await provider.connect()
        try:
            if profile.get("allow_resource_administration") is True: await provider.configure(trusted_admin_authorize=lambda *args:True)
            key=provider.enqueue(event_id="acceptance-"+str(int(local.clock())),kind="provider_health",references={"provider_id":"acceptance","status":"test-notification"})
            receipt=await provider.publish(key)
            assert receipt["ack_kind"]=="JetStream PubAck" and receipt["sequence"]>0
            notices=await provider.pull()
            assert any(notice.get("event_id")==local.row(key)["event_id"] for notice in notices)
            assert (await provider.status())["jetstream"]["connected"] is True
        finally: await provider.close()
    asyncio.run(case())
