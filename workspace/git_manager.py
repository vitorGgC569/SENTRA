from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import git
from .patch_manager import PatchManager
from .paths import iter_workspace_files, resolve_workspace_path


class GitManager:
    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path).resolve()
        self.repo: Optional[git.Repo] = None
        self._ensure_git_repo()

    def _ensure_git_repo(self) -> None:
        try:
            self.repo = git.Repo(self.repo_path, search_parent_directories=False)
        except Exception:
            self.repo = None

    async def inspect_repository(self) -> str:
        files_summary = [p.relative_to(self.repo_path).as_posix()
                         for p in iter_workspace_files(self.repo_path)]

        total_files = len(files_summary)
        snippet = "\n".join([f"- {f}" for f in files_summary[:50]])
        if total_files > 50:
            snippet += f"\n... and {total_files - 50} more files."

        return f"Total Files: {total_files}\nStructure:\n{snippet}"

    async def current_diff(self) -> str:
        from repository.git_adapter import GitAdapter
        return GitAdapter(self.repo_path).diff()

    async def apply_in_isolated_worktree(self, patches: List[str]) -> Dict[str, Any]:
        from .sandbox import WorkspaceSandbox
        sandbox = WorkspaceSandbox(self.repo_path)
        try:
            for patch in patches:
                result = PatchManager.apply_patch(sandbox.root, patch)
                if not result["success"]:
                    return result
            # Return the candidate artifact, never publish to the active checkout.
            return {"success": True, "patch": sandbox.changes(),
                    "base_hash": sandbox.base_hash,
                    "applied_files": sorted({p for patch in patches
                                             for p, _ in PatchManager.parse_patch_hunks(patch)}),
                    "error": None}
        finally:
            sandbox.close()

    async def commit_result(self, message: str = "SENTRA: round completed successfully",
                            paths: Optional[List[str]] = None) -> bool:
        if not paths:
            return False
        if self.repo:
            try:
                for path in paths:
                    resolve_workspace_path(self.repo_path, path)
                self.repo.git.add("--", *paths)
                self.repo.git.commit("--only", "-m", message, "--", *paths)
                return True
            except Exception:
                pass
        return False
