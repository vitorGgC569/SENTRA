"""SENTRA peer task/result transport: authenticated, encrypted *local* prototype.

No remote execution occurs upon reception. TASK_OFFER stays pending local
admission; RESULT stays pending independent verification. ACK proves only
durable transport ingestion, never a successful worker/model response.

Wire: AES-256-GCM confidentiality per workspace from an explicitly paired
mesh key, Ed25519 signer pinned separately by node id, bounded JSON frames,
local SQLite inbox/outbox with restart-safe replay prevention.

This is not an authorized VPN transport release: only loopback sockets are
enabled. External Hamachi/Radmin devices require pinned mutual TLS, explicit
IP allowlist, verified local grants, safe admission to the SENTRA ControlPlane,
and 2-machine E2E. Never auto-enable based on presence alone.
"""
from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import secrets
import socket
import socketserver
import sqlite3
import struct
import threading
import time
from typing import Mapping
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

MAX_FRAME = 8192
_VALID_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_KINDS = frozenset({"TASK_OFFER", "TASK_RESULT", "TRANSPORT_ACK"})
_AAD_PREFIX = b"sentra/peer-work/v1:"


class PeerWireDenied(PermissionError):
    pass


def _canonical(value: dict) -> bytes:
    try:
        data=json.dumps(value,ensure_ascii=False,sort_keys=True,
                        allow_nan=False,separators=(",",":")).encode("utf-8")
    except (TypeError,ValueError,OverflowError,RecursionError) as exc:
        raise PeerWireDenied("invalid peer message") from exc
    if len(data)>MAX_FRAME:
        raise PeerWireDenied("oversized peer message")
    return data


