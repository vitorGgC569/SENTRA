"""Transactional SQLite storage for isolated SENTRA Canvas projects."""
from __future__ import annotations
import getpass
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from sentra_remote.secrets import protect_secret, unprotect_secret
from sentra_core.telemetry import EventJournal
from sentra_core import telemetry_outbox

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,127}$")
TRANSCRIPT_LIMIT = 120000

class Denied(PermissionError):
    """A resource cannot be accessed by this authenticated local user."""

def validated_name(name):
    if not isinstance(name,str) or not NAME_RE.fullmatch(name):
        raise ValueError("name must be 1-48 ASCII letters/numbers/_/-")
    return name

def new_id():
    return uuid.uuid4().hex

class Store:
    def __init__(self, db_path, projects_root, principal=None, *, telemetry_root=None):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.root = Path(projects_root).resolve(strict=True)
        self.principal = principal or getpass.getuser()
        self.telemetry_root=Path(telemetry_root) if telemetry_root is not None else self.path.parent
        self.telemetry=None
        self.telemetry_error=None
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False,timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA synchronous=FULL")
        with self.db:
            version=self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 5: raise RuntimeError("database migration required")
            if version == 0:
                self.db.executescript("""
                    CREATE TABLE workspaces(
                      id TEXT PRIMARY KEY,name TEXT NOT NULL,owner TEXT NOT NULL,
                      path TEXT UNIQUE NOT NULL,created REAL NOT NULL,
                      UNIQUE(owner,name));
                    CREATE TABLE terminals(
                      id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                      name TEXT NOT NULL,shell TEXT NOT NULL,status TEXT NOT NULL,
                      pid INTEGER,created REAL NOT NULL,UNIQUE(workspace_id,name));
                    CREATE TABLE agents(
                      id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                      name TEXT NOT NULL,model TEXT NOT NULL,role TEXT NOT NULL,
                      terminal_id TEXT REFERENCES terminals(id),status TEXT NOT NULL,
                      created REAL NOT NULL,UNIQUE(workspace_id,name));
                    CREATE TABLE teams(
                      id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                      name TEXT NOT NULL,created REAL NOT NULL,UNIQUE(workspace_id,name));
                    CREATE TABLE team_members(
                      team_id TEXT NOT NULL REFERENCES teams(id),
                      agent_id TEXT NOT NULL REFERENCES agents(id),
                      role TEXT NOT NULL CHECK(role IN ('coordinator','worker')),
                      PRIMARY KEY(team_id,agent_id));
                    CREATE TABLE tasks(
                      id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                      team_id TEXT NOT NULL REFERENCES teams(id),
                      agent_id TEXT NOT NULL REFERENCES agents(id),
                      provider TEXT NOT NULL,prompt TEXT NOT NULL,status TEXT NOT NULL,
                      result TEXT,request_key TEXT,created REAL NOT NULL,updated REAL NOT NULL,
                      UNIQUE(workspace_id,request_key));
                    CREATE TABLE events(
                      seq INTEGER PRIMARY KEY AUTOINCREMENT,
                      workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                      subject TEXT NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL,
                      created REAL NOT NULL);
                    CREATE INDEX events_workspace ON events(workspace_id,seq);
                    PRAGMA user_version=1;
                """)
            if version < 2:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("""CREATE TABLE terminal_output_state(
                    terminal_id TEXT PRIMARY KEY REFERENCES terminals(id),
                    cursor INTEGER NOT NULL, updated REAL NOT NULL)""")
                self.db.execute("""CREATE TABLE terminal_output_chunks(
                    terminal_id TEXT NOT NULL REFERENCES terminals(id),
                    start INTEGER NOT NULL, end INTEGER NOT NULL,
                    protected TEXT NOT NULL, CHECK(end > start),
                    PRIMARY KEY(terminal_id,start))""")
                self.db.execute("PRAGMA user_version=2")
            if version < 3:
                if not self.db.in_transaction:
                    self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("ALTER TABLE agents ADD COLUMN conversation_id TEXT")
                self.db.execute("UPDATE agents SET conversation_id=id")
                self.db.execute("PRAGMA user_version=3")
            if version < 4:
                if not self.db.in_transaction:self.db.execute("BEGIN IMMEDIATE")
                for definition in ("approved INTEGER NOT NULL DEFAULT 0",
                                   "cancel_requested INTEGER NOT NULL DEFAULT 0",
                                   "revision INTEGER NOT NULL DEFAULT 1",
                                   "protected_prompt TEXT NOT NULL DEFAULT ''",
                                   "protected_result TEXT NOT NULL DEFAULT ''"):
                    self.db.execute("ALTER TABLE tasks ADD COLUMN "+definition)
                self.db.execute("PRAGMA user_version=4")
            if version < 5:
                if not self.db.in_transaction:self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("ALTER TABLE workspaces ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
                self.db.execute("UPDATE workspaces SET run_id='canvas-'||id")
                self.db.execute("ALTER TABLE tasks ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
                self.db.execute("UPDATE tasks SET run_id='canvas-'||workspace_id")
                self.db.execute("PRAGMA user_version=5")
            self.db.execute("CREATE TABLE IF NOT EXISTS task_projection_outbox(task_id TEXT PRIMARY KEY REFERENCES tasks(id),revision INTEGER NOT NULL)")
            self.db.execute("CREATE INDEX IF NOT EXISTS task_queue ON tasks(status,approved,agent_id,created,id)")
            self.db.execute("CREATE TABLE IF NOT EXISTS task_checks(task_id TEXT PRIMARY KEY REFERENCES tasks(id),protected_checks TEXT NOT NULL)")
            telemetry_outbox.initialize(self.db)
        # Old handles cannot be reattached on process restart.
        with self.tx():
            owned = "workspace_id IN (SELECT id FROM workspaces WHERE owner=?)"
            legacy=self.db.execute("SELECT * FROM tasks WHERE "+owned+
                " AND provider='sentra-cli' AND ((prompt<>'' AND protected_prompt='') OR (result<>'' AND protected_result=''))",
                (self.principal,)).fetchall()
            for row in legacy:
                prompt=self._protected(row["prompt"]) if row["prompt"] else row["protected_prompt"]
                result=self._protected(row["result"]) if row["result"] else row["protected_result"]
                self.db.execute("UPDATE tasks SET prompt='',result='',protected_prompt=?,protected_result=?,revision=revision+1 WHERE id=?",
                                (prompt,result,row["id"]))
                self._project_task(row["id"])
            interrupted = self.db.execute(
                "SELECT id,workspace_id FROM terminals WHERE " + owned +
                " AND status IN ('starting','running')", (self.principal,)).fetchall()
            self.db.execute("UPDATE terminals SET status='interrupted',pid=NULL WHERE " +
                            owned + " AND status IN ('starting','running')", (self.principal,))
            uncertain = self.db.execute(
                "SELECT id,workspace_id FROM tasks WHERE " + owned +
                " AND status='running'", (self.principal,)).fetchall()
            self.db.execute("UPDATE tasks SET status='uncertain',revision=revision+1,updated=? WHERE " +
                            owned + " AND status='running'", (time.time(), self.principal))
            self.db.execute("INSERT OR IGNORE INTO task_projection_outbox SELECT id,revision FROM tasks WHERE "+owned,
                            (self.principal,))
            for row in uncertain:self._project_task(row["id"])
            for row in interrupted:
                self._event(row["workspace_id"], row["id"], "terminal.interrupted", "runtime restart")
            for row in uncertain:
                self._event(row["workspace_id"], row["id"], "task.uncertain", "runtime restart; execution not replayed")

    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
        self._flush_telemetry()

    def _flush_telemetry(self):
        try:
            if self.telemetry is None:self.telemetry=EventJournal(self.telemetry_root)
            telemetry_outbox.flush(self.path,self.telemetry)
            self.telemetry_error=None
        except (OSError,RuntimeError,ValueError,sqlite3.Error) as exc:
            self.telemetry_error=type(exc).__name__

    def _ws(self, workspace_id):
        row=self.db.execute("SELECT * FROM workspaces WHERE id=? AND owner=?",
                            (workspace_id,self.principal)).fetchone()
        if row is None: raise Denied("workspace not accessible")
        return dict(row)

    def workspace(self, ws):
        with self.lock: return self._ws(ws)

    def workspaces(self):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT * FROM workspaces WHERE owner=? ORDER BY created",(self.principal,))]

    def create_workspace(self,name):
        validated_name(name)
        path=(self.root/name).resolve()
        if path.parent != self.root: raise Denied("workspace escapes allowed root")
        with self.tx():
            if self.db.execute("SELECT 1 FROM workspaces WHERE owner=? AND name=?",
                               (self.principal,name)).fetchone():
                raise ValueError("workspace already exists")
            path.mkdir(exist_ok=True)
            row=dict(id=new_id(),name=name,owner=self.principal,path=str(path),created=time.time())
            row["run_id"]="canvas-"+row["id"]
            self.db.execute("INSERT INTO workspaces VALUES(:id,:name,:owner,:path,:created,:run_id)",row)
            self._event(row["id"],row["id"],"workspace.created",name)
            return row

    def attach_workspace(self,name,path):
        validated_name(name)
        if not isinstance(path,str) or not Path(path).is_absolute():
            raise ValueError("absolute project directory required")
        target=Path(path).resolve(strict=True)
        if not target.is_dir():raise ValueError("project must be a directory")
        with self.tx():
            old=self.db.execute("SELECT * FROM workspaces WHERE owner=? AND path=?",(self.principal,str(target))).fetchone()
            if old:return dict(old)
            row=dict(id=new_id(),name=name,owner=self.principal,path=str(target),created=time.time())
            row["run_id"]="canvas-"+row["id"]
            self.db.execute("INSERT INTO workspaces VALUES(:id,:name,:owner,:path,:created,:run_id)",row)
            self._event(row["id"],row["id"],"workspace.attached",name)
            return row

    def new_run(self,ws):
        with self.tx():
            self._ws(ws)
            rid="canvas-"+new_id()
            self.db.execute("UPDATE workspaces SET run_id=? WHERE id=?",(rid,ws))
            self._event(ws,rid,"workspace.run.started")
            return rid

    def _event(self,ws,subject,kind,detail=""):
        self.db.execute("INSERT INTO events(workspace_id,subject,kind,detail,created) VALUES(?,?,?,?,?)",
                        (ws,subject,kind,str(detail)[:500],time.time()))
        telemetry_outbox.queue(self.db,self.telemetry,"canvas",kind,
            "uncertain" if kind.endswith(".uncertain") else "failed" if kind.endswith(".failed") else "ok",
            {"workspace_id":ws,"subject":subject},correlation_id=subject)

    def event(self,ws,subject,kind,detail=""):
        with self.tx():
            self._ws(ws); self._event(ws,subject,kind,detail)

    def _resource(self,table,ident,ws):
        if table not in {"terminals","agents","teams","tasks"}: raise ValueError("table")
        self._ws(ws)
        row=self.db.execute(f"SELECT * FROM {table} WHERE id=? AND workspace_id=?",
                            (ident,ws)).fetchone()
        if row is None: raise Denied("resource not accessible")
        return self._task_data(row) if table=="tasks" else dict(row)

    def resource(self,table,ident,ws):
        with self.lock: return self._resource(table,ident,ws)

    def list_resources(self,table,ws):
        if table not in {"terminals","agents","teams","tasks"}: raise ValueError("table")
        with self.lock:
            self._ws(ws)
            return [self._task_data(r) if table=="tasks" else dict(r) for r in self.db.execute(
                f"SELECT * FROM {table} WHERE workspace_id=? ORDER BY created",(ws,))]

    @staticmethod
    def _protected(value):
        protected=protect_secret(value)
        if not protected.startswith(("dpapi:","keyring:")):
            raise RuntimeError("task content requires OS protection")
        return protected

    def _task_data(self,row):
        data=dict(row)
        for field in ("prompt","result"):
            protected=data.pop("protected_"+field,"")
            if protected:
                if not protected.startswith(("dpapi:","keyring:")):
                    raise RuntimeError("unprotected task content rejected")
                data[field]=unprotect_secret(protected)
        data["approved"]=bool(data["approved"])
        data["cancel_requested"]=bool(data["cancel_requested"])
        data["operation_id"]="canvas-task-"+data["id"]
        data["work_item_id"]="canvas-work-"+data["id"]
        checks=self.db.execute("SELECT protected_checks FROM task_checks WHERE task_id=?",(data["id"],)).fetchone()
        if checks and not checks[0].startswith(("dpapi:","keyring:")):raise RuntimeError("unprotected task checks rejected")
        data["checks"]=json.loads(unprotect_secret(checks[0])) if checks else []
        return data

    def _project_task(self,ident):
        self.db.execute("INSERT INTO task_projection_outbox SELECT id,revision FROM tasks WHERE id=? "
                        "ON CONFLICT(task_id) DO UPDATE SET revision=excluded.revision",(ident,))

    def projection_tasks(self,limit=128):
        with self.lock:
            return [self._task_data(r) for r in self.db.execute("""SELECT t.* FROM tasks t
                JOIN task_projection_outbox o ON o.task_id=t.id
                JOIN workspaces w ON w.id=t.workspace_id WHERE w.owner=?
                ORDER BY CASE WHEN t.status IN ('queued','running') THEN 0 ELSE 1 END,t.created
                LIMIT ?""",(self.principal,min(128,max(1,int(limit)))))]

    def acknowledge_projection(self,ident,revision):
        with self.tx():
            self.db.execute("DELETE FROM task_projection_outbox WHERE task_id=? AND revision=?",
                            (ident,revision))

    def queued_tasks(self):
        with self.lock:
            return [self._task_data(r) for r in self.db.execute("""SELECT t.* FROM tasks t
                JOIN workspaces w ON w.id=t.workspace_id
                WHERE w.owner=? AND t.status='queued' AND t.approved=1
                AND NOT EXISTS(SELECT 1 FROM tasks q WHERE q.agent_id=t.agent_id
                    AND q.status='queued' AND q.approved=1
                    AND (q.created<t.created OR (q.created=t.created AND q.id<t.id)))
                ORDER BY t.created,t.id LIMIT 1024""",(self.principal,))]

    def create_terminal(self,ws,name,shell):
        validated_name(name)
        if shell not in ("powershell","pwsh","cmd","sentra-cli","codex"):
            raise ValueError("shell not allowed")
        with self.tx():
            self._ws(ws)
            row=dict(id=new_id(),workspace_id=ws,name=name,shell=shell,
                     status="starting",pid=None,created=time.time())
            self.db.execute("""INSERT INTO terminals
               (id,workspace_id,name,shell,status,pid,created)
               VALUES(:id,:workspace_id,:name,:shell,:status,:pid,:created)""",row)
            self._event(ws,row["id"],"terminal.created",name)
            return row

    def terminal_state(self,ws,terminal,status,pid=None):
        if status not in {"running","exited","error","closed","interrupted"}:
            raise ValueError("invalid state")
        with self.tx():
            self._resource("terminals",terminal,ws)
            self.db.execute("UPDATE terminals SET status=?,pid=? WHERE id=?",
                            (status,pid,terminal))
            self._event(ws,terminal,"terminal."+status,pid or "")

    def rename_terminal(self,ws,terminal,new_name):
        validated_name(new_name)
        with self.tx():
            self._resource("terminals",terminal,ws)
            if self.db.execute("SELECT 1 FROM terminals WHERE workspace_id=? AND name=? AND id<>?",
                               (ws,new_name,terminal)).fetchone():
                raise ValueError("terminal name already exists")
            self.db.execute("UPDATE terminals SET name=? WHERE id=?",(new_name,terminal))
            self._event(ws,terminal,"terminal.renamed",new_name)
            return self._resource("terminals",terminal,ws)

    def append_terminal_output(self, ws, terminal, text):
        """Commit encrypted chunks before publishing their absolute cursor."""
        if not isinstance(text, str) or len(text) > 8192:
            raise ValueError("invalid terminal output chunk")
        with self.tx():
            self._resource("terminals", terminal, ws)
            state = self.db.execute(
                "SELECT cursor FROM terminal_output_state WHERE terminal_id=?", (terminal,)).fetchone()
            start = state["cursor"] if state else 0
            if not text:
                return start
            protected = protect_secret(text)
            if not protected.startswith(("dpapi:", "keyring:")):
                raise RuntimeError("terminal transcript requires OS protected storage")
            end = start + len(text)
            self.db.execute("INSERT INTO terminal_output_chunks VALUES(?,?,?,?)",
                            (terminal, start, end, protected))
            self.db.execute("""INSERT INTO terminal_output_state VALUES(?,?,?)
                ON CONFLICT(terminal_id) DO UPDATE SET cursor=excluded.cursor,updated=excluded.updated""",
                            (terminal, end, time.time()))
            self.db.execute("DELETE FROM terminal_output_chunks WHERE terminal_id=? AND end<=?",
                            (terminal, end - TRANSCRIPT_LIMIT))
            return end

    def terminal_output(self, ws, terminal, cursor=0):
        """Recover the retained transcript without claiming a live PTY."""
        requested = max(0, int(cursor))
        with self.lock:
            self._resource("terminals", terminal, ws)
            state = self.db.execute(
                "SELECT cursor FROM terminal_output_state WHERE terminal_id=?", (terminal,)).fetchone()
            end = state["cursor"] if state else 0
            base = max(0, end - TRANSCRIPT_LIMIT)
            offset = min(end, max(base, requested))
            chunks = self.db.execute("""SELECT start,end,protected FROM terminal_output_chunks
                WHERE terminal_id=? AND end>? ORDER BY start""", (terminal, offset)).fetchall()
            pieces = []
            for chunk in chunks:
                if not chunk["protected"].startswith(("dpapi:", "keyring:")):
                    raise RuntimeError("unprotected terminal transcript rejected")
                value = unprotect_secret(chunk["protected"])
                if len(value) != chunk["end"] - chunk["start"]:
                    raise RuntimeError("terminal transcript length mismatch")
                pieces.append(value[max(0, offset - chunk["start"]):])
            return {"cursor": end, "text": "".join(pieces), "truncated": requested < base}

    def create_agent(self,ws,name,model,role,terminal_id=None,conversation_id=None):
        validated_name(name)
        if not isinstance(model,str) or not MODEL_RE.fullmatch(model):
            raise ValueError("invalid model")
        if not isinstance(role,str) or not 1 <= len(role.strip()) <= 80:
            raise ValueError("invalid role")
        from sentra_core.conversations import valid_session_id
        conversation_id=valid_session_id(conversation_id) if conversation_id else new_id()
        with self.tx():
            self._ws(ws)
            if terminal_id: self._resource("terminals",terminal_id,ws)
            row=dict(id=new_id(),workspace_id=ws,name=name,model=model,role=role,
                     terminal_id=terminal_id,status="configured",created=time.time(),conversation_id=conversation_id)
            self.db.execute("""INSERT INTO agents(id,workspace_id,name,model,role,terminal_id,status,created,conversation_id) VALUES(
                :id,:workspace_id,:name,:model,:role,:terminal_id,:status,:created,:conversation_id)""",row)
            self._event(ws,row["id"],"agent.created",name)
            return row

    def attach_agent_terminal(self,ws,agent,terminal):
        with self.tx():
            self._resource("agents",agent,ws)
            self._resource("terminals",terminal,ws)
            self.db.execute("UPDATE agents SET terminal_id=? WHERE id=?",(terminal,agent))
            self._event(ws,agent,"agent.session.started",terminal)
            return self._resource("agents",agent,ws)

    def create_team(self,ws,name,coordinator,workers):
        validated_name(name)
        if not isinstance(workers,list) or not 1 <= len(workers) <= 12:
            raise ValueError("workers list required (1-12)")
        if coordinator in workers or len(set(workers)) != len(workers):
            raise ValueError("distinct team members required")
        with self.tx():
            self._ws(ws)
            for ident in [coordinator,*workers]:
                self._resource("agents",ident,ws)
            row=dict(id=new_id(),workspace_id=ws,name=name,created=time.time())
            self.db.execute("INSERT INTO teams VALUES(:id,:workspace_id,:name,:created)",row)
            self.db.executemany("INSERT INTO team_members VALUES(?,?,?)",
                [(row["id"],coordinator,"coordinator"),
                 *[(row["id"],w,"worker") for w in workers]])
            self._event(ws,row["id"],"team.created",name)
            return row

    def team_members(self,ws,team):
        with self.lock:
            self._resource("teams",team,ws)
            return [dict(r) for r in self.db.execute("""
                SELECT a.*,m.role AS team_role FROM agents a
                JOIN team_members m ON a.id=m.agent_id
                WHERE m.team_id=? ORDER BY team_role,a.name""",(team,))]

    def create_task(self,ws,team,agent,provider,prompt,key,*,approved=False,max_pending=128,checks=None):
        from .validation import normalize_checks
        checks=normalize_checks(checks)
        if provider not in {"test","sentra-cli"}: raise ValueError("invalid provider")
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>4000:
            raise ValueError("invalid prompt")
        if not isinstance(key,str) or not 1 <= len(key) <= 128:
            raise ValueError("idempotency key required")
        with self.tx():
            self._resource("teams",team,ws)
            self._resource("agents",agent,ws)
            member=self.db.execute("""SELECT 1 FROM team_members
                 WHERE team_id=? AND agent_id=? AND role='worker'""",(team,agent)).fetchone()
            if member is None: raise Denied("not a team worker")
            old=self.db.execute("SELECT * FROM tasks WHERE workspace_id=? AND request_key=?",
                                (ws,key)).fetchone()
            if old:
                old=self._task_data(old)
                if (old["team_id"],old["agent_id"],old["provider"],old["prompt"],old["checks"]) != (
                     team,agent,provider,prompt,checks):
                    raise ValueError("idempotency collision")
                if old["status"]=="queued" and not old["approved"] and approved is True:
                    self.db.execute("UPDATE tasks SET approved=1,revision=revision+1,updated=? WHERE id=?",
                                    (time.time(),old["id"]))
                    self._project_task(old["id"])
                    self._event(ws,old["id"],"task.authorized",provider)
                return self._resource("tasks",old["id"],ws),False
            pending=self.db.execute("""SELECT COUNT(*) FROM tasks t JOIN workspaces w ON w.id=t.workspace_id
                WHERE w.owner=? AND t.status IN ('queued','running')""",(self.principal,)).fetchone()[0]
            if pending>=max_pending:raise ValueError("task queue quota reached")
            protected=self._protected(prompt) if provider=="sentra-cli" else ""
            now=time.time()
            row=dict(id=new_id(),workspace_id=ws,team_id=team,agent_id=agent,
                     provider=provider,prompt="" if protected else prompt,status="queued",result=None,
                     request_key=key,created=now,updated=now,run_id=self._ws(ws)["run_id"])
            self.db.execute("""INSERT INTO tasks(id,workspace_id,team_id,agent_id,provider,prompt,
                 status,result,request_key,created,updated,run_id) VALUES(
                 :id,:workspace_id,:team_id,:agent_id,:provider,:prompt,
                 :status,:result,:request_key,:created,:updated,:run_id)""",row)
            self.db.execute("UPDATE tasks SET approved=?,protected_prompt=?,prompt=? WHERE id=?",
                            (int(approved is True or provider=="test"),protected,
                             "" if protected else prompt,row["id"]))
            if checks:
                self.db.execute("INSERT INTO task_checks VALUES(?,?)",(row["id"],self._protected(json.dumps(checks,sort_keys=True))))
            self._project_task(row["id"])
            self._event(ws,row["id"],"task.queued",provider)
            return self._resource("tasks",row["id"],ws),True

    def task_state(self,ws,task,status,result=""):
        if status not in {"running","succeeded","failed","cancelled","uncertain"}:
            raise ValueError("invalid state")
        with self.tx():
            previous=self._resource("tasks",task,ws)
            if status==previous["status"]:
                return
            allowed={"queued":{"running","cancelled","failed"},
                     "running":{"succeeded","failed","cancelled","uncertain"}}
            if status not in allowed.get(previous["status"],set()):
                raise ValueError("task terminal state cannot be overwritten")
            text=str(result)[:10000]
            protected=self._protected(text) if text and previous["provider"]=="sentra-cli" else ""
            self.db.execute("UPDATE tasks SET status=?,result=?,protected_result=?,revision=revision+1,updated=? WHERE id=?",
                            (status,"" if protected else text,protected,time.time(),task))
            self._project_task(task)
            self._event(ws,task,"task."+status)

    def request_task_cancel(self,ws,task):
        with self.tx():
            row=self._resource("tasks",task,ws)
            if row["status"] not in {"queued","running"}:return row
            if not row["cancel_requested"]:
                self.db.execute("UPDATE tasks SET cancel_requested=1,revision=revision+1,updated=? WHERE id=?",
                                (time.time(),task))
                self._project_task(task)
                self._event(ws,task,"task.cancel_requested")
            return self._resource("tasks",task,ws)

    def events(self,ws,after=0,limit=200,search=""):
        if not isinstance(search,str) or len(search)>120:
            raise ValueError("search term too long")
        pattern="%"+search.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
        with self.lock:
            self._ws(ws)
            return [dict(r) for r in self.db.execute("""
                SELECT * FROM events WHERE workspace_id=? AND seq>?
                AND (kind LIKE ? ESCAPE '\\' OR subject LIKE ? ESCAPE '\\'
                     OR detail LIKE ? ESCAPE '\\')
                ORDER BY seq DESC LIMIT ?""",
                (ws,max(0,int(after)),pattern,pattern,pattern,min(500,int(limit))))]

    def close(self):
        with self.lock:
            self.db.close()
