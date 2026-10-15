"""Copy an owner-selected RustDesk build into private content-pinned storage.

This validates configured bytes and source metadata; it neither compiles a
native build nor authenticates its author, login or remote desktop availability.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from sentra_remote.windows_paths import filesystem_path, resolved_path


def _io(path):
    return Path(filesystem_path(Path(path)))


def _hash(path):
    value=hashlib.sha256()
    with _io(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):value.update(chunk)
    return value.hexdigest()


def pinned_rustdesk_bundle(*,executable,executable_sha256,build_manifest,source_revision,
                           private_root,max_bundle_bytes=2*1024*1024*1024):
    if not re.fullmatch("[0-9a-f]{64}",executable_sha256 or "") or not re.fullmatch("[0-9a-f]{40}",source_revision or ""):
        raise ValueError("explicit native executable/source pins required")
    if type(max_bundle_bytes) is not int or not 1<=max_bundle_bytes<=4*1024*1024*1024:
        raise ValueError("invalid native bundle byte bound")
    exe=Path(executable);manifest_file=Path(build_manifest)
    if not exe.is_absolute() or not manifest_file.is_absolute():raise ValueError("absolute native build paths required")
    exe=resolved_path(exe,strict=True);manifest_file=resolved_path(manifest_file,strict=True)
    if not _io(exe).is_file() or not _io(manifest_file).is_file() or _io(manifest_file).stat().st_size>65536:
        raise ValueError("bounded native build manifest required")
    source_root=exe.parent
    manifest=json.loads(_io(manifest_file).read_text(encoding="utf-8"))
    if (not isinstance(manifest,dict) or manifest.get("extension")!="sentra-peer-gate-v1"
            or manifest.get("stock_cli_supported") is not False or manifest.get("source_revision")!=source_revision
            or manifest.get("executable_sha256")!=executable_sha256):
        raise ValueError("configured native build manifest/source pin mismatch")
    files=manifest.get("bundle_sha256")
    if not isinstance(files,dict) or not 1<=len(files)<=10000:raise ValueError("native bundle file pins required")
    if os.name=="nt" and "librustdesk.dll" not in files:raise ValueError("native RustDesk library pin required")
    files=dict(files)
    if exe.name in files and files[exe.name]!=executable_sha256:raise ValueError("native launcher bundle pin conflict")
    files[exe.name]=executable_sha256
    assets=[];size=0
    for name,expected in files.items():
        if (not isinstance(name,str) or not name or not isinstance(expected,str) or not re.fullmatch("[0-9a-f]{64}",expected)
                or "\\" in name or ":" in name or Path(name).is_absolute() or ".." in Path(name).parts
                or Path(name).as_posix()!=name or name=="sentra-build-manifest.json"):
            raise ValueError("invalid native bundle asset")
        path=resolved_path(source_root/name,strict=True)
        if not path.is_relative_to(source_root) or not _io(path).is_file():raise ValueError("native asset outside build root")
        size+=_io(path).stat().st_size
        if size>max_bundle_bytes:raise ValueError("native build exceeds byte bound")
        assets.append((name,path,expected))
    raw=json.dumps(manifest,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(",",":")).encode()
    identity=hashlib.sha256(raw+b"\0"+exe.name.encode()+b"\0"+executable_sha256.encode()).hexdigest()
    private=resolved_path(Path(private_root),strict=True)
    if not _io(private).is_dir():raise ValueError("private native build directory required")
    target=private/identity
    def verify():
        resolved=resolved_path(target,strict=True)
        if resolved.parent!=private:raise ValueError("private native bundle root changed")
        if _io(resolved/"sentra-build-manifest.json").read_bytes()!=raw:raise ValueError("private native manifest changed")
        for name,_,expected in assets:
            path=resolved_path(resolved/name,strict=True)
            if not path.is_relative_to(resolved) or not _io(path).is_file() or _hash(path)!=expected:
                raise ValueError("private native bundle pin mismatch")
        return {"executable":str(resolved/exe.name),"build_manifest":str(resolved/"sentra-build-manifest.json"),
            "bundle_root":str(resolved),"bundle_sha256":identity,"source_revision":source_revision,
            "native_execution_verified":False}
    if _io(target).exists():return verify()
    temporary=private/(".candidate-"+uuid.uuid4().hex);_io(temporary).mkdir(mode=0o700)
    try:
        copied=0
        for name,source,expected in assets:
            destination=temporary/name;_io(destination.parent).mkdir(parents=True,exist_ok=True)
            value=hashlib.sha256()
            with _io(source).open("rb") as incoming,_io(destination).open("xb") as outgoing:
                for chunk in iter(lambda:incoming.read(1024*1024),b""):
                    copied+=len(chunk)
                    if copied>max_bundle_bytes:raise ValueError("native build grew beyond byte bound")
                    value.update(chunk);outgoing.write(chunk)
                outgoing.flush();os.fsync(outgoing.fileno())
            if value.hexdigest()!=expected:raise ValueError("native build asset pin mismatch")
        with _io(temporary/"sentra-build-manifest.json").open("xb") as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        try:os.rename(filesystem_path(temporary),filesystem_path(target))
        except OSError:
            if not _io(target).exists():raise
        return verify()
    finally:
        if _io(temporary).exists():
            resolved=resolved_path(temporary,strict=True)
            if resolved.parent==private and resolved.name.startswith(".candidate-"):
                shutil.rmtree(filesystem_path(resolved))
