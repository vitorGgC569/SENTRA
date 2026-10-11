"""Operator-enrolled, nonce-bound browser observations; never capability grants.

The extension transport authenticates the collector, not the truth of a page.
Only exact page request IDs can join MCP calls. Unknown React shapes, conflicting
identities, replay and stale documents fail closed. No chat prose is persisted.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time

from .chat_access import ChatAccessService, _ID, _PRINCIPAL, _validate
from .control_store import SQLiteControlPlaneStore

_EXTENSION = re.compile(r"^[a-p]{32}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_WORKER = re.compile(r"^TAB-[0-9]{1,12}$")
_HOST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,199}$")
_HOST_WORKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,99}$")
_PAGE_STATES = {"idle", "generating", "awaiting_approval", "signed_out", "unknown"}


class BrowserEvidenceService:
    def __init__(self, state_root, *, store=None, chat_access=None):
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.chat_access = chat_access or ChatAccessService(state_root, store=self.store)
        db = self.store.connect("chat_access")
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS browser_collectors(
                    extension_id TEXT PRIMARY KEY, principal TEXT NOT NULL,
                    workspace TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                    enabled INTEGER NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS browser_challenges(
                    nonce TEXT PRIMARY KEY, extension_id TEXT NOT NULL,
                    worker TEXT NOT NULL, document_id TEXT NOT NULL,
                    collector_revision INTEGER NOT NULL, created REAL NOT NULL,
                    consumed_sha256 TEXT);
                CREATE TABLE IF NOT EXISTS browser_documents(
                    extension_id TEXT NOT NULL, worker TEXT NOT NULL,
                    document_id TEXT NOT NULL, conversation_id TEXT,
                    observed REAL NOT NULL, state TEXT NOT NULL,
                    PRIMARY KEY(extension_id,worker));
                CREATE TABLE IF NOT EXISTS browser_revoked_documents(
                    extension_id TEXT NOT NULL, worker TEXT NOT NULL,
                    document_id TEXT NOT NULL, reason TEXT NOT NULL,
                    revoked REAL NOT NULL,
                    PRIMARY KEY(extension_id,worker,document_id));
                CREATE TABLE IF NOT EXISTS browser_document_epochs(
                    extension_id TEXT NOT NULL, worker TEXT NOT NULL,
                    document_id TEXT NOT NULL, identity_epoch TEXT NOT NULL,
                    PRIMARY KEY(extension_id,worker,document_id));
                CREATE TABLE IF NOT EXISTS browser_profile_uncertainty(
                    extension_id TEXT NOT NULL,
                    principal TEXT NOT NULL, reason TEXT NOT NULL,
                    detected REAL NOT NULL,
                    PRIMARY KEY(extension_id,principal));
                CREATE TABLE IF NOT EXISTS browser_request_conflicts(
                    principal TEXT NOT NULL, request_id TEXT NOT NULL,
                    detected REAL NOT NULL, PRIMARY KEY(principal,request_id));
                CREATE TABLE IF NOT EXISTS browser_chat_gates(
                    principal TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    state TEXT NOT NULL, observed REAL NOT NULL,
                    PRIMARY KEY(principal,conversation_id));
                CREATE TABLE IF NOT EXISTS browser_host_surfaces(
                    collector_id TEXT NOT NULL,worker TEXT NOT NULL,surface_id TEXT NOT NULL,
                    PRIMARY KEY(collector_id,worker),UNIQUE(collector_id,surface_id));
            """)
            db.execute("BEGIN IMMEDIATE")
            if "kind" not in {r["name"] for r in db.execute("PRAGMA table_info(browser_collectors)")}:
                db.execute("ALTER TABLE browser_collectors ADD COLUMN kind TEXT NOT NULL DEFAULT 'edge'")
            db.commit()
        finally:
            db.close()

    def configure(self, *, extension_id, principal, workspace, source_sha256,
                  enabled, expected_revision):
        """Local operator endpoint ONLY. Enrollment is explicit and revisioned."""
        _validate("extension identity", extension_id, _EXTENSION)
        _validate("principal", principal, _PRINCIPAL)
        _validate("source SHA256", source_sha256, _SHA)
        if not isinstance(workspace, str) or not 1 <= len(workspace) <= 4096:
            raise ValueError("workspace required")
        if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("collector boolean and revision required")
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM browser_collectors WHERE extension_id=?", (extension_id,)).fetchone()
            if (old["revision"] if old else 0) != expected_revision:
                raise ValueError("collector revision changed")
            if old and (old["principal"], old["workspace"]) != (principal, workspace):
                raise PermissionError("collector ownership is immutable; enroll another extension profile")
            if old and old["kind"] != "edge":
                raise PermissionError("host collector cannot be re-enrolled as Edge")
            db.execute("INSERT INTO browser_collectors (extension_id,principal,workspace,source_sha256,enabled,revision) "
                       "VALUES(?,?,?,?,?,?) ON CONFLICT(extension_id) "
                       "DO UPDATE SET source_sha256=excluded.source_sha256,enabled=excluded.enabled,revision=excluded.revision",
                       (extension_id, principal, workspace, source_sha256, int(enabled), expected_revision + 1))
            db.execute("DELETE FROM browser_challenges WHERE extension_id=?", (extension_id,))
            db.commit()
            return {"enabled": enabled, "revision": expected_revision + 1, "grants_created": False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def configure_host(self, *, collector_id, source_sha256, principal, workspace,
                       surface_id, worker, enabled, expected_revision, kind="electron"):
        """Explicit authenticated host enrollment. Never an Edge HTTP endpoint."""
        if kind != "electron":
            raise ValueError("supported host collector kind is electron")
        _validate("host collector identity", collector_id, _HOST_ID)
        if _EXTENSION.fullmatch(collector_id):
            raise ValueError("host collector identity cannot masquerade as an extension")
        _validate("host worker", worker, _HOST_WORKER)
        if _WORKER.fullmatch(worker):
            raise ValueError("host worker must use its real identity, not a Chrome TAB alias")
        _validate("host surface identity", surface_id, _HOST_ID)
        _validate("source SHA256", source_sha256, _SHA)
        _validate("principal", principal, _PRINCIPAL)
        if not isinstance(workspace, str) or not 1 <= len(workspace) <= 4096:
            raise ValueError("workspace required")
        if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("collector boolean and revision required")
        with self.store.connect("chat_access") as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM browser_collectors WHERE extension_id=?", (collector_id,)).fetchone()
            if (old["revision"] if old else 0) != expected_revision:
                raise ValueError("collector revision changed")
            if old and (old["principal"], old["workspace"], old["kind"]) != (principal, workspace, kind):
                raise PermissionError("host collector ownership and kind are immutable")
            previous = db.execute("SELECT surface_id FROM browser_host_surfaces WHERE collector_id=? AND worker=?",
                                  (collector_id, worker)).fetchone()
            if previous and previous[0] != surface_id:
                raise PermissionError("host worker belongs to another surface")
            db.execute("INSERT INTO browser_collectors (extension_id,principal,workspace,source_sha256,enabled,revision,kind) "
                       "VALUES(?,?,?,?,?,?,?) ON CONFLICT(extension_id) DO UPDATE SET "
                       "source_sha256=excluded.source_sha256,enabled=excluded.enabled,revision=excluded.revision",
                       (collector_id, principal, workspace, source_sha256, int(enabled), expected_revision + 1, kind))
            db.execute("INSERT OR IGNORE INTO browser_host_surfaces VALUES(?,?,?)", (collector_id, worker, surface_id))
            enrolled = db.execute("SELECT surface_id FROM browser_host_surfaces WHERE collector_id=? AND worker=?",
                                  (collector_id, worker)).fetchone()
            if not enrolled or enrolled[0] != surface_id:
                raise PermissionError("host surface already belongs to another worker")
            db.execute("DELETE FROM browser_challenges WHERE extension_id=?", (collector_id,))
        return {"collector_id": collector_id, "kind": kind, "enabled": enabled,
                "revision": expected_revision + 1, "grants_created": False}

    def _collector(self, db, extension_id, source_sha256, *, kind="edge", worker=None, surface_id=None):
        _validate("collector identity", extension_id, _EXTENSION if kind == "edge" else _HOST_ID)
        _validate("source SHA256", source_sha256, _SHA)
        row = db.execute("SELECT * FROM browser_collectors WHERE extension_id=?", (extension_id,)).fetchone()
        if not row or row["kind"] != kind or not row["enabled"] or not secrets.compare_digest(row["source_sha256"], source_sha256):
            raise PermissionError("browser collector is not enrolled for this extension build")
        if kind == "electron":
            bound = db.execute("SELECT surface_id FROM browser_host_surfaces WHERE collector_id=? AND worker=?",
                               (extension_id, worker)).fetchone()
            if bound is None or bound[0] != surface_id:
                raise PermissionError("host collector surface/worker is not enrolled")
        return row

    def challenge(self, *, extension_id, source_sha256, worker, document_id,
                  identity_epoch=None):
        return self._challenge(extension_id=extension_id, source_sha256=source_sha256,
                               worker=worker, document_id=document_id, identity_epoch=identity_epoch)

    def challenge_host(self, *, collector_id, source_sha256, surface_id, worker, document_id, identity_epoch):
        _validate("host surface identity", surface_id, _HOST_ID)
        _validate("identity epoch", identity_epoch, _ID)
        return self._challenge(extension_id=collector_id, source_sha256=source_sha256, worker=worker,
                               document_id=document_id, identity_epoch=identity_epoch, kind="electron", surface_id=surface_id)

    def _challenge(self, *, extension_id, source_sha256, worker, document_id,
                   identity_epoch=None, kind="edge", surface_id=None):
        _validate("worker", worker, _WORKER if kind == "edge" else _HOST_WORKER)
        _validate("document identity", document_id, _ID)
        if identity_epoch is not None:
            _validate("identity epoch", identity_epoch, _ID)
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            collector = self._collector(db, extension_id, source_sha256, kind=kind, worker=worker, surface_id=surface_id)
            now = time.time()
            if db.execute("SELECT 1 FROM browser_revoked_documents "
                          "WHERE extension_id=? AND worker=? AND document_id=?",
                          (extension_id,worker,document_id)).fetchone():
                raise PermissionError("revoked browser document cannot regain identity")
            old = db.execute("SELECT document_id,conversation_id FROM browser_documents "
                             "WHERE extension_id=? AND worker=?",
                             (extension_id,worker)).fetchone()
            if old and old["document_id"] != document_id:
                # A newly observed document fences requests from the old page
                # immediately, even when its first React scan fails.
                db.execute("INSERT OR IGNORE INTO browser_revoked_documents VALUES(?,?,?,?,?)",
                           (extension_id,worker,old["document_id"],"document_changed",now))
                db.execute("UPDATE browser_documents SET document_id=?,conversation_id=NULL,"
                           "state='unknown',observed=? WHERE extension_id=? AND worker=?",
                           (document_id,now,extension_id,worker))
                if old["conversation_id"]:
                    db.execute("UPDATE browser_chat_gates SET state='unknown',observed=? "
                               "WHERE principal=? AND conversation_id=?",
                               (now,collector["principal"],old["conversation_id"]))
            prior_epoch = db.execute(
                "SELECT identity_epoch FROM browser_document_epochs "
                "WHERE extension_id=? AND worker=? AND document_id=?",
                (extension_id,worker,document_id)).fetchone()
            if prior_epoch and prior_epoch["identity_epoch"] != identity_epoch:
                raise PermissionError("browser identity epoch changed for same document")
            if identity_epoch is not None and prior_epoch is None:
                db.execute("INSERT INTO browser_document_epochs VALUES(?,?,?,?)",
                           (extension_id,worker,document_id,identity_epoch))
            db.execute("DELETE FROM browser_challenges WHERE created<?", (now - 120,))
            # One live challenge per owned tab; bounded even under a noisy page.
            db.execute("DELETE FROM browser_challenges WHERE extension_id=? AND worker=?",
                       (extension_id, worker))
            nonce = secrets.token_urlsafe(32)
            db.execute("INSERT INTO browser_challenges VALUES(?,?,?,?,?,?,NULL)",
                       (nonce, extension_id, worker, document_id, collector["revision"], now))
            db.commit()
            return {"nonce": nonce, "expires_in": 30}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def observe(self, *, extension_id, source_sha256, worker, evidence):
        return self._observe(extension_id=extension_id, source_sha256=source_sha256, worker=worker, evidence=evidence)

    def observe_host(self, *, collector_id, source_sha256, surface_id, worker, evidence):
        _validate("host surface identity", surface_id, _HOST_ID)
        if not isinstance(evidence, dict) or not evidence.get("identity_epoch"):
            raise ValueError("host observation requires identity epoch")
        return self._observe(extension_id=collector_id, source_sha256=source_sha256, worker=worker,
                             evidence=evidence, kind="electron", surface_id=surface_id)

    def _observe(self, *, extension_id, source_sha256, worker, evidence, kind="edge", surface_id=None):
        required = {"nonce","document_id","conversation_id",
                    "route_conversation_id","state","requests"}
        if not isinstance(evidence, dict) or set(evidence) not in (
                required, required | {"identity_epoch"}):
            raise ValueError("exact browser evidence schema required")
        if "identity_epoch" in evidence:
            _validate("identity epoch",evidence["identity_epoch"],_ID)
        _validate("worker", worker, _WORKER if kind == "edge" else _HOST_WORKER)
        _validate("document identity", evidence["document_id"], _ID)
        _validate("nonce", evidence["nonce"], _ID)
        conversation = _validate("conversation identity", evidence["conversation_id"], _ID)
        if conversation != evidence["route_conversation_id"]:
            raise PermissionError("page branch and route identities disagree")
        if evidence["state"] not in _PAGE_STATES:
            raise ValueError("unknown browser page state")
        requests = evidence["requests"]
        if not isinstance(requests, list) or len(requests) > 200:
            raise ValueError("browser request limit exceeded")
        seen = set()
        seen_messages = set()
        for item in requests:
            if not isinstance(item, dict) or set(item) != {"request_id", "message_id"}:
                raise ValueError("request evidence allows identifiers only")
            _validate("request identity", item["request_id"], _ID)
            _validate("message identity", item["message_id"], _ID)
            if item["request_id"] in seen or item["message_id"] in seen_messages:
                raise ValueError("duplicate request/message observation")
            seen.add(item["request_id"])
            seen_messages.add(item["message_id"])
        canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        if len(canonical) > 65536:
            raise ValueError("browser evidence byte limit exceeded")
        digest = hashlib.sha256(canonical).hexdigest()
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            collector = self._collector(db, extension_id, source_sha256, kind=kind, worker=worker, surface_id=surface_id)
            epoch=db.execute("SELECT identity_epoch FROM browser_document_epochs "
                             "WHERE extension_id=? AND worker=? AND document_id=?",
                             (extension_id,worker,evidence["document_id"])).fetchone()
            if (epoch is not None and
                    epoch["identity_epoch"] != evidence.get("identity_epoch")):
                raise PermissionError("browser identity epoch does not match challenge")
            if epoch is None and "identity_epoch" in evidence:
                raise PermissionError("browser identity epoch lacks a bound challenge")
            if db.execute("SELECT 1 FROM browser_revoked_documents "
                          "WHERE extension_id=? AND worker=? AND document_id=?",
                          (extension_id,worker,evidence["document_id"])).fetchone():
                raise PermissionError("revoked browser document cannot be observed")
            challenge = db.execute("SELECT * FROM browser_challenges WHERE nonce=?", (evidence["nonce"],)).fetchone()
            if not challenge or (challenge["extension_id"], challenge["worker"], challenge["document_id"],
                                 challenge["collector_revision"]) != (
                extension_id, worker, evidence["document_id"], collector["revision"]
            ) or time.time() - challenge["created"] > 30:
                raise PermissionError("expired, revoked or mismatched browser challenge")
            if challenge["consumed_sha256"]:
                if not secrets.compare_digest(challenge["consumed_sha256"], digest):
                    raise PermissionError("browser nonce replay with different evidence")
                if any(db.execute("SELECT 1 FROM browser_request_conflicts WHERE principal=? AND request_id=?",
                                  (collector["principal"], item["request_id"])).fetchone() for item in requests):
                    raise PermissionError("conflicting request ownership remains quarantined")
                return {"state": "unchanged", "requests": len(requests), "grants_created": False}
            principal = collector["principal"]
            conflicts = set()
            for item in requests:
                old = db.execute("SELECT conversation_id FROM chat_request_owners WHERE principal=? AND request_id=?",
                                 (principal, item["request_id"])).fetchone()
                if old and old["conversation_id"] != conversation:
                    conflicts.add(item["request_id"])
                message = db.execute(
                    "SELECT request_id,message_id FROM browser_request_messages "
                    "WHERE principal=? AND (request_id=? OR message_id=?)",
                    (principal,item["request_id"],item["message_id"])
                ).fetchall()
                for linked in message:
                    if (linked["request_id"] != item["request_id"]
                            or linked["message_id"] != item["message_id"]):
                        conflicts.update((linked["request_id"],item["request_id"]))
            now = time.time()
            if conflicts:
                for request in sorted(conflicts):
                    db.execute("INSERT OR IGNORE INTO browser_request_conflicts VALUES(?,?,?)", (principal, request, now))
                db.execute("UPDATE browser_challenges SET consumed_sha256=? WHERE nonce=?", (digest, evidence["nonce"]))
                db.commit()  # Persist quarantine even though ingress is refused.
                raise PermissionError("conflicting request ownership quarantined")
            for item in requests:
                db.execute("INSERT OR IGNORE INTO chat_request_owners VALUES(?,?,?,?,?)",
                           (principal, item["request_id"], conversation, digest, now))
                db.execute(
                    "INSERT OR IGNORE INTO browser_request_messages VALUES(?,?,?,?,?,?,?)",
                    (principal,item["request_id"],item["message_id"],extension_id,
                     worker,evidence["document_id"],collector["revision"])
                )
            db.execute("INSERT INTO browser_documents VALUES(?,?,?,?,?,?) ON CONFLICT(extension_id,worker) "
                       "DO UPDATE SET document_id=excluded.document_id,conversation_id=excluded.conversation_id,"
                       "observed=excluded.observed,state=excluded.state",
                       (extension_id, worker, evidence["document_id"], conversation, now, evidence["state"]))
            states={r[0] for r in db.execute("SELECT d.state FROM browser_documents d JOIN browser_collectors c "
                    "ON d.extension_id=c.extension_id WHERE c.principal=? AND c.enabled=1 AND d.conversation_id=?",
                    (principal,conversation)).fetchall()}
            gate_state=next((s for s in ("awaiting_approval","signed_out","unknown") if s in states),evidence["state"])
            db.execute("INSERT INTO browser_chat_gates VALUES(?,?,?,?) ON CONFLICT(principal,conversation_id) "
                       "DO UPDATE SET state=excluded.state,observed=excluded.observed",
                       (principal, conversation, gate_state, now))
            db.execute("UPDATE browser_challenges SET consumed_sha256=? WHERE nonce=?", (digest, evidence["nonce"]))
            db.commit()
            return {"state": "observed", "requests": len(requests), "grants_created": False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def status(self, workspace):
        db = self.store.connect("chat_access")
        try:
            rows = db.execute("SELECT c.extension_id,c.kind,c.principal,c.enabled,c.revision,c.source_sha256,"
                              "d.worker,d.conversation_id,d.state,d.observed FROM browser_collectors c "
                              "LEFT JOIN browser_documents d ON c.extension_id=d.extension_id WHERE c.workspace=? "
                              "ORDER BY c.extension_id,d.worker LIMIT 100", (workspace,)).fetchall()
            return {"collectors": [dict(r) for r in rows], "creates_permissions": False,
                    "evidence_kind": "authenticated_collector_page_observation"}
        finally:
            db.close()

    def browser_principal_for(self, worker, *, collector_id=None, source_sha256=None, surface_id=None):
        """Host-only enrollment lookup; it never substitutes message proof."""
        edge = isinstance(worker, str) and _WORKER.fullmatch(worker)
        _validate("worker", worker, _WORKER if edge else _HOST_WORKER)
        with self.store.connect("chat_access") as db:
            if edge:
                rows = db.execute("SELECT c.*,NULL AS surface_id FROM browser_collectors c "
                                  "JOIN browser_documents d ON d.extension_id=c.extension_id "
                                  "WHERE c.enabled=1 AND c.kind='edge' AND d.worker=?", (worker,)).fetchall()
            else:
                rows = db.execute("SELECT c.*,h.surface_id FROM browser_collectors c "
                                  "JOIN browser_host_surfaces h ON h.collector_id=c.extension_id "
                                  "WHERE c.enabled=1 AND c.kind='electron' AND h.worker=?", (worker,)).fetchall()
        rows = [r for r in rows if (collector_id is None or r["extension_id"] == collector_id)
                and (source_sha256 is None or r["source_sha256"] == source_sha256)
                and (surface_id is None or r["surface_id"] == surface_id)]
        if len(rows) != 1:
            raise PermissionError("worker has no unique enabled collector enrollment")
        return rows[0]["principal"]

    def dispatch_state(self, principal, conversation_id, *, max_age_s=120):
        """Return conservative, scoped page state; never an execution grant."""
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation identity", conversation_id, _ID)
        if not isinstance(max_age_s, (int, float)) or max_age_s <= 0 or max_age_s > 3600:
            raise ValueError("invalid evidence freshness window")
        db = self.store.connect("chat_access")
        try:
            row = db.execute("SELECT state,observed FROM browser_chat_gates WHERE "
                             "principal=? AND conversation_id=?",
                             (principal, conversation_id)).fetchone()
            uncertain = db.execute(
                "SELECT 1 FROM browser_profile_uncertainty WHERE principal=? LIMIT 1",
                (principal,)).fetchone()
        finally:
            db.close()
        if uncertain:
            return {"state":"identity_unknown","send_blocked":True,
                    "evidence_present":row is not None}
        if row is None:
            return {"state": "unverified", "send_blocked": False, "evidence_present": False}
        age = max(0.0, time.time() - float(row["observed"]))
        state = str(row["state"])
        return {"state": state, "age_s": round(age, 2),
                "send_blocked": state != "idle" or age > max_age_s,
                "evidence_present": True}

    def require_dispatch_ready(self, principal, conversation_id):
        """Block new effects during human approval, generation or stale evidence.

        Unenrolled conversations keep legacy behavior. This guard cannot
        override the durable authorization or resend a pending browser job.
        """
        status = self.dispatch_state(principal, conversation_id)
        if status["send_blocked"]:
            raise PermissionError("browser conversation requires fresh idle evidence; "
                                  "human approval or generation may still be pending")
        return status

    def invalidate_document(self, *, extension_id, source_sha256, worker,
                            document_id, reason, identity_epoch=None):
        """Host-authenticated *deny-only* ingress from an enrolled extension.

        Route contract: /browser-evidence/invalidate, existing extension-origin
        + relay bearer enforcement, JSON exactly source_sha256/worker/
        document_id/reason. Neither the page nor an MCP tool may invoke this.
        """
        return self._invalidate(extension_id=extension_id, source_sha256=source_sha256, worker=worker,
                                document_id=document_id, reason=reason, identity_epoch=identity_epoch)

    def invalidate_host(self, *, collector_id, source_sha256, surface_id, worker, document_id, identity_epoch, reason):
        _validate("host surface identity", surface_id, _HOST_ID)
        _validate("identity epoch", identity_epoch, _ID)
        return self._invalidate(extension_id=collector_id, source_sha256=source_sha256, worker=worker,
                                document_id=document_id, reason=reason, identity_epoch=identity_epoch,
                                kind="electron", surface_id=surface_id)

    def _invalidate(self, *, extension_id, source_sha256, worker, document_id, reason,
                    identity_epoch=None, kind="edge", surface_id=None):
        _validate("worker", worker, _WORKER if kind == "edge" else _HOST_WORKER)
        _validate("document identity", document_id, _ID)
        if identity_epoch is not None:
            _validate("identity epoch", identity_epoch, _ID)
        if reason not in {"tab_closed", "navigation", "signed_out",
                          "account_changed", "profile_changed", "identity_unknown"}:
            raise ValueError("invalid browser invalidation reason")
        db=self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            collector=self._collector(db,extension_id,source_sha256,kind=kind,worker=worker,surface_id=surface_id)
            current=db.execute(
                "SELECT document_id,conversation_id FROM browser_documents "
                "WHERE extension_id=? AND worker=?",
                (extension_id,worker)).fetchone()
            bound_epoch=db.execute(
                "SELECT identity_epoch FROM browser_document_epochs WHERE "
                "extension_id=? AND worker=? AND document_id=?",
                (extension_id,worker,document_id)).fetchone()
            if bound_epoch and bound_epoch["identity_epoch"] != identity_epoch:
                raise PermissionError("browser invalidation identity epoch mismatch")
            if not bound_epoch and identity_epoch is not None:
                raise PermissionError("unbound browser identity epoch")
            if current is None:
                db.commit()
                return {"state":"absent","grants_created":False}
            if current["document_id"]!=document_id:
                # A delayed notification from the previous tab/document
                # must never damage a newly registered document.
                raise PermissionError("stale document invalidation")
            now=time.time()
            if reason in {"signed_out","account_changed","profile_changed","identity_unknown"}:
                # A page coming back to "idle" is NOT a verified account
                # recovery. Persist the uncertainty across tabs and restarts.
                # Only a future independent HOST account attestation can
                # safely clear this ledger; collector re-enrollment alone cannot.
                db.execute(
                    "INSERT INTO browser_profile_uncertainty VALUES(?,?,?,?) "
                    "ON CONFLICT(extension_id,principal) DO UPDATE SET "
                    "reason=excluded.reason,detected=excluded.detected",
                    (extension_id,collector["principal"],reason,now))
            db.execute("INSERT OR IGNORE INTO browser_revoked_documents VALUES(?,?,?,?,?)",
                       (extension_id,worker,document_id,reason,now))
            db.execute("DELETE FROM browser_challenges WHERE extension_id=? AND worker=?",
                       (extension_id,worker))
            db.execute("UPDATE browser_documents SET state='unknown',"
                       "conversation_id=NULL,observed=? WHERE extension_id=? AND worker=?",
                       (now,extension_id,worker))
            if current["conversation_id"]:
                # Account/profile changes may affect all tabs; only a plain
                # navigation/closed-tab may defer to independently live tabs.
                next_state="unknown"
                if reason in {"navigation","tab_closed"}:
                    states={r[0] for r in db.execute(
                        "SELECT d.state FROM browser_documents d "
                        "JOIN browser_collectors c ON d.extension_id=c.extension_id "
                        "WHERE c.principal=? AND c.enabled=1 AND d.conversation_id=?",
                        (collector["principal"],current["conversation_id"])).fetchall()}
                    if states:
                        next_state=next((s for s in
                            ("awaiting_approval","signed_out","unknown","generating")
                            if s in states),"idle")
                db.execute("INSERT INTO browser_chat_gates VALUES(?,?,?,?) "
                           "ON CONFLICT(principal,conversation_id) DO UPDATE SET "
                           "state=excluded.state,observed=excluded.observed",
                           (collector["principal"],current["conversation_id"],next_state,now))
            db.commit()
            return {"state":"invalidated","grants_created":False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
