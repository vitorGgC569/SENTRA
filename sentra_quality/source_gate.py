"""Fail-closed, READ-ONLY source provenance gate for optional third-party modules.

No vendor checkout code is ever imported or executed by this module. A passing
result confirms SOURCE provenance and tracked-file integrity at one Git
revision; it is not proof of security, license clearance, or runtime behavior.

Third-party sources in the SENTRA developer's third_party/ directory are
ignored by the product's Git repository and are NOT bundled automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Mapping
from urllib.parse import urlsplit

_NAME = re.compile(r"[a-z][a-z0-9._-]{0,79}\Z")
_REV = re.compile(r"[0-9a-f]{40}\Z")
_GIT_TIMEOUT = 25


class GateFailure(RuntimeError):
    """A vendored source cannot be trusted for activation or packaging."""


@dataclass(frozen=True, slots=True)
class ProjectPin:
    name: str
    upstream: str
    revision: str

    def __post_init__(self):
        if not isinstance(self.name, str) or not _NAME.fullmatch(self.name):
            raise GateFailure("invalid project name")
        if not isinstance(self.upstream, str):
            raise GateFailure("invalid upstream")
        url = urlsplit(self.upstream)
        if (url.scheme != "https" or url.hostname != "github.com" or url.port is not None
            or url.username or url.password or url.query or url.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", url.path)):
            raise GateFailure("only canonical HTTPS GitHub upstreams are supported")
        if not isinstance(self.revision, str) or not _REV.fullmatch(self.revision):
            raise GateFailure("invalid 40-character commit id")


@dataclass(frozen=True, slots=True)
class VerifiedSource:
    name: str
    revision: str
    upstream: str
    tracked_files: int


def _canonical_upstream(value: str) -> str:
    """Canonicalize origin, not arbitrary project display names."""
    item = value.rstrip("/")
    if item.endswith(".git"):
        item = item[:-4]
    return item.lower()


def _git(repo: Path, *args: str) -> bytes:
    env = os.environ.copy()
    # Do not allow Git's external pager or shell-like fsmonitor hooks.
    env["GIT_PAGER"] = "cat"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    call = ["git", "-c", "core.fsmonitor=false", "-c",
            "core.untrackedCache=false", "-C", str(repo), *args]
    try:
        result = subprocess.run(
            call, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=_GIT_TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateFailure("Git source inspection unavailable") from exc
    if result.returncode != 0:
        raise GateFailure(f"Git inspection failed for {repo.name} ({args[0]})")
    return result.stdout.strip()


def _contained(root: Path, candidate: Path) -> Path:
    root = root.resolve(strict=True)
    candidate = candidate.resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GateFailure("path escaped trusted third-party root") from exc
    return candidate


class SourceGate:
    def __init__(self, root: Path, manifest: Path | None = None,
                 trusted_pins: Path | None = None):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise GateFailure("third-party source root is not a directory")
        self.manifest = (
            Path(manifest).resolve(strict=True)
            if manifest is not None
            else (self.root / "SENTRA_SOURCES_MANIFEST.json")
        )
        try:
            data = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GateFailure("source manifest missing or malformed") from exc
        entries = data.get("repos") if isinstance(data, dict) else None
        if not isinstance(entries, list) or not 1 <= len(entries) <= 1024:
            raise GateFailure("invalid source manifest repos")
        self.pins: dict[str, ProjectPin] = {}
        for record in entries:
            if not isinstance(record, dict) or record.get("status") != "ok":
                raise GateFailure("source not successfully cloned")
            pin = ProjectPin(record.get("name"), record.get("upstream"),
                             record.get("revision"))
            if pin.name in self.pins:
                raise GateFailure("duplicate project in source manifest")
            self.pins[pin.name] = pin
        # In production this lock must be tracked/reviewed with SENTRA itself,
        # independently of the ignored/mutable third_party manifest.
        if trusted_pins is not None:
            try:
                locked = json.loads(Path(trusted_pins).read_text(encoding="utf-8"))
                approvals = locked["repos"]
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise GateFailure("independent trusted pin lock missing or malformed") from exc
            if not isinstance(approvals, list) or len(approvals) != len(self.pins):
                raise GateFailure("trusted pin count mismatch")
            approved: dict[str, ProjectPin] = {}
            for entry in approvals:
                if not isinstance(entry, dict):
                    raise GateFailure("invalid trusted source pin")
                candidate = ProjectPin(entry.get("name"), entry.get("upstream"),
                                       entry.get("revision"))
                if candidate.name in approved:
                    raise GateFailure("duplicate trusted source pin")
                approved[candidate.name] = candidate
            if approved != self.pins:
                raise GateFailure("manifest does not match independent trusted pins")

    def verify(self, name: str) -> VerifiedSource:
        pin = self.pins.get(name)
        if pin is None:
            raise GateFailure("source not explicitly pinned in manifest")
        repo = self.root / name
        try:
            repo = _contained(self.root, repo)
        except (OSError, RuntimeError) as exc:
            raise GateFailure("clone not available in trusted root") from exc
        if not repo.is_dir():
            raise GateFailure("source path is not a directory")
        if not (repo / ".git").exists():
            raise GateFailure("clone has no git metadata")
        sha = _git(repo, "rev-parse", "--verify", "HEAD").decode("ascii", errors="replace")
        if sha != pin.revision:
            raise GateFailure("source revision differs from approved manifest")
        origin = _git(repo, "remote", "get-url", "origin").decode("utf-8", errors="replace")
        if _canonical_upstream(origin) != _canonical_upstream(pin.upstream):
            raise GateFailure("Git origin differs from pinned upstream")
        dirty = _git(repo, "status", "--porcelain", "--untracked-files=no")
        if dirty:
            raise GateFailure("tracked source files were modified")
        tracked = _git(repo, "ls-files", "-z")
        paths = [p for p in tracked.split(b"\0") if p]
        if not paths:
            raise GateFailure("no source files tracked by Git")
        return VerifiedSource(pin.name, pin.revision, pin.upstream, len(paths))

    def verify_all(self) -> tuple[VerifiedSource, ...]:
        """Verify all pinned repos; never silently skip failures."""
        return tuple(self.verify(n) for n in sorted(self.pins))

    def attest_file(self, name: str, relative_path: str) -> dict[str, str]:
        """Bind a candidate code file to its pinned repository and SHA256.

        This does not activate/install a component. It is intended as the
        immutable evidence captured *before* reviewing/copying a module.
        """
        verified = self.verify(name)
        if not isinstance(relative_path, str) or "\\" in relative_path:
            raise GateFailure("candidate file must have POSIX relative path")
        pure = PurePosixPath(relative_path)
        if (not relative_path or pure.is_absolute() or ".." in pure.parts
            or "." in pure.parts or relative_path.startswith("-")):
            raise GateFailure("unsafe candidate file path")
        repo = self.root / name
        path = _contained(repo, repo.joinpath(*pure.parts))
        if not path.is_file():
            raise GateFailure("candidate is not a source file")
        # Git paths are compared against names in HEAD, not untracked files.
        tracked = _git(repo, "ls-files", "-z")
        names = {p.decode("utf-8", "surrogateescape") for p in tracked.split(b"\0") if p}
        if pure.as_posix() not in names:
            raise GateFailure("untracked source file cannot be attested")
        raw = path.read_bytes()
        return {
            "project": verified.name,
            "upstream": verified.upstream,
            "revision": verified.revision,
            "path": pure.as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
