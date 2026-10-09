"""Bounded signed presence on explicitly configured VPN/LAN addresses.

Presence proves membership in the selected mesh and possession of a node key.
It never grants filesystem, model or execution authority to another machine.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time

from sentra_core.conversations import _encode,_decode

PEER_PORT=37037
MULTICAST_GROUP="239.255.55.37"


def canonical(value):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
    if len(raw)>4096:raise ValueError("peer presence exceeds bound")
    return raw


class PeerNodeIdentity:
    def __init__(self,store,workspace):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,PublicFormat,NoEncryption
        store.workspace(workspace)
        with store.tx():
            store.db.execute("CREATE TABLE IF NOT EXISTS canvas_peer_identity("
                "principal TEXT NOT NULL,workspace TEXT NOT NULL,private_key TEXT NOT NULL,PRIMARY KEY(principal,workspace))")
            row=store.db.execute("SELECT private_key FROM canvas_peer_identity WHERE principal=? AND workspace=?",
                (store.principal,workspace)).fetchone()
            if row:
                private=base64.b64decode(_decode(row[0])["private_key"],validate=True)
                key=Ed25519PrivateKey.from_private_bytes(private)
            else:
                key=Ed25519PrivateKey.generate()
                private=key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption())
                store.db.execute("INSERT INTO canvas_peer_identity VALUES(?,?,?)",
                    (store.principal,workspace,_encode({"private_key":base64.b64encode(private).decode()})))
        self.key=key
        self.public_key=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
        self.node_id="peer-"+hashlib.sha256(base64.b64decode(self.public_key)).hexdigest()


class SignedPeerDirectory:
    def __init__(self,*,identity,mesh_key,label,address,port=PEER_PORT,target_addresses=(),
                 interval_seconds=5,ttl_seconds=30,clock=time.time):
        if not isinstance(mesh_key,str) or not 32<=len(mesh_key.encode())<=256:
            raise ValueError("configured mesh pairing key required")
        if not isinstance(label,str) or not 1<=len(label)<=80 or type(port) is not int or not 1<=port<=65535:
            raise ValueError("bounded peer label/common port required")
        if not 1<=interval_seconds<=60 or not interval_seconds*2<=ttl_seconds<=120:
            raise ValueError("bounded peer announcement interval/ttl required")
        source=ipaddress.ip_address(address)
        if source.version!=4 or source.is_unspecified or source.is_multicast:
            raise ValueError("explicit IPv4 VPN/LAN interface address required")
        if not isinstance(target_addresses,(tuple,list)) or len(target_addresses)>128:
            raise ValueError("bounded configured peer addresses required")
        targets=[]
        for value in target_addresses:
            target=ipaddress.ip_address(value)
            if target.version!=4 or target.is_unspecified or target.is_multicast:raise ValueError("invalid peer address")
            targets.append(str(target))
        self.identity,self.mesh_key,self.label=identity,mesh_key.encode(),label
        self.mesh_id=hashlib.sha256(self.mesh_key).hexdigest()[:24]
        self.address,self.port=str(source),port
        self.targets=tuple(dict.fromkeys(targets));self.interval,self.ttl,self.clock=interval_seconds,ttl_seconds,clock
        self.lock=threading.RLock();self.peers={};self.nonces={};self.stop=threading.Event()
        self.transport_metadata=None;self.socket=None;self.thread=None;self.rejected=0;self.send_errors=0

    def announcement(self):
        now=int(self.clock())
        body={"schema":1,"node_id":self.identity.node_id,"public_key":self.identity.public_key,
            "mesh_id":self.mesh_id,"label":self.label,"address":self.address,"port":self.port,
            "issued_at":now,"expires_at":now+int(self.ttl),"nonce":secrets.token_hex(16),
            "capabilities":["presence"],"certificate_sha256":None}
        if callable(self.transport_metadata):
            trusted=self.transport_metadata()
            body["capabilities"]=list(trusted["capabilities"])
            body["certificate_sha256"]=trusted.get("certificate_sha256")
        raw=canonical(body)
        return canonical({"presence":body,"signature":base64.b64encode(self.identity.key.sign(raw)).decode(),
            "mesh_mac":hmac.new(self.mesh_key,raw,hashlib.sha256).hexdigest()})

    def accept(self,packet,source_address):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        try:
            if not isinstance(packet,bytes) or len(packet)>4096:raise ValueError("presence packet bound")
            if source_address not in self.targets:raise ValueError("peer address outside configured whitelist")
            value=json.loads(packet)
            if not isinstance(value,dict) or set(value)!={"presence","signature","mesh_mac"}:raise ValueError("presence envelope")
            body=value["presence"]
            keys={"schema","node_id","public_key","mesh_id","label","address","port","issued_at","expires_at","nonce","capabilities","certificate_sha256"}
            if not isinstance(body,dict) or set(body)!=keys:raise ValueError("presence schema")
            raw=canonical(body)
            if not isinstance(value["mesh_mac"],str) or not hmac.compare_digest(value["mesh_mac"],hmac.new(self.mesh_key,raw,hashlib.sha256).hexdigest()):
                raise ValueError("mesh authentication")
            public=base64.b64decode(body["public_key"],validate=True)
            Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(value["signature"],validate=True),raw)
            if body["node_id"]!="peer-"+hashlib.sha256(public).hexdigest() or body["mesh_id"]!=self.mesh_id or type(body["schema"]) is not int or body["schema"]!=1:
                raise ValueError("peer identity binding")
            if body["node_id"]==self.identity.node_id:return None
            now=self.clock()
            if (type(body["issued_at"]) is not int or type(body["expires_at"]) is not int or
                    not 0<body["expires_at"]-body["issued_at"]<=120 or abs(now-body["issued_at"])>120 or body["expires_at"]<=now):
                raise ValueError("stale peer presence")
            if body["address"]!=str(ipaddress.ip_address(source_address)) or type(body["port"]) is not int or body["port"]!=self.port:
                raise ValueError("peer address/common port binding")
            if not isinstance(body["nonce"],str) or len(body["nonce"])!=32 or not isinstance(body["label"],str) or not 1<=len(body["label"])<=80:
                raise ValueError("bounded peer fields")
            if not isinstance(body["capabilities"],list) or len(body["capabilities"])>16 or any(not isinstance(v,str) or len(v)>80 for v in body["capabilities"]):
                raise ValueError("peer capability advertisements")
            if body["certificate_sha256"] is not None and (not isinstance(body["certificate_sha256"],str) or
                    len(body["certificate_sha256"])!=64 or any(c not in "0123456789abcdef" for c in body["certificate_sha256"])):
                raise ValueError("peer certificate pin")
            with self.lock:
                self.nonces={k:expires for k,expires in self.nonces.items() if expires>now}
                key=(body["node_id"],body["nonce"])
                if key in self.nonces:raise ValueError("replayed presence")
                if len(self.nonces)>=8192:raise ValueError("presence nonce capacity")
                self.peers={k:v for k,v in self.peers.items() if v["expires_at"]>now}
                if body["node_id"] not in self.peers and len(self.peers)>=128:raise ValueError("peer directory capacity")
                self.nonces[key]=body["expires_at"]
                self.peers[body["node_id"]]={**body,"last_seen":now,"state":"discovered",
                    "authenticated_mesh_member":True,"execution_authorized":False}
                return dict(self.peers[body["node_id"]])
        except (ValueError,TypeError,KeyError,InvalidSignature,OverflowError,RecursionError):
            with self.lock:self.rejected+=1
            return None

    def status(self):
        with self.lock:
            now=self.clock()
            return {"running":self.thread is not None and self.thread.is_alive(),"node_id":self.identity.node_id,
                "address":self.address,"port":self.port,"mesh_id":self.mesh_id,
                "peers":[dict(v) for v in self.peers.values() if v["expires_at"]>now],
                "rejected":self.rejected,"send_errors":self.send_errors,"presence_grants_execution":False}

    def start(self):
        if self.thread is not None:raise RuntimeError("peer directory already started")
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            sock.bind((self.address,self.port));sock.settimeout(.25)
            sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,1)
            sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton(self.address))
            try:sock.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,socket.inet_aton(MULTICAST_GROUP)+socket.inet_aton(self.address))
            except OSError:pass  # Explicit unicast peers remain available on VPNs without multicast.
        except BaseException:sock.close();raise
        self.socket=sock;self.thread=threading.Thread(target=self._serve,name="sentra-peer-presence",daemon=True);self.thread.start()

    def _serve(self):
        next_send=0
        while not self.stop.is_set():
            if time.monotonic()>=next_send:
                packet=self.announcement()
                for address in (MULTICAST_GROUP,*self.targets):
                    try:self.socket.sendto(packet,(address,self.port))
                    except OSError:
                        with self.lock:self.send_errors+=1
                next_send=time.monotonic()+self.interval
            try:packet,source=self.socket.recvfrom(4097)
            except socket.timeout:continue
            except OSError:break
            self.accept(packet,source[0])

    def close(self):
        self.stop.set()
        if self.socket:self.socket.close()
        if self.thread:self.thread.join(timeout=3)
