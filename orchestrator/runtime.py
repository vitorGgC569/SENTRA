"""Operational integration: persistent candidate workspace -> verified handoff.

The engine integrates task patches only into a run-owned workspace. Publication
into the user's checkout is a separate explicit operator command.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from repository.policy import PROTECTED_COMPONENTS
from workspace.patch_manager import PatchManager
from workspace.sandbox import copy_sources, diff_files, fingerprint, source_files

from .engine import OMAEngine
from .models import Candidate, TaskStatus
from .persistence import PersistenceStore
from .verification import CandidateVerifier


def validation_policy(options):
    return {"commands": options.get("validation_commands", ["[[TEST|all]]"]),
            "profiles": options.get("command_profiles") or {},
            "timeout": options.get("test_timeout", 120),
            "allowed_patch_paths": options.get("allowed_patch_paths")}


class RunLock:
    """OS lock released on process death; the lock file itself is not a busy flag."""
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        if self.path.is_symlink():
            raise ValueError("lock cannot be a symlink")
        self.handle = self.path.open("a+b")
        if os.fstat(self.handle.fileno()).st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError("another OMA operation holds this workspace lock")
        return self

    def __exit__(self, *_):
        if os.name == "nt":
            import msvcrt
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        self.handle.close()


class IntegratedRun:
    def __init__(self, workspace: Path, run_id: str, objective: str, router, *, resume=False, **engine_options):
        self.source = Path(workspace).resolve(strict=True)
        self.store = PersistenceStore(run_id, self.source / "runs")
        self.run_id, self.objective, self.router = run_id, objective, router
        self.resume, self.options = resume, engine_options
        self.baseline = self.store.run_dir / "baseline"
        self.manifest_file = self.store.run_dir / "snapshot.json"
        self.engine = None

    def _checkpoint(self, packages):
        patch = diff_files(self.before, source_files(self.work))
        tasks = [t.to_dict() for t in self.engine.task_queue._all_tasks.values()]
        completed = {p.task_id for p in packages}
        for task in tasks:
            if task["id"] in completed:
                task["status"] = "COMPLETED"
        self.store._atomic_write_json(self.store.run_dir / "checkpoint.json", {
            "base_hash": self.base_hash, "candidate_hash": fingerprint(source_files(self.work)),
            "patch": patch, "packages": [p.to_dict() for p in packages], "tasks": tasks})

    async def run(self):
        # Different Runs never mutate the user's checkout: each owns a baseline
        # and candidate workspace. Serialize only duplicate execution of the
        # SAME Run here; cross-Run publication remains guarded by the project
        # promotion lock in promote_candidate().
        with RunLock(self.store.run_dir / ".run.lock"):
            return await self._run_locked()

    async def _run_locked(self):
        from workspace.docker_runner import prepare_execution
        self.options["execution"] = await prepare_execution(self.options.get("execution"))
        snapshot = self.store._load_json(self.manifest_file, {})
        if snapshot and not self.resume:
            raise ValueError("run already exists; use --resume with the same --job-id")
        if self.resume and not snapshot:
            raise ValueError("no resumable snapshot for this run")
        if snapshot:
            if snapshot["objective"] != self.objective or snapshot["workspace"] != str(self.source):
                raise ValueError("resume objective/workspace mismatch")
            saved_project = snapshot.get("chat_project")
            requested_project = self.options.get("chat_project")
            if requested_project in (None, ""):
                self.options["chat_project"] = saved_project
            elif requested_project != saved_project:
                raise ValueError(
                    "resume chat project differs from snapshot; omit --chat-project "
                    "to reuse the recorded Project"
                )
            if snapshot.get("execution", {"backend": "host"}) != self.options["execution"]:
                raise ValueError("resume execution/image differs from snapshot; use the recorded image or create a new run")
            if snapshot.get("validation_policy", validation_policy(self.options)) != validation_policy(self.options):
                raise ValueError("resume validation policy differs from the recorded run")
            self.before = source_files(self.baseline)
            self.base_hash = fingerprint(self.before)
            if self.base_hash != snapshot["base_hash"]:
                raise ValueError("saved baseline was modified; refuse resume")
            handoff = self.store._load_json(self.store.run_dir / "handoff.json", {})
            if handoff.get("status") in {"CANDIDATE_READY", "APPLIED"}:
                return handoff
        else:
            self.before = copy_sources(self.source, self.baseline)
            self.base_hash = fingerprint(self.before)
            self.store._atomic_write_json(self.manifest_file, {
                "objective": self.objective, "workspace": str(self.source), "base_hash": self.base_hash,
                "created_at": time.time(), "execution": self.options["execution"],
                "chat_project": self.options.get("chat_project"),
                "validation_policy": validation_policy(self.options)})

        # Every recovery reconstructs from the last atomic checkpoint. Partial
        # application in a prior attempt is preserved as evidence, never trusted.
        self.work = self.store.run_dir / ("work-" + uuid.uuid4().hex[:12])
        copy_sources(self.baseline, self.work)
        checkpoint = self.store._load_json(self.store.run_dir / "checkpoint.json", {})
        if checkpoint:
            if checkpoint["base_hash"] != self.base_hash:
                raise ValueError("checkpoint baseline mismatch")
            if checkpoint["patch"]:
                applied = PatchManager.apply_patch(self.work, checkpoint["patch"])
                if not applied["success"]:
                    raise ValueError("checkpoint patch cannot be reconstructed")
            if fingerprint(source_files(self.work)) != checkpoint["candidate_hash"]:
                raise ValueError("checkpoint hash mismatch")
            # Merge latest failed/interrupted task status, but committed packages win.
            tasks = {t["id"]: t for t in checkpoint["tasks"]}
            tasks.update({t.id: t.to_dict() for t in self.store.load_tasks()})
            for p in checkpoint["packages"]:
                tasks[p["task_id"]]["status"] = "COMPLETED"
            self.store._atomic_write_json(self.store.tasks_file, list(tasks.values()))
            self.store._atomic_write_json(self.store.run_dir / "packages.json", checkpoint["packages"])
        if self.resume:
            tasks = self.store.load_tasks()
            for t in tasks:
                if t.status == TaskStatus.CANCELLED:
                    t.status = TaskStatus.PENDING  # explicit resume only; budget is NOT reset
            self.store.save_tasks(tasks)

        owned_context = None
        if (
            self.options.get("fixed_conversations")
            and self.options.get("shared_context_bridge") is None
        ):
            from sentra_mcp.services.context import ContextBusService
            from .shared_context import ContextBusSharedContextBridge

            owned_context = ContextBusService(self.source / ".sentra")
            self.options["shared_context_bridge"] = ContextBusSharedContextBridge(
                owned_context,
                owner=f"oma:{self.run_id}",
            )

        owned_resource_leases = None
        if self.options.get("resource_lease_manager") is None:
            from .durable_resources import DurableResourceLeaseManager

            owned_resource_leases = DurableResourceLeaseManager(
                self.source / ".sentra",
                workspace=self.source,
                logical_run_id=self.run_id,
            )
            self.options["resource_lease_manager"] = owned_resource_leases

        if self.options.get("program_memory") is None:
            from .program_memory import ProgramMemory

            # Project memory is runtime state, not product source. Keeping it
            # under .sentra prevents memory writes from contaminating candidate
            # diffs or invalidating source fingerprints.
            self.options["program_memory"] = ProgramMemory(self.source / ".sentra")

        self.engine = OMAEngine(self.run_id, self.objective, self.work, self.router,
                                persistence_base=self.source / "runs", checkpoint_callback=self._checkpoint,
                                **self.options)
        try:
            result = await self.engine.run(resume=self.resume)
        finally:
            if owned_context is not None:
                owned_context.close()
            if owned_resource_leases is not None:
                owned_resource_leases.close()
        patch = diff_files(self.before, source_files(self.work))
        patch_path = self.store.run_dir / "candidate.patch"
        patch_path.write_text(patch, encoding="utf-8", newline="\n")
        final_evidence = None
        status = result["status"]
        if status == "COMPLETED":
            candidate = Candidate(task_id="INTEGRATION", candidate_id="integration-" + self.run_id, patch=patch)
            verifier = CandidateVerifier(self.baseline, self.engine.validation_commands,
                                         self.options.get("command_profiles"), self.options.get("test_timeout",120),
                                         self.options["execution"], self.options.get("allowed_patch_paths"))
            final_evidence = await verifier.verify(candidate)
            self.store._atomic_write_json(self.store.run_dir / "integration-tests.json", final_evidence)
            status = "CANDIDATE_READY" if final_evidence["all_passed"] else "FAILED"
        after = source_files(self.work)
        protected = sorted(set(self.before.keys() | after.keys()) & PROTECTED_COMPONENTS)
        protected = [name for name in protected if self.before.get(name) != after.get(name)]
        handoff = {**result, "schema_version": 1, "status": status,
                   "workspace": str(self.source), "candidate_workspace": str(self.work),
                   "base_hash": self.base_hash, "candidate_hash": fingerprint(source_files(self.work)),
                   "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(), "patch_path": str(patch_path),
                   "integration_tests": final_evidence, "protected_changes": protected,
                   "requires_external_promotion": True,
                   "source_unchanged": fingerprint(source_files(self.source)) == self.base_hash,
                   "approved_packages": [p.to_dict() for p in self.engine.completed_packages],
                   "conversation_events": [e.to_dict() for e in self.store.load_events()
                                           if getattr(e.event_type, "value", e.event_type) == "MODEL_RESPONSE"
                                           and e.payload.get("conversation")],
                   "handoff_path": str(self.store.run_dir / "handoff.json"),
                   "execution": self.options["execution"],
                   "validation_policy": validation_policy(self.options),
                   "limitations": [("Docker restricts execution; it is not a VM or proof against kernel exploits."
                                     if self.options["execution"]["backend"] == "docker" else
                                     "Filesystem copy is not an OS sandbox; execute only trusted code."),
                                   "Validator consensus is not proof of correctness.",
                                   "No automatic delivery into the central AI chat; open this handoff explicitly."]}
        self.store._atomic_write_json(self.store.run_dir / "handoff.json", handoff)
        summary = [f"# OMA — {self.run_id}", "", f"Status: {status}", f"Objetivo: {self.objective}", "",
                   f"Tarefas: {result['completed_tasks']}/{result['total_tasks']}",
                   f"Hash do patch: {handoff['patch_sha256']}",
                   f"Código candidato: {self.work}", f"Contexto completo: {handoff['handoff_path']}", "",
                   "## Pacotes aprovados", "", result.get("final_synthesis") or "Nenhum.", "",
                   "## Pendências e limites", "", *result.get("errors", []), *handoff["limitations"]]
        (self.store.run_dir / "handoff.md").write_text("\n".join(summary)+"\n", encoding="utf-8")
        return handoff


async def promote_candidate(workspace, run_id, *, allow_protected=False, commands=None, profiles=None, timeout=120,
                            execution=None, allowed_patch_paths=None):
    """Separate operator action; never callable through a model directive."""
    root = Path(workspace).resolve(strict=True)
    store = PersistenceStore(run_id, root / "runs")
    with RunLock(store.run_dir.parent / ".workspace.lock"):
        handoff = store._load_json(store.run_dir / "handoff.json", {})
        if handoff.get("status") != "CANDIDATE_READY":
            raise ValueError("run has no verified candidate ready for promotion")
        from workspace.docker_runner import prepare_execution
        execution = await prepare_execution(execution)
        if handoff.get("execution", {"backend": "host"}) != execution:
            raise ValueError("promotion must use the same execution backend and image as the verified run")
        policy = validation_policy({"validation_commands": commands if commands is not None else ["[[TEST|all]]"],
                                    "command_profiles": profiles, "test_timeout": timeout,
                                    "allowed_patch_paths": allowed_patch_paths})
        if handoff.get("validation_policy", policy) != policy:
            raise ValueError("promotion must use the recorded validation policy")
        if handoff["protected_changes"] and not allow_protected:
            raise ValueError("protected changes require explicit --allow-protected approval")
        current_base_hash = fingerprint(source_files(root))
        rebased = current_base_hash != handoff["base_hash"]
        if rebased:
            integration_evidence = dict(handoff.get("integration_tests") or {})
            touched_base_hashes = dict(integration_evidence.get("touched_base_hashes") or {})
            current_files = source_files(root)
            conflicts = []
            for path, expected_hash in touched_base_hashes.items():
                current = current_files.get(path)
                current_hash = (
                    hashlib.sha256(current).hexdigest()
                    if current is not None
                    else None
                )
                if current_hash != expected_hash:
                    conflicts.append(path)
            if conflicts or not touched_base_hashes:
                detail = ",".join(conflicts[:20]) or "candidate scope unavailable"
                raise ValueError(
                    "STALE_BASE_CONFLICT: project changed in candidate scope: " + detail
                )
        promotion_base_hash = current_base_hash
        patch = (store.run_dir / "candidate.patch").read_bytes().decode("utf-8")
        if hashlib.sha256(patch.encode()).hexdigest() != handoff["patch_sha256"]:
            raise ValueError("candidate patch was changed after verification")
        candidate = Candidate(task_id="PROMOTION", candidate_id="promotion-"+run_id, patch=patch)
        evidence = await CandidateVerifier(root, commands, profiles, timeout, execution, allowed_patch_paths).verify(candidate)
        store._atomic_write_json(store.run_dir / "promotion-tests.json", evidence)
        if not evidence["all_passed"] or not evidence["source_unchanged"]:
            raise ValueError("promotion verification failed; checkout unchanged")
        if not rebased and evidence["candidate_hash"] != handoff["candidate_hash"]:
            raise ValueError("verified candidate hash mismatch")
        if fingerprint(source_files(root)) != promotion_base_hash:
            raise ValueError("workspace changed during promotion verification")
        from .durable_resources import DurableResourceLeaseManager
        from .integration import ProjectIntegrationCoordinator

        promotion_verifier = CandidateVerifier(
            root, commands, profiles, timeout, execution, allowed_patch_paths
        )
        lease_manager = DurableResourceLeaseManager(
            root / ".sentra",
            workspace=root,
            logical_run_id="promotion:" + run_id,
        )
        project_key = "project:" + hashlib.sha256(
            str(root).encode("utf-8")
        ).hexdigest()[:24]
        coordinator = ProjectIntegrationCoordinator(
            root,
            promotion_verifier,
            state_root=root / ".sentra",
            project_key=project_key,
            resource_lease_manager=lease_manager,
        )
        promotion_task = SimpleNamespace(
            run_id=run_id,
            id="PROMOTION",
            timeout_s=float(timeout),
            heartbeat_timeout_s=120.0,
        )

        async def apply_project_patch(patch_text):
            return (
                PatchManager.apply_patch(root, patch_text)
                if patch_text
                else {"success": True}
            )

        try:
            integration = await coordinator.integrate(
                promotion_task,
                candidate,
                evidence,
                apply_project_patch,
            )
        finally:
            lease_manager.close()
        if not integration.ok:
            raise ValueError(
                f"{integration.code}: {integration.error or 'promotion failed'}"
            )
        evidence = integration.evidence
        handoff.update(
            status="APPLIED",
            requires_external_promotion=False,
            promoted_at=time.time(),
            promotion_rebased=rebased or integration.rebased,
            promotion_base_hash=promotion_base_hash,
            promoted_candidate_hash=evidence.get("candidate_hash"),
            project_revision=integration.revision_after,
            project_revision_before=integration.revision_before,
            integration_fencing_token=integration.fencing_token,
        )
        store._atomic_write_json(store.run_dir / "handoff.json", handoff)
        return handoff
