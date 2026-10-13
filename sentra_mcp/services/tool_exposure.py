"""Global immutable tool-name ownership, including disabled providers.

Reservations survive disable/uninstall to prevent cached calls being redirected
to a newly installed provider. Publication is an ACL projection, never a grant.
"""
from __future__ import annotations
import hashlib
import json
import re
from contextlib import closing

MAX_TOOLS = 256
MAX_SCHEMA_BYTES = 250_000
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class ToolExposureRegistry:
    def __init__(self, store):
        self.store = store
        with closing(store.connect("plugin_worker")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS plugin_tool_names("
                       "name_key TEXT PRIMARY KEY,name TEXT NOT NULL,provider_id TEXT NOT NULL,"
                       "schema_sha256 TEXT NOT NULL,schema_json TEXT NOT NULL,enabled INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS plugin_schema_epoch ("
                       "id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO plugin_schema_epoch VALUES(1,0)")

    @staticmethod
    def descriptors(methods):
        if not isinstance(methods, list) or len(methods) > MAX_TOOLS:
            raise ValueError("plugin exposure exceeds 256 tools")
        tools, names = [], set()
        for method in methods:
            raw = {"name": method} if isinstance(method, str) else method
            if not isinstance(raw, dict) or not _NAME.fullmatch(raw.get("name", "")):
                raise ValueError("invalid published plugin tool name")
            key = raw["name"].casefold()
            if key in names:
                raise ValueError("ambiguous published plugin tool name")
            names.add(key)
            tool = {"name": raw["name"], "description": raw.get("description", ""),
                    "inputSchema": raw.get("inputSchema", {"type": "object"}),
                    "outputSchema": raw.get("outputSchema")}
            if not isinstance(tool["description"], str) or len(tool["description"]) > 8000:
                raise ValueError("plugin description exceeds bound")
            if not isinstance(tool["inputSchema"], dict) or tool["outputSchema"] is not None and not isinstance(tool["outputSchema"], dict):
                raise ValueError("plugin tool schema must be an object")
            tools.append(tool)
        canonical = json.dumps(tools, sort_keys=True, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")).encode()
        if len(canonical) > MAX_SCHEMA_BYTES:
            raise ValueError("plugin exposure exceeds 250000 schema bytes")
        return tools

    def reserve(self, provider_id, methods, *, enabled=False):
        if (not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 256
                or provider_id == "sentra-core" or type(enabled) is not bool):
            raise ValueError("provider identity and boolean required")
        tools = self.descriptors(methods)
        with closing(self.store.connect("plugin_worker")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            for tool in tools:
                old = db.execute("SELECT provider_id FROM plugin_tool_names WHERE name_key=?", (tool["name"].casefold(),)).fetchone()
                if old and old[0] != provider_id:
                    raise PermissionError("tool name is reserved by another provider, including disabled providers")
            # Old names remain reserved but disappear from current publication.
            db.execute("UPDATE plugin_tool_names SET enabled=0 WHERE provider_id=?", (provider_id,))
            for tool in tools:
                raw = json.dumps(tool, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                db.execute("INSERT INTO plugin_tool_names VALUES(?,?,?,?,?,?) ON CONFLICT(name_key) DO UPDATE SET "
                           "schema_sha256=excluded.schema_sha256,schema_json=excluded.schema_json,enabled=excluded.enabled",
                           (tool["name"].casefold(), tool["name"], provider_id, hashlib.sha256(raw.encode()).hexdigest(), raw, int(enabled)))
            db.execute("UPDATE plugin_schema_epoch SET generation=generation+1 WHERE id=1")
        return {"tools": len(tools), "enabled": enabled, "names_reserved_when_disabled": True}

    def conflict_report(self, provider_id, methods):
        """Read-only exposure pre-check (pluginExposure port), no reservation.

        Reports name collisions against reservations held by other
        providers (including disabled ones), schema budget overruns and
        the resulting tool count, without changing any publication.
        The host UI calls this before import/registration review.
        """
        if (not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 256
                or provider_id == "sentra-core"):
            raise ValueError("provider identity required")
        try:
            tools = self.descriptors(methods)
        except ValueError as exc:
            return {"provider_id": provider_id, "valid": False,
                    "reason": str(exc)[:200], "collisions": [],
                    "tool_count": 0, "grants_created": False}
        collisions = []
        with closing(self.store.connect("plugin_worker")) as db:
            for tool in tools:
                old = db.execute("SELECT provider_id FROM plugin_tool_names WHERE name_key=?",
                                 (tool["name"].casefold(),)).fetchone()
                if old and old[0] != provider_id:
                    collisions.append({"name": tool["name"],
                                       "reserved_by": old[0],
                                       "reserved_when_disabled": True})
        return {"provider_id": provider_id, "valid": not collisions,
                "collisions": collisions, "tool_count": len(tools),
                "names_reserved_when_disabled": True,
                "grants_created": False, "reservation_changed": False}

    def disable(self, provider_id):
        with closing(self.store.connect("plugin_worker")) as db, db:
            db.execute("UPDATE plugin_tool_names SET enabled=0 WHERE provider_id=?", (provider_id,))
            db.execute("UPDATE plugin_schema_epoch SET generation=generation+1 WHERE id=1")

    def publication(self, provider_ids):
        if not isinstance(provider_ids, (list, tuple)) or len(provider_ids) > 128:
            raise ValueError("bounded authorized provider projection required")
        if not provider_ids:
            return []
        with closing(self.store.connect("plugin_worker")) as db:
            rows = db.execute("SELECT schema_json FROM plugin_tool_names WHERE enabled=1 AND provider_id IN (" +
                              ",".join("?" for _ in provider_ids) + ") ORDER BY name_key LIMIT 257", list(provider_ids)).fetchall()
        tools = [json.loads(row[0]) for row in rows]
        return self.descriptors(tools)

    def reserve_core_names(self, names):
        """Reserve registered first-party MCP names without exposing plugin authority.

        Core tool descriptors may exceed a *plugin's* publication budgets;
        reserve minimal tombstones so no plugin can steal a first-party tool.
        """
        if not isinstance(names, list) or len(names) > 4096:
            raise ValueError("invalid bounded first-party MCP tool inventory")
        folded = set()
        for name in names:
            if not isinstance(name, str) or not _NAME.fullmatch(name) or name.casefold() in folded:
                raise ValueError("invalid or duplicate first-party tool identity")
            folded.add(name.casefold())
        with closing(self.store.connect("plugin_worker")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            for name in names:
                row = db.execute("SELECT provider_id FROM plugin_tool_names WHERE name_key=?",
                                 (name.casefold(),)).fetchone()
                if row and row[0] != "sentra-core":
                    raise PermissionError("first-party tool collides with reserved plugin name")
            db.execute("UPDATE plugin_tool_names SET enabled=0 WHERE provider_id='sentra-core'")
            for name in names:
                raw = json.dumps({"name": name, "inputSchema": {"type": "object"}}, separators=(",", ":"))
                db.execute("INSERT INTO plugin_tool_names VALUES(?,?,?,?,?,1) "
                           "ON CONFLICT(name_key) DO UPDATE SET enabled=1",
                           (name.casefold(), name, "sentra-core", hashlib.sha256(raw.encode()).hexdigest(), raw))
            db.execute("UPDATE plugin_schema_epoch SET generation=generation+1 WHERE id=1")
        return {"names": len(names), "reserved": True, "creates_grants": False}

    def publication_snapshot(self, provider_ids, *, allowed_names=None, previous=None):
        """Versioned, selectively disclosed schema snapshot for a host handshake.

        No grants are generated. Callers must derive provider_ids/allowed_names
        from owner-approved policy, not from MCP/LLM text. The epoch catches
        even ABA schema changes with the same final canonical JSON.
        """
        if (not isinstance(provider_ids, (tuple, list)) or len(provider_ids) > 128
                or any(not isinstance(p, str) or not 1 <= len(p) <= 256
                       or p == "sentra-core" for p in provider_ids)
                or len(set(provider_ids)) != len(provider_ids)):
            raise ValueError("invalid selective MCP provider ACL")
        if allowed_names is not None:
            if (not isinstance(allowed_names, (list, tuple)) or len(allowed_names) > MAX_TOOLS
                    or any(not isinstance(n, str) or not _NAME.fullmatch(n) for n in allowed_names)
                    or len({n.casefold() for n in allowed_names}) != len(allowed_names)):
                raise ValueError("invalid selective MCP tool ACL")
        if previous is not None and (not isinstance(previous, dict)
                or type(previous.get("generation")) is not int
                or not isinstance(previous.get("schema_sha256"), str)):
            raise ValueError("invalid previous MCP schema checkpoint")
        with closing(self.store.connect("plugin_worker")) as db:
            db.execute("BEGIN")
            generation = db.execute("SELECT generation FROM plugin_schema_epoch WHERE id=1").fetchone()[0]
            if provider_ids:
                rows = db.execute(
                    "SELECT schema_json FROM plugin_tool_names WHERE enabled=1 "
                    "AND provider_id IN (" + ",".join("?" for _ in provider_ids) +
                    ") ORDER BY name_key LIMIT 257", list(provider_ids),
                ).fetchall()
            else:
                rows = []
            tools = [json.loads(r[0]) for r in rows]
        if allowed_names is not None:
            names = {name.casefold() for name in allowed_names}
            tools = [tool for tool in tools if tool["name"].casefold() in names]
            if {tool["name"].casefold() for tool in tools} != names:
                raise PermissionError("selected MCP tool absent from active provider publication")
        tools = self.descriptors(tools)
        encoded = json.dumps(tools, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        return {"generation": generation, "schema_sha256": digest,
                "tools": tools, "tool_count": len(tools),
                "changed": previous is None or
                           previous["generation"] != generation or
                           previous["schema_sha256"] != digest,
                "grants_created": False, "external_account_verified": False}
