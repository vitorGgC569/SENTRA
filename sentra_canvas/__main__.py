"""Loopback-only authenticated SENTRA Canvas API and desktop launcher."""
from __future__ import annotations
import argparse
import hmac
import json
import os
import mimetypes
import secrets
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .service import Canvas
from .store import Denied
from sentra_mcp.services.shell_coordinator import ShellConflict
from sentra_collab.authority import SnapshotConflict

STATIC=Path(__file__).parent/"static"

class CanvasServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=os.name!="nt"

    def __init__(self,canvas,port=0):
        self.canvas=canvas
        self.secret=secrets.token_urlsafe(36)
        self.runtime_id=uuid.uuid4().hex
        self._collab_process=None
        self._collab_lock=threading.RLock()
        super().__init__(("127.0.0.1",port),CanvasHandler)
        canvas._agent_port=self.server_port
        canvas._shell_origins=(f"http://127.0.0.1:{self.server_port}",
                               f"http://localhost:{self.server_port}")

    def collaboration(self):
        from .collaboration import CollaborationProcess
        with self._collab_lock:
            if self._collab_process is not None and not self._collab_process.status()["available"]:
                self._collab_process.close()
                self._collab_process=None
            if self._collab_process is None:
                self._collab_process=CollaborationProcess(port=self.server_port,secret=self.secret)
                self.canvas._collab_process=self._collab_process
            return self._collab_process.status()

    def server_close(self):
        with self._collab_lock:
            if self._collab_process is not None:
                self._collab_process.close()
        super().server_close()

    def get_request(self):
        connection,address=super().get_request()
        connection.settimeout(5)
        return connection,address

