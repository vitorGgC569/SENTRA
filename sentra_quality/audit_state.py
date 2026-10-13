"""Protected configured outbox/head/proofs for the real audit SDK providers."""
import base64
import hashlib
import time
import uuid

from .protected_state import canonical, digest, StateConflict


class ProtectedAuditDeliveryStore:
    def __init__(self, state, *, max_pending=2000, max_bytes=32_000_000,
                 retention_seconds=30 * 86400):
        self.state = state.scoped("selo.audit")
        self.owner, self.workspace_id = state.owner, state.workspace_id
        self.scope = digest({"owner": self.owner, "workspace": self.workspace_id})
        self.max_pending, self.max_bytes = max_pending, max_bytes
        self.retention_seconds, self.clock = retention_seconds, state.clock

    def enqueue(self, *, provider, profile_sha256, event_id, body):
        key = digest({"provider": provider, "scope": self.scope, "event_id": event_id})
        if body.get("scope_sha256") != self.scope or len(canonical(body).encode()) > 65535:
            raise ValueError("audit body scope/bound mismatch")
        with self.state.transaction() as tx:
            old = tx.get("outbox:" + key)
            if old:
                row = old["value"]
                if (row["profile_sha256"], row["body_sha256"]) != (profile_sha256, digest(body)):
                    raise StateConflict("immutable audit event binding conflict")
                return key
            rows = [r["value"] for _, r in tx.records("outbox:")]
            if sum(r["state"] not in {"CONFIRMED", "REJECTED", "EXPIRED"} for r in rows) >= self.max_pending:
                raise StateConflict("audit queue full")
            if sum(r.get("bytes", 0) for r in rows) + len(canonical(body).encode()) > self.max_bytes:
                raise StateConflict("audit payload quota exceeded")
            now = self.clock()
            tx.put("outbox:" + key, {"id": key, "provider": provider,
                "profile_sha256": profile_sha256, "event_id": event_id,
                "body_sha256": digest(body), "body": body, "state": "QUEUED",
                "attempts": 0, "created_at": now, "updated_at": now,
                "bytes": len(canonical(body).encode()), "receipt": None})
        return key

    def row(self, key):
        row = self.state.get("outbox:" + key)
        if row is None:
            raise FileNotFoundError("audit delivery not found")
        return row["value"]

    def claim(self, key, *, provider, profile_sha256):
        with self.state.transaction() as tx:
            old = tx.get("outbox:" + key)
            if old is None:
                raise FileNotFoundError("audit delivery not found")
            row = old["value"]
            if (row["provider"], row["profile_sha256"], row["state"]) != (provider, profile_sha256, "QUEUED"):
                raise StateConflict("audit write already attempted; observe existing identity")
            row.update(state="IN_FLIGHT", attempts=row["attempts"] + 1, updated_at=self.clock())
            tx.put("outbox:" + key, row, expected_revision=old["revision"])
        return row

    @staticmethod
    def _head_key(provider, profile):
        return "head:" + digest([provider, profile])

    def head(self, provider, profile_sha256):
        return self.state.get(self._head_key(provider, profile_sha256))

    def initialize_head(self, provider, profile_sha256, value):
        return self.state.put(self._head_key(provider, profile_sha256), value)

    def update(self, key, *, state, receipt=None, head=None, expected_head_revision=None):
        if state not in {"CONFIRMED", "PENDING_INCLUSION", "UNCERTAIN", "REJECTED"}:
            raise ValueError("invalid audit delivery transition")
        with self.state.transaction() as tx:
            old = tx.get("outbox:" + key)
            if old is None:
                raise FileNotFoundError("audit delivery not found")
            row = old["value"]
            if row["state"] == "CONFIRMED" and state != "CONFIRMED":
                raise StateConflict("confirmed audit delivery cannot regress")
            if row["state"] in {"QUEUED", "EXPIRED", "REJECTED"}:
                raise StateConflict("audit delivery transition requires attempted write")
            if head is not None:
                if state != "CONFIRMED":
                    raise StateConflict("unverified audit head cannot advance")
                tx.put(self._head_key(row["provider"], row["profile_sha256"]), head,
                       expected_revision=expected_head_revision)
            row.update(state=state, updated_at=self.clock())
            if receipt is not None:
                row["receipt"] = receipt
            tx.put("outbox:" + key, row, expected_revision=old["revision"])

    def pending(self, provider, *, limit=64):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("invalid audit page")
        return sorted((r["value"] for _, r in self.state.records("outbox:")
                       if r["value"]["provider"] == provider and
                       r["value"]["state"] not in {"CONFIRMED", "REJECTED", "EXPIRED"}),
                      key=lambda row: row["created_at"])[:limit]

    def proof_blob(self, payload):
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= 16_000_000:
            raise ValueError("invalid native proof bytes")
        sha = hashlib.sha256(payload).hexdigest()
        with self.state.transaction() as tx:
            if tx.get("blob:" + sha) is None:
                used = sum(row["value"]["bytes"] for _, row in tx.records("blob:"))
                if used + len(payload) > self.max_bytes:
                    raise StateConflict("retained audit proof quota exceeded; archive before continuing")
                for offset in range(0, len(payload), 400_000):
                    tx.put("chunk:" + sha + ":" + str(offset // 400_000),
                           {"base64": base64.b64encode(payload[offset:offset + 400_000]).decode()})
                tx.put("blob:" + sha, {"bytes": len(payload), "sha256": sha,
                                       "created_at": self.clock()})
        return {"blob_id": sha, "sha256": sha, "bytes": len(payload)}

    def read_blob(self, reference):
        sha = reference if isinstance(reference, str) else reference.get("blob_id") or reference.get("sha256")
        metadata = self.state.get("blob:" + str(sha))
        if metadata is None:
            raise FileNotFoundError("retained proof unavailable")
        value = metadata["value"]
        chunks = []
        for index in range((value["bytes"] + 399_999) // 400_000):
            row = self.state.get("chunk:" + sha + ":" + str(index))
            if row is None:
                raise FileNotFoundError("retained proof incomplete")
            chunks.append(base64.b64decode(row["value"]["base64"], validate=True))
        payload = b"".join(chunks)
        if len(payload) != value["bytes"] or hashlib.sha256(payload).hexdigest() != sha:
            raise StateConflict("retained proof integrity mismatch")
        return payload

    def divergence(self, provider, evidence):
        key = "divergence:" + uuid.uuid4().hex
        with self.state.transaction() as tx:
            if len(tx.records("divergence:")) >= self.max_pending:
                raise StateConflict("audit divergence retention quota exceeded")
            tx.put(key, {"provider": provider, "evidence": evidence, "at": self.clock()})
        return key

    def status(self):
        counts = {}
        for _, record in self.state.records("outbox:"):
            state = record["value"]["state"]
            counts[state] = counts.get(state, 0) + 1
        return {"scope_sha256": self.scope, "states": counts,
                "trusted_heads": len(self.state.records("head:")),
                "divergences": len(self.state.records("divergence:")),
                "audit_complete": False, "authorizes_effects": False}

    def prune(self, *, confirmed_before):
        cutoff = min(confirmed_before, self.clock() - self.retention_seconds)
        expired = 0
        with self.state.transaction() as tx:
            for key, old in tx.records("outbox:"):
                row = old["value"]
                if row["state"] == "CONFIRMED" and row["updated_at"] < cutoff:
                    row.update(state="EXPIRED", body=None, receipt=None, bytes=0)
                    tx.put(key, row, expected_revision=old["revision"])
                    expired += 1
        # Proofs/heads/divergences remain recoverable; tombstones prohibit resend.
        return {"expired_payloads": expired, "proofs_preserved": True}
