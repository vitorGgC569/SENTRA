"""Strict unified patches: validate every file before publishing any change."""
from __future__ import annotations

import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .paths import resolve_workspace_path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")
_LOCK = threading.RLock()


@dataclass
class FilePatch:
    old: str | None
    new: str | None
    hunks: List[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new or self.old or ""


def _header_path(line: str, side: str) -> str | None:
    value = line[4:].split("\t", 1)[0]
    if value == "/dev/null":
        return None
    if not value.startswith(side + "/") or not value[2:]:
        raise ValueError("patch paths must use a/ and b/ headers")
    return value[2:]


def _atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".oma-patch-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class PatchManager:
    @staticmethod
    def parse_files(diff: str) -> List[FilePatch]:
        if not diff.strip() or len(diff.encode("utf-8")) > 1_000_000:
            raise ValueError("empty or oversized patch")
        # A missing terminator on the diff itself is not a no-newline marker.
        lines = (diff if diff.endswith("\n") else diff + "\n").splitlines(keepends=True)
        files: List[FilePatch] = []
        i = 0
        while i < len(lines):
            line = lines[i].rstrip("\r\n")
            if line.startswith(("diff --git ", "index ")) or not line:
                i += 1
                continue
            if line in ("new file mode 100644", "deleted file mode 100644"):
                i += 1
                continue
            if not line.startswith("--- ") or i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                raise ValueError(f"unsupported patch header: {line[:100]}")
            patch = FilePatch(_header_path(line, "a"),
                              _header_path(lines[i + 1].rstrip("\r\n"), "b"))
            if not patch.path or (patch.old and patch.new and patch.old != patch.new):
                raise ValueError("renames and empty targets are not supported")
            i += 2
            while i < len(lines) and lines[i].startswith("@@"):
                header = _HUNK.fullmatch(lines[i].rstrip("\r\n"))
                if not header:
                    raise ValueError("invalid hunk header")
                old_left, new_left = int(header[2] or 1), int(header[4] or 1)
                patch.hunks.append(lines[i])
                i += 1
                while old_left or new_left:
                    if i >= len(lines):
                        raise ValueError("truncated hunk")
                    entry = lines[i]
                    prefix = entry[:1]
                    if prefix not in (" ", "+", "-"):
                        raise ValueError("invalid hunk body or line counts")
                    old_left -= prefix in (" ", "-")
                    new_left -= prefix in (" ", "+")
                    if old_left < 0 or new_left < 0:
                        raise ValueError("hunk line counts do not match")
                    patch.hunks.append(entry)
                    i += 1
                    if i < len(lines) and lines[i].rstrip("\r\n") == "\\ No newline at end of file":
                        patch.hunks[-1] = patch.hunks[-1].rstrip("\r\n")
                        i += 1
            if not patch.hunks:
                raise ValueError("file patch has no hunks")
            if any(existing.path == patch.path for existing in files):
                raise ValueError(f"duplicate file target: {patch.path}")
            files.append(patch)
        if not files:
            raise ValueError("no file patches")
        return files

    @staticmethod
    def parse_patch_hunks(diff_str: str) -> List[Tuple[str, List[str]]]:
        return [(p.path, p.hunks) for p in PatchManager.parse_files(diff_str)]

    @staticmethod
    def check_applies(repo_root: Path, patch_text: str) -> None:
        """Dry-run: raises ValueError if the patch would not apply cleanly to
        the CURRENT files (overlap, context mismatch, unreadable target).
        Parse-level validity is necessary but not sufficient — this catches
        well-formed diffs that do not fit, BEFORE validator budget is spent."""
        root = Path(repo_root).resolve()
        for fp in PatchManager.parse_files(patch_text):
            target = resolve_workspace_path(root, fp.path)
            if not target.is_file():
                bad = [ln for hunk in [fp.hunks] for ln in hunk
                       if ln[:1] in (" ", "-") and not ln.startswith("@@")]
                if bad:
                    raise ValueError(
                        f"{fp.path}: new file must use '--- /dev/null' with pure-addition "
                        f"hunks; found context/removal line {bad[0][:60]!r}")
            try:
                existing = (target.read_text(encoding="utf-8", errors="replace")
                            .splitlines(keepends=True) if target.is_file() else [])
            except OSError as exc:
                raise ValueError(f"unreadable target {fp.path}: {exc}")
            try:
                PatchManager._apply_hunks(existing, fp.hunks)
            except ValueError as exc:
                raise ValueError(f"{fp.path}: {exc}")

    @staticmethod
    def _apply_hunks(existing: List[str], hunks: List[str]) -> List[str]:
        result: List[str] = []
        old_idx = 0
        for line in hunks:
            if line.startswith("@@"):
                h = _HUNK.fullmatch(line.rstrip("\r\n"))
                if not h:
                    raise ValueError("invalid hunk header")
                count = int(h[2] or 1)
                target = int(h[1]) - (1 if count else 0)
                if target < old_idx or target > len(existing):
                    raise ValueError("hunk position outside file or overlapping")
                result.extend(existing[old_idx:target])
                old_idx = target
                new_count = int(h[4] or 1)
                new_target = int(h[3]) - (1 if new_count else 0)
                if new_target != len(result):
                    raise ValueError("new hunk position inconsistent with prior edits")
                continue
            payload = line[1:]
            if line[0] in (" ", "-"):
                if old_idx >= len(existing):
                    raise ValueError("hunk consumes past end of file")
                original = existing[old_idx]
                if (original.rstrip("\r\n") != payload.rstrip("\r\n")
                        or original.endswith("\n") != payload.endswith("\n")):
                    raise ValueError(f"hunk context mismatch at line {old_idx + 1}")
                if line[0] == " ":
                    result.append(original)
                old_idx += 1
            elif line[0] == "+":
                result.append(payload.replace("\r\n", "\n"))
            else:
                raise ValueError("invalid hunk entry")
        result.extend(existing[old_idx:])
        return result

    @staticmethod
    def apply_patch(repo_root: Path, patch_text: str) -> Dict[str, Any]:
        with _LOCK:
            originals: Dict[Path, bytes | None] = {}
            proposed: Dict[Path, bytes | None] = {}
            modes: Dict[Path, int] = {}
            written: List[Path] = []
            created_dirs: List[Path] = []
            try:
                root = Path(repo_root).resolve(strict=True)
                parsed = PatchManager.parse_files(patch_text)
                for patch in parsed:
                    target = resolve_workspace_path(root, patch.path)
                    if target in proposed:
                        raise ValueError("aliased or case-folded duplicate patch target")
                    if patch.old is None and target.exists():
                        raise ValueError(f"create target already exists: {patch.path}")
                    if patch.old is not None and not target.is_file():
                        raise ValueError(f"patch source missing: {patch.path}")
                    before = target.read_bytes() if target.exists() else None
                    originals[target] = before
                    if before is not None:
                        modes[target] = target.stat().st_mode
                    content = (before or b"").decode("utf-8")
                    after = "".join(PatchManager._apply_hunks(content.splitlines(keepends=True), patch.hunks))
                    if patch.new is None and after:
                        raise ValueError("deletion patch leaves content behind")
                    proposed[target] = after.encode("utf-8") if patch.new else None
                # All context/path/count checks finish before the first mutation.
                for target, after in proposed.items():
                    resolve_workspace_path(root, target.relative_to(root).as_posix())
                    if (target.read_bytes() if target.exists() else None) != originals[target]:
                        raise ValueError("workspace changed during patch preparation")
                    missing = target.parent
                    parents = []
                    while not missing.exists() and missing != root:
                        parents.append(missing)
                        missing = missing.parent
                    created_dirs.extend(reversed(parents))
                    written.append(target)
                    if after is None:
                        target.unlink()
                    else:
                        _atomic_write(target, after, modes.get(target))
                return {"success": True, "applied_files": [p.path for p in parsed], "error": None}
            except Exception as exc:
                rollback_errors = []
                for target in reversed(written):
                    try:
                        before = originals[target]
                        if before is None:
                            target.unlink(missing_ok=True)
                        else:
                            _atomic_write(target, before, modes.get(target))
                    except Exception as rollback_exc:
                        rollback_errors.append(str(rollback_exc))
                for directory in reversed(created_dirs):
                    try:
                        directory.rmdir()  # Only empty directories created here.
                    except OSError:
                        pass
                error = f"Patch application failed: {exc}"
                if rollback_errors:
                    error += f"; ROLLBACK_FAILED: {rollback_errors}"
                return {"success": False, "applied_files": [], "error": error}
