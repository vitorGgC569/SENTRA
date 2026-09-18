"""Scoped Git operations: inspection never initializes repositories or exposes secrets."""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Sequence

from workspace.paths import is_private_path, resolve_workspace_path


class GitAdapter:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self._repo = None
        try:
            import git
            repo = git.Repo(self.repo_root, search_parent_directories=False)
            if Path(repo.working_tree_dir).resolve() == self.repo_root:
                self._repo = repo
        except Exception:
            pass

    def _files(self):
        if not self._repo:
            return []
        raw = self._repo.git.ls_files("-z", "--cached", "--others", "--exclude-standard")
        return [p for p in dict.fromkeys(raw.split("\x00")) if p and not is_private_path(Path(p))]

    def status(self) -> str:
        if not self._repo:
            # Neutro (sem prefixo ERROR): sandboxes excluem .git por desenho
            # (EXCLUDED_DIRS), então ausência de repo não é falha operacional.
            # Validadores seguem com evidência R/T/TEST; mutações (branch/
            # checkpoint) continuam recusando sem repo.
            return "NO_GIT_REPO: directory is not a git repository"
        try:
            rows = []
            for path in self._files():
                resolve_workspace_path(self.repo_root, path)
                row = self._repo.git.status("--short", "--", path)
                if row:
                    rows.append(row)
                if len(rows) >= 300:
                    rows.append("TRUNCATED: narrow repository scope")
                    break
            return "\n".join(rows)
        except Exception as exc:
            return f"ERROR: git status: {exc}"

    def diff(self, path: str = "") -> str:
        if not self._repo:
            return "NO_GIT_REPO: directory is not a git repository"
        try:
            paths = [path] if path else self._files()
            untracked = set(self._repo.untracked_files)
            pieces = []
            size = 0
            for item in paths:
                target = resolve_workspace_path(self.repo_root, item)
                if item in untracked and target.is_file():
                    from .registry import read_text
                    try:
                        text = read_text(target)
                    except (ValueError, UnicodeError):
                        continue
                    lines = difflib.unified_diff([], text.splitlines(keepends=True),
                                                fromfile="/dev/null", tofile=f"b/{item}")
                    piece = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                                    for line in lines)
                else:
                    piece = self._repo.git.diff("--no-ext-diff", "--no-textconv", "--", item)
                    piece += "\n" + self._repo.git.diff("--cached", "--no-ext-diff", "--no-textconv", "--", item)
                pieces.append(piece)
                size += len(piece)
                if size >= 900_000:
                    pieces.append("TRUNCATED: request DIFF with a specific file")
                    break
            return "\n".join(pieces).strip()
        except Exception as exc:
            return f"ERROR: git diff: {exc}"

    def branch(self, name: str) -> str:
        if not self._repo:
            return "ERROR: git repository unavailable"
        try:
            self._repo.git.check_ref_format("--branch", name)
            self._repo.git.checkout("-b", name)
            return f"branched to {name}"
        except Exception as exc:
            return f"ERROR: git branch: {exc}"

    def checkpoint(self, message: str, paths: Sequence[str] = ()) -> str:
        if not self._repo:
            return "ERROR: git repository unavailable"
        if not paths:
            return "ERROR: checkpoint requires files owned by a committed session transaction"
        try:
            for path in paths:
                resolve_workspace_path(self.repo_root, path)
            self._repo.git.add("--", *paths)
            # --only excludes unrelated files already staged by the user.
            self._repo.git.commit("--only", "-m", message, "--", *paths)
            return f"checkpoint: {self._repo.head.commit.hexsha}"
        except Exception as exc:
            return f"ERROR: git checkpoint: {exc}"
