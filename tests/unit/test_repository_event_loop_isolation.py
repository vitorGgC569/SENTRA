from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.services.jobs import JobService
from sentra_mcp.services.repository import RepositoryService, _registered_operation_passed


def _config(root: Path) -> MCPConfig:
    return MCPConfig(
        allowed_roots=(root,),
        audit_log=root / ".sentra" / "audit.jsonl",
        remote_store_path=root / ".sentra" / "remote.sqlite3",
    )


def test_repository_gateway_cache_is_event_loop_local(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repository = RepositoryService(config, AuditLogger(config.audit_log))

    async def acquire_pair():
        first = repository._gateway(None, None, "read")[2]
        second = repository._gateway(None, None, "read")[2]
        return first, second

    first_a, first_b = asyncio.run(acquire_pair())
    second_a, second_b = asyncio.run(acquire_pair())

    assert first_a is first_b
    assert second_a is second_b
    assert first_a is not second_a


class _LoopSensitiveRepository:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.entered = threading.Event()
        self.loop_ids: list[int] = []

    async def run_registered(self, operation, target, workspace, owner):
        async with self.lock:
            self.loop_ids.append(id(asyncio.get_running_loop()))
            self.entered.set()
            await asyncio.sleep(0.05)
            return {
                "operation": operation.lower(),
                "target": target or None,
                "passed": True,
                "result": "PASS exit=0",
                "workspace": workspace or "root:0",
                "workspace_alias": "sentra",
            }


def test_job_service_uses_one_durable_event_loop_for_parallel_jobs(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repository = _LoopSensitiveRepository()
    jobs = JobService(
        config,
        AuditLogger(config.audit_log),
        repository,
        db_path=tmp_path / ".sentra" / "jobs.sqlite3",
    )
    try:
        first = jobs.start("TEST", "mcp:test", target="unit")
        assert repository.entered.wait(1)
        second = jobs.start("TEST", "mcp:test", target="integration")

        one = jobs.wait(first["job_id"], "mcp:test", 5)
        two = jobs.wait(second["job_id"], "mcp:test", 5)

        assert one["state"] == "COMPLETED"
        assert two["state"] == "COMPLETED"
        assert len(repository.loop_ids) == 2
        assert len(set(repository.loop_ids)) == 1
    finally:
        jobs.close()


class _BlockingRepository:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    async def run_registered(self, operation, target, workspace, owner):
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        return {
            "operation": operation.lower(),
            "target": target or None,
            "passed": True,
            "result": "PASS exit=0",
            "workspace": workspace or "root:0",
            "workspace_alias": "sentra",
        }


def test_second_job_service_does_not_interrupt_live_producer(tmp_path: Path) -> None:
    config = _config(tmp_path)
    db_path = tmp_path / ".sentra" / "jobs.sqlite3"
    repository = _BlockingRepository()
    primary = JobService(
        config,
        AuditLogger(config.audit_log),
        repository,
        db_path=db_path,
    )
    secondary = None
    try:
        job = primary.start("TEST", "mcp:test", target="unit")
        assert repository.started.wait(1)
        deadline = time.monotonic() + 1
        while primary.status(job["job_id"], "mcp:test")["state"] != "RUNNING":
            assert time.monotonic() < deadline
            time.sleep(0.01)

        secondary = JobService(
            config,
            AuditLogger(config.audit_log),
            _LoopSensitiveRepository(),
            db_path=db_path,
        )
        assert secondary.status(job["job_id"], "mcp:test")["state"] == "RUNNING"
        assert primary.status(job["job_id"], "mcp:test")["state"] == "RUNNING"

        repository.release.set()
        assert primary.wait(job["job_id"], "mcp:test", 2)["state"] == "COMPLETED"
    finally:
        repository.release.set()
        if secondary is not None:
            secondary.close()
        primary.close()


def test_job_service_recovers_job_from_dead_producer(tmp_path: Path) -> None:
    config = _config(tmp_path)
    db_path = tmp_path / ".sentra" / "jobs.sqlite3"
    first = JobService(
        config,
        AuditLogger(config.audit_log),
        _LoopSensitiveRepository(),
        db_path=db_path,
    )
    first.close()

    with sqlite3.connect(db_path) as db:
        now = time.time()
        db.execute(
            "INSERT INTO jobs("
            "id,owner,operation,target,workspace,producer_pid,state,created,updated"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "orphan-job",
                "mcp:test",
                "TEST",
                "unit",
                "sentra",
                2147483647,
                "RUNNING",
                now,
                now,
            ),
        )
        db.commit()

    recovered = JobService(
        config,
        AuditLogger(config.audit_log),
        _LoopSensitiveRepository(),
        db_path=db_path,
    )
    try:
        status = recovered.status("orphan-job", "mcp:test")
        assert status["state"] == "INTERRUPTED"
        assert status["error"] == "producer process is no longer alive"
    finally:
        recovered.close()


def test_registered_operation_outcome_survives_result_paging() -> None:
    direct = "BUILD PASS exit=0\ncollected 590 items"
    paged = (
        "ALIAS=R01\n"
        "RESULT_ID=RES-123 LINES=590 OFFSET=0 MORE=true\n"
        "SUMMARY: BUILD paged\n"
        "BUILD PASS exit=0\n"
        "tests/unit/test_example.py::test_one"
    )
    assert _registered_operation_passed("BUILD", direct) is True
    assert _registered_operation_passed("BUILD", paged) is True

    assert _registered_operation_passed(
        "BUILD",
        paged.replace("BUILD PASS exit=0", "BUILD FAIL exit=1"),
    ) is False
    assert _registered_operation_passed(
        "BUILD",
        paged.replace("SUMMARY: BUILD paged", "SUMMARY: TEST paged"),
    ) is False
