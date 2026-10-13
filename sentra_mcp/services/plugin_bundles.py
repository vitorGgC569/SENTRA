"""Validated MCPB ingestion into SENTRA's existing plugin-worker authority.

Import does not execute third-party code, install packages, add MCP tools,
create work items or confer a grant. Activation requires a separate centrally
authorized PluginWorkerHost operation; this catalog is an immutable staging
area and is inert by default.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from .control_store import create_control_plane_store
from .pacto_authority import require_same_store


MAX_BUNDLE_BYTES=128*1024*1024
MAX_ENTRIES=10000
MAX_MANIFEST_BYTES=256000
_WINDOWS_RESERVED=re.compile(r"^(?:con|prn|aux|nul|conin\$|conout\$|com[1-9]|lpt[1-9])(?:\.|$)",re.I)
_VALID_OWNER=re.compile(r"^[A-Za-z0-9_.:@/-]{1,200}$")



def _file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda:source.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()

def _safe(name):
    if (not isinstance(name,str) or not name or name.startswith(("/","\\"))
            or "\\" in name or ":" in name or "\x00" in name):
        raise ValueError("MCPB unsafe archive path")
    parts=name.rstrip("/").split("/")
    if any(part in ("",".","..") or part.endswith((" ",".")) or
           _WINDOWS_RESERVED.match(part) or len(part)>255 or
           any(ord(c)<32 for c in part) for part in parts):
        raise ValueError("MCPB unsafe Windows path")
    return parts


class MCPBBundleCatalog:
    def __init__(self,state_root,*,store=None):
        self.state_root=Path(state_root).resolve()
        self.store=store if store is not None else create_control_plane_store(self.state_root)
        self.target=self.state_root/"plugin-bundles"
        self.target.mkdir(parents=True,exist_ok=True)
        db=self._connect()
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS plugin_bundles(
                owner TEXT NOT NULL,workspace TEXT NOT NULL,
                package_sha256 TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                name TEXT NOT NULL,version TEXT NOT NULL,
                source TEXT NOT NULL,created REAL NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(owner,workspace,package_sha256)
            )""")
            db.commit()
        finally:
            db.close()

    def _connect(self):
        return self.store.connect("plugin_bundle")

    def list(self,owner,workspace):
        if not isinstance(owner,str) or not _VALID_OWNER.fullmatch(owner):
            raise ValueError("invalid bundle owner")
        path=str(Path(workspace).resolve(strict=True))
        db=self._connect()
        try:
            rows=db.execute(
                "SELECT package_sha256,manifest_sha256,name,version,created,enabled "
                "FROM plugin_bundles WHERE owner=? AND workspace=? ORDER BY created DESC",
                (owner,path)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    def stage(self,owner,workspace,source,*,expected_sha256=None):
        if not isinstance(owner,str) or not _VALID_OWNER.fullmatch(owner):
            raise ValueError("invalid bundle owner")
        root=Path(workspace).resolve(strict=True)
        source=Path(source).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file() or source.suffix.lower()!=".mcpb":
            raise PermissionError("select an MCPB file within the authorized workspace")
        if not 0<source.stat().st_size<=MAX_BUNDLE_BYTES:
            raise ValueError("MCPB archive size exceeds limit")
        digest=hashlib.sha256()
        with source.open("rb") as handle:
            for data in iter(lambda:handle.read(1024*1024),b""):
                digest.update(data)
        sha=digest.hexdigest()
        if expected_sha256 is not None and sha!=expected_sha256:
            raise ValueError("MCPB checksum mismatch")
        staging=Path(tempfile.mkdtemp(prefix=".mcpb-",dir=self.target))
        manifest=None
        try:
            with zipfile.ZipFile(source) as archive:
                records=archive.infolist()
                if not records or len(records)>MAX_ENTRIES:
                    raise ValueError("MCPB file count exceeds bound")
                seen=set()
                children=set()
                total=0
                for entry in records:
                    _safe(entry.filename)
                    key=entry.filename.rstrip("/").casefold()
                    if key in seen:
                        raise ValueError("MCPB duplicate or case-colliding archive entry")
                    seen.add(key)
                    parts=entry.filename.rstrip("/").split("/")
                    for i in range(1,len(parts)):
                        children.add("/".join(parts[:i]).casefold())
                    mode=(entry.external_attr>>16)
                    if (stat.S_IFMT(mode)==stat.S_IFLNK or
                            entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)):
                        raise ValueError("MCPB encrypted, symbolic link or unsupported compression")
                    total+=entry.file_size
                    if total>MAX_BUNDLE_BYTES:
                        raise ValueError("MCPB extracted size exceeds bound")
                for entry in records:
                    key=entry.filename.rstrip("/").casefold()
                    if not entry.is_dir() and key in children:
                        raise ValueError("MCPB file/directory collision")
                root_manifest=next((e for e in records if e.filename=="manifest.json"),None)
                if root_manifest is None or root_manifest.file_size>MAX_MANIFEST_BYTES:
                    raise ValueError("MCPB needs a bounded manifest.json")
                manifest_data=archive.read(root_manifest)
                manifest=json.loads(manifest_data)
                if not isinstance(manifest,dict):
                    raise ValueError("invalid MCPB manifest")
                name=manifest.get("name")
                version=manifest.get("version")
                if (not isinstance(name,str) or not 1<=len(name)<=160 or
                        not isinstance(version,str) or not 1<=len(version)<=80):
                    raise ValueError("MCPB manifest needs bounded name and version")
                for entry in records:
                    if entry.is_dir():
                        continue
                    dest=staging/entry.filename
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    copied=0
                    with archive.open(entry) as stream,dest.open("xb") as out:
                        while data:=stream.read(1024*1024):
                            copied+=len(data)
                            if copied>entry.file_size or copied>MAX_BUNDLE_BYTES:
                                raise ValueError("MCPB decompression mismatch")
                            out.write(data)
                    if copied!=entry.file_size:
                        raise ValueError("MCPB decompression length mismatch")
            final=self.target/sha
            if final.exists():
                shutil.rmtree(staging)
            else:
                try:
                    os.replace(staging,final)
                except FileExistsError:
                    shutil.rmtree(staging)
            # Preserve original archive bytes under the state root. A registered
            # package cannot depend on an arbitrary workspace file remaining
            # unchanged after the user moves or removes it.
            archives=self.target/".archives"
            if archives.is_symlink() or (hasattr(archives,"is_junction") and archives.is_junction()):
                raise ValueError("MCPB archive root must not be a link")
            archives.mkdir(exist_ok=True)
            archive_target=archives/(sha+".mcpb")
            if not archive_target.exists():
                archive_temp=archives/("."+uuid.uuid4().hex+".part")
                try:
                    shutil.copyfile(source,archive_temp)
                    if _file_sha256(archive_temp)!=sha:
                        raise ValueError("MCPB source changed during import")
                    os.replace(archive_temp,archive_target)
                finally:
                    archive_temp.unlink(missing_ok=True)
            if (archive_target.is_symlink() or
                    _file_sha256(archive_target)!=sha):
                raise ValueError("MCPB saved archive integrity mismatch")
            db=self._connect()
            try:
                with db:
                    db.execute("INSERT OR IGNORE INTO plugin_bundles VALUES(?,?,?,?,?,?,?,?,0)",
                        (owner,str(root),sha,hashlib.sha256(manifest_data).hexdigest(),
                         name,version,str(source),time.time()))
            finally:
                db.close()
            return {"package_sha256":sha,"name":name,"version":version,
                    "status":"staged_inactive","enabled":False,
                    "manifest_sha256":hashlib.sha256(manifest_data).hexdigest(),
                    "requires_grant_and_activation":True}
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _registration_db(self):
        db = self._connect()
        db.execute("""CREATE TABLE IF NOT EXISTS plugin_bundle_registrations (
            owner TEXT NOT NULL, workspace TEXT NOT NULL, package_sha256 TEXT NOT NULL,
            plugin_id TEXT NOT NULL, status TEXT NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL,
            PRIMARY KEY(owner, workspace, package_sha256),
            UNIQUE(owner, plugin_id))""")
        db.commit()
        return db

    def _verify_payload(self, row, directory):
        """Bind every staged byte to its original archive digest before admission."""
        archive=self.target/".archives"/(row["package_sha256"]+".mcpb")
        # Existing staged packages predating archived snapshots may still use
        # their originally approved source. New imports are self-contained.
        original=archive if archive.exists() or archive.is_symlink() else Path(row["source"])
        if not original.is_file() or original.is_symlink() or original.stat().st_size > MAX_BUNDLE_BYTES:
            raise ValueError("MCPB saved archive is unavailable for integrity verification")
        digest = hashlib.sha256()
        with original.open("rb") as source:
            for part in iter(lambda:source.read(1024*1024),b""):
                digest.update(part)
        if digest.hexdigest()!=row["package_sha256"]:
            raise ValueError("MCPB original archive SHA-256 mismatch")
        with zipfile.ZipFile(original) as archive:
            expected=set()
            for item in archive.infolist():
                if item.is_dir():
                    continue
                _safe(item.filename)
                expected.add(item.filename.casefold())
                file=directory/item.filename
                relative=file.relative_to(directory)
                for component in (file, *(directory/Path(*relative.parts[:n])
                                       for n in range(1,len(relative.parts)))):
                    if component.is_symlink() or (hasattr(component,"is_junction") and component.is_junction()):
                        raise ValueError("MCPB staged payload contains links")
                if not file.is_file() or file.stat().st_size!=item.file_size:
                    raise ValueError("MCPB staged payload file missing or changed")
                with archive.open(item) as stream, file.open("rb") as installed:
                    while True:
                        left=stream.read(1024*1024)
                        right=installed.read(1024*1024)
                        if left!=right:
                            raise ValueError("MCPB staged payload integrity mismatch")
                        if not left:
                            break
            actual=set()
            for candidate in directory.rglob("*"):
                if candidate.is_symlink() or (hasattr(candidate,"is_junction") and candidate.is_junction()):
                    raise ValueError("MCPB staged payload contains links")
                if candidate.is_file():
                    actual.add(candidate.relative_to(directory).as_posix().casefold())
            if actual!=expected:
                raise ValueError("MCPB staged payload inventory changed")

    def describe(self, owner, workspace, package_sha256):
        """Inspect a staged MCPB 0.3 without resolving secrets or executing code."""
        if not isinstance(owner, str) or not _VALID_OWNER.fullmatch(owner):
            raise ValueError("invalid bundle owner")
        root = str(Path(workspace).resolve(strict=True))
        if not isinstance(package_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", package_sha256):
            raise ValueError("MCPB immutable SHA-256 required")
        with self._connect() as db:
            row = db.execute("SELECT * FROM plugin_bundles WHERE owner=? AND workspace=? "
                             "AND package_sha256=?", (owner,root,package_sha256)).fetchone()
        if not row:
            raise FileNotFoundError("MCPB is not staged for this workspace")
        directory = self.target / package_sha256
        if directory.is_symlink() or (hasattr(directory,"is_junction") and directory.is_junction()):
            raise ValueError("MCPB extraction root must not be a link")
        self._verify_payload(row,directory)
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("MCPB manifest missing or altered")
        data = manifest_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["manifest_sha256"]:
            raise ValueError("MCPB manifest integrity mismatch")
        manifest = json.loads(data)
        if not isinstance(manifest, dict) or manifest.get("manifest_version") != "0.3":
            raise ValueError("only reviewed MCPB 0.3 manifests can be registered")
        name = manifest.get("name")
        version = manifest.get("version")
        author = manifest.get("author")
        server = manifest.get("server")
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", name)
                or not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version)
                or not isinstance(author, dict) or not isinstance(author.get("name"), str)
                or not 1 <= len(author["name"]) <= 160
                or not isinstance(server, dict) or server.get("type") not in {"python","node","binary"}):
            raise ValueError("invalid MCPB 0.3 publisher, version or server metadata")
        entry = server.get("entry_point")
        if not isinstance(entry, str) or not entry or len(entry) > 255:
            raise ValueError("MCPB server entry_point required")
        _safe(entry)
        path = directory / entry
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("MCPB server entry_point is unavailable or unsafe")
        compatibility = manifest.get("compatibility") or {}
        if not isinstance(compatibility, dict):
            raise ValueError("invalid MCPB compatibility object")
        platforms = compatibility.get("platforms")
        if platforms is not None and (not isinstance(platforms, list)
                or any(x not in {"darwin","win32","linux"} for x in platforms)):
            raise ValueError("invalid MCPB platforms")
        settings = manifest.get("user_config") or {}
        if not isinstance(settings, dict) or len(settings) > 64:
            raise ValueError("invalid MCPB user configuration")
        if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", key)
               or not isinstance(value, dict) for key,value in settings.items()):
            raise ValueError("invalid MCPB user configuration keys")
        # mcp_config may contain substitutions, commands or secret references.
        # Deliberately do not return or persist those untrusted values.
        return {"package_sha256":package_sha256,"manifest_sha256":row["manifest_sha256"],
                "name":name,"version":version,"author_name":author["name"],
                "server_type":server["type"],"entry_point":entry,
                "compatible_with_host": platforms is None or ("win32" if os.name=="nt" else "linux") in platforms,
                "required_user_config_keys":sorted(key for key,value in settings.items() if value.get("required")),
                "execution_protocol":"mcp_stdio","execution_supported":False,
                "registration_creates_permissions":False}

    def registration(self, owner, workspace, package_sha256):
        root = str(Path(workspace).resolve(strict=True))
        with self._registration_db() as db:
            row = db.execute("SELECT plugin_id,status FROM plugin_bundle_registrations WHERE "
                             "owner=? AND workspace=? AND package_sha256=?",
                             (owner,root,package_sha256)).fetchone()
        return {"plugin_id":row["plugin_id"],"status":row["status"]} if row else None

    def register(self, owner, workspace, package_sha256, governance):
        """Bind staged bytes to governance, deliberately inert and idempotent."""
        evidence = self.describe(owner, workspace, package_sha256)
        if not evidence["compatible_with_host"]:
            raise PermissionError("MCPB is not compatible with this host platform")
        root = str(Path(workspace).resolve(strict=True))
        db = self._registration_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT plugin_id,status FROM plugin_bundle_registrations WHERE "
                             "owner=? AND workspace=? AND package_sha256=?",
                             (owner,root,package_sha256)).fetchone()
            if old:
                plugin = governance.plugin_info(old["plugin_id"], owner)
                if plugin["state"] not in {"REGISTERED","DISABLED"}:
                    raise PermissionError("MCPB no longer has an inert governance state")
                if plugin["state"] != old["status"]:
                    raise PermissionError("MCPB registration and governance state disagree")
                db.commit()
                return {"plugin_id":plugin["plugin_id"],"status":old["status"],
                        "package_sha256":package_sha256,"created_grants":False,
                        "worker_started":False,"already_registered":True}
            # Crash recovery across the separate governance/bundle databases:
            # reuse a previous inert registration with identical provenance.
            matches = [item for item in governance.list_plugins(owner)["items"]
                       if item.get("metadata",{}).get("mcpb_sha256")==package_sha256
                       and item.get("metadata",{}).get("mcpb_workspace")==root]
            if len(matches)>1:
                raise ValueError("conflicting MCPB governance registrations")
            if matches:
                plugin=matches[0]
                if plugin["state"] not in {"REGISTERED","DISABLED"}:
                    raise PermissionError("unexpected MCPB plugin state")
            else:
                plugin=governance.register_plugin(owner,
                    manifest={"name":evidence["name"],"version":evidence["version"],
                              "capabilities":[]},
                    verified_methods=[],narrowed_capabilities=[],trusted_ui=False,
                    metadata={"origin":"mcpb","mcpb_sha256":package_sha256,
                              "mcpb_workspace":root,
                              "manifest_sha256":evidence["manifest_sha256"],
                              "protocol":"mcp_stdio","worker_execution_available":False})
            status = "DISABLED" if plugin["state"]=="DISABLED" else "REGISTERED"
            now=time.time()
            db.execute("INSERT INTO plugin_bundle_registrations VALUES(?,?,?,?,?,?,?)",
                       (owner,root,package_sha256,plugin["plugin_id"],status,now,now))
            db.commit()
            return {"plugin_id":plugin["plugin_id"],"status":status,
                    "package_sha256":package_sha256,"created_grants":False,
                    "worker_started":False,"already_registered":bool(matches)}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def disable(self, owner, workspace, package_sha256, governance):
        """Revoke catalog admission; no subprocess is started or retained."""
        root = str(Path(workspace).resolve(strict=True))
        db=self._registration_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT plugin_id,status FROM plugin_bundle_registrations WHERE "
                           "owner=? AND workspace=? AND package_sha256=?",
                           (owner,root,package_sha256)).fetchone()
            if not row:
                raise FileNotFoundError("MCPB is not registered in this workspace")
            if row["status"] == "REMOVED":
                raise PermissionError("MCPB registration is permanently uninstalled")
            plugin=governance.plugin_info(row["plugin_id"],owner)
            if plugin["state"] not in {"REGISTERED","DISABLED"}:
                raise PermissionError("stop live plugin workers before disabling bundle")
            if plugin["state"]!="DISABLED":
                governance.update_plugin_verification(row["plugin_id"],owner,
                    verified_methods=[],live_capabilities=[],state="DISABLED")
            db.execute("UPDATE plugin_bundle_registrations SET status='DISABLED',updated=? "
                       "WHERE owner=? AND workspace=? AND package_sha256=?",
                       (time.time(),owner,root,package_sha256))
            db.commit()
            return {"plugin_id":row["plugin_id"],"status":"DISABLED",
                    "worker_started":False,"grants_created":False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def launch_spec(self, owner, workspace, package_sha256, governance):
        """Return a trusted-host launch *candidate* from reviewed Python MCPB bytes.

        No subprocess, environment injection, dependency installation, request
        admission or token/grant is created here. A separate central durable
        operation and fenced effect boundary MUST authorize any actual launch.
        """
        import sys
        evidence = self.describe(owner, workspace, package_sha256)
        registered = self.registration(owner, workspace, package_sha256)
        if not registered or registered["status"] != "REGISTERED":
            raise PermissionError("MCPB launch requires an enabled central registration")
        plugin = governance.plugin_info(registered["plugin_id"], owner)
        if (plugin["state"] != "REGISTERED" or
                plugin.get("effective_capabilities") or plugin.get("verified_methods") or
                plugin.get("metadata", {}).get("mcpb_sha256") != package_sha256 or
                plugin.get("metadata", {}).get("origin") != "mcpb" or
                plugin.get("metadata", {}).get("mcpb_workspace") !=
                str(Path(workspace).resolve(strict=True))):
            raise PermissionError("MCPB provenance or inert registration changed")
        if not evidence["compatible_with_host"] or evidence["server_type"] != "python":
            raise PermissionError("only reviewed Python MCPB launch plans are currently supported")
        if evidence["required_user_config_keys"]:
            raise PermissionError("MCPB unresolved user configuration requires a separate secret broker")
        directory = self.target / package_sha256
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        server = manifest["server"]
        configuration = server.get("mcp_config")
        if (not isinstance(configuration, dict) or
                set(configuration) - {"command", "args", "env"} or
                configuration.get("command") not in {"python", "python3"} or
                configuration.get("env", {}) != {}):
            raise PermissionError("MCPB launch configuration is unsupported or requests environment access")
        arguments = configuration.get("args")
        expected = "${__dirname}/" + evidence["entry_point"]
        if arguments != [expected]:
            raise PermissionError("MCPB argv must select only the reviewed package entry point")
        if manifest.get("user_config"):
            raise PermissionError("MCPB user configuration is not automatically injected")
        if getattr(sys, "frozen", False):
            raise PermissionError("frozen SENTRA executable is not a Python MCP interpreter")
        interpreter = Path(sys.executable).absolute()
        if not interpreter.is_file() or interpreter.is_symlink():
            raise PermissionError("trusted Python runtime executable is not available")
        try:
            interpreter_resolved = str(interpreter.resolve(strict=True)) == str(interpreter)
        except OSError:
            # Windows Store app aliases cannot prove their final target here.
            # The plan remains non-executable until a trusted host pins it.
            interpreter_resolved = False
        script = (directory / evidence["entry_point"]).resolve(strict=True)
        if not script.is_relative_to(directory.resolve()) or script.suffix.lower() != ".py":
            raise PermissionError("reviewed Python script is not confined to MCPB")
        archive_path = self.target / ".archives" / (package_sha256 + ".mcpb")
        if archive_path.is_symlink() or not archive_path.is_file():
            raise PermissionError("MCPB immutable archived payload is unavailable")
        expected_entry = hashlib.sha256()
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open(evidence["entry_point"]) as stream:
                for block in iter(lambda: stream.read(1024*1024), b""):
                    expected_entry.update(block)
        verified_entry = _file_sha256(script)
        if verified_entry != expected_entry.hexdigest():
            raise PermissionError("MCPB entry point changed after integrity verification")
        argv = ["-u", str(script)]
        argv_sha = hashlib.sha256(json.dumps(
            argv, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {"plugin_id":registered["plugin_id"],"package_sha256":package_sha256,
                "manifest_sha256":evidence["manifest_sha256"],"entry_sha256":verified_entry,
                "executable":str(interpreter),"cwd":str(directory),"args":argv,
                "argv_sha256":argv_sha,"server_id":"mcpb-"+package_sha256[:32],
                "protocol":"mcp_stdio","requires_capability":"mcp:launch",
                "interpreter_target_verified":interpreter_resolved,
                "worker_started":False,"durable_admission_required":True,
                "ready_to_execute":False}


    def update(self, owner, workspace, old_sha256, new_sha256, governance, *,
               approved=False):
        """Fail-closed staged revision switch, without auto-launch or auto-grants.

        Existing old registration is permanently disabled first; registering
        the new immutable archive uses the existing governance authority.
        A crash between phases leaves the old bundle disabled (never an
        implicit retry or auto-restore), requiring operator reconciliation.
        """
        if not approved or old_sha256 == new_sha256:
            raise PermissionError("distinct MCPB revision and operator approval required")
        old = self.describe(owner, workspace, old_sha256)
        new = self.describe(owner, workspace, new_sha256)
        previous = self.registration(owner, workspace, old_sha256)
        if not previous or previous["status"] != "REGISTERED":
            raise PermissionError("old MCPB must be actively registered before update")
        if (old["name"] != new["name"] or old["author_name"] != new["author_name"]
                or old["server_type"] != new["server_type"]):
            raise PermissionError("MCPB update provenance/publisher changed")
        current = self.registration(owner, workspace, new_sha256)
        if current and current["status"] != "REGISTERED":
            raise PermissionError("new MCPB revision is already disabled or retired")
        # Both bytes were checked before disabling the old revision.
        self.disable(owner, workspace, old_sha256, governance)
        replacement = self.register(owner, workspace, new_sha256, governance)
        if replacement["status"] != "REGISTERED":
            raise PermissionError("new MCPB registration did not become inert registered")
        return {"old_package_sha256": old_sha256, "package_sha256": new_sha256,
                "previous_status": "DISABLED", "status": "REGISTERED",
                "plugin_id": replacement["plugin_id"], "worker_started": False,
                "grants_created": False, "installation_requires_new_approval": True}

    def uninstall(self, owner, workspace, package_sha256, governance, *,
                  approved=False):
        """Permanently retire a registration; preserve immutable audit bytes.

        Not a full disk-purge: the immutable archive stays available for
        forensic reconciliation and existing operation receipts. No plugin
        can be registered again under this owner/workspace/SHA tombstone.
        """
        if not approved:
            raise PermissionError("explicit operator approval required for MCPB uninstall")
        existing = self.registration(owner, workspace, package_sha256)
        if not existing:
            raise FileNotFoundError("MCPB registration not found")
        if existing["status"] != "REMOVED":
            self.disable(owner, workspace, package_sha256, governance)
            root = str(Path(workspace).resolve(strict=True))
            with self._registration_db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "UPDATE plugin_bundle_registrations SET status='REMOVED',updated=? "
                    "WHERE owner=? AND workspace=? AND package_sha256=? AND status='DISABLED'",
                    (time.time(), owner, root, package_sha256))
        return {"plugin_id": existing["plugin_id"], "package_sha256": package_sha256,
                "status": "REMOVED", "worker_started": False, "grants_created": False,
                "archived_for_audit": True, "disk_purge_completed": False}

    def rollback(self, owner, workspace, current_sha256, previous_sha256,
                 governance, *, approved=False):
        """Operator-reviewed rollback of inactive MCPB registrations.

        Never roll back running plugins or resurrect REMOVED tombstones.
        If a mid-flight failure occurs, prefer both revisions DISABLED rather
        than silently enabling the previous provider with stale grants.
        """
        if approved is not True or current_sha256 == previous_sha256:
            raise PermissionError("explicit operator-approved distinct revision required")
        current = self.describe(owner, workspace, current_sha256)
        previous = self.describe(owner, workspace, previous_sha256)
        if (current["name"], current["author_name"], current["server_type"]) != (
                previous["name"], previous["author_name"], previous["server_type"]):
            raise PermissionError("MCPB rollback publisher/provenance mismatch")
        current_registration = self.registration(owner, workspace, current_sha256)
        old_registration = self.registration(owner, workspace, previous_sha256)
        if (not current_registration or current_registration["status"] != "REGISTERED"
                or not old_registration or old_registration["status"] != "DISABLED"):
            raise PermissionError("rollback needs active current and disabled prior revision")
        old_plugin = governance.plugin_info(old_registration["plugin_id"], owner)
        if (old_plugin["state"] != "DISABLED" or old_plugin["verified_methods"]
                or old_plugin["effective_capabilities"]):
            raise PermissionError("prior MCPB revision is not inert")
        self.disable(owner, workspace, current_sha256, governance)
        # Registration status and governance state live in separate central
        # namespaces. A failure between writes remains non-executable until
        # host reconciliation; this is not described as atomic rollback.
        governance.update_plugin_verification(
            old_registration["plugin_id"], owner, verified_methods=[],
            live_capabilities=[], state="REGISTERED")
        root = str(Path(workspace).resolve(strict=True))
        with self._registration_db() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                "UPDATE plugin_bundle_registrations SET status='REGISTERED',updated=? "
                "WHERE owner=? AND workspace=? AND package_sha256=? AND status='DISABLED'",
                (time.time(), owner, root, previous_sha256))
            if result.rowcount != 1:
                raise PermissionError("MCPB rollback registration conflict")
        return {"package_sha256": previous_sha256, "disabled_sha256": current_sha256,
                "status": "REGISTERED", "worker_started": False,
                "grants_created": False, "rollback_was_cross_database": True}


    def purge_uninstalled_extracted(self, owner, workspace, package_sha256,
                                    control, *, approved=False):
        """Remove globally unowned extracted files; keep immutable audit archive."""
        if approved is not True or not re.fullmatch(r"[a-f0-9]{64}", package_sha256 or ""):
            raise PermissionError("operator-approved MCPB SHA is required")
        root = str(Path(workspace).resolve(strict=True))
        require_same_store(control.store, self.store)
        target = self.target / package_sha256
        archive = self.target / ".archives" / (package_sha256 + ".mcpb")
        if archive.is_symlink() or not archive.is_file() or _file_sha256(archive) != package_sha256:
            raise PermissionError("immutable MCPB audit archive missing or modified")
        with self._registration_db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT owner,workspace,plugin_id,status FROM plugin_bundle_registrations "
                "WHERE package_sha256=?", (package_sha256,)).fetchall()
            if (not rows or not any(r["owner"] == owner and r["workspace"] == root for r in rows)
                    or any(r["status"] != "REMOVED" for r in rows)):
                raise PermissionError("MCPB remains registered for another owner or workspace")
            staged = db.execute(
                "SELECT owner,workspace FROM plugin_bundles WHERE package_sha256=?",
                (package_sha256,)).fetchall()
            if any(not any(s["owner"] == r["owner"] and s["workspace"] == r["workspace"]
                           for r in rows) for s in staged):
                raise PermissionError("an unregistered workspace still owns this staged MCPB")
            with control.store.connect("plugin_worker") as workers:
                for reg in rows:
                    if workers.execute(
                        "SELECT 1 FROM plugin_workers WHERE plugin_id=? AND state!='STOPPED' "
                        "LIMIT 1", (reg["plugin_id"],)).fetchone():
                        raise PermissionError("MCPB worker not stopped")
            try:
                pending = db.execute(
                    "SELECT 1 FROM mcpb_docker_ownership WHERE workspace IN (" +
                    ",".join("?" for _ in rows) + ") AND state!='CLEANED' LIMIT 1",
                    tuple(r["workspace"] for r in rows)).fetchone()
            except __import__("sqlite3").OperationalError:
                pending = None
            if pending:
                raise PermissionError("Docker mount ownership is unreconciled")
            if not target.exists():
                return {"package_sha256": package_sha256, "extracted_removed": True,
                        "archive_retained": True, "full_archive_purge": False}
            if (target.is_symlink() or getattr(target, "is_junction", lambda: False)()
                    or target.resolve(strict=True).parent != self.target.resolve(strict=True)):
                raise PermissionError("MCPB extracted root replaced")
            for directory, dirs, files in os.walk(target, followlinks=False):
                for filename in dirs + files:
                    path = Path(directory) / filename
                    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                        raise PermissionError("unsafe link/junction in extracted MCPB")
            quarantine = self.target / (".purge-" + package_sha256 + "-" + uuid.uuid4().hex)
            target.rename(quarantine)
            shutil.rmtree(quarantine)
            return {"package_sha256": package_sha256, "extracted_removed": True,
                    "archive_retained": True, "full_archive_purge": False,
                    "grants_created": False}


