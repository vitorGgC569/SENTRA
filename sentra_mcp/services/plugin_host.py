"""Out-of-process JSON-RPC plugin workers using SENTRA managed processes."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore


PLUGIN_PROTOCOL_VERSION = 1


class PluginProtocolError(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class PluginWorkerHost:
    """Capability-gated plugin worker host.

    Processes are never spawned directly.  The injected ProcessService remains
    the execution/workspace/sandbox authority.
    """

    def __init__(
        self,
        state_root: Path | str,
        *,
        processes: Any,
        governance: Any,
        authorization: Any,
        store: ControlPlaneStore | None = None,
        clock=time.time,
    ) -> None:
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.path = self.store.path_for("plugin_worker")
        self.processes = processes
        self.governance = governance
        self.authorization = authorization
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS plugin_workers(
                    plugin_worker_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    operation_id TEXT,
                    state TEXT NOT NULL,
                    protocol_version INTEGER NOT NULL,
                    methods_json TEXT NOT NULL,
                    method_capabilities_json TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    stdout_offset INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(owner,plugin_id,session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_plugin_workers_owner_plugin
                    ON plugin_workers(owner,plugin_id,state);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return self.store.connect("plugin_worker")

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["methods"] = _load(item.pop("methods_json"), [])
        item["method_capabilities"] = _load(item.pop("method_capabilities_json"), {})
        item["capabilities"] = _load(item.pop("capabilities_json"), [])
        return item

    def info(self, plugin_worker_id: str, owner: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM plugin_workers WHERE plugin_worker_id=? AND owner=?",
                (plugin_worker_id, owner),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("plugin worker not found")
        return self._row(row)

    @staticmethod
    def _method_descriptors(value: Any) -> tuple[list[str], dict[str, str]]:
        if not isinstance(value, list) or len(value) > 1000:
            raise PluginProtocolError("plugin handshake methods must be a bounded list")
        names: list[str] = []
        caps: dict[str, str] = {}
        for raw in value:
            if isinstance(raw, str):
                name = raw.strip()
                capability = ""
            elif isinstance(raw, dict):
                name = str(raw.get("name") or "").strip()
                capability = str(raw.get("capability") or "").strip()
            else:
                raise PluginProtocolError("plugin method descriptor is invalid")
            if not name or len(name) > 256:
                raise PluginProtocolError("plugin method name is invalid")
            if name in names:
                raise PluginProtocolError("plugin handshake contains duplicate methods")
            names.append(name)
            if capability:
                caps[name] = capability
        return names, caps

    def _read_response(
        self,
        session_id: str,
        owner: str,
        request_id: str,
        *,
        offset: int,
        timeout_s: float,
    ) -> tuple[dict[str, Any], int]:
        deadline = self.clock() + max(0.1, min(float(timeout_s), 30.0))
        cursor = max(0, int(offset))
        pending = ""
        while self.clock() < deadline:
            output = self.processes.read_process_output(
                session_id, owner, offset=cursor, length=262144
            )
            chunk = str(output.get("stdout") or "")
            if chunk:
                cursor += len(chunk.encode("utf-8"))
                pending += chunk
                while "\n" in pending:
                    raw, pending = pending.split("\n", 1)
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    if str(message.get("id") or "") != request_id:
                        continue
                    if "error" in message:
                        raise PluginProtocolError(
                            "plugin RPC error: " + str(message.get("error"))[:2000]
                        )
                    result = message.get("result")
                    if not isinstance(result, dict):
                        raise PluginProtocolError("plugin RPC result must be an object")
                    return result, cursor
            if not bool(output.get("running", True)) and not chunk:
                raise PluginProtocolError(
                    "plugin worker exited before returning an RPC response"
                )
            time.sleep(0.02)
        raise TimeoutError("plugin worker RPC response timed out")

    def _request(
        self,
        worker: dict[str, Any],
        owner: str,
        *,
        method: str,
        params: dict[str, Any],
        timeout_s: float = 5.0,
    ) -> dict[str, Any]:
        request_id = "rpc-" + uuid.uuid4().hex
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        raw = _json(payload)
        if len(raw.encode("utf-8")) > 1_000_000:
            raise ValueError("plugin RPC request exceeds 1 MiB")
        self.processes.interact_with_process(
            worker["session_id"], owner, raw + "\n"
        )
        result, cursor = self._read_response(
            worker["session_id"],
            owner,
            request_id,
            offset=int(worker.get("stdout_offset") or 0),
            timeout_s=timeout_s,
        )
        with self._connect() as db:
            db.execute(
                "UPDATE plugin_workers SET stdout_offset=?,updated_at=? "
                "WHERE plugin_worker_id=? AND owner=?",
                (cursor, self.clock(), worker["plugin_worker_id"], owner),
            )
        return result

    def start(
        self,
        owner: str,
        *,
        plugin_id: str,
        command: str | Sequence[str] | None = None,
        workspace: str | None = None,
        mode: str | None = None,
        run_id: str | None = None,
        timeout_s: float = 5.0,
        narrowed_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        plugin = self.governance.plugin_info(plugin_id, owner)
        manifest = dict(plugin.get("manifest") or {})
        worker_manifest = manifest.get("worker") or {}
        if not isinstance(worker_manifest, dict):
            raise ValueError("plugin manifest worker must be an object")
        declared_command = worker_manifest.get("command")
        if not declared_command:
            raise ValueError("plugin worker command must be declared in the manifest")
        if command is not None and _json(command) != _json(declared_command):
            raise PermissionError(
                "plugin worker command must match the registered manifest"
            )
        effective_command = declared_command
        process = self.processes.start_process(
            effective_command,
            owner,
            timeout=None,
            workspace=workspace,
            mode=mode,
            run_id=run_id,
            idempotency_key=f"plugin-worker:{plugin_id}",
            cleanup_policy="terminate_on_run_end",
        )
        session_id = str(process.get("session_id") or "")
        if not session_id:
            raise RuntimeError("managed plugin process did not return a session_id")
        worker_id = "plugin-worker-" + uuid.uuid4().hex
        now = self.clock()
        with self._connect() as db:
            db.execute(
                "INSERT INTO plugin_workers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    worker_id,
                    owner,
                    plugin_id,
                    session_id,
                    process.get("run_id"),
                    process.get("operation_id"),
                    "HANDSHAKING",
                    PLUGIN_PROTOCOL_VERSION,
                    "[]",
                    "{}",
                    "[]",
                    0,
                    now,
                    now,
                ),
            )
        worker = self.info(worker_id, owner)
        try:
            result = self._request(
                worker,
                owner,
                method="sentra.handshake",
                params={
                    "protocol_version": PLUGIN_PROTOCOL_VERSION,
                    "plugin_id": plugin_id,
                    "name": plugin["name"],
                    "version": plugin["version"],
                },
                timeout_s=timeout_s,
            )
            protocol = int(result.get("protocol_version") or 0)
            if protocol != PLUGIN_PROTOCOL_VERSION:
                raise PluginProtocolError(
                    f"plugin protocol mismatch: {protocol} != {PLUGIN_PROTOCOL_VERSION}"
                )
            if result.get("name") and str(result["name"]) != plugin["name"]:
                raise PluginProtocolError("plugin handshake name mismatch")
            if result.get("version") and str(result["version"]) != plugin["version"]:
                raise PluginProtocolError("plugin handshake version mismatch")
            methods, method_caps = self._method_descriptors(result.get("methods") or [])
            live_caps = [
                str(item).strip()
                for item in (result.get("capabilities") or [])
                if str(item).strip()
            ]
            verified = self.governance.update_plugin_verification(
                plugin_id,
                owner,
                verified_methods=methods,
                live_capabilities=live_caps,
                narrowed_capabilities=narrowed_capabilities,
                state="VERIFIED",
                metadata={
                    "worker_protocol_version": protocol,
                    "last_worker_session_id": session_id,
                },
            )
            with self._connect() as db:
                db.execute(
                    "UPDATE plugin_workers SET state='READY',methods_json=?,"
                    "method_capabilities_json=?,capabilities_json=?,updated_at=? "
                    "WHERE plugin_worker_id=? AND owner=?",
                    (
                        _json(methods),
                        _json(method_caps),
                        _json(live_caps),
                        self.clock(),
                        worker_id,
                        owner,
                    ),
                )
            return {
                "worker": self.info(worker_id, owner),
                "plugin": verified,
                "process": process,
            }
        except Exception:
            with self._connect() as db:
                db.execute(
                    "UPDATE plugin_workers SET state='FAILED',updated_at=? "
                    "WHERE plugin_worker_id=? AND owner=?",
                    (self.clock(), worker_id, owner),
                )
            try:
                self.processes.terminate_session(session_id, owner)
            except Exception:
                pass
            raise

    def call(
        self,
        plugin_worker_id: str,
        owner: str,
        *,
        method: str,
        params: dict[str, Any] | None = None,
        scope_type: str = "instance",
        scope_id: str | None = None,
        ancestors: dict[str, list[str]] | None = None,
        policy_context: dict[str, Any] | None = None,
        timeout_s: float = 10.0,
    ) -> dict[str, Any]:
        worker = self.info(plugin_worker_id, owner)
        if worker["state"] != "READY":
            raise RuntimeError("plugin worker is not READY")
        method = str(method or "").strip()
        if method not in set(worker["methods"]):
            raise PermissionError("plugin method was not verified by live handshake")
        plugin = self.governance.plugin_info(worker["plugin_id"], owner)
        method_capability = str(
            (worker.get("method_capabilities") or {}).get(method) or ""
        ).strip()
        if not method_capability:
            raise PermissionError(
                "plugin method did not declare a capability during live handshake"
            )
        if method_capability not in set(plugin["effective_capabilities"]):
            raise PermissionError(
                "plugin method capability is not effective after host narrowing"
            )
        self.authorization.require(
            owner,
            principal_type="plugin",
            principal_id=plugin["plugin_id"],
            capability="plugin." + method_capability,
            scope_type=scope_type,
            scope_id=scope_id,
            ancestors=ancestors,
            context=dict(policy_context or {}),
        )
        result = self._request(
            worker,
            owner,
            method=method,
            params=dict(params or {}),
            timeout_s=timeout_s,
        )
        self.governance.activity(
            owner,
            "plugin.call",
            "ok",
            actor_type="plugin",
            actor_id=plugin["plugin_id"],
            payload={
                "plugin_worker_id": plugin_worker_id,
                "method": method,
                "capability": method_capability,
            },
        )
        return result

    def stop(self, plugin_worker_id: str, owner: str) -> dict[str, Any]:
        worker = self.info(plugin_worker_id, owner)
        try:
            self.processes.terminate_session(worker["session_id"], owner)
        finally:
            with self._connect() as db:
                db.execute(
                    "UPDATE plugin_workers SET state='STOPPED',updated_at=? "
                    "WHERE plugin_worker_id=? AND owner=?",
                    (self.clock(), plugin_worker_id, owner),
                )
        return self.info(plugin_worker_id, owner)
