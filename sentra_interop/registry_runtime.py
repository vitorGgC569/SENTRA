"""Authorized staged ACP distribution installation; never launches the agent.

Binary archives use an independently approved hash. npm/Python distributions
use a host-supplied pinned lock and native package-manager invocation, with
scripts disabled for npm and hashes mandatory for uv. Promotion is immutable;
failed staging never replaces the known installed version.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tarfile
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path,PurePosixPath,PureWindowsPath

from sentra_runtime.effect_boundary import current_effect_context
from .acp_process import spawn_owned
from .gate import EffectRejected
from .registry import AGENT_ID
from .registry_install import ACPInstallationPlan
from .provider_store import canonical,digest


class ACPDistributionInstaller:
    def __init__(self,*,control,owner,install_root):
        self.control,self.owner=control,owner
        self.root=Path(install_root).resolve()
        expected=(control.durable.root/"interop-installed").resolve()
        if not self.root.is_relative_to(expected):raise ValueError("ACP installs belong to central private provider storage")
        self.root.mkdir(parents=True,exist_ok=True)
        db=control.store.connect("interop_installations")
        try:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS acp_installed(owner TEXT NOT NULL,agent TEXT NOT NULL,"
                    "version TEXT NOT NULL,plan TEXT NOT NULL,manifest TEXT NOT NULL,path TEXT NOT NULL,"
                    "PRIMARY KEY(owner,agent,version))")
        finally:db.close()

    @staticmethod
    def request_arguments(plan,*,executable_sha256,lock_sha256=None,runner_sha256=None):
        return {"plan_sha256":plan.fingerprint,"agent_id":plan.agent_id,"version":plan.version,
                "executable_sha256":executable_sha256,"lock_sha256":lock_sha256,"runner_sha256":runner_sha256}

    @staticmethod
    def version_key(value):
        match=re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:-preview\.([0-9]+))?",value)
        if match is None:raise ValueError("invalid pinned ACP version")
        major,minor,patch,preview=match.groups()
        return int(major),int(minor),int(patch),1 if preview is None else 0,int(preview or 0)

    def checkpoint(self):
        context=current_effect_context.get()
        if context is None:raise EffectRejected("ACP installation outside central physical admission")
        context.checkpoint()
        return context

    @staticmethod
    def file_hash(path):
        with Path(path).open("rb") as source:return hashlib.file_digest(source,"sha256").hexdigest()

    def reconcile(self,*,plan,executable_sha256):
        self.checkpoint()
        directory=(self.root/plan.agent_id/plan.version).resolve()
        if not directory.is_relative_to(self.root) or not directory.is_dir():
            return {"installed":False,"agent_id":plan.agent_id,"version":plan.version,"launch_authorized":False}
        manifest_path=directory/"sentra-install-manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size>8*1024*1024:
            raise EffectRejected("installed ACP manifest unavailable")
        manifest=json.loads(manifest_path.read_text(encoding="utf8"))
        if digest(manifest.get("plan"))!=digest(asdict(plan)) or not isinstance(manifest.get("files"),dict):
            raise EffectRejected("installed ACP manifest does not match selected plan")
        candidates=[]
        for name,target in manifest.get("links",{}).items():
            path=directory.joinpath(*self.member(name).parts)
            expected=directory.joinpath(*self.member(target).parts).resolve()
            if not path.is_symlink() or path.resolve()!=expected or not expected.is_relative_to(directory):
                raise EffectRejected("installed ACP package link changed")
        for name,sha in manifest["files"].items():
            path=directory.joinpath(*self.member(name).parts)
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory) or self.file_hash(path)!=sha:
                raise EffectRejected("installed ACP distribution changed")
            if sha==executable_sha256:candidates.append(path)
        if len(candidates)!=1:raise EffectRejected("installed ACP entrypoint pin is ambiguous")
        actual_files={str(p.relative_to(directory)).replace("\\","/") for p in directory.rglob("*") if p.is_file() or p.is_symlink()}
        expected_files=set(manifest["files"])|set(manifest.get("links",{}))|{"sentra-install-manifest.json"}
        if actual_files!=expected_files:raise EffectRejected("installed ACP file inventory changed")
        installed=str(candidates[0]);manifest_sha=digest({"files":manifest["files"],"links":manifest.get("links",{})})
        db=self.control.store.connect("interop_installations")
        try:
            with db:
                row=db.execute("SELECT * FROM acp_installed WHERE owner=? AND agent=? AND version=?",
                               (self.owner,plan.agent_id,plan.version)).fetchone()
                if row and (row["plan"]!=plan.fingerprint or row["manifest"]!=manifest_sha or row["path"]!=installed):
                    raise EffectRejected("ACP installation ledger differs from immutable files")
                if row is None:db.execute("INSERT INTO acp_installed VALUES(?,?,?,?,?,?)",(
                    self.owner,plan.agent_id,plan.version,plan.fingerprint,manifest_sha,installed))
        finally:db.close()
        return {"installed":True,"agent_id":plan.agent_id,"version":plan.version,"path":installed,
                "manifest_sha256":manifest_sha,"executable_sha256":executable_sha256,"launch_authorized":False,"reconciled":True}

    @staticmethod
    def member(name):
        if not isinstance(name,str) or any(c in name for c in "\0:"):
            raise ValueError("invalid ACP archive member")
        win=PureWindowsPath(name);path=PurePosixPath(name.replace("\\","/"))
        if win.drive or win.is_absolute() or path.is_absolute() or ".." in path.parts:
            raise ValueError("ACP archive traversal")
        reserved={"CON","PRN","AUX","NUL",*("COM"+str(i) for i in range(1,10)),*("LPT"+str(i) for i in range(1,10))}
        if any(p.endswith((" ",".")) or p.split(".")[0].upper() in reserved for p in path.parts):
            raise ValueError("ACP archive Windows name collision")
        return path

    def extract(self,archive,stage):
        total=0;seen=set()
        def target(name,size):
            nonlocal total
            rel=self.member(name);key=str(rel).casefold()
            if key in seen:raise ValueError("ACP archive case-insensitive collision")
            seen.add(key);total+=size
            if total>512*1024*1024 or len(seen)>20000:raise ValueError("ACP archive extraction limit")
            path=stage.joinpath(*rel.parts)
            if not path.resolve().is_relative_to(stage):raise ValueError("ACP archive escape")
            return path
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as source:
                for entry in source.infolist():
                    self.checkpoint()
                    mode=(entry.external_attr>>16)&0o170000
                    if mode not in {0,0o100000,0o040000}:raise ValueError("ACP archive links/special files denied")
                    path=target(entry.filename,entry.file_size)
                    if entry.is_dir():path.mkdir(parents=True,exist_ok=True);continue
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with source.open(entry) as inp,path.open("xb") as out:
                        self._copy(inp,out,entry.file_size)
        else:
            with tarfile.open(archive,"r:*") as source:
                for entry in source:
                    self.checkpoint()
                    if not entry.isdir() and not entry.isfile():raise ValueError("ACP tar links/special files denied")
                    path=target(entry.name,entry.size)
                    if entry.isdir():path.mkdir(parents=True,exist_ok=True);continue
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with source.extractfile(entry) as inp,path.open("xb") as out:self._copy(inp,out,entry.size)
                    path.chmod(entry.mode & 0o755)

    @staticmethod
    def _copy(inp,out,size):
        copied=0
        while chunk:=inp.read(65536):
            copied+=len(chunk)
            if copied>size:raise ValueError("ACP archive member size mismatch")
            out.write(chunk)
        if copied!=size:raise ValueError("ACP archive member truncated")

    async def _download(self,url,destination,sha256):
        import httpx
        total=0;hasher=hashlib.sha256()
        async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=60) as client:
            self.checkpoint()
            async with client.stream("GET",url) as response:
                if response.status_code!=200:raise RuntimeError("ACP distribution download failed")
                with destination.open("xb") as out:
                    async for chunk in response.aiter_bytes():
                        self.checkpoint();total+=len(chunk)
                        if total>128*1024*1024:raise ValueError("ACP archive download limit")
                        hasher.update(chunk);out.write(chunk)
        if hasher.hexdigest()!=sha256:raise ValueError("ACP archive approved digest mismatch")

    async def _run(self,executable,argv,cwd,sha256):
        self.checkpoint()
        if self.file_hash(executable)!=sha256:raise EffectRejected("ACP installer runner pin changed")
        from .mcp_stdio import _minimal_windows_runtime_env
        process,owner=await spawn_owned(str(executable),tuple(argv),cwd=str(cwd),env=_minimal_windows_runtime_env(),
            stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,
            checkpoint=self.checkpoint)
        try:
            code=await asyncio.wait_for(process.wait(),120)
            self.checkpoint()
            if code!=0:raise RuntimeError("ACP distribution installer failed")
        finally:await owner.close()

    async def install(self,request,*,plan,executable_sha256,lock_text=None,runner=None,entrypoint=None,
                      archive_sha256=None):
        if not isinstance(plan,ACPInstallationPlan) or not AGENT_ID.fullmatch(plan.agent_id):
            raise ValueError("approved ACP installation plan required")
        lock_sha=digest(lock_text) if lock_text is not None else None
        runner_sha=runner.get("sha256") if isinstance(runner,dict) else None
        if request.capability_id!="acp:install" or request.arguments!=self.request_arguments(plan,
                executable_sha256=executable_sha256,lock_sha256=lock_sha,runner_sha256=runner_sha):
            raise EffectRejected("ACP install intent differs from selected distribution")
        self.checkpoint()
        if not re.fullmatch(r"[a-f0-9]{64}",executable_sha256):raise ValueError("independent ACP entrypoint content pin required")
        db=self.control.store.connect("interop_installations")
        try:
            rows=db.execute("SELECT * FROM acp_installed WHERE owner=? AND agent=?",(self.owner,plan.agent_id)).fetchall()
        finally:db.close()
        current=self.version_key(plan.version)
        for row in rows:
            if self.version_key(row["version"])>current:raise EffectRejected("ACP version downgrade denied")
            if row["version"]==plan.version:
                if row["plan"]!=plan.fingerprint:raise EffectRejected("ACP installed version has another plan")
                return self.reconcile(plan=plan,executable_sha256=executable_sha256)
        final=self.root/plan.agent_id/plan.version
        if final.exists():return self.reconcile(plan=plan,executable_sha256=executable_sha256)
        final.parent.mkdir(parents=True,exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix=plan.agent_id+"-",dir=self.root)).resolve()
        # Staging is retained on failure for diagnosis. No recursive delete or
        # automatic replacement of a distribution that may own live processes.
        if plan.distribution_kind=="binary":
            approved=archive_sha256
            if (not isinstance(approved,str) or not re.fullmatch(r"[a-f0-9]{64}",approved)
                    or plan.archive_sha256 is not None and approved!=plan.archive_sha256):
                raise EffectRejected("independently approved archive pin required")
            archive=stage/"distribution.archive";files=stage/"files";files.mkdir()
            await self._download(plan.archive,archive,approved)
            await asyncio.to_thread(self.extract,archive,files)
            entry=files.joinpath(*self.member(plan.executable_relative).parts)
        else:
            if not isinstance(runner,dict) or not isinstance(lock_text,str) or len(lock_text.encode())>2*1024*1024:
                raise EffectRejected("ACP package distribution requires pinned host runner and full lock")
            executable=Path(runner["executable"]).resolve(strict=True)
            if not executable.is_file() or not executable.is_absolute():raise ValueError("native installer runner required")
            files=stage/"files";files.mkdir()
            if plan.distribution_kind=="npx":
                lock=json.loads(lock_text)
                package=plan.package.rsplit("@",1)[0]
                if (lock.get("lockfileVersion")!=3 or lock.get("packages",{}).get("",{}).get("dependencies")!={package:plan.version}
                        or any(not row.get("integrity") for name,row in lock["packages"].items() if name)):
                    raise ValueError("ACP npm lock must contain exact selected version and integrity for every package")
                (files/"package-lock.json").write_text(lock_text,encoding="utf8")
                (files/"package.json").write_text(canonical({"private":True,"dependencies":{package:plan.version}}),encoding="utf8")
                cli=Path(runner["npm_cli"]).resolve(strict=True)
                if self.file_hash(cli)!=runner["npm_cli_sha256"]:raise ValueError("npm cli pin mismatch")
                await self._run(executable,[str(cli),"ci","--ignore-scripts","--no-audit","--no-fund","--cache",str(stage/"cache")],files,runner_sha)
            elif plan.distribution_kind=="uvx":
                if plan.package not in lock_text or "--hash=sha256:" not in lock_text or any(
                        line.lstrip().startswith(("-e ","--extra-index-url","--trusted-host")) for line in lock_text.splitlines()):
                    raise ValueError("ACP Python distribution requires hash-locked selected version")
                requirements=stage/"requirements.txt";requirements.write_text(lock_text,encoding="utf8")
                await self._run(executable,["pip","install","--target",str(files),"--require-hashes","--only-binary",":all:",
                    "--no-cache","--no-progress","-r",str(requirements)],stage,runner_sha)
            else:raise ValueError("unsupported ACP distribution")
            if not isinstance(entrypoint,str):raise ValueError("host approved installed entrypoint required")
            entry=files.joinpath(*self.member(entrypoint).parts)
        if not entry.is_file() or entry.is_symlink() or self.file_hash(entry)!=executable_sha256:
            raise ValueError("installed ACP entrypoint failed independent content pin")
        links={}
        for path in files.rglob("*"):
            if path.is_symlink():
                if not path.resolve().is_relative_to(files):raise ValueError("ACP package link escaped staging")
                links[str(path.relative_to(files)).replace("\\","/")]=str(path.resolve().relative_to(files)).replace("\\","/")
        manifest={str(p.relative_to(files)).replace("\\","/"):self.file_hash(p)
                  for p in files.rglob("*") if p.is_file() and not p.is_symlink()}
        (files/"sentra-install-manifest.json").write_text(canonical({"plan":asdict(plan),"files":manifest,"links":links}),encoding="utf8")
        self.checkpoint()
        if final.exists():raise EffectRejected("ACP immutable version already present; reconcile staging")
        files.rename(final)
        self.checkpoint()
        installed=str(final/entry.relative_to(files))
        db=self.control.store.connect("interop_installations")
        try:
            with db:db.execute("INSERT INTO acp_installed VALUES(?,?,?,?,?,?)",(self.owner,plan.agent_id,
                plan.version,plan.fingerprint,digest({"files":manifest,"links":links}),installed))
        finally:db.close()
        return {"installed":True,"path":installed,"version":plan.version,"executable_sha256":executable_sha256,
                "manifest_sha256":digest({"files":manifest,"links":links}),"distribution_kind":plan.distribution_kind,"launch_authorized":False,
                "environment_requires_launch_authorization":bool(plan.environment)}
