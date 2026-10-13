"""Protected host request journal; all execution authority stays in Control Plane."""
from contextlib import closing
import hashlib
import json
import threading
import time

from sentra_core.conversations import _encode, _decode
from sentra_mcp.services.shell_coordinator import ShellConflict


class ShellHostRequests:
    def __init__(self, control, owner):
        self.control, self.owner = control, owner
        self.lock = threading.RLock()
        with closing(control.store.connect("shell")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS canvas_shell_host_requests("
                "owner TEXT NOT NULL,project_id TEXT NOT NULL,request_key TEXT NOT NULL,"
                "fingerprint TEXT NOT NULL,state TEXT NOT NULL,protected_result TEXT,"
                "created_at REAL NOT NULL,updated_at REAL NOT NULL,"
                "PRIMARY KEY(owner,project_id,request_key))")

    def operation_id(self, project_id, request_key, purpose):
        value = json.dumps([self.owner, project_id, request_key, purpose], separators=(",", ":"))
        return "op-shell-" + hashlib.sha256(value.encode()).hexdigest()[:40]

    def invoke(self, project_id, action, payload, request_key, callback):
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 200:
            raise ValueError("mutation requires a durable request_key")
        fingerprint = hashlib.sha256(json.dumps([action, payload], sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.lock:
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM canvas_shell_host_requests WHERE "
                    "owner=? AND project_id=? AND request_key=?",
                    (self.owner, project_id, request_key)).fetchone()
                if row:
                    if row["fingerprint"] != fingerprint:
                        raise ShellConflict("request_key belongs to another intent")
                    if row["protected_result"]:
                        return _decode(row["protected_result"])
                    return {"status": "uncertain", "request_key": request_key,
                        "receipt_id": None, "automatic_retry": False,
                        "reason": "request admitted; observe its outcome before resubmitting"}
                now = time.time()
                db.execute("INSERT INTO canvas_shell_host_requests VALUES(?,?,?,?,?,?,?,?)",
                    (self.owner, project_id, request_key, fingerprint, "claimed", None, now, now))
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
        except BaseException:
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("UPDATE canvas_shell_host_requests SET state='uncertain',updated_at=? "
                    "WHERE owner=? AND project_id=? AND request_key=?",
                    (time.time(), self.owner, project_id, request_key))
            raise
