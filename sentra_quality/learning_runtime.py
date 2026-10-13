"""Configured reviewed learning: exact protected transcript and central origin."""
import hashlib
import math
import time

from sentra_core.telemetry import safe_text
from .learning_review import ReviewedLearningStore
from .protected_state import StateConflict, digest


class ProtectedLearningStore(ReviewedLearningStore):
    def __init__(self, state, references):
        self.state, self.references = state.scoped("selo.learning"), references
        self.clock = state.clock

    def _owner(self, owner):
        if owner != self.state.owner:
            raise PermissionError("learning owner mismatch")

    def propose_from_artifact(self, *, operation_id, transcript_artifact_id, objective,
                              request_key, ttl_s=30 * 86400):
        if type(ttl_s) not in {int, float} or not math.isfinite(ttl_s) or not 1 <= ttl_s <= 90 * 86400:
            raise ValueError("invalid learning validity")
        if not isinstance(objective, str) or not 1 <= len(objective) <= 2000:
            raise ValueError("learning objective required")
        snapshot, original, artifact = self.references.transcript(operation_id, transcript_artifact_id)
        key = "su-" + digest([request_key, operation_id, artifact["sha256"]])[:40]
        value = {"suggestion_id": key, "workspace_id": self.state.workspace_id,
            "origin": snapshot["origin"], "agent_id": snapshot["principal_id"],
            "capability_id": snapshot["capability_id"],
            "scope": {"objective": safe_text(objective, 2000), "workspace_id": self.state.workspace_id,
                      "work_item_id": snapshot["origin"]["work_item_id"],
                      "required_capabilities": snapshot["required_capabilities"]},
            "result": {"state": snapshot["state"], "evidence_digest": snapshot["evidence_sha256"]},
            "quality_gate": snapshot["quality_gate"], "costs": snapshot["costs"],
            "original_transcript": original, "transcript": safe_text(original, 8192),
            "transcript_artifact": artifact, "transcript_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "status": "PROPOSED", "validity": {"expires_at": self.clock() + ttl_s},
            "reviews": [], "created_at": self.clock(), "updated_at": self.clock()}
        self.state.put(key, value)
        return self.get(self.state.owner, key)

    def get(self, owner, suggestion_id):
        self._owner(owner)
        row = self.state.get(suggestion_id)
        if row is None:
            raise FileNotFoundError("learning suggestion unavailable")
        item = dict(row["value"])
        item.pop("original_transcript", None)
        item.update(revision=row["revision"], activates_skill=False, creates_grants=False,
                    expired=self.clock() >= item["validity"]["expires_at"])
        return item

    def review(self, owner, suggestion_id, *, verdict, reviewer, expected_revision, reason=""):
        self._owner(owner)
        if verdict not in {"APPROVED", "REJECTED"} or not isinstance(reviewer, str) or not reviewer:
            raise ValueError("trusted human review required")
        with self.state.transaction() as tx:
            row = tx.get(suggestion_id)
            if row is None:
                raise FileNotFoundError("learning suggestion unavailable")
            item = row["value"]
            if item["status"] != "PROPOSED" or self.clock() >= item["validity"]["expires_at"]:
                raise StateConflict("learning suggestion closed or expired")
            # Review binds every byte, origin, capability manifest and validity.
            reviewed_sha = digest(item)
            item["reviews"].append({"reviewer": reviewer, "verdict": verdict,
                "reason": safe_text(reason, 2000), "reviewed_sha256": reviewed_sha,
                "created_at": self.clock()})
            item.update(status=verdict, updated_at=self.clock())
            tx.put(suggestion_id, item, expected_revision=expected_revision)
        return self.get(owner, suggestion_id)

    def withdraw(self, owner, suggestion_id, *, expected_revision):
        self._owner(owner)
        with self.state.transaction() as tx:
            row = tx.get(suggestion_id)
            if row is None:
                raise FileNotFoundError("learning suggestion unavailable")
            item = row["value"]
            item.update(status="WITHDRAWN", updated_at=self.clock())
            tx.put(suggestion_id, item, expected_revision=expected_revision)
        return self.get(owner, suggestion_id)

    def list(self, owner, *, status=None, limit=100, offset=0):
        self._owner(owner)
        if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or offset < 0:
            raise ValueError("invalid learning page")
        values = [self.get(owner, key) for key, _ in self.state.records("su-")]
        values = sorted((v for v in values if status is None or v["status"] == status),
                        key=lambda v: v["updated_at"], reverse=True)
        return {"items": values[offset:offset + limit], "total": len(values)}

    def to_skill_files(self, owner, suggestion_id):
        item = self.get(owner, suggestion_id)
        if item["expired"]:
            raise PermissionError("expired learning cannot produce a Skill candidate")
        live = self.references.snapshot(item["origin"]["operation_id"], terminal=True)
        if live["origin"] != item["origin"] or live["evidence_sha256"] != item["result"]["evidence_digest"]:
            raise StateConflict("learning origin changed since review")
        candidate = super().to_skill_files(owner, suggestion_id)
        candidate["capability_manifest"]["capabilities"] = item["scope"]["required_capabilities"]
        candidate.update(review_revision=item["revision"], reviews=item["reviews"],
                         validity=item["validity"], quality_gate=live["quality_gate"],
                         cost_event_ids=[v["cost_event_id"] for v in live["costs"]],
                         original_transcript_sha256=item["transcript_sha256"])
        return candidate
