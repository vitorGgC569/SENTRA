"""Selo: reviewed learning suggestions (CF17/FF10, revised).

A suggestion captures origin, scope, validity, result and the original
transcript (redacted, bounded) of a past SUCCEEDED/FAILED operation. It is
knowledge only: it never executes, never creates grants, and never activates
a Skill by itself.

Activation belongs to Pacto: only ``SkillLibrary`` (review + SHA pin +
capability manifest + pre-existing grant, explicit WorkItem activation) may
disclose a skill. This module produces the review bundle Pacto consumes:
file inventory with per-file SHA, SKILL.md frontmatter, and the activation
preconditions. Publishing a suggestion automatically is rejected by design.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RESULT = {"SUCCEEDED", "FAILED"}
_STATUS = {"PROPOSED", "APPROVED", "REJECTED", "WITHDRAWN"}
_MAX_TRANSCRIPT = 8192


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _redacted_transcript(text: str) -> str:
    try:
        from sentra_core.telemetry import safe_text
        return safe_text(text, _MAX_TRANSCRIPT)
    except Exception as exc:
        raise RuntimeError("trusted transcript redactor unavailable") from exc


class ReviewedLearningStore:
    """Owner-scoped durable store of reviewable learning suggestions."""

    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        root = Path(state_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "selo_learning.sqlite3"
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_suggestions(
                    owner TEXT NOT NULL,
                    suggestion_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    agent_id TEXT,
                    capability_id TEXT,
                    origin_json TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    validity_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner, suggestion_id)
                );
                CREATE TABLE IF NOT EXISTS learning_reviews(
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    suggestion_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")
            with db:
                yield db
        finally:
            db.close()

    def propose(self, owner: str, *, workspace_id: str,
                origin: dict[str, Any], scope: dict[str, Any],
                result: dict[str, Any], transcript: str,
                agent_id: str | None = None, capability_id: str | None = None,
                ttl_s: float | None = None) -> dict[str, Any]:
        owner = str(owner or "").strip()
        workspace_id = str(workspace_id or "").strip()
        if not owner or not workspace_id:
            raise ValueError("owner and workspace_id are required")
        if not isinstance(origin, dict):
            raise ValueError("origin must be an object")
        for key in ("operation_id", "work_item_id", "run_id"):
            if not str(origin.get(key) or "").strip():
                raise ValueError(f"origin.{key} is required")
        intent = str(origin.get("intent_sha256") or "")
        if intent and not _SHA256.fullmatch(intent):
            raise ValueError("origin.intent_sha256 must be hex sha256")
        if not isinstance(scope, dict) or not scope:
            raise ValueError("scope must be a non-empty object")
        if not isinstance(result, dict) or result.get("state") not in _RESULT:
            raise ValueError("result.state must be SUCCEEDED or FAILED")
        evidence = str(result.get("evidence_digest") or "")
        if evidence and not _SHA256.fullmatch(evidence):
            raise ValueError("result.evidence_digest must be hex sha256")
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError("original transcript is required")
        redacted = _redacted_transcript(transcript)
        expires_at = None
        if ttl_s is not None:
            if not isinstance(ttl_s, (int, float)) or not 1 <= float(ttl_s) <= 90 * 86400:
                raise ValueError("ttl_s must be 1..7776000")
            expires_at = self.clock() + float(ttl_s)
        suggestion_id = "su-" + uuid.uuid4().hex
        now = self.clock()
        validity = {"expires_at": expires_at}
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO learning_suggestions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (owner, suggestion_id, workspace_id, agent_id, capability_id,
                 _canonical(origin), _canonical(scope), _canonical(result),
                 redacted, "PROPOSED", 1, _canonical(validity), now, now),
            )
        return {"suggestion_id": suggestion_id, "status": "PROPOSED", "revision": 1,
                "transcript_redacted": True, "activates_skill": False,
                "creates_grants": False}

    def get(self, owner: str, suggestion_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM learning_suggestions WHERE owner=? AND suggestion_id=?",
                (owner, suggestion_id),
            ).fetchone()
            reviews = db.execute(
                "SELECT verdict,reviewer,reason,created_at FROM learning_reviews "
                "WHERE owner=? AND suggestion_id=? ORDER BY review_id",
                (owner, suggestion_id),
            ).fetchall()
        if row is None:
            raise FileNotFoundError("learning suggestion not found")
        item = dict(row)
        item["origin"] = json.loads(item.pop("origin_json"))
        item["scope"] = json.loads(item.pop("scope_json"))
        item["result"] = json.loads(item.pop("result_json"))
        item["validity"] = json.loads(item.pop("validity_json"))
        item["reviews"] = [dict(r) for r in reviews]
        item["activates_skill"] = False
        item["creates_grants"] = False
        return item

    def review(self, owner: str, suggestion_id: str, *, verdict: str,
               reviewer: str, reason: str = "",
               expected_revision: int | None = None) -> dict[str, Any]:
        verdict = str(verdict or "").upper()
        if verdict not in {"APPROVED", "REJECTED"}:
            raise ValueError("verdict must be APPROVED or REJECTED")
        reviewer = str(reviewer or "").strip()
        if not reviewer:
            raise ValueError("reviewer is required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,revision FROM learning_suggestions "
                "WHERE owner=? AND suggestion_id=?",
                (owner, suggestion_id),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("learning suggestion not found")
            if row["status"] != "PROPOSED":
                raise ValueError("only PROPOSED suggestions accept review")
            if expected_revision is not None and int(row["revision"]) != expected_revision:
                raise ValueError("suggestion revision conflict")
            now = self.clock()
            db.execute(
                "UPDATE learning_suggestions SET status=?,revision=revision+1,updated_at=? "
                "WHERE owner=? AND suggestion_id=?",
                (verdict, now, owner, suggestion_id),
            )
            db.execute(
                "INSERT INTO learning_reviews(owner,suggestion_id,verdict,reviewer,reason,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (owner, suggestion_id, verdict, reviewer, str(reason)[:2000], now),
            )
        return self.get(owner, suggestion_id)

    def withdraw(self, owner: str, suggestion_id: str,
                 *, expected_revision: int | None = None) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,revision FROM learning_suggestions "
                "WHERE owner=? AND suggestion_id=?",
                (owner, suggestion_id),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("learning suggestion not found")
            if row["status"] not in {"PROPOSED", "APPROVED"}:
                raise ValueError("suggestion already closed")
            if expected_revision is not None and int(row["revision"]) != expected_revision:
                raise ValueError("suggestion revision conflict")
            db.execute(
                "UPDATE learning_suggestions SET status='WITHDRAWN',revision=revision+1,"
                "updated_at=? WHERE owner=? AND suggestion_id=?",
                (self.clock(), owner, suggestion_id),
            )
        return self.get(owner, suggestion_id)

    def list(self, owner: str, *, status: str | None = None,
             limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if status is not None and str(status).upper() not in _STATUS:
            raise ValueError("unknown suggestion status")
        if type(limit) is not int or not 1 <= limit <= 500 \
                or type(offset) is not int or offset < 0:
            raise ValueError("invalid suggestion page")
        with self._connect() as db:
            where = "owner=?"
            params: list[Any] = [owner]
            if status is not None:
                where += " AND status=?"
                params.append(str(status).upper())
            total = db.execute(
                "SELECT COUNT(*) FROM learning_suggestions WHERE " + where,
                tuple(params),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT suggestion_id,workspace_id,agent_id,capability_id,status,"
                "revision,created_at,updated_at FROM learning_suggestions "
                "WHERE " + where + " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total,
                "offset": offset, "limit": limit}

    # -- Pacto handoff ----------------------------------------------------

    @staticmethod
    def _skill_name(suggestion_id: str, scope: dict[str, Any]) -> str:
        hint = re.sub(r"[^A-Za-z0-9._-]+", "-",
                      str(scope.get("objective") or scope.get("action") or "lesson"))
        hint = hint.strip("-").lower()[:40] or "lesson"
        return f"selo-{hint}-{suggestion_id[-8:]}"

    def to_skill_files(self, owner: str, suggestion_id: str) -> dict[str, Any]:
        """Build candidate SkillPack files from an APPROVED suggestion.

        Returns files + inventory for ``SkillLibrary`` import review. The
        caller (Pacto/Codex composition) still must import, review, pin SHA,
        declare the capability manifest and hold pre-existing grants before
        any WorkItem activation. This method activates nothing.
        """
        item = self.get(owner, suggestion_id)
        if item["status"] != "APPROVED":
            raise PermissionError("only APPROVED suggestions produce skill candidates")
        expires_at = item.get("validity", {}).get("expires_at")
        if expires_at is not None and self.clock() >= expires_at:
            raise PermissionError("expired suggestion cannot produce skill candidates")
        origin = item["origin"]
        result = item["result"]
        name = self._skill_name(suggestion_id, item["scope"])
        if not _NAME.fullmatch(name):
            raise ValueError("derived skill name invalid")
        description = ("Reviewed lesson from operation "
                       + str(origin.get("operation_id", ""))[:64]
                       + " (" + str(result.get("state")) + "). "
                         "Revalidate inputs, permissions and output verification "
                         "before applying.")[:2000]
        skill_md = (
            "---\n"
            f"name: {name}\n"
            f"description: \"{description}\"\n"
            "version: 1\n"
            "---\n\n"
            f"# {name}\n\n"
            f"Result: {result.get('state')}\n\n"
            f"Origin: run {origin.get('run_id')}, work item {origin.get('work_item_id')}, "
            f"operation {origin.get('operation_id')}.\n\n"
            "Scope:\n\n```json\n" + _canonical(item["scope"]) + "\n```\n\n"
            "Original transcript (redacted, preserved):\n\n```text\n"
            + item["transcript"] + "\n```\n"
        )
        files = {"SKILL.md": skill_md}
        inventory = [{"path": path,
                      "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                      "bytes": len(text.encode("utf-8"))}
                     for path, text in sorted(files.items())]
        package_sha = hashlib.sha256(_canonical(files).encode()).hexdigest()
        return {
            "suggestion_id": suggestion_id,
            "name": name,
            "description": description,
            "source": "selo-learning:" + suggestion_id,
            "files": files,
            "inventory": inventory,
            "package_sha256": package_sha,
            "capability_manifest": {
                "skill": name,
                "package_sha256": package_sha,
                "requires": ["explicit_work_item_activation", "preexisting_grant",
                             "capability_manifest"],
            },
            "executable": False,
            "activates_skill": False,
            "creates_grants": False,
        }

    def review_bundle(self, owner: str, suggestion_id: str) -> dict[str, Any]:
        """Operator review bundle mirroring ``SkillLibrary.review`` shape."""
        candidate = self.to_skill_files(owner, suggestion_id)
        item = self.get(owner, suggestion_id)
        frontmatter = {"name": candidate["name"],
                       "description": candidate["description"],
                       "version": "1"}
        return {"package_id": candidate["package_sha256"],
                "name": candidate["name"],
                "description": candidate["description"],
                "source": candidate["source"],
                "git_sha": None,
                "revoked": False,
                "revision": item["revision"],
                "created": item["created_at"],
                "frontmatter": frontmatter,
                "files": candidate["inventory"],
                "capability_manifest": candidate["capability_manifest"],
                "executable": False,
                "grants_created": False,
                "activation_requires": ["operator_review", "sha_pin",
                                        "capability_manifest", "preexisting_grant"]}
