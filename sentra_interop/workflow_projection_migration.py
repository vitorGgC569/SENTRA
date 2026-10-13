"""Explicit quiesced migration of legacy projections, never authority tables."""
import hashlib
import re
import sqlite3
from pathlib import Path
from .workflow_storage import projection_db, projection_path


ALLOWED = re.compile(r"(?:wf_[a-z_]+|ap_[a-z_]+|rt_[a-z_]+|workflows|steps|channel_(?:workflow_routes|dispatch_intents|subscriptions|inbound_events|outbound|senders)|routine_workflow_[a-z_]+|nats_workflow_events)")
IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")


def import_legacy_projection(control, *, owner, database, workspace, file_sha256,
                             operator_approved=False, quiesced=False):
    """Root/Vitra supplies a pinned snapshot and creates destination schemas first.

    Original bytes and local authority are untouched. Scoped projection rows
    only are copied to the configured store. Conflict aborts the transaction;
    a repeated identical snapshot is a no-op. No provider, command or input runs.
    """
    if operator_approved is not True or quiesced is not True:
        raise PermissionError("host-approved quiesced projection migration required")
    path = Path(projection_path(database, workspace, control=control))
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != file_sha256:
        raise ValueError("legacy projection snapshot digest mismatch")
    source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    copied = 0
    try:
        names = [row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if any(not ALLOWED.fullmatch(name) for name in names if not name.startswith("sqlite_")):
            raise ValueError("snapshot contains non-projection or unknown tables")
        with projection_db(database, control=control) as destination:
            destination.execute("BEGIN IMMEDIATE")
            for name in names:
                if name.startswith("sqlite_"):
                    continue
                fields = source.execute("PRAGMA table_info(" + name + ")").fetchall()
                columns = [field["name"] for field in fields]
                primary = [field["name"] for field in sorted(fields, key=lambda field: field["pk"]) if field["pk"]]
                if not primary or not all(IDENTIFIER.fullmatch(field) for field in columns):
                    raise ValueError("projection columns/primary identity unavailable")
                for row in source.execute("SELECT * FROM " + name):
                    record = dict(row)
                    if "owner" in record and record["owner"] != owner:
                        raise PermissionError("legacy projection owner differs")
                    work_item = record.get("work_item") or record.get("work_item_id")
                    if work_item:
                        item = control.work_item_info(work_item, owner)
                        if record.get("run_id") and item["run_id"] != record["run_id"]:
                            raise PermissionError("legacy projection references another Run")
                    where = " AND ".join(field + "=?" for field in primary)
                    existing = destination.execute("SELECT " + ",".join(columns) + " FROM " + name + " WHERE " + where,
                        tuple(record[field] for field in primary)).fetchone()
                    values = tuple(record[field] for field in columns)
                    if existing is not None:
                        if tuple(existing[column] for column in columns) != values:
                            raise ValueError("configured projection conflicts with legacy snapshot")
                        continue
                    destination.execute("INSERT INTO " + name + "(" + ",".join(columns) + ") VALUES(" +
                        ",".join("?" for _ in columns) + ")", values)
                    copied += 1
            if hashlib.sha256(path.read_bytes()).hexdigest() != file_sha256:
                raise ValueError("legacy projection changed while quiesced")
    finally:
        source.close()
    return {"source_sha256": file_sha256, "rows_copied": copied,
            "backend": control.store.backend, "effects_replayed": False, "source_preserved": True}
