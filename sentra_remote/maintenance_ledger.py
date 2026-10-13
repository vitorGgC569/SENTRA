"""Reservations/receipts on the configured CP store, never an authority replica."""
from contextlib import contextmanager
import hashlib
import json
import time
import uuid

from sentra_core.conversations import _encode, _decode


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class MaintenanceLedger:
    def __init__(self, control, *, owner, installation_id):
        if not control or not owner or not installation_id:
            raise ValueError("configured CP owner and installation binding required")
        self.control, self.store = control, control.store
        self.owner, self.installation = owner, installation_id
        self.tenant = getattr(self.store, "tenant_id", "local")
        if hasattr(self.store, "assert_principal"):
            self.store.assert_principal(owner)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS maintenance_requests(
                  owner TEXT NOT NULL, installation_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                  request_key TEXT NOT NULL, action TEXT NOT NULL, fingerprint TEXT NOT NULL,
                  operation_id TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL,
                  protected_intent TEXT NOT NULL, protected_result TEXT, receipt_id TEXT NOT NULL,
                  updated_at REAL NOT NULL, PRIMARY KEY(owner,installation_id,request_key));
                CREATE TABLE IF NOT EXISTS maintenance_versions(
                  owner TEXT NOT NULL, installation_id TEXT NOT NULL, revision INTEGER NOT NULL,
                  PRIMARY KEY(owner,installation_id));
            """)

    @contextmanager
    def db(self):
        db = self.store.connect("shell")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _scope(self):
        return self.owner, self.installation

    def revision(self):
        with self.db() as db:
            row = db.execute("SELECT revision FROM maintenance_versions WHERE owner=? AND installation_id=?", self._scope()).fetchone()
            return row["revision"] if row else 0

    def lookup(self, key):
        with self.db() as db:
            row = db.execute("SELECT * FROM maintenance_requests WHERE owner=? AND installation_id=? AND request_key=?", self._scope() + (key,)).fetchone()
        if not row:
            return None
        if row["tenant_id"] != self.tenant:
            raise PermissionError("maintenance receipt tenant mismatch")
        result = _decode(row["protected_result"]) if row["protected_result"] else None
        return {"request_key": key, "action": row["action"], "fingerprint": row["fingerprint"],
                "operation_id": row["operation_id"], "state": row["state"], "revision": row["revision"],
                "receipt_id": row["receipt_id"], "result": result}

    def reserve(self, key, action, intent, operation_id, *, expected_revision=None):
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("maintenance expected_revision must be a nonnegative integer")
        fingerprint = hashlib.sha256(canonical({"owner": self.owner, "tenant": self.tenant,
            "installation": self.installation, "action": action, "intent": intent}).encode()).hexdigest()
        protected = _encode(intent)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM maintenance_requests WHERE owner=? AND installation_id=? AND request_key=?", self._scope() + (key,)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint or row["action"] != action or row["tenant_id"] != self.tenant:
                    raise PermissionError("maintenance request_key bound to another immutable intent")
                return False
            active = db.execute("SELECT state FROM maintenance_requests WHERE owner=? AND installation_id=? AND state IN ('PENDING','RUNNING','UNCERTAIN') LIMIT 1", self._scope()).fetchone()
            if active:
                raise RuntimeError("maintenance effect pending; reconcile before admitting another effect")
            current = db.execute("SELECT revision FROM maintenance_versions WHERE owner=? AND installation_id=?", self._scope()).fetchone()
            revision = current["revision"] if current else 0
            if expected_revision is not None and expected_revision != revision:
                raise FileExistsError("maintenance CAS changed; refresh status")
            db.execute("INSERT INTO maintenance_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", self._scope() +
                (self.tenant, key, action, fingerprint, operation_id, "PENDING", 1, protected, None,
                 "maintenance-receipt-" + uuid.uuid4().hex, time.time()))
            db.execute("INSERT INTO maintenance_versions VALUES(?,?,?) ON CONFLICT(owner,installation_id) DO UPDATE SET revision=excluded.revision", self._scope() + (revision + 1,))
        return True

    def transition(self, key, *, from_state, revision, state, result=None):
        if state not in {"RUNNING", "SUCCEEDED", "FAILED", "UNCERTAIN", "DEFERRED"}:
            raise ValueError("invalid maintenance receipt state")
        protected = _encode(result) if result is not None else None
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE maintenance_requests SET state=?,revision=revision+1,protected_result=?,updated_at=? WHERE owner=? AND installation_id=? AND request_key=? AND state=? AND revision=?",
                (state, protected, time.time()) + self._scope() + (key, from_state, revision)).rowcount
            if changed != 1:
                raise FileExistsError("maintenance reservation CAS changed")
        return self.lookup(key)
