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
        self._machine_host=None
        self._collab_authority=None
        self._collab_process=None
        self._plan_history=None
        self._network_settings=None
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

    def _machine_service(self):
        """Share the existing durable state; the host owns only dispatch machinery."""
        with self._lock:
            if self._machine_host is None:
                from sentra_mcp.services.context import ContextBusService
                from sentra_mcp.services.control_plane import ControlPlaneService
                from sentra_runtime.machine_host import MachineHost
                runtime = self._runtime()
                control = ControlPlaneService(runtime.durable, ContextBusService(self.state_dir.parent))
                self._machine_host = MachineHost(control, owner=runtime.owner)
                def validate_scope(config):
                    workspace = self.store.workspace(config["workspace_id"])
                    self.store.resource("agents",config["agent_id"],config["workspace_id"])
                    if Path(workspace["path"]).resolve(strict=True) != Path(config["workspace_root"]).resolve(strict=True):
                        raise Denied("persisted machine workspace root changed")
                self._machine_host.restore(validate_scope)
            return self._machine_host

    def center_machines(self, ws):
        self.store.workspace(ws)
        host=self._machine_service()
        return {"machines": host.inventory(ws), "work_items":host.task_catalog(workspace_id=ws),
                "restore_errors":host.restore_errors}

    def center_telemetry(self,ws,config=None):
        self.store.workspace(ws)
        host=self._machine_service()
        return host.configure_telemetry(config) if config is not None else host.telemetry_status()

    def agent_working_context(self,ws,agent_id,*,goal=None,expected_revision=None):
        from .agent_context import AgentWorkingContext
        contexts=AgentWorkingContext(self.store)
        if goal is None:return contexts.get(ws,agent_id)
        return contexts.set(ws,agent_id,goal=goal,expected_revision=expected_revision)

    def center_network(self,ws,configuration=None,*,agent=False):
        with self._lock:
            if self._network_settings is None:
                from .network_settings import WorkspaceNetworkSettings
                self._network_settings=WorkspaceNetworkSettings(self.store)
                self._network_settings.restore()
            network=self._network_settings
        return network.configure(ws,configuration,agent=agent) if configuration is not None else network.status(ws)

    def center_network_pairing(self,ws):
        self.center_network(ws)
        return self._network_settings.pairing_code(ws)

    def _working_context_snapshot(self,ws,agents,origins,state):
        workspace=self.store.workspace(ws);runtime=self._runtime();run=runtime.run(ws)
        assignments=runtime.governance.list_work_items(runtime.owner,run_id=run["run_id"],
            states=["QUEUED","RUNNING","BLOCKED","VALIDATING"],limit=1000)["items"]
        own=[item for item in assignments if item.get("assignee_agent_id") in agents and
            item.get("metadata",{}).get("workspace_id")==ws]
        targets={link["target"] for link in state["links"] if link["source"] in origins}
        directed=[node for node in state["nodes"] if node["id"] in targets]
        return {"schema_version":1,"workspace":{"id":ws,"name":workspace["name"],"path":workspace["path"]},
            "run":{"run_id":run["run_id"],"state":run["state"]},
            "agents":[{"id":agent,"name":self.store.resource("agents",agent,ws)["name"],
                "role":self.store.resource("agents",agent,ws)["role"],
                "working_context":self.agent_working_context(ws,agent)} for agent in sorted(agents)],
            "work_items":[{key:item.get(key) for key in ("work_item_id","objective","state","required_capabilities","blockers")} for item in own[:32]],
            "connections":[{key:node[key] for key in ("id","kind","title","resource_id")} for node in directed[:64]],
            "notes":[{"id":node["id"],"body":str(node.get("body", ""))[:4000]} for node in directed if node["kind"]=="note"][:8],
            "context_creates_permissions":False,"automatic_coordination_available":True}

    def center_overview(self,ws,*,operation_offset=0,work_item_offset=0):
        """Current owner-scoped central state, with bounded metadata pages."""
        self.store.workspace(ws)
        runtime=self._runtime();host=self._machine_service();run=runtime.run(ws)
        operations=runtime.durable.list_operations(run["run_id"],runtime.owner,limit=50,offset=operation_offset)
        work=host.control.list_work_items(runtime.owner,run_id=run["run_id"],limit=50,offset=work_item_offset)
        visible=[item for item in work["items"] if item.get("metadata",{}).get("workspace_id")==ws]
        return {"run":{key:run[key] for key in ("run_id","state","desired_state","updated_at","last_event_seq")},
            "work_items":{"items":[{key:item.get(key) for key in ("work_item_id","objective","state",
                "assignee_agent_id","required_capabilities","updated_at","blockers")} for item in visible],"page":work["page"]},
            "operations":operations,"machines":host.inventory(ws),"restore_errors":host.restore_errors,
            "cost":host.control.cost_summary(runtime.owner,run_id=run["run_id"]),
            "budget_policies":self.budget_policies(ws)["items"],"telemetry":host.telemetry_status(),
            "consistency":"current-read","provider_registration_proves_execution":False}

    def center_configure_machine(self, ws, agent_id, kind, *, profiles=None, headless=True,
                                 recalculation_backends=None,ocr_backends=None,provider_config=None,definitions=None):
        """Authenticated owner configuration; agent tokens cannot call this method."""
        workspace = self.store.workspace(ws)
        self.store.resource("agents", agent_id, ws)
        host = self._machine_service()
        if kind == "documents":
            return host.configure_documents(workspace_id=ws, workspace_root=workspace["path"],
                                            agent_id=agent_id,recalculation_backends=recalculation_backends,
                                            ocr_backends=ocr_backends)
        if kind == "browser":
            return host.configure_browser(workspace_id=ws, workspace_root=workspace["path"],
                agent_id=agent_id, profiles=profiles, headless=headless)
        if kind == "openhands":
            return host.configure_openhands(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,provider_config=provider_config)
        if kind == "workflow":
            return host.configure_workflow(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,definitions=definitions)
        if kind in {"daytona","guacamole","rustdesk"}:
            return host.configure_session(workspace_id=ws,workspace_root=workspace["path"],
                agent_id=agent_id,kind=kind,provider_config=provider_config)
        raise ValueError("unsupported machine kind")

    def center_prepare_task(self, ws, machine_id, capabilities, objective):
        """Owner explicitly creates a scoped task/grant for a configured machine."""
        self.store.workspace(ws)
        host = self._machine_service()
        selected = next((m for m in host.inventory(ws) if m["machine_id"] == machine_id), None)
        if (selected is None or not isinstance(capabilities, list) or not capabilities
                or any(not isinstance(c, str) for c in capabilities)
                or not set(capabilities) <= set(selected["capabilities"])
                or not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000):
            raise ValueError("configured machine, explicit capabilities and objective required")
        runtime = self._runtime()
        run = runtime.run(ws)
        control = host.control
        if run["state"] == "CREATED":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING",
                                           reason="owner prepared a machine task")
        elif run["state"] != "RUNNING":
            raise Denied("resume the Canvas run before preparing a machine task")
        control.ensure_agent(run["run_id"], runtime.owner,
                             agent_id=selected["agent_id"], role="worker")
        item = control.create_work_item(run["run_id"], runtime.owner,
            work_item_id="WI-machine-" + secrets.token_hex(12), objective=objective.strip(),
            assignee_agent_id=selected["agent_id"], required_capabilities=sorted(set(capabilities)),
            metadata={"workspace_id": ws, "machine_id": machine_id,
                      "canvas_agent_id": selected["agent_id"], "owner_configured": True})
        grants = [control.authorization_grant(runtime.owner, principal_type="agent",
                    principal_id=selected["agent_id"], capability=cap,
                    scope_type="work_item", scope_id=item["work_item_id"])
                  for cap in sorted(set(capabilities))]
        control.transition_work_item(item["work_item_id"], runtime.owner, "RUNNING")
        return {"work_item": control.work_item_info(item["work_item_id"], runtime.owner),
                "machine_id": machine_id, "grant_ids": [g["grant_id"] for g in grants]}

    def center_execute(self, ws, work_item_id, machine_id, capability_id, operation_id,
                       arguments, request_key):
        self.store.workspace(ws)
        return self._machine_service().dispatch(workspace_id=ws, work_item_id=work_item_id,
            machine_id=machine_id, capability_id=capability_id, operation_id=operation_id,
            arguments=arguments, idempotency_key=request_key)

    def center_operation(self, ws, operation_id, *, as_owner=True):
        self.store.workspace(ws)
        return self._machine_service().observe(workspace_id=ws, operation_id=operation_id,
                                               as_owner=as_owner)

    def center_experiences(self, ws, work_item_id, machine_id, query, limit=5):
        self.store.workspace(ws)
        return self._machine_service().experiences(workspace_id=ws,work_item_id=work_item_id,
            machine_id=machine_id,query=query,limit=limit)

    def center_plan(self, ws, work_item_id, action="read", steps=None, expected_revision=None):
        self.store.workspace(ws)
        host=self._machine_service()
        item=host.control.work_item_info(work_item_id,host.owner)
        if item.get("metadata",{}).get("workspace_id")!=ws:
            raise Denied("plan task outside workspace")
        with self._lock:
            if self._plan_history is None:
                from sentra_runtime.plan_history import PlanHistory
                self._plan_history=PlanHistory(host.control,owner=host.owner)
        if action=="read":return self._plan_history.current(work_item_id)
        if action=="revise":return self._plan_history.revise(work_item_id,steps,expected_revision=expected_revision)
        if action in {"undo","redo"}:
            return self._plan_history.navigate(work_item_id,direction=action,expected_revision=expected_revision)
        raise ValueError("unknown plan action")

    def _agent_machine_control(self, token, payload):
        # Validate a live agent session under the Canvas lock, then release it
        # before potentially long provider I/O so other agents/UI remain usable.
        with self._lock:
            binding = self._agent_tokens.get(token)
            if binding is None:
                raise Denied("unknown Canvas agent capability")
            ws, terminal = binding
            workspace = self.store.workspace(ws)
            if payload.get("workspace") != workspace["path"]:
                raise Denied("Canvas capability belongs to another workspace")
            if terminal.startswith("task:"):
                task = self.store.resource("tasks", terminal[5:], ws)
                process = self._task_processes.get(task["id"])
                if process is None or process.poll() is not None:
                    self._revoke_agent(terminal)
                    raise Denied("Canvas task session is no longer running")
                agents = {task["agent_id"]}
            else:
                session = self._sessions.get(terminal)
                if session is None or session.pty is None or session.pty.poll() is not None:
                    self._revoke_agent(terminal)
                    raise Denied("Canvas agent session is no longer running")
                agents = {a["id"] for a in self.store.list_resources("agents", ws)
                          if a.get("terminal_id") == terminal}
        action = payload["action"]
        if action == "machine_list":
            host=self._machine_service()
            tasks=host.task_catalog(workspace_id=ws,agent_ids=agents)
            scopes={}
            for item in tasks:scopes.setdefault(item["machine_id"],set()).update(item["capabilities"])
            return {"machines":[{**m,"capabilities":sorted(scopes[m["machine_id"]]),
                "actions":{cap:values for cap,values in m["actions"].items() if cap in scopes[m["machine_id"]]}}
                for m in host.inventory(ws) if m["machine_id"] in scopes],"work_items":tasks}
        runtime = self._runtime()
        if action == "machine_observe":
            row = runtime.durable.operation_status(payload["operation_id"], runtime.owner)
            if (row.get("progress") or {}).get("principal_id") not in agents:
                raise Denied("operation belongs to another Canvas agent")
            return self.center_operation(ws, payload["operation_id"], as_owner=False)
        item = runtime.governance.work_item_info(payload["work_item_id"], runtime.owner)
        if (item.get("assignee_agent_id") not in agents
                or item.get("metadata", {}).get("workspace_id") != ws):
            raise Denied("machine task belongs to another Canvas agent")
        if action == "machine_experiences":
            return self.center_experiences(ws,payload["work_item_id"],payload["machine_id"],
                payload["query"],payload.get("limit",5))
        return self.center_execute(ws, payload["work_item_id"], payload["machine_id"],
            payload["capability_id"], payload["operation_id"], payload["arguments"],
            payload["request_key"])

    def _collaboration_service(self):
        with self._lock:
            if self._collab_authority is None:
                from sentra_collab.authority import CollaborationAuthority
                host = self._machine_service()
                self._collab_authority = CollaborationAuthority(host.control, owner=host.owner)
            return self._collab_authority

    def collab_session(self, ws, work_item_id, principal_id, permission="read"):
        """Owner-issued one-use ticket; grants must already exist in ControlPlane."""
        self.store.workspace(ws)
        return self._collaboration_service().issue(workspace_id=ws, principal_id=principal_id,
            work_item_id=work_item_id, principal_type="user", permission=permission)

    def collab_prepare(self, ws, principal_id):
        """Explicit owner action creates a user-scoped presentation task only."""
        from sentra_collab.authority import _id
        self.store.workspace(ws)
        principal_id = _id(principal_id)
        host = self._machine_service()
        runtime = self._runtime()
        run = runtime.run(ws)
        if run["state"] == "CREATED":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING",
                                           reason="owner enabled Canvas collaboration")
        elif run["state"] != "RUNNING":
            raise Denied("resume the Canvas run before enabling collaboration")
        caps = ["canvas.collab.read", "canvas.collab.write"]
        item = host.control.create_work_item(run["run_id"], host.owner,
            work_item_id="WI-collab-" + secrets.token_hex(12),
            objective="Collaborative Canvas layout and existing note text",
            assignee_user_id=principal_id, required_capabilities=caps,
            metadata={"workspace_id":ws,"owner_configured":True,"canvas_collaboration":True})
        for cap in caps:
            host.control.authorization_grant(host.owner, principal_type="user",
                principal_id=principal_id, capability=cap, scope_type="work_item",
                scope_id=item["work_item_id"])
        host.control.transition_work_item(item["work_item_id"], host.owner, "RUNNING")
        return {"work_item_id":item["work_item_id"],"principal_id":principal_id}

    def collab_disable(self, ws, work_item_id, principal_id):
        self.store.workspace(ws)
        host = self._machine_service()
        item = host.control.work_item_info(work_item_id, host.owner)
        if (item.get("assignee_user_id") != principal_id
                or item.get("metadata", {}).get("workspace_id") != ws
                or item.get("metadata", {}).get("canvas_collaboration") is not True):
            raise Denied("collaboration task identity mismatch")
        rows = host.control.authorization.list_grants(host.owner,
            principal_type="user", principal_id=principal_id)["items"]
        for grant in rows:
            if grant["scope_type"] == "work_item" and grant["scope_id"] == work_item_id:
                host.control.authorization.revoke(grant["grant_id"], host.owner)
        if item["state"] == "RUNNING":
            host.control.transition_work_item(work_item_id, host.owner, "CANCELLED")
        return {"disabled":True}

    def collab_host_call(self, method, params):
        """Private bearer-authenticated callbacks for the owned Node sidecar."""
        if not isinstance(params, dict):
            raise ValueError("collaboration callback parameters required")
        authority = self._collaboration_service()
        if method == "resolveGrant":
            self.store.workspace(params["workspaceId"])
            return authority.resolve(token=params["token"], workspace_id=params["workspaceId"])
        if method == "checkGrant":
            self.store.workspace(params["workspaceId"])
            return authority.check(params, action=params.get("action", "read"))
        if method == "consumeNonce":
            self.store.workspace(params["workspaceId"])
            return authority.consume(params, fingerprint=params["fingerprint"])
        if method == "loadSnapshot":
            self.store.workspace(params["workspaceId"])
            return authority.load(params["workspaceId"])
        if method == "commitSnapshot":
            self.store.workspace(params["workspaceId"])
            context = params["context"]
            if (context.get("workspaceId") != params["workspaceId"]
                    or context.get("principalId") != params["principalId"]
                    or context.get("epoch") != params["epoch"]):
                raise Denied("collaboration commit identity mismatch")
            result = authority.commit(context=context, expected_revision=params["expectedRevision"],
                snapshot=params["snapshot"], presentation=params["presentation"])
            # Snapshot commits first. A crash during projection is repaired on
            # the next graph read; an unknown acknowledgement is never replayed.
            self._apply_collaboration(params["workspaceId"], authority)
            return result
        raise ValueError("unsupported collaboration callback")

    def _apply_collaboration(self, ws, authority=None):
        authority = authority or self._collaboration_service()
        stored = authority.load(ws)
        self.graph.apply_presentation(ws, stored["revision"], stored["presentation"])
        return stored

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
        stored = self._apply_collaboration(ws)
        canvas = self.graph.snapshot(ws)
        return {**state, **canvas, "collaboration_revision": stored["revision"],
                "collaboration_layout": stored["presentation"]["layout"]}

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

    def _uncertain_receipts_for_terminal(self,ws,terminal):
        agents={a["id"] for a in self.store.list_resources("agents",ws)
                if a["terminal_id"]==terminal}
        targets={n["id"] for n in self.graph.snapshot(ws)["nodes"]
                 if (n["kind"]=="terminal" and n["resource_id"]==terminal)
                 or (n["kind"]=="agent" and n["resource_id"] in agents)}
        return self.graph.interrupt_handoffs(ws,targets)

    def _list_terminals(self,ws):
        result=self.store.list_resources("terminals",ws)
        for terminal in result:
            session=self._sessions.get(terminal["id"])
            if session and session.pty:
                status=session.pty.poll()
                if status is not None and terminal["status"]=="running":
                    self._uncertain_receipts_for_terminal(ws,terminal["id"])
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

        parts=value.split("|");brief=None
        if action=="create_agent" and value.lstrip().startswith("{"):
            structured=json.loads(value)
            if not isinstance(structured,dict) or set(structured)-{"name","model","role","brief"}:
                raise ValueError("unsupported structured agent creation field")
            parts=[structured.get("name"),structured.get("model"),structured.get("role","worker")]
            if any(not isinstance(v,str) for v in parts):raise ValueError("agent name/model/role must be text")
            brief=structured.get("brief")
            if brief is not None and (not isinstance(brief,str) or not 1<=len(brief)<=3200):
                raise ValueError("bounded child-agent brief required")
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
                # Make the created identities recoverable before an optional
                # bootstrap delivery. A lost delivery never recreates the child.
                with self.store.tx():
                    self.store.db.executemany("INSERT OR IGNORE INTO canvas_agent_nodes VALUES(?,?,?,?)",
                        [(*binding,ident) for ident in grants])
                    self.store.db.execute("UPDATE canvas_agent_requests SET result=? WHERE principal=? AND workspace_id=? AND actor=? AND request_key=?",
                        (json.dumps(result,ensure_ascii=False),*identity))
                if action=="create_agent":
                    from .agent_context import AgentWorkingContext
                    contexts=AgentWorkingContext(self.store)
                    parent=source["resource_id"] if source["kind"]=="agent" else None
                    snapshot=self._working_context_snapshot(ws,{parent} if parent else set(),{source["id"]},state)
                    parent_context=contexts.get(ws,parent) if parent else {"goal":""}
                    goals=snapshot["work_items"]
                    goal=brief or parent_context.get("goal") or "\n".join(item["objective"] for item in goals)
                    if goal:
                        bounded_goal=goal.encode()[:16000].decode("utf-8",errors="ignore")
                        result["working_context"]=contexts.set(ws,resource["id"],goal=bounded_goal,expected_revision=0,
                            parent_agent_id=parent,source_work_item_ids=[item["work_item_id"] for item in goals][:32])
                        message="Contexto de trabalho recebido do agente coordenador. Seu papel: "+role+". Objetivo: "+goal[:3000]+". Consulte [[CANVAS|context]] para o contexto atual, tarefas e conexões."
                        message=" ".join(re.sub(r"[\x00-\x1f\x7f]"," ",message).split())
                        bootstrap_key="bootstrap-"+hashlib.sha256(json.dumps([ws,actor,key],separators=(",",":")).encode()).hexdigest()
                        delivery=self.handoff(ws,source["id"],node["id"],message,True,bootstrap_key)
                        result["bootstrap_handoff_id"]=delivery.get("id")
                        result["bootstrap_model_answered"]=False
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
        if payload.get("action") in {"machine_list", "machine_execute", "machine_observe", "machine_experiences"}:
            return self._agent_machine_control(token, payload)
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
            action=payload.get("action")
            if action=="context":
                return self._working_context_snapshot(ws,agents,origins,state)
            if action=="network_settings":return self.center_network(ws)
            if action=="network_whitelist":
                value=json.loads(payload.get("value",""))
                return self.center_network(ws,value,agent=True)
            if action=="peers":return self.center_network(ws)["presence"]
            if action in {"claim", "receipt"}:
                if terminal.startswith("task:"):
                    raise Denied("task workers cannot claim interactive handoffs")
                if action=="claim":
                    value=payload.get("value")
                    if not isinstance(value,str) or not 1<=len(value)<=4000:
                        raise ValueError("invalid handoff content")
                    return self.graph.claim_handoff(ws,origins,value) or {"status":"not_found"}
                ident=payload.get("handoff_id")
                if not isinstance(ident,str) or not re.fullmatch(r"[0-9a-f]{32}",ident):
                    raise ValueError("invalid receipt identifier")
                return self.graph.complete_handoff(ws,ident,origins,payload.get("receipt_status"))
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
                receipts=[{"id":h["id"],"transport_status":h["status"],
                           "receipt_status":h["receipt_status"],"receipt_updated":h["receipt_updated"]}
                          for h in self.graph.handoffs(ws,limit=100)
                          if h["source"]==source and h["target"]==destination["id"]]
                return {**output,"text":output["text"][-4000:],"handoffs":receipts[:10]}
            if destination["kind"]=="note":
                if action=="note_read":
                    return {"id":destination["id"],"body":destination["body"]}
                if action=="note_write":
                    return self.graph_update_note(ws,destination["id"],content)
            raise ValueError("unsupported Canvas agent operation")

    def model_catalog(self):
        """Advisory model names from the authenticated Gateway; never attest access."""
        from sentra_cli.client import ModelClient,ProviderHTTPError
        from sentra_cli.config import CLIConfig
        cfg=CLIConfig(workspace=self.project_dir,state_root=self.state_dir.parent,
                      openai_api_key="none",auto_start_gateway=False)
        try:
            models=ModelClient(cfg).list_models()
            return {"models":[name for name in models if isinstance(name,str)
                              and name.startswith(("sentra/","chatgpt-web/","gemini-web/"))],
                    "source":"authenticated_catalog",
                    "model_access_verified":False}
        except (ProviderHTTPError,OSError,ValueError,RuntimeError):
            return {"models":[],"source":"unavailable","model_access_verified":False}

    def center_capabilities(self, ws):
        """Authenticated Canvas read-only view of operational integration."""
        self.store.workspace(ws)
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        machines = self._machine_host.inventory(ws) if self._machine_host is not None else []
        return {
            "center": "SENTRA Control Plane",
            "authority": "existing DurableRunService / AuthorizationService",
            "capabilities": ["canvas.workspace.inspect", *sorted({cap for machine in machines
                                                                  for cap in machine["capabilities"]})],
            "registered_machines": machines,
            "remote_executors_enabled": any(machine["kind"] in {"openhands","daytona","guacamole","rustdesk"} for machine in machines),
            "configured_local_executors_enabled": any(machine["kind"] in {"documents","browser"} for machine in machines),
            "durable_intent_api": callable(
                getattr(self._runtime().durable, "reserve_operation_intent", None)),
            "experimental": True,
        }

    def center_inspect(self, ws, work_item_id, operation_id, request_key):
        """Execute a safe lab read through LIVE durable Control Plane authority.

        This compatibility inspection has no
        filesystem/browser/desktop/terminal execution capability; an explicit
        existing SQLite grant, host-owned WorkItem and operation ID are needed.
        """
        import asyncio
        from sentra_mcp.services.authorization import AuthorizationService
        from sentra_runtime.authority_bridge import BoundWorkItemPolicy
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        from sentra_runtime.contracts import (
            Capability, Machine, OperationRequest, OperationResult,
        )
        from sentra_runtime.durable_admission import DurableOperationGate
        from sentra_runtime.executor import ExecutorRegistry

        workspace = self.store.workspace(ws)
        runtime = self._runtime()
        run = runtime.run(ws)
        item = runtime.governance.work_item_info(work_item_id, runtime.owner)
        cap_id = "canvas.workspace.inspect"
        if (item["run_id"] != run["run_id"]
                or item.get("metadata", {}).get("workspace_id") != ws
                or item.get("assignee_agent_id") in (None, "")
                or cap_id not in item.get("required_capabilities", [])):
            raise Denied("work item not bound to approved Canvas workspace capability")
        machine = Machine(
            "canvas-center-" + ws, "canvas-read-only",
            runtime.owner, (Capability(cap_id, "Read local Canvas workspace summary"),),
        )
        authorization = AuthorizationService(self.state_dir.parent)
        policy = BoundWorkItemPolicy(
            owner=runtime.owner, principal_type="agent",
            authorization=authorization, governance=runtime.governance,
        )
        request = OperationRequest(
            operation_id=operation_id,
            principal_id=item["assignee_agent_id"],
            machine_id=machine.machine_id,
            capability_id=cap_id,
            work_item_id=work_item_id,
            idempotency_key=request_key,
            arguments={"workspace_id": ws, "action": "read-only-summary"},
        )

        class _LocalReadAdapter:
            async def start(self, req):
                # The local Canvas Store is the authoritative source of counts;
                # no terminal or third-party process is started.
                count = {
                    "agents": len(self_store.list_resources("agents", ws)),
                    "teams": len(self_store.list_resources("teams", ws)),
                    "terminals": len(self_store.list_resources("terminals", ws)),
                }
                return OperationResult(req.operation_id, "SUCCEEDED", count)

            async def reconcile(self, oid):
                return OperationResult(oid, "UNCERTAIN",
                                       error="durable reconciliation required")

        self_store = self.store
        registry = ExecutorRegistry(policy)
        registry.register(machine, _LocalReadAdapter())
        gate = DurableOperationGate(
            CentralDurableIntentAuthority(runtime.durable),
            policy, machine=machine,
        )
        result = asyncio.run(gate.submit(
            run_id=workspace["run_id"], owner=runtime.owner,
            request=request, effect=registry.submit,
        ))
        return {
            "operation_id": result.operation_id, "state": result.state,
            "evidence": dict(result.evidence),
            "run_id": workspace["run_id"], "work_item_id": work_item_id,
            "source": "real-sentra-control-plane",
        }

    def integrations(self):
        rows=terminal_catalog(self.project_dir)
        from sentra_cli.codex_native import authenticated
        for row in rows:
            if row["id"]=="codex" and row["installed"]:
                row["native_model_authenticated"]=authenticated()
        return rows

    def create_terminal(self,ws,name,shell="powershell",model=None,effort=None):
        workspace=Path(self.store.workspace(ws)["path"])
        if shell=="sentra-cli":
            # Use the same authoritative CLI as Canvas agents, never a stale
            # checkout/dist binary. A selected model must be explicitly bounded.
            if model is not None and (not isinstance(model,str) or not MODEL_RE.fullmatch(model)):
                raise ValueError("invalid SENTRA CLI model")
            args=["--workspace",str(workspace),"--state-dir",str(self.state_dir.parent),
                  "--session-id",new_id()]
            if model:
                args.extend(["--model",model])
            if effort is not None:
                if not isinstance(effort,str) or effort not in {"low","medium","high","xhigh"}:
                    raise ValueError("invalid SENTRA CLI reasoning effort")
                args.extend(["--effort",effort])
            command=self._cli_command(args)
        else:
            if model is not None:
                raise ValueError("model selection requires SENTRA CLI")
            if effort is not None:
                raise ValueError("effort selection requires SENTRA CLI")
            command=cli_argv(self.project_dir,workspace,shell)
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
        if state is not None:
            self._uncertain_receipts_for_terminal(ws,terminal)
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
        self._uncertain_receipts_for_terminal(ws,terminal)
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

    def create_agent(self,ws,name,model,role="worker",start=False,*,goal=None):
        validated_name(name)
        if not isinstance(model,str) or not MODEL_RE.fullmatch(model):
            raise ValueError("invalid model identifier")
        if not isinstance(role,str) or not 1 <= len(role.strip()) <= 80:
            raise ValueError("invalid agent role")
        if goal is not None and (not isinstance(goal,str) or len(goal.encode())>16000):
            raise ValueError("bounded agent working goal required")
        if not start:
            agent=self.store.create_agent(ws,name,model,role)
            if goal is not None:self.agent_working_context(ws,agent["id"],goal=goal,expected_revision=0)
            return agent
        # Process started is NOT evidence of authenticated model readiness.
        conversation_id=new_id()
        command=self._cli_command(["--workspace",self.store.workspace(ws)["path"],
                                   "--model",model,"--no-auto-start",
                                   "--state-dir",str(self.state_dir.parent),"--session-id",conversation_id])
        t=self._start(ws,name[:44]+"_cli","sentra-cli",command)
        try:
            agent=self.store.create_agent(ws,name,model,role,t["id"],conversation_id)
            if goal is not None:self.agent_working_context(ws,agent["id"],goal=goal,expected_revision=0)
            return agent
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
        if self._collab_process is not None:
            self._collab_process.close()
        if self._network_settings is not None:
            self._network_settings.close()
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
        if self._machine_host is not None:
            # Keep central databases alive if a physical worker still owns I/O.
            self._machine_host.close()
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
