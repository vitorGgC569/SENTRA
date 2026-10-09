"""Acceptance coverage for central physical I/O and recoverable evidence.

These tests exercise actual files, SQLite and OS exclusion. They prove the
central boundary, not a deployed remote service or all37 incorporations.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

def test_owned_async_scope_survives_cancel_and_preserves_actual_return(live_center):
    cp,center,request,grant,root=live_center
    async def scenario():
        started=asyncio.Event();release=threading.Event()
        loop=asyncio.get_running_loop();destination=root/"late-async.txt"
        def already_admitted_io():
            loop.call_soon_threadsafe(started.set)
            release.wait(5)
            destination.write_text("actual completed I/O",encoding="utf-8")
            return {"sha256":hashlib.sha256(destination.read_bytes()).hexdigest()}
        async def effect(req):return await asyncio.to_thread(already_admitted_io)
        center.bind_provider("file:write",effect)
        task=asyncio.create_task(center.start(request("late-async")))
        await asyncio.wait_for(started.wait(),3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        row=cp.durable.operation_status("op-late-async",center.owner)
        assert row["state"]=="UNCERTAIN"
        probe=_ResourceLock(cp.durable.root/"effect-locks",center.machine.machine_id)
        with pytest.raises(ResourceEffectBusy):probe.acquire(0)
        release.set()
        authority=CentralDurableIntentAuthority(cp.durable)
        receipt=authority.receipt_for_operation("op-late-async",center.owner)
        for _ in range(200):
            late=authority.late_return_for_receipt(receipt)
            if late:break
            await asyncio.sleep(.01)
        assert late["worker_returned"] is True and late["operation_reconciled"] is False
        assert late["reported_return"]["sha256"]==hashlib.sha256(destination.read_bytes()).hexdigest()
        assert cp.durable.operation_status("op-late-async",center.owner)["state"]=="UNCERTAIN"
        probe.acquire(1);probe.release()
    asyncio.run(scenario())

from sentra_interop.central import CentralInteropAdapter
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService, DurableStateConflict
from sentra_runtime.central_authority import CentralDurableIntentAuthority
from sentra_runtime.contracts import Capability, Machine, OperationRequest
from sentra_runtime.effect_boundary import CentralEffectContext, _ResourceLock, ResourceEffectBusy
from sentra_runtime.executor import DuplicateOperation


@pytest.fixture
def live_center(tmp_path):
    durable = DurableRunService(tmp_path / "state")
    cp = ControlPlaneService(durable, ContextBusService(tmp_path / "state"))
    owner, run = "owner-real-effect", "run-real-effect"
    durable.create_run(owner, run_id=run)
    if durable.run_status(run, owner)["state"] != "RUNNING":
        durable.transition_run(run, owner, "RUNNING")
    cp.governance.create_work_item(run, owner, objective="Create a verifiable local artifact",
        work_item_id="WI-effect", assignee_agent_id="agent-effect",
        required_capabilities=["file:write"])
    cp.governance.transition_work_item("WI-effect", owner, "RUNNING")
    grant = cp.authorization.grant(owner, principal_type="agent", principal_id="agent-effect",
        capability="file:write", scope_type="work_item", scope_id="WI-effect")
    machine = Machine("file-machine", "local-file", owner, (Capability("file:write", "Write artifact"),))
    adapter = CentralInteropAdapter(control=cp, run_id=run, owner=owner, machine=machine)
    def request(tag="one", arguments=None):
        return OperationRequest("op-" + tag, "agent-effect", machine.machine_id, "file:write",
                                "WI-effect", "key-" + tag, arguments or {"value": "actual bytes"})
    yield cp, adapter, request, grant, tmp_path
    durable.close()


def test_real_effect_is_reserved_and_evidence_recovers_after_new_adapter(live_center):
    cp, center, request, grant, root = live_center
    destination = root / "result.txt"
    writes = []
    def write(req):
        row = cp.durable.operation_status(req.operation_id, center.owner)
        assert row["state"] == "RUNNING" and row["progress"]["effect_started"] is True
        destination.write_text(req.arguments["value"], encoding="utf-8")
        writes.append(req.operation_id)
        return {"path": str(destination), "bytes": destination.stat().st_size}
    center.bind_provider("file:write", write)
    first = asyncio.run(center.start(request()))
    assert first.state == "SUCCEEDED" and destination.read_text() == "actual bytes"
    stored = cp.durable.operation_status(first.operation_id, center.owner)
    artifact = cp.durable.artifact_info(stored["result"]["evidence_artifact_id"], center.owner)
    assert artifact["operation_id"] == first.operation_id
    assert json.loads(cp.durable.read_artifact(artifact["artifact_id"], max_bytes=70000))["evidence"] == first.evidence
    restarted = CentralInteropAdapter(control=cp, run_id=center.run_id,
                                       owner=center.owner, machine=center.machine)
    restarted.bind_provider("file:write", write)
    again = asyncio.run(restarted.start(request()))
    assert again == first and writes == [first.operation_id]
    assert asyncio.run(restarted.reconcile(first.operation_id)) == first
    # A different operation on this machine can proceed after terminal release.
    assert asyncio.run(restarted.start(request("two"))).state == "SUCCEEDED"
    assert len(writes) == 2


def test_changed_intent_revoked_grant_and_tampered_evidence_never_replay(live_center):
    cp, center, request, grant, root = live_center
    hits = []
    center.bind_provider("file:write", lambda req: hits.append(req.operation_id) or {"written": True})
    first = asyncio.run(center.start(request()))
    assert first.state == "SUCCEEDED"
    mismatch = asyncio.run(center.start(request(arguments={"value": "different"})))
    assert mismatch.state != "SUCCEEDED" and hits == [first.operation_id]
    stored = cp.durable.operation_status(first.operation_id, center.owner)
    artifact = cp.durable.artifact_info(stored["result"]["evidence_artifact_id"], center.owner)
    Path(artifact["path"]).write_text("{}", encoding="utf-8")
    assert asyncio.run(center.start(request())).state != "SUCCEEDED"
    assert hits == [first.operation_id]
    cp.authorization.revoke(grant["grant_id"], center.owner)
    assert asyncio.run(center.start(request("after-revoke"))).state == "FAILED"
    assert hits == [first.operation_id]


def test_blocking_worker_keeps_os_lock_when_its_waiter_is_cancelled(live_center):
    cp, center, request, grant, root = live_center
    authority = CentralDurableIntentAuthority(cp.durable, ttl_s=1)
    from sentra_runtime.executor import _request_snapshot
    req = request()
    receipt = authority.reserve_intent(run_id=center.run_id, owner=center.owner,
                                      request=req, intent_sha256=_request_snapshot(req)[1])
    assert authority.fence_active(receipt)
    context = CentralEffectContext(authority, receipt, req, center.policy)
    started, release = threading.Event(), threading.Event()
    def physical():
        started.set()
        assert release.wait(3)
        (root / "worker-finished.txt").write_text("completed physical I/O")
    async def exercise():
        task = asyncio.create_task(asyncio.to_thread(context.run_sync, physical))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            other = _ResourceLock(cp.durable.root / "effect-locks", req.machine_id)
            with pytest.raises(ResourceEffectBusy):
                other.acquire(0)
            await asyncio.sleep(1.1)
            with cp.durable.lock:
                cp.durable._verify_fence_locked("machine:" + req.machine_id, receipt.fencing_token)
            with pytest.raises(DuplicateOperation):
                # Cancellation never creates permission for a fresh physical effect.
                authority.reserve_intent(run_id=center.run_id, owner=center.owner,
                    request=request("other"), intent_sha256=_request_snapshot(request("other"))[1])
        finally:
            release.set()
    asyncio.run(exercise())
    assert (root / "worker-finished.txt").exists()


def test_machine_lock_excludes_another_actual_python_process(tmp_path):
    lock = _ResourceLock(tmp_path / "locks", "shared-machine")
    lock.acquire(0)
    script = (
        "from pathlib import Path\n"
        "from sentra_runtime.effect_boundary import _ResourceLock, ResourceEffectBusy\n"
        "import sys\n"
        "try:\n"
        "    _ResourceLock(Path(sys.argv[1]), 'shared-machine').acquire(0)\n"
        "except ResourceEffectBusy:\n"
        "    sys.exit(23)\n"
        "sys.exit(0)\n"
    )
    try:
        child = subprocess.run([sys.executable, "-c", script, str(tmp_path / "locks")],
                               capture_output=True, text=True, timeout=10)
        assert child.returncode == 23, child.stderr
    finally:
        lock.release()


def test_async_waiter_cancel_keeps_lock_until_blocking_io_returns(live_center):
    """Cancellation of an async wrapper cannot abandon a running thread effect."""
    cp, center, request, grant, root = live_center
    from sentra_runtime.executor import _request_snapshot
    authority = CentralDurableIntentAuthority(cp.durable, ttl_s=2)
    req = request("async-cancel")
    receipt = authority.reserve_intent(
        run_id=center.run_id, owner=center.owner, request=req,
        intent_sha256=_request_snapshot(req)[1],
    )
    context = CentralEffectContext(authority, receipt, req, center.policy)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocking_io():
        started.set()
        try:
            assert release.wait(4), "bounded fixture never released"
        finally:
            finished.set()

    async def provider():
        return await asyncio.to_thread(blocking_io)

    async def exercise():
        task = asyncio.create_task(context.run_async(provider))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            contender = _ResourceLock(cp.durable.root / "effect-locks", req.machine_id)
            with pytest.raises(ResourceEffectBusy):
                contender.acquire(0)
        finally:
            release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        await asyncio.sleep(0)

    asyncio.run(exercise())
