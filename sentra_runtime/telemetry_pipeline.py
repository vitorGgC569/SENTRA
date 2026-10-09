"""Bounded durable diagnostic queue. It never owns execution/audit completeness."""
import hashlib
import json
import threading
import time

from .otlp_sink import LocalOtlpExporter,SafeTelemetryEvent,to_otlp


class TelemetryPipeline:
    @staticmethod
    def _settings_db(store):
        db=store.connect("telemetry_pipeline")
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS diagnostic_settings(owner TEXT PRIMARY KEY,config TEXT NOT NULL,sha256 TEXT NOT NULL)")
        return db

    @classmethod
    def load_settings(cls,store,owner):
        db=cls._settings_db(store)
        try:row=db.execute("SELECT * FROM diagnostic_settings WHERE owner=?",(owner,)).fetchone()
        finally:db.close()
        if row is None:return None
        if hashlib.sha256(row["config"].encode()).hexdigest()!=row["sha256"]:raise ValueError("diagnostic configuration integrity failure")
        return json.loads(row["config"])

    @classmethod
    def save_settings(cls,store,owner,config):
        value=json.dumps(config,sort_keys=True,allow_nan=False,separators=(",",":"))
        db=cls._settings_db(store)
        try:
            with db:
                db.execute("INSERT INTO diagnostic_settings VALUES(?,?,?) ON CONFLICT(owner) DO UPDATE SET config=excluded.config,sha256=excluded.sha256",
                           (owner,value,hashlib.sha256(value.encode()).hexdigest()))
        finally:db.close()

    def __init__(self,store,*,owner,endpoint,max_pending=1000,batch_size=32,batch_bytes=256*1024,
                 flush_seconds=1,retention_seconds=3600,max_attempts=6,clock=time.time,start=True):
        if (type(max_pending) is not int or not 1<=max_pending<=10000 or type(batch_size) is not int or not 1<=batch_size<=128
                or type(batch_bytes) is not int or not 4096<=batch_bytes<=1024*1024
                or not .1<=flush_seconds<=60 or not 1<=retention_seconds<=86400
                or type(max_attempts) is not int or not 1<=max_attempts<=20):raise ValueError("invalid telemetry bounds")
        self.store,self.owner,self.clock=store,owner,clock
        # Keep diagnostic storage contention bounded independently of the
        # execution authority's longer transaction timeouts.
        if getattr(store,"backend",None)=="sqlite":
            from sentra_mcp.services.control_store import SQLiteControlPlaneStore
            self.store=SQLiteControlPlaneStore(store.root.parent,timeout_seconds=.05)
        self.exporter=LocalOtlpExporter(endpoint,timeout_s=2)
        self.max_pending,self.batch_size,self.batch_bytes=max_pending,batch_size,batch_bytes
        self.flush_seconds,self.retention_seconds,self.max_attempts=flush_seconds,retention_seconds,max_attempts
        self.endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest()
        self._stop=threading.Event();self._wake=threading.Event();self._flush_lock=threading.Lock()
        db=self.store.connect("telemetry_pipeline")
        try:
            with db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS diagnostic_queue(
                      owner TEXT NOT NULL,event TEXT NOT NULL,endpoint TEXT NOT NULL,
                      payload TEXT NOT NULL,sha256 TEXT NOT NULL,created REAL NOT NULL,
                      expires REAL NOT NULL,attempts INTEGER NOT NULL,next_attempt REAL NOT NULL,
                      PRIMARY KEY(owner,event));
                    CREATE TABLE IF NOT EXISTS diagnostic_stats(
                      owner TEXT PRIMARY KEY,enqueued INTEGER NOT NULL DEFAULT 0,
                      delivered INTEGER NOT NULL DEFAULT 0,dropped INTEGER NOT NULL DEFAULT 0,
                      retries INTEGER NOT NULL DEFAULT 0,errors INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE IF NOT EXISTS diagnostic_seen(
                      owner TEXT NOT NULL,event TEXT NOT NULL,expires REAL NOT NULL,
                      PRIMARY KEY(owner,event));
                """)
                db.execute("INSERT OR IGNORE INTO diagnostic_stats(owner) VALUES(?)",(owner,))
        finally:db.close()
        self._thread=None
        if start:self.start()

    def start(self):
        if self._stop.is_set():raise RuntimeError("diagnostic pipeline is closed")
        if self._thread is None:
            self._thread=threading.Thread(target=self._serve,daemon=True,name="sentra-diagnostics")
            self._thread.start()

    def _stat(self,db,column,count=1):
        if column not in {"enqueued","delivered","dropped","retries","errors"}:raise ValueError("unknown diagnostic counter")
        db.execute("UPDATE diagnostic_stats SET "+column+"="+column+"+? WHERE owner=?",(count,self.owner))

    def enqueue(self,event):
        if not isinstance(event,SafeTelemetryEvent):raise TypeError("sanitized telemetry event required")
        if self._stop.is_set():return False
        event_id=hashlib.sha256((event.name+"\0"+event.operation_id+"\0"+event.state).encode()).hexdigest()
        document=to_otlp(event)
        span=document["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        # Frozen trace/span identities make a retried diagnostic recognizable.
        span["traceId"]=hashlib.sha256((self.owner+"\0"+event.operation_id).encode()).hexdigest()[:32]
        span["spanId"]=event_id[:16]
        payload=json.dumps(document,separators=(",",":"),allow_nan=False)
        if len(payload.encode())>self.batch_bytes:return False
        db=self.store.connect("telemetry_pipeline")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE");now=self.clock()
                expired=db.execute("DELETE FROM diagnostic_queue WHERE owner=? AND expires<=?",(self.owner,now)).rowcount
                self._stat(db,"dropped",expired)
                db.execute("DELETE FROM diagnostic_seen WHERE owner=? AND expires<=?",(self.owner,now))
                if db.execute("SELECT 1 FROM diagnostic_seen WHERE owner=? AND event=?",(self.owner,event_id)).fetchone():return True
                if db.execute("SELECT 1 FROM diagnostic_queue WHERE owner=? AND event=?",(self.owner,event_id)).fetchone():return True
                count=db.execute("SELECT COUNT(*) FROM diagnostic_queue WHERE owner=?",(self.owner,)).fetchone()[0]
                if count>=self.max_pending:self._stat(db,"dropped");return False
                db.execute("INSERT INTO diagnostic_queue VALUES(?,?,?,?,?,?,?,?,?)",
                    (self.owner,event_id,self.endpoint_hash,payload,hashlib.sha256(payload.encode()).hexdigest(),
                     now,now+self.retention_seconds,0,now))
                db.execute("INSERT INTO diagnostic_seen VALUES(?,?,?)",(self.owner,event_id,now+self.retention_seconds))
                db.execute("DELETE FROM diagnostic_seen WHERE owner=? AND event NOT IN "
                    "(SELECT event FROM diagnostic_seen WHERE owner=? ORDER BY expires DESC LIMIT 10000)",(self.owner,self.owner))
                self._stat(db,"enqueued")
        finally:db.close()
        if count+1>=self.batch_size:self._wake.set()
        return True

    def flush(self):
        if not self._flush_lock.acquire(blocking=False):return 0
        try:
            db=self.store.connect("telemetry_pipeline")
            try:
                now=self.clock()
                with db:
                    expired=db.execute("DELETE FROM diagnostic_queue WHERE owner=? AND expires<=?",(self.owner,now)).rowcount
                    self._stat(db,"dropped",expired)
                rows=list(db.execute("SELECT * FROM diagnostic_queue WHERE owner=? AND endpoint=? AND next_attempt<=? "
                    "ORDER BY created LIMIT ?",(self.owner,self.endpoint_hash,now,self.batch_size)))
            finally:db.close()
            selected=[];documents=[];size=32
            for row in rows:
                payload=row["payload"]
                if size+len(payload.encode())>self.batch_bytes:break
                if hashlib.sha256(payload.encode()).hexdigest()!=row["sha256"]:
                    self._complete([row],success=False,corrupt=True);continue
                # Safe documents are created only by to_otlp; strict redaction
                # also rejects an altered local queue before network export.
                try:
                    doc=json.loads(payload);self._validate(doc)
                except (ValueError,TypeError,KeyError,IndexError):
                    self._complete([row],success=False,corrupt=True);continue
                selected.append(row);documents.extend(doc["resourceSpans"]);size+=len(payload.encode())
            if not selected:return 0
            success=False
            try:
                self.exporter._send(json.dumps({"resourceSpans":documents},separators=(",",":")).encode())
                success=True
            except Exception:pass
            self._complete(selected,success=success)
            return len(selected) if success else 0
        finally:self._flush_lock.release()

    @staticmethod
    def _validate(doc):
        if set(doc)!={"resourceSpans"} or len(doc["resourceSpans"])!=1:raise ValueError("invalid safe telemetry packet")
        resource=doc["resourceSpans"][0]
        if set(resource)!={"resource","scopeSpans"} or resource["resource"]!={"attributes":[{"key":"service.name","value":{"stringValue":"sentra-os"}}]}:
            raise ValueError("unsafe telemetry resource")
        scopes=resource["scopeSpans"]
        if len(scopes)!=1 or set(scopes[0])!={"scope","spans"} or scopes[0]["scope"]!={"name":"sentra.runtime"}:
            raise ValueError("unsafe telemetry scope")
        spans=scopes[0]["spans"]
        if len(spans)!=1:raise ValueError("invalid telemetry span count")
        span=spans[0]
        if (set(span)!={"traceId","spanId","name","startTimeUnixNano","endTimeUnixNano","attributes"}
                or span["name"] not in {"sentra.operation","sentra.policy","sentra.machine","sentra.collab"}):
            raise ValueError("unsafe telemetry span")
        attributes=span["attributes"]
        if len(attributes)!=2 or [a["key"] for a in attributes]!=["sentra.operation_sha256","sentra.operation_state"]:
            raise ValueError("unsafe telemetry attributes")
        import re
        if (not isinstance(span["traceId"],str) or not re.fullmatch("[a-f0-9]{32}",span["traceId"])
                or not isinstance(span["spanId"],str) or not re.fullmatch("[a-f0-9]{16}",span["spanId"])
                or any(not isinstance(span[key],str) or not re.fullmatch("[0-9]{1,20}",span[key])
                       for key in ("startTimeUnixNano","endTimeUnixNano"))):
            raise ValueError("unsafe telemetry identity/timestamp")
        if any(set(a)!={"key","value"} or set(a["value"])!={"stringValue"} for a in attributes):raise ValueError("unsafe telemetry value")
        if not re.fullmatch("[a-f0-9]{64}",attributes[0]["value"]["stringValue"]):raise ValueError("invalid telemetry digest")
        if attributes[1]["value"]["stringValue"] not in {"ACCEPTED","RUNNING","SUCCEEDED","FAILED","CANCELLED","UNCERTAIN"}:
            raise ValueError("invalid telemetry state")

    def _complete(self,rows,*,success,corrupt=False):
        db=self.store.connect("telemetry_pipeline")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                for row in rows:
                    if success or corrupt or row["attempts"]+1>=self.max_attempts:
                        db.execute("DELETE FROM diagnostic_queue WHERE owner=? AND event=?",(self.owner,row["event"]))
                        self._stat(db,"delivered" if success else "dropped")
                    else:
                        db.execute("UPDATE diagnostic_queue SET attempts=attempts+1,next_attempt=? WHERE owner=? AND event=?",
                            (self.clock()+min(60,2**row["attempts"]),self.owner,row["event"]))
                        self._stat(db,"retries")
                if not success:self._stat(db,"errors")
        finally:db.close()

    def status(self):
        db=self.store.connect("telemetry_pipeline")
        try:
            counters=dict(db.execute("SELECT * FROM diagnostic_stats WHERE owner=?",(self.owner,)).fetchone());counters.pop("owner")
            pending=db.execute("SELECT COUNT(*) FROM diagnostic_queue WHERE owner=?",(self.owner,)).fetchone()[0]
            return {**counters,"pending":pending,"max_pending":self.max_pending,"audit_complete":False,"diagnostics_only":True}
        finally:db.close()
    def _serve(self):
        while not self._stop.is_set():
            self._wake.wait(self.flush_seconds);self._wake.clear()
            if self._stop.is_set():break
            try:self.flush()
            except Exception:pass  # Never break execution because a diagnostic sink failed.
    def close(self):
        self._stop.set();self._wake.set()
        if self._thread:self._thread.join(timeout=3)
