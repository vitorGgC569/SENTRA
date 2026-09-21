"""Managed workspace/sandbox/candidate operations for SENTRA MCP."""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

from orchestrator.models import Candidate, Evidence, Finding, Severity, Task, ValidationReport
from orchestrator.quality_gate import QualityGate, QuorumPolicy
from workspace.docker_runner import create_runner
from workspace.patch_manager import PatchManager
from workspace.sandbox import WorkspaceSandbox, fingerprint, source_files

from ..audit import AuditLogger
from .filesystem import FilesystemService


class WorkspaceOpsService:
    def __init__(self, filesystem: FilesystemService, audit: AuditLogger) -> None:
        self.filesystem = filesystem
        self.audit = audit
        self.sandboxes: dict[str, dict[str, Any]] = {}

    def create_workspace(self, path: str) -> dict[str, Any]:
        return self.filesystem.create_directory(path)

    def _owned(self, sandbox_id: str, owner: str) -> dict[str, Any]:
        item = self.sandboxes.get(sandbox_id)
        if item is None:
            raise FileNotFoundError("sandbox not found")
        if item["owner"] != owner:
            raise PermissionError("sandbox belongs to another owner")
        return item

    def create_sandbox(self, source_path: str, owner: str) -> dict[str, Any]:
        if not owner.strip():
            raise ValueError("owner is required")
        _, source, rel = self.filesystem._resolve(source_path)
        if not source.is_dir():
            raise NotADirectoryError("sandbox source must be a directory")
        sandbox = WorkspaceSandbox(source)
        sandbox_id = str(uuid.uuid4())
        self.sandboxes[sandbox_id] = {
            "owner": owner,
            "sandbox": sandbox,
            "source": rel,
            "created": time.time(),
            "last_evidence": None,
        }
        self.audit.emit("sandbox.create", "ok", {"sandbox_id": sandbox_id, "owner": owner, "source": rel})
        return {"sandbox_id": sandbox_id, "owner": owner, "source": rel, "base_hash": sandbox.base_hash}

    def apply_candidate(self, sandbox_id: str, owner: str, patch: str) -> dict[str, Any]:
        item = self._owned(sandbox_id, owner)
        sandbox: WorkspaceSandbox = item["sandbox"]
        result = PatchManager.apply_patch(sandbox.root, patch)
        patch_hash = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        evidence = {
            "sandbox_id": sandbox_id,
            "patch_hash": patch_hash,
            "candidate_hash": fingerprint(source_files(sandbox.root)),
            "apply_result": result,
            "source_unchanged": sandbox.source_unchanged(),
        }
        item["last_evidence"] = evidence
        self.audit.emit("sandbox.apply_candidate", "ok", {"sandbox_id": sandbox_id, "owner": owner, "patch_hash": patch_hash})
        return evidence

    async def verify_candidate(
        self,
        sandbox_id: str,
        owner: str,
        commands: list[str] | None = None,
        timeout: float = 120,
    ) -> dict[str, Any]:
        item = self._owned(sandbox_id, owner)
        sandbox: WorkspaceSandbox = item["sandbox"]
        commands = commands or ["[[TEST|all]]"]
        if not commands or len(commands) > 16:
            raise ValueError("verification commands must contain 1..16 items")
        candidate_hash = fingerprint(source_files(sandbox.root))
        runner = create_runner(sandbox.root)
        results = []
        for command in commands:
            if not isinstance(command, str) or len(command) > 512:
                raise ValueError("invalid verification command")
            results.append(await runner.run_command(command, timeout=timeout))
        after = fingerprint(source_files(sandbox.root))
        evidence = {
            "sandbox_id": sandbox_id,
            "candidate_hash": candidate_hash,
            "post_test_hash": after,
            "source_unchanged": sandbox.source_unchanged(),
            "tests_preserved_candidate": after == candidate_hash,
            "all_passed": bool(results) and all(result.get("passed") for result in results),
            "checks_ran": len(results),
            "results": results,
            "diff": sandbox.changes(),
            "verified_at": time.time(),
        }
        if after != candidate_hash:
            evidence["all_passed"] = False
        item["last_evidence"] = evidence
        self.audit.emit("sandbox.verify", "ok" if evidence["all_passed"] else "failed", {"sandbox_id": sandbox_id, "owner": owner, "checks": len(results)})
        return evidence

    def get_evidence(self, sandbox_id: str, owner: str) -> dict[str, Any]:
        item = self._owned(sandbox_id, owner)
        return {"evidence": item.get("last_evidence"), "diff": item["sandbox"].changes()}

    def rollback(self, sandbox_id: str, owner: str) -> dict[str, Any]:
        item = self._owned(sandbox_id, owner)
        item["sandbox"].reset()
        item["last_evidence"] = None
        self.audit.emit("sandbox.rollback", "ok", {"sandbox_id": sandbox_id, "owner": owner})
        return {"sandbox_id": sandbox_id, "rolled_back": True}

    def close_sandbox(self, sandbox_id: str, owner: str) -> dict[str, Any]:
        item = self._owned(sandbox_id, owner)
        item["sandbox"].close()
        self.sandboxes.pop(sandbox_id, None)
        return {"sandbox_id": sandbox_id, "closed": True}

    @staticmethod
    def _finding(data: dict[str, Any]) -> Finding:
        return Finding(
            severity=Severity(str(data.get("severity", "MINOR")).upper()),
            category=str(data.get("category", "GENERAL")),
            description=str(data.get("description", "")),
            suggested_fix=data.get("suggested_fix"),
            file_path=data.get("file_path"),
            line_number=data.get("line_number"),
        )

    @staticmethod
    def _evidence(data: dict[str, Any]) -> Evidence:
        return Evidence(
            type=str(data.get("type", "TEST_OUTPUT")),
            description=str(data.get("description", "")),
            content=str(data.get("content", "")),
            passed=bool(data.get("passed", True)),
            metadata=dict(data.get("metadata") or {}),
        )

    def run_quality_gate(
        self,
        task_data: dict[str, Any],
        candidate_data: dict[str, Any],
        reports_data: list[dict[str, Any]],
        test_results: dict[str, Any],
        *,
        min_release_score: float = 9.5,
    ) -> dict[str, Any]:
        task = Task(**task_data)
        candidate = Candidate(**candidate_data)
        reports: list[ValidationReport] = []
        for data in reports_data:
            payload = dict(data)
            payload["findings"] = [self._finding(item) for item in data.get("findings", [])]
            payload["evidence"] = [self._evidence(item) for item in data.get("evidence", [])]
            reports.append(ValidationReport(**payload))
        gate = QualityGate(QuorumPolicy(min_release_score=min_release_score, require_explicit_scores=True))
        passed, reason, package = gate.evaluate(task, candidate, reports, test_results)
        return {
            "passed": passed,
            "reason": reason,
            "package": None if package is None else package.__dict__,
        }

    def shutdown(self) -> None:
        for sandbox_id, item in list(self.sandboxes.items()):
            try:
                item["sandbox"].close()
            except Exception:
                pass
            self.sandboxes.pop(sandbox_id, None)
