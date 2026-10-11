"""Durable leased jobs. Expired deliveries fail; they are never blindly resent."""
# REQUEUE SAFETY (por que so o nunca-iniciado volta a QUEUED):
# - Seguro: worker reportou apenas fases pre-send (preparing/navigating/settling/ready)
#   e NUNCA reportou sending/sent/waiting/reading. Como o contrato exige POST sending
#   com 200 ANTES de qualquer SEND_MESSAGE, ausencia de sending prova nada enviado.
# - Inseguro: qualquer fase pos-send (ou ausencia total de progresso em job LEASED)
#   significa envio incerto (pode ter enviado sem reportar); re-enfileirar duplicaria
#   mensagem no ChatGPT. Por isso vira FAILED/WORKER_LOST ou DELIVERY_SLOW, nunca QUEUED.
# - Fila e execução têm relógios separados: esperar um worker não consome o budget do job.
# - Ao leasear/releasear com segurança, o deadline de execução nasce/reinicia no claim.
# - Limite: no maximo max_requeues (default 1) retornos a QUEUED; depois FAILED definitivo.
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
import time
from sentra_remote.secrets import protect_secret, unprotect_secret
from .web_delivery import WebDeliveryJournal

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
    # MV3 browser worker identity is the exact Chrome tab ID. Prefix/digit
    # aliases could let TAB-123 take TAB-12's lease and weaken V2 document
    # binding. Preserve legacy matching only for non-tab workers.
    if expected.startswith("TAB-") or actual.startswith("TAB-"):
        return False
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
    QUEUE_MIN_WINDOW_S = 900.0
    QUEUE_MAX_WINDOW_S = 3600.0
    QUEUE_TIMEOUT_MULTIPLIER = 4.0

    @classmethod
    def _queue_window(cls, timeout_s: int | float) -> float:
        return min(
            float(cls.QUEUE_MAX_WINDOW_S),
            max(float(cls.QUEUE_MIN_WINDOW_S), float(timeout_s) * float(cls.QUEUE_TIMEOUT_MULTIPLIER)),
        )

    def __init__(self, path=":memory:", clock=time.time, max_requeues=MAX_REQUEUES_DEFAULT):
        self.clock = clock
        self.max_requeues = int(max_requeues)
        if self.max_requeues < 0:
            raise ValueError("max_requeues must be >= 0")
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT, "
                        "state TEXT, worker TEXT, lease TEXT, lease_until REAL, deadline REAL, "
                        "result TEXT, ack INTEGER DEFAULT 0, updated REAL)")
        self.db.commit()
        try:
            self._ensure_columns()
            self._migrate_protected_rows()
            self._backfill_created()
            self.delivery = WebDeliveryJournal(
                self.db, self.clock, decode_payload=self._decode_payload)
        except BaseException:
            self.db.close()  # failed migration never starts an unsafe relay
            raise

    @staticmethod
    def _seal(value, job_id, field):
        raw = json.dumps({"version": 1, "job_id": job_id, "field": field,
                          "value": value}, ensure_ascii=False, separators=(",", ":"))
        protected = protect_secret(raw)
        if not protected.startswith(("dpapi:", "keyring:")):
            raise RuntimeError("OS-protected job storage unavailable")
        return protected

    @staticmethod
    def _unseal(raw, job_id, field):
        if not isinstance(raw, str) or not raw.startswith(("dpapi:", "keyring:")):
            raise RuntimeError("unprotected relay job rejected")
        try:
            obj = json.loads(unprotect_secret(raw))
        except Exception as exc:
            raise RuntimeError("relay job could not be opened by OS protection") from exc
        if (not isinstance(obj, dict) or obj.get("version") != 1
                or obj.get("job_id") != job_id or obj.get("field") != field
                or not isinstance(obj.get("value"), dict)):
            raise RuntimeError("relay job ciphertext identity mismatch")
        return obj["value"]

    def _decode_payload(self, raw, job_id):
        return self._unseal(raw, job_id, "payload")

    def _decode_result(self, raw, job_id):
        return self._unseal(raw, job_id, "result")

    def _migrate_protected_rows(self):
        """Atomic compatibility migration. Do not expose a partially migrated queue.

        A post-commit VACUUM plus WAL truncation rewrites SQLite free pages;
        historical filesystem snapshots remain outside this local migration.
        """
        self.db.execute("CREATE TABLE IF NOT EXISTS relay_storage_security ("
                        "key TEXT PRIMARY KEY, cleanup_pending INTEGER NOT NULL)")
        self.db.commit()
        try:
            self.db.execute("BEGIN IMMEDIATE")
            migrated = 0
            for jid, payload, result in self.db.execute(
                    "SELECT id,payload,result FROM jobs").fetchall():
                updates = {}
                for field, raw in (("payload", payload), ("result", result)):
                    if raw is None:
                        continue
                    if isinstance(raw, str) and raw.startswith(("dpapi:", "keyring:")):
                        self._unseal(raw, jid, field)
                        continue
                    if not isinstance(raw, str) or not raw.startswith("{"):
                        raise RuntimeError("unsupported legacy relay storage encoding")
                    try:
                        value = json.loads(raw)
                    except (TypeError, ValueError) as exc:
                        raise RuntimeError("invalid legacy relay job") from exc
                    if not isinstance(value, dict):
                        raise RuntimeError("invalid legacy relay job envelope")
                    updates[field] = self._seal(value, jid, field)
                if updates:
                    self.db.execute("UPDATE jobs SET payload=COALESCE(?,payload),"
                                    "result=COALESCE(?,result) WHERE id=?",
                                    (updates.get("payload"), updates.get("result"), jid))
                    migrated += 1
            if migrated:
                self.db.execute("INSERT INTO relay_storage_security VALUES('job_crypto',1) "
                                "ON CONFLICT(key) DO UPDATE SET cleanup_pending=1")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        row = self.db.execute("SELECT cleanup_pending FROM relay_storage_security "
                              "WHERE key='job_crypto'").fetchone()
        if row and row[0]:
            self.db.execute("VACUUM")
            busy = self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if busy and busy[0]:
                raise RuntimeError("relay legacy WAL cleanup could not complete")
            self.db.execute("UPDATE relay_storage_security SET cleanup_pending=0 "
                            "WHERE key='job_crypto'")
            self.db.commit()

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
                timeout = int(self._decode_payload(payload, jid).get("timeout_s", 180))
            except (ValueError, TypeError, AttributeError):
                timeout = 180
            created = (deadline or 0) - timeout
            self.db.execute("UPDATE jobs SET created=? WHERE id=?", (created, jid))
        self.db.commit()

    def _fail(self, jid, task_id, error, now):
        if hasattr(self,"delivery"):
            self.delivery.uncertain(jid)
        result = ChatResult(job_id=jid, task_id=task_id, status="FAILED", error=error).to_dict()
        self.db.execute("UPDATE jobs SET state='FAILED',result=?,updated=? WHERE id=?",
                        (self._seal(result, jid, "result"), now, jid))

    def _expire(self, *, commit=True):
        now = self.clock()
        rows = self.db.execute(
            "SELECT id,payload,state,lease_until,deadline,phase,progress_at,requeues,may_have_sent "
            "FROM jobs WHERE state IN ('QUEUED','LEASED') "
            "AND (deadline<=? OR (state='LEASED' AND lease_until<=? "
            "AND (progress_at IS NULL OR progress_at<=0 OR progress_at+?<=?)))",
            (now, now, float(self.PROGRESS_WINDOW_S), now)).fetchall()
        for jid, payload, state, lease_until, deadline, phase, progress_at, requeues, may_sent in rows:
            try:
                job = self._decode_payload(payload, jid)
            except (ValueError, TypeError):
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
                    timeout_s = int(job.get("timeout_s") or 180)
                    queue_deadline = now + self._queue_window(timeout_s)
                    self.db.execute(
                        "UPDATE jobs SET state='QUEUED',worker='',lease='',lease_until=0,"
                        "deadline=?,updated=?,requeues=? WHERE id=?",
                        (queue_deadline, now, requeues + 1, jid))
                else:
                    reason = "uncertain execution" if may_sent or not progress_at else \
                        f"last phase '{phase}' not provably pre-send"
                    exhausted = f"; requeues exhausted ({requeues}/{self.max_requeues})" \
                        if safe and requeues >= self.max_requeues else ""
                    self._fail(jid, task_id,
                               f"WORKER_LOST: no heartbeat nor progress for "
                               f">{float(self.PROGRESS_WINDOW_S):.0f}s ({reason}); "
                               "execution uncertain; not automatically resent" + exhausted, now)
        self.db.execute("DELETE FROM jobs WHERE state IN ('COMPLETED','FAILED') AND updated<? "
                        "AND id NOT IN (SELECT job_id FROM web_deliveries)", (now - 86400,))
        if commit:
            self.db.commit()

    def submit(self, job: ChatJob):
        job.validate()
        with self.lock, self.db:
            # Take the write lock BEFORE expiry reconciliation: _expire itself
            # can UPDATE a job. BEGIN after that UPDATE breaks the relay with
            # "cannot start a transaction within a transaction" on later sends.
            if self.db.in_transaction:
                # Preserve the legacy host API's explicit SQL edits on this
                # connection while upgrading its transaction to a writer.
                self.db.execute("UPDATE jobs SET updated=updated WHERE id IS NULL")
            else:
                self.db.execute("BEGIN IMMEDIATE")
            self._expire(commit=False)
            previous=self.delivery.lookup(job)
            if previous:
                return previous
            if self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 10000:
                raise ValueError("QUEUE_FULL")
            now = self.clock()
            created = now
            # Queue wait is capacity pressure, not execution time. Give queued
            # work its own bounded window; the execution deadline is created
            # only when a worker actually claims the job.
            deadline = created + self._queue_window(job.timeout_s)
            self.db.execute(
                "INSERT INTO jobs (id,payload,state,worker,lease,lease_until,deadline,"
                "result,ack,updated,phase,progress_at,created,requeues,may_have_sent) "
                "VALUES (?,?, 'QUEUED','', '',0,?,NULL,0,?,'',0,?,0,0)",
                (job.job_id, self._seal(job.to_dict(), job.job_id, "payload"), deadline, now, created))
            self.delivery.reserve(job)
            self.db.commit()
        return job.job_id

    def poll(self, worker, *, candidate_check=None):
        if not worker or len(worker) > 100:
            raise ValueError("worker required (max 100 chars)")
        with self.lock, self.db:
            # Multiple host processes can open the same SQLite outbox. The
            # claim must serialize before reading candidates, not just inside
            # this Python instance's lock.
            if self.db.in_transaction:
                self.db.execute("UPDATE jobs SET updated=updated WHERE id IS NULL")
            else:
                self.db.execute("BEGIN IMMEDIATE")
            self._expire(commit=False)
            if self.db.execute("SELECT id FROM jobs WHERE state='LEASED' AND worker=?", (worker,)).fetchone():
                return None
            rows = self.db.execute(
                "SELECT id,payload,deadline,created,requeues,phase FROM jobs "
                "WHERE state='QUEUED' ORDER BY updated LIMIT 256").fetchall()
            row = None
            fallback = None
            for candidate in rows:
                try:
                    payload = self._decode_payload(candidate[1], candidate[0])
                except (ValueError, TypeError):
                    payload = {}
                if payload.get("dispatch_mode", "relay") == "external":
                    continue
                # Admission is read-only and runs BEFORE taking any new lease.
                # A human-approval gate cannot silently create a new send.
                if candidate_check is not None and not candidate_check(payload):
                    continue
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
            jid, raw, _queue_deadline, created, requeues, phase = row
            payload = self._decode_payload(raw, jid)
            now = self.clock()
            timeout_s = int(payload.get("timeout_s") or 180)
            deadline = now + timeout_s
            lease = secrets.token_urlsafe(32)
            until = min(deadline, now + float(self.LEASE_WINDOW_S))
            self.db.execute(
                "UPDATE jobs SET state='LEASED',worker=?,lease=?,lease_until=?,deadline=?,updated=? WHERE id=?",
                (worker, lease, until, deadline, now, jid),
            )
            self.db.commit()
            return {**payload, "lease_token": lease, "deadline": deadline, "lease_until": until,
                    "requeues": requeues or 0, "phase": phase or ""}

    def claim(self, jid, worker):
        """Claim one externally owned job; no generic poll or physical effect."""
        if not isinstance(worker, str) or not 1 <= len(worker) <= 100:
            raise ValueError("worker required (max 100 chars)")
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self._expire(commit=False)
            row = self.db.execute("SELECT payload,state FROM jobs WHERE id=?", (jid,)).fetchone()
            if row is None or row[1] != "QUEUED":
                raise ValueError("JOB_NOT_QUEUED")
            payload = self._decode_payload(row[0], jid)
            target = payload.get("target_worker") or ""
            if target and target != worker:
                raise ValueError("FOREIGN_WORKER")
            if self.db.execute("SELECT 1 FROM jobs WHERE state='LEASED' AND worker=?", (worker,)).fetchone():
                raise ValueError("WORKER_BUSY")
            now = self.clock()
            deadline = now + int(payload.get("timeout_s") or 180)
            token = secrets.token_urlsafe(32)
            until = min(deadline, now + float(self.LEASE_WINDOW_S))
            self.db.execute("UPDATE jobs SET state='LEASED',worker=?,lease=?,lease_until=?,"
                            "deadline=?,updated=? WHERE id=? AND state='QUEUED'",
                            (worker, token, until, deadline, now, jid))
            return {**payload, "lease_token": token, "deadline": deadline, "lease_until": until}

    def lease(self, jid, worker, token):
        with self.lock:
            self._expire()
            row = self.db.execute("SELECT state,worker,lease,deadline FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row or row[0] != 'LEASED' or not _workers_match(row[1], worker) or not secrets.compare_digest(row[2], token):
                raise ValueError("STALE_OR_FOREIGN_LEASE")
            self.db.execute("UPDATE jobs SET lease_until=?,updated=? WHERE id=?",
                            (min(row[3], self.clock() + float(self.LEASE_WINDOW_S)), self.clock(), jid))
            self.db.commit()

    def progress(self, jid, worker, token, phase, *, single_use_send=False):
        ProgressReport(job_id=jid, worker=worker, lease_token=token, phase=phase).validate()
        with self.lock, self.db:
            if self.db.in_transaction:
                self.db.execute("UPDATE jobs SET updated=updated WHERE id IS NULL")
            else:
                self.db.execute("BEGIN IMMEDIATE")
            self._expire(commit=False)
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
            if phase=="sending":
                self.delivery.pending(jid, single_use=single_use_send)
            self.db.execute("UPDATE jobs SET phase=?,progress_at=?,lease_until=?,"
                            "may_have_sent=?,updated=? WHERE id=?",
                            (phase, now, extended, latched, now, jid))
            self.db.commit()
            return {"lease_until": extended, "deadline": deadline}

    def _complete_attested_answer(self, jid, *, worker, receipt, body):
        """Host-only finalizer AFTER central authenticated final history commit.

        Publishes the original ChatResult and ACK; never acquires another
        lease or dispatches a message. A late proven final repairs timeout.
        """
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT payload,worker,state,result FROM jobs WHERE id=?", (jid,)).fetchone()
            delivery = self.delivery.status(jid)
            if (row is None or row[1] != worker or not delivery or delivery["state"] != "sent"
                    or delivery.get("receipt") != receipt):
                raise PermissionError("final answer does not match original confirmed job")
            payload = self._decode_payload(row[0], jid)
            result = ChatResult(job_id=jid, task_id=payload["task_id"], status="COMPLETED", result=body,
                                conversation_url="https://chatgpt.com/c/" + receipt["conversation_id"],
                                conversation_id=receipt["conversation_id"], worker=worker,
                                images_attached=receipt["images_attached"])
            result.validate()
            if row[2] == "COMPLETED":
                existing = self._decode_result(row[3], jid)
                if any(existing.get(key) != result.to_dict()[key] for key in
                       ("task_id", "status", "result", "conversation_id", "worker", "images_attached")):
                    raise ValueError("final answer conflicts with original completed result")
                self.db.execute("UPDATE jobs SET ack=1 WHERE id=?", (jid,))
            else:
                self.db.execute("UPDATE jobs SET state='COMPLETED',result=?,ack=1,lease_until=0,updated=? WHERE id=?",
                                (self._seal(result.to_dict(), jid, "result"), self.clock(), jid))

    def store_result(self, res: ChatResult, token):
        res.validate()
        with self.lock:
            self._expire()
            row = self.db.execute("SELECT payload,state,worker,lease,result FROM jobs WHERE id=?", (res.job_id,)).fetchone()
            if not row or not _workers_match(row[2], res.worker) or not secrets.compare_digest(row[3], token):
                raise ValueError("UNKNOWN_OR_FOREIGN_JOB")
            job = self._decode_payload(row[0], res.job_id)
            if res.task_id != job['task_id']:
                raise ValueError("TASK_MISMATCH")
            if res.status == 'COMPLETED' and job.get('kind') not in ('STATUS_PROBE', 'DELETE_CHAT') and not job.get('new_chat'):
                expected_url = (job.get('conversation_url') or '').split('?')[0].rstrip('/')
                actual_url = (res.conversation_url or '').split('?')[0].rstrip('/')
                if expected_url and actual_url and expected_url != actual_url:
                    raise ValueError("CONVERSATION_MISMATCH")
            encoded = self._seal(res.to_dict(), res.job_id, "result")
            if row[1] in ('COMPLETED', 'FAILED'):
                if row[4] and self._decode_result(row[4], res.job_id) == res.to_dict():
                    return  # same result after lost HTTP acknowledgement
                raise ValueError("STALE_OR_CONFLICTING_RESULT")
            if row[1] != 'LEASED':
                raise ValueError("JOB_NOT_LEASED")
            self.db.execute("UPDATE jobs SET state=?,result=?,updated=? WHERE id=?",
                            (res.status, encoded, self.clock(), res.job_id))
            self.delivery.uncertain(res.job_id)
            self.db.commit()

    def delivery_receipt(self,jid,worker,token,evidence):
        with self.lock:
            row=self.db.execute("SELECT worker,lease FROM jobs WHERE id=?",(jid,)).fetchone()
            if not row or not _workers_match(row[0],worker) or not secrets.compare_digest(row[1],token):
                raise ValueError("UNKNOWN_OR_FOREIGN_JOB")
            try:
                self.db.execute("BEGIN IMMEDIATE")
                result=self.delivery.receipt(jid,evidence)
                self.db.commit()
                return result
            except BaseException:
                self.db.rollback()
                raise

    def delivery_status(self,jid):
        with self.lock:
            return self.delivery.status(jid)

    def result(self, jid):
        with self.lock:
            self._expire()
            row = self.db.execute(
                "SELECT result,phase,may_have_sent,state FROM jobs WHERE id=?", (jid,)
            ).fetchone()
            if not row:
                raise ValueError("UNKNOWN_JOB")
            if not row[0]:
                return None
            value = self._decode_result(row[0], jid)
            if isinstance(value, dict):
                # Terminal delivery evidence is part of the relay contract.
                # Clients use this to decide whether a failed START is replay-safe.
                value["_delivery_phase"] = row[1] or ""
                value["_may_have_sent"] = bool(row[2])
                value["_relay_state"] = row[3]
                value["_web_delivery"] = self.delivery.status(jid)
            return value

    def pending_status(self, jid):
        with self.lock:
            self._expire()
            row = self.db.execute(
                "SELECT state,worker,deadline,phase,requeues,may_have_sent,created,updated "
                "FROM jobs WHERE id=?",
                (jid,),
            ).fetchone()
            if not row:
                raise ValueError("UNKNOWN_JOB")
            return {
                "state": row[0],
                "worker": row[1] or "",
                "deadline": row[2],
                "phase": row[3] or "",
                "requeues": int(row[4] or 0),
                "may_have_sent": bool(row[5]),
                "created": row[6],
                "updated": row[7],
                "web_delivery":self.delivery.status(jid),
            }

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
            res = ChatResult(job_id=jid, task_id=self._decode_payload(row[0], jid)['task_id'], status='FAILED', error='CANCELLED').to_dict()
            self.db.execute("UPDATE jobs SET state='FAILED',result=?,updated=? WHERE id=?",
                            (self._seal(res, jid, "result"), self.clock(), jid))
            self.delivery.uncertain(jid)
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
