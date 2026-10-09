"""Revision-aware ACP state and durable identities; never replay remote effects.

The store contains identifiers, scope, cwd and request hashes only. Transcript,
tool raw inputs/outputs, configuration values and credentials stay in memory.
It complements SENTRA admission, rather than granting authority of its own.
"""
from __future__ import annotations

import copy
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from sentra_runtime.contracts import OperationRequest
from .gate import EffectRejected, _fingerprint


def identity(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or "\0" in value:
        raise ValueError("invalid ACP identity")
    return value


@dataclass(frozen=True, slots=True)
class ACPSessionBinding:
    local_id: str
    provider: str
    session_id: str
    principal_id: str
    machine_id: str
    work_item_id: str
    cwd: str
    protocol_version: int
    state: str


class ACPSessionStore:
    """SQLite mappings plus pre-send receipts across process restarts.

    Binding scope is immutable. A closed session can be resumed explicitly; a
    deleted mapping is retained as a tombstone. IN_FLIGHT receipts are reported
    UNCERTAIN on lookup, never retried or automatically converted to success.
    """

    def __init__(self, database: str, *, workspace: str) -> None:
        self.workspace = Path(workspace).resolve()
        self.path = Path(database).resolve()
        if self.path == self.workspace or not self.path.is_relative_to(self.workspace):
            raise ValueError("ACP session database must be inside workspace")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS acp_session_bindings (
                local_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                session_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                machine_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
                cwd TEXT NOT NULL, protocol_version INTEGER NOT NULL,
                state TEXT NOT NULL,
                UNIQUE(provider,session_id,principal_id,machine_id,work_item_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS acp_session_effects (
                operation_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                fingerprint TEXT NOT NULL, local_id TEXT NOT NULL,
                method TEXT NOT NULL, state TEXT NOT NULL)""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, local_id: str, *, provider: str, request: OperationRequest) -> ACPSessionBinding | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM acp_session_bindings WHERE local_id=?",
                             (identity(local_id),)).fetchone()
        if row is None:
            return None
        binding = ACPSessionBinding(*row)
        if (binding.provider, binding.principal_id, binding.machine_id, binding.work_item_id) != (
            provider, request.principal_id, request.machine_id, request.work_item_id
        ):
            raise EffectRejected("ACP binding scope mismatch")
        return binding

    def bind(self, local_id: str, provider: str, session_id: str, cwd: str,
             protocol_version: int, request: OperationRequest) -> None:
        for value in (local_id, provider, session_id):
            identity(value)
        directory = Path(cwd).resolve()
        if protocol_version not in (1, 2) or not directory.is_relative_to(self.workspace):
            raise ValueError("invalid ACP binding")
        values = (local_id, provider, session_id, request.principal_id, request.machine_id,
                  request.work_item_id, str(directory), protocol_version)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM acp_session_bindings WHERE local_id=?", (local_id,)).fetchone()
            if old and (old[:8] != values or old[8] == "DELETED"):
                raise EffectRejected("ACP mapping cannot be replaced")
            db.execute("INSERT INTO acp_session_bindings VALUES (?,?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(local_id) DO UPDATE SET state='ACTIVE'", (*values, "ACTIVE"))

    def set_state(self, local_id: str, state: str) -> None:
        if state not in {"ACTIVE", "DETACHED", "CLOSED", "DELETED", "UNCERTAIN"}:
            raise ValueError("invalid ACP binding state")
        with self._db() as db:
            changed = db.execute("UPDATE acp_session_bindings SET state=? WHERE local_id=? AND state != 'DELETED'",
                                 (state, local_id))
            if changed.rowcount != 1:
                row = db.execute("SELECT state FROM acp_session_bindings WHERE local_id=?", (local_id,)).fetchone()
                if row is None:
                    raise ValueError("unknown ACP binding")

    def reserve(self, local_id: str, method: str, request: OperationRequest) -> None:
        signature = _fingerprint(request)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT operation_id FROM acp_session_effects WHERE "
                             "operation_id=? OR idempotency_key=?",
                             (request.operation_id, request.idempotency_key)).fetchone()
            if old:
                raise EffectRejected("durable ACP receipt exists; reconcile without resending")
            if method == "session/new" and db.execute(
                "SELECT 1 FROM acp_session_effects WHERE local_id=? AND method='session/new' "
                "AND state != 'FAILED'", (local_id,)).fetchone():
                raise EffectRejected("ACP creation already sent or uncertain; never create a replacement implicitly")
            db.execute("INSERT INTO acp_session_effects VALUES (?,?,?,?,?,?)", (
                request.operation_id, request.idempotency_key, signature, local_id, method, "IN_FLIGHT"))

    def finish(self, request: OperationRequest, state: str) -> None:
        if state not in {"SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}:
            raise ValueError("invalid ACP receipt state")
        with self._db() as db:
            changed = db.execute("UPDATE acp_session_effects SET state=? WHERE operation_id=? "
                                 "AND fingerprint=?", (state, request.operation_id, _fingerprint(request)))
            if changed.rowcount != 1:
                raise ValueError("unknown ACP receipt")

    def receipt(self, operation_id: str) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT state FROM acp_session_effects WHERE operation_id=?",
                             (operation_id,)).fetchone()
        return ("UNCERTAIN" if row[0] == "IN_FLIGHT" else row[0]) if row else None


V1_UPDATES = frozenset({"user_message_chunk", "agent_message_chunk", "agent_thought_chunk",
                      "tool_call", "tool_call_update", "plan", "available_commands_update",
                      "current_mode_update", "config_option_update", "session_info_update", "usage_update"})
V2_UPDATES = (V1_UPDATES - {"tool_call", "plan", "current_mode_update"}) | frozenset({
    "user_message", "agent_message", "agent_thought", "state_update", "tool_call_content_chunk",
    "terminal_update", "terminal_output_chunk", "plan_update"})
