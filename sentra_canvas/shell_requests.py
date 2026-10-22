"""Protected host request journal; all execution authority stays in Control Plane.

Missing a phase marker does not prove that no effect ran. The claim row
leaves phase empty. before_admission is stored only when the caller durably
attests that admission and effect did not happen. An unattested failure stays
uncertain and does not invent a phase.
"""
from contextlib import closing
import hashlib
import hmac
import json
import re
import threading
import time

from sentra_core.conversations import _encode, _decode
from sentra_mcp.services.shell_coordinator import ShellConflict

_OPERATION_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_EXCEPTION_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_ADMITTED_REASON = "request admitted; observe its outcome before resubmitting"
_EXPLICIT_PHASES = {"before_admission", "after_possible_effect"}


def _exception_class(exc):
    name = type(exc).__name__
    if not _EXCEPTION_CLASS.fullmatch(name):
        return "Exception"
    return name


def _safe_operation_id(operation_id):
    if operation_id is None:
        return None
    if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id):
        raise ValueError("operation_id is not a safe identifier")
    return operation_id


def _failure_receipt(request_key, exc, phase, operation_id):
    if phase not in _EXPLICIT_PHASES:
        phase = None
    before = phase == "before_admission"
    known_effect = phase == "after_possible_effect"
    return {
        "status": "admission_failed" if before else "uncertain",
        "request_key": request_key,
        "receipt_id": None,
        "automatic_retry": False,
        "may_resend": False,
        "success": False,
        "query_failed": before,
        "effect_uncertain": not before,
        "phase": phase,
        "reason": "host request failed before any effect was admitted" if before else _ADMITTED_REASON,
        "diagnosis": {
            "code": "admission_failed" if before else ("effect_uncertain" if known_effect else "phase_unattested"),
            "exception_class": _exception_class(exc),
            "operation_id": operation_id if isinstance(operation_id, str) else None,
        },
    }


