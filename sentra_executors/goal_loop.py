"""Explicitly approved bounded Goal/Loop pacing over central Run/WorkItem authority.

A loop step creates one durable WorkItem and NOTHING executes it automatically.
External effects remain exclusively inside SENTRA's existing executor gate.
"""
from __future__ import annotations
from sentra_interop.workflow_storage import projection_db

import hashlib
import json
import math
import time
from typing import Any
from sentra_core.conversations import _encode

from sentra_mcp.services.control_store import SQLiteControlPlaneStore


class GoalLoopConflict(RuntimeError):
    pass


class ConversationGoalLoop:
    """Host-only conversation projection of existing Goals and bounded loops.

    No Run, Operation or Grant is created. The mapping lives in the same
    ControlPlane namespace. Sensitive objectives are encrypted in that mapping;
    the existing central Goal carries only a digest label.
    """

    def __init__(self, control: Any, conversations=None, *, clock=time.time, price_quote=None):
        self.control, self.conversations, self.clock = control, conversations, clock
        self.store = control.store
        self.loop = HostPricedGoalLoop(control,price_quote=price_quote,clock=clock) if price_quote is not None else BoundedGoalLoop(control, clock=clock)
        with projection_db(None,store=self.store) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS conversation_goal_bindings(
                owner TEXT NOT NULL, conversation_id TEXT NOT NULL,
                run_id TEXT NOT NULL, goal_id TEXT NOT NULL,
                revision INTEGER NOT NULL, protected_objective TEXT NOT NULL,
                loop_id TEXT, updated REAL NOT NULL,
                PRIMARY KEY(owner,conversation_id))""")

    def _conversation(self, owner: str, conversation_id: str, run_id=None):
        if not isinstance(conversation_id, str) or not 1 <= len(conversation_id) <= 512:
            raise ValueError("bounded logical conversation identity required")
        if self.conversations is not None:
            principal = self.conversations.principal
            if owner not in {principal, "cli:" + principal, "canvas:" + principal}:
                raise PermissionError("ConversationStore owner differs from caller")
            conversation = self.conversations.status(conversation_id)
            if run_id:
                run = self.control.durable.run_status(run_id, owner, include_details=False)
                if run.get("workspace") != conversation["workspace"]:
                    raise PermissionError("conversation and Run workspaces differ")

    def _binding(self, owner, conversation_id):
        self._conversation(owner, conversation_id)
        with projection_db(None,store=self.store) as db:
            row = db.execute("SELECT * FROM conversation_goal_bindings WHERE owner=? AND conversation_id=?",
                             (owner, conversation_id)).fetchone()
        if row:
            self._conversation(owner, conversation_id, row["run_id"])
        return dict(row) if row else None

    def set(self, owner: str, conversation_id: str, *, run_id: str, objective: str,
            operator_approved: bool = False) -> dict:
        from sentra_core.conversations import _encode, _decode
        if operator_approved is not True:
            raise PermissionError("host owner approval required to set goal")
        if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 16000:
            raise ValueError("bounded goal objective required")
        objective = objective.strip()
        self._conversation(owner, conversation_id, run_id)
        run = self.control.durable.run_status(run_id, owner, include_details=False)
        if run.get("terminal"):
            raise GoalLoopConflict("goal Run is terminal")
        with projection_db(None,store=self.store) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM conversation_goal_bindings WHERE owner=? AND conversation_id=?",
                             (owner, conversation_id)).fetchone()
            if old and old["run_id"] != run_id:
                raise GoalLoopConflict("logical conversation is bound to another Run")
            same = False
            if old:
                stored = _decode(old["protected_objective"])
                if (stored.get("owner"), stored.get("conversation_id"), stored.get("goal_id")) != (
                        owner, conversation_id, old["goal_id"]):
                    raise GoalLoopConflict("protected goal identity changed")
                goal = self.control.goal_info(old["goal_id"], owner)
                same = not goal.get("terminal") and stored["objective"] == objective
            if not same:
                if old and old["loop_id"]:
                    live = db.execute("SELECT state FROM goal_loop_pacing WHERE loop_id=?", (old["loop_id"],)).fetchone()
                    if live and live[0] == "ACTIVE":
                        raise GoalLoopConflict("stop bounded loop before replacing objective")
                if old and not goal.get("terminal"):
                    self.control.update_goal(old["goal_id"], owner, state="CANCELLED", reason="owner replaced conversation objective")
                revision = old["revision"] + 1 if old else 1
                key = "conversation-goal:" + hashlib.sha256(
                    json.dumps([owner, conversation_id, revision], separators=(",", ":")).encode()).hexdigest()
                digest = hashlib.sha256(objective.encode()).hexdigest()
                goal = self.control.create_goal(run_id, owner, objective="Protected conversation objective SHA256 " + digest,
                                                external_key=key, metadata={"source": "conversation-goal", "objective_sha256": digest})
                if goal["objective"] != "Protected conversation objective SHA256 " + digest:
                    raise GoalLoopConflict("pending central goal differs after crash")
                protected = _encode({"owner": owner, "conversation_id": conversation_id,
                                     "goal_id": goal["goal_id"], "objective": objective})
                db.execute("INSERT INTO conversation_goal_bindings VALUES(?,?,?,?,?,?,NULL,?) "
                           "ON CONFLICT(owner,conversation_id) DO UPDATE SET goal_id=excluded.goal_id,"
                           "revision=excluded.revision,protected_objective=excluded.protected_objective,"
                           "loop_id=NULL,updated=excluded.updated",
                           (owner, conversation_id, run_id, goal["goal_id"], revision, protected, self.clock()))
        return self.status(owner, conversation_id)

    def status(self, owner: str, conversation_id: str) -> dict:
        from sentra_core.conversations import _decode
        row = self._binding(owner, conversation_id)
        if row is None:
            return {"conversation_id": conversation_id, "state": "UNSET", "goal": None,
                    "goal_id": None, "loop": None, "automatic_execution": False}
        value = _decode(row["protected_objective"])
        if (value.get("owner"), value.get("conversation_id"), value.get("goal_id")) != (
                owner, conversation_id, row["goal_id"]):
            raise GoalLoopConflict("protected conversation goal identity mismatch")
        goal = {**self.control.goal_info(row["goal_id"], owner), "objective": value["objective"]}
        pacing = self.loop.status(owner, row["loop_id"]) if row["loop_id"] else None
        return {"conversation_id": conversation_id, "state": goal["state"], "goal": goal,
                "goal_id": row["goal_id"], "run_id": row["run_id"], "revision": row["revision"],
                "loop": pacing, "automatic_execution": False}

    def stop(self, owner: str, conversation_id: str, *, operator_approved: bool = False) -> dict:
        if operator_approved is not True:
            raise PermissionError("host owner approval required to stop goal")
        row = self._binding(owner, conversation_id)
        if row:
            # Persist stop before central cancellation. A restart cannot revive
            # pacing when the goal cancellation acknowledgement was lost.
            if row["loop_id"]:
                self.loop.stop(owner, row["loop_id"], operator_approved=True)
            goal = self.control.goal_info(row["goal_id"], owner)
            if not goal.get("terminal"):
                self.control.update_goal(row["goal_id"], owner, state="CANCELLED", reason="conversation owner stopped goal")
        return self.status(owner, conversation_id)

    def open(self, owner: str, conversation_id: str, *, principal_id: str,
             max_steps: int = 2, max_cost_usd: float = 0.0, deadline_seconds: float = 120,
             operator_approved: bool = False) -> dict:
        if operator_approved is not True:
            raise PermissionError("host owner approval required to open loop")
        row = self._binding(owner, conversation_id)
        if row is None:
            return self.loop_status(owner, conversation_id)
        goal = self.control.goal_info(row["goal_id"], owner)
        if goal.get("terminal"):
            raise GoalLoopConflict("conversation goal is terminal")
        run = self.control._run(row["run_id"], owner)
        self.control._agent_from_run(run, principal_id)
        try:
            opened = self.loop.open(owner, run_id=row["run_id"], goal_id=row["goal_id"], principal_id=principal_id,
                                    max_steps=max_steps, max_cost_usd=max_cost_usd,
                                    deadline_seconds=deadline_seconds, operator_approved=True)
        except PermissionError as exc:
            return {**self.status(owner, conversation_id), "state": "BLOCKED", "blocked": True,
                    "reason": str(exc), "required_capability": "goal:iterate"}
        with projection_db(None,store=self.store) as db:
            db.execute("UPDATE conversation_goal_bindings SET loop_id=?,updated=? WHERE owner=? AND conversation_id=? AND goal_id=?",
                       (opened["loop_id"], self.clock(), owner, conversation_id, row["goal_id"]))
        return self.loop_status(owner, conversation_id)

    def loop_status(self, owner: str, conversation_id: str) -> dict:
        status = self.status(owner, conversation_id)
        loop = status["loop"]
        return {**status, "state": loop["state"] if loop else "UNSET", "blocked": False}

    def loop_stop(self, owner: str, conversation_id: str, *, operator_approved: bool = False) -> dict:
        if operator_approved is not True:
            raise PermissionError("host owner approval required to stop loop")
        row = self._binding(owner, conversation_id)
        if row and row["loop_id"]:
            self.loop.stop(owner, row["loop_id"], operator_approved=True)
        return self.loop_status(owner, conversation_id)

    def advance(self, owner: str, conversation_id: str, *, objective: str,
                operator_approved: bool = False, estimated_cost_usd: float | None = None) -> dict:
        row = self._binding(owner, conversation_id)
        if row is None or not row["loop_id"]:
            raise GoalLoopConflict("conversation bounded loop is not open")
        return self.loop.advance(owner, row["loop_id"], objective=objective, operator_approved=operator_approved,
                                 estimated_cost_usd=estimated_cost_usd)


class BoundedGoalLoop:
    def __init__(self, control: Any, *, clock=time.time):
        self.control = control
        self.clock = clock
        self.store = control.store
        with projection_db(None,store=self.store) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS goal_loop_pacing(
                    loop_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL, run_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                    max_steps INTEGER NOT NULL, max_cost_usd REAL NOT NULL,
                    deadline_at REAL NOT NULL, state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(owner,run_id,goal_id));
                CREATE TABLE IF NOT EXISTS goal_loop_steps(
                    loop_id TEXT NOT NULL, step INTEGER NOT NULL,
                    external_key TEXT NOT NULL UNIQUE,
                    objective_digest TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    work_item_id TEXT,
                    PRIMARY KEY(loop_id,step));
                CREATE TABLE IF NOT EXISTS goal_loop_cost_reservations(
                    loop_id TEXT NOT NULL, step INTEGER NOT NULL,
                    micro_usd INTEGER NOT NULL CHECK(micro_usd >= 0),
                    PRIMARY KEY(loop_id,step));
            """)
            from sentra_interop.workflow_storage import ensure_column
            ensure_column(db,"goal_loop_pacing","grant_id","TEXT")

    def _check_grant(self, row: dict[str, Any]) -> dict[str, Any]:
        grant = self.control.authorization.require(
            row["owner"], principal_type="agent",
            principal_id=row["principal_id"], capability="goal:iterate",
            scope_type="goal", scope_id=row["goal_id"], local_owner=False)
        if not grant.get("grant_id"):
            raise PermissionError("explicit goal-loop grant required")
        if "grant_id" in row and row["grant_id"] != grant["grant_id"]:
            raise PermissionError("original goal-loop grant missing, revoked or replaced")
        return grant

    def _scope(self, owner: str, loop_id: str) -> dict[str, Any]:
        with projection_db(None,store=self.store) as db:
            row = db.execute("SELECT * FROM goal_loop_pacing "
                             "WHERE owner=? AND loop_id=?",
                             (owner,loop_id)).fetchone()
        if row is None:
            raise FileNotFoundError("goal loop not found for owner")
        return dict(row)

    def open(self, owner: str, *, run_id: str, goal_id: str, principal_id: str,
             max_steps: int, max_cost_usd: float, deadline_seconds: float,
             operator_approved: bool = False) -> dict[str, Any]:
        if operator_approved is not True:
            raise PermissionError("human approval required to open goal loop")
        if type(max_steps) is not int or not 1 <= max_steps <= 16:
            raise ValueError("max_steps must be 1..16")
        if (type(max_cost_usd) not in (int,float) or not 0 <= max_cost_usd <= 1000
                or max_cost_usd != max_cost_usd):
            raise ValueError("bounded cost cap required")
        if type(deadline_seconds) not in (int,float) or not 1 <= deadline_seconds <= 86400:
            raise ValueError("bounded deadline required")
        goal = self.control.goal_info(goal_id, owner)
        if goal["run_id"] != run_id or goal["state"] != "ACTIVE":
            raise GoalLoopConflict("goal does not belong to Run")
        run = self.control._run(run_id, owner)
        self.control._agent_from_run(run, principal_id)
        ident = "loop-" + hashlib.sha256(
            f"{owner}|{run_id}|{goal_id}".encode()).hexdigest()[:32]
        now = self.clock()
        values = (ident,owner,run_id,goal_id,principal_id,
                  max_steps,float(max_cost_usd),now+float(deadline_seconds))
        candidate = dict(zip(("loop_id","owner","run_id","goal_id","principal_id",
                              "max_steps","max_cost_usd","deadline_at"),values))
        grant = self._check_grant(candidate)
        with projection_db(None,store=self.store) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM goal_loop_pacing "
                             "WHERE loop_id=?", (ident,)).fetchone()
            if old:
                if any(old[k] != candidate[k] for k in (
                    "owner","run_id","goal_id","principal_id","max_steps","max_cost_usd")):
                    raise GoalLoopConflict("goal loop already configured differently")
                if old["grant_id"] is not None and old["grant_id"] != grant["grant_id"]:
                    raise PermissionError("original goal-loop grant revoked or replaced")
                if old["grant_id"] is None:
                    # Legacy loops gain a pin only on an explicit approved
                    # open; startup/status/advance never choose a new grant.
                    db.execute("UPDATE goal_loop_pacing SET grant_id=? WHERE loop_id=?", (grant["grant_id"], ident))
                return self.status(owner, ident)
            db.execute("INSERT INTO goal_loop_pacing "
                       "(loop_id,owner,run_id,goal_id,principal_id,max_steps,max_cost_usd,deadline_at,state,created_at,grant_id) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (*values,"ACTIVE",now,grant["grant_id"]))
        return self.status(owner, ident)

    def status(self, owner: str, loop_id: str) -> dict[str, Any]:
        row = self._scope(owner,loop_id)
        with projection_db(None,store=self.store) as db:
            steps = [dict(r) for r in db.execute(
                "SELECT * FROM goal_loop_steps WHERE loop_id=? ORDER BY step",
                (loop_id,)).fetchall()]
            reserved = db.execute("SELECT COALESCE(SUM(micro_usd),0) FROM "
                                  "goal_loop_cost_reservations WHERE loop_id=?",
                                  (loop_id,)).fetchone()[0]
        from sentra_core.conversations import _decode
        for step in steps:
            try:
                step["objective"]=_decode(step["objective"])["objective"]
            except Exception:
                step["objective"]=None
                step["legacy_objective_requires_protected_migration"]=True
        return {**row, "steps": steps, "reserved_cost_usd":reserved / 1_000_000, "automatic_execution": False,
                "expired": self.clock() >= row["deadline_at"],
                "remaining_steps": row["max_steps"]-len(steps)}

    def advance(self, owner: str, loop_id: str, *, objective: str,
                operator_approved: bool = False,
                estimated_cost_usd: float | None = None) -> dict[str, Any]:
        return self._advance(owner, loop_id, objective=objective,
            operator_approved=operator_approved, estimated_cost_usd=estimated_cost_usd)

    def _advance(self, owner: str, loop_id: str, *, objective: str,
                 operator_approved: bool = False,
                 estimated_cost_usd: float | None = None,
                 host_quote: tuple[str, str, int, str] | None = None) -> dict[str, Any]:
        if operator_approved is not True:
            raise PermissionError("each new iteration requires human approval")
        if not isinstance(objective,str) or not 1 <= len(objective) <= 4000:
            raise ValueError("bounded step objective required")
        row = self._scope(owner,loop_id)
        self._check_grant(row)
        if estimated_cost_usd is None:
            if row["max_cost_usd"] > 0:
                raise ValueError("positive-cost loop requires explicit step estimate")
            estimated_cost_usd = 0.0
        if (type(estimated_cost_usd) not in (int,float) or
                not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0):
            raise ValueError("finite nonnegative cost estimate required")
        micro = round(estimated_cost_usd * 1_000_000)
        if abs(micro / 1_000_000 - estimated_cost_usd) > 1e-9:
            raise ValueError("cost precision exceeds one micro-USD")
        if row["max_cost_usd"] > 0 and micro == 0:
            raise ValueError("positive-cost loop cannot request unpriced iteration")
        if row["state"] != "ACTIVE" or self.clock() >= row["deadline_at"]:
            raise GoalLoopConflict("loop stopped or timed out")
        self.control.budgets.require(
            owner, workspace=self.control._run(row["run_id"],owner).get("workspace"),
            goal_id=row["goal_id"], agent_id=row["principal_id"])
        goal = self.control.goal_info(row["goal_id"],owner)
        if goal["run_id"] != row["run_id"] or goal["state"] != "ACTIVE":
            raise GoalLoopConflict("goal is not active on this Run")
        digest = hashlib.sha256(objective.encode()).hexdigest()
        with projection_db(None,store=self.store) as db:
            db.execute("BEGIN IMMEDIATE")
            live=db.execute("SELECT state,deadline_at,max_cost_usd FROM goal_loop_pacing "
                            "WHERE owner=? AND loop_id=?",(owner,loop_id)).fetchone()
            if (live is None or live["state"]!="ACTIVE" or
                    self.clock() >= live["deadline_at"]):
                raise GoalLoopConflict("loop stopped or expired concurrently")
            last = db.execute("SELECT * FROM goal_loop_steps "
                              "WHERE loop_id=? ORDER BY step DESC LIMIT 1",
                              (loop_id,)).fetchone()
            if last and last["work_item_id"]:
                prior = self.control.work_item_info(last["work_item_id"],owner)
                if prior["state"] != "COMPLETED":
                    # The caller can retry this SAME step objective to reconcile.
                    if prior["state"] in ("FAILED", "CANCELLED"):
                        raise GoalLoopConflict("previous iteration failed; stop and review")
                    raise GoalLoopConflict("previous WorkItem has not completed")
            if last and not last["work_item_id"]:
                step = last["step"]
                if last["objective_digest"] != digest:
                    raise GoalLoopConflict("pending step intent differs")
                key = last["external_key"]
                reserved = db.execute("SELECT micro_usd FROM goal_loop_cost_reservations "
                                      "WHERE loop_id=? AND step=?",(loop_id,step)).fetchone()
                if reserved is None or reserved["micro_usd"] != micro:
                    raise GoalLoopConflict("pending step cost estimate changed")
            else:
                step = (last["step"] + 1) if last else 1
                if step > row["max_steps"]:
                    raise GoalLoopConflict("iteration cap reached")
                spent=db.execute("SELECT COALESCE(SUM(micro_usd),0) FROM "
                                 "goal_loop_cost_reservations WHERE loop_id=?",
                                 (loop_id,)).fetchone()[0]
                cap=math.floor(live["max_cost_usd"] * 1_000_000 + 1e-8)
                if spent + micro > cap:
                    raise GoalLoopConflict("goal loop cumulative cost cap reached")
                key = f"goal-loop:{loop_id}:{step}"
                db.execute("INSERT INTO goal_loop_steps VALUES(?,?,?,?,?,NULL)",
                           (loop_id,step,key,digest,_encode({"objective":objective})))
                db.execute("INSERT INTO goal_loop_cost_reservations VALUES(?,?,?)",
                           (loop_id,step,micro))
            if host_quote is not None:
                quote_id, revision, quote_micro, objective_sha = host_quote
                if quote_micro != micro or objective_sha != digest:
                    raise GoalLoopConflict("host quote does not match the reserved step")
                existing = db.execute("SELECT * FROM goal_loop_host_quotes WHERE loop_id=? AND step=?", (loop_id, step)).fetchone()
                if existing and (existing["quote_id"], existing["price_revision"], existing["micro_usd"], existing["objective_sha256"]) != host_quote:
                    raise GoalLoopConflict("durable host quote/objective changed")
                if existing is None:
                    db.execute("INSERT INTO goal_loop_host_quotes(loop_id,step,quote_id,price_revision,micro_usd,objective_sha256) VALUES(?,?,?,?,?,?)",
                        (loop_id, step, quote_id, revision, micro, digest))
        # Cross-database crash gap is closed by GovernanceService.external_key
        # idempotency. Pending step is resumed only with identical objective.
        item = self.control.create_work_item(
            row["run_id"],owner,objective=objective,goal_id=row["goal_id"],
            external_key=key,assignee_agent_id=row["principal_id"],
            metadata={"goal_loop_id":loop_id,"goal_loop_step":step,
                      "automatic_execution":False,
                      "reserved_cost_usd":micro / 1_000_000})
        if (item["run_id"],item["goal_id"],item["objective"]) != (
                row["run_id"],row["goal_id"],objective):
            raise GoalLoopConflict("Governance external key is bound to a different intent")
        with projection_db(None,store=self.store) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE goal_loop_steps SET work_item_id=? "
                       "WHERE loop_id=? AND step=? AND objective_digest=? "
                       "AND (work_item_id IS NULL OR work_item_id=?)",
                       (item["work_item_id"],loop_id,step,digest,item["work_item_id"]))
        return {"step":step,"work_item_id":item["work_item_id"],"run_id":row["run_id"],
                "goal_id":row["goal_id"],"automatic_execution":False}

    def stop(self, owner: str, loop_id: str, *, operator_approved: bool = False):
        if operator_approved is not True:
            raise PermissionError("human approval required")
        self._scope(owner,loop_id)
        with projection_db(None,store=self.store) as db:
            db.execute("UPDATE goal_loop_pacing SET state='STOPPED' "
                       "WHERE owner=? AND loop_id=?", (owner,loop_id))
        return self.status(owner,loop_id)