class MCPBWorkItemLifecycle:
    """Host-only coordinated MCPB lifecycle; all authority remains in ControlPlane.

    This facade does not mint grants, operations, credentials, process sessions,
    or a parallel database. It binds existing central authorities to one
    immutable package/owner/workspace/Run/WorkItem/assignee.
    """
    def __init__(self, control, *, owner, workspace, package_sha256,
                 run_id, work_item_id, agent_id):
        self.control = control
        self.owner = owner
        self.workspace = str(Path(workspace).resolve(strict=True))
        self.package_sha256 = package_sha256
        self.server_id = "mcpb-" + package_sha256[:32]
        self.run_id, self.work_item_id, self.agent_id = run_id, work_item_id, agent_id
        self._binding()

    def _binding(self, capability=None, *, requires_registered=True):
        run = self.control.durable.run_status(self.run_id, self.owner)
        work = self.control.work_item_info(self.work_item_id, self.owner)
        if (run.get("state") not in ("CREATED", "RUNNING")
                or work.get("state") != "RUNNING"
                or work.get("run_id") != self.run_id
                or work.get("assignee_agent_id") != self.agent_id
                or str(Path(run["workspace"]).resolve()) != self.workspace):
            raise PermissionError("MCPB lifecycle requires same active central WorkItem")
        self.control._agent_from_run(run, self.agent_id)
        evidence = self.control.bundle_catalog.describe(
            self.owner, self.workspace, self.package_sha256)
        registration = self.control.bundle_catalog.registration(
            self.owner, self.workspace, self.package_sha256)
        if requires_registered and (not registration or registration["status"] != "REGISTERED"):
            raise PermissionError("MCPB lifecycle registration disabled or missing")
        if capability:
            self.control.authorization.require(
                self.owner, principal_type="agent", principal_id=self.agent_id,
                capability=capability, scope_type="work_item",
                scope_id=self.work_item_id)
        return evidence, registration

    def _host_approval(self, action, reference, verifier):
        if not callable(verifier) or not isinstance(reference, str) or not 1 <= len(reference) <= 256:
            raise PermissionError("MCPB host approval callback/reference required")
        try:
            approved = verifier(self.owner, self.workspace, self.run_id,
                self.work_item_id, self.agent_id, self.package_sha256,
                action, reference)
        except Exception:
            approved = False
        if approved is not True:
            raise PermissionError("MCPB owner approval expired, revoked or missing")

    def inspect(self):
        evidence, registration = self._binding(requires_registered=False)
        return {"package_sha256": self.package_sha256,
                "manifest_sha256": evidence["manifest_sha256"],
                "server_id": self.server_id,
                "registration": registration["status"] if registration else "STAGED",
                "work_item_id": self.work_item_id, "run_id": self.run_id,
                "agent_id": self.agent_id, "remote_account_verified": False,
                "worker_started": False, "grants_created": False}

    def oauth_callback(self, broker, *, host_session, consent_ref,
                       verify_host_consent, exchange):
        """Construct real loopback receiver; host must call start/close."""
        from .mcpb_oauth_callback import OAuthLoopbackReceiver
        self._binding("mcp:oauth")
        require_same_store(self.control.store, broker.vault.store)
        if not callable(verify_host_consent):
            raise PermissionError("authenticated OAuth owner host callback required")

        def revalidate(owner, workspace, server_id, session, approval):
            if (owner != self.owner or workspace != self.workspace
                    or server_id != self.server_id):
                return False
            try:
                self._binding("mcp:oauth")
                return verify_host_consent(
                    self.owner, self.workspace, self.run_id, self.work_item_id,
                    self.agent_id, self.package_sha256, session, approval) is True
            except Exception:
                return False

        return OAuthLoopbackReceiver(broker, owner=self.owner,
            workspace=self.workspace, server_id=self.server_id,
            host_session=host_session, consent_ref=consent_ref,
            verify_host_consent=revalidate, exchange=exchange)

    def _http(self, registry):
        if registry.control is not self.control:
            raise PermissionError("MCP HTTP registry must use same central authority")
        require_same_store(self.control.store, registry.store)
        row = registry.get(self.owner, self.workspace, self.server_id)
        if not row["enabled"] or not row["streamable"]:
            raise PermissionError("MCP HTTP lifecycle provider not active")
        return registry

    async def call_http_tool(self, registry, vault, *, name, arguments,
                             operation_id, idempotency_key):
        self._binding("mcp:" + name)
        self._http(registry)
        require_same_store(self.control.store, vault.store)
        # Host-only callable returns bearer to the transport, not the tool result.
        return await registry.execute(owner=self.owner, workspace=self.workspace,
            server_id=self.server_id, run_id=self.run_id,
            work_item_id=self.work_item_id, agent_id=self.agent_id,
            tool_name=name, arguments=arguments, operation_id=operation_id,
            idempotency_key=idempotency_key,
            access_token=lambda: vault.access(self.owner, self.workspace, self.server_id))

    async def session_action(self, registry, vault, *, source_operation_id,
                             operation_id, idempotency_key, action):
        if action not in ("events", "delete"):
            raise ValueError("MCP session action requires events/delete")
        self._binding("mcp:events" if action == "events" else "mcp:session-delete")
        self._http(registry)
        require_same_store(self.control.store, vault.store)
        return await registry.session_action(
            owner=self.owner, workspace=self.workspace, server_id=self.server_id,
            run_id=self.run_id, work_item_id=self.work_item_id, agent_id=self.agent_id,
            source_operation_id=source_operation_id, operation_id=operation_id,
            idempotency_key=idempotency_key, action=action,
            access_token=lambda: vault.access(self.owner, self.workspace, self.server_id))

    async def install_offline_in_owned_docker(self, *, operation_id, idempotency_key):
        self._binding("mcp:deps-install")
        from .mcpb_offline import verify_offline_dependencies_in_docker
        return await verify_offline_dependencies_in_docker(
            self.control, owner=self.owner, workspace=self.workspace,
            package_sha256=self.package_sha256, run_id=self.run_id,
            work_item_id=self.work_item_id, agent_id=self.agent_id,
            operation_id=operation_id, idempotency_key=idempotency_key)

    def publish_verified_tool(self, *, source_operation_id, tool_name,
                              descriptor, approval_ref, verify_host_approval):
        """Local, namespaced schema ACL only; NOT remote ChatGPT publication."""
        self._binding("mcp:publish-schema")
        self._host_approval("publish-schema", approval_ref, verify_host_approval)
        reg = self.control.bundle_catalog.registration(
            self.owner, self.workspace, self.package_sha256)
        operation = self.control.durable.operation_status(source_operation_id, self.owner)
        progress = operation.get("progress") or {}
        from .mcpb_http import _TOOL
        if (operation["state"] != "SUCCEEDED" or operation["run_id"] != self.run_id
                or progress.get("work_item_id") != self.work_item_id
                or progress.get("principal_id") != self.agent_id
                or not isinstance(tool_name, str) or not _TOOL.fullmatch(tool_name)
                or not isinstance(descriptor, dict)
                or descriptor.get("name") != tool_name):
            raise PermissionError("MCPB schema must match proved central tool Operation")
        with self.control.store.connect("plugin_bundle") as db:
            observed = db.execute("SELECT 1 FROM mcp_http_session_attempts "
                "WHERE owner=? AND workspace=? AND server_id=? "
                "AND operation_id=? AND state='COMPLETED'",
                (self.owner, self.workspace, self.server_id, source_operation_id)).fetchone()
        if not observed:
            raise PermissionError("MCPB schema has no successful session tool receipt")
        # Only the observed tool name is projected, with no new grants.
        result = self.control.tool_exposure.reserve(reg["plugin_id"], [descriptor], enabled=True)
        return {**result, "provider_id": reg["plugin_id"],
                "external_account_verified": False, "work_item_id": self.work_item_id}

    async def oauth_effect(self, vault, *, action, operation_id, idempotency_key,
                           approval_ref, verify_host_approval, exchange=None, revoke=None):
        """Real WorkItem-granted, durable OAuth refresh or remote revoke.

        The vault itself persists REFRESHING / REVOKING before a network effect,
        and never retries a rotated token following ambiguous completion.
        Caller must supply a trusted reviewed host-only exchange/revoker.
        """
        import asyncio
        from sentra_interop.central import CentralInteropAdapter
        from sentra_runtime.contracts import Capability, Machine, OperationRequest

        capability = {"refresh": "mcp:oauth-refresh",
                      "revoke": "mcp:oauth-revoke"}.get(action)
        if not capability:
            raise PermissionError("MCPB OAuth requires central vault and known effect")
        require_same_store(self.control.store, vault.store)
        transport = exchange if action == "refresh" else revoke
        if not callable(transport):
            raise PermissionError("trusted OAuth refresh or revoker required")
        self._binding(capability)
        self._host_approval("oauth-" + action, approval_ref, verify_host_approval)
        machine = Machine(self.server_id, "mcpb", self.owner, (
            Capability(capability, "Authorized one-shot OAuth token lifecycle"),))
        gate = CentralInteropAdapter(control=self.control, owner=self.owner,
                                     run_id=self.run_id, machine=machine).protocol_gate()
        request = OperationRequest(
            operation_id, self.agent_id, machine.machine_id, capability,
            self.work_item_id, idempotency_key,
            {"server_id": self.server_id, "package_sha256": self.package_sha256})
        if not (await gate.decision(request)).allowed:
            raise PermissionError("MCPB OAuth effect WorkItem grant denied")

        async def effect():
            self._binding(capability)
            self._host_approval("oauth-" + action, approval_ref, verify_host_approval)
            gate.physical_context(request).checkpoint()
            if action == "refresh":
                result = await asyncio.to_thread(
                    vault.refresh, self.owner, self.workspace, self.server_id, transport)
            else:
                result = await asyncio.to_thread(
                    vault.revoke_remote, self.owner, self.workspace, self.server_id,
                    transport, approved=True)
            gate.physical_context(request).checkpoint()
            return result

        return await gate.execute(request, effect, timeout=25)

    def retire(self, registry, vault, *, approval_ref, verify_host_approval,
               uninstall=False, purge=False):
        self._binding("mcp:manage")
        self._host_approval("uninstall" if uninstall else "disable",
                            approval_ref, verify_host_approval)
        _, registration = self._binding()
        if registry.control is not self.control:
            raise PermissionError("MCPB retirement needs exactly the central authorities")
        require_same_store(self.control.store, registry.store)
        require_same_store(self.control.store, vault.store)
        # Fail closed: schema first, transport second, local bearer third.
        self.control.tool_exposure.disable(registration["plugin_id"])
        try:
            endpoint = registry.get(self.owner, self.workspace, self.server_id)
        except FileNotFoundError:
            endpoint = None
        if endpoint and endpoint["enabled"]:
            registry.disable(self.owner, self.workspace, self.server_id, approved=True)
        from .mcpb_oauth import OAuthAdmissionError
        try:
            token_state = vault.status(self.owner, self.workspace, self.server_id)
        except OAuthAdmissionError:
            token_state = None
        if token_state and token_state["status"] == "ACTIVE":
            vault.revoke(self.owner, self.workspace, self.server_id, approved=True)
        disabled = self.control.bundle_disable(
            self.owner, self.workspace, self.package_sha256)
        result = {"registration": disabled["status"], "schema_enabled": False,
                  "oauth_local_access": False, "remote_oauth_revoke_confirmed": False,
                  "remote_schema_published": False}
        if uninstall:
            result["uninstall"] = self.control.bundle_catalog.uninstall(
                self.owner, self.workspace, self.package_sha256,
                self.control.governance, approved=True)
            if purge:
                result["purge"] = self.control.bundle_catalog.purge_uninstalled_extracted(
                    self.owner, self.workspace, self.package_sha256,
                    self.control, approved=True)
        return result