class CanvasHandler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        return  # no bearer tokens or request bodies in HTTP access logs

    def _allowed(self):
        host=self.headers.get("Host","")
        port=self.server.server_port
        if host not in {f"127.0.0.1:{port}",f"localhost:{port}"}:
            return False
        origin=self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{port}",
                                     f"http://localhost:{port}"}:
            return False
        return self.headers.get("Sec-Fetch-Site","").lower()!="cross-site"

    def _auth(self):
        return self._allowed() and hmac.compare_digest(
            self.headers.get("Authorization",""),
            "Bearer "+self.server.secret)

    def _send(self,status,body,content_type="application/json; charset=utf-8"):
        payload=(json.dumps(body,ensure_ascii=False).encode("utf-8")
                 if isinstance(body,(dict,list)) else body)
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Content-Security-Policy",
            "default-src 'self'; connect-src 'self' ws://127.0.0.1:*; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy","no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def _handle(self,fn):
        try:
            if not self._allowed():
                self._send(403,{"error":"invalid local origin"});return
            fn()
        except (ShellConflict,SnapshotConflict):
            self._send(409,{"error":"resource revision changed; reload before saving"})
        except (ValueError,TypeError) as exc:
            self._send(400,{"error":str(exc)[:200]})
        except (Denied,PermissionError):
            self._send(403,{"error":"access denied or explicit approval required"})
        except KeyError:
            self._send(400,{"error":"missing required parameter"})
        except (ConnectionAbortedError,BrokenPipeError,ConnectionResetError):
            # The browser may close a tab while a request is still in flight.
            # Do not attempt to send a second response on a broken socket.
            return
        except Exception as exc:
            try:
                self._send(500,{"error":f"{type(exc).__name__}: operation failed"})
            except (ConnectionAbortedError,BrokenPipeError,ConnectionResetError):
                pass

    def do_GET(self):
        self._handle(self._get)

    def _get(self):
        path=urlsplit(self.path)
        if path.path.startswith("/desktop-assets/"):
            assets=(STATIC/"desktop-assets").resolve()
            file=(assets/path.path.removeprefix("/desktop-assets/")).resolve()
            if (not file.is_relative_to(assets) or not file.is_file() or
                    (file.suffix.lower() not in {".js",".css",".svg",".png",".woff2"}
                     and file.name != "manifest.json")):
                self._send(404,{"error":"desktop asset unavailable"});return
            self._send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or "application/octet-stream");return
        if path.path in ("/","/index.html","/app.js","/app.css",
                          "/desktop.html","/native.html","/canvas","/native.js","/native.css","/sentra-logo.png","/rope-physics.js","/fractal-grid.js","/machine-panel.js",
                          "/sentra-collab.js","/collaboration-panel.js","/graph-view.js","/workflow-panel.js","/center-panel.js","/remote-panel.js","/vendor/sentra-collab-runtime.js",
                         "/vendor/xterm.js","/vendor/addon-fit.js","/vendor/xterm.css"):
            file=STATIC/("index.html" if path.path in ("/","/index.html")
                         else "native.html" if path.path=="/canvas"
                         else path.path.lstrip("/"))
            content_type=("text/html; charset=utf-8" if file.suffix==".html"
                          else "text/javascript; charset=utf-8" if file.suffix==".js"
                          else "text/css; charset=utf-8" if file.suffix==".css"
                          else "image/png" if file.suffix==".png"
                          else "application/octet-stream")
            self._send(200,file.read_bytes(),content_type)
            return
        if path.path.startswith("/api/channels/webhook/"):
            connector_id=path.path.removeprefix("/api/channels/webhook/")
            qs={key: values[0] for key,values in parse_qs(path.query).items() if len(values)==1}
            value=self.server.canvas.channel_challenge(connector_id,qs)
            self._send(200,str(value).encode("utf-8"),"text/plain; charset=utf-8")
            return
        if not self._auth():
            self._send(401,{"error":"local bearer token required"});return
        qs=parse_qs(path.query)
        ws=(qs.get("ws") or [""])[0]
        a=self.server.canvas
        if path.path == '/api/shell/generated-media':
            fields = {'project_id','space_id','conversation_id','message_id','asset_id'}
            if set(qs) != fields or any(len(qs[key]) != 1 for key in fields):
                raise ValueError('exact generated file message scope required')
            from .shell_generated_media import ShellGeneratedMedia
            a._shell_service()
            manifest, content = ShellGeneratedMedia(a._shell_runtime).read(**{key:qs[key][0] for key in fields})
            self._send(200, content, manifest['mime_type'])
            return
        if path.path=="/api/desktop/surfaces":
            from .electron_host import electron_status
            self._send(200,{"electron":electron_status(),"terminal":{"available":True,"authority":"Canvas/ConPTY"}});return
        if path.path=="/api/shell/delivery":
            fields={"project_id", "space_id", "conversation_id", "operation_id"}
            if set(qs) != fields or any(len(qs[key]) != 1 for key in fields):
                raise ValueError("exact scope required for delivery inspection")
            self._send(200,a.shell_delivery_inspect(qs["project_id"][0],
                qs["space_id"][0],qs["conversation_id"][0],qs["operation_id"][0]))
            return
        if path.path=="/api/shell/live":
            fields={"project_id", "space_id", "conversation_id"}
            if set(qs) != fields or any(len(qs[key]) != 1 for key in fields):
                raise ValueError("exact conversation scope required for live preview")
            self._send(200,a.shell_live_preview(qs["project_id"][0],
                qs["space_id"][0],qs["conversation_id"][0]))
            return
        if path.path=="/api/health":
            self._send(200,{"ok":True,"provider_ready":"unverified",
                           "terminal_backend":"Windows ConPTY",
                           "maestri_required":False,"runtime_id":self.server.runtime_id,
                           "pid":os.getpid(),"state_dir":str(a.state_dir.resolve()),
                           "task_scheduler":a.task_scheduler_status()});return
        if path.path=="/api/workspaces":
            self._send(200,a.workspaces());return
        if path.path=="/api/integrations":
            self._send(200,a.integrations());return
        if path.path=="/api/center/task/files":
            if set(qs) != {"ws", "conversation_id"} or any(len(qs[key]) != 1 for key in ("ws", "conversation_id")):
                raise ValueError("exact project and conversation required")
            self._send(200,a.center_file_work_items(ws,qs["conversation_id"][0]))
            return
        if path.path=="/api/center/capabilities":
            self._send(200,a.center_capabilities(ws));return
        if path.path=="/api/center/machines":
            self._send(200,a.center_machines(ws));return
        if path.path=="/api/center/network":
            self._send(200,a.center_network(ws));return
        if path.path=="/api/center/browser-evidence":
            self._send(200,a.center_browser_evidence(ws));return
        if path.path=="/api/center/skill-library":
            self._send(200,a.center_skill_library(ws));return
        if path.path=="/api/center/chat-access":
            self._send(200,a.center_chat_access(ws,(qs.get("conversation_id") or [""])[0]));return
        if path.path=="/api/center/project-review":
            action=(qs.get("action") or ["list"])[0]
            if action not in {"list","preview","diff","pdf_text","pdf_visual"}:
                raise Denied("project mutations require the approved POST editor")
            try:
                view=a.center_project_review(ws,
                    path=(qs.get("path") or [""])[0],action=action,
                    page=int((qs.get("page") or ["1"])[0]),
                    dpi=int((qs.get("dpi") or ["72"])[0]))
            except (TimeoutError, RuntimeError) as exc:
                # Only an unavailable/timed-out native PDF renderer is a
                # retryable read-only projection. Other runtime failures
                # remain 500 and must not silently trigger UI fallback.
                unavailable=(action=="pdf_visual" and
                    (isinstance(exc,TimeoutError) or
                     str(exc)=="PDFium is not installed; visual PDF preview disabled"))
                if not unavailable:
                    raise
                self._send(503,{"error":"visual PDF preview unavailable"});return
            self._send(200,view);return
        if path.path=="/api/center/conversation-search":
            self._send(200,a.center_conversation_search(ws,(qs.get("q") or [""])[0]));return
        if path.path=="/api/center/mcp-account":
            self._send(200,a.center_mcp_account(ws));return
        if path.path=="/api/center/plugin-proof":
            self._send(200,a.center_plugin_proof(ws));return
        if path.path=="/api/center/mcp-http":
            self._send(200,a.center_mcp_http(ws));return
        if path.path=="/api/center/plugin-bundles":
            self._send(200,a.center_plugin_bundles(ws));return
        if path.path=="/api/center/overview":
            self._send(200,a.center_overview(ws,operation_offset=int((qs.get("operation_offset") or ["0"])[0]),
                work_item_offset=int((qs.get("work_item_offset") or ["0"])[0])));return
        if path.path=="/api/center/goal-loop":
            self._send(200,a.center_goal_loop(ws));return
        if path.path=="/api/center/web-delivery":
            self._send(200,a.center_web_delivery(ws));return
        if path.path=="/api/center/telemetry":
            self._send(200,a.center_telemetry(ws));return
        if path.path=="/api/center/operation":
            self._send(200,a.center_operation(ws,(qs.get("operation_id") or [""])[0]));return
        if path.path in {"/api/models","/sentra/model-catalog"}:
            self._send(200,a.model_catalog());return
        if path.path=="/api/workspace":
            self._send(200,a.workspace_detail(ws));return
        if path.path=="/api/graph":
            self._send(200,a.graph_detail(ws));return
        if path.path=="/api/graph/handoffs":
            a.store.workspace(ws)
            self._send(200,a.graph.handoffs(ws));return
        if path.path=="/api/events":
            self._send(200,a.store.events(ws,limit=250,
                       search=(qs.get("q") or [""])[0]));return
        if path.path=="/api/terminal/output":
            self._send(200,a.terminal_output(ws,(qs.get("id") or [""])[0],
                              (qs.get("cursor") or ["0"])[0]));return
        if path.path=="/api/team":
            self._send(200,a.team_members(ws,(qs.get("id") or [""])[0]));return
        if path.path=="/api/task":
            self._send(200,a.store.resource("tasks",(qs.get("id") or [""])[0],ws));return
        if path.path=="/api/task/governance":
            self._send(200,a.task_governance(ws,(qs.get("id") or [""])[0]));return
        if path.path=="/api/budgets":
            self._send(200,a.budget_policies(ws));return
        self._send(404,{"error":"route not found"})

    def do_POST(self):
        self._handle(self._post)

    def _post(self):
        route=urlsplit(self.path).path
        if route.startswith(("/api/channels/webhook/", "/api/interop/webhook/")):
            # Verify the provider signature over the original bytes. This route
            # only commits authenticated inbox evidence, never an owner effect.
            if self.headers.get("Content-Type","").split(";")[0]!="application/json":
                raise ValueError("JSON webhook required")
            length=int(self.headers.get("Content-Length","0"))
            if not 0<length<=1048576:
                raise ValueError("invalid webhook size")
            raw=self.rfile.read(length)
            if len(raw)!=length:
                raise ValueError("incomplete webhook body")
            if route.startswith("/api/channels/webhook/"):
                value=self.server.canvas.channel_receive(route.removeprefix("/api/channels/webhook/"),raw,dict(self.headers))
            else:
                value=self.server.canvas.interop_receive(route.removeprefix("/api/interop/webhook/"),raw,dict(self.headers))
            self._send(200,value)
            return
        agent_route=route=="/api/agent/control"
        if not agent_route and not self._auth():
            self._send(401,{"error":"local bearer token required"});return
        if self.headers.get("Content-Type","").split(";")[0]!="application/json":
            raise ValueError("JSON content type required")
        length=int(self.headers.get("Content-Length","0"))
        body_limit = (1500000 if route == "/api/collab/host" else
                      2_010_000 if route=="/api/center/machine/configure" else
                      800000 if route=="/api/shell/bridge" else
                      160000 if route=="/api/center/project-review" else
                      131072 if route in {"/api/center/execute","/api/agent/control"} else 16384)
        if not 0<length<=body_limit:
            raise ValueError("invalid request size")
        p=json.loads(self.rfile.read(length))
        if not isinstance(p,dict): raise ValueError("JSON object expected")
        a=self.server.canvas
        if agent_route:
            authorization=self.headers.get("Authorization","")
            if not authorization.startswith("Bearer "):
                raise Denied("Canvas agent capability required")
            self._send(200,a.agent_control(authorization[7:],p))
            return
        ws=p.get("ws","")
        if route=="/api/shell/bridge":
            response=a.shell_bridge(p)
            if p.get("action")=="document_session" and response.get("ok") is True:
                response={**response,"value":{**response["value"],**self.server.collaboration()}}
            self._send(200,response)
            return
        if route=="/api/collab/host":
            self._send(200,{"ok":True,"value":a.collab_host_call(p["method"],p["params"])})
            return
        if route=="/api/collab/session":
            session=a.collab_session(ws,p["work_item_id"],p["principal_id"],p.get("permission","read"))
            self._send(200,{**session,**self.server.collaboration()})
            return
        if route=="/api/collab/prepare":
            availability=self.server.collaboration()
            self._send(200,{**a.collab_prepare(ws,p["principal_id"]),**availability})
            return
        if route=="/api/collab/disable":
            self._send(200,a.collab_disable(ws,p["work_item_id"],p["principal_id"]))
            return
        if route=="/api/center/goal-loop":
            if set(p) - {"ws","action","objective","goal_id","loop_id","max_steps","max_cost_usd","deadline_seconds"}:
                raise ValueError("unexpected Goal/Loop field")
            self._send(200,a.center_goal_loop(ws,action=p.get("action","status"),
                objective=p.get("objective",""),goal_id=p.get("goal_id"),loop_id=p.get("loop_id"),
                max_steps=p.get("max_steps",2),max_cost_usd=p.get("max_cost_usd",0.0),
                deadline_seconds=p.get("deadline_seconds",120)));return
        if route=="/api/center/compact-resume":
            if set(p) != {"ws", "action", "arguments"}:
                raise ValueError("invalid Compact&Resume fields")
            self._send(200,a.center_compact_resume(ws,action=p["action"],arguments=p["arguments"]));return
        if route=="/api/center/machine/configure":
            if p.get("kind") in {"workspace-files", "terminal"} and p.get("approve") is not True:
                raise Denied("explicit workspace machine consent required")
            self._send(200,a.center_configure_machine(ws,p["agent_id"],p["kind"],
                profiles=p.get("profiles"),headless=p.get("headless",True),
                recalculation_backends=p.get("recalculation_backends"),ocr_backends=p.get("ocr_backends"),
                provider_config=p.get("provider_config"),definitions=p.get("definitions")))
            return
        if route=="/api/center/network":
            self._send(200,a.center_network(ws,p["configuration"]));return
        if route=="/api/center/browser-evidence":
            if p.get("approve") is not True:raise Denied("explicit browser collector consent required")
            self._send(200,a.center_browser_evidence(ws,configuration=p["configuration"]));return
        if route=="/api/center/skill-library":
            if p.get("action") not in {"list","disclose","versions","latest","review"} and p.get("approve") is not True:
                raise Denied("explicit skill import, activation or revocation consent required")
            self._send(200,a.center_skill_library(ws,action=p["action"],parameters=p.get("parameters")));return
        if route=="/api/center/chat-access":
            self._send(200,a.center_chat_access(ws,change=p["change"]));return
        if route=="/api/center/conversation-export":
            self._send(200,a.center_conversation_export(ws,p["conversation_id"]));return
        if route=="/api/desktop/electron":
            if p.get("confirm") is not True:
                raise Denied("explicit consent to open Electron display required")
            from .electron_host import launch_electron
            self._send(200,{"launched":True,"pid":launch_electron(self.server,wait=False),
                            "authority":"existing_canvas_broker"});return
        if route=="/api/center/project-review":
            action=p.get("action")
            if action not in {"preview_edit","save"}:
                raise ValueError("unsupported editor mutation")
            if action=="save":
                if p.get("approve") is not True:
                    raise Denied("file save requires explicit review and owner confirmation")
                self._send(200,a.center_project_save_reviewed(ws,p["path"],p["content"],
                    p["expected_sha256"],p.get("review_token")));return
            self._send(200,a.center_project_review(ws,path=p["path"],action=action,
                content=p["content"],expected_sha256=p["expected_sha256"]));return
        if route=="/api/center/mcp-http":
            # Operator-only catalog admission, NOT a tool call. The endpoint
            # accepts no bearer token, arbitrary args, host effect or grant.
            action=p.get("action")
            required=({"ws","action","server_id","endpoint","approve"}
                      if action=="register" else
                      {"ws","action","server_id","approve"}
                      if action=="disable" else set())
            if not required or set(p)!=required:
                raise ValueError("exact MCP HTTP catalog request schema required")
            if p.get("approve") is not True:
                raise Denied("explicit MCP HTTP catalog consent required")
            self._send(200,a.center_mcp_http(ws,action=action,
                server_id=p["server_id"],endpoint=p.get("endpoint")));return
        if route=="/api/center/mcp-account":
            action=p.get("action")
            required=({"ws","action","approve"} if action=="begin" else
                      {"ws","action","approve","attempt_id"}
                      if action in {"mark_steps","cancel"} else set())
            if not required or set(p)!=required:
                raise ValueError("exact MCP account switch request schema required")
            if p.get("approve") is not True:
                raise Denied("explicit owner approval required")
            self._send(200,a.center_mcp_account(ws,action=action,
                attempt_id=p.get("attempt_id"),approved=True));return
        if route=="/api/center/plugin-bundles":
            if p.get("action") not in {"inspect","supervision"} and p.get("approve") is not True:
                raise Denied("explicit MCPB registration or catalog change approval required")
            action=p.get("action","stage")
            if action not in {"stage","inspect","register","disable","supervision","supervision_sweep"}:
                raise ValueError("unsupported MCPB catalog action")
            self._send(200,a.center_plugin_bundles(ws,action=action,
                source=p.get("source"),package_sha256=p.get("package_sha256"),
                expected_sha256=p.get("expected_sha256")));return
        if route=="/api/center/network/pairing":
            self._send(200,a.center_network_pairing(ws));return
        if route=="/api/center/task/prepare":
            self._send(200,a.center_prepare_task(ws,p["machine_id"],p["capabilities"],p["objective"],
                conversation_id=p.get("conversation_id"), approve=p.get("approve") is True))
            return
        if route=="/api/center/task/revoke":
            if set(p) != {"ws", "work_item_id", "conversation_id", "approve"} or p["approve"] is not True:
                raise Denied("explicit and scoped file grant revocation required")
            self._send(200,a.center_revoke_files(ws,p["work_item_id"],p["conversation_id"],approve=True))
            return
        if route=="/api/center/execute":
            self._send(200,a.center_execute(ws,p["work_item_id"],p["machine_id"],
                p["capability_id"],p["operation_id"],p["arguments"],p["request_key"]))
            return
        if route=="/api/center/experiences":
            self._send(200,a.center_experiences(ws,p["work_item_id"],p["machine_id"],p["query"],p.get("limit",5)))
            return
        if route=="/api/center/telemetry":
            self._send(200,a.center_telemetry(ws,p["configuration"]))
            return
        if route=="/api/center/plan":
            self._send(200,a.center_plan(ws,p["work_item_id"],p.get("action","read"),
                p.get("steps"),p.get("expected_revision")))
            return
        if route=="/api/center/inspect":
            if p.get("confirm") is not True:
                raise ValueError("explicit read-only center operation approval required")
            self._send(200,a.center_inspect(ws,p["work_item_id"],p["operation_id"],p["request_key"]))
            return
        if route=="/api/runtime/shutdown":
            if p.get("confirm") is not True:
                raise ValueError("explicit runtime shutdown confirmation required")
            self._send(200,{"requested":True})
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        if route=="/api/workspaces":
            result=a.create_workspace(p["name"])
        elif route=="/api/workspace/attach":
            result=a.attach_workspace(p["name"],p["path"])
        elif route=="/api/run/control":
            result=a.run_control(ws,p["action"])
        elif route=="/api/task/control":
            result=a.task_control(ws,p["id"],p["action"])
        elif route=="/api/task/verify":
            result=a.task_verify(ws,p["id"])
        elif route=="/api/budgets":
            result=a.budget_set(ws,p.get("scope","workspace"),p.get("limits"),
                task_id=p.get("task_id"),mode=p.get("mode","hard_stop"),
                policy_id=p.get("policy_id"),enabled=p.get("enabled",True))
        elif route=="/api/terminals":
            result=a.create_terminal(ws,p["name"],p.get("shell","powershell"),p.get("model"),p.get("effort"))
        elif route=="/api/terminal/input":
            result=a.terminal_input(ws,p["id"],p["data"])
        elif route=="/api/terminal/resize":
            result=a.terminal_resize(ws,p["id"],p["cols"],p["rows"])
        elif route=="/api/terminal/rename":
            result=a.terminal_rename(ws,p["id"],p["name"])
        elif route=="/api/terminal/duplicate":
            result=a.terminal_duplicate(ws,p["id"],p["name"])
        elif route=="/api/terminal/close":
            if p.get("confirm") is not True:
                raise ValueError("explicit close confirmation required")
            result=a.terminal_close(ws,p["id"])
        elif route=="/api/agents":
            result=a.create_agent(ws,p["name"],p["model"],
                                  p.get("role","worker"),p.get("start",False),goal=p.get("goal"))
        elif route=="/api/agent/context":
            result=a.agent_working_context(ws,p["agent_id"],goal=p.get("goal"),expected_revision=p.get("expected_revision"))
        elif route=="/api/agent/restart":
            result=a.restart_agent(ws,p["id"])
        elif route=="/api/teams":
            result=a.create_team(ws,p["name"],p["coordinator"],p["workers"])
        elif route=="/api/tasks":
            result=a.delegate(ws,p["team"],p["agent"],p["prompt"],
                              p["request_key"],p.get("provider","test"),
                              p.get("approved") is True,checks=p.get("checks"))
        elif route=="/api/task/cancel":
            result=a.cancel_task(ws,p["id"])
        elif route=="/api/graph/move":
            result=a.graph_move(ws,p["id"],p["x"],p["y"])
        elif route=="/api/graph/resize":
            result=a.graph_resize(ws,p["id"],p["width"],p["height"])
        elif route=="/api/graph/note":
            result=a.graph_note(ws,p["title"],p.get("body",""),
                                p.get("x",440),p.get("y",220))
        elif route=="/api/graph/note/update":
            result=a.graph_update_note(ws,p["id"],p["body"])
        elif route=="/api/graph/note/delete":
            if p.get("confirm") is not True:
                raise ValueError("explicit note delete confirmation required")
            result=a.graph_remove_note(ws,p["id"])
        elif route=="/api/external/antigravity":
            result=a.launch_antigravity(ws,p.get("approved") is True)
        elif route=="/api/graph/handoff":
            result=a.handoff(ws,p["source"],p["target"],p["message"],
                               p.get("approved") is True,p.get("request_key"))
        elif route=="/api/graph/link":
            result=a.graph_link(ws,p["source"],p["target"])
        elif route=="/api/graph/unlink":
            result=a.graph_unlink(ws,p["id"])
        else:
            self._send(404,{"error":"route not found"});return
        self._send(200,result)

