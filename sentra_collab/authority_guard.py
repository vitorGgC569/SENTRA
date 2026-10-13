"""Atomic cross-namespace read guards for the configured central store."""
import re

ALIASES = {"auth": "authorization", "gov": "governance", "core": "durable"}


def begin_authority_guard(db, store, durable_path, *, owner):
    if getattr(store, "backend", "sqlite") == "postgres":
        store.assert_principal(owner)
        # Same globally sorted namespace lock order as native backup. Keep the
        # membership row locked through commit so tenant revoke cannot race CAS.
        db._begin()
        for namespace in sorted({*ALIASES.values(), "canvas_collaboration"}):
            db.raw.execute("SELECT pg_advisory_xact_lock(%s)", (store.lock_key(namespace),))
        db._locked = True  # this transaction already holds its namespace lock
        row = db.raw.execute("SELECT role FROM sentra_admin.memberships WHERE tenant_id=%s AND principal_id=%s AND revoked=false FOR UPDATE",
                             (store.tenant_id, store.principal_id)).fetchone()
        if not row:
            raise PermissionError("collaboration tenant membership revoked")
        db._collaboration_member_role = row["role"]
        return row["role"]
    for alias, namespace in ALIASES.items():
        path = durable_path if alias == "core" else store.path_for(namespace)
        db.execute("ATTACH DATABASE ? AS " + alias, (str(path),))
    db.execute("BEGIN IMMEDIATE")
    return "operator"


def guard_query(db, store, sql, parameters=()):
    if getattr(store, "backend", "sqlite") == "postgres":
        for alias, namespace in ALIASES.items():
            schema = store.schema(namespace)
            if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
                raise ValueError("invalid authority schema")
            sql = sql.replace(alias + ".", '"' + schema + '".')
        if sql.lstrip().upper().startswith("SELECT"):
            sql += " FOR UPDATE"
        # All contributing namespaces remain locked until the caller commits.
    return db.execute(sql, parameters)