TOOL_FIELDS = frozenset({"name", "title", "kind", "status", "content", "locations",
                         "rawInput", "rawOutput", "_meta"})


@dataclass
class ACPSessionState:
    """Bounded in-memory projection, preserving wire absent/null distinctions."""

    protocol_version: int
    tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    config_options: list[dict[str, Any]] = field(default_factory=list)
    modes: dict[str, Any] | None = None
    available_commands: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    info: dict[str, Any] = field(default_factory=dict)
    foreground: dict[str, Any] | None = None
    max_tools: int = 4096
    max_projection_bytes: int = 2 * 1024 * 1024

    def _bounded(self, value: Any) -> None:
        if len(json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")) > self.max_projection_bytes:
            raise ValueError("ACP projection exceeds limit")

    def set_config(self, options: Any) -> None:
        if not isinstance(options, list) or len(options) > 128:
            raise ValueError("invalid ACP config options")
        seen = set()
        for option in options:
            if not isinstance(option, Mapping) or option.get("type") not in {"select", "boolean"}:
                raise ValueError("unsupported ACP config option")
            key = identity(option.get("id"))
            if key in seen:
                raise ValueError("duplicate ACP config option")
            seen.add(key)
            if option["type"] == "boolean" and type(option.get("currentValue")) is not bool:
                raise ValueError("invalid ACP boolean option")
            if option["type"] == "select":
                identity(option.get("currentValue"))
                self.option_values(option)
        self._bounded(options)
        self.config_options = copy.deepcopy(options)

    @staticmethod
    def option_values(option: Mapping[str, Any]) -> set[str]:
        options = option.get("options")
        if not isinstance(options, list):
            raise ValueError("invalid ACP select choices")
        values = set()
        for choice in options:
            if not isinstance(choice, Mapping):
                raise ValueError("invalid ACP select choice")
            group = choice.get("options")
            rows = group if isinstance(group, list) else [choice]
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("invalid ACP select choice")
                values.add(identity(row.get("value")))
        return values

    def setup(self, response: Mapping[str, Any]) -> None:
        # New/resumed session state must not inherit stale option availability.
        self.set_config(response.get("configOptions") or [])
        self.modes = copy.deepcopy(response.get("modes")) if self.protocol_version == 1 else None
        self.available_commands = copy.deepcopy(response.get("availableCommands") or [])

    def apply(self, event: Mapping[str, Any]) -> None:
        kind = event.get("sessionUpdate")
        allowed = V1_UPDATES if self.protocol_version == 1 else V2_UPDATES
        if kind not in allowed:
            raise ValueError("ACP update incompatible with negotiated revision")
        self._bounded(event)
        if kind in {"tool_call", "tool_call_update", "tool_call_content_chunk"}:
            key = identity(event.get("toolCallId"))
            if key not in self.tool_calls and len(self.tool_calls) >= self.max_tools:
                raise ValueError("ACP tool call count exceeded")
            if self.protocol_version == 1 and kind == "tool_call_update" and key not in self.tool_calls:
                raise ValueError("ACP v1 update requires initial tool call")
            old = self.tool_calls.get(key, {"toolCallId": key, "kind": "other", "status": "pending",
                                            "content": [], "locations": []})
            new = copy.deepcopy(old)
            if kind == "tool_call_content_chunk":
                if not isinstance(event.get("content"), Mapping):
                    raise ValueError("invalid ACP content chunk")
                new["content"] = [*(new.get("content") or []), copy.deepcopy(event["content"])]
            else:
                for name in TOOL_FIELDS:
                    if name not in event:
                        continue
                    value = event[name]
                    # v1 Rust Option fields: null and absence both skip changes.
                    # v2 patch fields: null clears, concrete replaces, absent skips.
                    if value is None and self.protocol_version == 1:
                        continue
                    if name in {"content", "locations"} and value is not None and not isinstance(value, list):
                        raise ValueError("invalid ACP tool collection")
                    if value is None:
                        new[name] = None  # Keep explicit clear distinct from never supplied.
                    else:
                        new[name] = copy.deepcopy(value)
            projected = dict(self.tool_calls)
            projected[key] = new
            self._bounded(projected)
            self.tool_calls[key] = new
        elif kind == "config_option_update":
            self.set_config(event.get("configOptions"))
        elif kind == "usage_update":
            for key in ("used", "size"):
                if type(event.get(key)) is not int or event[key] < 0:
                    raise ValueError("invalid ACP usage count")
            cost = event.get("cost")
            if cost is not None:
                if (not isinstance(cost, Mapping) or type(cost.get("amount")) not in (int, float)
                    or not math.isfinite(cost["amount"]) or cost["amount"] < 0
                    or not isinstance(cost.get("currency"), str) or not cost["currency"]):
                    raise ValueError("invalid ACP usage cost")
            self.usage = copy.deepcopy({k: v for k, v in event.items() if k != "sessionUpdate"})
        elif kind == "state_update":
            if not isinstance(event.get("state"), str) or not event["state"]:
                raise ValueError("invalid ACP foreground state")
            self.foreground = copy.deepcopy(dict(event))
        elif kind == "session_info_update":
            self.info.update(copy.deepcopy({k: v for k, v in event.items() if k != "sessionUpdate"}))
            self._bounded(self.info)
        elif kind == "available_commands_update":
            if not isinstance(event.get("availableCommands"), list):
                raise ValueError("invalid ACP commands")
            self.available_commands = copy.deepcopy(event["availableCommands"])
        elif kind == "current_mode_update":
            identity(event.get("currentModeId"))
            if self.modes is not None:
                self.modes["currentModeId"] = event["currentModeId"]
