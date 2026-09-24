"""Deterministic evidence for the exact patched candidate, before publication."""
from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from pathlib import Path

from repository.gateway import CommandGateway
from .version_guard import check_patch
from .failure_summary import summarize_test_results
from workspace.command_runner import CommandRunner
from workspace.docker_runner import create_runner, settings
from workspace.sandbox import WorkspaceSandbox, fingerprint, source_files
from workspace.patch_manager import PatchManager
from workspace.paths import resolve_workspace_path


class CandidateVerifier:
    def __init__(self, workspace: Path, commands=None, profiles=None, timeout: float = 120, execution=None,
                 allowed_patch_paths=None):
        self.workspace = Path(workspace).resolve()
        # Mandatory local validation cannot be removed by a candidate response.
        self.commands = list(commands) if commands is not None else ["[[TEST|all]]"]
        if not self.commands or timeout <= 0:
            raise ValueError("verification requires commands and a positive timeout")
        self.profiles = profiles
        self.timeout = timeout
        self.execution = settings(execution)
        self.allowed_patch_paths = (None if allowed_patch_paths is None else
                                    {resolve_workspace_path(self.workspace, path).relative_to(self.workspace).as_posix()
                                     for path in allowed_patch_paths})

    @contextmanager
    def reviewed_snapshot(self, candidate, evidence):
        """Reopen ONLY the exact tested version for read-only final review."""
        sandbox = WorkspaceSandbox(self.workspace)
        try:
            if (sandbox.base_hash != evidence.get("base_hash") or
                    hashlib.sha256(candidate.patch.encode()).hexdigest() != evidence.get("patch_hash")):
                raise ValueError("REVIEW_SNAPSHOT_MISMATCH: baseline/patch changed")
            if candidate.patch:
                applied = PatchManager.apply_patch(sandbox.root, candidate.patch)
                if not applied["success"]:
                    raise ValueError("REVIEW_SNAPSHOT_MISMATCH: patch could not be restored")
            if fingerprint(source_files(sandbox.root)) != evidence.get("candidate_hash"):
                raise ValueError("REVIEW_SNAPSHOT_MISMATCH: candidate changed")
            yield sandbox.root
            if fingerprint(source_files(sandbox.root)) != evidence["candidate_hash"]:
                raise ValueError("REVIEW_MODIFIED_CANDIDATE")
        finally:
            sandbox.close()

    async def verify(self, candidate, inspect=None, event_sink=None) -> dict:
        started = time.monotonic()
        sandbox = WorkspaceSandbox(self.workspace)
        try:
            gateway = CommandGateway(sandbox.root, event_sink=event_sink)
            session = gateway.open_session()
            applied = "NO_PATCH"
            dry_run = {"valid": True, "files": [], "python_files": [], "checks": []}
            if candidate.patch:
                try:
                    dry_run = PatchManager.dry_run_validate(
                        sandbox.root, candidate.patch
                    )
                    paths = {resolve_workspace_path(sandbox.root, item.path).relative_to(sandbox.root).as_posix()
                             for item in PatchManager.parse_files(candidate.patch)}
                    if self.allowed_patch_paths is not None and paths - self.allowed_patch_paths:
                        raise ValueError("PATCH_SCOPE_DENIED: " + ', '.join(sorted(paths - self.allowed_patch_paths)))
                    alias = gateway.stage_patch(session, candidate.patch)
                    applied = await gateway.execute(session, f"[[PATCH|{alias}]]", agent_id="verifier",
                                                    task_id=candidate.task_id, role="executor")
                except (ValueError, PermissionError) as exc:
                    applied = str(exc)
            results = []
            if candidate.patch and not applied.startswith("PATCH OK"):
                results.append(CommandRunner._result("APPLY_CANDIDATE", False, -1, stderr=applied))
            else:
                commands = list(dict.fromkeys(self.commands + candidate.validation_commands))
                runner = create_runner(sandbox.root, profiles=self.profiles, execution=self.execution)
                candidate_hash = fingerprint(source_files(sandbox.root))
                for command in commands:
                    results.append(await runner.run_command(command, timeout=self.timeout))
                # A test must not silently rewrite the code whose hash we report.
                if fingerprint(source_files(sandbox.root)) != candidate_hash:
                    results.append(CommandRunner._result("CANDIDATE_INTEGRITY", False, -1,
                                                         stderr="tests modified candidate source"))
            after_hash = fingerprint(source_files(sandbox.root))
            try:
                base_texts = {p: b.decode("utf-8", errors="replace")
                              for p, b in sandbox.before.items()}
                version_check = check_patch(base_texts, candidate.patch or "")
            except Exception as exc:
                version_check = {"changed": [], "upgrades": [], "downgrades": [],
                                 "added": [], "error": str(exc)[:200]}
            # Recusados pela política (refused=True) NÃO são evidência de falha:
            # saem das listas de passou/falhou e vão para refused_commands.
            ran_results = [r for r in results if not r.get("refused")]
            refused = [r["command"] for r in results if r.get("refused")]
            evidence = {
                "candidate_id": candidate.candidate_id, "task_id": candidate.task_id,
                "patch_hash": hashlib.sha256(candidate.patch.encode("utf-8")).hexdigest(),
                "base_hash": sandbox.base_hash, "candidate_hash": after_hash,
                "all_passed": bool(ran_results) and all(r["passed"] for r in ran_results),
                "passed_commands": [r["command"] for r in ran_results if r["passed"]],
                "failed_commands": [r["command"] for r in ran_results if not r["passed"]],
                "refused_commands": refused,
                "checks_ran": len(ran_results),
                "version_check": version_check,
                "dry_run": dry_run,
                "results": ran_results, "all_results": results,
                "elapsed_s": time.monotonic() - started,
                "source_unchanged": sandbox.source_unchanged(),
                "verification_scope": ("docker_restricted_candidate" if self.execution["backend"] == "docker"
                                       else "isolated_filesystem_candidate"),
                "execution": self.execution,
            }
            evidence["failure_summary"] = summarize_test_results(evidence)
            if inspect is not None:
                evidence["_reports"] = await inspect(sandbox.root, evidence)
                if fingerprint(source_files(sandbox.root)) != after_hash:
                    evidence["all_passed"] = False
                    evidence["failed_commands"].append("VALIDATOR_MODIFIED_CANDIDATE")
            return evidence
        finally:
            sandbox.close()
