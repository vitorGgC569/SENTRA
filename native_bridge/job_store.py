"""Durable leased jobs. Expired deliveries fail; they are never blindly resent."""
# REQUEUE SAFETY (por que so o nunca-iniciado volta a QUEUED):
# - Seguro: worker reportou apenas fases pre-send (preparing/navigating/settling/ready)
#   e NUNCA reportou sending/sent/waiting/reading. Como o contrato exige POST sending
#   com 200 ANTES de qualquer SEND_MESSAGE, ausencia de sending prova nada enviado.
# - Inseguro: qualquer fase pos-send (ou ausencia total de progresso em job LEASED)
#   significa envio incerto (pode ter enviado sem reportar); re-enfileirar duplicaria
#   mensagem no ChatGPT. Por isso vira FAILED/WORKER_LOST ou DELIVERY_SLOW, nunca QUEUED.
# - Teto: requeue preserva deadline original (created+timeout); lease novo nunca passa dele.
# - Limite: no maximo max_requeues (default 1) retornos a QUEUED; depois FAILED definitivo.
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
import time

from .protocol import (
    ChatJob,
    ChatResult,
    LEASE_WINDOW_S,
    MAX_REQUEUES_DEFAULT,
    PRE_SEND_PHASES,
    PROGRESS_WINDOW_S,
    ProgressReport,
)


def _workers_match(expected: str, actual: str) -> bool:
    if not expected or not actual:
        return False
    if expected == actual:
        return True
    if actual.startswith(expected) or expected.startswith(actual):
        return True
    exp_digits = re.search(r"\d+", expected)
    act_digits = re.search(r"\d+", actual)
    if exp_digits and act_digits and exp_digits.group(0) == act_digits.group(0):
        return True
    return False


