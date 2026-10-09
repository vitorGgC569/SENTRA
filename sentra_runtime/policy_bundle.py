"""Pinned OPA snapshot bundles: validate offline, publish atomically, keep last valid.

No services are started. The host serves resource() to its configured OPA
bundle plugin. Publishing is distinct from confirmed daemon activation.
"""
import asyncio
import hashlib
import json
import os
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sentra_interop.acp_process import spawn_owned
from .identity_state import ProtectedIdentityStore, identity_digest
from ._policy_http import strict_json


@dataclass(frozen=True)
class OPABundleCandidate:
    path: str
    sha256: str
    revision: str
    roots: tuple


class OPAOfflineValidator:
    def __init__(self,*,executable,executable_sha256,capabilities_file,capabilities_sha256,timeout=30):
        self.executable,self.capabilities=Path(executable),Path(capabilities_file)
        if not self.executable.is_absolute() or not self.capabilities.is_absolute() or not 0<timeout<=120:
            raise ValueError("explicit pinned OPA executable/capabilities required")
        self.executable_sha256,self.capabilities_sha256,self.timeout=executable_sha256,capabilities_sha256,timeout
    def _pins(self):
        for path,expected in ((self.executable,self.executable_sha256),(self.capabilities,self.capabilities_sha256)):
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                raise ValueError("OPA validator dependency absent/pin mismatch")
        cap=strict_json(self.capabilities.read_bytes())
        forbidden={"http.send","net.lookup_ip_addr","time.now_ns","uuid.rfc4122","rand.intn"}
        if not isinstance(cap.get("builtins"),list) or any(b.get("name") in forbidden for b in cap["builtins"]):
            raise ValueError("offline deterministic policy capabilities must exclude network/time/random builtins")
    async def _run(self,args,*,stdin=None):
        self._pins()
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        process,owner=await spawn_owned(str(self.executable),tuple(args),env={},stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,checkpoint=context.checkpoint if context else None)
        async def collect(stream):
            data=bytearray()
            while True:
                chunk=await stream.read(8192)
                if not chunk: return bytes(data)
                data.extend(chunk)
                if len(data)>2_000_000: raise ValueError("OPA validation output exceeds bound")
        async def run():
            process.stdin.write(stdin or b""); await process.stdin.drain(); process.stdin.close()
            stdout,stderr=await asyncio.gather(collect(process.stdout),collect(process.stderr))
            code=await process.wait()
            if code: raise ValueError("OPA official CLI rejected candidate; diagnostics omitted from public evidence")
            return stdout
        try:
            result=await asyncio.wait_for(run(),self.timeout)
            if context: context.checkpoint()
            return result
        finally: await asyncio.shield(owner.close())
    async def validate(self,candidate,*,acceptance_cases):
        if not isinstance(acceptance_cases,(tuple,list)) or not acceptance_cases: raise ValueError("meaningful policy acceptance cases required")
        await self._run(("check","--bundle",candidate.path,"--strict","--capabilities",str(self.capabilities)))
        for case in acceptance_cases:
            if not isinstance(case,dict) or set(case)!={"input","expected_allow"} or type(case["expected_allow"]) is not bool:
                raise ValueError("invalid policy acceptance case")
            raw=await self._run(("eval","--bundle",candidate.path,"--capabilities",str(self.capabilities),"--stdin-input","--format=json","data.sentra.allow"),
                stdin=json.dumps(case["input"],allow_nan=False).encode())
            result=strict_json(raw).get("result")
            if (not isinstance(result,list) or len(result)!=1 or len(result[0].get("expressions",[]))!=1 or
                type(result[0]["expressions"][0].get("value")) is not bool or result[0]["expressions"][0]["value"]!=case["expected_allow"]):
                raise ValueError("OPA candidate acceptance decision undefined/mismatched")
        return {"checked_by":"official pinned OPA CLI","cases":len(acceptance_cases),"sha256":candidate.sha256,"revision":candidate.revision}


