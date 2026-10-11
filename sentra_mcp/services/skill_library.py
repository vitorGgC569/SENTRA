"""Immutable, protected SKILL.md packages within the existing Control Plane.

Import is inert. Explicit WorkItem activation makes selected context readable;
it never executes a script, sets cwd or creates an authorization grant.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from contextlib import contextmanager

from sentra_core.conversations import _encode, _decode
from .plugin_bundles import _safe

MAX_FILES = 128
MAX_BYTES = 2_000_000
MAX_FILE_BYTES = 512_000
MAX_ARCHIVE = 8_000_000
_SHA = re.compile(r"^[a-f0-9]{40}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_EXTENSIONS = {".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv", ".svg"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def _metadata(text):
    # Deliberately narrow frontmatter parser: metadata is never evaluated.
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match or len(match[1]) > 8000:
        raise ValueError("bounded SKILL.md frontmatter required")
    fields = {}
    for line in match[1].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, colon, value = line.partition(":")
        if key not in {"name", "description", "version"}:
            continue  # Other upstream metadata cannot create permissions.
        if not colon or key in fields:
            raise ValueError("ambiguous skill metadata")
        fields[key] = value.strip().strip('"\'')
    if not _NAME.fullmatch(fields.get("name", "")) or not 1 <= len(fields.get("description", "")) <= 2000:
        raise ValueError("skill name and single-line description required")
    return fields


def _files(values):
    if not isinstance(values, dict) or not 1 <= len(values) <= MAX_FILES or "SKILL.md" not in values:
        raise ValueError("skill package requires SKILL.md and at most 128 files")
    total = 0
    normalized = set()
    for path, text in values.items():
        parts = _safe(path)
        if any(part.startswith(".") for part in parts) or PurePosixPath(path).suffix.lower() not in _EXTENSIONS:
            raise ValueError("private paths and unsupported skill resources refused")
        if path.casefold() in normalized or not isinstance(text, str) or "\x00" in text:
            raise ValueError("ambiguous or binary skill resource")
        normalized.add(path.casefold())
        size = len(text.encode())
        if size > MAX_FILE_BYTES:
            raise ValueError("skill resource exceeds byte limit")
        total += size
    if total > MAX_BYTES:
        raise ValueError("skill package exceeds total byte limit")
    return _metadata(values["SKILL.md"])


class SkillLibrary:
    def __init__(self, control):
        self.control = control
        self.store = control.store
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS skill_packages(
                    owner TEXT NOT NULL, workspace TEXT NOT NULL, package_id TEXT NOT NULL,
                    name TEXT NOT NULL, description TEXT NOT NULL, source TEXT NOT NULL,
                    git_sha TEXT, protected_files TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL,
                    PRIMARY KEY(owner,workspace,package_id));
                CREATE TABLE IF NOT EXISTS skill_package_activations(
                    owner TEXT NOT NULL, work_item_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    workspace TEXT NOT NULL, package_id TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(owner,work_item_id,agent_id,package_id));
            """)

    @contextmanager
    def _db(self):
        db=self.store.connect("governance")
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_files(self, owner, workspace, values, *, source, git_sha=None, expected_sha256=None):
        metadata = _files(values)
        root = str(Path(workspace).resolve(strict=True))
        if not isinstance(source, str) or not 1 <= len(source) <= 512:
            raise ValueError("bounded source provenance required")
        if git_sha is not None and not _SHA.fullmatch(git_sha):
            raise ValueError("Git source must be pinned to a full commit SHA")
        digest = _digest(values)
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("skill package checksum mismatch")
        protected = _encode(values)
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO skill_packages VALUES(?,?,?,?,?,?,?,?,0,1,?)",
                       (owner, root, digest, metadata["name"], metadata["description"],
                        source, git_sha, protected, time.time()))
        return self.info(owner, root, digest)

    def import_local(self, owner, workspace, path, *, expected_sha256=None):
        root = Path(workspace).resolve(strict=True)
        original = Path(path)
        selected = original if original.is_absolute() else root / original
        # Resolve only after checking all link components within the workspace.
        if not selected.absolute().is_relative_to(root):
            raise PermissionError("skill source outside workspace")
        for component in [selected, *selected.parents]:
            if component == root:
                break
            if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
                raise PermissionError("skill source cannot contain links")
        selected = selected.resolve(strict=True)
        if not selected.is_relative_to(root) or not selected.is_dir():
            raise PermissionError("skill source must be a workspace directory")
        values = {}
        total = 0
        # Bounded inventory; no secrets/dot directories are imported or executed.
        stack = [selected]
        entries = 0
        while stack:
            directory = stack.pop()
            for file in directory.iterdir():
                entries += 1
                if entries > 512:
                    raise ValueError("skill directory inventory exceeds bound")
                if file.is_symlink() or (hasattr(file, "is_junction") and file.is_junction()):
                    raise PermissionError("skill resource links refused")
                relative = file.relative_to(selected).as_posix()
                if any(part.startswith(".") for part in PurePosixPath(relative).parts):
                    raise ValueError("private files cannot be imported as skills")
                if file.is_dir():
                    stack.append(file)
                    continue
                if not file.is_file() or file.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError("skill resource is not a bounded regular file")
                raw = file.read_bytes()
                total += len(raw)
                if len(raw) > MAX_FILE_BYTES or total > MAX_BYTES or len(values) >= MAX_FILES:
                    raise ValueError("skill package exceeds size or file limit")
                values[relative] = raw.decode("utf-8")
        return self.import_files(owner, root, values, source="local:" + selected.relative_to(root).as_posix(),
                                 expected_sha256=expected_sha256)

    def import_git(self, owner, workspace, repository, commit_sha, subdirectory="", *, expected_sha256=None):
        """Snapshot a local Git tree by SHA. No checkout, hook, fetch or script execution."""
        if not isinstance(commit_sha, str) or not _SHA.fullmatch(commit_sha):
            raise ValueError("full 40-character Git commit SHA required")
        root = Path(workspace).resolve(strict=True)
        repo = (root / repository).resolve(strict=True)
        if not repo.is_relative_to(root) or not repo.is_dir():
            raise PermissionError("Git skill repository must be within workspace")
        prefix = subdirectory.rstrip("/")
        if prefix:
            _safe(prefix)
        def git(*args, maximum=MAX_BYTES):
            proc = subprocess.Popen(["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            try:
                raw = proc.stdout.read(maximum + 1)
                if len(raw) > maximum:
                    raise ValueError("Git output exceeds skill import bound")
                if proc.wait(timeout=15) != 0:
                    raise ValueError("Git skill snapshot unavailable")
                return raw
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()
        actual = git("rev-parse", "--verify", commit_sha + "^{commit}", maximum=100).decode().strip()
        if actual != commit_sha:
            raise ValueError("Git commit identity mismatch")
        listing = git("ls-tree", "-rz", "--full-tree", commit_sha, "--", prefix or ".", maximum=65536)
        values = {}
        total = 0
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            descriptor, filename = entry.split(b"\t", 1)
            mode, kind, blob = descriptor.decode("ascii").split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("Git links/submodules cannot be skill resources")
            path = filename.decode("utf-8")
            relative = path[len(prefix) + 1:] if prefix else path
            _safe(relative)
            raw = git("cat-file", "blob", blob, maximum=MAX_FILE_BYTES)
            total += len(raw)
            if len(values) >= MAX_FILES or total > MAX_BYTES:
                raise ValueError("Git skill package exceeds bound")
            values[relative] = raw.decode("utf-8")
        return self.import_files(owner, root, values, source="git:" + repo.relative_to(root).as_posix(),
                                 git_sha=commit_sha, expected_sha256=expected_sha256)

    def import_github(self, owner, workspace, repository, commit_sha, subdirectory="", *, expected_sha256=None):
        """Explicit operator import from an immutable GitHub archive; redirect host locked."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repository or "") or not _SHA.fullmatch(commit_sha or ""):
            raise ValueError("GitHub owner/repository and full SHA required")
        prefix = subdirectory.rstrip("/")
        if prefix:
            _safe(prefix)
        class LockedRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise PermissionError("GitHub archive redirects refused")
        opener = urllib.request.build_opener(LockedRedirect())
        with opener.open(f"https://codeload.github.com/{repository}/zip/{commit_sha}", timeout=20) as response:
            raw = response.read(MAX_ARCHIVE + 1)
        if len(raw) > MAX_ARCHIVE:
            raise ValueError("GitHub skill archive exceeds limit")
        values, seen, total = {}, set(), 0
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) > 10000:
                raise ValueError("GitHub archive inventory exceeds limit")
            top = None
            for entry in archive.infolist():
                parts = _safe(entry.filename)
                if top is None:
                    top = parts[0]
                if parts[0] != top:
                    raise ValueError("ambiguous GitHub archive root")
                path = "/".join(parts[1:])
                if prefix and not path.startswith(prefix + "/"):
                    continue
                if entry.is_dir() or not path:
                    continue
                relative = path[len(prefix) + 1:] if prefix else path
                if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK or entry.flag_bits & 1:
                    raise ValueError("GitHub linked or encrypted entry refused")
                if relative.casefold() in seen or len(values) >= MAX_FILES or entry.file_size > MAX_FILE_BYTES:
                    raise ValueError("GitHub skill archive collision or size limit")
                seen.add(relative.casefold())
                total += entry.file_size
                if total > MAX_BYTES:
                    raise ValueError("GitHub skill archive exceeds extracted limit")
                with archive.open(entry) as handle:
                    body = handle.read(MAX_FILE_BYTES + 1)
                if len(body) != entry.file_size:
                    raise ValueError("GitHub archive entry length mismatch")
                values[relative] = body.decode("utf-8")
        return self.import_files(owner, workspace, values, source="github:" + repository,
                                 git_sha=commit_sha, expected_sha256=expected_sha256)

    def info(self, owner, workspace, package_id):
        with self._db() as db:
            row = db.execute("SELECT package_id,name,description,source,git_sha,revoked,revision,created "
                             "FROM skill_packages WHERE owner=? AND workspace=? AND package_id=?",
                             (owner, str(Path(workspace).resolve()), package_id)).fetchone()
        if not row:
            raise FileNotFoundError("skill package not owned by this workspace")
        return dict(row)

    def list(self, owner, workspace):
        with self._db() as db:
            rows = db.execute("SELECT package_id FROM skill_packages WHERE owner=? AND workspace=? "
                              "ORDER BY name,created DESC LIMIT 200", (owner, str(Path(workspace).resolve()))).fetchall()
        return {"items": [self.info(owner, workspace, row[0]) for row in rows], "creates_grants": False}

    def revoke(self, owner, workspace, package_id, expected_revision):
        with self._db() as db:
            cursor = db.execute("UPDATE skill_packages SET revoked=1,revision=revision+1 WHERE owner=? AND workspace=? "
                                "AND package_id=? AND revision=? AND revoked=0",
                                (owner, str(Path(workspace).resolve()), package_id, expected_revision))
            if cursor.rowcount != 1:
                raise ValueError("skill package revision changed or already revoked")
        return self.info(owner, workspace, package_id)

    def _work(self, owner, workspace, work_item_id, agent_id):
        work = self.control.governance.work_item_info(work_item_id, owner)
        run = self.control.durable.run_status(work["run_id"], owner)
        if (Path(run["workspace"]).resolve() != Path(workspace).resolve() or
                work["assignee_agent_id"] != agent_id or
                run["state"] not in {"CREATED", "RUNNING", "PAUSED"} or
                work["state"] not in {"QUEUED", "RUNNING", "BLOCKED", "VALIDATING"}):
            raise PermissionError("skill context requires an active, assigned WorkItem in this workspace")
        self.control._agent_from_run(run, agent_id)

    def activate(self, owner, workspace, package_id, work_item_id, agent_id):
        self._work(owner, workspace, work_item_id, agent_id)
        root = str(Path(workspace).resolve())
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revoked FROM skill_packages WHERE owner=? AND workspace=? AND package_id=?",
                             (owner, root, package_id)).fetchone()
            if not row or row[0]:
                raise PermissionError("skill unavailable or revoked")
            db.execute("INSERT OR IGNORE INTO skill_package_activations VALUES(?,?,?,?,?,?)",
                       (owner, work_item_id, agent_id, root, package_id, time.time()))
        return {"package_id": package_id, "work_item_id": work_item_id, "activated": True, "grants_created": False}

    def deactivate(self, owner, workspace, package_id, work_item_id, agent_id):
        """Revoke a single WorkItem disclosure without revoking the immutable package."""
        self._work(owner, workspace, work_item_id, agent_id)
        root = str(Path(workspace).resolve(strict=True))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            removed = db.execute(
                "DELETE FROM skill_package_activations WHERE owner=? AND workspace=? "
                "AND work_item_id=? AND agent_id=? AND package_id=?",
                (owner, root, work_item_id, agent_id, package_id),
            ).rowcount
        return {"package_id": package_id, "work_item_id": work_item_id,
                "deactivated": bool(removed), "grants_revoked": False}

    def replace_activation(self, owner, workspace, old_package_id, new_package_id,
                           work_item_id, agent_id):
        """Atomically switch a WorkItem to a different immutable Skill SHA."""
        self._work(owner, workspace, work_item_id, agent_id)
        if old_package_id == new_package_id:
            raise ValueError("skill update requires a different immutable SHA")
        root = str(Path(workspace).resolve(strict=True))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT 1 FROM skill_package_activations WHERE owner=? AND workspace=? "
                "AND work_item_id=? AND agent_id=? AND package_id=?",
                (owner, root, work_item_id, agent_id, old_package_id),
            ).fetchone()
            new = db.execute(
                "SELECT revoked FROM skill_packages WHERE owner=? AND workspace=? AND package_id=?",
                (owner, root, new_package_id),
            ).fetchone()
            if not old or not new or new[0]:
                raise PermissionError("old skill activation missing or new revision unavailable")
            db.execute(
                "DELETE FROM skill_package_activations WHERE owner=? AND workspace=? "
                "AND work_item_id=? AND agent_id=? AND package_id=?",
                (owner, root, work_item_id, agent_id, old_package_id),
            )
            db.execute(
                "INSERT INTO skill_package_activations VALUES(?,?,?,?,?,?)",
                (owner, work_item_id, agent_id, root, new_package_id, time.time()),
            )
        return {"previous_sha256": old_package_id, "package_id": new_package_id,
                "work_item_id": work_item_id, "activated": True, "grants_created": False}

    def disclose(self, owner, workspace, work_item_id, agent_id, *, package_id=None, path="SKILL.md"):
        self._work(owner, workspace, work_item_id, agent_id)
        root = str(Path(workspace).resolve())
        with self._db() as db:
            rows = db.execute("SELECT p.* FROM skill_package_activations a JOIN skill_packages p "
                              "ON a.owner=p.owner AND a.workspace=p.workspace AND a.package_id=p.package_id "
                              "WHERE a.owner=? AND a.workspace=? AND a.work_item_id=? AND a.agent_id=? AND p.revoked=0 "
                              "ORDER BY p.name LIMIT 32", (owner, root, work_item_id, agent_id)).fetchall()
        if package_id is None:
            return {"items": [{k: r[k] for k in ("package_id", "name", "description", "git_sha")} for r in rows],
                    "content_creates_permissions": False}
        _safe(path)
        selected = next((r for r in rows if r["package_id"] == package_id), None)
        if not selected:
            raise PermissionError("skill revision not activated for this WorkItem")
        values = _decode(selected["protected_files"])
        if _digest(values) != package_id:
            raise ValueError("skill snapshot integrity failed")
        if path not in values:
            raise FileNotFoundError("skill resource not present in this revision")
        return {"package_id": package_id, "path": path, "content": values[path],
                "sha256": hashlib.sha256(values[path].encode()).hexdigest(), "executable": False}
