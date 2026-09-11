from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import git
from .patch_manager import PatchManager


class GitManager:
    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path).resolve()
        self.repo: Optional[git.Repo] = None
        self._ensure_git_repo()

    def _ensure_git_repo(self) -> None:
        try:
            self.repo = git.Repo(self.repo_path, search_parent_directories=True)
        except Exception:
            try:
                self.repo = git.Repo.init(self.repo_path)
            except Exception:
                self.repo = None

    async def inspect_repository(self) -> str:
        files_summary = []
        for root, dirs, files in os.walk(self.repo_path):
            # Ignore .git, node_modules, __pycache__, .venv
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv", "runs"}]
            for f in files:
                rel = Path(root, f).relative_to(self.repo_path)
                files_summary.append(str(rel))

        total_files = len(files_summary)
        snippet = "\n".join([f"- {f}" for f in files_summary[:50]])
        if total_files > 50:
            snippet += f"\n... and {total_files - 50} more files."

        return f"Total Files: {total_files}\nStructure:\n{snippet}"

    async def current_diff(self) -> str:
        if self.repo:
            try:
                diff_unstaged = self.repo.git.diff()
                diff_staged = self.repo.git.diff("--cached")
                return diff_unstaged + "\n" + diff_staged
            except Exception:
                pass
        return ""

    async def apply_in_isolated_worktree(self, patches: List[str]) -> Dict[str, Any]:
        applied = []
        for patch in patches:
            res = PatchManager.apply_patch(self.repo_path, patch)
            if not res["success"]:
                return res
            applied.extend(res.get("applied_files", []))

        return {
            "success": True,
            "applied_files": applied,
            "error": None,
        }

    async def commit_result(self, message: str = "AutonomousInfinityAI: round completed successfully") -> bool:
        if self.repo:
            try:
                self.repo.git.add(A=True)
                self.repo.index.commit(message)
                return True
            except Exception:
                pass
        return False
