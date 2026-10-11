"""Real Windows DPAPI/SQLite WAL regression for Web outbox at rest."""
import hashlib
import json
import sqlite3

import pytest

from native_bridge.job_store import JobStore
from native_bridge.protocol import ChatJob, ChatResult


def db_rows(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT id,payload,result,state FROM jobs ORDER BY id").fetchall()


def test_new_job_prompt_images_and_result_never_plaintext_at_rest(tmp_path):
    path=tmp_path/"relay.db"
    secret="SENTRA_HIGHLY_PRIVATE_CONTEXT_456ABC"
    store=JobStore(path)
    job=ChatJob(task_id="private-task",prompt=secret,images=[])
    jid=store.submit(job)
    raw=db_rows(path)
    assert len(raw)==1 and raw[0][1].startswith(("dpapi:","keyring:"))
    assert secret not in raw[0][1]
    leased=store.poll("worker-12345")
    assert leased["prompt"] == secret
    store.progress(jid,"worker-12345",leased["lease_token"],"sending")
    answer="SECRET_MODEL_ANSWER_918"
    result=ChatResult(job_id=jid,task_id="private-task",worker="worker-12345",result=answer)
    store.store_result(result,leased["lease_token"])
    store.store_result(result,leased["lease_token"])  # repeat HTTP ack is idempotent despite randomized DPAPI
    assert store.result(jid)["result"] == answer
    store.close()
    rows=db_rows(path)
    assert rows[0][2].startswith(("dpapi:","keyring:"))
    assert secret not in rows[0][1] and answer not in rows[0][2]
    with open(path,"rb") as stream:
        physical=stream.read()
    assert secret.encode() not in physical
    assert answer.encode() not in physical
    reopened=JobStore(path)
    assert reopened.result(jid)["result"]==answer
    reopened.close()


def test_migration_legacy_pending_and_terminal_atomic_restart(tmp_path):
    path=tmp_path/"legacy.db"
    pending="SENTRA_LEGACY_UNCERTAIN_PROMPT"
    terminal="SENTRA_LEGACY_REPLY_SECRET"
    old=JobStore(path)
    job=ChatJob(task_id="legacy-pending",prompt=pending)
    jid=old.submit(job)
    claim=old.poll("worker-legacy")
    old.progress(jid,"worker-legacy",claim["lease_token"],"sending")
    done=ChatJob(task_id="legacy-done",prompt="legacy finished prompt")
    done_id=old.submit(done)
    lease2=old.poll("worker-other")
    assert lease2["job_id"]==done_id
    old.store_result(ChatResult(job_id=done_id,task_id="legacy-done",
                               worker="worker-other",result=terminal),lease2["lease_token"])
    old.close()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE jobs SET payload=? WHERE id=?",
                   (json.dumps(job.to_dict()),jid))
        db.execute("UPDATE jobs SET payload=?, result=? WHERE id=?",
                   (json.dumps(done.to_dict()),
                    json.dumps(ChatResult(job_id=done_id,task_id="legacy-done",
                                          worker="worker-other",result=terminal).to_dict()),done_id))
    upgraded=JobStore(path)
    rows=db_rows(path)
    assert all(row[1].startswith(("dpapi:","keyring:")) for row in rows)
    assert rows[0][2] is None or rows[0][2].startswith(("dpapi:","keyring:"))
    assert rows[1][2] is None or rows[1][2].startswith(("dpapi:","keyring:"))
    assert upgraded.poll("new-worker") is None
    assert upgraded.result(done_id)["result"]==terminal
    assert upgraded.delivery_status(jid)["state"] in ("pending","unconfirmed")
    assert upgraded.db.execute("SELECT cleanup_pending FROM relay_storage_security").fetchone()[0]==0
    upgraded.close()
    assert pending.encode() not in path.read_bytes()
    assert terminal.encode() not in path.read_bytes()
    reopened=JobStore(path)
    assert reopened.poll("another-worker") is None
    assert reopened.result(done_id)["result"]==terminal
    reopened.close()


def test_migration_protection_failure_rolls_back_every_row(tmp_path,monkeypatch):
    path=tmp_path/"broken.db"
    store=JobStore(path)
    jobs=[ChatJob(task_id="legacy-one",prompt="PRIVATE_ONE"),
          ChatJob(task_id="legacy-two",prompt="PRIVATE_TWO")]
    for job in jobs:
        store.submit(job)
    store.close()
    with sqlite3.connect(path) as db:
        for job in jobs:
            db.execute("UPDATE jobs SET payload=? WHERE id=?",
                       (json.dumps(job.to_dict()),job.job_id))
    calls=[0]
    from native_bridge import job_store
    original=job_store.protect_secret
    def fail_on_second(value):
        calls[0]+=1
        if calls[0]==2:
            raise RuntimeError("OS protection failed")
        return original(value)
    monkeypatch.setattr(job_store,"protect_secret",fail_on_second)
    with pytest.raises(RuntimeError,match="OS protection failed"):
        JobStore(path)
    with sqlite3.connect(path) as db:
        states=db.execute("SELECT payload FROM jobs").fetchall()
        assert len(states)==2 and all(raw[0].startswith("{") for raw in states)
    monkeypatch.setattr(job_store,"protect_secret",original)
    fixed=JobStore(path)
    assert all(raw[1].startswith(("dpapi:","keyring:")) for raw in db_rows(path))
    fixed.close()


