"""Isolated source snapshots, exact diffs and stale-base detection.

This is filesystem isolation, not an operating-system security boundary for
executing arbitrary Python. Process execution is controlled by CommandRunner.
"""
from __future__ import annotations

import difflib
import hashlib
import shutil
import tempfile
from pathlib import Path

from .paths import iter_workspace_files, resolve_workspace_path

MAX_SNAPSHOT_BYTES = 100_000_000


def source_files(root: Path) -> dict[str, bytes]:
    files = {}
    size = 0
    for path in iter_workspace_files(root, max_files=10001):
        if len(files) == 10000:
            raise ValueError("snapshot exceeds 10000 file limit; narrow the workspace")
        size += path.stat().st_size
        if size > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot exceeds 100 MB limit; narrow the workspace")
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def fingerprint(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode("utf-8") + b"\x00" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def diff_files(before: dict[str, bytes], after: dict[str, bytes]) -> str:
    pieces = []
    for name in sorted(before.keys() | after.keys()):
        if before.get(name) == after.get(name):
            continue
        old = before.get(name, b"").decode("utf-8")
        new = after.get(name, b"").decode("utf-8")
        for line in difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile=f"a/{name}" if name in before else "/dev/null",
                                        tofile=f"b/{name}" if name in after else "/dev/null"):
            pieces.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(pieces)


def copy_sources(source: Path, destination: Path) -> dict[str, bytes]:
    source = source.resolve(strict=True)
    if destination.exists():
        raise ValueError("snapshot destination must not already exist")
    files = source_files(source)
    destination.mkdir(parents=True)
    for name, content in files.items():
        target = resolve_workspace_path(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        shutil.copymode(source / name, target)
    if fingerprint(source_files(source)) != fingerprint(files):
        raise ValueError("source changed while taking snapshot; retry with a stable workspace")
    return files


class WorkspaceSandbox:
    def __init__(self, source: Path):
        self.source = Path(source).resolve(strict=True)
        self.container = Path(tempfile.mkdtemp(prefix="oma-sandbox-" )).resolve()
        self.root = self.container / "repo"
        self.before = {}
        try:
            self.before = copy_sources(self.source, self.root)
        except BaseException:
            self.close()
            raise
        self.base_hash = fingerprint(self.before)

    def changes(self) -> str:
        return diff_files(self.before, source_files(self.root))

    def source_unchanged(self) -> bool:
        return fingerprint(source_files(self.source)) == self.base_hash

    def reset(self) -> None:
        current = source_files(self.root)
        for name in current.keys() - self.before.keys():
            resolve_workspace_path(self.root, name).unlink()
        for name, content in self.before.items():
            target = resolve_workspace_path(self.root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def close(self) -> None:
        # Validate the exact task-created temporary directory before recursive cleanup.
        target = self.container.resolve()
        if (target != self.container or target.parent != Path(tempfile.gettempdir()).resolve()
                or not target.name.startswith("oma-sandbox-") or target == self.source):
            raise ValueError("sandbox cleanup target failed ownership check")
        if target.exists():
            shutil.rmtree(target)
