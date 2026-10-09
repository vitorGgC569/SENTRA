"""Revisions of proposed plans. Undo edits never cancel or replay operations."""
import json
import re
import time

from sentra_core.conversations import _encode, _decode

_ID=re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class PlanHistory:
    def __init__(self, control, *, owner):
        self.control,self.owner=control,owner
        db=control.store.connect("plan_history")
        try:
            with db:
                if db.execute("PRAGMA user_version").fetchone()[0]>1:raise RuntimeError("newer plan history")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS plan_revisions(
                      owner TEXT NOT NULL,work_item TEXT NOT NULL,revision INTEGER NOT NULL,
                      parent INTEGER,content TEXT NOT NULL,created REAL NOT NULL,
                      PRIMARY KEY(owner,work_item,revision));
                    CREATE TABLE IF NOT EXISTS plan_cursors(
                      owner TEXT NOT NULL,work_item TEXT NOT NULL,revision INTEGER NOT NULL,
                      PRIMARY KEY(owner,work_item));
                    PRAGMA user_version=1;
                """)
        finally:db.close()

    def _validate(self, work_item_id, steps):
        item=self.control.work_item_info(work_item_id,self.owner)
        if not isinstance(steps,list) or len(steps)>128:
            raise ValueError("plan must contain at most 128 steps")
        steps=json.loads(json.dumps(steps,allow_nan=False))
        ids=set()
        for step in steps:
            if (not isinstance(step,dict) or set(step)-{"id","title","capability_id","depends_on","operation_id"}
                    or not isinstance(step.get("id"),str) or not _ID.fullmatch(step["id"]) or step["id"] in ids
                    or not isinstance(step.get("title"),str) or not 1<=len(step["title"])<=500
                    or step.get("capability_id") not in item["required_capabilities"]):
                raise ValueError("invalid scoped plan step")
            ids.add(step["id"])
        graph={step["id"]:step.get("depends_on",[]) for step in steps}
        for step in steps:
            edges=graph[step["id"]]
            if not isinstance(edges,list) or any(not isinstance(edge,str) or edge not in ids for edge in edges):
                raise ValueError("unknown plan dependency")
            if step.get("operation_id"):
                row=self.control.durable.operation_status(step["operation_id"],self.owner)
                progress=row.get("progress") or {}
                if (row["run_id"]!=item["run_id"] or progress.get("work_item_id")!=work_item_id
                        or progress.get("capability_id")!=step["capability_id"]):
                    raise PermissionError("plan operation outside its task/capability")
        visiting,visited=set(),set()
        def visit(key):
            if key in visiting:raise ValueError("cyclic plan")
            if key in visited:return
            visiting.add(key)
            for child in graph[key]:visit(child)
            visiting.remove(key);visited.add(key)
        for key in graph:visit(key)
        return steps

    def _locked(self, db, work_item_id):
        locked={}
        for row in db.execute("SELECT content FROM plan_revisions WHERE owner=? AND work_item=? ORDER BY revision",
                              (self.owner,work_item_id)):
            for step in _decode(row["content"]):
                if step.get("operation_id"):
                    operation=self.control.durable.operation_status(step["operation_id"],self.owner)
                    if (operation.get("progress") or {}).get("effect_started") is True:
                        locked[step["id"]]=step
        return locked

    @staticmethod
    def _merge_locked(steps, locked):
        by_id={step["id"]:step for step in steps}
        for ident,step in locked.items():
            by_id[ident]=step  # Completed/uncertain effects are immutable provenance.
        return list(by_id.values())

    def revise(self, work_item_id, steps, *, expected_revision):
        steps=self._validate(work_item_id,steps)
        if type(expected_revision) is not int or expected_revision<0:raise ValueError("invalid expected revision")
        db=self.control.store.connect("plan_history")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                cursor=db.execute("SELECT revision FROM plan_cursors WHERE owner=? AND work_item=?",
                                  (self.owner,work_item_id)).fetchone()
                current=cursor["revision"] if cursor else 0
                if current!=expected_revision:raise ValueError("plan revision changed; reload required")
                locked=self._locked(db,work_item_id)
                for step in steps:
                    if step["id"] in locked and step!=locked[step["id"]]:
                        raise ValueError("executed plan step is immutable")
                steps=self._validate(work_item_id,self._merge_locked(steps,locked))
                revision=db.execute("SELECT COALESCE(MAX(revision),0)+1 FROM plan_revisions WHERE owner=? AND work_item=?",
                                    (self.owner,work_item_id)).fetchone()[0]
                db.execute("INSERT INTO plan_revisions VALUES(?,?,?,?,?,?)",
                    (self.owner,work_item_id,revision,current or None,_encode(steps),time.time()))
                db.execute("INSERT INTO plan_cursors VALUES(?,?,?) ON CONFLICT(owner,work_item) DO UPDATE SET revision=excluded.revision",
                           (self.owner,work_item_id,revision))
        finally:db.close()
        return self.current(work_item_id)

    def current(self, work_item_id):
        self.control.work_item_info(work_item_id,self.owner)
        db=self.control.store.connect("plan_history")
        try:
            row=db.execute("SELECT r.* FROM plan_revisions r JOIN plan_cursors c "
                "ON r.owner=c.owner AND r.work_item=c.work_item AND r.revision=c.revision "
                "WHERE r.owner=? AND r.work_item=?",(self.owner,work_item_id)).fetchone()
            locked=self._locked(db,work_item_id)
            steps=self._merge_locked(_decode(row["content"]) if row else [],locked)
            return {"revision":row["revision"] if row else 0,"steps":steps,
                    "executed_step_ids":sorted(locked),"proposal_only":True}
        finally:db.close()

    def navigate(self, work_item_id, *, direction, expected_revision):
        self.control.work_item_info(work_item_id,self.owner)
        if direction not in {"undo","redo"} or type(expected_revision) is not int or expected_revision<1:
            raise ValueError("plan undo/redo requires current revision")
        db=self.control.store.connect("plan_history")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                cursor=db.execute("SELECT revision FROM plan_cursors WHERE owner=? AND work_item=?",
                                  (self.owner,work_item_id)).fetchone()
                if cursor is None or cursor["revision"]!=expected_revision:raise ValueError("plan revision changed")
                if direction=="undo":
                    row=db.execute("SELECT parent revision FROM plan_revisions WHERE owner=? AND work_item=? AND revision=?",
                        (self.owner,work_item_id,expected_revision)).fetchone()
                else:
                    row=db.execute("SELECT revision FROM plan_revisions WHERE owner=? AND work_item=? AND parent=? ORDER BY revision DESC LIMIT 1",
                        (self.owner,work_item_id,expected_revision)).fetchone()
                if row and row["revision"] is not None:
                    db.execute("UPDATE plan_cursors SET revision=? WHERE owner=? AND work_item=?",
                               (row["revision"],self.owner,work_item_id))
        finally:db.close()
        return self.current(work_item_id)
