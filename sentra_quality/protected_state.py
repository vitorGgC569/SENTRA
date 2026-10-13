"""Owner/workspace CAS projections on the configured authority, never grants.

Ciphertext uses SENTRA's OS codec. PostgreSQL deliberately uses the native
transaction API; it never opens a secondary SQLite authority.
"""
from contextlib import contextmanager
import hashlib
import json
import re
import time

from sentra_core.conversations import _encode, _decode


class StateConflict(PermissionError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise ValueError("untrusted database identifier")
    return '"' + value + '"'


class ProtectedState:
    def __init__(self, *, store, owner, workspace_id, namespace, clock=time.time):
        if not all(isinstance(v, str) and 0 < len(v) <= 256 and "\0" not in v
                   for v in (owner, workspace_id, namespace)):
            raise ValueError("trusted owner/workspace/namespace required")
        self.store, self.owner, self.workspace_id = store, owner, workspace_id
        self.namespace, self.clock = namespace, clock
        self.backend = store.backend
        store.assert_principal(owner)
        db = store.connect("provider_content")
        try:
            with db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS selo_records(
                    owner TEXT NOT NULL, workspace_id TEXT NOT NULL,
                    namespace TEXT NOT NULL, record_key TEXT NOT NULL,
                    revision INTEGER NOT NULL, protected_value TEXT NOT NULL,
                    value_sha256 TEXT NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(owner,workspace_id,namespace,record_key));
                """)
        finally:
            db.close()

    def scoped(self, namespace):
        return ProtectedState(store=self.store, owner=self.owner,
                              workspace_id=self.workspace_id, namespace=namespace,
                              clock=self.clock)

    @contextmanager
    def transaction(self):
        db = self.store.connect("provider_content")
        try:
            if self.backend == "postgres":
                db._begin()
                db.raw.execute("SELECT pg_advisory_xact_lock(%s)",
                               (self.store.lock_key("provider_content"),))
                db._locked = True
            else:
                db.execute("BEGIN IMMEDIATE")
            yield _Transaction(self, db)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, key):
        with self.transaction() as tx:
            return tx.get(key)

    def put(self, key, value, *, expected_revision=None):
        with self.transaction() as tx:
            return tx.put(key, value, expected_revision=expected_revision)

    def records(self, prefix="", *, limit=10000):
        with self.transaction() as tx:
            return tx.records(prefix, limit=limit)


class _Transaction:
    def __init__(self, state, db):
        self.state, self.db = state, db
        self.pg = state.backend == "postgres"
        self.table = (identifier(state.store.schema("provider_content")) + ".selo_records"
                      if self.pg else "selo_records")
        self.scope = (state.owner, state.workspace_id, state.namespace)

    def execute(self, sql, params=(), *, write=False):
        if write and self.pg and self.state.store.member_role == "reader":
            raise PermissionError("tenant reader cannot mutate Selo projections")
        if self.pg:
            return self.db.raw.execute(sql.replace("?", "%s"), params)
        return self.db.execute(sql, params)

    @staticmethod
    def key(key):
        if not isinstance(key, str) or not 1 <= len(key) <= 512 or "\0" in key:
            raise ValueError("invalid projection key")
        return key

    def get(self, key):
        row = self.execute("SELECT revision,protected_value,value_sha256 FROM " +
                           self.table + " WHERE owner=? AND workspace_id=? AND namespace=? AND record_key=?",
                           (*self.scope, self.key(key))).fetchone()
        if row is None:
            return None
        revision, payload, sha = ((row["revision"], row["protected_value"], row["value_sha256"])
                                  if self.pg else tuple(row))
        value = _decode(payload)
        if digest(value) != sha:
            raise StateConflict("protected projection integrity mismatch")
        return {"revision": revision, "value": value}

    def put(self, key, value, *, expected_revision=None):
        key = self.key(key)
        if len(canonical(value).encode()) > 1_000_000:
            raise ValueError("protected projection exceeds bound")
        current = self.get(key)
        if (current["revision"] if current else None) != expected_revision:
            raise StateConflict("projection revision conflict")
        revision = 0 if current is None else current["revision"] + 1
        # Protect BEFORE first persistence. Encryption failure has no plaintext fallback.
        encoded, sha = _encode(value), digest(value)
        self.execute("INSERT INTO " + self.table +
                     "(owner,workspace_id,namespace,record_key,revision,protected_value,value_sha256,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(owner,workspace_id,namespace,record_key) "
                     "DO UPDATE SET revision=excluded.revision,protected_value=excluded.protected_value,"
                     "value_sha256=excluded.value_sha256,updated_at=excluded.updated_at",
                     (*self.scope, key, revision, encoded, sha, self.state.clock()), write=True)
        return revision

    def delete(self, key, *, expected_revision):
        current = self.get(key)
        if current is None or current["revision"] != expected_revision:
            raise StateConflict("projection delete revision conflict")
        self.execute("DELETE FROM " + self.table +
                     " WHERE owner=? AND workspace_id=? AND namespace=? AND record_key=?",
                     (*self.scope, self.key(key)), write=True)

    def records(self, prefix="", *, limit=10000):
        if not isinstance(prefix, str) or type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("invalid projection page")
        # Prefix comparisons deliberately avoid LIKE wildcard interpolation.
        rows = self.execute("SELECT record_key FROM " + self.table +
                            " WHERE owner=? AND workspace_id=? AND namespace=? "
                            "AND substr(record_key,1,?)=? ORDER BY record_key LIMIT ?",
                            (*self.scope, len(prefix), prefix, limit + 1)).fetchall()
        if len(rows) > limit:
            raise StateConflict("projection page bound exceeded; narrow prefix")
        keys = [r["record_key"] if self.pg else r[0] for r in rows]
        return [(key, self.get(key)) for key in keys]