class OPABundleManager:
    def __init__(self,*,root,workspace,store:ProtectedIdentityStore,validator:OPAOfflineValidator,bundle_name="sentra",roots=("sentra",)):
        self.root,workspace=Path(root).resolve(),Path(workspace).resolve()
        if not self.root.is_relative_to(workspace) or self.root==workspace or not bundle_name or roots!=("sentra",):
            raise ValueError("bundle publication must be scoped to sentra root")
        self.root.mkdir(parents=True,exist_ok=True)
        self.store,self.validator,self.bundle_name,self.roots=store,validator,bundle_name,roots
        self.key="opa-bundle:"+bundle_name
    def stage(self,archive,*,expected_sha256,expected_revision):
        source=Path(archive)
        if not source.is_absolute() or source.is_symlink() or not source.is_file() or source.stat().st_size>16_000_000:
            raise ValueError("bounded explicit OPA archive required")
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected_sha256: raise ValueError("bundle archive pin mismatch")
        with tarfile.open(source,"r:gz") as tar:
            members=tar.getmembers(); names=set(); total=0; manifest=None
            if len(members)>1000: raise ValueError("bundle member count exceeds bound")
            for member in members:
                path=PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or "\\" in member.name or not (member.isfile() or member.isdir()) or member.name in names:
                    raise ValueError("unsafe/duplicate bundle member")
                names.add(member.name); total+=member.size
                if total>32_000_000: raise ValueError("uncompressed bundle exceeds bound")
                if member.name in {".manifest","./.manifest"}:
                    manifest=strict_json(tar.extractfile(member).read())
            if (not isinstance(manifest,dict) or manifest.get("revision")!=expected_revision or not isinstance(expected_revision,str)
                or not 1<=len(expected_revision)<=128 or tuple(manifest.get("roots",()))!=self.roots
                or manifest.get("rego_version",1)!=1 or any(n.endswith("patch.json") for n in names)):
                raise ValueError("versioned snapshot manifest required; delta/foreign root refused")
        destination=self.root/(expected_sha256+".tar.gz")
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=expected_sha256: raise ValueError("staged bundle collision")
        else:
            temporary=self.root/(uuid.uuid4().hex+".pending")
            with temporary.open("xb") as handle: handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary,destination)
        return OPABundleCandidate(str(destination),expected_sha256,expected_revision,self.roots)
    async def activate(self,candidate,*,acceptance_cases,trusted_admin_authorize):
        if not callable(trusted_admin_authorize) or trusted_admin_authorize(self.bundle_name,candidate.revision,candidate.sha256) is not True:
            raise PermissionError("CorePDP/host policy deployment authorization required")
        path=Path(candidate.path).resolve()
        if not path.is_relative_to(self.root) or hashlib.sha256(path.read_bytes()).hexdigest()!=candidate.sha256:
            raise ValueError("candidate changed since staging")
        prior=self.store.get(self.key)
        if prior and not prior["value"].get("runtime_activation_confirmed"):
            raise ValueError("previous published revision still needs runtime activation/reconciliation")
        pin_key="opa-revision:"+identity_digest({"bundle":self.bundle_name,"revision":candidate.revision})
        pin=self.store.get(pin_key)
        if pin and pin["value"]["sha256"]!=candidate.sha256: raise ValueError("OPA revision already bound to another archive")
        evidence=await self.validator.validate(candidate,acceptance_cases=acceptance_cases)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=candidate.sha256: raise ValueError("bundle changed during validation")
        if pin is None: self.store.put(pin_key,{"sha256":candidate.sha256,"revision":candidate.revision})
        value={"revision":candidate.revision,"sha256":candidate.sha256,"path":candidate.path,"validation":evidence,
            "previous":{k:v for k,v in prior["value"].items() if k!="previous"} if prior else None,
            "confirmed_revision":prior["value"].get("confirmed_revision") if prior else None,"runtime_activation_confirmed":False}
        self.store.put(self.key,value,expected_revision=prior["revision"] if prior else None)
        return {"published_revision":candidate.revision,"runtime_activation_confirmed":False,"last_valid_preserved_on_rejection":True}
    def active_revision(self):
        record=self.store.get(self.key)
        return record["value"].get("confirmed_revision") if record else None
    def published_revision(self):
        record=self.store.get(self.key)
        return record["value"]["revision"] if record else None
    def resource(self):
        record=self.store.get(self.key)
        if record is None: raise FileNotFoundError("no validated bundle published")
        value=record["value"]; path=Path(value["path"]).resolve()
        if not path.is_relative_to(self.root): raise ValueError("published bundle escaped root")
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value["sha256"]: raise ValueError("published bundle modified")
        return {"body":raw,"content_type":"application/gzip","etag":'"'+value["sha256"]+'"',"revision":value["revision"]}
    def accept_status(self,status,*,trusted_instance_authorize):
        if not callable(trusted_instance_authorize) or trusted_instance_authorize(status.get("labels",{})) is not True:
            raise PermissionError("authenticated OPA instance status required")
        record=self.store.get(self.key)
        if record is None: raise FileNotFoundError("no bundle projection")
        bundle=status.get("bundles",{}).get(self.bundle_name,{})
        if bundle.get("active_revision")!=record["value"]["revision"] or bundle.get("code") or bundle.get("errors"):
            previous=record["value"].get("previous")
            if previous and bundle.get("active_revision")==previous["revision"] and (bundle.get("code") or bundle.get("errors")):
                self.store.put(self.key,previous,expected_revision=record["revision"])
                return {"runtime_activation_confirmed":True,"candidate_rejected":True,"last_valid_revision":previous["revision"]}
            return {"runtime_activation_confirmed":False,"last_valid_revision":record["value"].get("confirmed_revision")}
        value=record["value"]; value["runtime_activation_confirmed"]=True; value["confirmed_revision"]=value["revision"]
        self.store.put(self.key,value,expected_revision=record["revision"])
        return {"runtime_activation_confirmed":True,"revision":value["revision"]}
