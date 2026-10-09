"""EXE central integration gates: REAL ControlPlaneService, SQLite grants,
Run, WorkItem, ExecutorRegistry, durable_admission; test-only SQLite intent
provider because production ControlStore lacks full fingerprint fencing.

Loopback child subprocess is ours, ephemeral, no personal apps/credentials.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

import pytest

from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.contracts import OperationRequest
from sentra_runtime.durable_admission import (
    DurableAdmissionUnavailable, IntentReceipt,
)
from sentra_runtime.executor import (
    AuthorizationRequired, DuplicateOperation,
)
from sentra_executors import (
    BrowserReadBinding, CentralExecutorFactory,
)


def go(coro):
    return asyncio.run(coro)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PermissionError("external_redirect_denied")


class OnlyHTTPFixtureBackend:
    """Isolated stdlib HTTP GET, no proxy or cookies or redirect."""
    def __init__(self):
        self.calls = []
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.before_request = None

    def run(self, binding, args):
        if args["url"] not in binding.allowed_urls:
            raise PermissionError("url_not_allowlisted")
        if self.before_request:
            self.before_request()
        self.calls.append(args["url"])
        with self.opener.open(Request(args["url"], method="GET"),
                              timeout=binding.timeout_seconds) as stream:
            body = stream.read(4097)
            if stream.status != 200 or len(body) > 4096:
                raise ValueError("fixture_http_response_denied")
        return {"text_sha256": hashlib.sha256(body).hexdigest(),
                "length": len(body)}


@contextmanager
def owned_loopback_child(tmp_path):
    """Starts only an explicit Python -I -B child serving a fixed lab page."""
    journal = tmp_path / "child_http_hits.txt"
    code = (
        "import http.server,sys\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  with open(sys.argv[1],'a') as f:f.write(self.path+'\\n')\n"
        "  if self.path!='/read':\n"
        "   self.send_response(404);self.end_headers();return\n"
        "  body=b'SENTRA-CENTRAL-LAB-ONLY'\n"
        "  self.send_response(200)\n"
        "  self.send_header('Content-Length',str(len(body)))\n"
        "  self.end_headers();self.wfile.write(body)\n"
        " def log_message(self,*a):pass\n"
        "s=http.server.ThreadingHTTPServer(('127.0.0.1',0),H)\n"
        "print(s.server_port,flush=True)\n"
        "s.serve_forever()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", code, str(journal)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, text=True)
    try:
        # Child stdout prints its own ephemeral listening port exactly once.
        # Hard limit on process startup to avoid waiting on another app.
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(process.stdout.readline)
        try:
            port_text = future.result(timeout=5).strip()
        except Exception:
            process.terminate()
            future.result(timeout=5)
            raise
        finally:
            pool.shutdown(wait=False)
        port = int(port_text)
        assert 1 <= port <= 65535
        yield f"http://127.0.0.1:{port}/read", journal, process
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()


@pytest.fixture
def central(tmp_path):
    root = tmp_path / "central_state"
    durable = DurableRunService(root)
    context = ContextBusService(root)
    control = ControlPlaneService(durable, context)
    owner, agent, run_id, work_id = "owner-exec-test", "agent-exec-test", "run-central-1", "work-central-1"
    control.durable.create_run(owner, run_id=run_id,
                               workspace=str(tmp_path / "isolated-lab"))
    control.ensure_agent(run_id, owner, agent_id=agent, role="worker")
    work = control.create_work_item(
        run_id, owner, work_item_id=work_id,
        objective="Read exact self-owned loopback fixture",
        assignee_agent_id=agent,
        required_capabilities=["browser.central.read"])
    assert work["state"] == "PENDING"
    control.transition_work_item(work_id, owner, "QUEUED")
    control.start_work_item_execution(work_id, owner, run_id=run_id, agent_id=agent)
    assert control.work_item_info(work_id, owner)["state"] == "RUNNING"
    try:
        yield root, control, owner, agent, run_id, work_id
    finally:
        durable.close()


class SQLiteAdmissionTestOnly:
    """DurableIntentAuthority test fixture, NEVER exported as a SENTRA provider.

    Transactionally reserves full fingerprints in its OWN disposable SQLite
    store; mirrors a legacy durable operation for test observability.
    Cross-database updates are NOT atomic; production MUST use coordinator's
    real ControlStore authority and fencing at physical effect boundary.
    """

    def __init__(self, tmp_path, control):
        self.path = tmp_path / "TEST_ONLY_intents.sqlite3"
        self.control = control
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reservations("
                "operation_id TEXT PRIMARY KEY, intent_sha256 TEXT NOT NULL,"
                "run_id TEXT NOT NULL, owner TEXT NOT NULL,"
                "work_item_id TEXT NOT NULL, capability_id TEXT NOT NULL,"
                "fence INTEGER NOT NULL, state TEXT NOT NULL)"
            )
        self.reserve_calls = self.fence_calls = self.record_calls = 0
        self.before_record = None

    def _db(self):
        db = sqlite3.connect(str(self.path), timeout=2)
        db.row_factory = sqlite3.Row
        return db

    def reserve_intent(self, *, run_id, owner, request, intent_sha256):
        self.reserve_calls += 1
        item = self.control.work_item_info(request.work_item_id, owner)
        run = self.control.durable.run_status(run_id, owner, include_details=False)
        if item["run_id"] != run_id or run["state"] != "RUNNING":
            raise PermissionError("run_work_item_mismatch")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM reservations WHERE operation_id=?",
                (request.operation_id,)).fetchone()
            if old:
                if (old["intent_sha256"] != intent_sha256
                        or old["run_id"] != run_id or old["owner"] != owner):
                    raise ValueError("test_sqlite_intent_fingerprint_conflict")
                return IntentReceipt(request.operation_id, intent_sha256,
                                     run_id, owner, old["fence"], "EXISTING")
            db.execute(
                "INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?)",
                (request.operation_id, intent_sha256, run_id, owner,
                 request.work_item_id, request.capability_id, 1, "RESERVED"))
        # Legacy projection is separate/NOT atomic with test reservation.
        self.control.durable.create_operation(
            run_id, owner, kind="sentra.executor.fixture_read",
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            cleanup_policy="manual")
        self.control.durable.update_operation(
            request.operation_id, owner, state="RUNNING",
            progress={"work_item_id": request.work_item_id,
                      "capability_id": request.capability_id,
                      "intent_sha256": intent_sha256, "fencing_token_test_only": 1})
        return IntentReceipt(request.operation_id, intent_sha256,
                             run_id, owner, 1, "RESERVED")

    def fence_active(self, receipt):
        self.fence_calls += 1
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM reservations WHERE operation_id=?",
                (receipt.operation_id,)).fetchone()
        if not row or row["fence"] != receipt.fencing_token or row["state"] != "RESERVED":
            return False
        op = self.control.durable.operation_status(receipt.operation_id, receipt.owner)
        work = self.control.work_item_info(row["work_item_id"], receipt.owner)
        return (op["state"] == "RUNNING" and work["state"] == "RUNNING"
                and op["progress"]["intent_sha256"] == receipt.intent_sha256)

    def record_result(self, receipt, result):
        self.record_calls += 1
        if self.before_record:
            self.before_record()
        if not self.fence_active(receipt):
            return False
        op = self.control.durable.operation_status(receipt.operation_id, receipt.owner)
        self.control.durable.update_operation(
            receipt.operation_id, receipt.owner, state=result.state,
            result={"work_item_id": op["progress"]["work_item_id"],
                    "evidence": dict(result.evidence or {})}
            if result.state == "SUCCEEDED" else None,
            error={"reason": result.error or "not_succeeded"}
            if result.state != "SUCCEEDED" else None)
        with self._db() as db:
            db.execute("UPDATE reservations SET state='RECORDED' WHERE operation_id=?",
                       (receipt.operation_id,))
        return True

    def force_fence_loss(self, op_id):
        with self._db() as db:
            db.execute("UPDATE reservations SET fence=fence+1 WHERE operation_id=?",
                       (op_id,))


def factory(central, url, *, authority=None, backend=None):
    _, control, owner, agent, _, _ = central
    hub = CentralExecutorFactory(
        control=control, owner=owner, agent_id=agent,
        durable_intent_authority=authority)
    backend = backend or OnlyHTTPFixtureBackend()
    registered = hub.register_lab_browser(
        machine_id="central-browser",
        binding=BrowserReadBinding("browser.central.read", (url,)),
        backend=backend)
    return hub, backend, registered


def request(hub, central, url, *, op="op-central-1"):
    _, _, _, _, run_id, work_id = central
    return hub.request(
        run_id=run_id, work_item_id=work_id,
        machine_id="central-browser", operation_id=op, url=url)


def grant(central):
    _, control, owner, agent, _, work_id = central
    # ADMIN/ControlPlane only: the factory and agent never create grants.
    return control.authorization.grant(
        owner, principal_type="agent", principal_id=agent,
        capability="browser.central.read",
        scope_type="work_item", scope_id=work_id)["grant_id"]


def test_1_factory_central_real_sqlite_registry_discover_deny_without_grant(central):
    root, control, owner, agent, run_id, work_id = central
    url = "http://127.0.0.1:43210/read"
    hub, backend, registered = factory(central, url)
    assert registered.machine.machine_id == "central-browser"
    assert [cap.capability_id for cap in go(hub.discover("central-browser"))] == [
        "browser.central.read"]
    assert [m.machine_id for m in hub.registry.machines()] == ["central-browser"]
    req = request(hub, central, url)
    # Real SQLite WorkItem and durable run exist. No agent-created grant.
    assert control.durable.run_status(run_id, owner, include_details=False)["state"] == "RUNNING"
    assert control.work_item_info(work_id, owner)["assignee_agent_id"] == agent
    assert hub.policy(req).allowed is False
    with pytest.raises(AuthorizationRequired):
        go(hub.registry.submit(req))
    with pytest.raises(AuthorizationRequired, match="SENTRA live grant denied"):
        go(hub.submit(run_id=run_id, request=req))
    assert backend.calls == []
    assert list(root.rglob("*.db")) or list(root.rglob("*.sqlite*"))
    with pytest.raises(ValueError, match="machine_already_registered"):
        hub.register_lab_browser(
            machine_id="central-browser",
            binding=BrowserReadBinding("browser.central.read", (url,)),
            backend=backend)


def test_1_direct_dispatch_still_blocked_when_granted_without_durable_authority(central):
    url = "http://127.0.0.1:32129/read"
    hub, backend, _ = factory(central, url)
    grant_id = grant(central)
    req = request(hub, central, url)
    assert hub.policy(req).allowed is True
    with pytest.raises(DurableAdmissionUnavailable):
        go(hub.submit(run_id=central[4], request=req))
    assert backend.calls == []
    central[1].authorization.revoke(grant_id, central[2])
    assert hub.policy(req).allowed is False


def test_2_authorized_real_run_workitem_operation_subprocess_loopback(central, tmp_path):
    with owned_loopback_child(tmp_path) as (url, hits, process):
        admission = SQLiteAdmissionTestOnly(tmp_path, central[1])
        hub, backend, registered = factory(central, url, authority=admission)
        req = request(hub, central, url)
        with pytest.raises(AuthorizationRequired):
            go(hub.submit(run_id=central[4], request=req))
        assert not hits.exists()
        grant_id = grant(central)
        outcome = go(hub.submit(run_id=central[4], request=req))
        assert outcome.state == "SUCCEEDED"
        assert outcome.evidence["text_sha256"] == hashlib.sha256(
            b"SENTRA-CENTRAL-LAB-ONLY").hexdigest()
        assert hits.read_text().splitlines() == ["/read"]
        op = central[1].durable.operation_status(req.operation_id, central[2])
        assert op["state"] == "SUCCEEDED"
        assert op["run_id"] == central[4]
        assert op["progress"]["work_item_id"] == central[5]
        assert op["progress"]["capability_id"] == req.capability_id
        assert op["result"]["work_item_id"] == central[5]
        assert admission.reserve_calls == 1
        # Same intent is an EXISTING durable receipt: do not repeat a GET.
        replay = go(hub.reconcile(run_id=central[4], request=req))
        assert replay.state == "UNCERTAIN"
        assert hits.read_text().splitlines() == ["/read"]
        central[1].authorization.revoke(grant_id, central[2])
        with pytest.raises(AuthorizationRequired):
            go(hub.submit(run_id=central[4], request=req))
        assert hits.read_text().splitlines() == ["/read"]
        assert process.poll() is None


def test_2_reject_cross_workitem_run_capability_and_client_grant_bypass(central, tmp_path):
    with owned_loopback_child(tmp_path) as (url, hits, _):
        hub, _, _ = factory(
            central, url, authority=SQLiteAdmissionTestOnly(tmp_path, central[1]))
        grant(central)
        req = request(hub, central, url)
        bad_run = "run-unrelated"
        with pytest.raises((FileNotFoundError, AuthorizationRequired)):
            go(hub.submit(run_id=bad_run, request=req))
        bad = OperationRequest(
            req.operation_id, "other-agent", req.machine_id, req.capability_id,
            req.work_item_id, req.idempotency_key, dict(req.arguments))
        with pytest.raises(AuthorizationRequired):
            go(hub.submit(run_id=central[4], request=bad))
        forged = OperationRequest(
            req.operation_id, req.principal_id, req.machine_id, req.capability_id,
            "work-forged", req.idempotency_key,
            {**dict(req.arguments), "grant": True, "allowed": True})
        with pytest.raises((FileNotFoundError, AuthorizationRequired)):
            go(hub.submit(run_id=central[4], request=forged))
        # Agent cannot create grants via hub; no grant() API.
        assert not hasattr(hub, "grant")
        assert not hits.exists()


def test_3_reconnect_existing_sqlite_intent_never_redispatches_child(central, tmp_path):
    with owned_loopback_child(tmp_path) as (url, hits, child):
        admission = SQLiteAdmissionTestOnly(tmp_path, central[1])
        hub, backend, _ = factory(central, url, authority=admission)
        grant(central)
        req = request(hub, central, url)
        first = go(hub.submit(run_id=central[4], request=req))
        assert first.state == "SUCCEEDED"
        assert hits.read_text().splitlines() == ["/read"]
        # New ExecutorRegistry with same real central durable SQLite root.
        new_durable = DurableRunService(central[0])
        new_control = ControlPlaneService(new_durable, ContextBusService(central[0]))
        try:
            new_admission = SQLiteAdmissionTestOnly(tmp_path, new_control)
            other, other_backend, _ = factory(
                (central[0], new_control, *central[2:]), url,
                authority=new_admission)
            restarted_req = request(other, central, url)
            result = go(other.reconcile(run_id=central[4], request=restarted_req))
            assert result.state == "UNCERTAIN"
            assert result.error == "existing reservation needs reconciliation"
            assert other_backend.calls == []
            assert hits.read_text().splitlines() == ["/read"]
        finally:
            new_durable.close()


def test_3_cancel_before_effect_is_fenced_and_cleanup_is_authorized(central, tmp_path):
    with owned_loopback_child(tmp_path) as (url, hits, _):
        admission = SQLiteAdmissionTestOnly(tmp_path, central[1])
        hub, backend, _ = factory(central, url, authority=admission)
        grant_id = grant(central)
        req = request(hub, central, url, op="op-central-cancel")
        # Simulate real ControlPlane cancel after durable admission and
        # before physical effect. No external GET allowed after cancellation.
        original_fence = admission.fence_active
        def interrupted(receipt):
            hub.cancel_from_control(
                run_id=central[4], operation_id=req.operation_id,
                work_item_id=req.work_item_id)
            admission.fence_active = original_fence
            return original_fence(receipt)
        admission.fence_active = interrupted
        with pytest.raises(DurableAdmissionUnavailable):
            go(hub.submit(run_id=central[4], request=req))
        assert backend.calls == [] and not hits.exists()
        op = central[1].durable.operation_status(req.operation_id, central[2])
        assert op["state"] == "CANCEL_REQUESTED"
        replay = go(hub.reconcile(run_id=central[4], request=req))
        assert replay.state == "UNCERTAIN"
        assert backend.calls == []
        central[1].authorization.revoke(grant_id, central[2])
        with pytest.raises(AuthorizationRequired):
            go(hub.cleanup(request=req))


def test_3_fencing_loss_and_unacked_result_uncertain_without_effect_replay(central, tmp_path):
    with owned_loopback_child(tmp_path) as (url, hits, _):
        admission = SQLiteAdmissionTestOnly(tmp_path, central[1])
        hub, _, _ = factory(central, url, authority=admission)
        grant(central)
        req = request(hub, central, url, op="op-central-fence")
        original_fence = admission.fence_active
        def lose_fence(receipt):
            admission.force_fence_loss(receipt.operation_id)
            admission.fence_active = original_fence
            return original_fence(receipt)
        admission.fence_active = lose_fence
        with pytest.raises(DurableAdmissionUnavailable):
            go(hub.submit(run_id=central[4], request=req))
        assert not hits.exists()
        uncertain = go(hub.reconcile(run_id=central[4], request=req))
        assert uncertain.state == "UNCERTAIN"
        assert not hits.exists()
        # Separate fully authorized request: response reached browser, but
        # durable acknowledgment was lost. Never claim success or auto-retry.
        other = request(hub, central, url, op="op-central-noack")
        admission.before_record = lambda: admission.force_fence_loss(other.operation_id)
        result = go(hub.submit(run_id=central[4], request=other))
        assert result.state == "UNCERTAIN"
        assert result.error == "durable result acknowledgement unavailable"
        assert hits.read_text().splitlines() == ["/read"]
        again = go(hub.reconcile(run_id=central[4], request=other))
        assert again.state == "UNCERTAIN"
        assert hits.read_text().splitlines() == ["/read"]


def test_3_same_operation_mutated_intent_rejected_from_real_sqlite(central, tmp_path):
    with owned_loopback_child(tmp_path) as (url, hits, _):
        admission = SQLiteAdmissionTestOnly(tmp_path, central[1])
        hub, _, _ = factory(central, url, authority=admission)
        grant(central)
        req = request(hub, central, url, op="op-central-mutate")
        assert go(hub.submit(run_id=central[4], request=req)).state == "SUCCEEDED"
        altered = OperationRequest(
            req.operation_id, req.principal_id, req.machine_id, req.capability_id,
            req.work_item_id, req.idempotency_key,
            {**dict(req.arguments), "action": "read_page", "url": url+"/outbound"})
        with pytest.raises(DuplicateOperation):
            go(hub.submit(run_id=central[4], request=altered))
        assert hits.read_text().splitlines() == ["/read"]


def test_3_cleanup_cannot_cross_operation_workitem(central, tmp_path):
    with owned_loopback_child(tmp_path) as (url, hits, _):
        admission = SQLiteAdmissionTestOnly(tmp_path, central[1])
        hub, _, _ = factory(central, url, authority=admission)
        grant(central)
        req = request(hub, central, url)
        assert go(hub.submit(run_id=central[4], request=req)).state == "SUCCEEDED"
        go(hub.cleanup(request=req))
        forged = OperationRequest(
            req.operation_id, req.principal_id, req.machine_id, req.capability_id,
            "work-unowned", req.idempotency_key, req.arguments)
        with pytest.raises((FileNotFoundError, AuthorizationRequired)):
            go(hub.cleanup(request=forged))
        assert hits.read_text().splitlines() == ["/read"]


def test_1_registered_executor_cannot_bypass_durable_gate_even_with_valid_grant(central):
    url = "http://127.0.0.1:43211/read"
    hub, backend, _ = factory(central, url)
    grant(central)
    req = request(hub, central, url, op="op-bypass-with-grant")
    # A caller holding the registry reference does NOT get execution simply
    # by having an authorization grant; durable admission scope is mandatory.
    with pytest.raises(AuthorizationRequired, match="central durable admission required"):
        go(hub.registry.submit(req))
    assert backend.calls == []


def test_1_real_canvas_taskruntime_smoke_separate_host_wiring_required(tmp_path):
    """Canvas core is exercised, but NOT silently registered to executors."""
    from sentra_canvas.service import Canvas
    app = Canvas(tmp_path / "isolated_canvas", principal="fixture-user")
    try:
        ws = app.create_workspace("executor-central-smoke")["id"]
        runtime = app._runtime()  # actual TaskRuntime constructor
        run = runtime.run(ws)     # actual DurableRunService SQLite state
        assert run["run_id"] == app.store.workspace(ws)["run_id"]
        assert run["state"] == "RUNNING"
        assert runtime.durable.run_status(
            run["run_id"], runtime.owner, include_details=False)["state"] == "RUNNING"
        # No factory is magically wired to native task dispatch. Coordinator
        # must explicitly call CentralExecutorFactory from Canvas integration.
    finally:
        app.shutdown()


def test_2_revocation_while_http_read_inflight_remains_uncertain(central, tmp_path):
    with owned_loopback_child(tmp_path) as (url, hits, _):
        admission = SQLiteAdmissionTestOnly(tmp_path, central[1])
        hub, backend, _ = factory(central, url, authority=admission)
        grant_id = grant(central)
        req = request(hub, central, url, op="op-revoke-inflight")
        def revoke_on_backend():
            central[1].authorization.revoke(grant_id, central[2])
            backend.before_request = None
        backend.before_request = revoke_on_backend
        result = go(hub.submit(run_id=central[4], request=req))
        assert result.state == "UNCERTAIN"
        assert result.error == "grant revoked after external dispatch"
        assert hits.read_text().splitlines() == ["/read"]
        with pytest.raises(AuthorizationRequired):
            go(hub.reconcile(run_id=central[4], request=req))
        assert hits.read_text().splitlines() == ["/read"]


def test_central_legacy_durable_service_is_not_a_full_intent_authority(central):
    url = "http://127.0.0.1:43212/read"
    hub, backend, _ = factory(
        central, url, authority=central[1].durable)
    grant(central)
    req = request(hub, central, url, op="op-legacy-gate-denied")
    with pytest.raises(DurableAdmissionUnavailable,
                       match="ControlStore missing atomic intent reservation"):
        go(hub.submit(run_id=central[4], request=req))
    assert backend.calls == []
    with pytest.raises(FileNotFoundError):
        central[1].durable.operation_status(req.operation_id, central[2])


def test_control_workitem_block_cannot_be_bypassed_with_existing_grant(central):
    url = "http://127.0.0.1:43213/read"
    hub, backend, _ = factory(
        central, url, authority=SQLiteAdmissionTestOnly(
            central[0].parent, central[1]))
    grant(central)
    req = request(hub, central, url, op="op-blocked-item")
    central[1].transition_work_item(central[5], central[2], "BLOCKED",
                                    reason="owner explicitly halted the work")
    with pytest.raises(AuthorizationRequired):
        go(hub.submit(run_id=central[4], request=req))
    assert backend.calls == []


def test_1_central_factory_registers_existing_real_uia_and_daytona_inventory(central):
    from sentra_executors import (
        WindowsUIABinding, DaytonaBinding,
        declare_windows_machine, declare_daytona_machine,
    )
    hub, _, _ = factory(central, "http://127.0.0.1:43214/read")
    backend = OnlyHTTPFixtureBackend()  # never invoked; no SDK/UIA access
    win = declare_windows_machine(
        machine_id="uia-declared", owner_principal_id=central[3],
        bindings=(WindowsUIABinding(
            "uia.title.read", 101, 202, "SENTRA-UIA-LAB-12345678",
            ("_unused",), ("Text",), ("read_window_title",)),),
        policy=lambda req: True, backend=backend)  # malicious policy replaced
    sandbox = declare_daytona_machine(
        machine_id="daytona-declared", owner_principal_id=central[3],
        bindings=(DaytonaBinding(
            "daytona.readonly-lab", "sandbox-explicit", ("echo approved",)),),
        policy=lambda req: True, backend=backend)
    ui_registered = hub.register_inventory(win)
    day_registered = hub.register_inventory(sandbox)
    assert ui_registered.capability_ids == ("uia.title.read",)
    assert day_registered.capability_ids == ("daytona.readonly-lab",)
    assert [c.capability_id for c in go(hub.discover("uia-declared"))] == [
        "uia.title.read"]
    assert [c.capability_id for c in go(hub.discover("daytona-declared"))] == [
        "daytona.readonly-lab"]
    assert {m.machine_id for m in hub.registry.machines()} == {
        "central-browser", "uia-declared", "daytona-declared"}
    # No dispatch path is exposed for inventory-only Machines.
    with pytest.raises(ValueError, match="unregistered_machine_or_lab_url"):
        hub.request(run_id=central[4], work_item_id=central[5],
                    machine_id="uia-declared", operation_id="op-other",
                    url="http://127.0.0.1:43214/read")
    direct = OperationRequest(
        "op-cannot-uia", central[3], "uia-declared",
        "uia.title.read", central[5], "op-cannot-uia",
        {"pid": 101, "hwnd": 202, "action": "read_window_title"})
    with pytest.raises(AuthorizationRequired):
        go(hub.registry.submit(direct))
    assert backend.calls == []
    with pytest.raises(ValueError, match="untrusted_or_duplicate_machine_inventory"):
        hub.register_inventory(win)