def _decode_b64(value: str) -> bytes:
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",value):
        raise PeerWireDenied("invalid message encoding")
    try:return base64.urlsafe_b64decode(value+"="*(-len(value)%4))
    except (ValueError,base64.binascii.Error) as exc:
        raise PeerWireDenied("invalid message encoding") from exc


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class PeerWorkWire:
    """One paired workspace endpoint. Does not own task or execution policy."""

    def __init__(self, *, identity, mesh_key: str, workspace_id: str,
                 trust: Mapping[str,str], ledger: str | Path,
                 clock=time.time):
        if (not isinstance(workspace_id,str)
                or not _VALID_ID.fullmatch(workspace_id)):
            raise ValueError("canonical workspace id required")
        if (not isinstance(mesh_key,str) or
                not 32<=len(mesh_key.encode("utf-8"))<=256):
            raise ValueError("explicit paired mesh key required")
        if (not hasattr(identity,"key") or not hasattr(identity,"node_id")
                or not isinstance(identity.node_id,str)):
            raise ValueError("host-owned Ed25519 peer identity required")
        if not isinstance(trust,Mapping) or not trust:
            raise ValueError("trusted peer pins required")
        trusted={}
        for node,pub in trust.items():
            try:
                public=base64.b64decode(pub,validate=True)
            except (TypeError,ValueError,base64.binascii.Error) as exc:
                raise ValueError('invalid pinned Ed25519 public key') from exc
            if ("peer-"+hashlib.sha256(public).hexdigest()!=node
                    or len(public)!=32 or node==identity.node_id):
                raise ValueError("invalid or self-signed peer trust pin")
            trusted[node]=Ed25519PublicKey.from_public_bytes(public)
        self.node=identity.node_id
        self.identity=identity
        self.workspace=workspace_id
        self.trust=trusted
        self.clock=clock
        self._aad=_AAD_PREFIX+workspace_id.encode("utf-8")
        key=HKDF(algorithm=hashes.SHA256(),length=32,
                 salt=hashlib.sha256(workspace_id.encode()).digest(),
                 info=_AAD_PREFIX).derive(mesh_key.encode("utf-8"))
        self._aead=AESGCM(key)
        self.path=Path(ledger)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self._db()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS peer_inbox("
                       "workspace TEXT NOT NULL,sender TEXT NOT NULL,"
                       "message_id TEXT NOT NULL,kind TEXT NOT NULL,"
                       "body_sha256 TEXT NOT NULL,state TEXT NOT NULL,"
                       "subject_id TEXT NOT NULL,created_at INTEGER NOT NULL,"
                       "PRIMARY KEY(workspace,sender,message_id))")
            db.execute("CREATE TABLE IF NOT EXISTS peer_outbox("
                       "workspace TEXT NOT NULL,message_id TEXT PRIMARY KEY,"
                       "target TEXT NOT NULL,body_sha256 TEXT NOT NULL,"
                       "receipt_state TEXT NOT NULL,created_at INTEGER NOT NULL)")

    def _db(self):
        db=sqlite3.connect(str(self.path),timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def _validate_body(self,body: dict) -> None:
        if (not isinstance(body,dict) or set(body)!={
                "schema","source","target","workspace","kind","message_id",
                "subject_id","issued_at","expires_at","reference_sha256"}
                or type(body["schema"]) is not int or body["schema"]!=1):
            raise PeerWireDenied("unsupported peer envelope")
        for key in ("source","target","workspace","message_id","subject_id"):
            if not isinstance(body[key],str) or not _VALID_ID.fullmatch(body[key]):
                raise PeerWireDenied("invalid peer identity/reference")
        if (body["workspace"]!=self.workspace or body["kind"] not in _KINDS
                or not isinstance(body["reference_sha256"],str)
                or not re.fullmatch(r"[0-9a-f]{64}",body["reference_sha256"])):
            raise PeerWireDenied("peer message scope denied")
        now=int(self.clock())
        if (type(body["issued_at"]) is not int or type(body["expires_at"]) is not int
                or not 0<body["expires_at"]-body["issued_at"]<=90
                or abs(body["issued_at"]-now)>60
                or body["expires_at"]<=now):
            raise PeerWireDenied("peer message expired or future-dated")

    def seal(self, *, kind: str, target: str, subject_id: str,
             reference_sha256: str, message_id: str | None = None) -> bytes:
        """Seal metadata only; no raw prompts, files, tokens or tool arguments."""
        body={"schema":1,"source":self.node,"target":target,
              "workspace":self.workspace,"kind":kind,
              "message_id":message_id or secrets.token_hex(16),
              "subject_id":subject_id,"issued_at":int(self.clock()),
              "expires_at":int(self.clock())+60,
              "reference_sha256":reference_sha256}
        self._validate_body(body)
        if target not in self.trust:
            raise PeerWireDenied("peer not explicitly paired")
        raw=_canonical(body)
        inner=_canonical({"body":body,"signature":_b64(self.identity.key.sign(raw))})
        nonce=secrets.token_bytes(12)
        ciphertext=self._aead.encrypt(nonce,inner,self._aad)
        packet=_canonical({"version":1,"nonce":_b64(nonce),
                           "ciphertext":_b64(ciphertext)})
        return packet

    def accept(self, packet: bytes) -> tuple[dict, bool]:
        """Verify and persist before acknowledging. Never dispatch operations."""
        try:
            if not isinstance(packet,bytes) or not 0<len(packet)<=MAX_FRAME:
                raise PeerWireDenied("bounded transport frame required")
            frame=json.loads(packet)
            if (not isinstance(frame,dict)
                    or set(frame)!={"version","nonce","ciphertext"}
                    or type(frame["version"]) is not int or frame["version"]!=1):
                raise PeerWireDenied("unsupported encrypted transport")
            nonce=_decode_b64(frame["nonce"])
            if len(nonce)!=12:raise PeerWireDenied("invalid AEAD nonce")
            inner=json.loads(self._aead.decrypt(
                nonce,_decode_b64(frame["ciphertext"]),self._aad))
            if not isinstance(inner,dict) or set(inner)!={"body","signature"}:
                raise PeerWireDenied("untrusted signed envelope")
            body=inner["body"]
            self._validate_body(body)
            if body["target"]!=self.node or body["source"] not in self.trust:
                raise PeerWireDenied("peer not pinned or wrong receiver")
            pub=self.trust[body["source"]]
            pub.verify(_decode_b64(inner["signature"]),_canonical(body))
            digest=hashlib.sha256(_canonical(body)).hexdigest()
            state=("PENDING_LOCAL_ADMISSION" if body["kind"]=="TASK_OFFER"
                   else "PENDING_RESULT_VERIFICATION" if body["kind"]=="TASK_RESULT"
                   else "RECEIPT_ONLY")
            with closing(self._db()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                existing=db.execute(
                    "SELECT body_sha256 FROM peer_inbox WHERE "
                    "workspace=? AND sender=? AND message_id=?",
                    (self.workspace,body["source"],body["message_id"]),
                ).fetchone()
                if existing:
                    if existing[0]!=digest:
                        raise PeerWireDenied("replayed identity with altered intent")
                    return body,True
                db.execute(
                    "INSERT INTO peer_inbox VALUES(?,?,?,?,?,?,?,?)",
                    (self.workspace,body["source"],body["message_id"],
                     body["kind"],digest,state,body["subject_id"],int(self.clock())),
                )
            return body,False
        except (InvalidTag,InvalidSignature,ValueError,KeyError,TypeError,
                UnicodeError,RecursionError) as exc:
            raise PeerWireDenied("peer message verification failed") from exc

    def inbox(self) -> list[dict]:
        with closing(self._db()) as db, db:
            return [
                {"sender":r[0],"message_id":r[1],"kind":r[2],
                 "state":r[3],"subject_id":r[4]}
                for r in db.execute(
                    "SELECT sender,message_id,kind,state,subject_id "
                    "FROM peer_inbox WHERE workspace=? ORDER BY created_at",
                    (self.workspace,),
                ).fetchall()
            ]


class PeerLoopbackServer:
    """Actual TCP frame exchange on 127.0.0.1 only, for integration QA."""

    def __init__(self, receiver: PeerWorkWire):
        self.receiver=receiver
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address=True
            daemon_threads=True
        class Handler(socketserver.BaseRequestHandler):
            def handle(handler):
                conn=handler.request
                conn.settimeout(3)
                try:
                    prefix=_read_exact(conn,4)
                    size=struct.unpack("!I",prefix)[0]
                    if not 0<size<=MAX_FRAME:raise PeerWireDenied("frame too large")
                    body,repeat=receiver.accept(_read_exact(conn,size))
                    # Durable receipt authenticates transport acceptance only.
                    ack=receiver.seal(
                        kind="TRANSPORT_ACK",target=body["source"],
                        subject_id=body["message_id"],
                        reference_sha256=hashlib.sha256(
                            body["message_id"].encode()).hexdigest(),
                    )
                    conn.sendall(struct.pack("!I",len(ack))+ack)
                except (OSError,PeerWireDenied,ConnectionError):
                    # Never echo tokens/payloads in error responses.
                    pass
        self.server=Server(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)

    @property
    def address(self):
        return ("127.0.0.1",self.server.server_address[1])

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def _read_exact(conn,size):
    result=bytearray()
    while len(result)<size:
        chunk=conn.recv(size-len(result))
        if not chunk:raise ConnectionError("truncated packet")
        result.extend(chunk)
    return bytes(result)


def deliver_loopback(sender: PeerWorkWire, address: tuple[str,int],
                     sealed: bytes, *, timeout_s: float=4.0) -> dict:
    """TCP roundtrip + pinned authenticated ACK; no automatic retry."""
    if (not isinstance(address,tuple) or len(address)!=2
            or address[0]!="127.0.0.1" or type(address[1]) is not int
            or not 0<address[1]<=65535):
        raise PeerWireDenied("VPN transport must not be started without mTLS")
    if not isinstance(sealed,bytes) or not 0<len(sealed)<=MAX_FRAME:
        raise PeerWireDenied("invalid outbound frame")
    if not 0<timeout_s<=10:raise ValueError("bounded timeout required")
    try:
        with socket.create_connection(address,timeout=timeout_s) as conn:
            conn.settimeout(timeout_s)
            conn.sendall(struct.pack("!I",len(sealed))+sealed)
            response_size=struct.unpack("!I",_read_exact(conn,4))[0]
            if not 0<response_size<=MAX_FRAME:raise PeerWireDenied("response bound")
            receipt,_=sender.accept(_read_exact(conn,response_size))
            if receipt["kind"]!="TRANSPORT_ACK":
                raise PeerWireDenied("transport response not a receipt")
            # Mark only an already reserved outbound identity and its pinned
            # recipient. A transport ACK never means work completion.
            with closing(sender._db()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "UPDATE peer_outbox SET receipt_state='RECEIVED_PENDING_REMOTE_ADMISSION' "
                    "WHERE workspace=? AND message_id=? AND target=?",
                    (sender.workspace,receipt["subject_id"],receipt["source"]),
                )
            return {"state":"RECEIVED_NOT_EXECUTED",
                    "message_id":receipt["subject_id"],
                    "recipient":receipt["source"]}
    except (OSError,ConnectionError) as exc:
        raise PeerWireDenied("transport delivery uncertain; reconcile before resending") from exc



def prepare_authorized_offer(
    *, canvas, wire: PeerWorkWire, workspace_id: str,
    work_item_id: str, destination: str, request_key: str,
) -> tuple[str, bytes]:
    """Host-bound TASK_OFFER with existing real SENTRA grant/WorkItem.

    The remote host STILL must separately authorize any subsequent effect.
    This function does not launch/accept tasks. It locks an outbound intent
    in the peer transport journal before making a packet available.
    The same request_key is never automatically regenerated on uncertainty.
    """
    from sentra_mcp.services.authorization import AuthorizationService
    from sentra_runtime.authority_bridge import BoundWorkItemPolicy
    from sentra_runtime.contracts import OperationRequest, PolicyDecision
    from sentra_runtime.executor import _request_snapshot

    if (not isinstance(wire,PeerWorkWire) or wire.workspace!=workspace_id
            or destination not in wire.trust
            or not isinstance(request_key,str)
            or not _VALID_ID.fullmatch(request_key)
            or not isinstance(work_item_id,str)
            or not _VALID_ID.fullmatch(work_item_id)):
        raise PeerWireDenied("scoped transport offer required")
    canvas.store.workspace(workspace_id)
    runtime=canvas._runtime()
    run=runtime.run(workspace_id)
    work=runtime.governance.work_item_info(work_item_id,runtime.owner)
    if (run["state"]!="RUNNING" or work["run_id"]!=run["run_id"]
            or work["state"]!="RUNNING"
            or work.get("metadata",{}).get("workspace_id")!=workspace_id
            or "peer.task.offer" not in work.get("required_capabilities",[])
            or not work.get("assignee_agent_id")):
        raise PeerWireDenied("real running SENTRA WorkItem and workspace binding required")
    request=OperationRequest(
        operation_id="peer-offer-"+hashlib.sha256(
            (workspace_id+":"+request_key).encode()).hexdigest()[:32],
        principal_id=work["assignee_agent_id"],
        machine_id="peer-transport-"+workspace_id,
        capability_id="peer.task.offer",
        work_item_id=work_item_id,
        idempotency_key=request_key,
        arguments={"workspace_id":workspace_id,"destination":destination},
    )
    policy=BoundWorkItemPolicy(
        owner=runtime.owner,principal_type="agent",
        authorization=AuthorizationService(canvas.state_dir.parent),
        governance=runtime.governance,
    )
    decision=policy(request)
    if not isinstance(decision,PolicyDecision) or decision.allowed is not True:
        raise PeerWireDenied("real SENTRA grant denied")
    digest=_request_snapshot(request)[1]
    msgid=hashlib.sha256(
        (wire.node+"|"+workspace_id+"|"+request_key).encode()).hexdigest()[:32]
    packet=wire.seal(
        kind="TASK_OFFER",target=destination,subject_id=work_item_id,
        reference_sha256=digest,message_id=msgid,
    )
    with closing(wire._db()) as db,db:
        db.execute("BEGIN IMMEDIATE")
        previous=db.execute(
            "SELECT body_sha256 FROM peer_outbox WHERE message_id=?",
            (msgid,),
        ).fetchone()
        if previous is not None:
            raise PeerWireDenied("outbound task identity reserved; reconcile before retry")
        db.execute("INSERT INTO peer_outbox VALUES(?,?,?,?,?,?)",(
            workspace_id,msgid,destination,hashlib.sha256(packet).hexdigest(),
            "PREPARED_NOT_SENT",int(wire.clock()),
        ))
    return msgid,packet
