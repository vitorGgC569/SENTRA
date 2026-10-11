"""Operator-registered loopback MCP HTTP, admitted through SENTRA central SQLite.

No self-registration from an MCPB manifest. No direct user/agent ability to
create credentials, authorities or network endpoints. An operator must approve
the pinned endpoint and the WorkItem needs three independent live grants.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Mapping
from pathlib import Path

from sentra_runtime.contracts import Capability, Machine, OperationRequest
from .control_store import SQLiteControlPlaneStore

_SERVER = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_TOOL = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")


class MCPHttpRegistry:
    def __init__(self, control):
        self.control = control
        self.store = control.store
        with self.store.connect("plugin_bundle") as db:
            db.execute("""CREATE TABLE IF NOT EXISTS mcp_http_endpoints(
                owner TEXT NOT NULL, workspace TEXT NOT NULL,
                server_id TEXT NOT NULL, endpoint TEXT NOT NULL,
                enabled INTEGER NOT NULL, revision INTEGER NOT NULL,
                updated REAL NOT NULL,
                PRIMARY KEY(owner,workspace,server_id))""")
            columns = {item[1] for item in db.execute("PRAGMA table_info(mcp_http_endpoints)")}
            if "streamable" not in columns:
                db.execute("ALTER TABLE mcp_http_endpoints ADD COLUMN streamable INTEGER NOT NULL DEFAULT 0")
            db.execute("""CREATE TABLE IF NOT EXISTS mcp_http_session_attempts(
                owner TEXT NOT NULL, workspace TEXT NOT NULL, server_id TEXT NOT NULL,
                operation_id TEXT PRIMARY KEY, session_id TEXT,
                state TEXT NOT NULL, updated REAL NOT NULL)""")
            session_cols = {item[1] for item in db.execute(
                "PRAGMA table_info(mcp_http_session_attempts)")}
            for column, ddl in (
                ("event_cursor", "TEXT"),
                ("observation_state", "TEXT NOT NULL DEFAULT 'IDLE'"),
                ("deletion_state", "TEXT NOT NULL DEFAULT 'ACTIVE'"),
            ):
                if column not in session_cols:
                    db.execute("ALTER TABLE mcp_http_session_attempts ADD COLUMN " +
                               column + " " + ddl)

    def get(self, owner, workspace, server_id):
        root = str(Path(workspace).resolve(strict=True))
        with self.store.connect("plugin_bundle") as db:
            row = db.execute(
                "SELECT server_id,endpoint,enabled,revision,streamable FROM mcp_http_endpoints "
                "WHERE owner=? AND workspace=? AND server_id=?",
                (owner, root, server_id),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("operator-provisioned MCP HTTP endpoint absent")
        return dict(row)

    def register(self, owner, workspace, server_id, endpoint, *, approved=False,
                 streamable=False):
        if type(streamable) is not bool:
            raise ValueError("MCP Streamable HTTP mode requires explicit boolean")
        if not approved or not _SERVER.fullmatch(server_id or ""):
            raise PermissionError("explicit operator approval and server identity required")
        # Avoid a circular import when ControlPlaneService imports this registry.
        from sentra_interop.mcp_http import LoopbackMCPHttpClient
        LoopbackMCPHttpClient(endpoint, None, server_id=server_id)
        root = str(Path(workspace).resolve(strict=True))
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT endpoint,enabled,revision,streamable FROM mcp_http_endpoints "
                "WHERE owner=? AND workspace=? AND server_id=?",
                (owner, root, server_id),
            ).fetchone()
            if row is not None:
                # Pin cannot silently change underneath a cached Operation.
                if row["endpoint"] != endpoint or bool(row["streamable"]) != streamable:
                    raise PermissionError("MCP HTTP update requires disable and new server identity")
                if not row["enabled"]:
                    raise PermissionError("revoked MCP HTTP endpoint cannot be silently reactivated")
                return self.get(owner, workspace, server_id)
            db.execute("INSERT INTO mcp_http_endpoints("
                       "owner,workspace,server_id,endpoint,enabled,revision,updated,streamable)"
                       " VALUES(?,?,?,?,1,1,?,?)",
                       (owner, root, server_id, endpoint, time.time(), int(streamable)))
        return self.get(owner, workspace, server_id)

    def disable(self, owner, workspace, server_id, *, approved=False):
        if not approved:
            raise PermissionError("operator approval required for MCP HTTP revocation")
        root = str(Path(workspace).resolve(strict=True))
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE mcp_http_endpoints SET enabled=0,revision=revision+1,updated=? "
                "WHERE owner=? AND workspace=? AND server_id=? AND enabled=1",
                (time.time(), owner, root, server_id),
            ).rowcount
            if not changed:
                row = db.execute(
                    "SELECT 1 FROM mcp_http_endpoints WHERE owner=? AND workspace=? "
                    "AND server_id=?", (owner, root, server_id)).fetchone()
                if not row:
                    raise FileNotFoundError("MCP HTTP server not registered")
        return self.get(owner, workspace, server_id)

    async def execute(self, *, owner, workspace, server_id, run_id,
                      work_item_id, agent_id, tool_name, arguments,
                      operation_id, idempotency_key, access_token=None):
        if not isinstance(tool_name, str) or not _TOOL.fullmatch(tool_name):
            raise ValueError("invalid MCP HTTP named tool")
        if not isinstance(arguments, Mapping):
            raise ValueError("MCP HTTP arguments must be an object")
        encoded = json.dumps(dict(arguments), allow_nan=False, ensure_ascii=False)
        if len(encoded.encode()) > 16_384:
            raise ValueError("MCP HTTP arguments oversized")
        row = self.get(owner, workspace, server_id)
        if not row["enabled"]:
            raise PermissionError("MCP HTTP provider revoked")
        run = self.control.durable.run_status(run_id, owner)
        work = self.control.work_item_info(work_item_id, owner)
        if (Path(run["workspace"]).resolve() != Path(workspace).resolve()
                or work["run_id"] != run_id or work["assignee_agent_id"] != agent_id):
            raise PermissionError("MCP HTTP WorkItem ownership mismatch")
        self.control._agent_from_run(run, agent_id)
        from sentra_interop.central import CentralInteropAdapter
        from sentra_interop.mcp_http import LoopbackMCPHttpClient
        machine = Machine("mcp-http-" + server_id, "mcp", owner, (
            Capability("mcp:http-connect", "Authorized HTTP MCP initialization"),
            Capability("mcp:list", "Authorized HTTP MCP discovery"),
            Capability("mcp:" + tool_name, "Authorized HTTP named tool"),
        ))
        gate = CentralInteropAdapter(control=self.control, run_id=run_id,
                                     owner=owner, machine=machine).protocol_gate()
        launch = OperationRequest(operation_id + "-launch", agent_id,
                                  machine.machine_id, "mcp:http-connect", work_item_id,
                                  idempotency_key + "-launch", {"server_id": server_id})
        listing = OperationRequest(operation_id + "-list", agent_id,
                                   machine.machine_id, "mcp:list", work_item_id,
                                   idempotency_key + "-list", {"server_id": server_id})
        request = OperationRequest(operation_id, agent_id, machine.machine_id,
                                   "mcp:" + tool_name, work_item_id, idempotency_key,
                                   {"server_id": server_id, "tool_name": tool_name,
                                    "arguments": json.loads(encoded)})
        for inquiry in (launch, listing, request):
            decision = await gate.decision(inquiry)
            if not decision.allowed:
                raise PermissionError("MCP HTTP WorkItem capability grant denied: " + decision.reason)

        async def revalidate():
            active = self.get(owner, workspace, server_id)
            if (not active["enabled"] or active["revision"] != row["revision"]
                    or active["endpoint"] != row["endpoint"]):
                raise PermissionError("MCP HTTP endpoint revised or revoked")
            for inquiry in (launch, listing, request):
                if not (await gate.decision(inquiry)).allowed:
                    raise PermissionError("MCP HTTP grant revoked")
            gate.physical_context(request).checkpoint()

        async def effect():
            await revalidate()
            client = LoopbackMCPHttpClient(
                row["endpoint"], gate, server_id=server_id,
                access_token=access_token, streamable=bool(row["streamable"]))
            root = str(Path(workspace).resolve(strict=True))
            with self.store.connect("plugin_bundle") as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO mcp_http_session_attempts("
                           "owner,workspace,server_id,operation_id,session_id,state,updated)"
                           " VALUES(?,?,?,?,?,?,?)",
                           (owner, root, server_id, operation_id, None, "INITIALIZING", time.time()))
            try:
                await client.initialize(launch)
                with self.store.connect("plugin_bundle") as db:
                    db.execute("UPDATE mcp_http_session_attempts SET state='ACTIVE',"
                               "session_id=?,updated=? WHERE operation_id=? AND state='INITIALIZING'",
                               (client._session_id, time.time(), operation_id))
                await revalidate()
                inventory = await client.list_tools(listing)
                if tool_name not in inventory:
                    raise PermissionError("MCP HTTP tool not in observed inventory")
                await revalidate()
                result = await client.call_tool_authorized(
                    request, tool_name, request.arguments["arguments"])
                await revalidate()
                # Same strict text-only result boundary as MCP stdio.
                from sentra_interop.mcp import _deny_obvious_secret_values
                if not isinstance(result.get("content"), list):
                    raise ValueError("MCP HTTP response missing content")
                if any(not isinstance(x, dict) or set(x) - {"type", "text"}
                       or x.get("type") != "text" or not isinstance(x.get("text"), str)
                       for x in result["content"]):
                    raise ValueError("unsupported MCP HTTP result")
                if len(json.dumps(result, allow_nan=False).encode()) > 16_384:
                    raise ValueError("MCP HTTP tool result oversized")
                _deny_obvious_secret_values(result)
                with self.store.connect("plugin_bundle") as db:
                    db.execute("UPDATE mcp_http_session_attempts SET state='COMPLETED',updated=? "
                               "WHERE operation_id=? AND state='ACTIVE'",
                               (time.time(), operation_id))
                return result
            except BaseException:
                with self.store.connect("plugin_bundle") as db:
                    db.execute("UPDATE mcp_http_session_attempts SET state='UNCERTAIN',updated=? "
                               "WHERE operation_id=? AND state IN ('INITIALIZING','ACTIVE')",
                               (time.time(), operation_id))
                raise
            finally:
                await client.close()

        return await gate.execute(request, effect, timeout=19)

    def session_status(self, owner, workspace, operation_id):
        """Read-only durable session health; never asserts a remote worker is alive."""
        root = str(Path(workspace).resolve(strict=True))
        with self.store.connect("plugin_bundle") as db:
            row = db.execute("SELECT server_id,operation_id,state,updated FROM "
                             "mcp_http_session_attempts WHERE owner=? AND workspace=? "
                             "AND operation_id=?", (owner, root, operation_id)).fetchone()
        if not row:
            raise FileNotFoundError("MCP HTTP session evidence absent")
        return {**dict(row), "remote_liveness_proved": False}

    def reconcile_abandoned(self, owner, workspace, *, min_age_seconds=60):
        """Crash recovery only marks stale attempts UNCERTAIN. No network resend.

        Caller must hold host operator authority. The physical operation
        fence and SQLite receipt remain authoritative for any effect.
        """
        if type(min_age_seconds) is not int or min_age_seconds < 30:
            raise ValueError("minimum stale session age is 30 seconds")
        root = str(Path(workspace).resolve(strict=True))
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "UPDATE mcp_http_session_attempts SET state='UNCERTAIN',updated=? "
                "WHERE owner=? AND workspace=? AND state IN ('INITIALIZING','ACTIVE') "
                "AND updated<?", (time.time(), owner, root,
                                  time.time() - min_age_seconds)).rowcount
            observed = db.execute(
                "UPDATE mcp_http_session_attempts SET observation_state='UNCERTAIN',"
                "updated=? WHERE owner=? AND workspace=? AND observation_state='READING' "
                "AND updated<?",
                (time.time(), owner, root, time.time()-min_age_seconds)).rowcount
            deleting = db.execute(
                "UPDATE mcp_http_session_attempts SET deletion_state='UNCERTAIN',"
                "updated=? WHERE owner=? AND workspace=? AND deletion_state='DELETING' "
                "AND updated<?",
                (time.time(), owner, root, time.time()-min_age_seconds)).rowcount
        return {"sessions_marked_uncertain": count, "event_reads_uncertain": observed,
                "deletions_uncertain": deleting, "effects_replayed": 0,
                "remote_workers_terminated": 0,
                "requires_host_reconciliation": bool(count or observed or deleting)}


    async def session_action(self, *, owner, workspace, server_id, run_id,
                             work_item_id, agent_id, source_operation_id,
                             operation_id, idempotency_key, action,
                             access_token=None):
        """GET observation or DELETE with separate central durable Operation.

        Source session belongs to a previously successful WorkItem Operation.
        No agent/browser-supplied session ID or Last-Event-ID is trusted.
        """
        if action not in {"events", "delete"} or operation_id == source_operation_id:
            raise ValueError("invalid MCP session management action")
        row = self.get(owner, workspace, server_id)
        if not row["enabled"] or not row["streamable"]:
            raise PermissionError("MCP session provider unavailable")
        root = str(Path(workspace).resolve(strict=True))
        source = self.control.durable.operation_status(source_operation_id, owner)
        run = self.control.durable.run_status(run_id, owner)
        work = self.control.work_item_info(work_item_id, owner)
        progress = source.get("progress") or {}
        if (source["state"] != "SUCCEEDED" or source["run_id"] != run_id
                or Path(run["workspace"]).resolve() != Path(root)
                or work["run_id"] != run_id
                or work["assignee_agent_id"] != agent_id
                or progress.get("work_item_id") != work_item_id
                or progress.get("principal_id") != agent_id):
            raise PermissionError("MCP session is not bound to successful owned Operation")
        self.control._agent_from_run(run, agent_id)
        with self.store.connect("plugin_bundle") as db:
            source_row = db.execute(
                "SELECT * FROM mcp_http_session_attempts WHERE owner=? AND workspace=? "
                "AND server_id=? AND operation_id=?",
                (owner, root, server_id, source_operation_id)).fetchone()
        if (not source_row or source_row["state"] != "COMPLETED"
                or source_row["deletion_state"] != "ACTIVE"
                or source_row["observation_state"] not in ("IDLE", "OBSERVED")
                or not source_row["session_id"]):
            raise PermissionError("MCP session is absent, uncertain or terminated")
        session_id, cursor = source_row["session_id"], source_row["event_cursor"]
        from sentra_interop.central import CentralInteropAdapter
        from sentra_interop.mcp_http import LoopbackMCPHttpClient
        cap = "mcp:events" if action == "events" else "mcp:session-delete"
        machine = Machine("mcp-http-" + server_id, "mcp", owner,
                          (Capability(cap, "MCP authorized session management"),))
        gate = CentralInteropAdapter(control=self.control, run_id=run_id,
                                     owner=owner, machine=machine).protocol_gate()
        arguments = {"server_id": server_id, "session_id": session_id}
        if action == "events":
            arguments["last_event_id"] = cursor
        intent = OperationRequest(operation_id, agent_id, machine.machine_id,
                                  cap, work_item_id, idempotency_key, arguments)
        if not (await gate.decision(intent)).allowed:
            raise PermissionError("MCP session action grant denied")

        def transition(expected, new, field):
            with self.store.connect("plugin_bundle") as db:
                db.execute("BEGIN IMMEDIATE")
                result = db.execute(
                    f"UPDATE mcp_http_session_attempts SET {field}=?,updated=? "
                    "WHERE owner=? AND workspace=? AND server_id=? AND operation_id=? "
                    "AND state='COMPLETED' AND deletion_state='ACTIVE' "
                    f"AND {field}=?",
                    (new, time.time(), owner, root, server_id,
                     source_operation_id, expected))
                if result.rowcount != 1:
                    raise PermissionError("MCP session state conflicted with another worker")

        async def effect():
            current = self.get(owner, workspace, server_id)
            if (not current["enabled"] or current["revision"] != row["revision"]
                    or current["endpoint"] != row["endpoint"]
                    or not (await gate.decision(intent)).allowed):
                raise PermissionError("MCP session revocation before effect")
            gate.physical_context(intent).checkpoint()
            state_field = "observation_state" if action == "events" else "deletion_state"
            previous_state = source_row[state_field]
            transition(previous_state, "READING" if action == "events" else "DELETING",
                       state_field)
            client = LoopbackMCPHttpClient(
                row["endpoint"], gate, server_id=server_id,
                access_token=access_token, streamable=True)
            try:
                if action == "events":
                    result = await client.events_authorized(
                        intent, session_id=session_id, last_event_id=cursor)
                    with self.store.connect("plugin_bundle") as db:
                        db.execute("BEGIN IMMEDIATE")
                        changed = db.execute(
                            "UPDATE mcp_http_session_attempts SET event_cursor=?,"
                            "observation_state='OBSERVED',updated=? WHERE owner=? "
                            "AND workspace=? AND server_id=? AND operation_id=? "
                            "AND observation_state='READING'",
                            (result["last_event_id"], time.time(), owner, root,
                             server_id, source_operation_id)).rowcount
                else:
                    result = await client.delete_authorized(intent, session_id=session_id)
                    with self.store.connect("plugin_bundle") as db:
                        db.execute("BEGIN IMMEDIATE")
                        changed = db.execute(
                            "UPDATE mcp_http_session_attempts SET deletion_state='DELETED',"
                            "updated=? WHERE owner=? AND workspace=? AND server_id=? "
                            "AND operation_id=? AND deletion_state='DELETING'",
                            (time.time(), owner, root, server_id,
                             source_operation_id)).rowcount
                if changed != 1:
                    raise PermissionError("MCP session ownership changed during effect")
                return result
            except BaseException:
                with self.store.connect("plugin_bundle") as db:
                    db.execute("UPDATE mcp_http_session_attempts SET "
                               f"{state_field}='UNCERTAIN',updated=? "
                               "WHERE owner=? AND workspace=? AND server_id=? "
                               "AND operation_id=? AND "
                               f"{state_field} IN ('READING','DELETING')",
                               (time.time(), owner, root, server_id,
                                source_operation_id))
                raise
            finally:
                await client.close()

        return await gate.execute(intent, effect, timeout=12)
