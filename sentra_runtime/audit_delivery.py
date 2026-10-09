"""Protected bounded export outbox/inbox and proof references, not authority.

No Run/WorkItem/Operation/grants tables, dispatch callbacks or command replay.
An unfinished export is uncertain on restart until its REAL provider observes
it. Retention is explicit and never removes the current trusted provider head.
"""
import base64
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from sentra_core.conversations import _encode,_decode


def encoded(value):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
    if len(raw)>1_000_000: raise ValueError("export envelope exceeds bound")
    return raw
def digest(value): return hashlib.sha256(encoded(value)).hexdigest()
def scope_key(owner,workspace):
    if not all(isinstance(v,str) and 1<=len(v)<=256 for v in (owner,workspace)): raise ValueError("host-owned export scope required")
    return digest({"owner":owner,"workspace":workspace})


class AuditBackpressure(RuntimeError): pass
class AuditBindingConflict(PermissionError): pass


class AuditDeliveryStore:
    def __init__(self,database,*,workspace_root,owner,workspace_id,max_pending=10000,max_stored_bytes=64_000_000,retention_seconds=604800,clock=time.time):
        root,self.path=Path(workspace_root).resolve(),Path(database).resolve()
        if self.path==root or not self.path.is_relative_to(root) or not 1<=max_pending<=100000 or not 1_000_000<=max_stored_bytes<=1_000_000_000 or not 60<=retention_seconds<=31536000:
            raise ValueError("bounded scoped delivery store required")
        self.owner,self.workspace_id,self.scope=owner,workspace_id,scope_key(owner,workspace_id)
        self.max_pending,self.max_stored_bytes,self.retention_seconds,self.clock=max_pending,max_stored_bytes,retention_seconds,clock
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS audit_outbox(scope TEXT,id TEXT,provider TEXT,profile_sha256 TEXT,event_id TEXT,body_sha256 TEXT,protected_body TEXT,state TEXT,attempt INTEGER,created REAL,updated REAL,protected_receipt TEXT,PRIMARY KEY(scope,id),UNIQUE(scope,provider,event_id))")
            db.execute("CREATE TABLE IF NOT EXISTS audit_inbox(scope TEXT,event_id TEXT,body_sha256 TEXT,protected_body TEXT,stream_seq INTEGER,created REAL,PRIMARY KEY(scope,event_id))")
            db.execute("CREATE TABLE IF NOT EXISTS audit_heads(scope TEXT,provider TEXT,profile_sha256 TEXT,revision INTEGER,protected_head TEXT,sha256 TEXT,PRIMARY KEY(scope,provider,profile_sha256))")
            db.execute("CREATE TABLE IF NOT EXISTS audit_proof_blobs(scope TEXT,id TEXT,part INTEGER,sha256 TEXT,protected_part TEXT,PRIMARY KEY(scope,id,part))")
            db.execute("CREATE TABLE IF NOT EXISTS audit_divergence(scope TEXT,id TEXT,provider TEXT,protected_evidence TEXT,created REAL,PRIMARY KEY(scope,id))")
            if "created" not in {r[1] for r in db.execute("PRAGMA table_info(audit_proof_blobs)")}:
                db.execute("ALTER TABLE audit_proof_blobs ADD COLUMN created REAL NOT NULL DEFAULT 0")
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def _bound(self,db,extra=0,*,new_pending=False):
        pending=db.execute("SELECT count(*) FROM audit_outbox WHERE scope=? AND state NOT IN ('CONFIRMED','REJECTED','EXPIRED')",(self.scope,)).fetchone()[0]
        total=0
        for table,columns in (("audit_outbox","length(protected_body)+coalesce(length(protected_receipt),0)"),("audit_inbox","length(protected_body)"),
            ("audit_proof_blobs","length(protected_part)"),("audit_divergence","length(protected_evidence)")):
            total+=db.execute("SELECT coalesce(sum("+columns+"),0) FROM "+table+" WHERE scope=?",(self.scope,)).fetchone()[0]
        if new_pending and pending>=self.max_pending or total+extra>self.max_stored_bytes: raise AuditBackpressure("export storage full; explicit retention/reconciliation required")
    def enqueue(self,*,provider,profile_sha256,event_id,body):
        if provider not in {"nats","tessera","immudb"} or not isinstance(event_id,str) or not 1<=len(event_id)<=512 or len(profile_sha256)!=64:
            raise ValueError("invalid export binding")
        sha=digest(body); key=digest({"provider":provider,"event":event_id,"scope":self.scope}); protected=_encode(body)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior=db.execute("SELECT body_sha256,profile_sha256 FROM audit_outbox WHERE scope=? AND id=?",(self.scope,key)).fetchone()
            if prior:
                if (prior[0],prior[1])!=(sha,profile_sha256): raise AuditBindingConflict("immutable export identity/content/profile changed")
                return key
            self._bound(db,len(protected),new_pending=True); now=self.clock()
            db.execute("INSERT INTO audit_outbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(self.scope,key,provider,profile_sha256,event_id,sha,protected,"QUEUED",0,now,now,None))
        return key
    def row(self,key):
        with self.db() as db: row=db.execute("SELECT * FROM audit_outbox WHERE scope=? AND id=?",(self.scope,key)).fetchone()
        if row is None: raise FileNotFoundError("export not in owner scope")
        value=dict(row); value["body"]=_decode(value.pop("protected_body")); receipt=value.pop("protected_receipt")
        if value["state"]=="EXPIRED": value["body"]=None
        elif digest(value["body"])!=value["body_sha256"]: raise AuditBindingConflict("export payload changed")
        value["receipt"]=_decode(receipt) if receipt else None
        return value
    def claim(self,key,*,provider,profile_sha256):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM audit_outbox WHERE scope=? AND id=?",(self.scope,key)).fetchone()
            if row is None or (row["provider"],row["profile_sha256"])!=(provider,profile_sha256): raise AuditBindingConflict("provider/profile mismatch")
            if row["state"]!="QUEUED": raise AuditBindingConflict("export already attempted; observe existing identity, never resend")
            db.execute("UPDATE audit_outbox SET state='IN_FLIGHT',attempt=attempt+1,updated=? WHERE scope=? AND id=?",(self.clock(),self.scope,key))
        return self.row(key)
    def pending(self,*,provider,limit=100):
        if type(limit) is not int or not 1<=limit<=1000: raise ValueError("bounded outbox query required")
        with self.db() as db: keys=[r[0] for r in db.execute("SELECT id FROM audit_outbox WHERE scope=? AND provider=? AND state NOT IN ('CONFIRMED','REJECTED','EXPIRED') ORDER BY created LIMIT ?",(self.scope,provider,limit))]
        return [self.row(k) for k in keys]
    def update(self,key,*,state,receipt=None,head=None,expected_head_revision=None):
        if state not in {"CONFIRMED","PENDING_INCLUSION","UNCERTAIN","REJECTED"}: raise ValueError("invalid delivery status")
        projected=self.row(key); protected=_encode(receipt or {})
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE"); self._bound(db,len(protected))
            if head is not None:
                self._set_head(db,projected["provider"],projected["profile_sha256"],head,expected_head_revision)
            row=db.execute("SELECT state FROM audit_outbox WHERE scope=? AND id=?",(self.scope,key)).fetchone()
            if row[0]=="CONFIRMED" and state!="CONFIRMED": raise AuditBindingConflict("confirmed provider reference cannot regress")
            db.execute("UPDATE audit_outbox SET state=?,protected_receipt=?,updated=? WHERE scope=? AND id=?",(state,protected,self.clock(),self.scope,key))
    def head(self,provider,profile_sha256):
        with self.db() as db: row=db.execute("SELECT * FROM audit_heads WHERE scope=? AND provider=? AND profile_sha256=?",(self.scope,provider,profile_sha256)).fetchone()
        if row is None: return None
        value=_decode(row["protected_head"])
        if digest(value)!=row["sha256"]: raise AuditBindingConflict("trusted head modified")
        return {"revision":row["revision"],"value":value}
    def _set_head(self,db,provider,profile,head,expected):
        row=db.execute("SELECT revision FROM audit_heads WHERE scope=? AND provider=? AND profile_sha256=?",(self.scope,provider,profile)).fetchone()
        if (row[0] if row else None)!=expected: raise AuditBindingConflict("trusted-head CAS conflict; retain evidence and reconcile")
        revision=0 if row is None else row[0]+1
        db.execute("INSERT INTO audit_heads VALUES(?,?,?,?,?,?) ON CONFLICT(scope,provider,profile_sha256) DO UPDATE SET revision=excluded.revision,protected_head=excluded.protected_head,sha256=excluded.sha256",
            (self.scope,provider,profile,revision,_encode(head),digest(head)))
    def initialize_head(self,provider,profile_sha256,head):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE"); self._set_head(db,provider,profile_sha256,head,None)
    def proof_blob(self,data):
        if not isinstance(data,bytes) or len(data)>16_000_000: raise ValueError("bounded actual proof/export bytes required")
        sha=hashlib.sha256(data).hexdigest(); key="proof-"+sha
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE"); self._bound(db,len(data)*2)
            for part,offset in enumerate(range(0,len(data),500000)):
                chunk=data[offset:offset+500000]
                db.execute("INSERT OR IGNORE INTO audit_proof_blobs(scope,id,part,sha256,protected_part,created) VALUES(?,?,?,?,?,?)",(self.scope,key,part,hashlib.sha256(chunk).hexdigest(),_encode({"data":base64.b64encode(chunk).decode()}),self.clock()))
        return {"blob_id":key,"sha256":sha,"bytes":len(data),"protected":True}
    def read_blob(self,key):
        with self.db() as db: rows=db.execute("SELECT * FROM audit_proof_blobs WHERE scope=? AND id=? ORDER BY part",(self.scope,key)).fetchall()
        if not rows: raise FileNotFoundError("proof bytes not retained in this scope")
        result=bytearray()
        for part,row in enumerate(rows):
            chunk=base64.b64decode(_decode(row["protected_part"])["data"],validate=True)
            if row["part"]!=part or hashlib.sha256(chunk).hexdigest()!=row["sha256"]: raise AuditBindingConflict("proof blob corrupt")
            result.extend(chunk)
        if key!="proof-"+hashlib.sha256(result).hexdigest(): raise AuditBindingConflict("proof digest mismatch")
        return bytes(result)
    def inbox(self,*,event_id,body,stream_seq):
        sha=digest(body); protected=_encode(body)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT body_sha256 FROM audit_inbox WHERE scope=? AND event_id=?",(self.scope,event_id)).fetchone()
            if row:
                if row[0]!=sha: raise AuditBindingConflict("redelivery ID has conflicting content")
                return {"event_id":event_id,"duplicate":True,"effects_executed":False}
            self._bound(db,len(protected))
            db.execute("INSERT INTO audit_inbox VALUES(?,?,?,?,?,?)",(self.scope,event_id,sha,protected,stream_seq,self.clock()))
        return {"event_id":event_id,"duplicate":False,"effects_executed":False}
    def notifications(self,*,limit=100):
        if not 1<=limit<=1000: raise ValueError("bounded notification query required")
        with self.db() as db: rows=db.execute("SELECT event_id,protected_body,stream_seq FROM audit_inbox WHERE scope=? ORDER BY created LIMIT ?",(self.scope,limit)).fetchall()
        return [{"event_id":r[0],"notification":_decode(r[1]),"stream_seq":r[2],"requires_central_reconciliation":True,"authorizes_effects":False} for r in rows]
    def divergence(self,provider,evidence):
        protected=_encode(evidence); key=uuid.uuid4().hex
        with self.db() as db:
            self._bound(db,len(protected)); db.execute("INSERT INTO audit_divergence VALUES(?,?,?,?,?)",(self.scope,key,provider,protected,self.clock()))
        return key
    def prune(self,*,confirmed_before):
        if confirmed_before>self.clock()-self.retention_seconds: raise ValueError("cannot shorten configured evidence retention")
        # Host must archive receipts/proofs first if longer evidence is needed.
        # Pending/uncertain and trusted heads/divergence are never removed.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            expired=db.execute("SELECT id,protected_receipt FROM audit_outbox WHERE scope=? AND state='CONFIRMED' AND updated<?",(self.scope,confirmed_before)).fetchall()
            for row in expired:
                receipt=_decode(row["protected_receipt"])
                compact={k:v for k,v in receipt.items() if k in {"tx_id","database","server_uuid","index","tree_size","root_hash","stream","sequence","body_sha256","proof"}}
                compact.update(retention_expired=True,proof_bytes_available_locally=False)
                db.execute("UPDATE audit_outbox SET state='EXPIRED',protected_body=?,protected_receipt=? WHERE scope=? AND id=?",
                    (_encode({"retention_expired":True}),_encode(compact),self.scope,row["id"]))
            # Immutable event-ID tombstones prevent another export after payload
            # retention. Keep native references, but do not claim old proof bytes.
            retained=set()
            def refs(value):
                if isinstance(value,dict):
                    if isinstance(value.get("blob_id"),str): retained.add(value["blob_id"])
                    for item in value.values(): refs(item)
                elif isinstance(value,list):
                    for item in value: refs(item)
            for row in db.execute("SELECT protected_receipt FROM audit_outbox WHERE scope=? AND state<>'EXPIRED' AND protected_receipt IS NOT NULL",(self.scope,)): refs(_decode(row[0]))
            blob_keys=[r[0] for r in db.execute("SELECT id FROM audit_proof_blobs WHERE scope=? GROUP BY id HAVING max(created)<?",(self.scope,confirmed_before)) if r[0] not in retained]
            for key in blob_keys: db.execute("DELETE FROM audit_proof_blobs WHERE scope=? AND id=?",(self.scope,key))
            inbox=db.execute("DELETE FROM audit_inbox WHERE scope=? AND created<?",(self.scope,confirmed_before)).rowcount
        return {"receipts_expired":len(expired),"inbox_expired":inbox,"proof_blobs_expired":len(blob_keys),"trusted_heads_preserved":True,"immutable_event_tombstones_preserved":True}
    def status(self):
        with self.db() as db:
            counts={r[0]:r[1] for r in db.execute("SELECT state,count(*) FROM audit_outbox WHERE scope=? GROUP BY state",(self.scope,))}
            stored=0
            for table,column in (("audit_outbox","length(protected_body)+coalesce(length(protected_receipt),0)"),("audit_inbox","length(protected_body)"),
                ("audit_proof_blobs","length(protected_part)"),("audit_divergence","length(protected_evidence)")):
                stored+=db.execute("SELECT coalesce(sum("+column+"),0) FROM "+table+" WHERE scope=?",(self.scope,)).fetchone()[0]
            inbox_count=db.execute("SELECT count(*) FROM audit_inbox WHERE scope=?",(self.scope,)).fetchone()[0]
        return {"scope_sha256":self.scope,"outbox":counts,"max_pending":self.max_pending,"max_stored_bytes":self.max_stored_bytes,
                "stored_protected_bytes":stored,"inbox_count":inbox_count,"retention_seconds":self.retention_seconds,"status_source":"local projection only","authority":"existing SENTRA core only"}


def enqueue_ledger_head(store,ledger,*,provider,profile_sha256,source_id):
    """Read the existing SQLiteAuditLedger; never mutate its history/aliases."""
    last,selected=_ledger_snapshot(ledger,None); head=last.digest if last else "0"*64
    body={"version":1,"class":"audit_head","scope_sha256":store.scope,"source_id":source_id,
          "source_seq":last.seq if last else 0,"source_head_sha256":head,
          "evidence_kind":"local audit head digest; not yet external proof"}
    return store.enqueue(provider=provider,profile_sha256=profile_sha256,event_id=source_id+":"+str(body["source_seq"])+":"+head,body=body)


def enqueue_audit_entry(store,ledger,*,provider,profile_sha256,source_id,sequence):
    """Commit digest of an ACTUAL source entry and its existing Operation ref."""
    from .audit_chain import canonical
    if type(sequence) is not int or sequence<1: raise ValueError("actual source audit sequence required")
    last,entry=_ledger_snapshot(ledger,sequence)
    if entry is None: raise ValueError("actual source audit sequence absent")
    operation=entry.event.get("operation_id")
    if operation is not None and (not isinstance(operation,str) or not 1<=len(operation)<=256): raise ValueError("invalid existing operation reference")
    body={"version":1,"class":"audit_event","scope_sha256":store.scope,"source_id":source_id,"source_seq":sequence,
        "source_event_sha256":hashlib.sha256(canonical(entry.event)).hexdigest(),"source_entry_digest":entry.digest,
        "source_previous_digest":entry.previous,"operation_id":operation,"creates_operations":False}
    return store.enqueue(provider=provider,profile_sha256=profile_sha256,event_id=source_id+":"+str(sequence)+":"+entry.digest,body=body)


def _ledger_snapshot(ledger,sequence):
    """Streaming verification of the existing ledger, with bounded memory."""
    from .sqlite_audit import SQLiteAuditLedger,AuditIntegrityError
    from .audit_chain import canonical,_hash,GENESIS,AuditEntry
    if not isinstance(ledger,SQLiteAuditLedger): raise TypeError("existing trusted SQLiteAuditLedger source required")
    db=sqlite3.connect(ledger.path.resolve().as_uri()+"?mode=ro",uri=True)
    previous=GENESIS;last=selected=None;expected=1
    try:
        for seq,raw,parent,sha in db.execute("SELECT seq,event_json,previous,digest FROM audit_events ORDER BY seq"):
            if len(raw.encode())>65536: raise AuditIntegrityError("source event exceeds existing bound")
            event=json.loads(raw)
            if seq!=expected or parent!=previous or canonical(event).decode()!=raw or _hash(previous,canonical(event))!=sha:
                raise AuditIntegrityError("existing source audit chain mismatch")
            last=AuditEntry(seq,event,parent,sha)
            if seq==sequence: selected=last
            previous=sha;expected+=1
        return last,selected
    finally: db.close()
