"""Workflow projections borrow the configured authority store, never fork it."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import hashlib
import re


class ProjectionConnection:
    """Keep the original per-file logical partition in a shared native store."""
    def __init__(self, connection, database):
        self.connection = connection
        self.prefix = "pulso_" + hashlib.sha256(str(Path(database).resolve()).encode()).hexdigest()[:20] + "_"

    def execute(self, sql, parameters=()):
        # Rewrite table identifiers only; quoted SQL values remain untouched.
        tokens = re.split(r"('(?:''|[^'])*')", sql)
        pattern = r"\b(?:wf_[a-z_]+|ap_[a-z_]+|rt_[a-z_]+|channel_workflow_routes|channel_dispatch_intents|channel_subscriptions|channel_inbound_events|channel_outbound|channel_senders|routine_workflow_[a-z_]+|nats_workflow_events|workflows|steps)\b"
        for index in range(0, len(tokens), 2):
            tokens[index] = re.sub(pattern, lambda match: self.prefix + match.group(), tokens[index])
        return self.connection.execute("".join(tokens), parameters)

    def __getattr__(self, name):
        return getattr(self.connection, name)


@contextmanager
def projection_db(database, *, control=None, store=None, namespace="execution_workspace"):
    configured = store if store is not None else getattr(control, "store", None)
    if configured is not None:
        connection = configured.connect(namespace)
    else:
        connection = sqlite3.connect(str(database), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
    try:
        with connection:
            yield ProjectionConnection(connection, database) if configured is not None and database is not None else connection
    finally:
        connection.close()


def projection_path(database, workspace, *, control=None, store=None):
    target, root = Path(database).resolve(), Path(workspace).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("projection outside workspace")
    configured = store if store is not None else getattr(control, "store", None)
    if configured is None:
        target.parent.mkdir(parents=True, exist_ok=True)
    return str(target)


def ensure_column(db, table, column, definition):
    if not all(re.fullmatch(r"[a-z_][a-z0-9_]*", value) for value in (table, column)):
        raise ValueError("trusted projection schema names required")
    connection = getattr(db, "connection", db)
    if getattr(connection, "raw", None) is not None:
        physical = getattr(db, "prefix", "") + table
        exists = connection.raw.execute("SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s AND column_name=%s",
            (connection.schema, physical, column)).fetchone()
    else:
        exists = column in {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")}
    if not exists:
        db.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + definition)
