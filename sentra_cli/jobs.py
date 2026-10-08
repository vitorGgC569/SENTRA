"""Detached background jobs for long-running SENTRA CLI operations."""
from __future__ import annotations

import contextlib
import io
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .tools import run_registered, run_tests

_TERMINAL = {"SUCCEEDED", "FAILED"}


def _now() -> float:
    return time.time()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        path.name
        + f".tmp-{os.getpid()}-{secrets.token_hex(2)}"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _job_dir(workspace: Path) -> Path:
    return workspace / ".sentra" / "cli-jobs"


class BackgroundJobManager:
    """Spawn durable detached workers and expose bounded status summaries."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = _job_dir(self.workspace)
        self._notified: set[str] = set()
        # Do not replay every historical completion when a new CLI session
        # starts. Jobs still running at startup remain eligible for a future
        # completion notice.
        if self.root.is_dir():
            for path in self.root.glob("job-*.json"):
                try:
                    data = _read(path)
                except Exception:
                    continue
                if str(data.get("state") or "") in _TERMINAL:
                    self._notified.add(
                        str(data.get("job_id") or path.stem)
                    )

    def submit(
        self,
        operation: str,
        raw_args: str = "",
        *,
        timeout: float = 180.0,
    ) -> str:
        operation = operation.upper().strip()
        if operation not in {"TEST", "LINT", "TYPECHECK", "BUILD", "BENCH"}:
            return f"Error: operation {operation!r} is not background-capable"

        job_id = (
            time.strftime("job-%Y%m%d-%H%M%S-")
            + secrets.token_hex(3)
        )
        path = self.root / f"{job_id}.json"
        record: dict[str, Any] = {
            "version": 1,
            "job_id": job_id,
            "operation": operation,
            "raw_args": raw_args,
            "workspace": str(self.workspace),
            "state": "QUEUED",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "pid": None,
            "result": None,
            "error": None,
        }
        _atomic_write(path, record)

        if getattr(sys, "frozen", False):
            command = [sys.executable, "--job-worker", str(path)]
        else:
            command = [
                sys.executable,
                "-B",
                "-m",
                "sentra_cli",
                "--job-worker",
                str(path),
            ]

        flags = 0
        if os.name == "nt":
            flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.workspace),
                env={
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                    "SENTRA_CLI_JOB_TIMEOUT": str(max(timeout, 1.0)),
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                start_new_session=(os.name != "nt"),
            )
        except Exception as exc:
            record["state"] = "FAILED"
            record["finished_at"] = _now()
            record["error"] = f"{type(exc).__name__}: {exc}"
            _atomic_write(path, record)
            return (
                f"Error: failed to start {operation} background job: "
                f"{record['error']}"
            )

        return (
            f"ACK job={job_id} state=QUEUED operation={operation} "
            f"pid={process.pid}. Disparado em background; "
            f"use /job {job_id} ou /jobs."
        )

    def status(self, job_id: str) -> str:
        job_id = job_id.strip()
        if not job_id:
            return "Error: /job requires a job id"
        path = self.root / f"{job_id}.json"
        if not path.is_file():
            return f"Error: job not found: {job_id}"
        try:
            data = _read(path)
        except Exception as exc:
            return f"Error reading job {job_id}: {exc}"

        lines = [
            f"job={data.get('job_id', job_id)}",
            f"state={data.get('state', 'UNKNOWN')}",
            f"operation={data.get('operation', 'UNKNOWN')}",
        ]
        if data.get("pid"):
            lines.append(f"pid={data['pid']}")
        if data.get("error"):
            lines.append(f"error={data['error']}")
        result = str(data.get("result") or "").strip()
        if result:
            lines.append("")
            lines.append(result)
        return "\n".join(lines)

    def list_jobs(self, limit: int = 20) -> str:
        if not self.root.is_dir():
            return "(no background jobs)"
        rows: list[dict[str, Any]] = []
        for path in self.root.glob("job-*.json"):
            try:
                rows.append(_read(path))
            except Exception:
                continue
        rows.sort(
            key=lambda item: float(item.get("created_at") or 0),
            reverse=True,
        )
        if not rows:
            return "(no background jobs)"
        return "\n".join(
            f"{item.get('job_id')}  "
            f"{item.get('state', 'UNKNOWN'):<9}  "
            f"{item.get('operation', 'UNKNOWN')}"
            for item in rows[: max(1, limit)]
        )

    def completed_notifications(self) -> list[str]:
        if not self.root.is_dir():
            return []
        notices: list[str] = []
        for path in sorted(self.root.glob("job-*.json")):
            try:
                data = _read(path)
            except Exception:
                continue
            job_id = str(data.get("job_id") or path.stem)
            state = str(data.get("state") or "")
            if state not in _TERMINAL or job_id in self._notified:
                continue
            self._notified.add(job_id)
            notices.append(
                f"job {job_id} terminou: {state} "
                f"({data.get('operation', 'UNKNOWN')}). "
                f"Use /job {job_id} para ver o resultado."
            )
        return notices


def _run_frozen_pytest(
    workspace: Path,
    target: str,
) -> str:
    """Run pytest in-process when sys.executable is the frozen SENTRA CLI."""
    import pytest

    args = ["-q"]
    if target and target != "all":
        args.append(target)

    stdout = io.StringIO()
    stderr = io.StringIO()
    previous = Path.cwd()
    try:
        os.chdir(workspace)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = int(pytest.main(args))
    finally:
        os.chdir(previous)

    combined = (stdout.getvalue() + "\n" + stderr.getvalue()).strip()
    status = "PASSED" if code == 0 else f"FAILED (exit {code})"
    return f"Test status: {status}\n\n{combined}".rstrip()


def run_job_file(path: Path) -> int:
    """Internal worker entrypoint used by source and frozen CLI builds."""
    path = path.expanduser().resolve()
    try:
        record = _read(path)
    except Exception:
        return 2

    workspace = Path(str(record.get("workspace") or "")).resolve()
    operation = str(record.get("operation") or "").upper()
    raw_args = str(record.get("raw_args") or "")
    try:
        timeout = float(os.environ.get("SENTRA_CLI_JOB_TIMEOUT", "180"))
    except ValueError:
        timeout = 180.0

    record["state"] = "RUNNING"
    record["started_at"] = _now()
    record["pid"] = os.getpid()
    _atomic_write(path, record)

    try:
        if operation == "TEST":
            target = raw_args.strip() or "all"
            if getattr(sys, "frozen", False):
                result = _run_frozen_pytest(workspace, target)
            else:
                result = run_tests(
                    workspace,
                    target,
                    timeout=max(timeout, 60.0),
                )
            passed = result.startswith("Test status: PASSED")
        elif operation in {"LINT", "TYPECHECK", "BUILD", "BENCH"}:
            result = run_registered(
                workspace,
                operation,
                timeout=max(timeout, 180.0),
            )
            passed = result.startswith(f"{operation} status: PASSED")
        else:
            raise ValueError(f"unsupported job operation: {operation}")

        record["result"] = result
        record["state"] = "SUCCEEDED" if passed else "FAILED"
        return_code = 0 if passed else 1
    except Exception as exc:
        record["state"] = "FAILED"
        record["error"] = f"{type(exc).__name__}: {exc}"
        return_code = 1
    finally:
        record["finished_at"] = _now()
        _atomic_write(path, record)

    return return_code
