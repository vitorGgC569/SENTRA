"""Owned Node execution of an explicitly pinned installed Activepieces bundle.

All SDK store/file/context RPCs perform actual host work under the current
central fence. Unsupported services are denied, not replaced by fake helpers.
The owned group/job is closed on success, error, timeout and cancellation.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .acp_process import spawn_owned
from .workflow_contracts import ActivityReceipt, canonical, digest


@dataclass(frozen=True)
class InstalledPieceBundle:
    piece_name: str
    piece_version: str
    module_path: str
    export_name: str
    package_json: str
    module_sha256: str
    lock_file: str
    lock_sha256: str


class OwnedPieceSDKBackend:
    def __init__(self,*,node_executable,install_root,bundles,artifact_root,project_id,
                 flow_id,flow_version,project_external_id=None,file_publisher=None,
                 schedule_handler=None,webhook_url=None,server_context=None,timeout=120):
        self.node=Path(node_executable)
        self.root=Path(install_root).resolve()
        self.artifact_root=Path(artifact_root).resolve()
        if not self.node.is_absolute() or not self.root.is_dir() or not self.artifact_root.is_relative_to(self.root):
            raise ValueError("piece executable/install/artifact roots must be explicit and contained")
        self.artifact_root.mkdir(parents=True,exist_ok=True)
        bundles=tuple(bundles)
        self.bundles={(b.piece_name,b.piece_version):b for b in bundles}
        if len(self.bundles)!=len(bundles) or not project_id or not flow_id or not flow_version or not 0<timeout<=3600:
            raise ValueError("invalid owned piece context/version catalog")
        self.project_id,self.flow_id,self.flow_version=project_id,flow_id,flow_version
        self.project_external_id,self.file_publisher=project_external_id,file_publisher
        self.schedule_handler,self.webhook_url,self.server_context=schedule_handler,webhook_url,server_context
        self.timeout=timeout
        self.runner=Path(__file__).with_name("activepieces_worker.mjs").resolve()
        self.active={}

    @property
    def configuration_sha256(self):
        return digest({"node":str(self.node),"root":str(self.root),"artifact_root":str(self.artifact_root),
            "project":self.project_id,"flow":self.flow_id,"flow_version":self.flow_version,
            "project_external_id":self.project_external_id,"webhook_url":self.webhook_url,
            "server_origin":{k:self.server_context.get(k) for k in ("apiUrl","publicUrl")} if isinstance(self.server_context,dict) else None,
            "file_publisher_configured":callable(self.file_publisher),"schedule_configured":callable(self.schedule_handler),
            "bundles":[asdict(v) for k,v in sorted(self.bundles.items())],
            "runner_sha256":hashlib.sha256(self.runner.read_bytes()).hexdigest()})

    def _verify_bundle(self,bundle):
        files=[]
        for raw in (bundle.module_path,bundle.package_json,bundle.lock_file):
            path=Path(raw)
            if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(self.root) or not path.is_file():
                raise ValueError("piece bundle path outside approved installed root")
            files.append(path)
        module,package,lock=files
        if (hashlib.sha256(module.read_bytes()).hexdigest()!=bundle.module_sha256 or
            hashlib.sha256(lock.read_bytes()).hexdigest()!=bundle.lock_sha256): raise ValueError("installed piece/lock digest mismatch")
        metadata=json.loads(package.read_text(encoding="utf8"))
        if metadata.get("name")!=bundle.piece_name or metadata.get("version")!=bundle.piece_version:
            raise ValueError("installed piece package version mismatch")
        return module

    def preflight(self,descriptor,member,hook):
        if not self.node.is_file():
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="DEPENDENCY_UNAVAILABLE",retryable=True)
        bundle=self.bundles.get((descriptor.name,descriptor.version))
        if bundle is None: return ActivityReceipt("FAILED","NOT_STARTED",failure_type="PIECE_NOT_INSTALLED")
        try: self._verify_bundle(bundle)
        except (ValueError,OSError): return ActivityReceipt("FAILED","NOT_STARTED",failure_type="BUNDLE_PIN_MISMATCH")
        if json.loads(descriptor.metadata_json).get("contextInfo",{}).get("version")!="2":
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="CONTEXT_VERSION_UNSUPPORTED")
        if hook in {"onEnable","onRenew","trigger-run"}:
            trigger=descriptor.member(member,hook)
            if trigger.get("type") in {"WEBHOOK","APP_WEBHOOK"} and not self.webhook_url:
                return ActivityReceipt("FAILED","NOT_STARTED",failure_type="TRIGGER_CALLBACK_UNAVAILABLE")
            if trigger.get("type")=="APP_WEBHOOK":
                return ActivityReceipt("FAILED","NOT_STARTED",failure_type="APP_WEBHOOK_CONTEXT_UNSUPPORTED")
            if hook=="onEnable" and trigger.get("type")=="POLLING" and not callable(self.schedule_handler):
                return ActivityReceipt("FAILED","NOT_STARTED",failure_type="TRIGGER_SCHEDULER_UNAVAILABLE")
        return None

    async def _rpc(self,frame,*,request,descriptor,auth,store,updates,files):
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        if context is None: raise PermissionError("piece context RPC requires central physical admission")
        context.checkpoint()
        method,args=frame.get("method"),frame.get("args")
        if not isinstance(args,dict): raise ValueError("invalid piece RPC arguments")
        if method=="metadata.verify":
            if canonical(args.get("metadata"))!=descriptor.metadata_json: raise ValueError("piece SDK metadata/schema changed")
            return True
        if method in {"store.get","store.put","store.delete"}:
            scope=args.get("scope") or "FLOW"
            if scope not in {"FLOW","COLLECTION"}: raise ValueError("unknown SDK store scope")
            owned_scope=digest({"principal":request.principal_id,"machine":request.machine_id,"work":request.work_item_id,
                "project":self.project_id,"flow":self.flow_id if scope=="FLOW" else None})
            return store.storage(owned_scope,method.split(".")[1],args.get("key"),args.get("value"))
        if method=="connections.get":
            if args.get("key")!=request.arguments.get("connection_id") or auth is None:
                raise PermissionError("piece attempted another connection")
            return auth
        if method=="project.externalId":
            if self.project_external_id is None: raise ValueError("project external ID not configured")
            return self.project_external_id
        if method=="output.update":
            canonical(args.get("data"))
            updates.append(store.artifact(request.arguments["invocation_id"],args.get("data"),kind="piece-progress")); return None
        if method=="tags.add":
            name=args.get("name")
            if not isinstance(name,str) or not 1<=len(name)<=256: raise ValueError("invalid piece tag")
            updates.append(store.artifact(request.arguments["invocation_id"],{"tag":name},kind="piece-tag")); return None
        if method in {"files.write","files.upload"}:
            file_name=args.get("fileName")
            if not isinstance(file_name,str) or not file_name or Path(file_name).name!=file_name or any(c in file_name for c in "\\/:\0"):
                raise ValueError("piece file must be a simple filename")
            data=base64.b64decode(args.get("data",""),validate=True)
            if len(data)>16*1024*1024: raise ValueError("piece file exceeds limit")
            hash_value=hashlib.sha256(data).hexdigest()
            target=self.artifact_root/(hash_value+Path(file_name).suffix[:20])
            if not target.resolve().is_relative_to(self.root): raise ValueError("piece artifact escaped approved root")
            if target.is_symlink(): raise ValueError("piece artifact symlink denied")
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest()!=hash_value: raise ValueError("piece artifact collision")
            else:
                with target.open("xb") as output: output.write(data)
            files.append({"path":str(target),"sha256":hash_value,"file_name":file_name,"size":len(data),"kind":"piece-file"})
            if method=="files.write": return str(target)
            if not callable(self.file_publisher): raise ValueError("files.upload needs a real host file publisher")
            uploaded=self.file_publisher(request,target,file_name)
            if inspect.isawaitable(uploaded): uploaded=await uploaded
            if not isinstance(uploaded,dict) or not uploaded.get("id") or not str(uploaded.get("url","")).startswith("https://"):
                raise ValueError("file publisher did not return a real HTTPS artifact URL")
            return uploaded
        if method=="schedule.set":
            if not callable(self.schedule_handler): raise ValueError("trigger scheduling requires real host integration")
            result=self.schedule_handler(request,args)
            return await result if inspect.isawaitable(result) else result
        raise PermissionError("SDK context service not implemented in this explicit profile")

    async def execute(self,request,descriptor,props,auth,store,heartbeat,*,trigger_payload=None):
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        if context is None: raise PermissionError("piece process must run in central physical boundary")
        bundle=self.bundles[(descriptor.name,descriptor.version)]
        module=self._verify_bundle(bundle)
        context.checkpoint()
        process,owner=await spawn_owned(str(self.node),(str(self.runner),),cwd=str(self.root),env={},
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
            limit=32*1024*1024+1,checkpoint=context.checkpoint)
        invocation=request.arguments["invocation_id"]
        self.active[invocation]=owner
        updates,files=[],[]
        payload={"version":1,"command":"execute","module_path":str(module),"export_name":bundle.export_name,
            "piece_name":descriptor.name,"piece_version":descriptor.version,"member":request.arguments["member"],
            "hook":request.arguments["hook"],"auth":auth,"props":props,"project_id":self.project_id,
            "flow_id":self.flow_id,"flow_version":self.flow_version,"operation_id":request.operation_id,
            "server":self.server_context,"webhook_url":self.webhook_url,"trigger_payload":trigger_payload}
        async def write(value):
            context.checkpoint()
            raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()+b"\n"
            if len(raw)>32*1024*1024: raise ValueError("piece stdin exceeds frame bound")
            process.stdin.write(raw); await process.stdin.drain()
        async def read():
            await write(payload)
            while True:
                raw=await process.stdout.readline()
                if not raw or len(raw)>32*1024*1024: return ActivityReceipt("UNCERTAIN","UNKNOWN",failure_type="PIECE_DISCONNECTED")
                def unique(pairs):
                    fields={}
                    for key,value in pairs:
                        if key in fields: raise ValueError("duplicate piece protocol field")
                        fields[key]=value
                    return fields
                frame=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite piece frame")))
                if not isinstance(frame,dict): raise ValueError("piece frame must be an object")
                heartbeat()
                if frame.get("type")=="rpc":
                    try:
                        value=await self._rpc(frame,request=request,descriptor=descriptor,auth=auth,store=store,updates=updates,files=files)
                        await write({"id":frame["id"],"value":value})
                    except Exception: await write({"id":frame.get("id"),"error":"CONTEXT_DENIED"})
                elif frame.get("type")=="started": continue
                elif frame.get("type")=="failure":
                    # Import/module initialization may already have effects;
                    # even a failure before run() is not a retry certificate.
                    return ActivityReceipt("UNCERTAIN","UNKNOWN",failure_type="PIECE_EXECUTION_UNKNOWN",artifacts=tuple([*files,*updates]))
                elif frame.get("type")=="result":
                    context.checkpoint()
                    return ActivityReceipt("SUCCEEDED","COMPLETED",frame.get("output"),artifacts=tuple([*files,*updates]))
                else: raise ValueError("unexpected piece worker frame")
        try:
            return await asyncio.wait_for(read(),self.timeout)
        finally:
            await asyncio.shield(owner.close())
            self.active.pop(invocation,None)
