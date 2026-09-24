"""Persistent asynchronous search sessions for approved workspaces."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from workspace.paths import iter_workspace_files, resolve_workspace_path

from ..audit import AuditLogger
from ..config import MCPConfig
from .workspaces import WorkspaceRegistry


class SearchSessionService:
    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger,
        workspaces: WorkspaceRegistry | None = None,
        *,
        durable: object | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.config = config
        self.audit = audit
        self.workspaces = workspaces
        self.durable = durable
        self.db_path = Path(db_path or (config.state_root / "searches.sqlite3"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.stops: dict[str, threading.Event] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS searches(
                id TEXT PRIMARY KEY,
                root_index INTEGER NOT NULL DEFAULT 0,
                owner TEXT NOT NULL DEFAULT 'legacy',
                workspace_id TEXT NOT NULL DEFAULT '',
                workspace_alias TEXT NOT NULL DEFAULT '',
                workspace_path TEXT NOT NULL DEFAULT '',
                run_id TEXT,
                operation_id TEXT,
                idempotency_key TEXT,
                scope TEXT NOT NULL,
                pattern TEXT NOT NULL,
                search_type TEXT NOT NULL,
                literal INTEGER NOT NULL,
                ignore_case INTEGER NOT NULL,
                context INTEGER NOT NULL,
                max_results INTEGER NOT NULL,
                max_files INTEGER NOT NULL,
                state TEXT NOT NULL,
                files_scanned INTEGER NOT NULL DEFAULT 0,
                matches INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS search_results(
                search_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(search_id,seq)
            );
            """
        )
        columns = {str(row[1]) for row in self.db.execute("PRAGMA table_info(searches)").fetchall()}
        migrations = {
            "owner": "TEXT NOT NULL DEFAULT 'legacy'",
            "workspace_id": "TEXT NOT NULL DEFAULT ''",
            "workspace_alias": "TEXT NOT NULL DEFAULT ''",
            "workspace_path": "TEXT NOT NULL DEFAULT ''",
            "run_id": "TEXT",
            "operation_id": "TEXT",
            "idempotency_key": "TEXT",
        }
        for name, ddl in migrations.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE searches ADD COLUMN {name} {ddl}")
        self.db.execute(
            "UPDATE searches SET state='INTERRUPTED',error='server restarted during search' "
            "WHERE state IN ('RUNNING','CANCELLING')"
        )
        self.db.commit()
        self._recover_interrupted_durable_operations()

    def _recover_interrupted_durable_operations(self) -> None:
        if self.durable is None:
            return
        with self.lock:
            rows = self.db.execute(
                "SELECT owner,operation_id,id,state FROM searches "
                "WHERE state='INTERRUPTED' AND operation_id IS NOT NULL"
            ).fetchall()
        for row in rows:
            try:
                current = self.durable.operation_status(
                    str(row["operation_id"]), str(row["owner"])
                )
                if current["state"] in {"SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}:
                    continue
                self.durable.update_operation(
                    str(row["operation_id"]),
                    str(row["owner"]),
                    state="UNCERTAIN",
                    progress={
                        "stage": "INTERRUPTED",
                        "search_id": str(row["id"]),
                        "reason": "server restarted while search was active",
                    },
                    event_type="SEARCH_INTERRUPTED",
                    error={
                        "code": "SEARCH_INTERRUPTED",
                        "message": "server restarted while search was active; no automatic replay",
                    },
                )
            except Exception:
                pass

    def _durable_update(
        self,
        search_id: str,
        *,
        state: str | None = None,
        readiness: str | None = None,
        stage: str,
        files_scanned: int | None = None,
        matches: int | None = None,
        event_type: str = "SEARCH_PROGRESS",
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        if self.durable is None:
            return
        with self.lock:
            row = self.db.execute(
                "SELECT owner,operation_id FROM searches WHERE id=?",
                (search_id,),
            ).fetchone()
        if row is None or not row["operation_id"]:
            return
        progress: dict[str, Any] = {"stage": stage, "search_id": search_id}
        if files_scanned is not None:
            progress["files_scanned"] = int(files_scanned)
        if matches is not None:
            progress["matches"] = int(matches)
        try:
            self.durable.update_operation(
                str(row["operation_id"]),
                str(row["owner"]),
                state=state,
                readiness=readiness,
                progress=progress,
                event_type=event_type,
                result=result,
                error=error,
            )
        except Exception:
            pass

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "search_id": row["id"],
            "run_id": row["run_id"],
            "operation_id": row["operation_id"],
            "idempotency_key": row["idempotency_key"],
            "state": row["state"],
            "files_scanned": row["files_scanned"],
            "matches": row["matches"],
            "error": row["error"],
            "workspace_id": row["workspace_id"],
            "workspace_alias": row["workspace_alias"],
            "workspace_path": row["workspace_path"],
            "scope": row["scope"],
            "pattern": row["pattern"],
            "search_type": row["search_type"],
            "created": row["created"],
            "updated": row["updated"],
        }

    def update_config(self, config: MCPConfig) -> None:
        self.config = config
        if self.workspaces is not None:
            self.workspaces.update_config(config)

    def close(self) -> None:
        for event in list(self.stops.values()):
            event.set()
        for thread in list(self.threads.values()):
            thread.join(timeout=5)
        with self.lock:
            self.db.close()

    def _workspace(
        self,
        path: str,
        workspace: str | None,
        owner: str,
    ) -> tuple[int, Path, str, dict[str, Any]]:
        candidate = Path(path)
        if self.workspaces is not None:
            if workspace:
                view = self.workspaces.resolve(workspace, owner, "read")
            elif candidate.is_absolute():
                view = self.workspaces.resolve_path(candidate, owner, "read")
            else:
                view = self.workspaces.resolve(None, owner, "read")
            root = Path(view["path"]).resolve()
            index = int(str(view["id"]).split(":", 1)[1])
        else:
            roots = tuple(Path(root).resolve() for root in self.config.allowed_roots)
            if candidate.is_absolute():
                selected = next(
                    (
                        (idx, root)
                        for idx, root in enumerate(roots)
                        if candidate.resolve() == root or root in candidate.resolve().parents
                    ),
                    None,
                )
                if selected is None:
                    raise PermissionError("search path is outside configured roots")
                index, root = selected
            else:
                index, root = 0, roots[0]
            view = {
                "id": f"root:{index}",
                "workspace_id": f"config:{index}",
                "alias": "sentra" if index == 0 else root.name,
                "path": str(root),
            }
        if candidate.is_absolute():
            rel = candidate.resolve().relative_to(root).as_posix() or "."
        else:
            rel = path
        checked = resolve_workspace_path(root, rel)
        return index, root, checked.relative_to(root).as_posix() or ".", view

    def start(
        self,
        path: str,
        pattern: str,
        *,
        owner: str,
        workspace: str | None = None,
        search_type: str = "names",
        literal: bool = True,
        ignore_case: bool = True,
        context: int = 0,
        max_results: int = 10000,
        max_files: int = 100000,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not owner.strip():
            raise ValueError("owner is required")
        if search_type not in {"names", "content"}:
            raise ValueError("search_type must be names or content")
        if not pattern or len(pattern) > 4096:
            raise ValueError("search pattern must be 1..4096 characters")
        if context < 0 or context > 20:
            raise ValueError("context must be between 0 and 20")
        if not 1 <= max_results <= 100000:
            raise ValueError("max_results must be between 1 and 100000")
        if not 1 <= max_files <= 500000:
            raise ValueError("max_files must be between 1 and 500000")
        if not literal:
            re.compile(pattern)

        root_index, root, scope, view = self._workspace(path, workspace, owner)
        durable_run_id: str | None = None
        operation_id: str | None = None
        key = str(idempotency_key or "").strip() or (
            f"search:{search_type}:{uuid.uuid4().hex}"
        )
        if self.durable is not None:
            if run_id:
                durable_run = self.durable.run_status(run_id, owner)
            else:
                durable_run = self.durable.ensure_implicit_run(
                    owner, workspace=str(view["id"])
                )
            durable_run_id = str(durable_run["run_id"])
            operation = self.durable.create_operation(
                durable_run_id,
                owner,
                kind="search.scan",
                idempotency_key=key,
            )
            operation_id = str(operation["operation_id"])
            if operation.get("idempotent_replay"):
                with self.lock:
                    row = self.db.execute(
                        "SELECT * FROM searches WHERE operation_id=? AND owner=? "
                        "ORDER BY created DESC LIMIT 1",
                        (operation_id, owner),
                    ).fetchone()
                if row is not None:
                    data = self._summary(row)
                    data["idempotent_replay"] = True
                    return data
                if operation["state"] not in {
                    "SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"
                }:
                    try:
                        operation = self.durable.update_operation(
                            operation_id,
                            owner,
                            state="UNCERTAIN",
                            progress={
                                "stage": "UNCERTAIN",
                                "reason": "operation exists but search row is absent",
                            },
                            event_type="SEARCH_CORRELATION_LOST",
                            error={
                                "code": "SEARCH_CORRELATION_LOST",
                                "message": (
                                    "durable operation exists but persisted search "
                                    "state cannot prove whether scanning started"
                                ),
                            },
                        )
                    except Exception:
                        operation = self.durable.operation_status(
                            operation_id, owner
                        )
                return {
                    "run_id": durable_run_id,
                    "operation_id": operation_id,
                    "idempotency_key": key,
                    "idempotent_replay": True,
                    "state": operation["state"],
                    "semantic_status": (
                        operation["state"]
                        if operation["state"] in {
                            "SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"
                        }
                        else "OPERATION_STILL_RUNNING"
                    ),
                }

        search_id = str(uuid.uuid4())
        now = time.time()
        with self.lock:
            self.db.execute(
                "INSERT INTO searches("
                "id,root_index,owner,workspace_id,workspace_alias,workspace_path,"
                "run_id,operation_id,idempotency_key,scope,pattern,"
                "search_type,literal,ignore_case,context,max_results,max_files,state,created,updated"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'RUNNING',?,?)",
                (
                    search_id,
                    root_index,
                    owner,
                    view["workspace_id"],
                    view["alias"],
                    str(root),
                    durable_run_id,
                    operation_id,
                    key,
                    scope,
                    pattern,
                    search_type,
                    int(literal),
                    int(ignore_case),
                    context,
                    max_results,
                    max_files,
                    now,
                    now,
                ),
            )
            self.db.commit()

        if self.durable is not None and operation_id:
            try:
                self.durable.update_operation(
                    operation_id,
                    owner,
                    state="STARTING",
                    progress={
                        "stage": "STARTING",
                        "search_id": search_id,
                        "scope": scope,
                        "search_type": search_type,
                    },
                    event_type="SEARCH_STARTING",
                )
            except Exception:
                pass

        stop = threading.Event()
        self.stops[search_id] = stop
        thread = threading.Thread(
            target=self._worker,
            args=(
                search_id, root, scope, pattern, search_type, literal,
                ignore_case, context, max_results, max_files, stop,
            ),
            name=f"sentra-search-{search_id[:8]}",
            daemon=True,
        )
        self.threads[search_id] = thread
        thread.start()
        self.audit.emit("search.start", "ok", {
            "search_id": search_id,
            "run_id": durable_run_id,
            "operation_id": operation_id,
            "idempotency_key": key,
            "scope": scope,
            "type": search_type,
            "owner": owner,
            "workspace": view["id"],
            "workspace_alias": view["alias"],
        })
        return {
            "search_id": search_id,
            "run_id": durable_run_id,
            "operation_id": operation_id,
            "idempotency_key": key,
            "state": "RUNNING",
            "workspace": view["id"],
            "workspace_id": view["workspace_id"],
            "workspace_alias": view["alias"],
        }

    def _append(self, search_id: str, payload: dict[str, Any]) -> None:
        with self.lock:
            seq = self.db.execute(
                "SELECT COALESCE(MAX(seq),-1)+1 FROM search_results WHERE search_id=?",
                (search_id,),
            ).fetchone()[0]
            self.db.execute(
                "INSERT INTO search_results(search_id,seq,payload) VALUES(?,?,?)",
                (search_id, seq, json.dumps(payload, ensure_ascii=False)),
            )
            self.db.execute(
                "UPDATE searches SET matches=matches+1,updated=? WHERE id=?",
                (time.time(), search_id),
            )
            self.db.commit()

    @staticmethod
    def _matches(text: str, pattern: str, literal: bool, ignore_case: bool) -> bool:
        if literal:
            return pattern.casefold() in text.casefold() if ignore_case else pattern in text
        return re.search(pattern, text, re.IGNORECASE if ignore_case else 0) is not None

    def _worker(
        self,
        search_id: str,
        root: Path,
        scope: str,
        pattern: str,
        search_type: str,
        literal: bool,
        ignore_case: bool,
        context: int,
        max_results: int,
        max_files: int,
        stop: threading.Event,
    ) -> None:
        scanned = 0
        matches = 0
        state = "COMPLETED"
        error = None
        last_progress = 0.0
        self._durable_update(
            search_id,
            state="RUNNING",
            stage="SEARCHING",
            files_scanned=0,
            matches=0,
            event_type="SEARCH_RUNNING",
        )
        try:
            for file_path in iter_workspace_files(root, scope, max_files=max_files):
                if stop.is_set():
                    state = "CANCELLED"
                    break
                scanned += 1
                rel = file_path.relative_to(root).as_posix()
                if search_type == "names":
                    if self._matches(rel, pattern, literal, ignore_case):
                        self._append(search_id, {"path": rel})
                        matches += 1
                else:
                    try:
                        if file_path.stat().st_size > self.config.max_read_bytes:
                            continue
                        lines = file_path.read_text(encoding="utf-8").splitlines()
                    except (OSError, UnicodeDecodeError):
                        continue
                    for idx, line in enumerate(lines):
                        if self._matches(line, pattern, literal, ignore_case):
                            item: dict[str, Any] = {
                                "path": rel,
                                "line": idx + 1,
                                "text": line,
                            }
                            if context:
                                lo = max(0, idx - context)
                                hi = min(len(lines), idx + context + 1)
                                item["context"] = [
                                    {"line": pos + 1, "text": lines[pos]}
                                    for pos in range(lo, hi)
                                ]
                            self._append(search_id, item)
                            matches += 1
                            if matches >= max_results:
                                break
                now = time.monotonic()
                with self.lock:
                    self.db.execute(
                        "UPDATE searches SET files_scanned=?,updated=? WHERE id=?",
                        (scanned, time.time(), search_id),
                    )
                    self.db.commit()
                if scanned == 1 or scanned % 100 == 0 or now - last_progress >= 0.5:
                    self._durable_update(
                        search_id,
                        stage="SEARCHING",
                        files_scanned=scanned,
                        matches=matches,
                        event_type="SEARCH_PROGRESS",
                    )
                    last_progress = now
                if matches >= max_results:
                    state = "LIMIT_REACHED"
                    break
        except Exception as exc:
            state = "FAILED"
            error = str(exc)[:1000]
        finally:
            with self.lock:
                self.db.execute(
                    "UPDATE searches SET state=?,files_scanned=?,matches=?,error=?,updated=? WHERE id=?",
                    (state, scanned, matches, error, time.time(), search_id),
                )
                self.db.commit()

            if state in {"COMPLETED", "LIMIT_REACHED"}:
                self._durable_update(
                    search_id,
                    state="SUCCEEDED",
                    readiness="PRODUCT_READY",
                    stage=state,
                    files_scanned=scanned,
                    matches=matches,
                    event_type=f"SEARCH_{state}",
                    result={
                        "search_id": search_id,
                        "state": state,
                        "files_scanned": scanned,
                        "matches": matches,
                    },
                )
            elif state == "CANCELLED":
                self._durable_update(
                    search_id,
                    state="CANCELLED",
                    stage="CANCELLED",
                    files_scanned=scanned,
                    matches=matches,
                    event_type="SEARCH_CANCELLED",
                )
            else:
                self._durable_update(
                    search_id,
                    state="FAILED",
                    stage="FAILED",
                    files_scanned=scanned,
                    matches=matches,
                    event_type="SEARCH_FAILED",
                    error={
                        "code": "SEARCH_FAILED",
                        "message": str(error or "search failed")[:1000],
                    },
                )
            self.stops.pop(search_id, None)
            self.threads.pop(search_id, None)

    def _owned_row(self, search_id: str, owner: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("search session not found")
        if row["owner"] not in {owner, "legacy"}:
            raise PermissionError("search session belongs to another MCP session")
        return row

    @staticmethod
    def _meta(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "workspace_id": row["workspace_id"],
            "workspace_alias": row["workspace_alias"],
            "workspace_path": row["workspace_path"],
        }

    def get_results(
        self,
        search_id: str,
        owner: str,
        offset: int = 0,
        length: int = 100,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= length <= 1000:
            raise ValueError("invalid result page")
        with self.lock:
            row = self._owned_row(search_id, owner)
            results = self.db.execute(
                "SELECT payload FROM search_results WHERE search_id=? AND seq>=? ORDER BY seq LIMIT ?",
                (search_id, offset, length),
            ).fetchall()
            payloads = [json.loads(item["payload"]) for item in results]
            total = int(self.db.execute(
                "SELECT COUNT(*) FROM search_results WHERE search_id=?",
                (search_id,),
            ).fetchone()[0])
            next_offset = offset + len(payloads)
            next_offset = next_offset if next_offset < total else None
            return {
                "search_id": search_id,
                "run_id": row["run_id"],
                "operation_id": row["operation_id"],
                "idempotency_key": row["idempotency_key"],
                "state": row["state"],
                "files_scanned": row["files_scanned"],
                "matches": row["matches"],
                "error": row["error"],
                "offset": offset,
                "returned": len(payloads),
                "next_offset": next_offset,
                "next_poll_after_ms": 100 if row["state"] in {"RUNNING", "CANCELLING"} else None,
                "items": payloads,
                "results": payloads,
                "page": {
                    "offset": offset,
                    "limit": length,
                    "returned": len(payloads),
                    "total": total,
                    "next_offset": next_offset,
                },
                **self._meta(row),
            }

    def list_searches(
        self,
        owner: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset must be >=0 and limit must be 1..1000")
        with self.lock:
            total = int(self.db.execute(
                "SELECT COUNT(*) FROM searches WHERE owner IN (?, 'legacy')",
                (owner,),
            ).fetchone()[0])
            rows = self.db.execute(
                "SELECT id,owner,workspace_id,workspace_alias,workspace_path,"
                "run_id,operation_id,idempotency_key,scope,pattern,"
                "search_type,state,files_scanned,matches,error,created,updated "
                "FROM searches WHERE owner IN (?, 'legacy') "
                "ORDER BY created DESC LIMIT ? OFFSET ?",
                (owner, limit, offset),
            ).fetchall()
        items = [dict(row) for row in rows]
        next_offset = offset + len(items)
        return {
            "items": items,
            "searches": items,
            "page": {
                "offset": offset,
                "limit": limit,
                "returned": len(items),
                "total": total,
                "next_offset": next_offset if next_offset < total else None,
            },
        }

    def stop(self, search_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            row = self._owned_row(search_id, owner)
            if row["state"] != "RUNNING":
                return self._summary(row)
            event = self.stops.get(search_id)
            if event:
                event.set()
            self.db.execute(
                "UPDATE searches SET state='CANCELLING',updated=? WHERE id=?",
                (time.time(), search_id),
            )
            self.db.commit()
            data = self._summary(
                self.db.execute(
                    "SELECT * FROM searches WHERE id=?", (search_id,)
                ).fetchone()
            )
        if self.durable is not None and row["operation_id"]:
            try:
                self.durable.request_cancel(
                    str(row["operation_id"]),
                    owner,
                    side_effect_may_have_started=True,
                )
            except Exception:
                pass
        return data
