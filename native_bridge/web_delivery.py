"""Durable Web message delivery projection on the relay's existing job SQLite.

Intent and receipts describe browser effects; they do not authorize effects.
No message body is stored here. Unconfirmed deliveries are never retransmitted.
"""
from __future__ import annotations
import hashlib
import json
import re

SEND_KINDS = {"CHAT_TASK", "CHAT_START", "CHAT_SEND"}
_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")


class WebDeliveryJournal:
    def __init__(self, db, clock, *, decode_payload):
        if not callable(decode_payload):
            raise TypeError("protected relay decoder required")
        self.db, self.clock = db, clock
        self.decode_payload = decode_payload
        db.executescript("""
            CREATE TABLE IF NOT EXISTS web_deliveries(
                delivery_key TEXT PRIMARY KEY, job_id TEXT UNIQUE NOT NULL,
                provider TEXT NOT NULL, conversation_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL, prompt_sha256 TEXT NOT NULL,
                state TEXT NOT NULL, receipt_json TEXT, updated REAL NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS web_delivery_active_chat
                ON web_deliveries(provider,conversation_key) WHERE state IN ('pending','unconfirmed');
            CREATE TABLE IF NOT EXISTS web_message_receipts(
                provider TEXT NOT NULL, conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
                job_id TEXT UNIQUE NOT NULL, receipt_sha256 TEXT NOT NULL,
                PRIMARY KEY(provider,conversation_id,message_id));
        """)

    @staticmethod
    def material(job):
        return {"provider": job.provider, "conversation_url": job.conversation_url,
                "new_chat": job.new_chat, "prompt_sha256": hashlib.sha256(job.prompt.encode()).hexdigest(),
                "images_sha256": [hashlib.sha256(image.encode()).hexdigest() for image in job.images],
                **({"attachments": job.attachments} if job.attachments else {}),
                "project_id": job.project_id, "project_url": job.project_url, "model": job.model,
                **({"dispatch_mode": job.dispatch_mode,
                    "requested_model": job.requested_model,
                    "requested_effort": job.requested_effort}
                   if job.dispatch_mode != "relay" or job.requested_model or job.requested_effort else {})}

    def lookup(self, job):
        if job.kind not in SEND_KINDS:
            return None
        key = job.delivery_key or "job:" + job.job_id
        material = self.material(job)
        fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        row = self.db.execute("SELECT job_id,fingerprint FROM web_deliveries WHERE delivery_key=?", (key,)).fetchone()
        if row and row[1] != fingerprint:
            raise ValueError("DELIVERY_KEY_CONFLICT")
        return row[0] if row else None

    def reserve(self, job):
        if job.kind not in SEND_KINDS:
            return
        material = self.material(job)
        fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        conversation = job.conversation_url or "new:" + job.job_id
        self.db.execute("INSERT INTO web_deliveries VALUES(?,?,?,?,?,?,'not_sent',NULL,?)",
                        (job.delivery_key or "job:" + job.job_id, job.job_id, job.provider,
                         conversation, fingerprint, material["prompt_sha256"], self.clock()))

    def pending(self, job_id, *, single_use=False):
        row = self.db.execute("SELECT state,provider,conversation_key FROM web_deliveries WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return
        if row[0] in {"sent", "unconfirmed"}:
            raise ValueError("DELIVERY_REQUIRES_RECONCILIATION")
        if single_use and row[0] != "not_sent":
            raise ValueError("DELIVERY_ACK_ALREADY_CONSUMED")
        other = self.db.execute("SELECT job_id FROM web_deliveries WHERE provider=? AND conversation_key=? "
                                "AND state IN ('pending','unconfirmed') AND job_id<>?",
                                (row[1], row[2], job_id)).fetchone()
        if other:
            raise ValueError("CONVERSATION_DELIVERY_BUSY")
        changed = self.db.execute("UPDATE web_deliveries SET state='pending',updated=? WHERE job_id=? AND state='not_sent'",
                                  (self.clock(), job_id)).rowcount
        if single_use and changed != 1:
            raise ValueError("DELIVERY_ACK_ALREADY_CONSUMED")

    def uncertain(self, job_id):
        self.db.execute("UPDATE web_deliveries SET state='unconfirmed',updated=? WHERE job_id=? AND state='pending'",
                        (self.clock(), job_id))

    def receipt(self, job_id, evidence):
        legacy = {"conversation_id", "message_id", "prompt_sha256", "images_attached"}
        binary = legacy | {"attachments", "attachment_names"}
        if not isinstance(evidence, dict) or set(evidence) not in (legacy, binary):
            raise ValueError("exact Web receipt schema required")
        for key in ("conversation_id", "message_id"):
            if not isinstance(evidence[key], str) or not _ID.fullmatch(evidence[key]):
                raise ValueError("exact Web message and conversation identities required")
        row = self.db.execute("SELECT provider,conversation_key,prompt_sha256,state,receipt_json FROM web_deliveries "
                              "WHERE job_id=?", (job_id,)).fetchone()
        if not row or row[3] == "not_sent":
            raise ValueError("receipt requires prior durable send intent")
        if evidence["prompt_sha256"] != row[2]:
            raise ValueError("Web receipt prompt digest mismatch")
        payload_row = self.db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not payload_row:
            raise ValueError("delivery job unavailable")
        job = self.decode_payload(payload_row[0], job_id)
        if type(evidence["images_attached"]) is not int or evidence["images_attached"] != len(job.get("images", [])):
            raise ValueError("Web receipt attachment count mismatch")
        refs = job.get("attachments", [])
        if refs:
            if (set(evidence) != binary or evidence["attachments"] != refs
                    or evidence["attachment_names"] != [ref["name"] for ref in refs]):
                raise ValueError("Web receipt does not cover the exact submitted binary set")
        elif set(evidence) != legacy:
            raise ValueError("unexpected binary set in text/image legacy receipt")
        if not job.get("new_chat"):
            from sentra_core.conversation import ConversationIdentity
            expected = ConversationIdentity.parse(job["conversation_url"]).conversation_id
            if expected != evidence["conversation_id"]:
                raise ValueError("Web receipt conversation mismatch")
        raw = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        if row[3] == "sent":
            if row[4] != raw:
                raise ValueError("conflicting Web delivery receipt")
            return self.status(job_id)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        old = self.db.execute("SELECT job_id,receipt_sha256 FROM web_message_receipts WHERE provider=? "
                              "AND conversation_id=? AND message_id=?",
                              (row[0], evidence["conversation_id"], evidence["message_id"])).fetchone()
        if old and old != (job_id, digest):
            raise ValueError("message receipt already belongs to another delivery")
        self.db.execute("INSERT OR IGNORE INTO web_message_receipts VALUES(?,?,?,?,?)",
                        (row[0], evidence["conversation_id"], evidence["message_id"], job_id, digest))
        self.db.execute("UPDATE web_deliveries SET state='sent',receipt_json=?,updated=? WHERE job_id=?",
                        (raw, self.clock(), job_id))
        return self.status(job_id)

    def status(self, job_id):
        row = self.db.execute("SELECT state,receipt_json,updated FROM web_deliveries WHERE job_id=?", (job_id,)).fetchone()
        return {"state": row[0], "receipt": json.loads(row[1]) if row[1] else None,
                "updated": row[2], "automatic_resend": False} if row else None
