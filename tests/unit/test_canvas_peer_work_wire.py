"""Two real authenticated encrypted peer TCP sockets + SQLite durable receipts.

Transport-only. Receiving TASK_OFFER never starts a worker or grants authority.
"""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import secrets
import sqlite3
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import pytest

from sentra_canvas.peer_work_wire import (
    PeerLoopbackServer, PeerWireDenied, PeerWorkWire, deliver_loopback,
)


def identity():
    key=Ed25519PrivateKey.generate()
    public=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    return SimpleNamespace(
        key=key,
        node_id="peer-"+hashlib.sha256(public).hexdigest(),
        public_key=base64.b64encode(public).decode(),
    )


def pair(tmp_path, *, mesh=None, workspace="qa-workspace"):
    a,b=identity(),identity()
    mesh=mesh or ("SENTRA-MESH-TEST-"+"u"*36)
    alice=PeerWorkWire(
        identity=a,mesh_key=mesh,workspace_id=workspace,
        trust={b.node_id:b.public_key},ledger=tmp_path/"alice.db",
    )
    bob=PeerWorkWire(
        identity=b,mesh_key=mesh,workspace_id=workspace,
        trust={a.node_id:a.public_key},ledger=tmp_path/"bob.db",
    )
    return a,b,alice,bob


def message(alice,bob,*,kind="TASK_OFFER",subject="work-item-1"):
    return alice.seal(
        kind=kind,target=bob.node,subject_id=subject,
        reference_sha256=hashlib.sha256(b"only-a-pinned-reference").hexdigest(),
    )


