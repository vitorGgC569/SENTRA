"""Native Canvas access through the Commander's existing workspace authority."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from sentra_core.conversations import ConversationStore,UncertainCall
from sentra_canvas.broker import read_endpoint,connect_or_start,_NoRedirect
from sentra_canvas.store import validated_name

READ_ACTIONS={"status","workspaces","workspace","terminal_output","task_status","task_governance","budget_list","handoffs","request_status"}
ROUTES={
    "terminal_create":("/api/terminals",{"name","shell"},"execute"),
    "terminal_input":("/api/terminal/input",{"id","data"},"execute"),
    "terminal_resize":("/api/terminal/resize",{"id","cols","rows"},"execute"),
    "terminal_close":("/api/terminal/close",{"id"},"execute"),
    "agent_create":("/api/agents",{"name","model","role","start"},"execute"),
    "agent_restart":("/api/agent/restart",{"id"},"execute"),
    "team_create":("/api/teams",{"name","coordinator","workers"},"write"),
    "task_delegate":("/api/tasks",{"team","agent","prompt","checks"},"execute"),
    "task_cancel":("/api/task/cancel",{"id"},"execute"),
    "task_verify":("/api/task/verify",{"id"},"execute"),
    "task_block":("/api/task/control",{"id"},"execute"),
    "task_unblock":("/api/task/control",{"id"},"execute"),
    "budget_set":("/api/budgets",{"scope","limits","task_id","mode","policy_id","enabled"},"execute"),
    "note_create":("/api/graph/note",{"title","body","x","y"},"write"),
    "note_update":("/api/graph/note/update",{"id","body"},"write"),
    "note_delete":("/api/graph/note/delete",{"id"},"write"),
    "link":("/api/graph/link",{"source","target"},"write"),
    "unlink":("/api/graph/unlink",{"id"},"write"),
    "handoff":("/api/graph/handoff",{"source","target","message"},"execute"),
    "run_pause":("/api/run/control",set(),"execute"),
    "run_resume":("/api/run/control",set(),"execute"),
    "run_cancel":("/api/run/control",set(),"execute"),
}
REQUIRED={
    "terminal_create":{"name"},"terminal_input":{"id","data"},"terminal_resize":{"id","cols","rows"},
    "terminal_close":{"id"},"agent_create":{"name","model"},"agent_restart":{"id"},
    "team_create":{"name","coordinator","workers"},"task_delegate":{"team","agent","prompt"},
    "task_cancel":{"id"},"note_create":{"title"},"note_update":{"id","body"},"note_delete":{"id"},
    "task_block":{"id"},"task_unblock":{"id"},
    "task_verify":{"id"},
    "link":{"source","target"},"unlink":{"id"},"handoff":{"source","target","message"},
}


class NativeCanvasService:
    def __init__(self,config,workspaces,filesystem,audit):
        self.config=config;self.workspaces=workspaces;self.filesystem=filesystem;self.audit=audit

    def update_config(self,config):self.config=config

    @property
    def state(self):return self.config.resolved_state_root/"canvas"

    def _endpoint(self):
        endpoint=read_endpoint(self.state)
        if endpoint is None:raise FileNotFoundError("Native Canvas is not running; use start or open SENTRA Canvas")
        return endpoint

    def _request(self,endpoint,path,body=None):
        request=urllib.request.Request(f"http://127.0.0.1:{endpoint.server_port}"+path,
            data=None if body is None else json.dumps(body,ensure_ascii=False).encode("utf-8"),
            headers={"Authorization":"Bearer "+endpoint.secret,"Content-Type":"application/json"})
        if request.data is not None and len(request.data)>16384:raise ValueError("Canvas request exceeded 16 KiB")
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
        try:
            with opener.open(request,timeout=12) as response:
                limit=min(self.config.max_output_bytes,4*1024*1024)
                payload=response.read(limit+1)
                if len(payload)>limit:raise RuntimeError("Canvas response exceeded the configured output limit")
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Native Canvas rejected the operation (HTTP {exc.code})") from None

    def _host(self):
        if self.config.process_mode=="sandbox":
            raise PermissionError("native host execution exceeds the configured sandbox policy")

    def _allowed(self,row,owner,permission):
        path=Path(row["path"])
        if path.resolve()!=path or not path.is_dir():raise PermissionError("Canvas project directory changed")
        self.workspaces.resolve_path(path,owner,permission)
        return row

    def _select(self,endpoint,selector,owner,permission):
        if not selector:raise ValueError("Canvas workspace ID/name/path is required")
        rows=self._request(endpoint,"/api/workspaces")
        matches=[row for row in rows if selector in (row["id"],row["name"],row["path"])]
        if len(matches)!=1:raise PermissionError("unique accessible Canvas workspace required")
        return self._allowed(matches[0],owner,permission)

    def _journal(self,workspace,principal,key,action,body,invoke,*,resolve=None):
        if not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError("persistent request_key required (1-128 characters)")
        digest=hashlib.sha256(json.dumps([principal,workspace["id"],key]).encode()).hexdigest()
        store=ConversationStore(self.config.resolved_state_root,
            principal="canvas-control:"+hashlib.sha256(principal.encode()).hexdigest()[:32])
        sid=store.open(workspace["path"],session_id="canvas_mcp_"+digest[:40])
        if resolve is not None:
            receipt=store.tool_receipt(sid)
            if receipt is None:raise FileNotFoundError("Canvas request receipt does not exist")
            store.resolve_call(sid,receipt["id"],executed=resolve["executed"],evidence=resolve["evidence"])
            return {"receipt_id":sid,"resolved":True,"automatically_replayed":False}
        with store.executing(sid):
            receipt=store.tool_receipt(sid)
            if action=="request_status":
                return {"receipt_id":sid,"status":receipt["state"] if receipt else "not_started",
                        "call_id":receipt["id"] if receipt else None,"automatically_replayed":False}
            args=json.dumps({"action":action,"body":body},sort_keys=True,ensure_ascii=False,separators=(",",":"))
            if receipt:
                if receipt["fingerprint"]!=store.fingerprint("CANVAS_CONTROL",args):raise ValueError("Canvas request key collision")
                if receipt["state"]=="completed":
                    result=receipt["result"]
                    return {"receipt_id":sid,"idempotent_replay":True,"result":result}
                if receipt["state"]!="not_executed":raise UncertainCall("Canvas delivery is uncertain; inspect request_status before any repeat")
                turn,_=store.continue_turn(sid)
            else:
                turn,_=store.begin_turn(sid,action+" native Canvas request",kind="journal")
            call,_=store.start_tool(sid,turn,"CANVAS_CONTROL",args)
            try:
                result=invoke()
                store.finish_tool(sid,call,result)
                store.end_turn(sid,turn)
                details={"workspace_id":workspace["id"],"correlation_id":sid}
                if isinstance(result,dict):
                    for field in ("id","operation_id","run_id"):
                        if field in result:details[field]=result[field]
                self.audit.emit("canvas."+action,"ok",details)
                return {"receipt_id":sid,"idempotent_replay":False,"result":result}
            except BaseException:
                store.end_turn(sid,turn,"interrupted")
                raise UncertainCall("Native Canvas delivery is uncertain; inspect request_status using the same request_key") from None

    def execute(self,action,*,owner,principal,workspace=None,params=None,request_key=None,confirm=False):
        p=dict(params or {})
        if action=="status":
            endpoint=read_endpoint(self.state)
            if endpoint is None:return {"running":False,"native":True}
            health=endpoint.request("/api/health")
            return {k:health[k] for k in ("ok","pid","runtime_id","provider_ready","task_scheduler") if k in health}|{"running":True,"native":True}
        if action=="start":
            self._host();self.workspaces.resolve(None,owner,"execute")
            endpoint=connect_or_start(self.config.allowed_roots[0],self.state)
            return {"running":True,"native":True,"pid":endpoint.pid,"runtime_id":endpoint.runtime_id}
        endpoint=self._endpoint()
        if action=="workspaces":
            result=[]
            for row in self._request(endpoint,"/api/workspaces"):
                try:result.append(self._allowed(row,owner,"read"))
                except PermissionError:continue
            return {"items":result}
        if action=="workspace_attach":
            if set(p)!={"path","name"}:raise ValueError("workspace_attach requires path and name")
            path=Path(p["path"]).expanduser().resolve(strict=True)
            self.workspaces.resolve_path(path,owner,"write")
            if self.filesystem.file_info(str(path),owner=owner)["type"]!="directory":raise ValueError("project must be a directory")
            validated_name(p["name"])
            # Attaching is idempotent by canonical project path in Canvas Store.
            return self._request(endpoint,"/api/workspace/attach",{"path":str(path),"name":p["name"]})
        permission=ROUTES[action][2] if action in ROUTES else "read"
        selected=self._select(endpoint,workspace,owner,permission)
        ws=selected["id"]
        query=urllib.parse.urlencode({"ws":ws,**{k:p[k] for k in ("id","cursor") if k in p}})
        if action=="workspace":return self._request(endpoint,"/api/graph?"+query)
        if action=="terminal_output":return self._request(endpoint,"/api/terminal/output?"+query)
        if action=="task_status":return self._request(endpoint,"/api/task?"+query)
        if action=="task_governance":return self._request(endpoint,"/api/task/governance?"+query)
        if action=="budget_list":return self._request(endpoint,"/api/budgets?"+query)
        if action=="handoffs":return {"items":self._request(endpoint,"/api/graph/handoffs?"+query)}
        if action in {"request_status","request_resolve"}:
            if action=="request_resolve":
                self._allowed(selected,owner,"execute")
                if confirm is not True or set(p)!={"executed","evidence"}:raise ValueError("explicit resolution and evidence required")
            return self._journal(selected,principal,request_key,action,{},None,
                resolve=p if action=="request_resolve" else None)
        if action not in ROUTES:raise ValueError("unsupported native Canvas action")
        route,fields,_=ROUTES[action]
        if set(p)-fields:raise ValueError("unsupported Canvas parameters")
        if REQUIRED.get(action,set())-set(p):raise ValueError("missing required Canvas parameters")
        if permission=="execute":self._host()
        if action in {"terminal_close","note_delete","run_cancel"} and confirm is not True:
            raise PermissionError("explicit close/delete/cancel confirmation required")
        body={**p,"ws":ws}
        if action in {"terminal_close","note_delete"}:body["confirm"]=True
        if action in {"task_delegate","handoff"}:
            if confirm is not True:raise PermissionError("explicit agent tool execution approval required")
            body.update(approved=True,request_key=hashlib.sha256((principal+":"+str(request_key)).encode()).hexdigest())
        if action=="task_delegate":
            body["provider"]="sentra-cli"
            if "checks" in body:
                from sentra_canvas.validation import normalize_checks
                body["checks"]=normalize_checks(body["checks"])
        if action.startswith("run_"):body["action"]=action.removeprefix("run_")
        if action in {"task_block","task_unblock"}:body["action"]=action.removeprefix("task_")
        if len(json.dumps(body,ensure_ascii=False,allow_nan=False).encode("utf-8"))>16384:
            raise ValueError("Canvas request exceeded 16 KiB")
        return self._journal(selected,principal,request_key,action,body,lambda:self._request(endpoint,route,body))
