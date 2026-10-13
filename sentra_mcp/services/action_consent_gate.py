"""Two human consent decisions plus central WorkItem grant for local action APIs.

Host-only integration. Browser observation cannot approve an action or issue a
grant. An approved single-use fingerprint is consumed *inside* the durable
operation's effect boundary. An uncertain result never silently replays.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sentra_interop.central import CentralInteropAdapter
from sentra_runtime.contracts import Capability, Machine, OperationRequest

from .chat_access import ChatAccessService, _ID, _PRINCIPAL, _validate
from .control_store import create_control_plane_store

_ACTION = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    if len(raw) > 16_384:
        raise ValueError("action body exceeds 16 KiB")
    return hashlib.sha256(raw).hexdigest()


class ActionConsentService:
    """Operator-authorized endpoints must call allow_api / approve_action.

    A trusted host owner_authenticator must verify every independent operator
    click before an assertion is claimed. Booleans alone never convey identity.
    Never publish these mutations as model-facing tools/browser callbacks.
    """

    def __init__(self, state_root, *, store=None, chat_access=None,
                 owner_authenticator=None):
        # The host injects a trusted authenticator for a fresh, operator-click
        # assertion; no authenticator means all consent writes are DISABLED.
        self.owner_authenticator = owner_authenticator
        self.store = store if store is not None else create_control_plane_store(state_root)
        self.chat_access = chat_access or ChatAccessService(state_root, store=self.store)
        with self.store.connect("chat_access") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS action_api_consent (
                    owner TEXT NOT NULL, agent_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL, enabled INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    PRIMARY KEY(owner,agent_id,work_item_id)
                );
                CREATE TABLE IF NOT EXISTS action_api_session_bindings (
                    owner TEXT NOT NULL, agent_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    session_sha256 TEXT NOT NULL,
                    PRIMARY KEY(owner,agent_id,work_item_id)
                );
                CREATE TABLE IF NOT EXISTS action_api_owner_assertions (
                    assertion_sha256 TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    purpose TEXT NOT NULL, consumed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_api_intents (
                    action_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    agent_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    capability TEXT NOT NULL, body_sha256 TEXT NOT NULL,
                    api_revision INTEGER NOT NULL, expires REAL NOT NULL,
                    state TEXT NOT NULL, consumed_operation_id TEXT
                );
            """)

    def _db(self):
        return self.store.connect("chat_access")

    def pending_intents(self, owner, agent_id=None, work_item_id=None, *, limit=50):
        """Read-only projection of undecided action intents for approval cards.

        Powers conversation/chat approval UX (Prisma shell): lists PROPOSED
        intents with capability, body digest and expiry. Returns no
        authorization and never extends an expiry.
        """
        _validate("owner", owner, _PRINCIPAL)
        if agent_id is not None:
            _validate("agent", agent_id, _PRINCIPAL)
        if work_item_id is not None:
            _validate("work item", work_item_id, _ID)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("bounded pending intent listing required")
        clauses, args = ["owner=?"], [owner]
        if agent_id is not None:
            clauses.append("agent_id=?")
            args.append(agent_id)
        if work_item_id is not None:
            clauses.append("work_item_id=?")
            args.append(work_item_id)
        now = time.time()
        with self._db() as db:
            rows = db.execute(
                "SELECT action_id,agent_id,work_item_id,request_id,message_id,"
                "capability,body_sha256,api_revision,expires,state "
                "FROM action_api_intents WHERE " + " AND ".join(clauses) +
                " ORDER BY expires ASC LIMIT ?", (*args, limit)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if item["state"] == "PROPOSED" and item["expires"] <= now:
                item = {**item, "state": "EXPIRED"}
            items.append(item)
        return {"owner": owner, "items": items, "grants_created": False,
                "approval_creates_effect": False}

    def intent_status(self, action_id, owner):
        """Read-only lifecycle state of one action intent (receipt view)."""
        _validate("owner", owner, _PRINCIPAL)
        if not isinstance(action_id, str) or not action_id.startswith("act-"):
            raise ValueError("invalid action identity")
        with self._db() as db:
            row = db.execute("SELECT action_id,agent_id,work_item_id,request_id,"
                             "message_id,capability,body_sha256,expires,state,"
                             "consumed_operation_id FROM action_api_intents "
                             "WHERE action_id=? AND owner=?", (action_id, owner)).fetchone()
        if row is None:
            raise FileNotFoundError("action intent not found for this owner")
        item = dict(row)
        if item["state"] == "PROPOSED" and item["expires"] <= time.time():
            item["state"] = "EXPIRED"
        return {**item, "effect_executed": item["state"] == "CONSUMED"}

    def _owner_assertion_digest(self, *, owner, purpose, owner_proof):
        """Authenticate an independent human click, NOT a model boolean.

        Host verifier must validate a fresh local session, origin/CSRF and a
        click-scoped owner assertion; it returns the exact principal identity.
        Unconfigured services always deny consent mutations.
        """
        if (not callable(self.owner_authenticator) or
                not isinstance(owner_proof, str) or
                not 24 <= len(owner_proof) <= 4096):
            raise PermissionError("owner-auth human assertion unavailable")
        try:
            verified = self.owner_authenticator(owner, purpose, owner_proof)
        except Exception as exc:
            raise PermissionError("owner-auth verification failed") from exc
        if verified != owner or type(verified) is not str:
            raise PermissionError("owner-auth principal mismatch")
        return hashlib.sha256(owner_proof.encode("utf-8")).hexdigest()

    def _consume_assertion(self, db, *, digest, owner, purpose):
        # Unique PK creates a crash-durable, cross-worker single-use claim.
        try:
            db.execute("INSERT INTO action_api_owner_assertions VALUES(?,?,?,?)",
                       (digest, owner, purpose, time.time()))
        except Exception as exc:
            raise PermissionError("owner-auth assertion already consumed") from exc
        if isinstance(self.owner_authenticator, HostOwnerClickAuthenticator):
            return self.owner_authenticator.consume(db,digest=digest,owner=owner,
                                                     purpose=purpose)
        return None

    def allow_api(self, *, owner, agent_id, work_item_id, enabled,
                  expected_revision, human_confirmed=False, owner_proof=None):
        """Consent #1, *authenticated local-operator endpoint only*."""
        _validate("owner", owner, _PRINCIPAL)
        _validate("agent", agent_id, _PRINCIPAL)
        _validate("work item", work_item_id, _ID)
        if (human_confirmed is not True or type(enabled) is not bool or
                type(expected_revision) is not int or expected_revision < 0):
            raise PermissionError("first human API consent and revision required")
        proof_digest = self._owner_assertion_digest(
            owner=owner, purpose="api-consent", owner_proof=owner_proof)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM action_api_consent WHERE owner=? AND agent_id=? AND work_item_id=?",
                (owner, agent_id, work_item_id)).fetchone()
            current = row["revision"] if row else 0
            if current != expected_revision:
                raise ValueError("API consent revision changed")
            session_sha=self._consume_assertion(
                db,digest=proof_digest,owner=owner,purpose="api-consent")
            if session_sha is not None:
                db.execute("INSERT INTO action_api_session_bindings VALUES(?,?,?,?,?) "
                           "ON CONFLICT(owner,agent_id,work_item_id) DO UPDATE SET "
                           "revision=excluded.revision,session_sha256=excluded.session_sha256",
                           (owner,agent_id,work_item_id,current+1,session_sha))
            db.execute("INSERT INTO action_api_consent VALUES(?,?,?,?,?) "
                       "ON CONFLICT(owner,agent_id,work_item_id) DO UPDATE SET "
                       "enabled=excluded.enabled,revision=excluded.revision",
                       (owner, agent_id, work_item_id, int(enabled), current + 1))
            return {"enabled":enabled, "revision":current + 1, "grants_created":False}

    def _api_revision(self, db, *, owner, agent_id, work_item_id):
        row = db.execute("SELECT revision,enabled FROM action_api_consent "
                         "WHERE owner=? AND agent_id=? AND work_item_id=?",
                         (owner, agent_id, work_item_id)).fetchone()
        if row is None or not row["enabled"]:
            raise PermissionError("first API consent absent or revoked")
        if isinstance(self.owner_authenticator,HostOwnerClickAuthenticator):
            bound=db.execute("SELECT revision,session_sha256 FROM "
                             "action_api_session_bindings WHERE owner=? "
                             "AND agent_id=? AND work_item_id=?",
                             (owner,agent_id,work_item_id)).fetchone()
            if bound is None or bound["revision"]!=row["revision"]:
                raise PermissionError("first API consent missing authenticated owner session")
            self.owner_authenticator.check_bound_session(
                db,owner=owner,session_sha256=bound["session_sha256"])
        return row["revision"]

    def propose_action(self, *, owner, agent_id, work_item_id, request_id,
                       message_id, action, body, ttl_s=120):
        """Propose exact-action digest; no effect and no grant."""
        _validate("owner", owner, _PRINCIPAL)
        _validate("agent", agent_id, _PRINCIPAL)
        for label, value in (("work item",work_item_id),("request",request_id),
                             ("message",message_id)):
            _validate(label, value, _ID)
        if not isinstance(action,str) or not _ACTION.fullmatch(action):
            raise ValueError("invalid named API action")
        if type(ttl_s) not in (int,float) or not 1 <= ttl_s <= 600:
            raise ValueError("invalid action approval window")
        body_sha = _digest(body)
        self.chat_access.require_exact_message(owner, request_id, message_id)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            revision=self._api_revision(db,owner=owner,agent_id=agent_id,
                                        work_item_id=work_item_id)
            action_id="act-"+secrets.token_hex(20)
            db.execute("INSERT INTO action_api_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (action_id,owner,agent_id,work_item_id,request_id,message_id,
                        "api:action:"+action,body_sha,revision,time.time()+ttl_s,
                        "PROPOSED",None))
        return {"action_id":action_id,"body_sha256":body_sha,
                "capability":"api:action:"+action, "state":"PROPOSED",
                "grants_created":False}

    def approve_action(self, *, action_id, body_sha256,
                       human_confirmed=False, owner_proof=None):
        """Consent #2, *authenticated local-operator endpoint only*."""
        if human_confirmed is not True or not isinstance(body_sha256,str) or not _SHA.fullmatch(body_sha256):
            raise PermissionError("second human confirmation of exact action required")
        # Resolve immutable intent owner before BEGIN IMMEDIATE so a host
        # verifier may inspect its own session store without a nested DB lock.
        with self._db() as read_db:
            identity=read_db.execute("SELECT owner FROM action_api_intents WHERE action_id=?",
                                     (action_id,)).fetchone()
        if identity is None:
            raise PermissionError("action proposal unavailable")
        proof_digest=self._owner_assertion_digest(
            owner=identity["owner"],purpose="action:"+action_id,
            owner_proof=owner_proof)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM action_api_intents WHERE action_id=?",(action_id,)).fetchone()
            if row is None or row["state"]!="PROPOSED" or row["expires"]<=time.time():
                raise PermissionError("action proposal absent, expired or already decided")
            self._api_revision(db,owner=row["owner"],agent_id=row["agent_id"],
                               work_item_id=row["work_item_id"])
            if not secrets.compare_digest(row["body_sha256"],body_sha256):
                raise PermissionError("human action review digest mismatch")
            click_session_sha=self._consume_assertion(
                db,digest=proof_digest,owner=row["owner"],purpose="action:"+action_id)
            if click_session_sha is not None:
                binding=db.execute("SELECT session_sha256 FROM "
                    "action_api_session_bindings WHERE owner=? AND agent_id=? "
                    "AND work_item_id=? AND revision=?",
                    (row["owner"],row["agent_id"],row["work_item_id"],
                     row["api_revision"])).fetchone()
                if binding is None or binding["session_sha256"]!=click_session_sha:
                    raise PermissionError("two consents require same authenticated host session")
            db.execute("UPDATE action_api_intents SET state='APPROVED' WHERE action_id=?",(action_id,))
            return {"action_id":action_id,"state":"APPROVED","grants_created":False}

    def _claim(self, *, action_id, owner, agent_id, work_item_id, request_id,
               message_id, capability, body_sha256, operation_id):
        """Atomic one-shot claim; before host effect, never auto-refunded."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM action_api_intents WHERE action_id=?",(action_id,)).fetchone()
            if (row is None or row["state"]!="APPROVED" or row["expires"]<=time.time()
                    or (row["owner"],row["agent_id"],row["work_item_id"],
                        row["request_id"],row["message_id"],row["capability"],row["body_sha256"])
                    != (owner,agent_id,work_item_id,request_id,message_id,capability,body_sha256)
                    or row["api_revision"] != self._api_revision(
                        db,owner=owner,agent_id=agent_id,work_item_id=work_item_id)):
                raise PermissionError("action approval revoked, used or not bound to exact request")
            # No effect can start until both browser and operator state match.
            self.chat_access.require_exact_message(owner,request_id,message_id,_db=db)
            db.execute("UPDATE action_api_intents SET state='CONSUMED',consumed_operation_id=? "
                       "WHERE action_id=? AND state='APPROVED'",(operation_id,action_id))

    def _preflight(self, *, action_id, owner, agent_id, work_item_id,
                   request_id, message_id, capability, body_sha256, operation_id):
        """Reject missing/revoked consent before any durable Operation reservation.

        Permit exact replay of a consumed operation; the durable gate owns
        idempotency and must not execute the callback twice.
        """
        with self._db() as db:
            row=db.execute("SELECT * FROM action_api_intents WHERE action_id=?",(action_id,)).fetchone()
            if row is None or (row["state"]!="APPROVED" and not (
                row["state"]=="CONSUMED" and row["consumed_operation_id"]==operation_id)):
                raise PermissionError("action approval absent, revoked or already used")
            if (row["expires"]<=time.time() or
                    (row["owner"],row["agent_id"],row["work_item_id"],row["request_id"],
                     row["message_id"],row["capability"],row["body_sha256"]) !=
                    (owner,agent_id,work_item_id,request_id,message_id,capability,body_sha256)
                    or row["api_revision"] != self._api_revision(
                        db,owner=owner,agent_id=agent_id,work_item_id=work_item_id)):
                raise PermissionError("action approval revoked, expired or mismatched")

    async def execute(self, *, control, owner, run_id, work_item_id, agent_id,
                      request_id, message_id, action_id, action, body,
                      operation_id, idempotency_key,
                      host_effect: Callable[[], Awaitable[Any]]):
        """Trusted host adapter; the CentralInteropAdapter owns grants and lease.

        host_effect is a host-selected implementation, not a browser-submitted
        callable or arbitrary script. Caller must use this behind a host-only
        facade; any tool exposure must omit operator approval methods.
        """
        if not isinstance(action,str) or not _ACTION.fullmatch(action):
            raise ValueError("invalid API action")
        for name,value in (("operation",operation_id),("idempotency",idempotency_key)):
            _validate(name,value,_ID)
        if not callable(host_effect):
            raise ValueError("trusted host effect required")
        cap="api:action:"+action
        sha=_digest(body)
        # Validate first, BEFORE reserving the durable machine effect.
        self.chat_access.require_exact_message(owner,request_id,message_id)
        row=control.work_item_info(work_item_id,owner)
        if row["run_id"]!=run_id:
            raise PermissionError("API action WorkItem does not belong to run")
        self._preflight(action_id=action_id,owner=owner,agent_id=agent_id,
                        work_item_id=work_item_id,request_id=request_id,
                        message_id=message_id,capability=cap,body_sha256=sha,
                        operation_id=operation_id)
        machine=Machine("action-api-"+hashlib.sha256(owner.encode()).hexdigest()[:24],
                        "api",owner,(Capability(cap,"Human-reviewed local API action"),))
        adapter=CentralInteropAdapter(control=control,run_id=run_id,owner=owner,machine=machine)
        gate=adapter.protocol_gate()
        request=OperationRequest(operation_id,agent_id,machine.machine_id,
                                 cap,work_item_id,idempotency_key,{"body_sha256":sha})
        if not (await gate.decision(request)).allowed:
            raise PermissionError("named API action requires active central WorkItem grant")

        async def effect():
            # The gate has acquired the operation's physical and durable fence.
            context=gate.physical_context(request)
            context.checkpoint()
            if not (await gate.decision(request)).allowed:
                raise PermissionError("API action grant revoked before effect")
            self._claim(action_id=action_id,owner=owner,agent_id=agent_id,
                        work_item_id=work_item_id,request_id=request_id,
                        message_id=message_id,capability=cap,body_sha256=sha,
                        operation_id=operation_id)
            context.checkpoint()
            return await host_effect()
        return await gate.execute(request,effect,timeout=20)

    async def read_api(self, *, control, owner, run_id, work_item_id, agent_id,
                       request_id, message_id, resource, body, operation_id,
                       idempotency_key, host_read: Callable[[], Awaitable[Any]]):
        """Read-only host implementation; first consent + distinct read grant.

        No second per-action approval is needed for read, but read access is
        never implied by an action grant. A host-selected read runs under its
        own centrally fenced, durable Operation (including any host I/O).
        """
        if not isinstance(resource,str) or not _ACTION.fullmatch(resource):
            raise ValueError("invalid named read resource")
        for name,value in (("operation",operation_id),("idempotency",idempotency_key)):
            _validate(name,value,_ID)
        if not callable(host_read):
            raise ValueError("trusted host read required")
        sha=_digest(body)
        self.chat_access.require_exact_message(owner,request_id,message_id)
        with self._db() as db:
            self._api_revision(db,owner=owner,agent_id=agent_id,
                               work_item_id=work_item_id)
        item=control.work_item_info(work_item_id,owner)
        if item["run_id"]!=run_id:
            raise PermissionError("read API WorkItem does not belong to run")
        cap="api:read:"+resource
        machine=Machine("read-api-"+hashlib.sha256(owner.encode()).hexdigest()[:24],
                        "api",owner,(Capability(cap,"Consent-bound read-only local API"),))
        gate=CentralInteropAdapter(control=control,run_id=run_id,owner=owner,
                                   machine=machine).protocol_gate()
        request=OperationRequest(operation_id,agent_id,machine.machine_id,
                                 cap,work_item_id,idempotency_key,{"body_sha256":sha})
        if not (await gate.decision(request)).allowed:
            raise PermissionError("named read API requires distinct central WorkItem grant")

        async def effect():
            context=gate.physical_context(request)
            context.checkpoint()
            if not (await gate.decision(request)).allowed:
                raise PermissionError("read API grant revoked before effect")
            # Enforce fresh first consent and live browser ownership immediately
            # before host-read; a closed tab or pending approval must deny.
            with self._db() as db:
                self._api_revision(db,owner=owner,agent_id=agent_id,
                                   work_item_id=work_item_id)
            self.chat_access.require_exact_message(owner,request_id,message_id)
            context.checkpoint()
            return await host_read()
        return await gate.execute(request,effect,timeout=20)

@dataclass(frozen=True, slots=True)
class HostOwnerSession:
    """ONLY a trusted host request middleware may construct this identity.

    csrf_verified must mean the host checked its independent CSRF token,
    authenticated owner bearer AND exact permitted Origin. A browser, model or
    extension must never submit these fields directly to this constructor.
    """
    owner: str
    session_id: str
    origin: str
    csrf_verified: bool

    def __post_init__(self):
        _validate("session owner", self.owner, _PRINCIPAL)
        if (type(self.session_id) is not str or len(self.session_id)<24 or
                type(self.origin) is not str or not self.origin.startswith(
                    ("https://127.0.0.1:", "http://127.0.0.1:",
                     "https://localhost:", "http://localhost:")) or
                type(self.csrf_verified) is not bool):
            raise ValueError("host-only session identity required")


class HostOwnerClickAuthenticator:
    """Host-only two-click authenticator sharing ActionConsentService's DB.

    session_lookup MUST resolve a current, independently authenticated local
    request, not a session chosen by payload/model/DOM. Issuing a click requires
    a valid CSRF/Origin check, and consumption uses an atomic SQLite CAS.
    """

    def __init__(self, state_root, *, session_lookup, store=None, clock=time.time):
        if not callable(session_lookup):
            raise TypeError("trusted host session resolver required")
        self.store=store if store is not None else create_control_plane_store(state_root)
        self.session_lookup=session_lookup
        self.clock=clock
        with self.store.connect("chat_access") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS action_api_host_clicks(
                    token_sha256 TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    session_sha256 TEXT NOT NULL,
                    origin_sha256 TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    nonce_sha256 TEXT NOT NULL,
                    expires REAL NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('ISSUED','CONSUMED'))
                );
                CREATE TABLE IF NOT EXISTS action_api_revoked_sessions(
                    owner TEXT NOT NULL,
                    session_sha256 TEXT NOT NULL,
                    revoked_at REAL NOT NULL,
                    PRIMARY KEY(owner,session_sha256)
                );
            """)

    @staticmethod
    def _fingerprint(session):
        return hashlib.sha256(
            (session.owner+"\\0"+session.session_id).encode()).hexdigest()

    @staticmethod
    def _origin(session):
        return hashlib.sha256(session.origin.encode()).hexdigest()

    def _current(self, owner):
        session=self.session_lookup()
        if (not isinstance(session, HostOwnerSession) or
                session.owner!=owner or session.csrf_verified is not True):
            raise PermissionError("current host owner session/CSRF unavailable")
        return session

    def issue_click(self, *, owner, purpose, ttl_s=90):
        """Call only from a POST route after bearer/Origin/CSRF verification."""
        _validate("owner",owner,_PRINCIPAL)
        if not (type(purpose) is str and (
                purpose=="api-consent" or
                (purpose.startswith("action:act-") and len(purpose)<=80))):
            raise ValueError("invalid click purpose")
        if type(ttl_s) not in (int,float) or not 1<=ttl_s<=180:
            raise ValueError("invalid click lifetime")
        session=self._current(owner)
        nonce=secrets.token_urlsafe(24)
        proof="owner-click-"+secrets.token_urlsafe(32)+"."+nonce
        digest=hashlib.sha256(proof.encode()).hexdigest()
        with self.store.connect("chat_access") as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_active(db,owner,self._fingerprint(session))
            db.execute(
                "INSERT INTO action_api_host_clicks VALUES(?,?,?,?,?,?,?,?)",
                (digest,owner,self._fingerprint(session),
                 self._origin(session),purpose,
                 hashlib.sha256(nonce.encode()).hexdigest(),
                 self.clock()+ttl_s,"ISSUED"))
        return proof

    def _require_active(self, db, owner, session_sha):
        if db.execute(
                "SELECT 1 FROM action_api_revoked_sessions WHERE owner=? "
                "AND session_sha256=?", (owner,session_sha)).fetchone():
            raise PermissionError("owner host session was revoked")

    def __call__(self, owner, purpose, owner_proof):
        session=self._current(owner)
        if type(owner_proof) is not str or len(owner_proof)>4096:
            raise PermissionError("invalid host click")
        parts=owner_proof.split(".")
        if len(parts)!=2 or not parts[0].startswith("owner-click-"):
            raise PermissionError("host click nonce missing")
        digest=hashlib.sha256(owner_proof.encode()).hexdigest()
        with self.store.connect("chat_access") as db:
            row=db.execute("SELECT * FROM action_api_host_clicks WHERE token_sha256=?",
                           (digest,)).fetchone()
            if (row is None or row["owner"]!=owner or row["purpose"]!=purpose
                    or row["session_sha256"]!=self._fingerprint(session)
                    or row["origin_sha256"]!=self._origin(session)
                    or row["nonce_sha256"]!=hashlib.sha256(parts[1].encode()).hexdigest()
                    or row["expires"]<=self.clock()):
                raise PermissionError("host click identity, purpose or TTL mismatch")
            self._require_active(db,owner,row["session_sha256"])
            if row["state"]!="ISSUED":
                raise PermissionError("host click already consumed")
        return owner

    def consume(self, db, *, digest, owner, purpose):
        row=db.execute(
            "SELECT * FROM action_api_host_clicks WHERE token_sha256=?",
            (digest,)).fetchone()
        if (row is None or row["owner"]!=owner or row["purpose"]!=purpose
                or row["state"]!="ISSUED" or row["expires"]<=self.clock()):
            raise PermissionError("host click unavailable, expired or consumed")
        self._require_active(db,owner,row["session_sha256"])
        result=db.execute(
            "UPDATE action_api_host_clicks SET state='CONSUMED' "
            "WHERE token_sha256=? AND state='ISSUED'",(digest,))
        if result.rowcount!=1:
            raise PermissionError("host click concurrent replay")
        return row["session_sha256"]

    def revoke_current_session(self, *, owner):
        """Host authenticated logout/session freeze; no PID/Web effects."""
        session=self._current(owner)
        fingerprint=self._fingerprint(session)
        with self.store.connect("chat_access") as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO action_api_revoked_sessions VALUES(?,?,?)",
                (owner,fingerprint,self.clock()))
            db.execute("UPDATE action_api_host_clicks SET state='CONSUMED' "
                       "WHERE owner=? AND session_sha256=?",
                       (owner,fingerprint))
        return {"revoked":True,"owner":owner,"no_effect_replayed":True}

    def check_bound_session(self, db, *, owner, session_sha256):
        self._require_active(db,owner,session_sha256)