def test_two_paired_peers_exchange_real_tcp_task_and_durable_ack(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    with_server=PeerLoopbackServer(bob).start()
    try:
        receipt=deliver_loopback(alice,with_server.address,message(alice,bob))
        assert receipt["state"]=="RECEIVED_NOT_EXECUTED"
        assert receipt["recipient"]==b.node_id
        assert len(bob.inbox())==1
        assert bob.inbox()[0]["state"]=="PENDING_LOCAL_ADMISSION"
        assert alice.inbox()[0]["kind"]=="TRANSPORT_ACK"
        # Actual socket delivery and signed ACK != grant or model reply.
        assert bob.inbox()[0]["subject_id"]=="work-item-1"
    finally:
        with_server.close()


def test_real_peer_result_is_pending_verification_not_success(tmp_path):
    _,_,alice,bob=pair(tmp_path)
    server=PeerLoopbackServer(bob).start()
    try:
        reply=deliver_loopback(alice,server.address,
                               message(alice,bob,kind="TASK_RESULT",
                                       subject="op-reference-1"))
        assert reply["state"]=="RECEIVED_NOT_EXECUTED"
        assert bob.inbox()[0]["state"]=="PENDING_RESULT_VERIFICATION"
    finally:server.close()


def test_duplicate_same_ciphertext_remains_single_inbox_after_restart(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    frame=message(alice,bob)
    server=PeerLoopbackServer(bob).start()
    try:
        assert deliver_loopback(alice,server.address,frame)["state"]=="RECEIVED_NOT_EXECUTED"
    finally:server.close()
    # New process-level PeerWorkWire object and real reopened SQLite.
    bob2=PeerWorkWire(identity=b,mesh_key="SENTRA-MESH-TEST-"+"u"*36,
                      workspace_id="qa-workspace",
                      trust={a.node_id:a.public_key},ledger=tmp_path/"bob.db")
    server2=PeerLoopbackServer(bob2).start()
    try:
        assert deliver_loopback(alice,server2.address,frame)["state"]=="RECEIVED_NOT_EXECUTED"
        assert len(bob2.inbox())==1
    finally:server2.close()


def test_unsigned_or_untrusted_peer_is_denied(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    foreign=identity()
    attacker=PeerWorkWire(
        identity=foreign,mesh_key="SENTRA-MESH-TEST-"+"u"*36,
        workspace_id="qa-workspace",
        trust={b.node_id:b.public_key},ledger=tmp_path/"attacker.db",
    )
    frame=message(attacker,bob)
    with pytest.raises(PeerWireDenied):
        bob.accept(frame)
    assert bob.inbox()==[]


def test_wrong_mesh_key_or_workspace_rejected(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    rogue_key=PeerWorkWire(
        identity=b,mesh_key="SENTRA-MESH-TEST-"+"t"*36,
        workspace_id="qa-workspace",
        trust={a.node_id:a.public_key},ledger=tmp_path/"wrong-key.db",
    )
    with pytest.raises(PeerWireDenied):
        rogue_key.accept(message(alice,bob))
    rogue_workspace=PeerWorkWire(
        identity=b,mesh_key="SENTRA-MESH-TEST-"+"u"*36,
        workspace_id="qa-other",trust={a.node_id:a.public_key},
        ledger=tmp_path/"other.db",
    )
    with pytest.raises(PeerWireDenied):
        rogue_workspace.accept(message(alice,bob))


def test_bit_tamper_and_wrong_recipient_denied(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    original=message(alice,bob)
    frame=json.loads(original)
    frame["ciphertext"]=frame["ciphertext"][:-2]+"aa"
    with pytest.raises(PeerWireDenied):
        bob.accept(json.dumps(frame).encode())
    with pytest.raises(PeerWireDenied):
        bob.accept(alice.seal(
            kind="TASK_OFFER",target=alice.node,
            subject_id="wi",reference_sha256="a"*64,
        ))


def test_expired_offer_never_enters_inbox(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    frame=message(alice,bob)
    bob.clock=lambda:time.time()+3600
    with pytest.raises(PeerWireDenied):
        bob.accept(frame)
    assert bob.inbox()==[]


def test_no_public_transport_or_service_auto_enable(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    frame=message(alice,bob)
    for address in (("8.8.8.8",443),("10.0.0.2",37037),("localhost",443)):
        with pytest.raises(PeerWireDenied,match="mTLS"):
            deliver_loopback(alice,address,frame)


def test_received_offer_is_not_task_success_even_if_ack_is_received(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    server=PeerLoopbackServer(bob).start()
    try:
        result=deliver_loopback(alice,server.address,message(alice,bob))
        assert result["state"]!="SUCCEEDED"
        assert bob.inbox()[0]["state"]!="SUCCEEDED"
        assert alice.inbox()[0]["state"]=="RECEIPT_ONLY"
    finally:server.close()


def test_message_contains_no_prompts_tokens_or_plaintext_refs(tmp_path):
    _,_,alice,bob=pair(tmp_path)
    frame=message(alice,bob)
    assert b"work-item-1" not in frame
    assert b"SENTRA-MESH-TEST" not in frame
    assert len(frame)<8192
    assert set(json.loads(frame))=={"version","nonce","ciphertext"}


def test_sqlite_ledger_retains_only_reference_ids_and_hashes(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    bob.accept(message(alice,bob))
    with sqlite3.connect(tmp_path/"bob.db") as conn:
        rows=conn.execute("SELECT kind,state,body_sha256,subject_id FROM peer_inbox").fetchall()
        assert rows[0][0]=="TASK_OFFER"
        assert rows[0][1]=="PENDING_LOCAL_ADMISSION"
        assert len(rows[0][2])==64
        assert rows[0][3]=="work-item-1"


def test_explicit_pins_and_mesh_key_required(tmp_path):
    a,b,alice,bob=pair(tmp_path)
    with pytest.raises(ValueError):
        PeerWorkWire(identity=a,mesh_key="short",workspace_id="qa-workspace",
                     trust={b.node_id:b.public_key},ledger=tmp_path/"bad.db")
    with pytest.raises(ValueError):
        PeerWorkWire(identity=a,mesh_key="SENTRA-MESH-TEST-"+"u"*36,
                     workspace_id="qa-workspace",trust={},ledger=tmp_path/"bad.db")



def test_real_canvas_core_authorizes_outgoing_peer_offer_only_with_grant(tmp_path):
    from sentra_canvas.service import Canvas
    from sentra_canvas.peer_work_wire import prepare_authorized_offer
    from sentra_mcp.services.authorization import AuthorizationService
    app=Canvas(tmp_path/"canvas",state_dir=tmp_path/"app-state")
    try:
        ws=app.create_workspace("TransportQA")["id"]
        agent=app.create_agent(ws,"OwnerAgent","sentra/test",start=False)
        run=app._runtime().run(ws)
        app._runtime().control.ensure_agent(
            run["run_id"], app._runtime().owner, agent_id=agent["id"], role=agent["role"],
        )
        gov=app._runtime().governance
        gov.create_work_item(
            run["run_id"],app._runtime().owner,
            work_item_id="WI-TRANSPORT",
            objective="Offer a bounded task reference",
            assignee_agent_id=agent["id"],
            required_capabilities=["peer.task.offer"],
            metadata={"workspace_id":ws},
        )
        gov.transition_work_item("WI-TRANSPORT",app._runtime().owner,"RUNNING")
        a,b=identity(),identity()
        mesh="SENTRA-MESH-TEST-"+"u"*36
        alice=PeerWorkWire(identity=a,mesh_key=mesh,workspace_id=ws,
                           trust={b.node_id:b.public_key},ledger=tmp_path/"sending.db")
        bob=PeerWorkWire(identity=b,mesh_key=mesh,workspace_id=ws,
                         trust={a.node_id:a.public_key},ledger=tmp_path/"receiving.db")
        def prepare(key):
            return prepare_authorized_offer(
                canvas=app,wire=alice,workspace_id=ws,work_item_id="WI-TRANSPORT",
                destination=b.node_id,request_key=key,
            )
        with pytest.raises(PeerWireDenied,match="grant denied"):
            prepare("outbound-1")
        auth=AuthorizationService(app.state_dir.parent)
        grant=auth.grant(
            app._runtime().owner,principal_type="agent",principal_id=agent["id"],
            capability="peer.task.offer",scope_type="work_item",scope_id="WI-TRANSPORT",
        )
        msgid,packet=prepare("outbound-1")
        assert len(msgid)==32 and packet
        with alice._db() as db:
            assert db.execute("SELECT receipt_state FROM peer_outbox").fetchone()[0]=="PREPARED_NOT_SENT"
        listener=PeerLoopbackServer(bob).start()
        try:
            receipt=deliver_loopback(alice,listener.address,packet)
            assert receipt["message_id"]==msgid
            assert bob.inbox()[0]["state"]=="PENDING_LOCAL_ADMISSION"
            with alice._db() as db:
                state=db.execute(
                    "SELECT receipt_state FROM peer_outbox WHERE message_id=?",
                    (msgid,),
                ).fetchone()[0]
            assert state=="RECEIVED_PENDING_REMOTE_ADMISSION"
        finally:listener.close()
        with pytest.raises(PeerWireDenied,match="reserved"):
            prepare("outbound-1")
        auth.revoke(grant["grant_id"],app._runtime().owner)
        with pytest.raises(PeerWireDenied,match="grant denied"):
            prepare("outbound-2")
    finally:
        app.shutdown()


def test_peer_offer_wrong_canvas_workspace_rejected_before_core_access(tmp_path):
    from sentra_canvas.service import Canvas
    from sentra_canvas.peer_work_wire import prepare_authorized_offer
    app=Canvas(tmp_path/"canvas",state_dir=tmp_path/"app-state")
    try:
        ws=app.create_workspace("TransportQA")["id"]
        other=app.create_workspace("Other")["id"]
        a,b,alice,bob=pair(tmp_path)
        with pytest.raises(PeerWireDenied,match="scope"):
            prepare_authorized_offer(
                canvas=app,wire=alice,workspace_id=ws,work_item_id="work",
                destination=b.node_id,request_key="offer",
            )
    finally:
        app.shutdown()