class JobStore:
    LEASE_WINDOW_S = LEASE_WINDOW_S
    PROGRESS_WINDOW_S = PROGRESS_WINDOW_S

    def __init__(self, path=":memory:", clock=time.time, max_requeues=MAX_REQUEUES_DEFAULT):
        self.clock = clock
        self.max_requeues = int(max_requeues)
        if self.max_requeues < 0:
            raise ValueError("max_requeues must be >= 0")
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT, "
                        "state TEXT, worker TEXT, lease TEXT, lease_until REAL, deadline REAL, "
                        "result TEXT, ack INTEGER DEFAULT 0, updated REAL)")
        self.db.commit()
        self._ensure_columns()
        self._backfill_created()

    def _ensure_columns(self):
        cols = {row[1] for row in self.db.execute("PRAGMA table_info(jobs)").fetchall()}
        wanted = {
            "phase": "ALTER TABLE jobs ADD COLUMN phase TEXT DEFAULT ''",
            "progress_at": "ALTER TABLE jobs ADD COLUMN progress_at REAL DEFAULT 0",
            "created": "ALTER TABLE jobs ADD COLUMN created REAL DEFAULT 0",
            "requeues": "ALTER TABLE jobs ADD COLUMN requeues INTEGER DEFAULT 0",
            "may_have_sent": "ALTER TABLE jobs ADD COLUMN may_have_sent INTEGER DEFAULT 0",
        }
        for name, ddl in wanted.items():
            if name not in cols:
                self.db.execute(ddl)
        self.db.commit()

    def _backfill_created(self):
        rows = self.db.execute("SELECT id,payload,deadline FROM jobs WHERE created IS NULL OR created=0").fetchall()
        for jid, payload, deadline in rows:
            try:
                timeout = int(json.loads(payload).get("timeout_s", 180))
            except (ValueError, TypeError, AttributeError):
                timeout = 180
            created = (deadline or 0) - timeout
            self.db.execute("UPDATE jobs SET created=? WHERE id=?", (created, jid))
        self.db.commit()

    def _fail(self, jid, task_id, error, now):
        result = ChatResult(job_id=jid, task_id=task_id, status="FAILED", error=error).to_dict()
        self.db.execute("UPDATE jobs SET state='FAILED',result=?,updated=? WHERE id=?",
                        (json.dumps(result), now, jid))

    def _expire(self):
        now = self.clock()
        rows = self.db.execute(
            "SELECT id,payload,state,lease_until,deadline,phase,progress_at,requeues,may_have_sent "
            "FROM jobs WHERE state IN ('QUEUED','LEASED') "
            "AND (deadline<=? OR (state='LEASED' AND lease_until<=? "
            "AND (progress_at IS NULL OR progress_at<=0 OR progress_at+?<=?)))",
            (now, now, float(self.PROGRESS_WINDOW_S), now)).fetchall()
        for jid, payload, state, lease_until, deadline, phase, progress_at, requeues, may_sent in rows:
            try:
                job = json.loads(payload)
            except ValueError:
                job = {}
            task_id = job.get("task_id", "")
            phase = phase or ""
            progress_at = progress_at or 0
            requeues = requeues or 0
            may_sent = may_sent or 0
            recent = progress_at > 0 and (now - progress_at) <= float(self.PROGRESS_WINDOW_S)
            if state == "QUEUED":
                # Nunca alocado: nada foi enviado, seguro retentar por fora (sem auto-requeue).
                self._fail(jid, task_id,
                           "QUEUE_TIMEOUT: no worker claimed job before deadline; nothing was sent", now)
            elif deadline <= now:
                if recent:
                    # Lento: worker vivo (progresso recente) mas teto absoluto estourou.
                    self._fail(jid, task_id,
                               f"DELIVERY_SLOW: recent progress in phase '{phase}' but absolute "
                               "deadline exceeded; execution uncertain; reconcile before retry", now)
                else:
                    self._fail(jid, task_id,
                               "WORKER_LOST: no heartbeat nor progress before absolute deadline; "
                               "execution uncertain; not automatically resent", now)
            else:
                # Lease + progresso ambos vencidos, mas ainda ha orcamento de deadline.
                safe = (not may_sent) and progress_at > 0 and phase in PRE_SEND_PHASES
                if safe and requeues < self.max_requeues:
                    self.db.execute(
                        "UPDATE jobs SET state='QUEUED',worker='',lease='',lease_until=0,"
                        "updated=?,requeues=? WHERE id=?", (now, requeues + 1, jid))
                else:
                    reason = "uncertain execution" if may_sent or not progress_at else \
                        f"last phase '{phase}' not provably pre-send"
                    exhausted = f"; requeues exhausted ({requeues}/{self.max_requeues})" \
                        if safe and requeues >= self.max_requeues else ""
                    self._fail(jid, task_id,
                               f"WORKER_LOST: no heartbeat nor progress for "
                               f">{float(self.PROGRESS_WINDOW_S):.0f}s ({reason}); "
                               "execution uncertain; not automatically resent" + exhausted, now)
        self.db.execute("DELETE FROM jobs WHERE state IN ('COMPLETED','FAILED') AND updated<?", (now - 86400,))
        self.db.commit()

    def submit(self, job: ChatJob):
        job.validate()
        with self.lock:
            self._expire()
            if self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 10000:
                raise ValueError("QUEUE_FULL")
            now = self.clock()
            created = now
            deadline = created + job.timeout_s
            self.db.execute(
                "INSERT INTO jobs (id,payload,state,worker,lease,lease_until,deadline,"
                "result,ack,updated,phase,progress_at,created,requeues,may_have_sent) "
                "VALUES (?,?, 'QUEUED','', '',0,?,NULL,0,?,'',0,?,0,0)",
                (job.job_id, json.dumps(job.to_dict()), deadline, now, created))
            self.db.commit()
        return job.job_id

    def poll(self, worker):
        if not worker or len(worker) > 100:
            raise ValueError("worker required (max 100 chars)")
        with self.lock:
            self._expire()
            if self.db.execute("SELECT id FROM jobs WHERE state='LEASED' AND worker=?", (worker,)).fetchone():
                return None
            rows = self.db.execute(
                "SELECT id,payload,deadline,created,requeues,phase FROM jobs "
                "WHERE state='QUEUED' ORDER BY updated LIMIT 256").fetchall()
            row = None
            fallback = None
            for candidate in rows:
                try:
                    payload = json.loads(candidate[1])
                except ValueError:
                    payload = {}
                target = str(payload.get("target_worker") or "")
                if target and _workers_match(target, worker):
                    row = candidate
                    break
                if not target and fallback is None:
                    fallback = candidate
            if row is None:
                row = fallback
            if row is None:
                return None
            jid, raw, deadline, created, requeues, phase = row
            lease = secrets.token_urlsafe(32)
            until = min(deadline, self.clock() + float(self.LEASE_WINDOW_S))
            self.db.execute("UPDATE jobs SET state='LEASED',worker=?,lease=?,lease_until=?,updated=? WHERE id=?",
                            (worker, lease, until, self.clock(), jid))
            self.db.commit()
            return {**json.loads(raw), "lease_token": lease, "deadline": deadline, "lease_until": until,
                    "requeues": requeues or 0, "phase": phase or ""}

    def lease(self, jid, worker, token):
        with self.lock:
            self._expire()
            row = self.db.execute("SELECT state,worker,lease,deadline FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row or row[0] != 'LEASED' or not _workers_match(row[1], worker) or not secrets.compare_digest(row[2], token):
                raise ValueError("STALE_OR_FOREIGN_LEASE")
            self.db.execute("UPDATE jobs SET lease_until=?,updated=? WHERE id=?",
                            (min(row[3], self.clock() + float(self.LEASE_WINDOW_S)), self.clock(), jid))
            self.db.commit()

    def progress(self, jid, worker, token, phase):
        ProgressReport(job_id=jid, worker=worker, lease_token=token, phase=phase).validate()
        with self.lock:
            self._expire()
            row = self.db.execute(
                "SELECT state,worker,lease,deadline,lease_until,may_have_sent FROM jobs WHERE id=?",
                (jid,)).fetchone()
            if not row or row[0] != 'LEASED' or not _workers_match(row[1], worker) or not secrets.compare_digest(row[2], token):
                raise ValueError("STALE_OR_FOREIGN_LEASE")
            _, _, _, deadline, lease_until, may_sent = row
            now = self.clock()
            if deadline is None:
                raise ValueError("STALE_OR_FOREIGN_LEASE")
            # Invariante: lease nunca passa do deadline (teto = created+timeout_s).
            extended = min(deadline, max(lease_until or 0, now + float(self.PROGRESS_WINDOW_S)))
            latched = 1 if (may_sent or phase not in PRE_SEND_PHASES) else 0
            self.db.execute("UPDATE jobs SET phase=?,progress_at=?,lease_until=?,"
                            "may_have_sent=?,updated=? WHERE id=?",
                            (phase, now, extended, latched, now, jid))
            self.db.commit()
            return {"lease_until": extended, "deadline": deadline}

    def store_result(self, res: ChatResult, token):
        res.validate()
        with self.lock:
            self._expire()
            row = self.db.execute("SELECT payload,state,worker,lease,result FROM jobs WHERE id=?", (res.job_id,)).fetchone()
            if not row or not _workers_match(row[2], res.worker) or not secrets.compare_digest(row[3], token):
                raise ValueError("UNKNOWN_OR_FOREIGN_JOB")
            job = json.loads(row[0])
            if res.task_id != job['task_id']:
                raise ValueError("TASK_MISMATCH")
            if res.status == 'COMPLETED' and job.get('kind') not in ('STATUS_PROBE', 'DELETE_CHAT') and not job.get('new_chat'):
                expected_url = (job.get('conversation_url') or '').split('?')[0].rstrip('/')
                actual_url = (res.conversation_url or '').split('?')[0].rstrip('/')
                if expected_url and actual_url and expected_url != actual_url:
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