class ShellHostRequests:
    def __init__(self, control, owner):
        self.control, self.owner = control, owner
        self.lock = threading.RLock()
        with closing(control.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS canvas_shell_request_schema(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL)")
            version = db.execute("SELECT version FROM canvas_shell_request_schema WHERE id=1").fetchone()
            if version is not None and version[0] > 2:
                raise RuntimeError("host request schema is newer than this application")
            db.execute("CREATE TABLE IF NOT EXISTS canvas_shell_host_requests("
                "owner TEXT NOT NULL,project_id TEXT NOT NULL,request_key TEXT NOT NULL,"
                "fingerprint TEXT NOT NULL,state TEXT NOT NULL,protected_result TEXT,"
                "created_at REAL NOT NULL,updated_at REAL NOT NULL,"
                "PRIMARY KEY(owner,project_id,request_key))")
            cols = {row[1] for row in db.execute("PRAGMA table_info(canvas_shell_host_requests)")}
            if "phase" not in cols:
                db.execute("ALTER TABLE canvas_shell_host_requests ADD COLUMN phase TEXT")
            if "operation_id" not in cols:
                db.execute("ALTER TABLE canvas_shell_host_requests ADD COLUMN operation_id TEXT")
            if "protected_intent" not in cols:
                db.execute("ALTER TABLE canvas_shell_host_requests ADD COLUMN protected_intent TEXT")
            db.execute("INSERT INTO canvas_shell_request_schema VALUES(1,2) ON CONFLICT(id) DO UPDATE SET version=2")

    def operation_id(self, project_id, request_key, purpose):
        value = json.dumps([self.owner, project_id, request_key, purpose], separators=(",", ":"))
        return "op-shell-" + hashlib.sha256(value.encode()).hexdigest()[:40]

    def _row(self, db, project_id, request_key):
        return db.execute("SELECT * FROM canvas_shell_host_requests WHERE "
            "owner=? AND project_id=? AND request_key=?",
            (self.owner, project_id, request_key)).fetchone()

    def _mark(self, project_id, request_key, phase, operation_id):
        operation_id = _safe_operation_id(operation_id)
        with self.lock:
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = self._row(db, project_id, request_key)
                if row is None or row["state"] not in {"claimed", "effect_possible"}:
                    raise ShellConflict("host request is not open for a phase mark")
                if row["phase"] == "after_possible_effect" and phase != "after_possible_effect":
                    raise ShellConflict("an effect may already have started")
                state = "effect_possible" if phase == "after_possible_effect" else row["state"]
                db.execute("UPDATE canvas_shell_host_requests SET state=?,phase=?,operation_id=?,updated_at=? "
                    "WHERE owner=? AND project_id=? AND request_key=?",
                    (state, phase, operation_id if operation_id is not None else row["operation_id"],
                     time.time(), self.owner, project_id, request_key))

    def note_before_admission(self, project_id, request_key):
        """Attest that this open request has not reserved an intent or started an effect.

        Calling this without that evidence is a false receipt. Legacy callbacks
        must not use it to paper over an unknown failure.
        """
        self._mark(project_id, request_key, "before_admission", None)

    def note_effect_possible(self, project_id, request_key, operation_id=None):
        """Durably mark that reserve_intent or another effect may have started."""
        self._mark(project_id, request_key, "after_possible_effect", operation_id)

    def _open_receipt(self, row):
        phase = row["phase"] if "phase" in row.keys() else None
        operation_id = row["operation_id"] if "operation_id" in row.keys() else None
        if phase == "after_possible_effect" or row["state"] == "effect_possible":
            return {"status": "uncertain", "request_key": row["request_key"],
                "receipt_id": None, "automatic_retry": False, "may_resend": False,
                "success": False, "query_failed": False, "effect_uncertain": True,
                "phase": "after_possible_effect", "reason": _ADMITTED_REASON,
                "diagnosis": {"code": "effect_uncertain", "exception_class": None,
                    "operation_id": operation_id}}
        if phase == "before_admission":
            return {"status": "uncertain", "request_key": row["request_key"],
                "receipt_id": None, "automatic_retry": False, "may_resend": False,
                "success": False, "query_failed": False, "effect_uncertain": True,
                "phase": "before_admission", "reason": _ADMITTED_REASON,
                "diagnosis": {"code": "phase_unknown", "exception_class": None,
                    "operation_id": operation_id}}
        return {"status": "uncertain", "request_key": row["request_key"],
            "receipt_id": None, "automatic_retry": False,
            "reason": _ADMITTED_REASON}

    def invoke(self, project_id, action, payload, request_key, callback):
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 200:
            raise ValueError("mutation requires a durable request_key")
        fingerprint = hashlib.sha256(json.dumps([action, payload], sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.lock:
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = self._row(db, project_id, request_key)
                if row:
                    if row["fingerprint"] != fingerprint:
                        raise ShellConflict("request_key belongs to another intent")
                    if row["protected_result"]:
                        return _decode(row["protected_result"])
                    return self._open_receipt(row)
                now = time.time()
                db.execute("INSERT INTO canvas_shell_host_requests("
                    "owner,project_id,request_key,fingerprint,state,protected_result,created_at,updated_at,protected_intent) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (self.owner, project_id, request_key, fingerprint, "claimed", None, now, now,
                     _encode({"action": action, "payload": payload})))
        # No database transaction or global lock spans provider network I/O.
        try:
            result = callback()
            if not isinstance(result, dict):
                raise ValueError("host action returned an invalid projection")
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("UPDATE canvas_shell_host_requests SET state=?,protected_result=?,"
                    "updated_at=? WHERE owner=? AND project_id=? AND request_key=?",
                    (result.get("status", "committed"), _encode(result), time.time(),
                     self.owner, project_id, request_key))
            return result
        except BaseException as exc:
            with closing(self.control.store.connect("shell")) as db:
                current = self._row(db, project_id, request_key)
            stored_phase = current["phase"] if current is not None else None
            phase = stored_phase if stored_phase in _EXPLICIT_PHASES else None
            operation_id = current["operation_id"] if current is not None else None
            receipt = _failure_receipt(request_key, exc, phase, operation_id)
            with closing(self.control.store.connect("shell")) as db, db:
                if phase in _EXPLICIT_PHASES:
                    db.execute("UPDATE canvas_shell_host_requests SET state=?,phase=?,operation_id=?,"
                        "protected_result=?,updated_at=? WHERE owner=? AND project_id=? AND request_key=?",
                        (receipt["status"], phase, receipt["diagnosis"]["operation_id"],
                         _encode(receipt), time.time(), self.owner, project_id, request_key))
                else:
                    db.execute("UPDATE canvas_shell_host_requests SET state=?,protected_result=?,updated_at=? "
                        "WHERE owner=? AND project_id=? AND request_key=? AND phase IS NULL",
                        (receipt["status"], _encode(receipt), time.time(),
                         self.owner, project_id, request_key))
            raise

    def inspect(self, project_id, action, payload, request_key):
        """Read an exact existing intent. Never invoke its callback or reserve it.

        Absence does not authorize replay: a client may have lost the transport
        before the host persisted a claim. Callers must validate resource scope
        before exposing a protected result.
        """
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 200:
            raise ValueError("original durable request_key required")
        fingerprint = hashlib.sha256(json.dumps([action, payload], sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with closing(self.control.store.connect("shell")) as db:
            row = self._row(db, project_id, request_key)
        if row is None:
            return {"found": False, "resolved": False, "request_key": request_key,
                    "automatic_retry": False, "may_resend": False}
        if not hmac.compare_digest(row["fingerprint"], fingerprint):
            raise ShellConflict("request_key belongs to another intent")
        result = _decode(row["protected_result"]) if row["protected_result"] else self._open_receipt(row)
        operation_id = row["operation_id"] or result.get("operation_id") or (result.get("diagnosis") or {}).get("operation_id")
        operation_state = result.get("operation_state", result.get("state"))
        operation_open = operation_state is not None and str(operation_state).upper() not in {
            "SUCCEEDED", "FAILED", "CANCELLED"}
        return {"found": True, "resolved": bool(row["protected_result"]) and not operation_open
                and not result.get("effect_uncertain") and row["state"] not in
                {"claimed", "effect_possible", "uncertain", "unconfirmed"},
                "request_key": request_key, "journal_state": row["state"],
                "result": result, "operation_id": operation_id,
                "automatic_retry": False, "may_resend": False}

    def intent(self, project_id, request_key, fingerprint):
        """Host-only recovery of a protected original; never expose it to clients."""
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 200:
            raise ValueError("original durable request_key required")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("original request fingerprint required")
        with closing(self.control.store.connect("shell")) as db:
            row = self._row(db, project_id, request_key)
        if row is None:
            return None
        if not hmac.compare_digest(row["fingerprint"], fingerprint):
            raise ShellConflict("request_key belongs to another intent")
        if not row["protected_intent"]:
            raise ValueError("legacy request requires its exact original fields")
        return _decode(row["protected_intent"])