def main(argv=None):
    p=argparse.ArgumentParser(description="SENTRA Canvas independent of Maestri")
    p.add_argument("--root",type=Path,default=Path.cwd(),help="authorized SENTRA root")
    p.add_argument("--state-dir",type=Path,help="persisted Canvas state directory")
    p.add_argument("--port",type=int,default=0,help="local port; 0 chooses free port")
    p.add_argument("--no-open",action="store_true",help="do not open UI")
    p.add_argument("--ui",choices=("native","electron","terminal"),default="native",
                   help="desktop UI host, Electron view or SENTRA CLI terminal")
    p.add_argument("--surface",choices=("shell-home","desktop","native"),default="shell-home",
                   help="shell-first Home/Dots/Spaces surface; Canvas stays as internal view")
    p.add_argument("--broker",action="store_true",help="run persistent local Canvas owner")
    args=p.parse_args(argv)
    from .broker import connect_or_start,publish_endpoint,remove_endpoint
    if not args.no_open and not args.broker:
        if args.ui == "terminal":
            from sentra_cli.__main__ import main as cli_main
            return cli_main(["--workspace",str(args.root.resolve())])
        endpoint=connect_or_start(args.root,args.state_dir,port=args.port)
        if args.ui == "electron":
            from .electron_host import launch_electron
            return launch_electron(endpoint,wait=True)
        from .native_app import launch_native, resolve_surface
        surface_file = {"shell-home": "shell-home.html", "desktop": "desktop.html",
                        "native": "native.html"}[args.surface]
        # Shell-first with fallback: resolve_surface prefers the shipped shell
        # bundle and falls back to the current desktop bundle.
        from pathlib import Path as _Path
        if not (_Path(__file__).parent / "static" / surface_file).is_file():
            surface_file = resolve_surface()
        launch_native(endpoint,serve=False,surface=surface_file)
        return 0
    app=Canvas(args.root,state_dir=args.state_dir)
    server=None
    try:
        server=CanvasServer(app,args.port)
        publish_endpoint(server)
        if sys.stdout is not None:
            print(f"SENTRA Canvas listening on 127.0.0.1:{server.server_port}",flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.server_close()
        try:
            app.shutdown()
        finally:
            if server is not None:
                remove_endpoint(server)
    return 0

if __name__=="__main__":
    sys.exit(main())
