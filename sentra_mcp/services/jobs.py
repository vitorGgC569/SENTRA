"""Persistent asynchronous jobs for registered repository operations."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..audit import AuditLogger
from ..config import MCPConfig
from .repository import RepositoryService

_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}


class JobService:
    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger,
        repository: RepositoryService,
        *,
        db_path: Path | None = None,
    ) -> None:
        self.config = config
        self.audit = audit
        self.repository = repository
        self.db_path = Path(db_path or (config.allowed_roots[0] / ".sentra" / "jobs.sqlite3"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.loops: dict[str, asyncio.AbstractEventLoop] = {}
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.done_events: dict[str, threading.Event] = {}
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                operation TEXT NOT NULL,
                target TEXT,
                workspace TEXT,
                state TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_owner_created
                ON jobs(owner, created DESC);
            """
        )
        self.db.execute(
            "UPDATE jobs SET state='INTERRUPTED',error='server restarted during job',updated=? "
            "WHERE state IN ('PENDING','RUNNING','CANCELLING')",
            (time.time(),),
        )
        self.db.commit()
        self._closed = False

    def update_config(self, config: MCPConfig) -> None:
        self.config = config

    def _set(
        self,
        job_id: str,
        state: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        payload = None
        if result is not None:
            payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            if len(payload.encode("utf-8")) > self.config.max_output_bytes:
                payload = json.dumps({
                    "operation": result.get("operation"),
                    "passed": result.get("passed"),
                    "workspace": result.get("workspace"),
                    "workspace_alias": result.get("workspace_alias"),
                    "result": str(result.get("result", ""))[: self.config.max_output_bytes // 2],
                    "output_truncated": True,
                }, ensure_ascii=False)
        with self.lock:
            self.db.execute(
                "UPDATE jobs SET state=?,result_json=?,error=?,updated=? WHERE id=?",
                (state, payload, error, time.time(), job_id),
            )
            self.db.commit()
        event = self.done_events.get(job_id)
        if state in _TERMINAL and event is not None:
            event.set()

    def _thread_main(
        self,
        job_id: str,
        owner: str,
        operation: str,
        target: str,
        workspace: str | None,
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self.lock:
            self.loops[job_id] = loop
        async def runner() -> None:
            self._set(job_id, "RUNNING")
            try:
                result = await self.repository.run_registered(
                    operation,
                    target,
                    workspace,
                    owner,
                )
            except asyncio.CancelledError:
                self._set(job_id, "CANCELLED", error="job cancelled")
                raise
            except Exception as exc:
                self._set(job_id, "FAILED", error=str(exc)[:4000])
            else:
                self._set(job_id, "COMPLETED", result=result)
                self.audit.emit(
                    "job.complete",
                    "ok" if result.get("passed") else "failed",
                    {
                        "job_id": job_id,
                        "operation": operation,
                        "owner": owner,
                        "workspace": workspace,
                    },
                )

        task = loop.create_task(runner())
        with self.lock:
            self.tasks[job_id] = task
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            pending = [item for item in asyncio.all_tasks(loop) if not item.done()]
            for item in pending:
                item.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            with self.lock:
                self.loops.pop(job_id, None)
                self.tasks.pop(job_id, None)
                self.threads.pop(job_id, None)
            event = self.done_events.get(job_id)
            if event:
                event.set()

    def start(
        self,
        operation: str,
        owner: str,
        *,
        target: str = "",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("job service is shut down")
        op = str(operation).strip().upper()
        if op not in {"TEST", "LINT", "TYPECHECK", "BUILD", "BENCH"}:
            raise ValueError("operation must be TEST, LINT, TYPECHECK, BUILD or BENCH")
        if op == "TEST":
            target = (target or "all").strip()
        elif target:
            raise ValueError(f"{op} does not accept a target")
        job_id = str(uuid.uuid4())
        now = time.time()
        with self.lock:
            self.db.execute(
                "INSERT INTO jobs(id,owner,operation,target,workspace,state,created,updated) "
                "VALUES(?,?,?,?,?,'PENDING',?,?)",
                (job_id, owner, op, target or None, workspace, now, now),
            )
            self.db.commit()
            self.done_events[job_id] = threading.Event()
        thread = threading.Thread(
            target=self._thread_main,
            args=(job_id, owner, op, target, workspace),
            name=f"sentra-job-{job_id[:8]}",
            daemon=True,
        )
        with self.lock:
            self.threads[job_id] = thread
        thread.start()
        self.audit.emit("job.start", "ok", {
            "job_id": job_id,
            "operation": op,
            "target": target or None,
            "owner": owner,
            "workspace": workspace,
        })
        return {
            "job_id": job_id,
            "state": "PENDING",
            "operation": op,
            "target": target or None,
            "workspace": workspace,
        }

    def _row(self, job_id: str, owner: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("job not found")
        if row["owner"] != owner:
            raise PermissionError("job belongs to another MCP session")
        return row

    @staticmethod
    def _view(row: sqlite3.Row, *, include_result: bool = False) -> dict[str, Any]:
        data = {
            "job_id": row["id"],
            "operation": row["operation"],
            "target": row["target"],
            "workspace": row["workspace"],
            "state": row["state"],
            "error": row["error"],
            "created": row["created"],
            "updated": row["updated"],
        }
        if include_result:
            data["result"] = json.loads(row["result_json"]) if row["result_json"] else None
        return data

    def status(self, job_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            return self._view(self._row(job_id, owner))

    def result(self, job_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            row = self._row(job_id, owner)
            if row["state"] not in _TERMINAL:
                raise RuntimeError("job is not finished")
            return self._view(row, include_result=True)

    def wait(
        self,
        job_id: str,
        owner: str,
        timeout_s: float = 5.0,
    ) -> dict[str, Any]:
        if not 0 < timeout_s <= 25:
            raise ValueError("timeout_s must be >0 and <=25")
        with self.lock:
            row = self._row(job_id, owner)
            if row["state"] in _TERMINAL:
                data = self._view(row, include_result=True)
                data["timed_out"] = False
                return data
            event = self.done_events.setdefault(job_id, threading.Event())
        finished = event.wait(timeout_s)
        with self.lock:
            row = self._row(job_id, owner)
            data = self._view(row, include_result=row["state"] in _TERMINAL)
        data["timed_out"] = not finished and row["state"] not in _TERMINAL
        data["next_poll_after_ms"] = (
            250 if row["state"] not in _TERMINAL else None
        )
        return data

    def cancel(self, job_id: str, owner: str) -> dict[str, Any]:
        with self.lock:
            row = self._row(job_id, owner)
            if row["state"] in _TERMINAL:
                return self._view(row)
            self.db.execute(
                "UPDATE jobs SET state='CANCELLING',updated=? WHERE id=?",
                (time.time(), job_id),
            )
            self.db.commit()
            loop = self.loops.get(job_id)
            task = self.tasks.get(job_id)
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)
        return {
            "job_id": job_id,
            "state": "CANCELLING",
        }

    def list_jobs(self, owner: str, limit: int = 100) -> dict[str, Any]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
        return {"jobs": [self._view(row) for row in rows]}

    def close(self) -> None:
        self._closed = True
        with self.lock:
            jobs = [
                (job_id, loop, self.tasks.get(job_id))
                for job_id, loop in self.loops.items()
            ]
        for job_id, loop, task in jobs:
            if task is not None:
                loop.call_soon_threadsafe(task.cancel)
        for thread in list(self.threads.values()):
            thread.join(timeout=5)
        with self.lock:
            self.db.close()
