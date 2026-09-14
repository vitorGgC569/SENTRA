"""Durable leased jobs. Expired deliveries fail; they are never blindly resent."""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time

from .protocol import ChatJob, ChatResult


class JobStore:
    def __init__(self, path=":memory:", clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT, "
                        "state TEXT, worker TEXT, lease TEXT, lease_until REAL, deadline REAL, "
                        "result TEXT, ack INTEGER DEFAULT 0, updated REAL)")
        self.db.commit()

    def _expire(self):
        now = self.clock()
        rows = self.db.execute("SELECT id,payload FROM jobs WHERE state IN ('QUEUED','LEASED') "
                               "AND (deadline<=? OR (state='LEASED' AND lease_until<=?))", (now, now)).fetchall()
        for jid, payload in rows:
            job = json.loads(payload)
            result = ChatResult(job_id=jid, task_id=job['task_id'], status="FAILED",
                                error="DELIVERY_EXPIRED: execution uncertain; not automatically resent").to_dict()
            self.db.execute("UPDATE jobs SET state='FAILED',result=?,updated=? WHERE id=?",
                            (json.dumps(result), now, jid))
        self.db.execute("DELETE FROM jobs WHERE state IN ('COMPLETED','FAILED') AND updated<?", (now - 86400,))
        self.db.commit()

    def submit(self, job: ChatJob):
        job.validate()
        with self.lock:
            self._expire()
            if self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 10000:
                raise ValueError("QUEUE_FULL")
            self.db.execute("INSERT INTO jobs VALUES (?,?, 'QUEUED','', '',0,?,NULL,0,?)",
                            (job.job_id, json.dumps(job.to_dict()), self.clock()+job.timeout_s, self.clock()))
            self.db.commit()
        return job.job_id

    def poll(self, worker):
        if not worker or len(worker) > 100:
            raise ValueError("worker required (max 100 chars)")
        with self.lock:
            self._expire()
            if self.db.execute("SELECT id FROM jobs WHERE state='LEASED' AND worker=?", (worker,)).fetchone():
                return None
            row = self.db.execute("SELECT id,payload,deadline FROM jobs WHERE state='QUEUED' ORDER BY updated LIMIT 1").fetchone()
            if not row:
                return None
            jid, raw, deadline = row
            lease = secrets.token_urlsafe(32)
            until = min(deadline, self.clock()+30)
            self.db.execute("UPDATE jobs SET state='LEASED',worker=?,lease=?,lease_until=?,updated=? WHERE id=?",
                            (worker, lease, until, self.clock(), jid))
            self.db.commit()
            return {**json.loads(raw), "lease_token": lease, "deadline": deadline, "lease_until": until}

    def lease(self, jid, worker, token):
        with self.lock:
            self._expire()
            row = self.db.execute("SELECT state,worker,lease,deadline FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row or row[0] != 'LEASED' or row[1] != worker or not secrets.compare_digest(row[2], token):
                raise ValueError("STALE_OR_FOREIGN_LEASE")
            self.db.execute("UPDATE jobs SET lease_until=?,updated=? WHERE id=?",
                            (min(row[3], self.clock()+30), self.clock(), jid))
            self.db.commit()

    def store_result(self, res: ChatResult, token):
        res.validate()
        with self.lock:
            self._expire()
            row = self.db.execute("SELECT payload,state,worker,lease,result FROM jobs WHERE id=?", (res.job_id,)).fetchone()
            if not row or row[2] != res.worker or not secrets.compare_digest(row[3], token):
                raise ValueError("UNKNOWN_OR_FOREIGN_JOB")
            job = json.loads(row[0])
            if res.task_id != job['task_id']:
                raise ValueError("TASK_MISMATCH")
            if res.status == 'COMPLETED' and not job['new_chat'] and res.conversation_url != job['conversation_url']:
                raise ValueError("CONVERSATION_MISMATCH")
            encoded = json.dumps(res.to_dict())
            if row[1] in ('COMPLETED', 'FAILED'):
                if row[4] == encoded:
                    return  # safe duplicate result after lost HTTP acknowledgement
                raise ValueError("STALE_OR_CONFLICTING_RESULT")
            if row[1] != 'LEASED':
                raise ValueError("JOB_NOT_LEASED")
            self.db.execute("UPDATE jobs SET state=?,result=?,updated=? WHERE id=?",
                            (res.status, encoded, self.clock(), res.job_id))
            self.db.commit()

    def result(self, jid):
        with self.lock:
            self._expire()
            row = self.db.execute("SELECT result FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise ValueError("UNKNOWN_JOB")
            return json.loads(row[0]) if row[0] else None

    def acknowledge(self, jid):
        with self.lock:
            if self.result(jid) is None:
                raise ValueError("RESULT_NOT_READY")
            self.db.execute("UPDATE jobs SET ack=1 WHERE id=?", (jid,))
            self.db.commit()

    def cancel(self, jid):
        with self.lock:
            row = self.db.execute("SELECT payload,state FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise ValueError("UNKNOWN_JOB")
            if row[1] in ('COMPLETED','FAILED'):
                return
            res = ChatResult(job_id=jid, task_id=json.loads(row[0])['task_id'], status='FAILED', error='CANCELLED').to_dict()
            self.db.execute("UPDATE jobs SET state='FAILED',result=?,updated=? WHERE id=?",
                            (json.dumps(res), self.clock(), jid))
            self.db.commit()

    def counts(self):
        with self.lock:
            self._expire()
            counts = dict(self.db.execute("SELECT state,count(*) FROM jobs GROUP BY state"))
            return {"submitted": sum(counts.values()), "completed": counts.get('COMPLETED',0),
                    "failed": counts.get('FAILED',0), "queued": counts.get('QUEUED',0),
                    "leased": counts.get('LEASED',0)}

    def close(self):
        with self.lock:
            self.db.close()
