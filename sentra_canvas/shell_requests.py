"""Protected host request journal; all execution authority stays in Control Plane.

Missing a phase marker does not prove that no effect ran. The claim row
leaves phase empty. before_admission is stored only when the caller durably
attests that admission and effect did not happen. An unattested failure stays
uncertain and does not invent a phase.
"""
from contextlib import closing
from dataclasses import dataclass
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
_RETIREMENT_RESERVATION = 1024


@dataclass(frozen=True)
class HostRequestRetentionPolicy:
    """Admission bounds include unresolved records; their contents are never evicted."""
    max_records: int = 250_000
    max_protected_bytes: int = 256 * 1024 * 1024
    result_reservation_bytes: int = 3 * 1024 * 1024
    retain_after_ack_seconds: int = 7 * 24 * 60 * 60
    compact_batch: int = 64

    def __post_init__(self):
        if (any(type(value) is not int for value in vars(self).values())
                or self.max_records < 1 or self.result_reservation_bytes < 4096
                or self.max_protected_bytes < self.result_reservation_bytes
                or self.retain_after_ack_seconds < 0 or not 1 <= self.compact_batch <= 1024):
            raise ValueError("invalid protected request retention policy")


class HostRequestCapacityError(ValueError):
    """No callback was admitted. Existing selectors remain observable."""


