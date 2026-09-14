"""WS2 supervisor: laco, backoff, sentinelas, watchdog e snapshot.

Testes reais com tmp_path + runners canned (dicts, sem LLM, sem rede,
sem Edge). Timeouts pequenos; nenhum sleep longo.
"""
import asyncio
import json

from orchestrator.supervisor import Supervisor


def _sup(workspace, **kwargs):
    kwargs.setdefault("poll_interval_secs", 0.01)
    kwargs.setdefault("backoff_base_secs", 0.01)
    kwargs.setdefault("backoff_max_secs", 0.05)
    return Supervisor(workspace, **kwargs)


async def test_processes_until_empty_and_writes_status(tmp_path):
    items = [{"id": "a", "run_id": "a"}, {"id": "b", "run_id": "b"}]

    async def next_item():
        return items.pop(0) if items else None

    async def run_item(item):
        return {"status": "CANDIDATE_READY", "run_id": item["id"]}

    sup = _sup(tmp_path, next_item=next_item, run_item=run_item, idle_exit_secs=0.05)
    result = await sup.serve()
    assert result["exit_reason"] == "idle-timeout"
    assert result["iterations"] == 2
    assert result["completed"] == 2
    assert result["failed"] == 0 and result["stalled"] == 0
    status = json.loads((tmp_path / "runs" / "supervisor-status.json").read_text(encoding="utf-8"))
    for key in ("state", "active_run", "iterations", "completed", "failed",
                "stalled", "consecutive_failures", "last_error", "exit_reason"):
        assert key in status
    assert status["state"] == "done" and status["iterations"] == 2
    raw = (tmp_path / "runs" / "supervisor-status.json").read_bytes()
    assert b"\r" not in raw


async def test_max_iterations_caps_loop(tmp_path):
    async def next_item():
        return {"id": "x", "run_id": "x"}

    async def run_item(item):
        return {"status": "OK"}

    sup = _sup(tmp_path, next_item=next_item, run_item=run_item,
               max_iterations=3, idle_exit_secs=5)
    result = await sup.serve()
    assert result["exit_reason"] == "max-iterations"
    assert result["iterations"] == 3 and result["completed"] == 3


async def test_backoff_progressive_and_resets_on_success(tmp_path):
    delays = []

    async def fake_sleep(secs):
        delays.append(secs)

    items = [{"id": "f1"}, {"id": "ok"}, {"id": "f2"}]

    async def next_item():
        return items.pop(0) if items else None

    async def run_item(item):
        if item["id"] == "ok":
            return {"status": "CANDIDATE_READY"}
        return {"status": "FAILED", "error": "boom-" + item["id"]}

    sup = Supervisor(tmp_path, next_item=next_item, run_item=run_item,
                     sleep=fake_sleep, poll_interval_secs=0.001,
                     backoff_base_secs=0.5, backoff_max_secs=10.0,
                     idle_exit_secs=0.02)
    result = await sup.serve()
    assert result["failed"] == 2 and result["completed"] == 1
    backoffs = [d for d in delays if d >= 0.5]
    assert backoffs == [0.5, 0.5]
    assert result["consecutive_failures"] == 1
    assert "boom-f2" in (result["last_error"] or "")


async def test_backoff_doubles_while_failing(tmp_path):
    delays = []

    async def fake_sleep(secs):
        delays.append(secs)

    async def next_item():
        return {"id": "w"}

    async def run_item(item):
        return {"status": "FAILED", "error": "nope"}

    sup = Supervisor(tmp_path, next_item=next_item, run_item=run_item,
                     sleep=fake_sleep, poll_interval_secs=0.001,
                     backoff_base_secs=0.5, backoff_max_secs=10.0,
                     max_iterations=3, idle_exit_secs=5)
    result = await sup.serve()
    assert result["failed"] == 3
    assert delays == [0.5, 1.0]


async def test_stop_sentinel_exits_gracefully(tmp_path):
    seen = []

    async def next_item():
        return {"id": "job-1", "run_id": "job-1"}

    async def run_item(item):
        seen.append(item["id"])
        (tmp_path / "runs" / "SUPERVISOR.stop").write_text("stop", encoding="utf-8")
        return {"status": "CANDIDATE_READY"}

    sup = _sup(tmp_path, next_item=next_item, run_item=run_item,
               idle_exit_secs=5, max_iterations=10)
    result = await sup.serve()
    assert result["exit_reason"] == "stop-requested"
    assert seen == ["job-1"]
    status = json.loads((tmp_path / "runs" / "supervisor-status.json").read_text(encoding="utf-8"))
    assert status["exit_reason"] == "stop-requested"


