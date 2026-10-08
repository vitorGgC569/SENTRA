"""Loopback-only authenticated SENTRA Canvas API and desktop launcher."""
from __future__ import annotations
import argparse
import hmac
import json
import os
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

STATIC=Path(__file__).parent/"static"

class CanvasServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=os.name!="nt"

    def __init__(self,canvas,port=0):
        self.canvas=canvas
        self.secret=secrets.token_urlsafe(36)
        self.runtime_id=uuid.uuid4().hex
        super().__init__(("127.0.0.1",port),CanvasHandler)
        canvas._agent_port=self.server_port

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
            "default-src 'self'; connect-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy","no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def _handle(self,fn):
        try:
            if not self._allowed():
                self._send(403,{"error":"invalid local origin"});return
            fn()
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
        if path.path in ("/","/index.html","/app.js","/app.css",
                         "/native.html","/native.js","/native.css",
                         "/vendor/xterm.js","/vendor/addon-fit.js","/vendor/xterm.css"):
            file=STATIC/("index.html" if path.path in ("/","/index.html")
                         else path.path.lstrip("/"))
            content_type=("text/html; charset=utf-8" if file.suffix==".html"
                          else "text/javascript; charset=utf-8" if file.suffix==".js"
                          else "text/css; charset=utf-8")
            self._send(200,file.read_bytes(),content_type)
            return
        if not self._auth():
            self._send(401,{"error":"local bearer token required"});return
        qs=parse_qs(path.query)
        ws=(qs.get("ws") or [""])[0]
        a=self.server.canvas
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
        agent_route=route=="/api/agent/control"
        if not agent_route and not self._auth():
            self._send(401,{"error":"local bearer token required"});return
        if self.headers.get("Content-Type","").split(";")[0]!="application/json":
            raise ValueError("JSON content type required")
        length=int(self.headers.get("Content-Length","0"))
        if not 0<length<=16384:
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
            result=a.create_terminal(ws,p["name"],p.get("shell","powershell"))
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
                                  p.get("role","worker"),p.get("start",False))
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
    p.add_argument("--broker",action="store_true",help="run persistent local Canvas owner")
    args=p.parse_args(argv)
    from .broker import connect_or_start,publish_endpoint,remove_endpoint
    if not args.no_open and not args.broker:
        from .native_app import launch_native
        endpoint=connect_or_start(args.root,args.state_dir,port=args.port)
        launch_native(endpoint,serve=False)
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