def _resolved_result(row, result):
    operation_state = result.get("operation_state", result.get("state"))
    operation_open = operation_state is not None and str(operation_state).upper() not in {
        "SUCCEEDED", "FAILED", "CANCELLED"}
    return bool(row["protected_result"]) and not operation_open and not result.get("effect_uncertain") and row["state"] not in {
        "claimed", "effect_possible", "uncertain", "unconfirmed"}


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
    def __init__(self, control, owner, *, retention_policy=None):
        if not isinstance(owner, str) or not 1 <= len(owner) <= 256:
            raise ValueError("bounded host request owner required")
        self.control, self.owner = control, owner
        self.retention_policy = retention_policy or HostRequestRetentionPolicy()
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
            # Additive extension: schema-v2 readers still return the protected
            # tombstone, never an empty row that could run its callback again.
            db.execute("CREATE TABLE IF NOT EXISTS canvas_shell_request_retention_schema("
                "id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL)")
            retention_version = db.execute("SELECT version FROM canvas_shell_request_retention_schema WHERE id=1").fetchone()
            if retention_version is not None and retention_version[0] != 1:
                raise RuntimeError("host request retention schema is newer than this application")
            for name, sql_type in (("retention_ack_at", "REAL"), ("retired_at", "REAL"),
                                   ("reserved_bytes", "INTEGER NOT NULL DEFAULT 0")):
                if name not in cols:
                    db.execute("ALTER TABLE canvas_shell_host_requests ADD COLUMN " + name + " " + sql_type)
            db.execute("CREATE TABLE IF NOT EXISTS canvas_shell_request_usage("
                "owner TEXT PRIMARY KEY,record_count INTEGER NOT NULL,protected_bytes INTEGER NOT NULL,reserved_bytes INTEGER NOT NULL)")
            if retention_version is None:
                db.execute("INSERT INTO canvas_shell_request_usage "
                    "SELECT owner,COUNT(*),SUM(LENGTH(COALESCE(protected_intent,''))+LENGTH(COALESCE(protected_result,''))),"
                    "SUM(reserved_bytes) FROM canvas_shell_host_requests GROUP BY owner")
            # Triggers count changes made by compatible older applications too.
            db.execute("CREATE TRIGGER IF NOT EXISTS canvas_shell_request_usage_insert AFTER INSERT ON canvas_shell_host_requests BEGIN "
                "INSERT INTO canvas_shell_request_usage VALUES(NEW.owner,1,LENGTH(COALESCE(NEW.protected_intent,''))+LENGTH(COALESCE(NEW.protected_result,'')),NEW.reserved_bytes) "
                "ON CONFLICT(owner) DO UPDATE SET record_count=record_count+1,protected_bytes=protected_bytes+excluded.protected_bytes,reserved_bytes=reserved_bytes+excluded.reserved_bytes; END")
            db.execute("CREATE TRIGGER IF NOT EXISTS canvas_shell_request_usage_update AFTER UPDATE ON canvas_shell_host_requests BEGIN "
                "UPDATE canvas_shell_request_usage SET protected_bytes=protected_bytes+LENGTH(COALESCE(NEW.protected_intent,''))+LENGTH(COALESCE(NEW.protected_result,''))"
                "-LENGTH(COALESCE(OLD.protected_intent,''))-LENGTH(COALESCE(OLD.protected_result,'')),reserved_bytes=reserved_bytes+NEW.reserved_bytes-OLD.reserved_bytes WHERE owner=NEW.owner; END")
            db.execute("CREATE TRIGGER IF NOT EXISTS canvas_shell_request_usage_delete AFTER DELETE ON canvas_shell_host_requests BEGIN "
                "UPDATE canvas_shell_request_usage SET record_count=record_count-1,protected_bytes=protected_bytes-LENGTH(COALESCE(OLD.protected_intent,''))"
                "-LENGTH(COALESCE(OLD.protected_result,'')),reserved_bytes=reserved_bytes-OLD.reserved_bytes WHERE owner=OLD.owner; END")
            db.execute("CREATE TRIGGER IF NOT EXISTS canvas_shell_request_identity_immutable BEFORE UPDATE OF owner,project_id,request_key,fingerprint "
                "ON canvas_shell_host_requests WHEN NEW.owner<>OLD.owner OR NEW.project_id<>OLD.project_id OR NEW.request_key<>OLD.request_key OR NEW.fingerprint<>OLD.fingerprint "
                "BEGIN SELECT RAISE(ABORT,'host request identity is immutable'); END")
            db.execute("CREATE INDEX IF NOT EXISTS canvas_shell_request_retention_due ON canvas_shell_host_requests(owner,retired_at,retention_ack_at)")
            db.execute("INSERT INTO canvas_shell_request_retention_schema VALUES(1,1) ON CONFLICT(id) DO NOTHING")

    def retention_status(self):
        with closing(self.control.store.connect("shell")) as db:
            row = db.execute("SELECT * FROM canvas_shell_request_usage WHERE owner=?", (self.owner,)).fetchone()
        return {"record_count": row["record_count"] if row else 0,
            "protected_bytes": row["protected_bytes"] if row else 0,
            "reserved_bytes": row["reserved_bytes"] if row else 0,
            "max_records": self.retention_policy.max_records,
            "max_protected_bytes": self.retention_policy.max_protected_bytes,
            "retain_after_ack_seconds": self.retention_policy.retain_after_ack_seconds,
            "deduplication_keys_expire": False, "unresolved_payloads_expire": False}

    def acknowledge_terminal_input(self, db, project_id, request_key, fingerprint):
        """Host-only: caller must delete its exact pending selector in this transaction."""
        row = self._row(db, project_id, request_key)
        if row is None or not hmac.compare_digest(row["fingerprint"], fingerprint):
            raise ShellConflict("request_key belongs to another intent")
        original = _decode(row["protected_intent"]) if row["protected_intent"] else None
        result = _decode(row["protected_result"]) if row["protected_result"] else None
        if (not original or original.get("action") != "terminal_input" or not result
                or result.get("status") not in {"delivered", "admission_failed"}
                or not _resolved_result(row, result)):
            return False
        db.execute("UPDATE canvas_shell_host_requests SET retention_ack_at=COALESCE(retention_ack_at,?) "
            "WHERE owner=? AND project_id=? AND request_key=?", (time.time(), self.owner, project_id, request_key))
        return True

    def compact_acknowledged(self, project_id):
        """Retire acknowledged terminal payloads, retaining permanent protected receipts.

        Generic committed host responses are deliberately ineligible: an outer
        callback may have returned while an asynchronous operation is still live.
        """
        now = time.time()
        with self.lock, closing(self.control.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM canvas_shell_host_requests WHERE owner=? AND project_id=? "
                "AND retired_at IS NULL AND retention_ack_at IS NOT NULL AND retention_ack_at<=? "
                "ORDER BY retention_ack_at,request_key LIMIT ?", (self.owner, project_id,
                    now-self.retention_policy.retain_after_ack_seconds, self.retention_policy.compact_batch)).fetchall()
            pending_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_terminal_input_pending'").fetchone()
            retired = 0
            for row in rows:
                if pending_table and db.execute("SELECT 1 FROM canvas_terminal_input_pending WHERE owner=? AND project_id=? AND request_key=?",
                        (self.owner, project_id, row["request_key"])).fetchone():
                    continue
                if not row["protected_intent"] or not row["protected_result"]:
                    continue
                original, result = _decode(row["protected_intent"]), _decode(row["protected_result"])
                if (original.get("action") != "terminal_input" or result.get("status") not in {"delivered", "admission_failed"}
                        or not _resolved_result(row, result)):
                    continue
                scope = {name: original.get("payload", {}).get(name) for name in ("terminal_id", "input_target")}
                if not all(isinstance(value, str) and value for value in scope.values()):
                    continue
                summary = {name: result[name] for name in ("ok", "status", "phase", "delivery_stage", "bytes", "query_failed") if name in result}
                summary.update({"request_key": row["request_key"], **scope, "payload_retired": True,
                    "retired_at": now, "automatic_retry": False, "may_resend": False, "task_completion_verified": False,
                    "reason": "acknowledged input content retired; delivery receipt and deduplication key preserved"})
                intent = {"action": "terminal_input", "payload": scope, "payload_retired": True}
                protected_intent, protected_result = _encode(intent), _encode(summary)
                usage = db.execute("SELECT protected_bytes,reserved_bytes FROM canvas_shell_request_usage WHERE owner=?", (self.owner,)).fetchone()
                old_size = len(row["protected_intent"].encode("utf-8")) + len(row["protected_result"].encode("utf-8"))
                new_size = len(protected_intent.encode("utf-8")) + len(protected_result.encode("utf-8"))
                if usage["protected_bytes"] + usage["reserved_bytes"] - old_size - row["reserved_bytes"] + new_size > self.retention_policy.max_protected_bytes:
                    continue  # A pre-policy store can already exceed its budget.
                db.execute("UPDATE canvas_shell_host_requests SET protected_intent=?,protected_result=?,retired_at=?,reserved_bytes=0 "
                    "WHERE owner=? AND project_id=? AND request_key=?", (protected_intent, protected_result, now,
                        self.owner, project_id, row["request_key"]))
                retired += 1
        return {"retired": retired, "deleted_keys": 0, "automatic_retry": False}

    def inspect_retired_input(self, project_id, request_key, fingerprint, terminal_id):
        """Observe a retired receipt using its original selector, without command text."""
        with closing(self.control.store.connect("shell")) as db:
            row = self._row(db, project_id, request_key)
        if row is None or not hmac.compare_digest(row["fingerprint"], fingerprint):
            raise ShellConflict("request_key belongs to another intent")
        original = _decode(row["protected_intent"])
        if (not row["retired_at"] or original.get("action") != "terminal_input"
                or original.get("payload", {}).get("terminal_id") != terminal_id):
            raise PermissionError("retired receipt belongs to another terminal")
        result = _decode(row["protected_result"])
        return {"found": True, "resolved": True, "request_key": request_key, "journal_state": row["state"],
            "result": result, "payload_retired": True, "automatic_retry": False, "may_resend": False}

    def operation_id(self, project_id, request_key, purpose):
        value = json.dumps([self.owner, project_id, request_key, purpose], separators=(",", ":"))
        return "op-shell-" + hashlib.sha256(value.encode()).hexdigest()[:40]

    def _row(self, db, project_id, request_key):
        if not isinstance(project_id, str) or not 1 <= len(project_id) <= 256:
            raise ValueError("bounded host request project required")
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

    def bind_terminal_input_effect(self, project_id, request_key, fingerprint, reference):
        """Protect an exact daemon selector before dispatch, never a permission."""
        from .pty_input_effects import validate_reference
        reference = validate_reference(reference)
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, project_id, request_key)
            if (row is None or row['fingerprint'] != fingerprint or row['state'] != 'claimed'
                    or row['phase'] != 'before_admission'):
                raise ShellConflict('terminal input effect must bind before physical admission')
            original = _decode(row['protected_intent'])
            payload = original.get('payload', {})
            if (original.get('action') != 'terminal_input' or reference['workspace_id'] != project_id
                    or reference['terminal_id'] != payload.get('terminal_id')
                    or reference['payload_sha256'] != hashlib.sha256(payload['data'].encode('utf-8')).hexdigest()
                    or original.get('terminal_effect', reference) != reference):
                raise ShellConflict('physical input selector differs from protected intent')
            encoded = _encode({**original,'terminal_effect':reference})
            delta = len(encoded.encode('utf-8')) - len(row['protected_intent'].encode('utf-8'))
            usage = db.execute('SELECT * FROM canvas_shell_request_usage WHERE owner=?',(self.owner,)).fetchone()
            if usage['protected_bytes'] + usage['reserved_bytes'] + delta > self.retention_policy.max_protected_bytes:
                raise HostRequestCapacityError('physical input selector exceeds protected journal budget before admission')
            db.execute('UPDATE canvas_shell_host_requests SET protected_intent=? WHERE owner=? AND project_id=? AND request_key=?',
                (encoded,self.owner,project_id,request_key))

    def confirm_terminal_input_observation(self, project_id, request_key, fingerprint, reference, receipt):
        """Commit exact daemon delivery evidence without invoking any callback.

        The distinct state fences a late callback failure from replacing this
        definite observation with uncertainty. The receipt proves delivery only.
        """
        from .pty_input_effects import validate_reference
        reference = validate_reference(reference)
        if (not isinstance(receipt,dict) or any(receipt.get(k) != v for k,v in reference.items())
                or receipt.get('input_receipt_protocol_version') != 1
                or receipt.get('stage') != 'delivered_to_process'
                or receipt.get('automatic_retry') is not False or receipt.get('task_completion_verified') is not False):
            raise ShellConflict('exact physical input delivery receipt required')
        with closing(self.control.store.connect('shell')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db,project_id,request_key)
            if row is None or row['fingerprint'] != fingerprint:
                raise ShellConflict('physical input observation belongs to another request')
            original = _decode(row['protected_intent'])
            payload = original.get('payload',{})
            if (original.get('action') != 'terminal_input' or original.get('terminal_effect') != reference
                    or reference['workspace_id'] != project_id or reference['terminal_id'] != payload.get('terminal_id')):
                raise ShellConflict('physical input observation differs from protected selector')
            if row['state'] == 'observed_input':return True
            if row['phase'] != 'after_possible_effect' or row['state'] not in {'effect_possible','uncertain'}:
                return False
            result = {'ok':True,'status':'delivered','delivery_stage':'delivered_to_process',
                'request_key':request_key,'terminal_id':reference['terminal_id'],'input_target':payload['input_target'],
                'bytes':len(payload['data'].encode('utf-8')),'task_completion_verified':False,'automatic_retry':False,
                'physical_receipt':receipt,'observed':True}
            encoded = _encode(result)
            if len(encoded.encode('utf-8')) > self.retention_policy.result_reservation_bytes:
                raise HostRequestCapacityError('physical input observation exceeds admitted reservation')
            db.execute("UPDATE canvas_shell_host_requests SET state='observed_input',protected_result=?,reserved_bytes=?,updated_at=? "
                'WHERE owner=? AND project_id=? AND request_key=?',
                (encoded,_RETIREMENT_RESERVATION,time.time(),self.owner,project_id,request_key))
            return True

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
        self.compact_acknowledged(project_id)
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
                protected_intent = _encode({"action": action, "payload": payload})
                usage = db.execute("SELECT * FROM canvas_shell_request_usage WHERE owner=?", (self.owner,)).fetchone()
                policy = self.retention_policy
                if (usage and usage["record_count"] >= policy.max_records or
                        (usage["protected_bytes"] + usage["reserved_bytes"] if usage else 0)
                        + len(protected_intent.encode("utf-8")) + policy.result_reservation_bytes + _RETIREMENT_RESERVATION > policy.max_protected_bytes):
                    raise HostRequestCapacityError("protected request journal budget reached before admission; inspect and acknowledge existing receipts")
                now = time.time()
                db.execute("INSERT INTO canvas_shell_host_requests("
                    "owner,project_id,request_key,fingerprint,state,protected_result,created_at,updated_at,protected_intent,reserved_bytes) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (self.owner, project_id, request_key, fingerprint, "claimed", None, now, now,
                     protected_intent, policy.result_reservation_bytes + _RETIREMENT_RESERVATION))
        # No database transaction or global lock spans provider network I/O.
        try:
            result = callback()
            if not isinstance(result, dict):
                raise ValueError("host action returned an invalid projection")
            journal_state = result.get("status", "committed")
            if not isinstance(journal_state, str) or not 1 <= len(journal_state) <= 128:
                raise ValueError("host action returned an unbounded journal state")
            encoded_result = _encode(result)
            if len(encoded_result.encode("utf-8")) > self.retention_policy.result_reservation_bytes:
                raise ValueError("protected request result exceeds its admitted reservation")
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("UPDATE canvas_shell_host_requests SET state=?,protected_result=?,"
                    "reserved_bytes=?,updated_at=? WHERE owner=? AND project_id=? AND request_key=? AND state<>'observed_input'",
                    (journal_state, encoded_result, _RETIREMENT_RESERVATION, time.time(),
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
                        "protected_result=?,reserved_bytes=?,updated_at=? WHERE owner=? AND project_id=? AND request_key=? AND state<>'observed_input'",
                        (receipt["status"], phase, receipt["diagnosis"]["operation_id"],
                         _encode(receipt), _RETIREMENT_RESERVATION, time.time(), self.owner, project_id, request_key))
                else:
                    db.execute("UPDATE canvas_shell_host_requests SET state=?,protected_result=?,reserved_bytes=?,updated_at=? "
                        "WHERE owner=? AND project_id=? AND request_key=? AND phase IS NULL",
                        (receipt["status"], _encode(receipt), _RETIREMENT_RESERVATION, time.time(),
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
        return {"found": True, "resolved": _resolved_result(row, result),
                "request_key": request_key, "journal_state": row["state"],
                "result": result, "operation_id": operation_id,
                "payload_retired": bool(row["retired_at"]),
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