async def test_pause_holds_queue_until_removed(tmp_path):
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs" / "SUPERVISOR.pause").write_text("pause", encoding="utf-8")
    calls = []

    async def next_item():
        calls.append(1)
        return {"id": "p1", "run_id": "p1"}

    async def run_item(item):
        return {"status": "OK"}

    sup = _sup(tmp_path, next_item=next_item, run_item=run_item,
               max_iterations=1, idle_exit_secs=5)

    async def unpause():
        await asyncio.sleep(0.05)
        (tmp_path / "runs" / "SUPERVISOR.pause").unlink(missing_ok=True)

    result = await asyncio.wait_for(_serve_and_unpause(sup, unpause), timeout=5)
    assert result["exit_reason"] == "max-iterations"
    assert result["iterations"] == 1
    assert calls, "fila nao deve ser consumida enquanto pausado, mas deve avancar depois"


async def _serve_and_unpause(sup, unpause):
    task = asyncio.create_task(sup.serve())
    await unpause()
    return await task


async def test_watchdog_cancels_stalled_runner_and_marks_no_replay(tmp_path):
    stalled_marks = []
    cancelled = {}

    async def next_item():
        if stalled_marks or cancelled.get("ran"):
            return None
        if not hasattr(next_item, "asked"):
            next_item.asked = True
            return {"id": "stuck-1", "run_id": "stuck-1"}
        return None

    async def run_item(item):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled["ran"] = True
            raise
        return {"status": "OK"}

    async def mark_stalled(item, reason):
        stalled_marks.append({"id": item["id"], "reason": reason, "replay_allowed": False})

    sup = _sup(tmp_path, next_item=next_item, run_item=run_item,
               mark_stalled=mark_stalled, watchdog_secs=0.05, idle_exit_secs=0.05)
    result = await asyncio.wait_for(sup.serve(), timeout=5)
    assert cancelled.get("ran") is True
    assert result["stalled"] == 1
    assert len(stalled_marks) == 1 and stalled_marks[0]["id"] == "stuck-1"
    assert stalled_marks[0]["replay_allowed"] is False
    assert "watchdog" in (stalled_marks[0]["reason"] or "").lower()


async def test_watchdog_sees_progress_and_does_not_fire(tmp_path):
    async def next_item():
        if getattr(next_item, "done", False):
            return None
        next_item.done = True
        return {"id": "live-1", "run_id": "live-1"}

    async def run_item(item):
        run_dir = tmp_path / "runs" / "live-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        events = run_dir / "events.jsonl"
        for i in range(5):
            await asyncio.sleep(0.02)
            with open(events, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event_id": str(i)}) + "\n")
        return {"status": "CANDIDATE_READY"}

    sup = _sup(tmp_path, next_item=next_item, run_item=run_item,
               watchdog_secs=0.3, idle_exit_secs=0.05)
    result = await asyncio.wait_for(sup.serve(), timeout=5)
    assert result["completed"] == 1 and result["stalled"] == 0


async def test_blocked_result_counts_as_stalled_without_replay(tmp_path):
    marks = []

    async def next_item():
        if getattr(next_item, "done", False):
            return None
        next_item.done = True
        return {"id": "b1", "run_id": "b1"}

    async def run_item(item):
        return {"status": "BLOCKED", "error": "incerto; sem replay"}

    async def mark_stalled(item, reason):
        marks.append((item["id"], reason))

    sup = _sup(tmp_path, next_item=next_item, run_item=run_item,
               mark_stalled=mark_stalled, idle_exit_secs=0.05)
    result = await sup.serve()
    assert result["stalled"] == 1 and result["failed"] == 0
    assert marks and marks[0][0] == "b1"


def test_cli_flags_exist():
    from main import parser
    cli = parser()
    args = cli.parse_args(["--supervise"])
    assert args.supervise is True
    args = cli.parse_args(["--supervise", "--max-iterations", "3", "--idle-exit-secs", "10"])
    assert args.max_iterations == 3 and args.idle_exit_secs == 10
