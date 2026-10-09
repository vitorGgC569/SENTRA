from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

from orchestrator.integration import ProjectIntegrationCoordinator
from orchestrator.models import Candidate
from workspace.patch_manager import PatchManager
from workspace.sandbox import WorkspaceSandbox, fingerprint, source_files


class FakeVerifier:
    def __init__(self, root):
        self.root = root

    async def verify(self, candidate):
        sandbox = WorkspaceSandbox(self.root)
        try:
            base_hash = sandbox.base_hash
            touched = [
                item.path
                for item in PatchManager.parse_files(candidate.patch)
            ]
            touched_base_hashes = {
                path: (
                    hashlib.sha256(sandbox.before[path]).hexdigest()
                    if path in sandbox.before
                    else None
                )
                for path in touched
            }
            result = PatchManager.apply_patch(sandbox.root, candidate.patch)
            assert result["success"] is True
            return {
                "candidate_id": candidate.candidate_id,
                "task_id": candidate.task_id,
                "base_hash": base_hash,
                "candidate_hash": fingerprint(source_files(sandbox.root)),
                "patch_hash": hashlib.sha256(
                    candidate.patch.encode("utf-8")
                ).hexdigest(),
                "touched_files": touched,
                "touched_base_hashes": touched_base_hashes,
                "all_passed": True,
                "source_unchanged": True,
                "checks_ran": 1,
                "failed_commands": [],
            }
        finally:
            sandbox.close()


def _task():
    return SimpleNamespace(
        id="T-1",
        run_id="run-1",
        timeout_s=30.0,
        heartbeat_timeout_s=30.0,
    )


def _candidate():
    return Candidate(
        candidate_id="cand-1",
        task_id="T-1",
        run_id="run-1",
        patch=(
            "--- a/a.txt\n"
            "+++ b/a.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        ),
        summary="change a only",
    )


def _apply(root):
    async def inner(patch):
        return PatchManager.apply_patch(root, patch) if patch else {"success": True}
    return inner


def test_coordinator_rebases_unrelated_change_without_model_retry(tmp_path):
    root = tmp_path / "project"
    state = tmp_path / "state"
    root.mkdir()
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    (root / "b.txt").write_text("zero\n", encoding="utf-8")
    verifier = FakeVerifier(root)
    candidate = _candidate()
    evidence = asyncio.run(verifier.verify(candidate))

    (root / "b.txt").write_text("one\n", encoding="utf-8")
    coordinator = ProjectIntegrationCoordinator(
        root,
        verifier,
        state_root=state,
        project_key="project:test",
    )
    result = asyncio.run(
        coordinator.integrate(_task(), candidate, evidence, _apply(root))
    )

    assert result.ok is True
    assert result.rebased is True
    assert result.revision_before == 0
    assert result.revision_after == 1
    assert (root / "a.txt").read_text(encoding="utf-8") == "new\n"
    assert (root / "b.txt").read_text(encoding="utf-8") == "one\n"
    latest = coordinator.revisions.latest("project:test")
    assert latest["revision"] == 1
    assert latest["candidate_id"] == "cand-1"
    assert latest["touched_files"] == ["a.txt"]


def test_coordinator_rejects_changed_candidate_scope_without_applying(tmp_path):
    root = tmp_path / "project"
    state = tmp_path / "state"
    root.mkdir()
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    verifier = FakeVerifier(root)
    candidate = _candidate()
    evidence = asyncio.run(verifier.verify(candidate))
    (root / "a.txt").write_text("external\n", encoding="utf-8")

    called = False

    async def apply_patch(_patch):
        nonlocal called
        called = True
        return {"success": True}

    coordinator = ProjectIntegrationCoordinator(
        root,
        verifier,
        state_root=state,
        project_key="project:test",
    )
    result = asyncio.run(
        coordinator.integrate(_task(), candidate, evidence, apply_patch)
    )

    assert result.ok is False
    assert result.code == "STALE_BASE_CONFLICT"
    assert result.conflicts == ["a.txt"]
    assert called is False
    assert (root / "a.txt").read_text(encoding="utf-8") == "external\n"


def test_revision_store_records_monotonic_candidate_commits(tmp_path):
    root = tmp_path / "project"
    state = tmp_path / "state"
    root.mkdir()
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    verifier = FakeVerifier(root)
    coordinator = ProjectIntegrationCoordinator(
        root,
        verifier,
        state_root=state,
        project_key="project:test",
    )
    candidate = _candidate()
    evidence = asyncio.run(verifier.verify(candidate))
    result = asyncio.run(
        coordinator.integrate(_task(), candidate, evidence, _apply(root))
    )

    assert result.revision_after == 1
    latest = coordinator.revisions.latest("project:test")
    assert latest["revision"] == 1
    assert latest["kind"] == "CANDIDATE_COMMIT"
    assert latest["workspace_hash"] == fingerprint(source_files(root))


class LostLeaseManager:
    def __init__(self):
        self.released = False

    def acquire(self, task, resources):
        return [{
            "resource_key": "project-integration",
            "logical_resource": "project:integration",
            "fencing_token": 7,
        }]

    def renew(self, leases, task):
        raise RuntimeError("stale fencing token")

    def release(self, leases):
        self.released = True


def test_coordinator_refuses_write_after_fence_is_lost(tmp_path):
    root = tmp_path / "project"
    state = tmp_path / "state"
    root.mkdir()
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    verifier = FakeVerifier(root)
    candidate = _candidate()
    evidence = asyncio.run(verifier.verify(candidate))
    leases = LostLeaseManager()
    called = False

    async def apply_patch(_patch):
        nonlocal called
        called = True
        return {"success": True}

    coordinator = ProjectIntegrationCoordinator(
        root,
        verifier,
        state_root=state,
        project_key="project:test",
        resource_lease_manager=leases,
    )
    result = asyncio.run(
        coordinator.integrate(_task(), candidate, evidence, apply_patch)
    )

    assert result.ok is False
    assert result.code == "STALE_FENCE"
    assert called is False
    assert leases.released is True
    assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
