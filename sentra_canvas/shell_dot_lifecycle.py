"""Owner-scoped Dot favorites/order and conservative removal preflight."""
from contextlib import closing
import hashlib
import json
import time

from sentra_core.conversations import _decode, _encode
from .shell_dot_canvas import canvas_root, dot_graph
from .shell_dot_retirement import DotRetirement, remote_archive_projection
from .shell_dot_authority_retirement import DotAuthorityRetirement
from .shell_dot_vm_retirement import DotVmRetirementInspector
from .store import Denied

DOT_LIFECYCLE_ACTIONS = frozenset({
    "dot_preferences_get", "dot_preference_set", "dot_order_move", "dot_order_place", "dot_remove_preflight",
    "dot_archive_local", "dot_restore_local", "dot_pause_family", "dot_resume_family",
    "dot_reconcile_family", "dot_incident_reconcile", "dot_delete_request",
    "dot_retire_authority_close",
    "dot_retire_authority_status", "dot_retire_authority_reconcile", "dot_vm_retire_preflight",
})


class DotLifecycleServices:
    def __init__(self, canvas):
        self.canvas = canvas
        self.control = canvas._shell_service()
        self.owner = canvas._runtime().owner
        self.retirement = DotRetirement(canvas, self.control, self.owner)
        self.authority_retirement = DotAuthorityRetirement(self.retirement)
        self.vm_retirement = DotVmRetirementInspector(self.retirement)
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_preferences(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, space_id TEXT NOT NULL,
                dot_id TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(owner,project_id,space_id,dot_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_preference_requests(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, request_key TEXT NOT NULL,
                intent_hash TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(owner,project_id,request_key))""")

    def _scope(self, project_id, params):
        space_id = params.get("space_id")
        if not isinstance(space_id, str) or not space_id:
            raise ValueError("canonical Space is required")
        with closing(self.control.store.connect("shell")) as db:
            self.control.shell._entity(db, self.owner, project_id, "space", space_id)
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND space_id=? AND kind='dot'",
                (self.owner, project_id, space_id)).fetchall()
            all_dots = [_decode(row["body"]) for row in rows]
        roots = [dot for dot in all_dots if canvas_root(dot) == dot["dot_id"]]
        roots.sort(key=lambda dot: (dot.get("created_at", 0), dot["dot_id"]))
        return space_id, roots

    def _target(self, project_id, space_id, dot_id):
        if not isinstance(dot_id, str) or not dot_id:
            raise ValueError("canonical Dot is required")
        with closing(self.control.store.connect("shell")) as db:
            dot = self.control.shell._entity(db, self.owner, project_id, "dot", dot_id, space_id=space_id)
        if canvas_root(dot) != dot_id:
            raise Denied("Dot lifecycle actions are scoped to canvas root Dots")
        return dot

    def _preferences(self, project_id, space_id, roots, db=None):
        if db is None:
            with closing(self.control.store.connect("shell")) as connection:
                return self._preferences(project_id, space_id, roots, connection)
        else:
            rows = db.execute("SELECT dot_id,favorite,position FROM shell_dot_preferences WHERE owner=? AND project_id=? AND space_id=?",
                (self.owner, project_id, space_id)).fetchall()
        saved = {row["dot_id"]: row for row in rows}
        archived = self.retirement.archived(project_id, space_id)
        remote = remote_archive_projection()
        items = []
        for index, dot in enumerate(roots):
            row = saved.get(dot["dot_id"])
            items.append({"dot_id": dot["dot_id"], "favorite": bool(row["favorite"]) if row else False,
                "position": int(row["position"]) if row else index,
                "archived_local": archived.get(dot["dot_id"], False), **remote})
        return sorted(items, key=lambda item: (item["archived_local"], not item["favorite"], item["position"], item["dot_id"]))

    def _persist(self, project_id, space_id, items, db):
        now = time.time()
        for item in items:
            db.execute("INSERT INTO shell_dot_preferences(owner,project_id,space_id,dot_id,favorite,position,updated_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner,project_id,space_id,dot_id) DO UPDATE SET "
                "favorite=excluded.favorite,position=excluded.position,updated_at=excluded.updated_at",
                (self.owner, project_id, space_id, item["dot_id"], int(item["favorite"]), item["position"], now))

    def _incident_plan(self, project_id, space_id, dot, incident):
        """Read the owner run, conversations, Grants and relay jobs. Does not resend."""
        from sentra_runtime.uncertain_recovery import INCIDENTS, UncertainRecovery
        if not isinstance(incident, str) or incident not in INCIDENTS:
            raise ValueError("incident must be crash, canvas_closed, relay_down or reboot")
        run_id = dot.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise Denied("Dot has no durable run to observe")
        plan = UncertainRecovery(incident).reconcile_durable(
            self.control, self.owner, run_id,
            conversations=self._owner_conversations(project_id, space_id, dot),
            grants=self._owner_grants(project_id, space_id, dot),
            relay_jobs=self._owner_relay_jobs())
        if plan.get("effects_executed") != 0 or plan.get("may_resend") is not False:
            raise RuntimeError("incident plan must not execute or resend")
        return plan

    def _owner_conversations(self, project_id, space_id, dot):
        family = {member["dot_id"] for member in self.retirement._family(project_id, space_id, dot)}
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? "
                "AND space_id=? AND kind='conversation'", (self.owner, project_id, space_id)).fetchall()
            queue = db.execute("SELECT conversation_id,state,created_at FROM canvas_shell_queue "
                "WHERE owner=? AND project_id=? ORDER BY created_at",
                (self.owner, project_id)).fetchall()
        state_by_id = {}
        for row in queue:
            state_by_id[row["conversation_id"]] = row["state"]
        found = []
        for item in (_decode(row["body"]) for row in rows):
            if item.get("dot_id") not in family:
                continue
            ident = item.get("conversation_id")
            if not isinstance(ident, str) or not ident:
                continue
            found.append({"id": ident, "state": state_by_id.get(ident) or "confirmed"})
        found.sort(key=lambda item: item["id"])
        return found

    def _owner_relay_jobs(self):
        """Read relay jobs already stored for this owner. Does not create the table."""
        with closing(self.control.store.connect("execution_workspace")) as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
            if not exists:
                return []
            rows = db.execute(
                "SELECT id, state, updated FROM jobs WHERE owner=? ORDER BY id",
                (self.owner,)).fetchall()
        found = []
        for row in rows:
            ident, state = row["id"], row["state"]
            if not isinstance(ident, str) or not ident or not isinstance(state, str) or not state:
                continue
            found.append({"id": ident, "state": state})
        return found

    def _owner_grants(self, project_id, space_id, dot):
        agents = {member["agent_id"] for member in self.retirement._family(project_id, space_id, dot)}
        grants = self.control.authorization.list_grants(self.owner, include_revoked=True)["items"]
        uncertain = set()
        with closing(self.control.store.connect("authorization")) as db:
            rows = db.execute("SELECT grant_id,outcome FROM authorization_events WHERE owner=? ORDER BY seq",
                (self.owner,)).fetchall()
        for row in rows:
            if row["grant_id"] and str(row["outcome"]).upper() == "UNCERTAIN":
                uncertain.add(row["grant_id"])
        found = []
        for grant in grants:
            if grant.get("principal_type") == "agent" and grant.get("principal_id") not in agents:
                continue
            ident = grant.get("grant_id")
            if not isinstance(ident, str) or not ident:
                continue
            if ident in uncertain:
                state = "UNCERTAIN"
            elif grant.get("revoked"):
                state = "revoked"
            else:
                state = "active"
            found.append({"id": ident, "state": state})
        found.sort(key=lambda item: item["id"])
        return found

    def dispatch(self, project_id, action, params, request_key=None):
        allowed = {
            "dot_preferences_get": {"space_id"},
            "dot_preference_set": {"space_id", "dot_id", "favorite"},
            "dot_order_move": {"space_id", "dot_id", "direction"},
            "dot_order_place": {"space_id", "dot_id", "target_dot_id", "edge"},
            "dot_remove_preflight": {"space_id", "dot_id"},
            "dot_archive_local": {"space_id", "dot_id", "confirm_name", "snapshot"},
            "dot_restore_local": {"space_id", "dot_id"},
            "dot_pause_family": {"space_id", "dot_id", "confirm_name"},
            "dot_resume_family": {"space_id", "dot_id", "confirm_name"},
            "dot_reconcile_family": {"space_id", "dot_id"},
            "dot_incident_reconcile": {"space_id", "dot_id", "incident"},
            "dot_delete_request": {"space_id", "dot_id", "confirm_name", "confirm_phrase"},
            "dot_retire_authority_close": {"space_id", "dot_id", "confirm_name", "confirm_phrase", "snapshot"},
            "dot_retire_authority_status": {"space_id", "dot_id", "retirement_key"},
            "dot_retire_authority_reconcile": {"space_id", "dot_id", "retirement_key"},
            "dot_vm_retire_preflight": {"space_id", "dot_id"},
        }[action]
        if set(params) - allowed or "space_id" not in params:
            raise ValueError("Dot lifecycle fields are invalid")
        space_id, roots = self._scope(project_id, params)
        if action == "dot_preferences_get":
            return {"project_id": project_id, "space_id": space_id, "items": self._preferences(project_id, space_id, roots)}
        dot = self._target(project_id, space_id, params.get("dot_id"))
        if action == "dot_remove_preflight":
            return self.retirement.preflight(project_id, space_id, dot)
        if action == "dot_vm_retire_preflight":
            return self.vm_retirement.preview(project_id, dot)
        if action in {"dot_archive_local", "dot_restore_local"}:
            return self.retirement.mutate(project_id, space_id, dot, action, params, request_key)
        if action == "dot_pause_family":
            return self.retirement.pause_family(project_id, space_id, dot, params, request_key)
        if action == "dot_resume_family":
            return self.retirement.resume_family(project_id, space_id, dot, params, request_key)
        if action == "dot_reconcile_family":
            return self.retirement.reconcile_family(project_id, space_id, dot, request_key)
        if action == "dot_incident_reconcile":
            return self._incident_plan(project_id, space_id, dot, params.get("incident"))
        if action == "dot_delete_request":
            return self.retirement.request_deletion(project_id, space_id, dot, params, request_key)
        if action == "dot_retire_authority_close":
            return self.authority_retirement.close(project_id, space_id, dot, params, request_key)
        if action == "dot_retire_authority_status":
            return self.authority_retirement.status(project_id, space_id, dot, params.get("retirement_key"))
        if action == "dot_retire_authority_reconcile":
            return self.authority_retirement.reconcile(project_id, space_id, dot, params["retirement_key"])
        with closing(self.control.store.connect("shell")) as db, db:
            # Read and change order under the same lock; concurrent moves cannot overwrite
            # an unrelated favorite change with a stale projection.
            db.execute("BEGIN IMMEDIATE")
            intent = hashlib.sha256(json.dumps([action, params], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if request_key:
                previous = db.execute("SELECT intent_hash,result FROM shell_dot_preference_requests WHERE owner=? AND project_id=? AND request_key=?",
                    (self.owner, project_id, request_key)).fetchone()
                if previous:
                    if previous["intent_hash"] != intent:
                        raise Denied("Dot preference request key belongs to another intention")
                    return _decode(previous["result"])
            result = self._change_preferences(db, project_id, space_id, roots, dot, action, params)
            if request_key:
                db.execute("INSERT INTO shell_dot_preference_requests VALUES(?,?,?,?,?)",
                    (self.owner, project_id, request_key, intent, _encode(result)))
            return result

    def _change_preferences(self, db, project_id, space_id, roots, dot, action, params):
        items = self._preferences(project_id, space_id, roots, db)
        if action == "dot_preference_set":
            if type(params.get("favorite")) is not bool:
                raise ValueError("favorite must be boolean")
            for item in items:
                if item["dot_id"] == dot["dot_id"]:
                    item["favorite"] = params["favorite"]
            self._persist(project_id, space_id, items, db)
            return {"dot_id": dot["dot_id"], "favorite": params["favorite"], "items": self._preferences(project_id, space_id, roots, db)}
        if action == "dot_order_move":
            direction = params.get("direction")
            if direction not in {"up", "down"}:
                raise ValueError("direction must be up or down")
            ordered = sorted(items, key=lambda item: (item["archived_local"], not item["favorite"], item["position"], item["dot_id"]))
            index = next(i for i, item in enumerate(ordered) if item["dot_id"] == dot["dot_id"])
            neighbor_index = index + (-1 if direction == "up" else 1)
            moved = neighbor_index in range(len(ordered)) and ordered[neighbor_index]["favorite"] == ordered[index]["favorite"] and ordered[neighbor_index]["archived_local"] == ordered[index]["archived_local"]
            if moved:
                ordered[index], ordered[neighbor_index] = ordered[neighbor_index], ordered[index]
                for position, item in enumerate(ordered):
                    item["position"] = position
                self._persist(project_id, space_id, ordered, db)
            return {"dot_id": dot["dot_id"], "moved": moved, "items": ordered}
        if action == "dot_order_place":
            target_id, edge = params.get("target_dot_id"), params.get("edge")
            if edge not in {"before", "after"}:
                raise ValueError("edge must be before or after")
            target = next((item for item in items if item["dot_id"] == target_id), None)
            if target is None:
                raise Denied("reorder target must be a root Dot in the same Space")
            ordered = sorted(items, key=lambda item: (item["archived_local"], not item["favorite"], item["position"], item["dot_id"]))
            if target_id == dot["dot_id"]:
                return {"dot_id": dot["dot_id"], "moved": False, "items": ordered}
            moving = next(item for item in ordered if item["dot_id"] == dot["dot_id"])
            if moving["archived_local"] != target["archived_local"]:
                raise Denied("archived and active Dots cannot cross lifecycle groups")
            ordered.remove(moving)
            moving["favorite"] = target["favorite"]
            index = next(i for i, item in enumerate(ordered) if item["dot_id"] == target_id)
            ordered.insert(index + int(edge == "after"), moving)
            for position, item in enumerate(ordered):
                item["position"] = position
            self._persist(project_id, space_id, ordered, db)
            return {"dot_id": dot["dot_id"], "moved": True, "items": ordered}
        raise ValueError("unknown Dot preference action")

    def _remove_preflight(self, project_id, space_id, dot):
        return self.retirement.preflight(project_id, space_id, dot)


__all__ = ["DOT_LIFECYCLE_ACTIONS", "DotLifecycleServices"]
