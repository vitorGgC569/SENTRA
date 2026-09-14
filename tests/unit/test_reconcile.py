"""Reconciliação operacional: listar, investigar, descartar explícito. Sem live."""
import json

import pytest

from orchestrator.reconcile import blocked_seats, drop_seat, relay_jobs_for_task


def _seat_map(run_id="R1"):
    return {"schema_version": 2, "run_id": run_id, "last_dispatch_at": 0.0,
            "seats": {
                f"{run_id}:executor": {"state": "CONFIRMED", "provider": "extension",
                                       "role": "executor", "task_id": "T-1",
                                       "url": "https://chatgpt.com/c/aaaa-1",
                                       "conversation_id": "aaaa-1", "updated": 100.0},
                f"{run_id}:validator.logic": {"state": "IN_FLIGHT", "provider": "extension",
                                              "role": "validator.logic", "task_id": "T-1",
                                              "request_sha256": "deadbeef"*8, "updated": 200.0},
            }}


def _write_run(tmp_path, run_id="R1"):
    rundir = tmp_path / run_id
    rundir.mkdir(parents=True, exist_ok=True)
    (rundir / "conversations.json").write_text(json.dumps(_seat_map(run_id)), encoding="utf-8")
    return rundir


def test_blocked_lists_only_stuck_seats(tmp_path):
    rundir = _write_run(tmp_path)
    stuck = blocked_seats(rundir)
    assert [s["seat"] for s in stuck] == ["R1:validator.logic"]
    assert stuck[0]["task_id"] == "T-1"


def test_drop_seat_removes_intent_and_journals(tmp_path):
    rundir = _write_run(tmp_path)
    record = drop_seat(rundir, "R1:validator.logic", reason="stale question superseded")
    assert record["seat"] == "R1:validator.logic"
    assert record["dropped_state"] == "IN_FLIGHT"
    remaining = json.loads((rundir / "conversations.json").read_text(encoding="utf-8"))
    assert "R1:validator.logic" not in remaining["seats"]
    assert "R1:executor" in remaining["seats"]  # confirmado intocado
    audit = (rundir / "reconciliations.jsonl").read_text(encoding="utf-8")
    assert "drop-stale-intent" in audit and "R1:validator.logic" in audit


def test_drop_refuses_healthy_or_unknown_seats(tmp_path):
    rundir = _write_run(tmp_path)
    with pytest.raises(ValueError, match="CONFIRMED|only stuck"):
        drop_seat(rundir, "R1:executor", reason="x")
    with pytest.raises(ValueError, match="unknown seat"):
        drop_seat(rundir, "R1:nobody", reason="x")


def test_relay_forensics_read_only_and_filtered(tmp_path):
    from native_bridge.job_store import JobStore
    from native_bridge.protocol import ChatJob
    db = tmp_path / "relay.sqlite3"
    store = JobStore(str(db))
    store.submit(ChatJob(task_id="T-1", prompt="hi", timeout_s=60))
    store.submit(ChatJob(task_id="T-2", prompt="hi", timeout_s=60))
    store.close()
    jobs = relay_jobs_for_task(db, "T-1")
    assert len(jobs) == 1 and jobs[0]["state"] == "QUEUED"
    assert relay_jobs_for_task(db, "T-zzz") == []
    assert relay_jobs_for_task(tmp_path / "missing.sqlite3", "T-1") == []
