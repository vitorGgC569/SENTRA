"""Idempotent import/outbox, retention and concurrent durable event publication."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from sentra_core.telemetry import EventJournal
from sentra_core.conversations import ConversationStore
from sentra_mcp.audit import AuditLogger


def test_secret_and_content_fields_never_enter_telemetry(tmp_path):
    hub=EventJournal(tmp_path)
    key="sk-test-secret-material-12345678"
    hub.append("cli","provider.delivery","submitted",{
        "runtime_key":key,"accessToken":key,"authorizationHeader":key,
        "nested":{"authorization":"Bearer "+key,"prompt":"private user content"},
        "output_tokens":24,"error":"API_KEY="+key},correlation_id="turn-7")
    stored=json.dumps(hub.query(correlation_id="turn-7"))
    assert key not in stored and "private user content" not in stored
    assert "output_tokens" in stored and "24" in stored
    assert key.encode() not in hub.path.read_bytes()


def test_invalid_legacy_metrics_do_not_crash_usage_and_import_does_not_double_count(tmp_path):
    path=tmp_path/"audit.jsonl"
    path.write_text(json.dumps({"action":"filesystem.read","outcome":"ok","details":{"bytes":"bad"}})+"\n"+
        json.dumps({"action":"filesystem.write","outcome":"ok","details":{"bytes":-17}})+"\n"+
        json.dumps({"action":"provider.delivery","outcome":"failed","details":[]})+"\n"+"invalid json\n")
    hub=EventJournal(tmp_path)
    assert hub.import_jsonl(path)["imported"]==3
    assert hub.import_jsonl(path)["imported"]==0
    stats=hub.stats()
    assert stats["calls_total"]==3
    assert stats["bytes_read_observed"]==stats["bytes_written_observed"]==0
    assert stats["security_denials"]==0


def test_partial_append_is_not_lost_or_counted_twice(tmp_path):
    path=tmp_path/"audit.jsonl"
    text=json.dumps({"action":"process.start","outcome":"ok"})
    path.write_text(text[:10])
    hub=EventJournal(tmp_path)
    first=hub.import_jsonl(path)
    assert not first["complete"] and first["imported"]==0
    with path.open("a") as stream:stream.write(text[10:]+"\n")
    assert hub.import_jsonl(path)["imported"]==1
    assert hub.import_jsonl(path)["complete"]
    assert hub.stats()["calls_total"]==1


def test_bounded_import_reports_incomplete_history_then_resumes(tmp_path):
    path=tmp_path/"audit.jsonl"
    path.write_text("".join(json.dumps({"action":"read","outcome":"ok","details":{"bytes":1}})+"\n" for _ in range(50)))
    hub=EventJournal(tmp_path)
    page=hub.import_jsonl(path,budget_bytes=150)
    assert not page["complete"] and page["pending_bytes"]>0
    while not page["complete"]:page=hub.import_jsonl(path,budget_bytes=150)
    assert hub.stats()["calls_total"]==50


def test_oversized_legacy_line_can_be_skipped_across_bounded_pages(tmp_path):
    path=tmp_path/"audit.jsonl"
    path.write_text("x"*400000+"\n"+json.dumps({"action":"process.start","outcome":"ok"})+"\n")
    hub=EventJournal(tmp_path)
    pages=0
    while True:
        page=hub.import_jsonl(path,budget_bytes=70000)
        pages+=1
        if page["complete"]:break
        assert pages<10
    assert page["invalid_lines"]==1 and hub.stats()["calls_total"]==1


def test_retention_preserves_lifetime_totals_despite_duplicate_sequence_gaps(tmp_path):
    hub=EventJournal(tmp_path,retain=128)
    for n in range(512):
        event="fixed-"+str(n)
        hub.append("mcp","read","ok",{"bytes":1},event_id=event)
        hub.append("mcp","read","ok",{"bytes":1},event_id=event)
    stats=hub.stats()
    assert stats["calls_total"]==512 and stats["bytes_read_observed"]==512
    assert stats["records_retained"]==128
    assert len(hub.query(limit=200)["items"])==128


def test_jsonl_export_failure_does_not_hide_a_committed_audit(tmp_path):
    invalid_file=tmp_path/"audit.jsonl"
    invalid_file.mkdir()
    audit=AuditLogger(invalid_file)
    audit.emit("process.start","ok",{"pid":1234})
    assert audit.last_error.startswith("jsonl:")
    assert EventJournal(tmp_path).stats()["calls_total"]==1


@pytest.mark.skipif(os.name!="nt",reason="Windows DPAPI conversation state")
def test_conversation_outbox_recovery_is_idempotent_and_does_not_block_history(tmp_path,monkeypatch):
    store=ConversationStore(tmp_path)
    def unavailable(*args):raise sqlite3.OperationalError("telemetry index unavailable")
    monkeypatch.setattr(store.telemetry,"append_record",unavailable)
    sid=store.open(tmp_path)
    store.append(sid,"user","private durable context")
    assert store.status(sid)["telemetry_pending"]==2
    assert store.status(sid)["telemetry_error"]=="OperationalError"
    assert store.messages(sid)[0]["content"]=="private durable context"
    # Publish one event, but deliberately leave it in the producer outbox as a
    # crash after the central commit would do.
    with store._connect() as db:
        queued=json.loads(db.execute("SELECT record_json FROM telemetry_outbox ORDER BY rowid LIMIT 1").fetchone()[0])
    fresh=EventJournal(tmp_path)
    fresh.append_record(queued)
    recovered=ConversationStore(tmp_path)
    assert recovered.status(sid)["telemetry_pending"]==0
    assert fresh.stats()["calls_total"]==2
    assert "private durable context" not in json.dumps(fresh.query())


def test_multiple_processes_publish_exactly_one_event_per_id(tmp_path):
    root=Path(__file__).resolve().parents[2]
    script="""import sys;from sentra_core.telemetry import EventJournal
hub=EventJournal(sys.argv[1])
for n in range(40):hub.append('worker','event','ok',event_id=sys.argv[2]+'-'+str(n))
"""
    processes=[subprocess.Popen([sys.executable,"-B","-c",script,str(tmp_path),str(i)],cwd=root,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)) for i in range(3)]
    for process in processes:
        _,error=process.communicate(timeout=15)
        assert process.returncode==0,error.decode("utf-8","replace")
    assert EventJournal(tmp_path).stats()["calls_total"]==120
