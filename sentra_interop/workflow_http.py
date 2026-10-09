"""Native Activepieces HTTP execution of a version-pinned stored step.

Uses inspected /v1/flows, /v1/sample-data/test-step and /v1/flow-runs APIs.
Test-step executes real piece effects. It is not a dry-run or an invented
generic /execute endpoint. Runtime inputs come from the stored AP flow; the
SENTRA configuration must pin that step snapshot. Dynamic props use the SDK
worker backend instead. HTTP acknowledgements do not prove completion.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit, quote

from .workflow_contracts import ActivityReceipt, digest, ident


class WorkflowHTTPStatus(RuntimeError):
    def __init__(self,status): self.status=status; super().__init__("workflow HTTP status "+str(status))


class WorkflowHTTPClient:
    def __init__(self,*,base_url,token,enabled=False,client=None,timeout=60,max_response=2_000_000):
        url=urlsplit(base_url)
        if (not enabled or url.scheme not in {"http","https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path.rstrip("/") not in {"","/api"}
            or url.scheme=="http" and url.hostname not in {"localhost","127.0.0.1","::1"}
            or not isinstance(token,str) or not token or any(c in token for c in "\r\n\0") or not 0<timeout<=120):
            raise ValueError("explicit authenticated HTTPS/loopback workflow service required")
        if type(max_response) is not int or not 1<=max_response<=16*1024*1024: raise ValueError("invalid HTTP response bound")
        self.base,self._token,self._client=base_url.rstrip("/"),token,client
        self._owned=client is None
        self.timeout,self.max_response=timeout,max_response

    async def request(self,method,path,*,body=None,params=None):
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        if context is None: raise PermissionError("workflow HTTP requires central physical admission")
        context.checkpoint()
        if not path.startswith("/v1/") or ".." in path or "?" in path: raise ValueError("unapproved workflow HTTP path")
        if self._client is None:
            import httpx
            self._client=httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=self.timeout)
        async with self._client.stream(method,self.base+path,json=body,params=params,
            headers={"Authorization":"Bearer "+self._token,"Accept":"application/json"},
            timeout=self.timeout,follow_redirects=False) as response:
            raw=bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw)>self.max_response: raise ValueError("workflow HTTP response exceeds bound")
            if not 200<=response.status_code<300: raise WorkflowHTTPStatus(response.status_code)
            if response.status_code==204 and not raw: return None
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result: raise ValueError("duplicate workflow HTTP JSON field")
                    result[key]=value
                return result
            return json.loads(raw,object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite workflow JSON")))

    async def close(self):
        if self._owned and self._client is not None: await self._client.aclose(); self._client=None


@dataclass(frozen=True)
class ActivepiecesHTTPBinding:
    piece_name: str
    piece_version: str
    action_name: str
    project_id: str
    flow_id: str
    flow_version_id: str
    step_name: str
    step_sha256: str
    props_sha256: str
    connection_id: str | None = None
    connection_name: str | None = None


class ActivepiecesHTTPBackend:
    def __init__(self,client:WorkflowHTTPClient,*,bindings):
        self.client=client
        bindings=tuple(bindings)
        self.bindings={(b.piece_name,b.piece_version,b.action_name):b for b in bindings}
        if len(self.bindings)!=len(bindings): raise ValueError("duplicate native HTTP piece binding")
        for b in bindings:
            for key in (b.project_id,b.flow_id,b.flow_version_id,b.step_name): ident(key)
            if (b.connection_id is None)!=(b.connection_name is None): raise ValueError("native connection needs explicit host-ID/AP-name mapping")
            if b.connection_name is not None: ident(b.connection_name)

    @property
    def configuration_sha256(self):
        return digest({"origin":self.client.base,"bindings":[asdict(v) for k,v in sorted(self.bindings.items())]})

    def preflight(self,descriptor,member,hook):
        if hook!="action" or (descriptor.name,descriptor.version,member) not in self.bindings:
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="HTTP_PIECE_BINDING_UNAVAILABLE")
        try: import httpx
        except ImportError: return ActivityReceipt("FAILED","NOT_STARTED",failure_type="DEPENDENCY_UNAVAILABLE",retryable=True)
        return None

    async def metadata(self,request,*,piece_name,piece_version,project_id):
        from .activepieces import PieceDescriptor, PIECE_NAME, VERSION
        if not isinstance(piece_name,str) or not PIECE_NAME.fullmatch(piece_name) or not isinstance(piece_version,str) or not VERSION.fullmatch(piece_version):
            raise ValueError("exact native piece metadata pin required")
        if project_id not in {b.project_id for b in self.bindings.values()}: raise PermissionError("metadata project not configured")
        path="/v1/pieces/"+"/".join(quote(part,safe="") for part in piece_name.split("/"))
        metadata=await self.client.request("GET",path,params={"version":piece_version,"projectId":project_id})
        if not isinstance(metadata,dict) or (metadata.get("name"),metadata.get("version"))!=(piece_name,piece_version):
            raise ValueError("native piece metadata version mismatch")
        return PieceDescriptor.from_metadata(name=piece_name,version=piece_version,metadata=metadata)

    def _find_step(self,node,name):
        if isinstance(node,dict):
            if node.get("name")==name and isinstance(node.get("settings"),dict): return node
            for key,value in node.items():
                result=self._find_step(value,name)
                if result is not None: return result
        elif isinstance(node,list):
            for value in node:
                result=self._find_step(value,name)
                if result is not None: return result
        return None

    async def execute(self,request,descriptor,props,auth,store,heartbeat,*,trigger_payload=None):
        import httpx
        b=self.bindings[(descriptor.name,descriptor.version,request.arguments["member"])]
        if digest(props)!=b.props_sha256 or request.arguments.get("connection_id")!=b.connection_id:
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="STORED_STEP_INPUT_MISMATCH")
        try:
            flow=await self.client.request("GET","/v1/flows/"+b.flow_id,
                                           params={"versionId":b.flow_version_id,"projectId":b.project_id})
        except WorkflowHTTPStatus as exc:
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="DEPENDENCY_UNAVAILABLE" if exc.status in {429,502,503,504}
                else "AUTH_DENIED" if exc.status in {401,403} else "FLOW_UNAVAILABLE",retryable=exc.status in {429,502,503,504})
        except (TimeoutError,OSError,httpx.TransportError):
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="DEPENDENCY_UNAVAILABLE",retryable=True)
        heartbeat()
        version=flow.get("version") if isinstance(flow,dict) else None
        step=self._find_step(version,b.step_name)
        if not isinstance(version,dict) or version.get("id")!=b.flow_version_id or step is None or digest(step)!=b.step_sha256:
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="FLOW_VERSION_OR_SCHEMA_MISMATCH")
        settings=step["settings"]
        if flow.get("id")!=b.flow_id or flow.get("projectId")!=b.project_id:
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="FLOW_SCOPE_MISMATCH")
        if (settings.get("pieceName"),settings.get("pieceVersion"),settings.get("actionName"))!=(b.piece_name,b.piece_version,b.action_name):
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="PIECE_VERSION_OR_MEMBER_MISMATCH")
        stored=settings.get("input")
        if not isinstance(stored,dict) or digest({k:v for k,v in stored.items() if k!="auth"})!=digest(props):
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="STORED_STEP_INPUT_MISMATCH")
        def has_template(value):
            if isinstance(value,str): return "{{" in value
            if isinstance(value,dict): return any(has_template(v) for v in value.values())
            if isinstance(value,list): return any(has_template(v) for v in value)
            return False
        if has_template(props):
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="DYNAMIC_STORED_INPUT_REQUIRES_SDK_BACKEND")
        expected_auth={None} if b.connection_name is None else {"{{connections['"+b.connection_name+"']}}"}
        if b.connection_name is not None and "." not in b.connection_name: expected_auth.add("{{connections."+b.connection_name+"}}")
        if not isinstance(stored.get("auth"),(str,type(None))) or stored.get("auth") not in expected_auth:
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="STORED_CONNECTION_MISMATCH")
        retries=settings.get("errorHandlingOptions") or {}
        if (retries.get("retryOnFailure") or {}).get("value") not in (None,False) or step.get("skip") is True:
            return ActivityReceipt("FAILED","NOT_STARTED",failure_type="PROVIDER_AUTOMATIC_RETRY_OR_SKIPPED_STEP")
        # No retries after this POST. A disconnect can mean a saved run whose
        # ID was lost; restarting is not evidence that no effect happened.
        result=await self.client.request("POST","/v1/sample-data/test-step",body={
            "projectId":b.project_id,"flowVersionId":b.flow_version_id,"stepName":b.step_name})
        heartbeat()
        return self._receipt(result,b)

    def _receipt(self,result,b):
        if not isinstance(result,dict) or not isinstance(result.get("id"),str): raise ValueError("AP run omitted identity")
        if result.get("flowVersionId")!=b.flow_version_id or result.get("projectId")!=b.project_id or result.get("flowId")!=b.flow_id:
            raise ValueError("AP run version/project mismatch")
        ident(result["id"])
        status=result.get("status")
        steps=result.get("steps",{})
        step=steps.get(b.step_name) if isinstance(steps,dict) else None
        if isinstance(step,dict) and step.get("status")=="SUCCEEDED" and "output" in step:
            return ActivityReceipt("SUCCEEDED","COMPLETED",step["output"],provider_reference=result["id"])
        if status in {"FAILED","TIMEOUT","INTERNAL_ERROR","CANCELED","CANCELLED","QUOTA_EXCEEDED"}:
            return ActivityReceipt("CANCELLED" if status in {"CANCELED","CANCELLED"} else "FAILED","UNKNOWN",
                failure_type="PROVIDER_TERMINAL_AFTER_START",provider_reference=result["id"])
        return ActivityReceipt("WAITING","UNKNOWN",provider_reference=result["id"])

    async def observe(self,request,binding,heartbeat):
        b=self.bindings[(binding["piece"],binding["version"],binding["member"])]
        reference=binding.get("provider_reference")
        if not reference: return ActivityReceipt("UNCERTAIN","UNKNOWN",failure_type="PROVIDER_RUN_ID_UNAVAILABLE")
        result=await self.client.request("GET","/v1/flow-runs/"+ident(reference),params={"projectId":b.project_id})
        heartbeat()
        if result.get("id")!=reference: raise ValueError("AP observation run identity mismatch")
        return self._receipt(result,b)

    async def cancel(self,request,binding,heartbeat):
        b=self.bindings[(binding["piece"],binding["version"],binding["member"])]
        reference=binding.get("provider_reference")
        if not reference: return ActivityReceipt("UNCERTAIN","UNKNOWN",failure_type="PROVIDER_RUN_ID_UNAVAILABLE")
        await self.client.request("POST","/v1/flow-runs/cancel",body={"projectId":b.project_id,"flowRunIds":[ident(reference)]})
        return await self.observe(request,binding,heartbeat)