def test_swapped_ciphertext_and_plaintext_post_migration_fail_closed(tmp_path):
    path=tmp_path/"tampered.db"
    store=JobStore(path)
    a=ChatJob(task_id="private-a",prompt="SECRET_A_122")
    b=ChatJob(task_id="private-b",prompt="SECRET_B_122")
    store.submit(a);store.submit(b)
    store.close()
    with sqlite3.connect(path) as db:
        encrypted=db.execute("SELECT payload FROM jobs WHERE id=?",(a.job_id,)).fetchone()[0]
        db.execute("UPDATE jobs SET payload=? WHERE id=?",(encrypted,b.job_id))
    with pytest.raises(RuntimeError,match="identity mismatch"):
        JobStore(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE jobs SET payload=? WHERE id=?",
                   ("not-json-unprotected",b.job_id))
    with pytest.raises(RuntimeError,match="unsupported legacy"):
        JobStore(path)


def test_exact_web_receipt_after_os_protected_restart(tmp_path):
    path=tmp_path/"receipt.db"
    store=JobStore(path)
    conversation="abcd1234-1111-2222-3333-444444444444"
    url=f"https://chatgpt.com/c/{conversation}"
    job=ChatJob(task_id="receipt-task",prompt="SENSITIVE_WEB_CONTINUATION",
                kind="CHAT_SEND",new_chat=False,conversation_url=url)
    jid=store.submit(job)
    leased=store.poll("worker-browser")
    store.progress(jid,"worker-browser",leased["lease_token"],"sending")
    store.close()
    restarted=JobStore(path)
    receipt=dict(conversation_id=conversation,message_id="message-id-9999",
                 prompt_sha256=hashlib.sha256(job.prompt.encode()).hexdigest(),
                 images_attached=0)
    assert restarted.delivery_receipt(jid,"worker-browser",leased["lease_token"],
                                     receipt)["state"]=="sent"
    assert restarted.delivery_receipt(jid,"worker-browser",leased["lease_token"],
                                     receipt)["state"]=="sent"
    with pytest.raises(ValueError,match="mismatch"):
        restarted.delivery_receipt(jid,"worker-browser",leased["lease_token"],
                                  {**receipt,"prompt_sha256":"0"*64})
    assert restarted.delivery_status(jid)["automatic_resend"] is False
    restarted.close()


def test_restarted_migration_resumes_interrupted_sqlite_cleanup(tmp_path):
    path=tmp_path/"cleanup-crash.db"
    old=JobStore(path)
    job=ChatJob(task_id="cleanup-task",prompt="SENSITIVE_LEGACY_TO_MIGRATE")
    old.submit(job)
    old.close()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE jobs SET payload=? WHERE id=?",
                   (json.dumps(job.to_dict()),job.job_id))
        db.execute("UPDATE relay_storage_security SET cleanup_pending=1 WHERE key='job_crypto'")
    reopened=JobStore(path)
    assert reopened.poll("TAB-505")["prompt"]==job.prompt
    row=reopened.db.execute("SELECT cleanup_pending FROM relay_storage_security "
                            "WHERE key='job_crypto'").fetchone()
    assert row[0] == 0
    reopened.close()
    assert job.prompt.encode() not in path.read_bytes()


def test_no_plaintext_in_fail_result_for_lost_browser_worker(tmp_path,monkeypatch):
    now=[100.0]
    monkeypatch.setattr(JobStore,"LEASE_WINDOW_S",2)
    monkeypatch.setattr(JobStore,"PROGRESS_WINDOW_S",2)
    path=tmp_path/"failed.db"
    store=JobStore(path,clock=lambda:now[0])
    job=ChatJob(task_id="failed-task",prompt="PRIVATE_SENTRA_FAILED_JOB_CONTEXT",
                timeout_s=60)
    jid=store.submit(job)
    worker=store.poll("TAB-408")
    store.progress(jid,"TAB-408",worker["lease_token"],"sending")
    now[0] += 65
    result=store.result(jid)
    assert result["status"] == "FAILED"
    assert store.delivery_status(jid)["automatic_resend"] is False
    store.close()
    raw=db_rows(path)[0]
    assert raw[1].startswith(("dpapi:","keyring:"))
    assert raw[2].startswith(("dpapi:","keyring:"))
    assert job.prompt not in raw[1]
