"""Deterministic single-writer integration for concurrent SENTRA candidates."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from workspace.sandbox import fingerprint, source_files


class RevisionConflict(RuntimeError):
    """The revision ledger moved after reconciliation and before commit."""


@dataclass
class IntegrationResult:
    ok: bool
    code: str
    evidence: dict[str, Any]
    revision_before: int
    revision_after: int | None = None
    rebased: bool = False
    conflicts: list[str] | None = None
    touched_files: list[str] | None = None
    resource_set: list[str] | None = None
    fencing_token: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectRevisionStore:
    """Append-only SQLite revision ledger.

    The source workspace never stores this database. state_root must point at
    SENTRA runtime state, normally project/.sentra or a Run directory.
    SQLite serializes revision numbering; the Durable Core lease fences the
    actual workspace write.
    """

    def __init__(self, state_root: Path | str) -> None:
        self.state_root = Path(state_root)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.path = self.state_root / "project-revisions.sqlite3"
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS project_revisions (
                    project_key TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    workspace_hash TEXT NOT NULL,
                    previous_hash TEXT,
                    run_id TEXT,
                    task_id TEXT,
                    candidate_id TEXT,
                    patch_hash TEXT,
                    touched_files_json TEXT NOT NULL,
                    fencing_token INTEGER,
                    kind TEXT NOT NULL,
                    committed_at REAL NOT NULL,
                    PRIMARY KEY (project_key, revision)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_revision_latest "
                "ON project_revisions(project_key, revision DESC)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30.0)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _latest_locked(db: sqlite3.Connection, project_key: str) -> tuple[int, str] | None:
        row = db.execute(
            "SELECT revision, workspace_hash FROM project_revisions "
            "WHERE project_key=? ORDER BY revision DESC LIMIT 1",
            (project_key,),
        ).fetchone()
        return (int(row[0]), str(row[1])) if row else None

    def observe(
        self,
        project_key: str,
        workspace_hash: str,
        *,
        run_id: str = "",
    ) -> tuple[int, str]:
        """Return current revision, recording uncoordinated external drift."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = self._latest_locked(db, project_key)
            if latest is None:
                db.execute(
                    "INSERT INTO project_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_key, 0, workspace_hash, None, run_id, None, None,
                        None, "[]", None, "BASELINE", time.time(),
                    ),
                )
                db.commit()
                return 0, workspace_hash
            revision, known_hash = latest
            if known_hash == workspace_hash:
                db.commit()
                return revision, known_hash
            revision += 1
            db.execute(
                "INSERT INTO project_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    project_key, revision, workspace_hash, known_hash, run_id,
                    None, None, None, "[]", None, "EXTERNAL_CHANGE", time.time(),
                ),
            )
            db.commit()
            return revision, workspace_hash

    def commit(
        self,
        project_key: str,
        *,
        expected_base_hash: str,
        workspace_hash: str,
        run_id: str,
        task_id: str,
        candidate_id: str,
        patch_hash: str,
        touched_files: list[str],
        fencing_token: int | None,
    ) -> int:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = self._latest_locked(db, project_key)
            if latest is None:
                raise RevisionConflict("project revision baseline is missing")
            revision, known_hash = latest
            if known_hash != expected_base_hash:
                raise RevisionConflict(
                    "project revision moved during integration "
                    f"(expected {expected_base_hash[:12]}, ledger {known_hash[:12]})"
                )
            if workspace_hash == known_hash and not patch_hash:
                db.commit()
                return revision
            next_revision = revision + 1
            db.execute(
                "INSERT INTO project_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    project_key,
                    next_revision,
                    workspace_hash,
                    known_hash,
                    run_id,
                    task_id,
                    candidate_id,
                    patch_hash or None,
                    json.dumps(sorted(set(touched_files)), ensure_ascii=False),
                    fencing_token,
                    "CANDIDATE_COMMIT",
                    time.time(),
                ),
            )
            db.commit()
            return next_revision

    def latest(self, project_key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT revision, workspace_hash, previous_hash, run_id, task_id, "
                "candidate_id, patch_hash, touched_files_json, fencing_token, kind, committed_at "
                "FROM project_revisions WHERE project_key=? "
                "ORDER BY revision DESC LIMIT 1",
                (project_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "revision": int(row[0]),
            "workspace_hash": row[1],
            "previous_hash": row[2],
            "run_id": row[3],
            "task_id": row[4],
            "candidate_id": row[5],
            "patch_hash": row[6],
            "touched_files": json.loads(row[7] or "[]"),
            "fencing_token": row[8],
            "kind": row[9],
            "committed_at": float(row[10]),
        }


class ProjectIntegrationCoordinator:
    """Only logical writer for candidate integration into one workspace."""

    def __init__(
        self,
        workspace: Path | str,
        verifier: Any,
        *,
        state_root: Path | str,
        project_key: str,
        resource_lease_manager: Any | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.verifier = verifier
        self.project_key = str(project_key)
        if not self.project_key:
            raise ValueError("project_key is required")
        self.revisions = ProjectRevisionStore(state_root)
        self.resource_lease_manager = resource_lease_manager
        self._lock = asyncio.Lock()

    @staticmethod
    def _hash_bytes(value: bytes | None) -> str | None:
        return hashlib.sha256(value).hexdigest() if value is not None else None

    def _conflicts(self, evidence: dict[str, Any]) -> tuple[list[str], list[str]]:
        touched_base_hashes = dict(evidence.get("touched_base_hashes") or {})
        touched = sorted(touched_base_hashes)
        current = source_files(self.workspace)
        conflicts = [
            path
            for path, expected in touched_base_hashes.items()
            if self._hash_bytes(current.get(path)) != expected
        ]
        return sorted(conflicts), touched

    async def integrate(
        self,
        task: Any,
        candidate: Any,
        evidence: dict[str, Any],
        apply_patch: Callable[[str], Awaitable[dict[str, Any]]],
    ) -> IntegrationResult:
        """Reconcile, reverify if stale, apply once, then advance revision."""
        async with self._lock:
            leases: list[dict[str, Any]] = []
            if self.resource_lease_manager is not None:
                acquired = self.resource_lease_manager.acquire(
                    task, ["project:integration"]
                )
                if acquired is None:
                    return IntegrationResult(
                        False, "INTEGRATION_LEASE_BUSY", dict(evidence), -1,
                        error="another writer holds the project integration lease",
                    )
                leases = list(acquired)
            fencing_token = max(
                (int(item.get("fencing_token", 0)) for item in leases),
                default=0,
            ) or None
            try:
                current_hash = fingerprint(source_files(self.workspace))
                revision_before, _ = self.revisions.observe(
                    self.project_key,
                    current_hash,
                    run_id=str(getattr(task, "run_id", "")),
                )
                working = dict(evidence)
                rebased = current_hash != str(working.get("base_hash") or "")
                conflicts: list[str] = []
                touched = sorted(working.get("touched_files") or [])
                if rebased:
                    conflicts, touched = self._conflicts(working)
                    if conflicts or not touched:
                        detail = ",".join(conflicts[:20]) or "candidate scope unavailable"
                        return IntegrationResult(
                            False,
                            "STALE_BASE_CONFLICT",
                            working,
                            revision_before,
                            rebased=True,
                            conflicts=conflicts,
                            touched_files=touched,
                            resource_set=["project:integration", *[f"file:{p}" for p in touched]],
                            fencing_token=fencing_token,
                            error=detail,
                        )
                    working = await self.verifier.verify(candidate)
                    if not working.get("all_passed") or not working.get("source_unchanged"):
                        failed = ",".join(working.get("failed_commands") or [])
                        return IntegrationResult(
                            False,
                            "STALE_BASE_REVERIFY_FAILED",
                            working,
                            revision_before,
                            rebased=True,
                            conflicts=[],
                            touched_files=touched,
                            resource_set=["project:integration", *[f"file:{p}" for p in touched]],
                            fencing_token=fencing_token,
                            error=failed or "verification failed",
                        )
                    current_hash = str(working.get("base_hash") or current_hash)

                if not working.get("all_passed") or not working.get("source_unchanged"):
                    return IntegrationResult(
                        False,
                        "INTEGRATION_EVIDENCE_INVALID",
                        working,
                        revision_before,
                        rebased=rebased,
                        conflicts=conflicts,
                        touched_files=touched,
                        fencing_token=fencing_token,
                        error="candidate lacks passing immutable objective evidence",
                    )
                if fingerprint(source_files(self.workspace)) != working.get("base_hash"):
                    return IntegrationResult(
                        False,
                        "INTEGRATION_BASE_MOVED",
                        working,
                        revision_before,
                        rebased=rebased,
                        touched_files=touched,
                        fencing_token=fencing_token,
                        error="workspace changed after reconciliation",
                    )

                patch = str(getattr(candidate, "patch", "") or "")
                if leases and self.resource_lease_manager is not None:
                    try:
                        leases = self.resource_lease_manager.renew(leases, task)
                        fencing_token = max(
                            int(item.get("fencing_token", 0))
                            for item in leases
                        )
                    except Exception as exc:
                        return IntegrationResult(
                            False,
                            "STALE_FENCE",
                            working,
                            revision_before,
                            rebased=rebased,
                            touched_files=touched,
                            fencing_token=fencing_token,
                            error=str(exc),
                        )
                patch_result = await apply_patch(patch)
                if not patch_result.get("success"):
                    return IntegrationResult(
                        False,
                        "INTEGRATION_APPLY_FAILED",
                        working,
                        revision_before,
                        rebased=rebased,
                        touched_files=touched,
                        fencing_token=fencing_token,
                        error=str(patch_result.get("error") or "integration failed"),
                    )

                after_hash = fingerprint(source_files(self.workspace))
                expected_after = str(working.get("candidate_hash") or "")
                if expected_after and after_hash != expected_after:
                    return IntegrationResult(
                        False,
                        "INTEGRATION_POST_APPLY_HASH_MISMATCH",
                        working,
                        revision_before,
                        rebased=rebased,
                        touched_files=touched,
                        fencing_token=fencing_token,
                        error="applied workspace does not match verified candidate hash",
                    )
                patch_hash = (
                    hashlib.sha256(patch.encode("utf-8")).hexdigest()
                    if patch else ""
                )
                revision_after = self.revisions.commit(
                    self.project_key,
                    expected_base_hash=current_hash,
                    workspace_hash=after_hash,
                    run_id=str(getattr(task, "run_id", "")),
                    task_id=str(getattr(task, "id", "")),
                    candidate_id=str(getattr(candidate, "candidate_id", "")),
                    patch_hash=patch_hash,
                    touched_files=touched,
                    fencing_token=fencing_token,
                )
                return IntegrationResult(
                    True,
                    "INTEGRATED",
                    working,
                    revision_before,
                    revision_after=revision_after,
                    rebased=rebased,
                    conflicts=[],
                    touched_files=touched,
                    resource_set=["project:integration", *[f"file:{p}" for p in touched]],
                    fencing_token=fencing_token,
                )
            except RevisionConflict as exc:
                return IntegrationResult(
                    False,
                    "PROJECT_REVISION_CONFLICT",
                    dict(evidence),
                    -1,
                    fencing_token=fencing_token,
                    error=str(exc),
                )
            finally:
                if leases and self.resource_lease_manager is not None:
                    self.resource_lease_manager.release(leases)


async def integrate_engine_candidate(
    engine: Any,
    task: Any,
    candidate: Any,
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    """Engine adapter: coordinator owns writes; engine keeps task/package state."""
    from .events import EventEnvelope, EventType

    async def _apply(patch_text: str) -> dict[str, Any]:
        if not patch_text:
            return {"success": True}
        return await engine.tool_gateway.execute_patch(
            role="master",
            patch_text=patch_text,
            idempotency_key=f"{task.id}_{candidate.candidate_id}",
        )

    result = await engine.integration_coordinator.integrate(
        task, candidate, evidence, _apply
    )
    if result.rebased:
        task.metadata["optimistic_rebase"] = {
            "applied": result.ok,
            "touched_files": list(result.touched_files or []),
            "new_base_hash": result.evidence.get("base_hash"),
            "candidate_hash": result.evidence.get("candidate_hash"),
            "project_revision_before": result.revision_before,
            "project_revision_after": result.revision_after,
            "fencing_token": result.fencing_token,
        }
        await engine.event_bus.publish(
            EventEnvelope(
                event_type=EventType.VALIDATION_COMPLETED,
                correlation_id=engine.run_id,
                task_id=task.id,
                candidate_id=candidate.candidate_id,
                producer="integration-coordinator",
                payload={
                    "status": "APPROVED" if result.ok else "REJECTED",
                    "ran": True,
                    "kind": "optimistic_rebase",
                    "code": result.code,
                    "touched_files": list(result.touched_files or []),
                    "base_hash": result.evidence.get("base_hash"),
                    "candidate_hash": result.evidence.get("candidate_hash"),
                    "project_revision_before": result.revision_before,
                    "project_revision_after": result.revision_after,
                    "fencing_token": result.fencing_token,
                },
            )
        )
    if not result.ok:
        detail = str(result.error or result.code)
        engine._record_program_candidate(
            task, candidate, result.code, notes=detail
        )
        await engine.task_queue.mark_failed(
            task.id, f"{result.code}: {detail}"
        )
        return None

    task.metadata["project_revision"] = result.revision_after
    task.metadata["integration_fencing_token"] = result.fencing_token
    task.metadata["integration_resource_set"] = list(result.resource_set or [])
    return dict(result.evidence)
