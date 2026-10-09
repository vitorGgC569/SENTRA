"""Execute an explicitly pinned Grype binary against a frozen local SBOM."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time

from sentra_canvas.owned_process import TaskProcess
from .grype_gate import VulnerabilityGateError, evaluate_grype_json


def digest(path):
    sha=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):sha.update(block)
    return sha.hexdigest()


@dataclass(frozen=True)
class GrypeScanConfig:
    executable: str
    executable_sha256: str
    database_cache: str
    max_database_age_hours: int = 120
    timeout_seconds: int = 120
    max_report_bytes: int = 8_000_000

    def __post_init__(self):
        if (not Path(self.executable).is_absolute() or not Path(self.database_cache).is_absolute()
                or not re.fullmatch(r"[a-f0-9]{64}",self.executable_sha256)
                or type(self.max_database_age_hours) is not int or not 1<=self.max_database_age_hours<=720
                or type(self.timeout_seconds) is not int or not 1<=self.timeout_seconds<=600
                or type(self.max_report_bytes) is not int or not 65536<=self.max_report_bytes<=32_000_000):
            raise ValueError("invalid pinned Grype configuration")


def _run(config, args, *, cwd, limit):
    if digest(config.executable)!=config.executable_sha256:
        raise VulnerabilityGateError("Grype executable digest changed")
    env={k:v for k,v in os.environ.items() if k.upper() in {"PATH","SYSTEMROOT","WINDIR","TEMP","TMP","HOME","USERPROFILE"}}
    env.update({"GRYPE_CHECK_FOR_APP_UPDATE":"false","GRYPE_DB_AUTO_UPDATE":"false",
        "GRYPE_DB_CACHE_DIR":config.database_cache,"GRYPE_DB_VALIDATE_AGE":"true",
        "GRYPE_DB_MAX_ALLOWED_BUILT_AGE":str(config.max_database_age_hours)+"h",
        "GRYPE_DB_REQUIRE_UPDATE_CHECK":"false","GRYPE_DB_VALIDATE_BY_HASH_ON_START":"true"})
    options={"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}
    from sentra_runtime.effect_boundary import current_effect_context
    context=current_effect_context.get()
    if context is not None:context.checkpoint()
    child=TaskProcess([config.executable,"--config",str(Path(cwd)/"scanner-config.json"),*args],cwd=str(cwd),env=env,stdin=subprocess.DEVNULL,
                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,**options)
    results=queue.Queue();threads=[]
    def read(name, stream, bound):
        data=bytearray()
        try:
            for block in iter(lambda:stream.read(65536),b""):
                if len(data)+len(block)>bound:
                    child.terminate_tree();results.put((name,False,b""));return
                data.extend(block)
            results.put((name,True,bytes(data)))
        except (OSError,ValueError):results.put((name,False,b""))
    for name,stream,bound in (("stdout",child.process.stdout,limit),("stderr",child.process.stderr,65536)):
        thread=threading.Thread(target=read,args=(name,stream,bound),daemon=True);thread.start();threads.append(thread)
    try:
        code=child.process.wait(timeout=config.timeout_seconds)
        for thread in threads:thread.join(timeout=2)
        if code!=0 or any(thread.is_alive() for thread in threads):
            raise VulnerabilityGateError("Grype process failed; database/tool provisioning may be required")
        return code,results
    except subprocess.TimeoutExpired as exc:
        raise VulnerabilityGateError("Grype scan timed out") from exc
    finally:
        child.terminate_tree();child.process.wait(timeout=5)
        for stream in (child.process.stdout,child.process.stderr):stream.close()


def _command(config, args, *, cwd, limit):
    outputs={}
    code,events=_run(config,args,cwd=cwd,limit=limit)
    for _ in range(2):
        name,ok,data=events.get(timeout=2)
        if not ok:raise VulnerabilityGateError("Grype output limit exceeded")
        outputs[name]=data
    try:value=json.loads(outputs["stdout"])
    except (ValueError,UnicodeError,KeyError) as exc:raise VulnerabilityGateError("Grype returned invalid JSON output") from exc
    if not isinstance(value,dict):raise VulnerabilityGateError("Grype returned no JSON object")
    return outputs["stdout"]


def scan_sbom(config: GrypeScanConfig, sbom: Path, *, expected_sbom_sha256: str, fail_at="high"):
    sbom=Path(sbom).resolve(strict=True)
    if (not sbom.is_file() or sbom.stat().st_size>32_000_000
            or not re.fullmatch(r"[a-f0-9]{64}",expected_sbom_sha256)
            or digest(sbom)!=expected_sbom_sha256):
        raise VulnerabilityGateError("SBOM digest/bounds do not match declared artifact")
    if not Path(config.database_cache).is_dir():raise VulnerabilityGateError("Grype database cache missing")
    with tempfile.TemporaryDirectory(prefix="sentra-grype-") as directory:
        root=Path(directory)
        # Explicit config prevents inherited ~/.grype.yaml ignore rules from
        # making a release report appear clean. JSON is also valid YAML.
        (root/"scanner-config.json").write_text(json.dumps({"check-for-app-update":False,"ignore":[],
            "db":{"cache-dir":config.database_cache,"auto-update":False,"validate-age":True,
                  "max-allowed-built-age":str(config.max_database_age_hours)+"h",
                  "require-update-check":False,"validate-by-hash-on-start":True}}),encoding="utf-8")
        frozen=root/"input.json";frozen.write_bytes(sbom.read_bytes())
        if digest(frozen)!=expected_sbom_sha256:raise VulnerabilityGateError("SBOM changed during capture")
        status=json.loads(_command(config,["db","status","-o","json"],cwd=root,limit=65536))
        if status.get("valid") is not True or status.get("error") not in {None,""} or not isinstance(status.get("built"),str):
            raise VulnerabilityGateError("Grype database not valid")
        try:built=datetime.fromisoformat(status["built"].replace("Z","+00:00"))
        except ValueError as exc:raise VulnerabilityGateError("Grype database build timestamp invalid") from exc
        if built.tzinfo is None or not 0<=(datetime.now(timezone.utc)-built).total_seconds()<=config.max_database_age_hours*3600:
            raise VulnerabilityGateError("Grype database is obsolete or future dated")
        report=_command(config,["sbom:"+str(frozen),"-o","json"],cwd=root,limit=config.max_report_bytes)
        decision=evaluate_grype_json(report,fail_at=fail_at,expected_sha256=hashlib.sha256(report).hexdigest(),
                                     max_bytes=config.max_report_bytes)
        document=json.loads(report)
        if document.get("ignoredMatches"):
            raise VulnerabilityGateError("scan contains ignored vulnerabilities; explicit review required")
        descriptor=document.get("descriptor") or {}
        if descriptor.get("name")!="grype" or not isinstance(descriptor.get("version"),str):
            raise VulnerabilityGateError("Grype scanner descriptor missing")
        recommendations=[]
        for match in document["matches"]:
            vuln=match["vulnerability"];fix=vuln.get("fix") or {}
            versions=fix.get("versions",[])
            if not isinstance(versions,list) or any(not isinstance(v,str) or len(v)>256 for v in versions):
                raise VulnerabilityGateError("invalid fix versions")
            recommendations.append({"id":vuln["id"],"package":match["artifact"]["name"],
                "installed_version":match["artifact"]["version"],"fix_state":fix.get("state","unknown"),
                "fixed_versions":versions[:32],"fix_available":bool(versions),
                "matchers":sorted({d.get("matcher","") for d in match.get("matchDetails",[]) if isinstance(d,dict)})})
        return {"decision":asdict(decision),"sbom_sha256":expected_sbom_sha256,
            "scanner_sha256":config.executable_sha256,"scanner_version":descriptor["version"],
            "database_built":status["built"],"recommendations":recommendations,"report":report}


def scan_diff(previous, current):
    key=lambda finding:(finding["id"],finding["package"],finding["installed_version"])
    before={key(x):x for x in previous["recommendations"]};after={key(x):x for x in current["recommendations"]}
    return {"introduced":[after[k] for k in sorted(after.keys()-before.keys())],
            "resolved":[before[k] for k in sorted(before.keys()-after.keys())],
            "changed":[after[k] for k in sorted(before.keys()&after.keys()) if before[k]!=after[k]],
            "previous_sbom_sha256":previous["sbom_sha256"],"current_sbom_sha256":current["sbom_sha256"]}
