"""Durable multi-device registry, pairing, leases and chunked remote results."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sentra_version import CAPABILITY_VERSION, PROTOCOL_VERSION, SERVER_VERSION

from .models import EXEC_PHASES, PRE_EXEC_PHASES, TERMINAL_STATES, LeasedRemoteJob


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _error_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:4000]
    return _json(value)[:4000]


class RemoteAgentCompatibilityError(RuntimeError):
    code = "REMOTE_AGENT_STALE"
    category = "contract"
    retryable = False

    def __init__(self, reasons: list[dict[str, Any]]) -> None:
        self.reasons = reasons
        self.details = {"reasons": reasons}
        if reasons:
            self.code = str(reasons[0].get("code") or self.code)
        message = "; ".join(str(item.get("message") or item.get("code")) for item in reasons)
        super().__init__(message or "remote agent identity is incompatible")


class RemoteStore:
    """SQLite state for SENTRA Cloud/Relay.

    Device secrets are never persisted in plaintext. A leased job is requeued only
    when the agent never reported an execution phase. Once execution may have
    started, lease loss becomes UNCERTAIN and requires operator reconciliation.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        clock=time.time,
        online_window_s: float = 20.0,
        lease_window_s: float = 20.0,
        max_requeues: int = 1,
        max_result_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.online_window_s = float(online_window_s)
        self.lease_window_s = float(lease_window_s)
        self.max_requeues = int(max_requeues)
        self.max_result_bytes = int(max_result_bytes)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self._schema()

    def _schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices(
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OFFLINE',
                last_seen REAL NOT NULL DEFAULT 0,
                token_hash TEXT NOT NULL,
                token_created REAL NOT NULL,
                token_expires REAL NOT NULL,
                previous_token_hash TEXT NOT NULL DEFAULT '',
                previous_token_expires REAL NOT NULL DEFAULT 0,
                revoked INTEGER NOT NULL DEFAULT 0,
                allowed_tools TEXT NOT NULL,
                capabilities TEXT NOT NULL DEFAULT '{}',
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);

            CREATE TABLE IF NOT EXISTS pairings(
                code_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                allowed_tools TEXT NOT NULL,
                expires REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                tool TEXT NOT NULL,
                arguments TEXT NOT NULL,
                run_id TEXT,
                operation_id TEXT,
                idempotency_key TEXT,
                contract_required INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL,
                lease_hash TEXT NOT NULL DEFAULT '',
                lease_until REAL NOT NULL DEFAULT 0,
                deadline REAL NOT NULL,
                phase TEXT NOT NULL DEFAULT '',
                may_have_started INTEGER NOT NULL DEFAULT 0,
                requeues INTEGER NOT NULL DEFAULT 0,
                result TEXT,
                error TEXT,
                created REAL NOT NULL,
                updated REAL NOT NULL,
                FOREIGN KEY(device_id) REFERENCES devices(id)
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_device_state ON jobs(device_id,state,created);

            CREATE TABLE IF NOT EXISTS result_chunks(
                job_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                data BLOB NOT NULL,
                PRIMARY KEY(job_id,chunk_index),
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            """
        )
        columns = {str(row[1]) for row in self.db.execute("PRAGMA table_info(devices)").fetchall()}
        if "previous_token_hash" not in columns:
            self.db.execute("ALTER TABLE devices ADD COLUMN previous_token_hash TEXT NOT NULL DEFAULT ''")
        if "previous_token_expires" not in columns:
            self.db.execute("ALTER TABLE devices ADD COLUMN previous_token_expires REAL NOT NULL DEFAULT 0")
        job_columns = {
            str(row[1])
            for row in self.db.execute("PRAGMA table_info(jobs)").fetchall()
        }
        for column in ("run_id", "operation_id", "idempotency_key"):
            if column not in job_columns:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
        if "contract_required" not in job_columns:
            self.db.execute(
                "ALTER TABLE jobs ADD COLUMN contract_required INTEGER NOT NULL DEFAULT 0"
            )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_operation ON jobs(operation_id)"
        )
        self.db.commit()

    def close(self) -> None:
        with self.lock:
            self.db.close()

    @staticmethod
    def _normalize_tools(tools: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        clean: list[str] = []
        for tool in tools:
            item = str(tool).strip()
            if not item or len(item) > 128:
                raise ValueError("invalid tool permission")
            if not all(ch.isalnum() or ch in "._:-*" for ch in item):
                raise ValueError("invalid tool permission")
            if item not in clean:
                clean.append(item)
        if not clean:
            raise ValueError("at least one allowed tool is required")
        return tuple(clean)

    @staticmethod
    def _tool_allowed(tool: str, permissions: tuple[str, ...]) -> bool:
        for rule in permissions:
            if rule == "*":
                return True
            if rule.endswith("*") and tool.startswith(rule[:-1]):
                return True
            if secrets.compare_digest(rule, tool):
                return True
        return False

    def create_pairing(
        self,
        user_id: str,
        name: str,
        platform: str,
        allowed_tools: list[str] | tuple[str, ...],
        *,
        ttl_s: int = 300,
    ) -> dict[str, Any]:
        if not user_id.strip() or not name.strip() or len(name) > 120:
            raise ValueError("user_id and device name are required")
        if ttl_s < 30 or ttl_s > 1800:
            raise ValueError("pairing ttl must be between 30 and 1800 seconds")
        tools = self._normalize_tools(allowed_tools)
        code = "-".join(
            (
                secrets.token_hex(3).upper(),
                secrets.token_hex(3).upper(),
                secrets.token_hex(3).upper(),
            )
        )
        now = self.clock()
        with self.lock:
            self.db.execute("DELETE FROM pairings WHERE expires<=? OR used=1", (now,))
            active = self.db.execute("SELECT count(*) FROM pairings WHERE user_id=? AND used=0 AND expires>?", (user_id, now)).fetchone()[0]
            if active >= 100:
                raise ValueError("too many active pairing requests")
            self.db.execute(
                "INSERT INTO pairings(code_hash,user_id,name,platform,allowed_tools,expires,used,created) "
                "VALUES(?,?,?,?,?,?,0,?)",
                (_hash_secret(code), user_id, name.strip(), platform.strip() or "unknown", _json(tools), now + ttl_s, now),
            )
            self.db.commit()
        return {"pairing_code": code, "expires_at": now + ttl_s, "device_name": name.strip()}

    def pair_device(self, code: str, *, agent_name: str | None = None) -> dict[str, Any]:
        now = self.clock()
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM pairings WHERE code_hash=? AND used=0 AND expires>?",
                (_hash_secret(code.strip().upper()), now),
            ).fetchone()
            if row is None:
                raise PermissionError("invalid or expired pairing code")
            device_id = str(uuid.uuid4())
            token = secrets.token_urlsafe(48)
            expires = now + 30 * 24 * 3600
            name = (agent_name or row["name"]).strip()[:120]
            self.db.execute(
                "INSERT INTO devices(id,user_id,name,platform,status,last_seen,token_hash,token_created,"
                "token_expires,revoked,allowed_tools,capabilities,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,0,?,'{}',?,?)",
                (
                    device_id,
                    row["user_id"],
                    name,
                    row["platform"],
                    "OFFLINE",
                    0,
                    _hash_secret(token),
                    now,
                    expires,
                    row["allowed_tools"],
                    now,
                    now,
                ),
            )
            self.db.execute("UPDATE pairings SET used=1 WHERE code_hash=?", (row["code_hash"],))
            self.db.commit()
        return {
            "device_id": device_id,
            "device_token": token,
            "token_expires_at": expires,
            "name": name,
            "allowed_tools": json.loads(row["allowed_tools"]),
        }

    def _device_row(self, device_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("device not found")
        return row

    def authenticate_device(self, device_id: str, token: str) -> sqlite3.Row:
        now = self.clock()
        digest = _hash_secret(token)
        with self.lock:
            row = self._device_row(device_id)
            if row["revoked"] or row["token_expires"] <= now:
                raise PermissionError("device credential is revoked or expired")
            current_ok = secrets.compare_digest(row["token_hash"], digest)
            previous_ok = (
                bool(row["previous_token_hash"])
                and row["previous_token_expires"] > now
                and secrets.compare_digest(row["previous_token_hash"], digest)
            )
            if not (current_ok or previous_ok):
                raise PermissionError("invalid device credential")
            return row

    @staticmethod
    def agent_compatibility(capabilities: dict[str, Any] | None) -> dict[str, Any]:
        caps = dict(capabilities or {})
        sentra = caps.get("sentra")
        reasons: list[dict[str, Any]] = []
        if not isinstance(sentra, dict):
            return {
                "compatible": False,
                "reasons": [{
                    "code": "REMOTE_AGENT_STALE",
                    "field": "sentra",
                    "message": "remote agent did not publish a SENTRA contract manifest",
                }],
                "server": None,
                "contract": None,
            }

        server = sentra.get("server")
        contract = sentra.get("contract")
        advertised = sentra.get("capabilities")
        if not isinstance(server, dict):
            reasons.append({
                "code": "REMOTE_AGENT_STALE",
                "field": "sentra.server",
                "message": "remote agent build identity is missing",
            })
            server = {}
        if not isinstance(contract, dict):
            reasons.append({
                "code": "SCHEMA_MISMATCH",
                "field": "sentra.contract",
                "message": "remote agent live schema identity is missing",
            })
            contract = {}

        comparisons = (
            ("version", SERVER_VERSION, "REMOTE_AGENT_STALE"),
            ("protocol_version", PROTOCOL_VERSION, "PROTOCOL_MISMATCH"),
            ("capability_version", CAPABILITY_VERSION, "CAPABILITY_MISMATCH"),
        )
        for field, expected, code in comparisons:
            actual = str(server.get(field) or "")
            if actual != expected:
                reasons.append({
                    "code": code,
                    "field": f"sentra.server.{field}",
                    "expected": expected,
                    "actual": actual or None,
                    "message": f"remote agent {field} is incompatible",
                })

        build_id = str(server.get("build_id") or "")
        fingerprint = str(server.get("fingerprint") or "")
        source_hash = str(server.get("source_hash") or "")
        executable_hash = str(server.get("executable_sha256") or "")
        if not build_id or not fingerprint:
            reasons.append({
                "code": "REMOTE_AGENT_STALE",
                "field": "sentra.server",
                "message": "remote agent build identity is incomplete",
            })
        if not source_hash and not executable_hash:
            reasons.append({
                "code": "REMOTE_AGENT_STALE",
                "field": "sentra.server",
                "message": "remote agent cannot prove source or executable identity",
            })

        schema_hash = str(contract.get("schema_hash") or "")
        if len(schema_hash) != 64 or any(
            ch not in "0123456789abcdefABCDEF" for ch in schema_hash
        ):
            reasons.append({
                "code": "SCHEMA_MISMATCH",
                "field": "sentra.contract.schema_hash",
                "message": "remote agent did not publish a valid live tool schema hash",
            })
        tool_names = contract.get("tool_names")
        if not isinstance(tool_names, list) or not tool_names:
            reasons.append({
                "code": "SCHEMA_MISMATCH",
                "field": "sentra.contract.tool_names",
                "message": "remote agent live tool inventory is missing",
            })
        if not isinstance(advertised, dict):
            reasons.append({
                "code": "CAPABILITY_MISSING",
                "field": "sentra.capabilities",
                "message": "remote agent capability manifest is missing",
            })

        return {
            "compatible": not reasons,
            "reasons": reasons,
            "server": server,
            "contract": contract,
            "capabilities": advertised if isinstance(advertised, dict) else None,
        }

    def heartbeat(self, device_id: str, token: str, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
        self.authenticate_device(device_id, token)
        now = self.clock()
        caps = dict(capabilities or {})
        raw = _json(caps)
        if len(raw.encode("utf-8")) > 64 * 1024:
            raise ValueError("capabilities payload too large")
        with self.lock:
            self.db.execute(
                "UPDATE devices SET status='ONLINE',last_seen=?,capabilities=?,updated=? WHERE id=?",
                (now, raw, now, device_id),
            )
            self.db.commit()
        return {
            "ok": True,
            "server_time": now,
            "compatibility": self.agent_compatibility(caps),
        }

    def _public_device(self, row: sqlite3.Row) -> dict[str, Any]:
        now = self.clock()
        online = (
            not row["revoked"]
            and row["last_seen"] > 0
            and now - row["last_seen"] <= self.online_window_s
        )
        capabilities = json.loads(row["capabilities"] or "{}")
        return {
            "device_id": row["id"],
            "name": row["name"],
            "platform": row["platform"],
            "status": "ONLINE" if online else ("REVOKED" if row["revoked"] else "OFFLINE"),
            "last_seen": row["last_seen"],
            "token_expires_at": row["token_expires"],
            "allowed_tools": json.loads(row["allowed_tools"]),
            "capabilities": capabilities,
            "compatibility": self.agent_compatibility(capabilities),
        }

    def list_devices(self, user_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM devices WHERE user_id=? ORDER BY created", (user_id,)).fetchall()
            return [self._public_device(row) for row in rows]

    def get_device(self, user_id: str, device_id: str) -> dict[str, Any]:
        with self.lock:
            row = self._device_row(device_id)
            if row["user_id"] != user_id:
                raise PermissionError("device belongs to another user")
            return self._public_device(row)

    def set_device_tools(self, user_id: str, device_id: str, tools: list[str] | tuple[str, ...]) -> dict[str, Any]:
        normalized = self._normalize_tools(tools)
        now = self.clock()
        with self.lock:
            row = self._device_row(device_id)
            if row["user_id"] != user_id:
                raise PermissionError("device belongs to another user")
            self.db.execute("UPDATE devices SET allowed_tools=?,updated=? WHERE id=?", (_json(normalized), now, device_id))
            self.db.commit()
            return self.get_device(user_id, device_id)

    def revoke_device(self, user_id: str, device_id: str) -> None:
        now = self.clock()
        with self.lock:
            row = self._device_row(device_id)
            if row["user_id"] != user_id:
                raise PermissionError("device belongs to another user")
            self.db.execute(
                "UPDATE devices SET revoked=1,status='REVOKED',token_hash=?,previous_token_hash='',"
                "previous_token_expires=0,updated=? WHERE id=?",
                (_hash_secret(secrets.token_urlsafe(48)), now, device_id),
            )
            self.db.execute(
                "UPDATE jobs SET state='CANCELLED',error='device revoked',updated=? "
                "WHERE device_id=? AND state='QUEUED'",
                (now, device_id),
            )
            self.db.commit()

    def rotate_device_token(self, device_id: str, old_token: str) -> dict[str, Any]:
        row = self.authenticate_device(device_id, old_token)
        token = secrets.token_urlsafe(48)
        now = self.clock()
        expires = now + 30 * 24 * 3600
        grace_expires = now + 120
        with self.lock:
            self.db.execute(
                "UPDATE devices SET previous_token_hash=?,previous_token_expires=?,token_hash=?,"
                "token_created=?,token_expires=?,updated=? WHERE id=?",
                (row["token_hash"], grace_expires, _hash_secret(token), now, expires, now, device_id),
            )
            self.db.commit()
        return {"device_token": token, "token_expires_at": expires, "previous_token_valid_until": grace_expires}

    def _expire_jobs(self) -> None:
        now = self.clock()
        rows = self.db.execute(
            "SELECT * FROM jobs WHERE state IN ('QUEUED','LEASED') AND "
            "(deadline<=? OR (state='LEASED' AND lease_until<=?))",
            (now, now),
        ).fetchall()
        for row in rows:
            if row["deadline"] <= now:
                state = "UNCERTAIN" if row["may_have_started"] else "FAILED"
                error = (
                    "deadline exceeded after execution may have started; reconcile before retry"
                    if state == "UNCERTAIN"
                    else "job deadline exceeded before execution"
                )
                self.db.execute(
                    "UPDATE jobs SET state=?,error=?,updated=? WHERE id=?",
                    (state, error, now, row["id"]),
                )
                continue
            if row["state"] == "LEASED":
                if row["may_have_started"] or row["phase"] in EXEC_PHASES:
                    self.db.execute(
                        "UPDATE jobs SET state='UNCERTAIN',error=?,updated=? WHERE id=?",
                        ("agent lost after execution may have started; not automatically replayed", now, row["id"]),
                    )
                elif row["phase"] in PRE_EXEC_PHASES and row["requeues"] < self.max_requeues:
                    self.db.execute(
                        "UPDATE jobs SET state='QUEUED',lease_hash='',lease_until=0,phase='',"
                        "requeues=requeues+1,updated=? WHERE id=?",
                        (now, row["id"]),
                    )
                else:
                    self.db.execute(
                        "UPDATE jobs SET state='FAILED',error=?,updated=? WHERE id=?",
                        ("agent lease expired without safe replay evidence", now, row["id"]),
                    )
        self.db.commit()

    def submit_job(
        self,
        user_id: str,
        device_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        timeout_s: int = 180,
        run_id: str | None = None,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
        require_compatible_agent: bool = False,
    ) -> str:
        if timeout_s < 5 or timeout_s > 3600:
            raise ValueError("remote timeout must be between 5 and 3600 seconds")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        raw_args = _json(arguments)
        if len(raw_args.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("remote arguments too large")
        now = self.clock()
        with self.lock:
            self._expire_jobs()
            row = self._device_row(device_id)
            if row["user_id"] != user_id:
                raise PermissionError("device belongs to another user")
            if row["revoked"]:
                raise PermissionError("device is revoked")
            if require_compatible_agent:
                compatibility = self.agent_compatibility(
                    json.loads(row["capabilities"] or "{}")
                )
                if not compatibility["compatible"]:
                    raise RemoteAgentCompatibilityError(
                        list(compatibility["reasons"])
                    )
            permissions = tuple(json.loads(row["allowed_tools"]))
            if not self._tool_allowed(tool, permissions):
                raise PermissionError("tool is not authorized for this device")
            job_id = str(uuid.uuid4())
            self.db.execute(
                "INSERT INTO jobs(id,user_id,device_id,tool,arguments,run_id,operation_id,"
                "idempotency_key,contract_required,state,deadline,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?, 'QUEUED',?,?,?)",
                (
                    job_id, user_id, device_id, tool, raw_args,
                    run_id, operation_id, idempotency_key,
                    1 if require_compatible_agent else 0,
                    now + timeout_s, now, now,
                ),
            )
            self.db.commit()
            return job_id

    def poll_job(self, device_id: str, token: str) -> LeasedRemoteJob | None:
        device = self.authenticate_device(device_id, token)
        compatibility = self.agent_compatibility(
            json.loads(device["capabilities"] or "{}")
        )
        now = self.clock()
        with self.lock:
            self._expire_jobs()
            active = self.db.execute(
                "SELECT id FROM jobs WHERE device_id=? AND state='LEASED'", (device_id,)
            ).fetchone()
            if active:
                return None
            row = self.db.execute(
                "SELECT * FROM jobs WHERE device_id=? AND state='QUEUED' ORDER BY created LIMIT 1",
                (device_id,),
            ).fetchone()
            if row is None:
                return None
            if int(row["contract_required"] or 0) and not compatibility["compatible"]:
                return None
            lease = secrets.token_urlsafe(32)
            until = min(row["deadline"], now + self.lease_window_s)
            self.db.execute(
                "UPDATE jobs SET state='LEASED',lease_hash=?,lease_until=?,phase='leased',updated=? WHERE id=?",
                (_hash_secret(lease), until, now, row["id"]),
            )
            self.db.commit()
            return LeasedRemoteJob(
                job_id=row["id"],
                tool=row["tool"],
                arguments=json.loads(row["arguments"]),
                lease_token=lease,
                deadline=row["deadline"],
            )

    def _leased_row(self, device_id: str, token: str, job_id: str, lease: str) -> sqlite3.Row:
        self.authenticate_device(device_id, token)
        row = self.db.execute("SELECT * FROM jobs WHERE id=? AND device_id=?", (job_id, device_id)).fetchone()
        if row is None or row["state"] != "LEASED":
            raise PermissionError("job is not leased to this device")
        if not secrets.compare_digest(row["lease_hash"], _hash_secret(lease)):
            raise PermissionError("stale or foreign lease")
        return row

    def progress(self, device_id: str, token: str, job_id: str, lease: str, phase: str) -> dict[str, Any]:
        if phase not in PRE_EXEC_PHASES | EXEC_PHASES:
            raise ValueError("invalid remote execution phase")
        now = self.clock()
        with self.lock:
            row = self._leased_row(device_id, token, job_id, lease)
            may_started = int(bool(row["may_have_started"] or phase in EXEC_PHASES))
            until = min(row["deadline"], now + self.lease_window_s)
            self.db.execute(
                "UPDATE jobs SET phase=?,may_have_started=?,lease_until=?,updated=? WHERE id=?",
                (phase, may_started, until, now, job_id),
            )
            self.db.commit()
            return {"lease_until": until, "deadline": row["deadline"]}

    def complete_job(
        self,
        device_id: str,
        token: str,
        job_id: str,
        lease: str,
        result: dict[str, Any],
        *,
        failed: bool = False,
    ) -> None:
        raw = _json(result)
        if len(raw.encode("utf-8")) > self.max_result_bytes:
            raise ValueError("result too large; use chunk upload")
        now = self.clock()
        with self.lock:
            self._leased_row(device_id, token, job_id, lease)
            self.db.execute(
                "UPDATE jobs SET state=?,result=?,error=?,phase='finalizing',updated=? WHERE id=?",
                ("FAILED" if failed else "COMPLETED", raw, _error_text(result.get("error")) if failed else None, now, job_id),
            )
            self.db.commit()

    def put_result_chunk(
        self,
        device_id: str,
        token: str,
        job_id: str,
        lease: str,
        index: int,
        data: bytes,
        sha256: str,
    ) -> None:
        if index < 0 or index > 65535 or len(data) > 1024 * 1024:
            raise ValueError("invalid result chunk")
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError("result chunk hash mismatch")
        with self.lock:
            self._leased_row(device_id, token, job_id, lease)
            total = self.db.execute(
                "SELECT COALESCE(SUM(length(data)),0) FROM result_chunks WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            if total + len(data) > self.max_result_bytes:
                raise ValueError("chunked result exceeds configured maximum")
            self.db.execute(
                "INSERT OR REPLACE INTO result_chunks(job_id,chunk_index,sha256,data) VALUES(?,?,?,?)",
                (job_id, index, sha256, data),
            )
            self.db.commit()

    def finalize_chunks(
        self,
        device_id: str,
        token: str,
        job_id: str,
        lease: str,
        chunks: int,
        digest: str,
        *,
        failed: bool = False,
    ) -> None:
        if chunks < 1:
            raise ValueError("chunk count must be positive")
        now = self.clock()
        with self.lock:
            self._leased_row(device_id, token, job_id, lease)
            rows = self.db.execute(
                "SELECT chunk_index,data FROM result_chunks WHERE job_id=? ORDER BY chunk_index", (job_id,)
            ).fetchall()
            if len(rows) != chunks or [row["chunk_index"] for row in rows] != list(range(chunks)):
                raise ValueError("result chunks are incomplete")
            raw = b"".join(bytes(row["data"]) for row in rows)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("final result digest mismatch")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("chunked result payload must be a JSON object")
            self.db.execute(
                "UPDATE jobs SET state=?,result=?,error=?,phase='finalizing',updated=? WHERE id=?",
                (
                    "FAILED" if failed else "COMPLETED",
                    _json(payload),
                    _error_text(payload.get("error")) if failed else None,
                    now,
                    job_id,
                ),
            )
            self.db.execute("DELETE FROM result_chunks WHERE job_id=?", (job_id,))
            self.db.commit()

    def job_result(self, user_id: str, job_id: str) -> dict[str, Any]:
        with self.lock:
            self._expire_jobs()
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise FileNotFoundError("remote job not found")
            if row["user_id"] != user_id:
                raise PermissionError("remote job belongs to another user")
            return {
                "job_id": row["id"],
                "run_id": row["run_id"],
                "operation_id": row["operation_id"],
                "idempotency_key": row["idempotency_key"],
                "contract_required": bool(row["contract_required"]),
                "device_id": row["device_id"],
                "tool": row["tool"],
                "state": row["state"],
                "phase": row["phase"],
                "requeues": row["requeues"],
                "result": json.loads(row["result"]) if row["result"] else None,
                "error": row["error"],
                "created": row["created"],
                "updated": row["updated"],
                "deadline": row["deadline"],
            }

    def job_for_operation(
        self,
        user_id: str,
        operation_id: str,
    ) -> dict[str, Any] | None:
        with self.lock:
            self._expire_jobs()
            row = self.db.execute(
                "SELECT id FROM jobs WHERE user_id=? AND operation_id=? "
                "ORDER BY created DESC LIMIT 1",
                (user_id, operation_id),
            ).fetchone()
        if row is None:
            return None
        return self.job_result(user_id, str(row["id"]))

    def cancel_job(self, user_id: str, job_id: str) -> None:
        now = self.clock()
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["user_id"] != user_id:
                raise FileNotFoundError("remote job not found")
            if row["state"] in TERMINAL_STATES:
                return
            if row["state"] == "LEASED" and row["may_have_started"]:
                state = "UNCERTAIN"
                error = "cancel requested after execution may have started"
            else:
                state = "CANCELLED"
                error = "cancelled by operator"
            self.db.execute("UPDATE jobs SET state=?,error=?,updated=? WHERE id=?", (state, error, now, job_id))
            self.db.commit()
