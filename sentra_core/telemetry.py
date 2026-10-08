"""Bounded, correlated, durable operational telemetry for SENTRA components."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_SECRET_KEY = re.compile(r"(?i)authorization|password|secret|cookie|api_?key|runtime_key|access_token|refresh_token|session_token|private_key|protected_value|protected_token|(?:^|_)tokens?(?:_|$)")
_CONTENT_KEYS = {"prompt", "response", "messages", "content", "html", "dom"}
_SECRETS = (
    re.compile(r"(?i)(bearer\s+)[^\s,;\"']+"),
    re.compile(r"(?i)\b(api[-_ ]?key|token|password|secret|cookie|client_secret)(\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\b(?:sk[-_]|ghp_|github_pat_)[A-Za-z0-9_-]{8,}\b", re.I),
    re.compile(r"(://[^\s:/]+:)[^\s/@]+(@)"),
)


def safe_text(value, limit=2000):
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = _SECRETS[0].sub(r"\1[REDACTED]", text)
    text = _SECRETS[1].sub(r"\1\2[REDACTED]", text)
    text = _SECRETS[2].sub("[REDACTED]", text)
    text = _SECRETS[3].sub(r"\1[REDACTED]\2", text)
    return text[:limit]


def redact(value, key=None, *, depth=0, budget=None):
    budget = [2048] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0 or depth > 6:
        return "[TRUNCATED]"
    normalized = re.sub(r"([a-z])([A-Z])",r"\1_\2",str(key or "")).casefold().replace("-", "_").replace(" ", "_")
    metric=normalized in {"input_tokens","output_tokens","cached_input_tokens","reasoning_tokens","total_tokens","token_count","token_budget","tokens_used"} and type(value) in {int,float}
    if _SECRET_KEY.search(normalized) and not metric:
        return "[REDACTED]"
    if normalized in _CONTENT_KEYS:
        return "[CONTENT OMITTED]"
    if isinstance(value, dict):
        return {safe_text(k,120):redact(v,str(k),depth=depth+1,budget=budget) for k,v in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        return [redact(v,depth=depth+1,budget=budget) for v in value[:100]]
    if isinstance(value, str):
        return safe_text(value)
    if value is None or isinstance(value, (bool,int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return safe_text(repr(value))


def nonnegative_int(value):
    try:
        if isinstance(value,bool):return 0
        return max(0,int(value or 0))
    except (ValueError,TypeError,OverflowError):
        return 0


class EventJournal:
    MAX_DETAILS_BYTES = 65536

    def __init__(self, state_root, *, retain=100000):
        self.path = Path(state_root).resolve()/"telemetry"/"events.sqlite3"
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if type(retain) is not int or retain<128:
            raise ValueError("telemetry retention must be at least 128 events")
        self.retain=retain
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0]>1:
                raise RuntimeError("telemetry database requires a newer SENTRA")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,component TEXT NOT NULL,action TEXT NOT NULL,
                    outcome TEXT NOT NULL,correlation_id TEXT,details_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS telemetry_correlation ON events(correlation_id,seq);
                CREATE INDEX IF NOT EXISTS telemetry_action ON events(action,seq);
                CREATE INDEX IF NOT EXISTS telemetry_outcome ON events(outcome,seq);
                CREATE TABLE IF NOT EXISTS totals(
                    component TEXT NOT NULL,action TEXT NOT NULL,outcome TEXT NOT NULL,
                    count INTEGER NOT NULL,read_bytes INTEGER NOT NULL,write_bytes INTEGER NOT NULL,
                    process_start INTEGER NOT NULL,process_end INTEGER NOT NULL,denials INTEGER NOT NULL,
                    PRIMARY KEY(component,action,outcome));
                CREATE TABLE IF NOT EXISTS imports(
                    source TEXT PRIMARY KEY,identity TEXT NOT NULL,offset INTEGER NOT NULL,
                    prefix_sha TEXT NOT NULL,generation TEXT NOT NULL,invalid_lines INTEGER NOT NULL,
                    skipping INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS telemetry_state(id INTEGER PRIMARY KEY CHECK(id=1),appends INTEGER NOT NULL);
                INSERT OR IGNORE INTO telemetry_state VALUES(1,0);
                PRAGMA user_version=1;
            """)
            columns={r[1] for r in db.execute("PRAGMA table_info(imports)")}
            if "skipping" not in columns:
                db.execute("ALTER TABLE imports ADD COLUMN skipping INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")
            with db:yield db
        finally:db.close()

    @staticmethod
    def record(component, action, outcome, details=None, *, correlation_id=None, event_id=None, timestamp=None):
        if event_id is not None and (not isinstance(event_id,str) or not 1<=len(event_id)<=256):
            raise ValueError("invalid telemetry event identity")
        if timestamp is not None and not isinstance(timestamp,str):
            raise ValueError("invalid telemetry timestamp")
        clean=redact(dict(details or {}))
        encoded=json.dumps(clean,ensure_ascii=False,separators=(",",":"),sort_keys=True)
        if len(encoded.encode("utf-8"))>EventJournal.MAX_DETAILS_BYTES:
            clean={"truncated":True,"fields":list(clean)[:50]}
        return {"event_id":event_id or uuid.uuid4().hex,
                "timestamp":timestamp or datetime.now(timezone.utc).isoformat(),
                "component":safe_text(component,64),"action":safe_text(action,128),
                "outcome":safe_text(outcome,64),
                "correlation_id":safe_text(correlation_id,256) if correlation_id else None,
                "details":clean}

    def _append(self,db,record):
        details=record["details"]
        inserted=db.execute("INSERT OR IGNORE INTO events(event_id,timestamp,component,action,outcome,correlation_id,details_json) VALUES(?,?,?,?,?,?,?)",
            (record["event_id"],record["timestamp"],record["component"],record["action"],record["outcome"],record["correlation_id"],
             json.dumps(details,ensure_ascii=False,separators=(",",":"),sort_keys=True)))
        if not inserted.rowcount:return False
        action,outcome=record["action"],record["outcome"]
        read=nonnegative_int(details.get("bytes")) if "read" in action else 0
        write=nonnegative_int(details.get("bytes",details.get("stdin_bytes"))) if "write" in action or "edit" in action else 0
        denial=int(outcome.casefold() in {"forbidden","denied","blocked","unauthorized"} or
                   any(v in action.casefold() for v in ("denied","forbidden","blocked")))
        db.execute("""INSERT INTO totals VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(component,action,outcome) DO UPDATE SET
            count=count+excluded.count,read_bytes=read_bytes+excluded.read_bytes,write_bytes=write_bytes+excluded.write_bytes,
            process_start=process_start+excluded.process_start,process_end=process_end+excluded.process_end,denials=denials+excluded.denials""",
            (record["component"],action,outcome,1,read,write,int(action=="process.start"),
             int(action in {"process.kill","process.terminate","process.cleanup","process.timeout"}),denial))
        db.execute("UPDATE telemetry_state SET appends=appends+1 WHERE id=1")
        count=db.execute("SELECT appends FROM telemetry_state WHERE id=1").fetchone()[0]
        if count%128==0:
            db.execute("DELETE FROM events WHERE seq<COALESCE((SELECT seq FROM events ORDER BY seq DESC LIMIT 1 OFFSET ?),0)",
                       (self.retain-1,))
        return True

    def append(self, component, action, outcome, details=None, *, correlation_id=None, event_id=None):
        record=self.record(component,action,outcome,details,correlation_id=correlation_id,event_id=event_id)
        return self.append_record(record)

    def append_record(self,record):
        record=self.record(record.get("component","unknown"),record.get("action","unknown"),
            record.get("outcome","unknown"),record.get("details",{}),
            correlation_id=record.get("correlation_id"),event_id=record.get("event_id"),timestamp=record.get("timestamp"))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._append(db,record)
        return record

    def import_jsonl(self,path,*,budget_bytes=2_000_000,budget_seconds=1):
        path=Path(path).resolve()
        if not path.is_file():return {"complete":True,"pending_bytes":0,"imported":0}
        with path.open("rb") as stream:
            stat=path.stat();identity=f"{stat.st_dev}:{stat.st_ino}"
            prefix=hashlib.sha256(stream.read(min(256,stat.st_size))).hexdigest()
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old=db.execute("SELECT * FROM imports WHERE source=?",(str(path),)).fetchone()
                reset=(old is None or old["identity"]!=identity or stat.st_size<old["offset"]
                       or (old["offset"]>=256 and old["prefix_sha"]!=prefix))
                offset=0 if reset else old["offset"]
                generation=uuid.uuid4().hex if reset else old["generation"]
                invalid=0 if reset else old["invalid_lines"]
                skipping=False if reset else bool(old["skipping"])
                stream.seek(offset);start=offset;imported=0;deadline=time.monotonic()+budget_seconds
                while offset-start<budget_bytes and time.monotonic()<deadline:
                    position=stream.tell();line=stream.readline(self.MAX_DETAILS_BYTES+1)
                    if not line:break
                    if skipping:
                        offset=stream.tell()
                        if line.endswith(b"\n"):
                            skipping=False
                        continue
                    if not line.endswith(b"\n"):
                        # A partial final append is retried without advancing its cursor.
                        if len(line)<=self.MAX_DETAILS_BYTES:
                            stream.seek(position);break
                        invalid+=1;offset=stream.tell();skipping=True;continue
                    offset=stream.tell()
                    try:
                        item=json.loads(line)
                        if not isinstance(item,dict):raise ValueError("not a record")
                        details=item.get("details") if isinstance(item.get("details"),dict) else {}
                        event_id=item.get("event_id") or uuid.uuid5(uuid.NAMESPACE_URL,f"{path}:{generation}:{position}").hex
                        record=self.record(item.get("component") or "mcp",item.get("action","unknown"),
                            item.get("outcome","unknown"),details,event_id=event_id,
                            timestamp=item.get("timestamp"),correlation_id=item.get("correlation_id"))
                        imported+=int(self._append(db,record))
                    except (ValueError,TypeError):invalid+=1
                db.execute("INSERT OR REPLACE INTO imports VALUES(?,?,?,?,?,?,?)",
                    (str(path),identity,offset,prefix,generation,invalid,int(skipping)))
        pending=max(0,path.stat().st_size-offset)
        return {"complete":pending==0 and not skipping,"pending_bytes":pending,"imported":imported,"invalid_lines":invalid}

    @staticmethod
    def _row(row):
        result=dict(row);result["details"]=json.loads(result.pop("details_json"));return result

    def query(self,*,action="",outcome="",contains="",component="",correlation_id="",limit=100,offset=0):
        if type(limit) is not int or not 1<=limit<=5000 or type(offset) is not int or offset<0:
            raise ValueError("invalid telemetry page")
        where=[];params=[]
        for name,value in (("component",component),("outcome",outcome),("correlation_id",correlation_id)):
            if value:where.append(name+"=?");params.append(value)
        def literal(value):return "%"+value.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
        if action:where.append("action LIKE ? ESCAPE '\\'");params.append(literal(action))
        if contains:
            where.append("(details_json LIKE ? ESCAPE '\\' OR action LIKE ? ESCAPE '\\' OR outcome LIKE ? ESCAPE '\\')")
            params.extend([literal(contains)]*3)
        clause=" WHERE "+" AND ".join(where) if where else ""
        with self.connect() as db:
            total=db.execute("SELECT COUNT(*) FROM events"+clause,params).fetchone()[0]
            rows=db.execute("SELECT * FROM events"+clause+" ORDER BY seq DESC LIMIT ? OFFSET ?",(*params,limit,offset)).fetchall()
        items=[self._row(r) for r in rows]
        return {"items":items,"records":items,"page":{"offset":offset,"limit":limit,"returned":len(items),
            "total":total,"next_offset":offset+len(items) if offset+len(items)<total else None}}

    def stats(self):
        with self.connect() as db:
            rows=db.execute("SELECT * FROM totals").fetchall()
            retained=db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        actions={};outcomes={};components={}
        for r in rows:
            for mapping,key in ((actions,r["action"]),(outcomes,r["outcome"]),(components,r["component"])):
                mapping[key]=mapping.get(key,0)+r["count"]
        return {"calls_total":sum(r["count"] for r in rows),"by_action":actions,"by_outcome":outcomes,
            "by_component":components,"bytes_read_observed":sum(r["read_bytes"] for r in rows),
            "bytes_written_observed":sum(r["write_bytes"] for r in rows),
            "processes_started":sum(r["process_start"] for r in rows),"process_end_events":sum(r["process_end"] for r in rows),
            "security_denials":sum(r["denials"] for r in rows),"records_retained":retained,"retention_limit":self.retain}