class HostPricedGoalLoop(BoundedGoalLoop):
    """Host-only pricing facade. The model cannot set a monetary estimate.

    The injected synchronous pricer is an authenticated host price catalog and
    must return exact integer micro-USD plus catalog quote ID and revision.
    Reserving budget still uses BoundedGoalLoop's central SQLite transactions;
    an optional price quote never authorizes execution.
    """

    def __init__(self, control: Any, *, price_quote, clock=time.time):
        if not callable(price_quote):
            raise TypeError("trusted host pricing callback required")
        super().__init__(control, clock=clock)
        self.price_quote=price_quote
        with projection_db(None,store=self.store) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS goal_loop_host_quotes(
                loop_id TEXT NOT NULL, step INTEGER NOT NULL,
                quote_id TEXT NOT NULL, price_revision TEXT NOT NULL,
                micro_usd INTEGER NOT NULL CHECK(micro_usd >= 0),
                PRIMARY KEY(loop_id,step))""")
            from sentra_interop.workflow_storage import ensure_column
            ensure_column(db,"goal_loop_host_quotes","objective_sha256","TEXT")

    def advance(self, owner: str, loop_id: str, *, objective: str,
                operator_approved: bool = False,
                estimated_cost_usd: float | None = None):
        if estimated_cost_usd is not None:
            raise PermissionError("agent supplied cost cannot replace host price quote")
        if operator_approved is not True:
            raise PermissionError("human approval required for host-priced step")
        row=self._scope(owner,loop_id)
        quote=self.price_quote(owner=owner,run_id=row["run_id"],
            goal_id=row["goal_id"],principal_id=row["principal_id"],
            objective=objective)
        if not isinstance(quote,dict):
            raise ValueError("trusted host quote record required")
        micro=quote.get("micro_usd")
        quote_id=quote.get("quote_id")
        revision=quote.get("price_revision")
        if (type(micro) is not int or not 0<=micro<=1_000_000_000 or
                (row["max_cost_usd"]>0 and micro==0) or
                type(quote_id) is not str or not 8<=len(quote_id)<=128 or
                type(revision) is not str or not 1<=len(revision)<=64):
            raise ValueError("invalid bounded host price quote")
        # Quote, step and cost reserve commit together before the WorkItem
        # admission crash gap. A rejected budget cannot pin a nonexistent step.
        objective_sha=hashlib.sha256(objective.encode()).hexdigest()
        result=self._advance(owner,loop_id,objective=objective,
            operator_approved=True,estimated_cost_usd=micro/1_000_000,
            host_quote=(quote_id,revision,micro,objective_sha))
        return {**result,"host_priced":True,"quote_id":quote_id,
                "price_revision":revision,"reserved_cost_usd":micro/1_000_000}
