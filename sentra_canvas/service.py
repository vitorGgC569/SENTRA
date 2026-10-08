"""Application service using native ConPTY and the existing SENTRA CLI."""
from __future__ import annotations
import codecs
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from sentra_mcp.errors import sanitize_error
from pathlib import Path

from .store import Store, Denied, validated_name, MODEL_RE, TRANSCRIPT_LIMIT, new_id
from .terminal import WindowsPTY, TerminalError
from .instance_lock import InstanceLock
from .namespaces import Namespace
from .graph import GraphStore
from .owned_process import TaskProcess
from .adapters import catalog as terminal_catalog,cli_argv,resolve as resolve_adapters

class Session:
    def __init__(self, persist=None, on_persistence_error=None):
        self.lock=threading.RLock()
        self.decoder=codecs.getincrementaldecoder("utf-8")("replace")
        self.base=0
        self.buffer=""
        self.pty=None
        self.persist=persist
        self.persistence_error=None
        self.on_persistence_error=on_persistence_error
        self.exit_input=b"exit\r"

    def append(self,chunk):
        with self.lock:
            text=self.decoder.decode(chunk)
            if self.persist and text and self.persistence_error is None:
                try:
                    self.persist(text)
                except Exception as exc:
                    # Keep draining ConPTY, but never claim this volatile suffix
                    # survived a restart or append it at the wrong durable offset.
                    self.persistence_error=type(exc).__name__
                    if self.on_persistence_error:
                        try:
                            self.on_persistence_error(self.persistence_error)
                        except Exception:
                            # A failed disk must not stop draining the child pipe.
                            pass
            self.buffer+=text
            if len(self.buffer)>TRANSCRIPT_LIMIT:
                removed=len(self.buffer)-TRANSCRIPT_LIMIT
                self.buffer=self.buffer[removed:]
                self.base+=removed

    def output(self,cursor=0):
        with self.lock:
            requested=max(0,int(cursor))
            cursor=min(self.base+len(self.buffer),max(self.base,requested))
            return {"cursor":self.base+len(self.buffer),
                    "text":self.buffer[cursor-self.base:],
                    "truncated":requested<self.base}

