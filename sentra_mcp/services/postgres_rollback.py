"""Export a quiesced native tenant to retained SQLite files without data loss."""
from pathlib import Path
import re
import sqlite3
import time
from .control_store import CONTROL_PLANE_NAMESPACES
from .postgres_store import _identifier
from .authority_snapshot import SnapshotCodec, capture_files, stage_files, publish_files
from .authority_paths import relocate_machine_configuration


def _default(value):
    if value is None:
        return None
    value = re.sub(r"::(?:text|character varying|bigint|integer|double precision|boolean|jsonb)", "", value)
    if re.search(r"\b(nextval|CURRENT_|now\(|gen_random_uuid)\b", value, re.I):
        raise ValueError("native default has no lossless SQLite rollback equivalent")
    return value


def _type(column):
    kind = column["data_type"]
    return "INTEGER" if kind in {"bigint", "integer", "smallint", "boolean"} else "REAL" if kind in {"real", "double precision", "numeric"} else "BLOB" if kind == "bytea" else "TEXT"


def export_sqlite_rollback(store, source_root, source_manifest):
    root = Path(source_root).resolve()
    staging = root / "authority-rollback" / str(int(time.time() * 1000000))
    staging.mkdir(parents=True, exist_ok=False)
    originals = {(n["namespace"], t["table"]): t for n in source_manifest["namespaces"] for t in n["tables"]}
    shadows = []
    file_archive = staging / "owned-files"
    file_archive.mkdir()
    codec, keys = SnapshotCodec(file_archive,create=True), {}
    with store._connect_raw() as pg:
        with pg.transaction():
            pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            store.lock_administrator(pg)
            for namespace in sorted(CONTROL_PLANE_NAMESPACES):
                pg.execute("SELECT pg_advisory_xact_lock(%s)", (store.lock_key(namespace),))
            members = pg.execute("SELECT principal_id FROM sentra_admin.memberships WHERE tenant_id=%s ORDER BY principal_id FOR SHARE", (store.tenant_id,)).fetchall()
            for namespace in sorted(CONTROL_PLANE_NAMESPACES):
                schema = store.schema(namespace)
                tables = pg.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' AND table_name NOT LIKE '_sentra_%%' ORDER BY table_name", (schema,)).fetchall()
                if not tables:
                    continue
                shadow = staging / (namespace + ".sqlite3")
                with sqlite3.connect(shadow) as db:
                    db.execute("PRAGMA foreign_keys=OFF")
                    db.execute("BEGIN IMMEDIATE")
                    for entry in tables:
                        table = entry["table_name"]
                        columns = pg.execute("SELECT column_name,data_type,is_nullable,column_default,is_identity FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", (schema, table)).fetchall()
                        original = originals.get((namespace, table))
                        if original:
                            db.execute(original["ddl"])
                            names = {r[1] for r in db.execute("PRAGMA table_info(" + table + ")")}
                            for col in columns:
                                if col["column_name"] not in names:
                                    declaration = _identifier(col["column_name"]) + " " + _type(col)
                                    default = _default(col["column_default"])
                                    if default is not None:
                                        declaration += " DEFAULT " + default
                                    if col["is_nullable"] == "NO":
                                        declaration += " NOT NULL"
                                    db.execute("ALTER TABLE " + _identifier(table) + " ADD COLUMN " + declaration)
                        else:
                            declarations = []
                            for col in columns:
                                declaration = _identifier(col["column_name"]) + " " + _type(col)
                                if col["is_nullable"] == "NO":
                                    declaration += " NOT NULL"
                                default = _default(col["column_default"])
                                if default is not None:
                                    declaration += " DEFAULT " + default
                                declarations.append(declaration)
                            constraints = pg.execute("SELECT pg_get_constraintdef(c.oid) AS ddl FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=%s AND t.relname=%s ORDER BY c.conname", (schema, table)).fetchall()
                            for constraint in constraints:
                                ddl = re.sub(r"\s+(?:NOT )?DEFERRABLE(?: INITIALLY (?:IMMEDIATE|DEFERRED))?", "", constraint["ddl"])
                                ddl = re.sub(r"::(?:text|bigint|integer|double precision)", "", ddl)
                                declarations.append(ddl.replace(schema + ".", "").replace(_identifier(schema) + ".", ""))
                            db.execute("CREATE TABLE " + _identifier(table) + "(" + ",".join(declarations) + ")")
                        names = [c["column_name"] for c in columns]
                        sql = "INSERT INTO " + _identifier(table) + "(" + ",".join(_identifier(n) for n in names) + ") VALUES(" + ",".join("?" for _ in names) + ")"
                        principals = [m["principal_id"] for m in members] if "owner" in names else [store.principal_id]
                        for principal in principals:
                            pg.execute("SELECT set_config('sentra.principal_id',%s,true)", (principal,))
                            query = pg.execute("SELECT * FROM " + _identifier(schema) + "." + _identifier(table))
                            while True:
                                rows = query.fetchmany(100)
                                if not rows:
                                    break
                                if namespace == "machine_configuration" and table == "configured_machines":
                                    rows = [relocate_machine_configuration(row,store.state_root,root) for row in rows]
                                values = [[bytes(v) if isinstance(v, memoryview) else v for v in (row[n] for n in names)] for row in rows]
                                if namespace == "durable" and table == "artifacts" and "path" in names:
                                    for record in values:
                                        old = Path(record[names.index("path")]).resolve()
                                        if old.is_relative_to(store.state_root):
                                            record[names.index("path")] = str(root / old.relative_to(store.state_root))
                                db.executemany(sql, values)
                        if original:
                            for index in original["indexes"]:
                                db.execute(index)
                    if namespace == "durable":
                        db.execute("UPDATE operations SET state='UNCERTAIN' WHERE state IN ('STARTING','RUNNING','WAITING_EXTERNAL','CANCEL_REQUESTED')")
                        db.execute("UPDATE runs SET state='RECOVERING' WHERE state IN ('RUNNING','PAUSED')")
                        db.execute("UPDATE leases SET lease_until=0")
                        db.execute("UPDATE lease_fences SET fencing_token=fencing_token+1")
                    meta = pg.execute("SELECT application_version FROM " + _identifier(schema) + "._sentra_namespace WHERE singleton=1").fetchone()
                    db.execute("PRAGMA user_version=" + str(int(meta["application_version"])))
                    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        raise RuntimeError("rollback snapshot violates domain references")
                target = root / "context" / "context.sqlite3" if namespace == "context" else root / "durable" / CONTROL_PLANE_NAMESPACES[namespace]
                if not target.resolve().is_relative_to(root):
                    raise PermissionError("rollback target outside intended state root")
                shadows.append((shadow, target))
            # Preserve current native artifacts/journals before switching authority.
            # SQLite sidecars outside the native namespaces remain at source.
            excluded = list(store.state_root.rglob("*.sqlite3"))
            snapshot = capture_files(codec,{"native":store.state_root},keys,excluded=excluded)
            files = stage_files(codec,snapshot,{"native":root})
    publish_files(files)
    for shadow, target in shadows:
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as destination:
            if target.stat().st_size:
                with sqlite3.connect(staging / (target.name + ".retained")) as retained:
                    destination.backup(retained)
            with sqlite3.connect(shadow) as source:
                source.backup(destination)
    return {"namespace_count": len(shadows), "native_data_retained": True, "effects_replayed": False}
