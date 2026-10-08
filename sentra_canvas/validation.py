"""Bounded verification of caller-declared output files, without model judgments."""
import hashlib
import os
from pathlib import Path,PureWindowsPath
import re
import stat
import time

MAX_FILE_BYTES=16*1024*1024
MAX_TOTAL_BYTES=64*1024*1024


def normalize_checks(checks):
    if checks is None:return []
    if not isinstance(checks,list) or len(checks)>16:raise ValueError("checks must contain at most 16 files")
    result=[];paths=set()
    for check in checks:
        if not isinstance(check,dict) or set(check)-{"path","sha256","text","mode"}:
            raise ValueError("unsupported output check")
        value=check.get("path")
        if not isinstance(value,str) or not 1<=len(value)<=1024 or re.search(r'[\x00-\x1f:<>"|?*]',value):
            raise ValueError("invalid output path")
        path=PureWindowsPath(value)
        if path.is_absolute() or path.drive or path.root or ".." in path.parts:
            raise ValueError("output checks must stay relative to the workspace")
        normalized=path.as_posix()
        if normalized in {".",""} or normalized.casefold() in paths:raise ValueError("duplicate or empty output path")
        paths.add(normalized.casefold())
        if ("sha256" in check)==("text" in check):raise ValueError("provide exactly one expected text or SHA-256")
        if "text" in check:
            text=check["text"]
            if not isinstance(text,str) or len(text)>4000:raise ValueError("expected text must be at most 4000 characters")
            if check.get("mode","text")!="text":raise ValueError("expected text requires text mode")
            mode="text"
            digest=hashlib.sha256(text.replace("\r\n","\n").replace("\r","\n").encode("utf-8")).hexdigest()
        else:
            digest=check["sha256"]
            if not isinstance(digest,str) or not re.fullmatch(r"[a-fA-F0-9]{64}",digest):raise ValueError("invalid expected SHA-256")
            digest=digest.lower()
            mode=check.get("mode","bytes")
            if mode not in {"bytes","text"}:raise ValueError("invalid check mode")
        result.append({"path":normalized,"sha256":digest,"mode":mode})
    return result


def verify_files(root,checks):
    root=Path(root).resolve(strict=True)
    outcomes=[];total=0;outputs=[];deadline=time.monotonic()+10
    for index,check in enumerate(checks):
        outcome={"index":index,"expected_sha256":check["sha256"],"passed":False}
        try:
            target=(root/check["path"]).resolve(strict=True)
            if not target.is_relative_to(root):raise ValueError("outside_workspace")
            before=target.stat()
            if not stat.S_ISREG(before.st_mode):raise ValueError("not_regular_file")
            if before.st_size>MAX_FILE_BYTES or total+before.st_size>MAX_TOTAL_BYTES:raise ValueError("verification_size_limit")
            digest=hashlib.sha256();size=0;text_bytes=bytearray() if check.get("mode")=="text" else None
            with target.open("rb") as stream:
                opened=os.fstat(stream.fileno())
                if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino):raise ValueError("file_changed")
                while chunk:=stream.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_FILE_BYTES or total+size>MAX_TOTAL_BYTES:raise ValueError("verification_size_limit")
                    if time.monotonic()>deadline:raise ValueError("verification_deadline")
                    digest.update(chunk)
                    if text_bytes is not None:text_bytes.extend(chunk)
                after=os.fstat(stream.fileno())
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or size!=after.st_size:
                raise ValueError("file_changed")
            file_digest=digest.hexdigest();total+=size
            actual=file_digest
            if text_bytes is not None:
                try:text=text_bytes.decode("utf-8").replace("\r\n","\n").replace("\r","\n")
                except UnicodeError:raise ValueError("invalid_utf8") from None
                actual=hashlib.sha256(text.encode("utf-8")).hexdigest()
            outcome.update(actual_sha256=actual,file_sha256=file_digest,size_bytes=size,passed=actual==check["sha256"])
            if outcome["passed"]:outputs.append((index,target,file_digest))
            else:outcome["error"]="content_mismatch"
        except (OSError,ValueError) as exc:
            outcome["error"]=str(exc) if isinstance(exc,ValueError) else "file_unavailable"
        outcomes.append(outcome)
    return {"passed":bool(checks) and all(item["passed"] for item in outcomes),"checks":outcomes},outputs
