"""Persistent asynchronous jobs for registered repository operations."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
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
        durable: object | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.config = config
        self.audit = audit
        self.repository = repository
        self.durable = durable
        self.db_path = Path(db_path or (config.state_root / "jobs.sqlite3"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        # All async jobs execute on one durable event loop. Shared async
        # services (RepositoryService, subprocess transports, etc.) must never
        # migrate between per-job loops.
        self.loop = asyncio.new_event_loop()
        self.loop_ready = threading.Event()
        self.tasks: dict[str, Any] = {}
        self.done_events: dict[str, threading.Event] = {}
        self.worker_thread = threading.Thread(
            target=self._loop_main,
            name="sentra-job-loop",
            daemon=True,
        )
        self.worker_thread.start()
        if not self.loop_ready.wait(5):
            raise RuntimeError("job event loop failed to start")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                operation TEXT NOT NULL,
                target TEXT,
                workspace TEXT,
                run_id TEXT,
                operation_id TEXT,
                idempotency_key TEXT,
                producer_pid INTEGER,
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
        existing_columns = {
            str(row["name"]) for row in self.db.execute("PRAGMA table_info(jobs)").fetchall()
        }
        for column in ("run_id", "operation_id", "idempotency_key"):
            if column not in existing_columns:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
        if "producer_pid" not in existing_columns:
            self.db.execute("ALTER TABLE jobs ADD COLUMN producer_pid INTEGER")
        self._recover_stale_jobs()
        self.db.commit()
        self._closed = False

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                proc = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=3,
                    check=False,
                    shell=False,
                )
            except (OSError, subprocess.SubprocessError):
                return False
            output = proc.stdout.strip()
            return proc.returncode == 0 and str(pid) in output and "No tasks" not in output
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _recover_stale_jobs(self) -> None:
        rows = self.db.execute(
            "SELECT id,producer_pid FROM jobs "
            "WHERE state IN ('PENDING','RUNNING','CANCELLING')"
        ).fetchall()
        stale_ids = [
            str(row["id"])
            for row in rows
            if row["producer_pid"] is None or not self._pid_exists(int(row["producer_pid"]))
        ]
        if not stale_ids:
            return
        now = time.time()
        self.db.executemany(
            "UPDATE jobs SET state='INTERRUPTED',"
            "error='producer process is no longer alive',updated=? WHERE id=?",
            [(now, job_id) for job_id in stale_ids],
        )

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
            now = time.time()
            self.db.execute(
                "UPDATE jobs SET state=?,result_json=?,error=?,updated=? WHERE id=?",
                (state, payload, error, now, job_id),
            )
            self.db.commit()
            row = self.db.execute(
                "SELECT owner,run_id,operation_id FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if self.durable is not None and row is not None and row["operation_id"]:
            mapped = {
                "PENDING": "QUEUED",
                "RUNNING": "RUNNING",
                "CANCELLING": "CANCEL_REQUESTED",
                "COMPLETED": "SUCCEEDED",
                "FAILED": "FAILED",
                "CANCELLED": "CANCELLED",
                "INTERRUPTED": "UNCERTAIN",
            }.get(state)
            if mapped is not None:
                try:
                    self.durable.update_operation(
                        str(row["operation_id"]),
                        str(row["owner"]),
                        state=mapped,
                        readiness="PRODUCT_READY" if mapped == "SUCCEEDED" else None,
                        progress={
                            "stage": state,
                            "job_id": job_id,
                            "updated_at": now,
                        },
                        event_type=f"JOB_{state}",
                        result=(
                            json.loads(payload)
                            if mapped == "SUCCEEDED" and payload
                            else None
                        ),
                        error=(
                            {
                                "code": "JOB_INTERRUPTED" if mapped == "UNCERTAIN" else "JOB_FAILED",
                                "message": str(error or "")[:1000],
                            }
                            if mapped in {"FAILED", "UNCERTAIN"} else None
                        ),
                    )
                except Exception:
                    pass
        event = self.done_events.get(job_id)
        if state in _TERMINAL and event is not None:
            event.set()

    def _loop_main(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop_ready.set()
        self.loop.run_forever()
        pending = [item for item in asyncio.all_tasks(self.loop) if not item.done()]
        for item in pending:
            item.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

    async def _run_job(
        self,
        job_id: str,
        owner: str,
        operation: str,
        target: str,
        workspace: str | None,
    ) -> None:
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
            if result.get("passed") is False:
                self._set(
                    job_id,
                    "FAILED",
                    result=result,
                    error=str(result.get("result") or "registered repository operation failed")[:4000],
                )
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

    def _job_done(self, job_id: str, future: Any) -> None:
        with self.lock:
            self.tasks.pop(job_id, None)
            row = self.db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
        if future.cancelled() and row is not None and row["state"] not in _TERMINAL:
            self._set(job_id, "CANCELLED", error="job cancelled")
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
        run_id: str | None = None,
        idempotency_key: str | None = None,
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

        durable_run_id: str | None = None
        operation_id: str | None = None
        key = str(idempotency_key or "").strip() or (
            f"job:{op}:{target or '-'}:{uuid.uuid4().hex}"
        )
        if self.durable is not None:
            if run_id:
                durable_run = self.durable.run_status(run_id, owner)
            else:
                durable_run = self.durable.ensure_implicit_run(
                    owner, workspace=workspace
                )
            durable_run_id = str(durable_run["run_id"])
            durable_operation = self.durable.create_operation(
                durable_run_id,
                owner,
                kind=f"repository.{op.lower()}",
                idempotency_key=key,
            )
            operation_id = str(durable_operation["operation_id"])
            if durable_operation.get("idempotent_replay"):
                with self.lock:
                    row = self.db.execute(
                        "SELECT * FROM jobs WHERE operation_id=? AND owner=? "
                        "ORDER BY created DESC LIMIT 1",
                        (operation_id, owner),
                    ).fetchone()
                if row is not None:
                    data = self._view(row, include_result=row["state"] in _TERMINAL)
                    data["idempotent_replay"] = True
                    return data
                return {
                    "run_id": durable_run_id,
                    "operation_id": operation_id,
                    "idempotency_key": key,
                    "idempotent_replay": True,
                    "state": durable_operation["state"],
                    "semantic_status": (
                        "OPERATION_STILL_RUNNING"
                        if durable_operation["state"]
                        not in {"SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}
                        else durable_operation["state"]
                    ),
                }

        job_id = str(uuid.uuid4())
        now = time.time()
        with self.lock:
            self.db.execute(
                "INSERT INTO jobs(id,owner,operation,target,workspace,run_id,operation_id,"
                "idempotency_key,producer_pid,state,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?, 'PENDING',?,?)",
                (
                    job_id, owner, op, target or None, workspace,
                    durable_run_id, operation_id, key, os.getpid(), now, now,
                ),
            )
            self.db.commit()
            self.done_events[job_id] = threading.Event()
        if self.durable is not None and operation_id:
            try:
                self.durable.update_operation(
                    operation_id,
                    owner,
                    state="STARTING",
                    progress={
                        "stage": "STARTING",
                        "job_id": job_id,
                        "operation": op,
                        "target": target or None,
                    },
                    event_type="JOB_STARTING",
                )
            except Exception:
                pass
        future = asyncio.run_coroutine_threadsafe(
            self._run_job(job_id, owner, op, target, workspace),
            self.loop,
        )
        with self.lock:
            self.tasks[job_id] = future
        future.add_done_callback(lambda item, ident=job_id: self._job_done(ident, item))
        self.audit.emit("job.start", "ok", {
            "job_id": job_id,
            "run_id": durable_run_id,
            "operation_id": operation_id,
            "idempotency_key": key,
            "operation": op,
            "target": target or None,
            "owner": owner,
            "workspace": workspace,
        })
        return {
            "job_id": job_id,
            "run_id": durable_run_id,
            "operation_id": operation_id,
            "idempotency_key": key,
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
            "run_id": row["run_id"],
            "operation_id": row["operation_id"],
            "idempotency_key": row["idempotency_key"],
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
        if data["timed_out"]:
            data["semantic_status"] = "OPERATION_STILL_RUNNING"
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
            task = self.tasks.get(job_id)
        if task is not None:
            task.cancel()
        if self.durable is not None and row["operation_id"]:
            try:
                self.durable.request_cancel(
                    str(row["operation_id"]),
                    owner,
                    side_effect_may_have_started=True,
                )
            except Exception:
                pass
        return {
            "job_id": job_id,
            "run_id": row["run_id"],
            "operation_id": row["operation_id"],
            "state": "CANCELLING",
        }

    def list_jobs(
        self,
        owner: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset must be >=0 and limit must be 1..1000")
        with self.lock:
            total = int(self.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE owner=?", (owner,)
            ).fetchone()[0])
            rows = self.db.execute(
                "SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT ? OFFSET ?",
                (owner, limit, offset),
            ).fetchall()
        items = [self._view(row) for row in rows]
        next_offset = offset + len(items)
        return {
            "items": items,
            "jobs": items,
            "page": {
                "offset": offset,
                "limit": limit,
                "returned": len(items),
                "total": total,
                "next_offset": next_offset if next_offset < total else None,
            },
        }

    def close(self) -> None:
        self._closed = True
        with self.lock:
            tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        deadline = time.monotonic() + 5
        for task in tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                task.result(timeout=remaining)
            except Exception:
                pass
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
        with self.lock:
            self.db.close()
