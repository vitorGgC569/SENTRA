"""Offline, recoverable SQLite -> native PostgreSQL authority cutover.

Prepare only snapshots databases. Commit imports in one PostgreSQL transaction;
activation is a protected compare-and-swap selection record. Rollback restores
the protected native snapshot to retained SQLite files while both runtimes are
quiesced. None of these administrative methods is a shell/agent command.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from sentra_core.conversations import _encode, _decode
from .control_store import CONTROL_PLANE_NAMESPACES
from .postgres_store import PostgresConnection, _identifier, native_sql
from .authority_snapshot import SnapshotCodec, capture_files, collect_keys, stage_files, publish_files, restore_keys
from .authority_paths import relocate_machine_configuration


SELECTION_FILE = "authority-selection.protected"


def read_selection(state_root):
    path = Path(state_root).resolve() / SELECTION_FILE
    if not path.is_file():
        return {"backend": "sqlite", "revision": 0}
    value = _decode(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("backend") not in {"sqlite", "postgres"} or type(value.get("revision")) is not int:
        raise RuntimeError("invalid authority selection record")
    return value


def _source(root, namespace):
    return root / "context" / "context.sqlite3" if namespace == "context" else root / "durable" / CONTROL_PLANE_NAMESPACES[namespace]


class NativeAuthorityMigration:
    def __init__(self, source_root, target_store):
        self.source_root = Path(source_root).resolve()
        if target_store.backend != "postgres" or target_store.member_role != "administrator":
            raise PermissionError("native target tenant administrator required")
        self.target = target_store

    def prepare(self, directory, *, quiesced=False, recovery_key=None):
        if quiesced is not True:
            raise PermissionError("quiesced source authority required")
        self.target.require_membership(write=True,administrator=True)
        root = Path(directory).resolve()
        root.mkdir(parents=True, exist_ok=False)
        codec, keys = SnapshotCodec(root,recovery_key=recovery_key,create=True), {}
        with self.target._connect_raw() as db:
            members = db.execute("SELECT principal_id,role,revoked FROM sentra_admin.memberships WHERE tenant_id=%s ORDER BY principal_id",(self.target.tenant_id,)).fetchall()
        principals = {member["principal_id"] for member in members}
        manifest = {"version": 2, "migration_id": "migration-" + uuid.uuid4().hex, "source_root": str(self.source_root),
            "tenant_id": self.target.tenant_id, "principal_id": self.target.principal_id,
            "created_at": time.time(), "selection_revision": read_selection(self.source_root)["revision"], "namespaces": [], "memberships": members}
        for namespace in sorted(CONTROL_PLANE_NAMESPACES):
            path = _source(self.source_root, namespace)
            if not path.is_file():
                continue
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN")
                tables = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
                namespace_data = {"namespace": namespace, "source_file": str(path), "schema_version": db.execute("PRAGMA user_version").fetchone()[0], "tables": []}
                for table in tables:
                    _identifier(table["name"])
                    # Compile all source DDL before staging any authority data.
                    native_sql(table["sql"])
                    columns = [row["name"] for row in db.execute("PRAGMA table_info(" + table["name"] + ")")]
                    chunks = []
                    query = db.execute("SELECT * FROM " + _identifier(table["name"]))
                    index = 0
                    while True:
                        rows = query.fetchmany(100)
                        if not rows:
                            break
                        data = [dict(row) for row in rows]
                        owners = {row["owner"] for row in data if "owner" in row}
                        if owners - principals:
                            raise PermissionError("source owner must be explicitly enrolled in this tenant before migration")
                        collect_keys(data,keys)
                        for row in data:
                            for key, value in row.items():
                                if isinstance(value, bytes):
                                    row[key] = {"__sentra_bytea__": value.hex()}
                        filename = namespace + "-" + table["name"] + "-" + str(index) + ".protected"
                        collect_keys(data,keys)
                        encoded = codec.encode(data,filename)
                        (root / filename).write_bytes(encoded)
                        chunks.append({"file": filename, "sha256": hashlib.sha256(encoded).hexdigest(), "rows": len(data)})
                        index += 1
                    indexes = [row["sql"] for row in db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL ORDER BY name", (table["name"],))]
                    for sql in indexes:
                        native_sql(sql)
                    namespace_data["tables"].append({"table": table["name"], "columns": columns, "ddl": table["sql"], "indexes": indexes, "chunks": chunks})
                manifest["namespaces"].append(namespace_data)
                db.rollback()
        excluded = [_source(self.source_root,ns) for ns in CONTROL_PLANE_NAMESPACES]
        excluded.extend(self.source_root / name for name in ("tenants", "authority-rollback", "provider-authority", SELECTION_FILE))
        manifest["files"] = capture_files(codec,{"source":self.source_root},keys,excluded=excluded)
        key_bytes = codec.encode(keys,"os-key-references")
        (root / "os-key-references.sealed").write_bytes(key_bytes)
        manifest["key_references_sha256"] = hashlib.sha256(key_bytes).hexdigest()
        encoded = codec.encode(manifest,"migration")
        (root / "migration.protected").write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        with self.target._connect_raw() as db:
            db.execute("INSERT INTO sentra_admin.migrations VALUES(%s,%s,%s,'PREPARED',%s,%s,%s)",
                (manifest["migration_id"], self.target.tenant_id, self.target.principal_id, digest, str(root), time.time()))
        return {"migration_id": manifest["migration_id"], "directory": str(root), "manifest_sha256": digest,
                "state": "PREPARED", "source_preserved": True, "effects_replayed": False}

    def _manifest(self, directory, expected_digest, recovery_key=None):
        root = Path(directory).resolve(strict=True)
        raw = (root / "migration.protected").read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("migration manifest digest mismatch")
        codec = SnapshotCodec(root,recovery_key=recovery_key) if (root / "archive-key.json").exists() else None
        value = codec.decode(raw,"migration") if codec else _decode(raw.decode())
        if (value["source_root"], value["tenant_id"], value["principal_id"]) != (str(self.source_root), self.target.tenant_id, self.target.principal_id):
            raise PermissionError("migration scope mismatch")
        return root, value, codec

    def commit(self, directory, *, manifest_sha256, quiesced=False, recovery_key=None):
        self.target.require_membership(write=True,administrator=True)
        if quiesced is not True:
            raise PermissionError("quiesced source/target required")
        root, manifest, codec = self._manifest(directory, manifest_sha256,recovery_key)
        for item in manifest["namespaces"]:
            self.target.connect(item["namespace"]).close()
        with self.target._connect_raw() as db:
            with db.transaction():
                db.execute("SELECT set_config('sentra.principal_id',%s,true)", (self.target.principal_id,))
                for namespace in sorted(CONTROL_PLANE_NAMESPACES):
                    db.execute("SELECT pg_advisory_xact_lock(%s)", (self.target.lock_key(namespace),))
                state = db.execute("SELECT * FROM sentra_admin.migrations WHERE migration_id=%s AND tenant_id=%s AND principal_id=%s FOR UPDATE",
                    (manifest["migration_id"], self.target.tenant_id, self.target.principal_id)).fetchone()
                if state is None or state["source_digest"] != manifest_sha256:
                    raise PermissionError("migration not prepared by this authority")
                if state["state"] in {"IMPORTED", "ACTIVE"}:
                    return {"migration_id": manifest["migration_id"], "state": state["state"], "idempotent_replay": True}
                if state["state"] != "PREPARED":
                    raise RuntimeError("migration cannot be imported from its current state")
                members = db.execute("SELECT principal_id,role,revoked FROM sentra_admin.memberships WHERE tenant_id=%s ORDER BY principal_id FOR SHARE",(self.target.tenant_id,)).fetchall()
                if manifest.get("memberships") is not None and manifest["memberships"] != members:
                    raise PermissionError("tenant enrollment changed since migration preparation")
                db.execute("SET CONSTRAINTS ALL DEFERRED")
                for item in manifest["namespaces"]:
                    namespace = item["namespace"]
                    schema = self.target.schema(namespace)
                    db.execute("SELECT set_config('search_path',%s,true)", (schema + ",pg_catalog",))
                    # Adopt the one transaction, not one commit per namespace.
                    adapter = PostgresConnection(self.target, namespace)
                    adapter.raw.close()
                    adapter.raw = db
                    adapter._transaction = adapter._locked = True
                    for table in item["tables"]:
                        adapter.execute(table["ddl"])
                        names = table["columns"]
                        target = _identifier(schema) + "." + _identifier(table["table"])
                        existing = 0
                        for member in members:
                            db.execute("SELECT set_config('sentra.principal_id',%s,true)",(member["principal_id"],))
                            existing += db.execute("SELECT count(*) AS n FROM " + target).fetchone()["n"]
                        if existing:
                            raise RuntimeError("migration target contains authority data")
                        current = [r["column_name"] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", (schema, table["table"])).fetchall()]
                        if set(names) - set(current):
                            raise RuntimeError("source migration requires newer native schema")
                        sql = "INSERT INTO " + target + "(" + ",".join(_identifier(name) for name in names) + ") VALUES(" + ",".join("%s" for _ in names) + ")"
                        for chunk in table["chunks"]:
                            filename = chunk["file"]
                            if Path(filename).name != filename:
                                raise ValueError("invalid migration chunk path")
                            raw = (root / filename).read_bytes()
                            if hashlib.sha256(raw).hexdigest() != chunk["sha256"]:
                                raise ValueError("migration chunk digest mismatch")
                            for row in codec.decode(raw,filename) if codec else _decode(raw.decode()):
                                db.execute("SELECT set_config('sentra.principal_id',%s,true)",(row.get("owner",self.target.principal_id),))
                                if namespace == "machine_configuration" and table["table"] == "configured_machines":
                                    row = relocate_machine_configuration(row,self.source_root,self.target.state_root)
                                values = [bytes.fromhex(v["__sentra_bytea__"]) if isinstance(v, dict) and set(v) == {"__sentra_bytea__"} else v for v in (row[name] for name in names)]
                                if namespace == "durable" and table["table"] == "artifacts" and "path" in names:
                                    old = Path(values[names.index("path")]).resolve()
                                    if old.is_relative_to(self.source_root):
                                        values[names.index("path")] = str(self.target.state_root / old.relative_to(self.source_root))
                                db.execute(sql, values)
                        for index in table["indexes"]:
                            adapter.execute(index.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1).replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1) if "IF NOT EXISTS" not in index.upper() else index)
                        for column in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND is_identity='YES'", (schema, table["table"])).fetchall():
                            sequence = db.execute("SELECT pg_get_serial_sequence(%s,%s) AS seq", (schema + "." + table["table"], column["column_name"])).fetchone()["seq"]
                            db.execute("SELECT setval(%s::regclass,COALESCE((SELECT MAX(" + _identifier(column["column_name"]) + ") FROM " + target + "),1),EXISTS(SELECT 1 FROM " + target + "))", (sequence,))
                    db.execute("UPDATE _sentra_namespace SET application_version=%s WHERE singleton=1", (item["schema_version"],))
                durable = _identifier(self.target.schema("durable"))
                for member in members:
                    db.execute("SELECT set_config('sentra.principal_id',%s,true)",(member["principal_id"],))
                    db.execute("UPDATE " + durable + ".operations SET state='UNCERTAIN' WHERE state IN ('STARTING','RUNNING','WAITING_EXTERNAL','CANCEL_REQUESTED')")
                    db.execute("UPDATE " + durable + ".leases SET lease_until=0")
                    db.execute("UPDATE " + durable + ".runs SET state='RECOVERING' WHERE state IN ('RUNNING','PAUSED')")
                db.execute("UPDATE " + durable + ".lease_fences SET fencing_token=fencing_token+1")
                if manifest.get("version") == 2:
                    key_bytes = (root / "os-key-references.sealed").read_bytes()
                    if hashlib.sha256(key_bytes).hexdigest() != manifest["key_references_sha256"]:
                        raise ValueError("migration key archive digest mismatch")
                    restore_keys(codec.decode(key_bytes,"os-key-references"))
                    staged = stage_files(codec,manifest["files"],{"source":self.target.state_root})
                    for temporary,target in staged:
                        if target.exists() and hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(temporary.read_bytes()).digest():
                            raise RuntimeError("native migration file target contains different data")
                    publish_files(staged)
                db.execute("UPDATE sentra_admin.migrations SET state='IMPORTED' WHERE migration_id=%s", (manifest["migration_id"],))
        return {"migration_id": manifest["migration_id"], "state": "IMPORTED", "effects_replayed": False, "recovery_required": True}

    def activate(self, directory, *, manifest_sha256, expected_revision, quiesced=False, recovery_key=None):
        self.target.require_membership(write=True,administrator=True)
        if quiesced is not True:
            raise PermissionError("quiesced source/target activation required")
        _, manifest, _ = self._manifest(directory, manifest_sha256,recovery_key)
        from sentra_core.conversations import _lease
        path = self.source_root / SELECTION_FILE
        with _lease(path.with_suffix(".lock")):
            previous = read_selection(self.source_root)
            if previous["revision"] != expected_revision:
                raise RuntimeError("authority selection revision conflict")
            with self.target._connect_raw() as db, db.transaction():
                self.target.lock_administrator(db)
                state = db.execute("SELECT state FROM sentra_admin.migrations WHERE migration_id=%s AND tenant_id=%s AND principal_id=%s", (manifest["migration_id"], self.target.tenant_id, self.target.principal_id)).fetchone()
                if state is None or state["state"] != "IMPORTED":
                    raise RuntimeError("native authority must be imported before activation")
                # Selection is the cutover point. Crash before publication keeps
                # SQLite selected; crash after it keeps PG selected, never both.
                value = {"backend": "postgres", "dsn": self.target._dsn, "tenant_id": self.target.tenant_id,
                    "principal_id": self.target.principal_id, "revision": expected_revision + 1,
                    "migration_id": manifest["migration_id"], "updated_at": time.time()}
                temporary = path.with_suffix(".pending")
                temporary.write_text(_encode(value), encoding="utf-8")
                temporary.replace(path)
                self.target._selection_revision = value["revision"]
                db.execute("UPDATE sentra_admin.migrations SET state='ACTIVE' WHERE migration_id=%s", (manifest["migration_id"],))
        return {"backend": "postgres", "revision": value["revision"], "state": "ACTIVE", "recovery_required": True}

    def rollback(self, directory, *, manifest_sha256, expected_revision, quiesced=False, recovery_key=None):
        self.target.require_membership(write=True,administrator=True)
        if quiesced is not True:
            raise PermissionError("both authorities must be quiesced before rollback")
        _, manifest, _ = self._manifest(directory, manifest_sha256,recovery_key)
        from sentra_core.conversations import _lease
        path = self.source_root / SELECTION_FILE
        with _lease(path.with_suffix(".lock")):
            previous = read_selection(self.source_root)
            if previous["revision"] != expected_revision or previous.get("migration_id") != manifest["migration_id"]:
                raise RuntimeError("rollback authority selection conflict")
            # If PG changed after activation, retained SQLite is stale. Export
            # native state back into shadow SQLite files first, under a PG
            # snapshot/namespace locks, so rollback never discards new work.
            from .postgres_rollback import export_sqlite_rollback
            with self.target._connect_raw() as db, db.transaction():
                self.target.lock_administrator(db)
                export_sqlite_rollback(self.target, self.source_root, manifest)
                value = {"backend": "sqlite", "revision": expected_revision + 1, "migration_id": manifest["migration_id"], "updated_at": time.time()}
                temporary = path.with_suffix(".pending")
                temporary.write_text(_encode(value), encoding="utf-8")
                temporary.replace(path)
                db.execute("UPDATE sentra_admin.migrations SET state='ROLLED_BACK' WHERE migration_id=%s", (manifest["migration_id"],))
        return {"backend": "sqlite", "revision": value["revision"], "state": "ROLLED_BACK", "effects_replayed": False}
