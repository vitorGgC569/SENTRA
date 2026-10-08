"""Commit operational events with producer state, then publish idempotently."""
import json
import sqlite3
from pathlib import Path

from .telemetry import EventJournal


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS telemetry_outbox(event_id TEXT PRIMARY KEY,record_json TEXT NOT NULL)")


def queue(db, journal, component, action, outcome, details, *, correlation_id=None):
    record=EventJournal.record(component,action,outcome,details,correlation_id=correlation_id)
    db.execute("INSERT INTO telemetry_outbox VALUES(?,?)",
               (record["event_id"],json.dumps(record,ensure_ascii=False,separators=(",",":"))))


def flush(path, journal, *, limit=128):
    db=sqlite3.connect(Path(path),timeout=5)
    try:
        rows=db.execute("SELECT event_id,record_json FROM telemetry_outbox ORDER BY rowid LIMIT ?",(limit,)).fetchall()
        published=[]
        for event_id,payload in rows:
            journal.append_record(json.loads(payload))
            published.append((event_id,))
        if published:
            with db:db.executemany("DELETE FROM telemetry_outbox WHERE event_id=?",published)
        return len(published)
    finally:db.close()