class Canvas:
    def __init__(self,root,db_path=None,principal=None,max_terminals=12,*,state_dir=None,
                 max_task_workers=4,max_pending_tasks=128):
        if type(max_task_workers) is not int or not 1<=max_task_workers<=16:
            raise ValueError("task worker limit must be 1-16")
        if type(max_pending_tasks) is not int or not max_task_workers<=max_pending_tasks<=1024:
            raise ValueError("pending task limit must cover workers and be <=1024")
        root=Path(root).resolve()
        self.project_dir=root
        self.state_dir=Path(state_dir).resolve() if state_dir is not None else root/".sentra"/"canvas"
        self.state_dir.mkdir(parents=True,exist_ok=True)
        self.instance_lock=InstanceLock(self.state_dir/"owner.lock")
        try:
            projects=self.state_dir/"projects"
            projects.mkdir(exist_ok=True)
            self.store=Store(db_path or self.state_dir/"canvas.sqlite3",
                             projects,principal=principal,telemetry_root=self.state_dir.parent)
        except BaseException:
            self.instance_lock.close()
            raise
        self.graph=GraphStore(self.state_dir/"graph.sqlite3")
        self.graph.recover_handoffs([ws["id"] for ws in self.store.workspaces()])
        self._lock=threading.RLock()
        self._shutdown_lock=threading.Lock()
        self._sessions={}
        self._jobs={}
        self._task_threads={}
        self._task_processes={}
        self._job_tasks={}
        self._closing=False
        self._closed=False
        self._agent_tokens={}
        self._agent_port=None
        self.max_terminals=max_terminals
        self.max_task_workers=max_task_workers
        self.max_pending_tasks=max_pending_tasks
        self._task_runtime=None
        self._task_runtime_error=None
        self._dispatch_stop=threading.Event()
        self._dispatch_wake=threading.Event()
        self._dispatch_thread=threading.Thread(target=self._dispatch_loop,daemon=True,name="sentra-canvas-queue")
        self._dispatch_thread.start()

    def _runtime(self):
        if self._task_runtime is None:
            from .task_runtime import TaskRuntime
            self._task_runtime=TaskRuntime(self.state_dir.parent,self.store)
        return self._task_runtime

    def _dispatch_loop(self):
        while not self._dispatch_stop.is_set():
            try:
                self._drain_tasks()
            except Exception as exc:
                self._task_runtime_error=type(exc).__name__
            self._dispatch_wake.wait(.5)
            self._dispatch_wake.clear()

    def _drain_tasks(self):
        with self._lock:
            if self._closing:return
            runtime=self._runtime()
            error=None
            for task in self.store.projection_tasks():
                try:runtime.project(task)
                except Exception as exc:error=type(exc).__name__
            self._task_runtime_error=error
            queued=self.store.queued_tasks()
            runs={}
            for task in queued:runs.setdefault(task["run_id"],runtime.task_run(task))
            active_agents=set()
            for ident,(ws,agent) in self._job_tasks.items():
                # A registered worker retains its seat until its final state and
                # process teardown have completed, including cancellation.
                task=self.store.resource("tasks",ident,ws)
                runtime.flush_usage(task)
                run=runs.setdefault(task["run_id"],runtime.task_run(task))
                active_agents.add(agent)
                operation=runtime.operation(task)
                governed=runtime.work_item(task)
                if task["cancel_requested"] or operation["state"]=="CANCEL_REQUESTED" or governed["state"] in {"CANCELLED","FAILED","BLOCKED"} or run["state"] in {"CANCELLED","FAILED","SUCCEEDED"}:
                    self.store.request_task_cancel(ws,ident)
                    if ident in self._jobs:self._jobs[ident].set()
            for task in queued:
                run=runs[task["run_id"]]
                governed=runtime.work_item(task)
                if task["cancel_requested"] or governed["state"] in {"CANCELLED","FAILED"} or run["state"] in {"CANCELLED","FAILED","SUCCEEDED"}:
                    self.store.task_state(task["workspace_id"],task["id"],"cancelled")
                    continue
                if run["state"]!="RUNNING" or run["desired_state"]!="RUNNING":continue
                if len(self._job_tasks)>=self.max_task_workers:break
                if task["agent_id"] in active_agents:continue
                operation=runtime.operation(task)
                if operation["state"]!="QUEUED" or operation["progress"].get("revision")!=task["revision"]:
                    continue
                if not runtime.admission(task,reserve=True)["allowed"]:continue
                # Commit the claim before launching a thread or external child.
                self.store.task_state(task["workspace_id"],task["id"],"running")
                claimed=self.store.resource("tasks",task["id"],task["workspace_id"])
                try:runtime.project(claimed)
                except Exception:
                    # No worker/thread/child has been created yet.
                    self.store.task_state(task["workspace_id"],task["id"],"failed","durable claim publication failed before execution")
                    raise
                cancel=threading.Event()
                self._jobs[task["id"]]=cancel
                self._job_tasks[task["id"]]=(task["workspace_id"],task["agent_id"])
                thread=threading.Thread(target=self._run_task,args=(task["workspace_id"],claimed,cancel),
                    daemon=True,name="sentra-task-"+task["id"][:8])
                self._task_threads[task["id"]]=thread
                active_agents.add(task["agent_id"])
                try:thread.start()
                except Exception:
                    self._jobs.pop(task["id"],None);self._task_threads.pop(task["id"],None)
                    self._job_tasks.pop(task["id"],None)
                    self.store.task_state(task["workspace_id"],task["id"],"failed","worker startup failed")
                    raise

    def task_scheduler_status(self):
        with self._lock:
            return {"worker_limit":self.max_task_workers,"pending_limit":self.max_pending_tasks,
                    "active_workers":len(self._job_tasks),"projection_error":self._task_runtime_error,
                    "closing":self._closing}

    def task_governance(self,ws,ident):
        with self._lock:
            task=self.store.resource("tasks",ident,ws)
            runtime=self._runtime()
            runtime.project(task)
            task=self.store.resource("tasks",ident,ws)
            return {"work_item":runtime.work_item(task),
                    "execution_status":task["status"],"check_count":len(task["checks"]),
                    "cost":runtime.governance.cost_summary(runtime.owner,work_item_id=task["work_item_id"]),
                    "provider_usage":runtime.usage_summary(task),
                    "admission":runtime.admission(task) if task["status"]=="queued" else None}

    def task_control(self,ws,ident,action):
        with self._lock:
            task=self.store.resource("tasks",ident,ws)
            if task["status"]!="queued":
                raise ValueError("only queued tasks can be blocked or unblocked; cancel running tasks explicitly")
            if action not in {"block","unblock"}:raise ValueError("invalid work item control")
            runtime=self._runtime()
            runtime.project(task)
            result=runtime.governance.transition_work_item(task["work_item_id"],runtime.owner,
                "BLOCKED" if action=="block" else "QUEUED",reason="explicit native Canvas control")
            self._dispatch_wake.set()
            return result

    def task_verify(self,ws,ident):
        with self._lock:
            return self._runtime().verify(self.store.resource("tasks",ident,ws))

    def budget_policies(self,ws):
        with self._lock:
            workspace=self.store.workspace(ws)
            runtime=self._runtime()
            items=runtime.budgets.list_policies(runtime.owner)["items"]
            def visible(item):
                if item["scope_type"]=="workspace":return item["scope_id"]==workspace["path"]
                if item["scope_type"]=="run":return item["scope_id"]==workspace["run_id"]
                if item["scope_type"]=="work_item":
                    try:work=runtime.governance.work_item_info(item["scope_id"],runtime.owner)
                    except FileNotFoundError:return False
                    return work["metadata"].get("workspace_id")==ws
                return False
            return {"items":[item for item in items if visible(item)]}

    def budget_set(self,ws,scope,limits,*,task_id=None,mode="hard_stop",policy_id=None,enabled=True):
        with self._lock:
            workspace=self.store.workspace(ws)
            runtime=self._runtime()
            if policy_id is not None:
                if policy_id not in {p["budget_policy_id"] for p in self.budget_policies(ws)["items"]}:
                    raise Denied("budget policy is outside this workspace")
                result=runtime.budgets.set_enabled(policy_id,runtime.owner,enabled=enabled)
            else:
                if scope=="workspace":scope_id=workspace["path"]
                elif scope=="run":scope_id=workspace["run_id"]
                elif scope=="work_item":scope_id=self.store.resource("tasks",task_id,ws)["work_item_id"]
                else:raise ValueError("budget scope must be workspace, run or work_item")
                result=runtime.budgets.set_policy(runtime.owner,scope_type=scope,scope_id=scope_id,
                    limits=limits,mode=mode,enabled=enabled)
            self._dispatch_wake.set()
            return result

    def workspaces(self):
        return [{**w,"namespace":Namespace(w["id"]).path}
                for w in self.store.workspaces()]

    def workspace_detail(self,ws):
        root=self.store.workspace(ws)
        terminals=self._list_terminals(ws)
        agents=self.store.list_resources("agents",ws)
        teams=self.store.list_resources("teams",ws)
        tasks=self.store.list_resources("tasks",ws)
        return {
            "workspace":{**root,"namespace":Namespace(ws).path},
            "terminals":[{**t,"namespace":Namespace(ws,session=t["id"]).path}
                         for t in terminals],
            "agents":[{**a,"namespace":Namespace(ws,agent=a["id"]).path}
                      for a in agents],
            "teams":[{**t,"namespace":Namespace(ws,team=t["id"]).path}
                     for t in teams],
            "tasks":[{**t,"namespace":Namespace(ws,team=t["team_id"],
                       agent=t["agent_id"],task=t["id"]).path} for t in tasks],
            "events":self.store.events(ws,limit=100)
        }

    def graph_detail(self, ws):
        state=self.workspace_detail(ws)
        canvas=self.graph.sync(ws,state["terminals"],state["agents"],state["teams"])
        return {**state, **canvas}

    def graph_move(self,ws,ident,x,y):
        self.store.workspace(ws)
        return self.graph.move(ws,ident,x,y)

    def graph_resize(self,ws,ident,width,height):
        self.store.workspace(ws)
        return self.graph.resize(ws,ident,width,height)

    def graph_note(self,ws,title,body,x=440,y=220):
        self.store.workspace(ws)
        note=self.graph.note(ws,title,body,x,y)
        self.store.event(ws,note["id"],"canvas.note.created",title)
        return note

    def graph_update_note(self,ws,ident,body):
        self.store.workspace(ws)
        return self.graph.update_note(ws,ident,body)

    def graph_remove_note(self,ws,ident):
        self.store.workspace(ws)
        self.graph.remove_note(ws,ident)
        self.store.event(ws,ident,"canvas.note.removed")
        return {"ok":True}

    def graph_link(self,ws,source,target):
        self.store.workspace(ws)
        link=self.graph.link(ws,source,target)
        self.store.event(ws,link["id"],"canvas.link.created")
        return link

    def graph_unlink(self,ws,ident):
        self.store.workspace(ws)
        self.graph.unlink(ws,ident)
        self.store.event(ws,ident,"canvas.link.removed")
        return {"ok":True}

    def handoff(self,ws,source,target,message,approved=False,request_key=None):
        """Explicit directed relay to an active agent CLI, never to a shell."""
        self.store.workspace(ws)
        if approved is not True:
            raise Denied("explicit handoff approval required")
        if (not isinstance(message,str) or not 1<=len(message.strip())<=4000
            or any(ord(ch)<32 or ord(ch)==127 for ch in message)):
            raise ValueError("handoff must be a single-line message without control characters")
        if request_key is not None:
            if not isinstance(request_key,str) or not 1<=len(request_key)<=128:
                raise ValueError("handoff request key must contain 1-128 characters")
            previous=self.graph.handoff_request(ws,source,target,message,request_key)
            if previous:
                return {"id":previous["id"],"transport":"conpty-stdin","status":previous["status"],
                        "model_acknowledged":False,"idempotent_replay":True}
        origin,destination=self.graph.linked_target(ws,source,target)
        if destination["kind"]=="agent":
            agent=self.store.resource("agents",destination["resource_id"],ws)
            if not agent["terminal_id"]:
                raise ValueError("destination agent session is not running")
            terminal=self.store.resource("terminals",agent["terminal_id"],ws)
        elif destination["kind"]=="terminal":
            terminal=self.store.resource("terminals",destination["resource_id"],ws)
        else:
            raise ValueError("destination must be a terminal or agent node")
        if terminal["shell"] not in ("sentra-cli","codex"):
            raise Denied("handoff allowed only to supported agent CLIs, not OS shells")
        session=self._sessions.get(terminal["id"])
        if session is None or session.pty is None or session.pty.poll() is not None:
            raise ValueError("destination CLI session is not running")
        result,created=self.graph.prepare_handoff(ws,source,target,message,request_key or new_id())
        if not created:
            return {"id":result["id"],"transport":"conpty-stdin","status":result["status"],
                    "model_acknowledged":False,"idempotent_replay":True}
        self.graph.handoff_state(ws,result["id"],"sending")
        try:
            # A write is evidence of transport only, NOT that a model processed it.
            session.pty.write((message+"\r").encode("utf-8"))
        except BaseException:
            self.graph.handoff_state(ws,result["id"],"uncertain")
            raise
        result=self.graph.handoff_state(ws,result["id"],"sent")
        self.store.event(ws,result["id"],"canvas.handoff.sent",
                         "transport-only "+terminal["shell"])
        return {"id":result["id"],"transport":"conpty-stdin",
                "status":"sent","model_acknowledged":False}

    def _list_terminals(self,ws):
        result=self.store.list_resources("terminals",ws)
        for terminal in result:
            session=self._sessions.get(terminal["id"])
            if session and session.pty:
                status=session.pty.poll()
                if status is not None and terminal["status"]=="running":
                    self.store.terminal_state(ws,terminal["id"],"exited")
                    terminal["status"]="exited"
                    terminal["exit_code"]=status
        return result

    def create_workspace(self,name):
        return self.store.create_workspace(name)

    def attach_workspace(self,name,path):
        return self.store.attach_workspace(name,path)

    def run_control(self,ws,action):
        self.store.workspace(ws)
        if action not in {"pause","resume","cancel"}:raise ValueError("invalid run control")
        with self._lock:
            result=self._runtime().control(ws,action)
            if action=="cancel":
                for ident,(workspace,_) in self._job_tasks.items():
                    if workspace==ws:
                        self.store.request_task_cancel(ws,ident)
                        if ident in self._jobs:self._jobs[ident].set()
            self._dispatch_wake.set()
            return result

    def _start(self,ws,name,shell,argv):
        with self._lock:
            if self._closing:
                raise RuntimeError("Canvas runtime is shutting down")
            active=sum(1 for s in self._sessions.values()
                       if s.pty is not None and s.pty.poll() is None)
            if active>=self.max_terminals:
                raise ValueError("terminal concurrency quota reached")
            workspace=self.store.workspace(ws)
            record=self.store.create_terminal(ws,name,shell)
            session=Session(
                lambda text: self.store.append_terminal_output(ws,record["id"],text),
                lambda error: self.store.event(ws,record["id"],"terminal.transcript.failed",error))
            session.exit_input=b"/exit\r" if shell=="sentra-cli" else b"\x03" if shell=="codex" else b"exit\r"
            self._sessions[record["id"]]=session
            try:
                options={}
                if shell=="sentra-cli" and self._agent_port is not None:
                    token=secrets.token_urlsafe(36)
                    self._agent_tokens[token]=(ws,record["id"])
                    environment=os.environ.copy()
                    for key in list(environment):
                        if key.startswith("MAESTRI_"):
                            environment.pop(key)
                    # This capability cannot use the UI/runtime bearer routes.
                    environment.update(SENTRA_CANVAS_AGENT_TOKEN=token,
                                       SENTRA_CANVAS_AGENT_PORT=str(self._agent_port))
                    options["env"]=environment
                session.pty=WindowsPTY(argv,Path(workspace["path"]),session.append,**options)
                self.store.terminal_state(ws,record["id"],"running",session.pty.pid)
                record.update(status="running",pid=session.pty.pid)
            except Exception:
                self.store.terminal_state(ws,record["id"],"error")
                self._sessions.pop(record["id"],None)
                self._revoke_agent(record["id"])
                raise
            return record

    def _revoke_agent(self,terminal):
        with self._lock:
            for token,(_,ident) in list(self._agent_tokens.items()):
                if ident==terminal:
                    self._agent_tokens.pop(token,None)

    def _coordination_tables(self):
        # Additive service-owned tables; preserve the Store/graph schema versions.
        with self.store.tx():
            self.store.db.execute("""CREATE TABLE IF NOT EXISTS canvas_agent_requests(
                principal TEXT NOT NULL, workspace_id TEXT NOT NULL, actor TEXT NOT NULL,
                request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(principal,workspace_id,actor,request_key))""")
            self.store.db.execute("""CREATE TABLE IF NOT EXISTS canvas_agent_nodes(
                principal TEXT NOT NULL, workspace_id TEXT NOT NULL, actor TEXT NOT NULL,
                node_id TEXT NOT NULL, PRIMARY KEY(principal,workspace_id,actor,node_id))""")

    def _coordinate_agent(self,ws,actor,origins,state,payload):
        """Finite mutations, durably reserved before starting external processes."""
        action=payload["action"]
        value=payload.get("value","")
        key=payload.get("request_key")
        if not isinstance(value,str) or len(value)>4000:
            raise ValueError("Canvas coordination value must contain at most 4000 characters")
        if not isinstance(key,str) or not 1<=len(key)<=128:
            raise ValueError("persistent coordination identity required (1-128 characters)")
        self._coordination_tables()
        binding=(self.store.principal,ws,actor)
        identity=(*binding,key)
        fingerprint=hashlib.sha256(json.dumps([action,value],ensure_ascii=False).encode()).hexdigest()
        with self.store.lock:
            previous=self.store.db.execute("""SELECT * FROM canvas_agent_requests
                WHERE principal=? AND workspace_id=? AND actor=? AND request_key=?""",identity).fetchone()
            managed={row[0] for row in self.store.db.execute("""SELECT node_id FROM canvas_agent_nodes
                WHERE principal=? AND workspace_id=? AND actor=?""",binding)}
        if previous:
            if previous["fingerprint"]!=fingerprint:
                raise ValueError("Canvas coordination idempotency collision")
            result=json.loads(previous["result"])
            return {**result,"status":previous["status"] if previous["status"]!="pending" else "uncertain",
                    "request_key":key,"idempotent_replay":True,"model_acknowledged":False}
        connected={link["target"] for link in state["links"] if link["source"] in origins}
        allowed=origins|managed|connected
        sources=origins|managed

        def resolve(value,permitted):
            matches=[n for n in state["nodes"] if n["id"] in permitted
                     and value.strip() in (n["id"],n["resource_id"],n["title"])]
            if len(matches)!=1:
                raise Denied("unique authorized Canvas node required")
            return matches[0]

        parts=value.split("|")
        # Agent nodes survive terminal replacement and keep outgoing coordination.
        source=next((n for n in state["nodes"] if n["id"] in origins and n["kind"]=="agent"),
                    next((n for n in state["nodes"] if n["id"] in origins),None))
        if source is None:
            raise Denied("Canvas coordination origin required")
        if action in {"create_agent","create_terminal"}:
            if not 2<=len(parts)<=3:
                raise ValueError("creation requires name|model|optional role")
            name,model=parts[:2]
            role=parts[2] if len(parts)==3 else "worker"
            validated_name(name)
            if not MODEL_RE.fullmatch(model) or not 1<=len(role.strip())<=80:
                raise ValueError("invalid Canvas model or role")
            terminal_name=name[:44]+"_cli" if action=="create_agent" else name
            if any(t["name"]==terminal_name for t in state["terminals"]) or (
                action=="create_agent" and any(a["name"]==name for a in state["agents"])):
                raise ValueError("Canvas resource name already exists")
            if sum(s.pty is not None and s.pty.poll() is None for s in self._sessions.values())>=self.max_terminals:
                raise ValueError("terminal concurrency quota reached")
        elif action=="connect":
            if len(parts)==1:
                destination=resolve(parts[0],allowed)
            elif len(parts)==2:
                source=resolve(parts[0],sources)
                destination=resolve(parts[1],allowed)
            else:
                raise ValueError("connect requires target or source|target")
            if source["id"]==destination["id"]:
                raise ValueError("cannot connect a node to itself")
        elif action=="create_team":
            if len(parts)!=3:
                raise ValueError("team requires name|coordinator|comma-separated workers")
            name,coordinator,workers=parts
            validated_name(name)
            coordinator=resolve(coordinator,sources)
            workers=[resolve(w,allowed) for w in workers.split(",")]
            members=[coordinator,*workers]
            if (not 1<=len(workers)<=12 or any(n["kind"]!="agent" for n in members)
                or len({n["id"] for n in members})!=len(members)):
                raise ValueError("team requires distinct authorized agents")
            if any(t["name"]==name for t in state["teams"]):
                raise ValueError("Canvas team name already exists")
        else:
            raise ValueError("unsupported Canvas coordination action")
        with self.store.tx():
            self.store.db.execute("INSERT INTO canvas_agent_requests VALUES(?,?,?,?,?,?,?,?)",
                (*identity,fingerprint,"pending","{}",time.time()))
        try:
            grants=[]
            if action in {"create_agent","create_terminal"}:
                if action=="create_agent":
                    resource=self.create_agent(ws,name,model,role,start=True)
                    terminal=resource["terminal_id"]
                    kind="agent"
                else:
                    conversation=new_id()
                    command=self._cli_command(["--workspace",self.store.workspace(ws)["path"],
                        "--model",model,"--no-auto-start","--state-dir",str(self.state_dir.parent),
                        "--session-id",conversation])
                    resource=self._start(ws,name,"sentra-cli",command)
                    resource["conversation_id"]=conversation
                    terminal=resource["id"]
                    kind="terminal"
                graph=self.graph_detail(ws)
                node=next(n for n in graph["nodes"] if n["kind"]==kind and n["resource_id"]==resource["id"])
                grants=[n["id"] for n in graph["nodes"] if
                        (n["kind"]==kind and n["resource_id"]==resource["id"]) or
                        (n["kind"]=="terminal" and n["resource_id"]==terminal)]
                link=self.graph_link(ws,source["id"],node["id"])
                result={"resource":resource,"node_id":node["id"],"link":link,
                        "status":"started","model_acknowledged":False}
            elif action=="connect":
                result={"link":self.graph_link(ws,source["id"],destination["id"]),"status":"connected"}
            else:
                team=self.create_team(ws,name,coordinator["resource_id"],[w["resource_id"] for w in workers])
                graph=self.graph_detail(ws)
                node=next(n for n in graph["nodes"] if n["kind"]=="team" and n["resource_id"]==team["id"])
                grants=[node["id"]]
                result={"resource":team,"node_id":node["id"],"status":"created"}
            result.update(request_key=key,model_acknowledged=False)
            with self.store.tx():
                self.store.db.executemany("INSERT OR IGNORE INTO canvas_agent_nodes VALUES(?,?,?,?)",
                                         [(*binding,node) for node in grants])
                self.store.db.execute("""UPDATE canvas_agent_requests SET status=?,result=?
                    WHERE principal=? AND workspace_id=? AND actor=? AND request_key=?""",
                    (result["status"],json.dumps(result,ensure_ascii=False),*identity))
            return result
        except BaseException:
            # A crash/failure can follow process creation. Never retry that mutation.
            with self.store.tx():
                self.store.db.execute("""UPDATE canvas_agent_requests SET status='uncertain'
                    WHERE principal=? AND workspace_id=? AND actor=? AND request_key=?""",identity)
            raise

    def agent_control(self,token,payload):
        """A CLI sees only its own directed graph, not the UI bearer authority."""
        with self._lock:
            binding=self._agent_tokens.get(token)
            if binding is None:
                raise Denied("unknown Canvas agent capability")
            ws,terminal=binding
            workspace=self.store.workspace(ws)
            if payload.get("workspace")!=workspace["path"]:
                raise Denied("Canvas capability belongs to another workspace")
            if terminal.startswith("task:"):
                task=self.store.resource("tasks",terminal[5:],ws)
                process=self._task_processes.get(task["id"])
                if process is None or process.poll() is not None:
                    self._revoke_agent(terminal)
                    raise Denied("Canvas task session is no longer running")
                agents={task["agent_id"]}
            else:
                session=self._sessions.get(terminal)
                if session is None or session.pty is None or session.pty.poll() is not None:
                    self._revoke_agent(terminal)
                    raise Denied("Canvas agent session is no longer running")
                agents=None
            state=self.graph_detail(ws)
            if agents is None:
                agents={a["id"] for a in state["agents"] if a["terminal_id"]==terminal}
            origins={n["id"] for n in state["nodes"]
                     if (n["kind"]=="terminal" and n["resource_id"]==terminal)
                     or (n["kind"]=="agent" and n["resource_id"] in agents)}
            connections=[link for link in state["links"] if link["source"] in origins]
            targets={link["target"] for link in connections}
            nodes=[n for n in state["nodes"] if n["id"] in targets]
            action=payload.get("action")
            if action in {"create_agent","create_terminal","connect","create_team"}:
                actor="agent:"+sorted(agents)[0] if agents else "terminal:"+terminal
                return self._coordinate_agent(ws,actor,origins,state,payload)
            if action=="list":
                return [{k:n[k] for k in ("id","kind","title","resource_id")} for n in nodes]
            value=payload.get("value","")
            if not isinstance(value,str):
                raise ValueError("Canvas command value must be text")
            target,_,content=value.partition("|")
            candidates=[n for n in nodes if target.strip() in (n["id"],n["title"])]
            if len(candidates)!=1:
                raise Denied("unique directed Canvas connection required")
            destination=candidates[0]
            source=next(link["source"] for link in connections if link["target"]==destination["id"])
            if action=="dispatch":
                key=payload.get("request_key")
                if not isinstance(key,str) or not key:
                    raise ValueError("persistent delivery identity required")
                return self.handoff(ws,source,destination["id"],content,True,key)
            if action=="check" and destination["kind"] in {"terminal","agent"}:
                ident=destination["resource_id"]
                if destination["kind"]=="agent":
                    ident=self.store.resource("agents",ident,ws)["terminal_id"]
                    if not ident:
                        return {"status":"configured","text":"","recoverable":False}
                output=self.terminal_output(ws,ident)
                return {**output,"text":output["text"][-4000:]}
            if destination["kind"]=="note":
                if action=="note_read":
                    return {"id":destination["id"],"body":destination["body"]}
                if action=="note_write":
                    return self.graph_update_note(ws,destination["id"],content)
            raise ValueError("unsupported Canvas agent operation")

    def integrations(self):
        rows=terminal_catalog(self.project_dir)
        from sentra_cli.codex_native import authenticated
        for row in rows:
            if row["id"]=="codex" and row["installed"]:
                row["native_model_authenticated"]=authenticated()
        return rows

    def create_terminal(self,ws,name,shell="powershell"):
        workspace=Path(self.store.workspace(ws)["path"])
        command=cli_argv(self.project_dir,workspace,shell)
        if shell=="sentra-cli":
            command.extend(["--state-dir",str(self.state_dir.parent)])
        return self._start(ws,name,shell,command)

    def launch_antigravity(self,ws,approved=False):
        workspace=self.store.workspace(ws)
        if approved is not True:
            raise Denied("explicit approval required to launch external application")
        adapter=resolve_adapters(self.project_dir).get("antigravity-app")
        if adapter is None:raise ValueError("Antigravity application is not installed")
        # GUI only: never claim it is a programmatic agent/ConPTY integration.
        proc=subprocess.Popen([*adapter,workspace["path"]],
                              stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.store.event(ws,str(proc.pid),"external.antigravity.launched","editor")
        return {"started":True,"pid":proc.pid,"mode":"external-app",
                "agent_api_connected":False}

    def terminal_output(self,ws,terminal,cursor=0):
        record=self.store.resource("terminals",terminal,ws)
        session=self._sessions.get(terminal)
        if not session:
            return {**self.store.terminal_output(ws,terminal,cursor),
                    "status":record["status"],"recoverable":False,
                    "persisted":True}
        data=session.output(cursor)
        state=session.pty.poll()
        data.update(status=("running" if state is None else "exited"),
                    exit_code=state,recoverable=True,
                    persisted=session.persistence_error is None,
                    persistence_error=session.persistence_error)
        return data

    def terminal_input(self,ws,terminal,data):
        self.store.resource("terminals",terminal,ws)
        if not isinstance(data,str) or len(data)>4096:
            raise ValueError("invalid terminal input")
        session=self._sessions.get(terminal)
        if session is None or session.pty is None:
            raise TerminalError("terminal is no longer attached")
        session.pty.write(data.encode("utf-8"))
        return {"ok":True}

    def terminal_resize(self,ws,terminal,cols,rows):
        self.store.resource("terminals",terminal,ws)
        session=self._sessions.get(terminal)
        if session is None or session.pty is None:
            raise TerminalError("terminal no longer attached")
        session.pty.resize(int(cols),int(rows))
        return {"ok":True}

    def terminal_close(self,ws,terminal):
        self.store.resource("terminals",terminal,ws)
        self._revoke_agent(terminal)
        session=self._sessions.get(terminal)
        if session and session.pty: session.pty.close(exit_input=session.exit_input)
        self.store.terminal_state(ws,terminal,"closed")
        return {"ok":True}

    def terminal_rename(self,ws,terminal,name):
        return self.store.rename_terminal(ws,terminal,name)

    def terminal_duplicate(self,ws,terminal,name):
        source=self.store.resource("terminals",terminal,ws)
        return self.create_terminal(ws,name,source["shell"])

    def _cli_command(self, arguments):
        """Use installed SENTRA CLI when frozen; source CLI in development."""
        if getattr(sys,"frozen",False):
            candidates=[Path(sys.executable).parent/"sentra-cli.exe",
                        self.project_dir/"dist"/"sentra-cli.exe",
                        self.project_dir/"sentra-cli.exe"]
            executable=next((x for x in candidates if x.is_file()),None)
            if executable is None:
                raise FileNotFoundError("SENTRA CLI executable not installed; install CLI to run real agents")
            return [str(executable),*arguments]
        source_root=Path(__file__).resolve().parents[1]
        launch=("import sys;sys.path.insert(0,"+repr(str(source_root))+
                ");from sentra_cli.__main__ import main;sys.exit(main())")
        return [sys.executable,"-c",launch,*arguments]

    def create_agent(self,ws,name,model,role="worker",start=False):
        validated_name(name)
        if not isinstance(model,str) or not MODEL_RE.fullmatch(model):
            raise ValueError("invalid model identifier")
        if not isinstance(role,str) or not 1 <= len(role.strip()) <= 80:
            raise ValueError("invalid agent role")
        if not start:
            return self.store.create_agent(ws,name,model,role)
        # Process started is NOT evidence of authenticated model readiness.
        conversation_id=new_id()
        command=self._cli_command(["--workspace",self.store.workspace(ws)["path"],
                                   "--model",model,"--no-auto-start",
                                   "--state-dir",str(self.state_dir.parent),"--session-id",conversation_id])
        t=self._start(ws,name[:44]+"_cli","sentra-cli",command)
        try:
            return self.store.create_agent(ws,name,model,role,t["id"],conversation_id)
        except BaseException:
            self.terminal_close(ws,t["id"])
            raise

    def restart_agent(self,ws,agent_id):
        with self._lock:
            agent=self.store.resource("agents",agent_id,ws)
            existing=self._sessions.get(agent["terminal_id"])
            if existing and existing.pty and existing.pty.poll() is None:
                return agent
            command=self._cli_command(["--workspace",self.store.workspace(ws)["path"],
                "--model",agent["model"],"--no-auto-start","--state-dir",str(self.state_dir.parent),
                "--session-id",agent["conversation_id"]])
            terminal=self._start(ws,agent["name"][:35]+"_cli_"+new_id()[:8],"sentra-cli",command)
            try:
                return self.store.attach_agent_terminal(ws,agent_id,terminal["id"])
            except BaseException:
                self.terminal_close(ws,terminal["id"])
                raise

    def create_team(self,ws,name,coordinator,workers):
        return self.store.create_team(ws,name,coordinator,workers)

    def team_members(self,ws,team):
        return self.store.team_members(ws,team)

    def delegate(self,ws,team,agent,prompt,request_key,provider="test",
                 approved=False,*,checks=None):
        with self._lock:
            if self._closing:
                raise RuntimeError("Canvas runtime is shutting down")
            if provider=="sentra-cli" and approved is not True:
                raise Denied("explicit approval required before CLI can edit project")
            task,created=self.store.create_task(ws,team,agent,provider,prompt,request_key,
                approved=approved,max_pending=self.max_pending_tasks,checks=checks)
            self._dispatch_wake.set()
            return task

    def _run_task(self,ws,task,cancel):
        ident=task["id"]
        process=None
        try:
            if cancel.is_set():
                self.store.task_state(ws,ident,"cancelled"); return
            self.store.task_state(ws,ident,"running")
            if task["provider"]=="test":
                # Explicit deterministic TEST PROVIDER, never represented as AI.
                result="PROVEDOR DE TESTE (sem inferência): "+task["prompt"][:300]
                if cancel.wait(.08):
                    self.store.task_state(ws,ident,"cancelled"); return
                self.store.task_state(ws,ident,"succeeded",result)
                return
            agent=self.store.resource("agents",task["agent_id"],ws)
            # No automatic restart/retry of uncertain model responses.
            command=self._cli_command([
                "--prompt-stdin","--workspace",self.store.workspace(ws)["path"],
                "--model",agent["model"],"--no-auto-start","--timeout","90"])
            command.extend(["--state-dir",str(self.state_dir.parent),"--session-id","task_"+ident])
            with self._lock:
                if self._closing or cancel.is_set():
                    self.store.task_state(ws,ident,"cancelled");return
                environment=os.environ.copy()
                for key in list(environment):
                    if key.startswith(("MAESTRI_","SENTRA_CANVAS_AGENT_")):environment.pop(key)
                if self._agent_port is not None:
                    token=secrets.token_urlsafe(36)
                    self._agent_tokens[token]=(ws,"task:"+ident)
                    environment.update(SENTRA_CANVAS_AGENT_TOKEN=token,SENTRA_CANVAS_AGENT_PORT=str(self._agent_port))
                process=TaskProcess(
                    command,cwd=str(self.project_dir),stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,stdin=subprocess.PIPE,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),env=environment)
                self._task_processes[ident]=process
            deadline=time.monotonic()+120
            pending_input=task["prompt"].encode("utf-8")
            while True:
                try:
                    value=pending_input;pending_input=None
                    out,_=process.communicate(input=value,timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancel.is_set():
                        self._stop_task_process(process)
                        self.store.task_state(ws,ident,self._task_outcome(ws,task,process.returncode,True))
                        return
                    if time.monotonic()>deadline:
                        self._stop_task_process(process)
                        raise TimeoutError("SENTRA CLI exceeded 120 second deadline")
            text=sanitize_error(out.decode("utf-8","replace"))
            self.store.task_state(ws,ident,
                                  self._task_outcome(ws,task,process.returncode,cancel.is_set()),
                                  text[-10000:] or f"exit code {process.returncode}")
        except Exception as exc:
            if process is not None and process.poll() is None:
                self._stop_task_process(process)
            outcome=self._task_outcome(ws,task,process.returncode,cancel.is_set()) if process is not None else "failed"
            self.store.task_state(ws,ident,outcome,sanitize_error(f"{type(exc).__name__}: {exc}"))
        finally:
            self._revoke_agent("task:"+ident)
            with self._lock:
                self._jobs.pop(ident,None)
                self._task_threads.pop(ident,None)
                if process is None or process.poll() is not None:
                    self._task_processes.pop(ident,None)
                    self._job_tasks.pop(ident,None)
            self._dispatch_wake.set()

    @staticmethod
    def _stop_task_process(process):
        if isinstance(process,TaskProcess):
            process.terminate_tree()
            process.communicate(timeout=5)
            return
        if process.poll() is None:
            if os.name=="nt":
                subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            else:
                process.kill()
        process.communicate(timeout=5)

    def _task_outcome(self,ws,task,returncode,cancelled=False):
        from sentra_core.conversations import ConversationStore
        try:
            store=ConversationStore(self.state_dir.parent)
            sid="task_"+task["id"]
            store.open(self.store.workspace(ws)["path"],session_id=sid,resume=True)
            status=store.status(sid)
            if status["uncertain_calls"]:
                return "uncertain"
            if status["state"]=="completed" and returncode==0:
                return "succeeded"
            if status["state"]=="provider_error":
                return "failed"
            if cancelled and status["state"]=="ready" and not status["message_count"]:
                return "cancelled"
            return "uncertain"
        except Exception:
            # Missing or unreadable journals cannot prove no submission/effect.
            return "uncertain"

    def cancel_task(self,ws,task):
        with self._lock:
            row=self.store.request_task_cancel(ws,task)
            if row["status"]=="queued":
                self.store.task_state(ws,task,"cancelled")
            elif task in self._jobs:
                self._jobs[task].set()
            self._dispatch_wake.set()
        # Cancellation is cooperative; not declared cancelled until worker acknowledges.
        return {"requested":row["status"] in {"queued","running"}}

    def shutdown(self):
        with self._shutdown_lock:
            self._shutdown()

    def _shutdown(self):
        with self._lock:
            if self._closed:return
            self._closing=True
            self._dispatch_stop.set()
            self._dispatch_wake.set()
            self._agent_tokens.clear()
            for event in self._jobs.values():event.set()
            threads=list(self._task_threads.values())
        self._dispatch_thread.join(timeout=5)
        deadline=time.monotonic()+25
        for thread in threads:
            thread.join(timeout=max(0,deadline-time.monotonic()))
        # Keep the databases and owner lease alive if cancellation has not ended
        # an owned worker. A later explicit shutdown can retry safely.
        with self._lock:
            if any(thread.is_alive() for thread in self._task_threads.values()) or any(
                process.poll() is None for process in self._task_processes.values()):
                raise RuntimeError("Canvas workers have not stopped; runtime ownership retained")
        for sess in list(self._sessions.values()):
            if sess.pty:
                try: sess.pty.close(exit_input=sess.exit_input)
                except (OSError,TerminalError): pass
        if self._task_runtime:
            # Publish final task states before closing the shared registry.
            try:
                for task in self.store.projection_tasks():
                    try:self._task_runtime.project(task)
                    except Exception as exc:self._task_runtime_error=type(exc).__name__
            finally:self._task_runtime.close()
        self.graph.close()
        self.store.close()
        self.instance_lock.close()
        self._closed=True
