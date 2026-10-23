"""Real loopback Federation -> MachineHost -> fenced workspace file operations.

Two independent installation identities and Control Planes exchange signed
mTLS websocket frames. Files and durable receipts are real; no model is mocked
or claimed here. The typed task is supplied explicitly by the authorized caller.
"""
from __future__ import annotations

import copy
import faulthandler
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from sentra_federation.errors import FederationDenied, FederationUncertain
from sentra_federation.executor import verify_result_receipt
from sentra_federation.gateway import PeerGateway
from sentra_federation.identity import InstallationIdentity
from sentra_federation.journal import Journal
from sentra_federation.task_runtime import FederatedMachineExecutor, validate_task
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.machine_host import MachineHost

SCOPE = {"kind": "project", "project_id": "shared-project"}


def task(content="Resultado persistente: ação, 漢字 e conexão.\n"):
    return {"schema": 1, "objective": "Criar e verificar o arquivo de entrega do projeto remoto",
            "steps": [
                {"machine_kind": "workspace-files", "capability_id": "workspace:file.write",
                 "arguments": {"action": "write", "path": "entrega.txt", "content": content}},
                {"machine_kind": "workspace-files", "capability_id": "workspace:file.read",
                 "arguments": {"action": "read", "path": "entrega.txt"}},
            ]}


def grant(control, owner, capability, *, agent=None, scope="shared-project"):
    return control.authorization.grant(owner, principal_type="agent" if agent else "user",
        principal_id=agent or owner, capability=capability,
        scope_type="workspace" if agent else "project", scope_id=scope)


def pair(left, right):
    left.exchange_hello("127.0.0.1", right.bound_port)
    right.exchange_hello("127.0.0.1", left.bound_port)
    code = left.confirmation_code_for(right.identity.node_id)
    left.confirm(right.identity.node_id, code)
    right.confirm(left.identity.node_id, code)


def wait_receiver_receipt(right, intent_id):
    # A sender socket deadline says nothing about receiver completion. Observe
    # the existing protected projection; never dispatch the intent again.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        saved = right.journal.get(intent_id) or {}
        if saved.get("receipt"):
            return saved["receipt"]
        time.sleep(.02)
    pytest.fail("receiver did not persist the existing intent receipt")


def delegate_for_review(left, right, requested=None):
    requested = task() if requested is None else requested
    before = set(left.journal.intents())
    try:
        return left.delegate(right.identity.node_id, SCOPE, requested)
    except FederationUncertain:
        # Setup for review tests must also honor a lost delivery response under
        # load. Reconcile exactly that intent; do not invoke delegate twice.
        created = set(left.journal.intents()) - before
        assert len(created) == 1
        intent_id = created.pop()
        receipt = wait_receiver_receipt(right, intent_id)
        assert receipt["result_ready"] is True, receipt
        left.restore_link(right.identity.node_id)
        assert left.reconcile(right.identity.node_id, intent_id)["disposition"] == "found"
        recovered = left.journal.get(intent_id)["receipt"]
        verify_result_receipt(recovered, objective=requested, scope=SCOPE)
        return recovered


@pytest.fixture
def peers(tmp_path):
    controls, gateways = [], []
    host = None
    for label in ("left", "right"):
        root = tmp_path / label
        control = ControlPlaneService.from_store(root / "control")
        controls.append(control)
        owner = "owner-" + label
        for capability in ("federation.delegate", "federation.review"):
            grant(control, owner, capability)
        kwargs = {}
        if label == "right":
            run = control.durable.create_run(owner, workspace="shared-project")
            control.ensure_agent(run["run_id"], owner, agent_id="remote-dot", role="worker")
            workspace = root / "project"; workspace.mkdir()
            host = MachineHost(control, owner=owner)
            host.configure_workspace_files(workspace_id="shared-project", workspace_root=str(workspace), agent_id="remote-dot")
            for capability in ("workspace:file.read", "workspace:file.write"):
                grant(control, owner, capability, agent="remote-dot")
            kwargs["task_executor"] = FederatedMachineExecutor(host, project_id="shared-project",
                agent_id="remote-dot", run_id=run["run_id"])
        gateway = PeerGateway(identity=InstallationIdentity.load_or_create(root / "identity"),
            control=control, owner=owner, principal_id=owner, journal_dir=root / "journal", **kwargs)
        gateway.listen()
        gateways.append(gateway)
    pair(*gateways)
    try:
        yield gateways[0], gateways[1], controls[0], controls[1], host, tmp_path / "right" / "project"
    finally:
        for gateway in gateways: gateway.close()
        if host: host.close()
        for control in controls: control.durable.close()


def test_real_non_arithmetic_task_artifact_and_review(peers):
    left, right, _, control, host, workspace = peers
    request = task()
    receipt = delegate_for_review(left, right, request)
    assert receipt["result_ready"] is True, receipt
    assert receipt["effect_executed"] is True
    assert receipt["review_approved"] is False
    assert receipt["work_item_state"] == "IN_REVIEW"
    assert workspace.joinpath("entrega.txt").read_text(encoding="utf-8") == request["steps"][0]["arguments"]["content"]
    assert verify_result_receipt(receipt, objective=request, scope=SCOPE) == receipt["artifact_sha256"]
    document = control.durable.read_artifact(receipt["artifact_id"], max_bytes=65536)
    assert json.loads(document)["steps"][1]["evidence"]["content"] == request["steps"][0]["arguments"]["content"]
    for oid in receipt["step_operation_ids"]:
        operation = control.durable.operation_status(oid, right.owner)
        assert operation["state"] == "SUCCEEDED"
        assert operation["progress"]["work_item_id"] in receipt["step_work_item_ids"]
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        assert CentralDurableIntentAuthority(control.durable).receipt_for_operation(oid, right.owner).fencing_token >= 1
        assert host.observe(workspace_id="shared-project", operation_id=oid, as_owner=True)["state"] == "SUCCEEDED"
    reviewed = left.review(right.identity.node_id, receipt["intent_id"])
    assert reviewed["review_approved"] is True and reviewed["remote_state"] == "SUCCEEDED"
    for wi in receipt["step_work_item_ids"] + [receipt["work_item_id"]]:
        assert control.work_item_info(wi, right.owner)["state"] == "COMPLETED"
    assert left.review(right.identity.node_id, receipt["intent_id"]) == reviewed
    with pytest.raises(FederationUncertain, match="not re-executed"):
        left.delegate(right.identity.node_id, SCOPE, request, intent_id=receipt["intent_id"])


def test_lost_receipt_reconciles_persisted_effect_without_replay(peers):
    left, right, _, control, _, workspace = peers
    intent_id = "intent-" + "42" * 16
    left.drop_before_receipt = True
    with pytest.raises(FederationUncertain):
        left.delegate(right.identity.node_id, SCOPE, task(), intent_id=intent_id)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        remote = right.journal.get(intent_id)
        if remote and remote.get("receipt"): break
        time.sleep(.05)
    assert remote.get("receipt", {}).get("result_ready") is True, remote
    before = workspace.joinpath("entrega.txt").stat().st_mtime_ns
    operations = control.durable.list_operations(remote["receipt"]["run_id"], right.owner)["page"]["total"]
    # Simulate a crash after central receipt commit but before the optional
    # transport projection copied it. Reconciliation reads the central result.
    right.journal.mark(intent_id, "DISPATCHED", receipt=None)
    left.restore_link(right.identity.node_id)
    result = left.reconcile(right.identity.node_id, intent_id)
    assert result["disposition"] == "found" and result["automatic_resend"] is False
    assert left.reconcile(right.identity.node_id, intent_id)["disposition"] == "already_settled"
    assert control.durable.list_operations(remote["receipt"]["run_id"], right.owner)["page"]["total"] == operations
    assert workspace.joinpath("entrega.txt").stat().st_mtime_ns == before


def test_lost_chat_receipt_reconciles_with_its_own_capability(peers):
    left, right, local, remote, _, _ = peers
    grant(local, left.owner, "federation.conversation")
    grant(remote, right.owner, "federation.conversation")
    intent = "intent-" + "ab" * 16
    left.drop_before_receipt = True
    with pytest.raises(FederationUncertain):
        left.send_chat(right.identity.node_id, "Mensagem persistente", SCOPE, intent_id=intent)
    until = time.monotonic() + 5
    while time.monotonic() < until:
        saved = right.journal.get(intent)
        if saved and saved.get("receipt"): break
        time.sleep(.05)
    assert saved.get("receipt", {}).get("recorded") is True
    left.restore_link(right.identity.node_id)
    assert left.reconcile(right.identity.node_id, intent)["verified"] is True
    assert len(right.history(left.identity.node_id)) == 1


def test_task_capability_grant_is_separate_from_federation_grant(peers):
    left, right, _, control, _, workspace = peers
    grants = control.authorization.list_grants(right.owner)["items"]
    write = next(g for g in grants if g["capability"] == "workspace:file.write")
    control.authorization.revoke(write["grant_id"], right.owner)
    result = left.delegate(right.identity.node_id, SCOPE, task())
    assert result["result_ready"] is False
    assert not workspace.joinpath("entrega.txt").exists()
    assert result["automatic_resend"] is False
    assert control.work_item_info(result["work_item_id"], right.owner)["state"] == "REPAIRING"


def test_receipt_binds_exact_task_scope_and_step_operations(peers):
    left, right, _, _, _, _ = peers
    request = task()
    receipt = delegate_for_review(left, right, request)
    assert receipt["result_ready"], receipt
    with pytest.raises(FederationDenied):
        verify_result_receipt(receipt, objective=task("different"), scope=SCOPE)
    with pytest.raises(FederationDenied):
        verify_result_receipt(receipt, objective=request, scope={"kind": "project", "project_id": "other"})
    forged = copy.deepcopy(receipt)
    forged["step_operation_ids"] = ["forged"]
    with pytest.raises(FederationDenied):
        verify_result_receipt(forged, objective=request, scope=SCOPE)


@pytest.mark.parametrize("change", [
    lambda t: t.update(owner="attacker"),
    lambda t: t.update(schema=True),
    lambda t: t["steps"][0].update(grant_id="grant-forged"),
    lambda t: t["steps"][0]["arguments"].update(api_key="never"),
    lambda t: t.update(steps=t["steps"] * 5),
])
def test_wire_never_carries_authority(change):
    value = task(); change(value)
    with pytest.raises(FederationDenied): validate_task(value)


def test_pairing_and_revocation_persist_with_protected_journal(peers):
    left, right, _, control, host, _ = peers
    receipt = delegate_for_review(left, right)
    assert receipt["result_ready"], receipt
    path = right.journal._path
    raw = path.read_text(encoding="utf-8")
    assert "entrega.txt" not in raw and "central-machine-task" not in raw
    assert "dpapi:" in raw or "keyring:" in raw
    right.close()
    restored = PeerGateway(identity=right.identity, control=control, owner=right.owner,
        principal_id=right.principal_id, journal_dir=path.parent, task_executor=right.task_executor)
    try:
        assert restored.peers[left.identity.node_id]["pair_state"] == "paired"
        assert restored.peers[left.identity.node_id]["transport"] == "disconnected"
        assert restored.journal.get(receipt["intent_id"])["receipt"]["artifact_sha256"] == receipt["artifact_sha256"]
        restored.revoke(left.identity.node_id)
    finally: restored.close()
    revoked = PeerGateway(identity=right.identity, control=control, owner=right.owner,
        principal_id=right.principal_id, journal_dir=path.parent, task_executor=right.task_executor)
    try:
        assert revoked.peers[left.identity.node_id]["revoked"] is True
        with pytest.raises(FederationDenied, match="revoked"):
            revoked.restore_link(left.identity.node_id)
        with pytest.raises(PermissionError, match="another installation"):
            Journal(path.parent, owner="other-owner", node_id=right.identity.node_id)
    finally: revoked.close()


def test_other_paired_peer_cannot_review_or_read_another_peers_task(peers, tmp_path):
    left, right, _, _, _, _ = peers
    receipt = delegate_for_review(left, right)
    assert receipt["result_ready"], receipt
    control = ControlPlaneService.from_store(tmp_path / "third" / "control")
    owner = "third-owner"
    grant(control, owner, "federation.review")
    grant(control, owner, "federation.delegate")
    third = PeerGateway(identity=InstallationIdentity.load_or_create(tmp_path / "third" / "identity"),
        control=control, owner=owner, principal_id=owner, journal_dir=tmp_path / "third" / "journal")
    third.listen()
    try:
        pair(third, right)
        peer = third.peers[right.identity.node_id]
        for kind, body in (("review", {"intent_id": receipt["intent_id"], "decision": "approved"}),
                           ("reconcile", {"intent_id": receipt["intent_id"]})):
            with pytest.raises(FederationDenied, match="another peer"):
                third._call(peer, kind, body, intent_id=receipt["intent_id"], admit=False)
        assert right.control.work_item_info(receipt["work_item_id"], right.owner)["state"] == "IN_REVIEW"
        assert left.review(right.identity.node_id, receipt["intent_id"])["review_approved"] is True
    finally:
        third.close(); control.durable.close()


def test_review_revalidates_local_and_remote_grants(peers):
    left, right, local, remote, _, _ = peers
    receipt = delegate_for_review(left, right)
    assert receipt["result_ready"], receipt
    remote_grant = next(g for g in remote.authorization.list_grants(right.owner)["items"]
                        if g["capability"] == "federation.review")
    remote.authorization.revoke(remote_grant["grant_id"], right.owner)
    with pytest.raises(FederationDenied, match="grant missing"):
        left.review(right.identity.node_id, receipt["intent_id"])
    assert remote.work_item_info(receipt["work_item_id"], right.owner)["state"] == "IN_REVIEW"
    grant(remote, right.owner, "federation.review")
    local_grant = next(g for g in local.authorization.list_grants(left.owner)["items"]
                       if g["capability"] == "federation.review")
    local.authorization.revoke(local_grant["grant_id"], left.owner)
    with pytest.raises(FederationDenied, match="grant missing"):
        left.review(right.identity.node_id, receipt["intent_id"])
    assert remote.work_item_info(receipt["work_item_id"], right.owner)["state"] == "IN_REVIEW"


def test_pair_revocation_cancels_active_step_and_does_not_start_next_step(peers, monkeypatch):
    left, right, _, control, host, workspace = peers
    from sentra_runtime.effect_boundary import CentralEffectContext
    original = CentralEffectContext.capture_output
    published, release = threading.Event(), threading.Event()
    def pause_capture(self, path, **kwargs):
        published.set()
        assert release.wait(5)
        return original(self, path, **kwargs)
    monkeypatch.setattr(CentralEffectContext, "capture_output", pause_capture)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(left.delegate, right.identity.node_id, SCOPE, task())
        try:
            assert published.wait(5)
            right.revoke(left.identity.node_id)
        finally:
            release.set()
        with pytest.raises(FederationUncertain):
            future.result(timeout=10)
    result = next(iter(right.journal.intents().values()))["receipt"]
    assert result["result_ready"] is False and result["remote_state"] == "UNCERTAIN"
    assert result["effect_executed"] is None  # already published, unacknowledged
    assert len(result["step_operation_ids"]) == 1
    assert workspace.joinpath("entrega.txt").exists()
    oid = result["step_operation_ids"][0]
    assert control.durable.operation_status(oid, right.owner)["state"] == "UNCERTAIN"
    before = workspace.joinpath("entrega.txt").stat().st_mtime_ns
    assert host.observe(workspace_id="shared-project", operation_id=oid, as_owner=True)["state"] == "UNCERTAIN"
    assert workspace.joinpath("entrega.txt").stat().st_mtime_ns == before


@pytest.mark.parametrize("after_publish", [False, True])
def test_federation_grant_revoked_inside_slow_step_is_checked_at_physical_boundary(peers, monkeypatch, after_publish):
    left, right, _, control, host, workspace = peers
    from sentra_executors.workspace_files import WorkspaceFilesExecutor
    from sentra_runtime.effect_boundary import CentralEffectContext
    waiting, release = threading.Event(), threading.Event()
    if after_publish:
        original = CentralEffectContext.capture_output
        def pause(self, path, **kwargs):
            waiting.set(); assert release.wait(5)
            return original(self, path, **kwargs)
        monkeypatch.setattr(CentralEffectContext, "capture_output", pause)
    else:
        original = WorkspaceFilesExecutor._execute
        def pause(self, binding, arguments):
            waiting.set(); assert release.wait(5)
            return original(self, binding, arguments)
        monkeypatch.setattr(WorkspaceFilesExecutor, "_execute", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(left.delegate, right.identity.node_id, SCOPE, task())
        try:
            assert waiting.wait(5)
            delegation = next(g for g in control.authorization.list_grants(right.owner)["items"]
                              if g["capability"] == "federation.delegate")
            control.authorization.revoke(delegation["grant_id"], right.owner)
        finally:
            release.set()
        with pytest.raises(FederationUncertain):
            future.result(timeout=10)
    result = next(iter(right.journal.intents().values()))["receipt"]
    assert result["result_ready"] is False and result["remote_state"] == "UNCERTAIN", result
    assert workspace.joinpath("entrega.txt").exists() is after_publish
    assert len(result["step_operation_ids"]) == 1
    # Machine grants themselves remain live: the additional Federation guard
    # is the authority that stopped publication/capture inside the same step.
    assert all(g.get("revoked_at") is None for g in control.authorization.list_grants(right.owner)["items"]
               if g["capability"].startswith("workspace:file."))
    oid = result["step_operation_ids"][0]
    assert host.observe(workspace_id="shared-project", operation_id=oid, as_owner=True)["state"] == "UNCERTAIN"
    grant(control, right.owner, "federation.delegate")
    left.restore_link(right.identity.node_id)
    assert left.reconcile(right.identity.node_id, result["intent_id"])["disposition"] == "pending"
    assert workspace.joinpath("entrega.txt").exists() is after_publish


def revoke_authority(right, control, left, authority, *, capability="federation.delegate"):
    if authority == "pair":
        right.revoke(left.identity.node_id)
    else:
        existing = next(g for g in control.authorization.list_grants(right.owner)["items"]
                        if g["capability"] == capability and not g.get("revoked_at"))
        control.authorization.revoke(existing["grant_id"], right.owner)


@pytest.mark.parametrize("authority", ["grant", "pair"])
@pytest.mark.parametrize("boundary", ["after_steps", "artifact_registered"])
@pytest.mark.parametrize("delayed_projection", [False, True])
def test_revocation_after_last_effect_keeps_results_private_and_never_replays(peers, monkeypatch, authority, boundary, delayed_projection):
    left, right, _, control, _, workspace = peers
    waiting, release = threading.Event(), threading.Event()
    artifacts = []
    if delayed_projection:
        put = right.journal.put
        def project_after_sender_deadline(record):
            if record.get("receipt", {}).get("remote_state") == "UNCERTAIN":
                time.sleep(5.2)
            return put(record)
        monkeypatch.setattr(right.journal, "put", project_after_sender_deadline)
    if boundary == "after_steps":
        original = control.governance.submit_for_policy
        submitted = []
        def pause(work_id, *args, **kwargs):
            result = original(work_id, *args, **kwargs)
            submitted.append(work_id)
            if len(submitted) == 2:
                waiting.set(); assert release.wait(10)
            return result
        monkeypatch.setattr(control.governance, "submit_for_policy", pause)
    else:
        original = control.durable.register_artifact
        def pause(*args, **kwargs):
            result = original(*args, **kwargs)
            if str(kwargs.get("operation_id", "")).startswith("op-fedtask-"):
                artifacts.append(result)
                waiting.set(); assert release.wait(10)
            return result
        monkeypatch.setattr(control.durable, "register_artifact", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(left.delegate, right.identity.node_id, SCOPE, task())
        try:
            assert waiting.wait(10)
            revoke_authority(right, control, left, authority)
        finally:
            release.set()
        with pytest.raises(FederationUncertain):
            future.result(timeout=15)
    receipt = wait_receiver_receipt(right, next(iter(left.journal.intents())))
    assert receipt["remote_state"] == "UNCERTAIN" and receipt["result_ready"] is False, receipt
    assert receipt["effect_executed"] is True and receipt["automatic_resend"] is False
    assert not any(receipt.get(k) for k in ("result_document", "artifact_id", "artifact_sha256"))
    assert all(control.durable.operation_status(oid, right.owner)["state"] == "SUCCEEDED"
               for oid in receipt["step_operation_ids"])
    assert workspace.joinpath("entrega.txt").read_text(encoding="utf-8") == task()["steps"][0]["arguments"]["content"]
    before = workspace.joinpath("entrega.txt").stat().st_mtime_ns
    operations = control.durable.list_operations(receipt["run_id"], right.owner)["page"]["total"]
    if boundary == "artifact_registered":
        assert json.loads(control.durable.read_artifact(artifacts[0]["artifact_id"], max_bytes=65536))["steps"]
    else:
        assert not right.journal.artifact_dir.joinpath(receipt["operation_id"] + ".json").exists()
    # A restart only observes the protected central/journal receipt; even an
    # explicit direct duplicate cannot repeat the committed machine effects.
    right.close()
    restored = PeerGateway(identity=right.identity, control=control, owner=right.owner,
        principal_id=right.principal_id, journal_dir=right.journal._path.parent,
        task_executor=right.task_executor)
    try:
        assert restored.task_executor.observe(peer=left.identity.node_id, intent_id=receipt["intent_id"]) == receipt
        def never_authorize():
            raise AssertionError("duplicate must not dispatch or publish")
        duplicate = restored.task_executor.execute(intent_id=receipt["intent_id"], task=task(), scope=SCOPE,
            request_scope=SCOPE, grant_id=receipt["grant_id"], peer=left.identity.node_id,
            artifact_dir=restored.journal.artifact_dir, authorize=never_authorize)
        assert duplicate == receipt
        assert restored.journal.get(receipt["intent_id"])["receipt"] == receipt
    finally:
        restored.close()
    assert control.durable.list_operations(receipt["run_id"], right.owner)["page"]["total"] == operations
    assert workspace.joinpath("entrega.txt").stat().st_mtime_ns == before


@pytest.mark.parametrize("authority", ["grant", "pair"])
def test_final_tls_checkpoint_drops_result_when_authority_was_revoked(peers, monkeypatch, authority):
    left, right, _, control, _, workspace = peers
    waiting, release = threading.Event(), threading.Event()
    original = right._authorize_response
    def pause(frame, response):
        if frame.get("kind") == "delegate":
            waiting.set(); assert release.wait(10)
        return original(frame, response)
    monkeypatch.setattr(right, "_authorize_response", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(left.delegate, right.identity.node_id, SCOPE, task())
        try:
            if not waiting.wait(10):
                # Preserve the receiver's actual blocking stack in CI instead
                # of diagnosing a missing checkpoint from a bare Event=False.
                faulthandler.dump_traceback()
                outcome = repr(future.exception()) if future.done() else "sender still pending"
                pytest.fail("receiver never reached final TLS checkpoint: " + outcome)
            revoke_authority(right, control, left, authority)
        finally:
            release.set()
        with pytest.raises(FederationUncertain):
            future.result(timeout=15)
    saved = next(iter(right.journal.intents().values()))
    receipt = saved["receipt"]
    assert receipt["result_ready"] is True  # committed locally, never sent
    assert left.journal.get(receipt["intent_id"])["state"] == "UNCERTAIN"
    assert not left.journal.get(receipt["intent_id"]).get("receipt")
    before = workspace.joinpath("entrega.txt").stat().st_mtime_ns
    if authority == "grant":
        # A transport-level duplicate after revocation must not manufacture a
        # signed executed=False for the physical work that already succeeded.
        with pytest.raises(FederationUncertain):
            left._call(left.peers[right.identity.node_id], "delegate", {"scope": SCOPE, "body": task()},
                       intent_id=receipt["intent_id"], admit=False)
        grant(control, right.owner, "federation.delegate")
        left.restore_link(right.identity.node_id)
        assert left.reconcile(right.identity.node_id, receipt["intent_id"])["disposition"] == "found"
        assert left.journal.get(receipt["intent_id"])["receipt"] == receipt
        assert left.reconcile(right.identity.node_id, receipt["intent_id"])["disposition"] == "already_settled"
        with pytest.raises(FederationUncertain, match="not re-executed"):
            left.delegate(right.identity.node_id, SCOPE, task(), intent_id=receipt["intent_id"])
    assert workspace.joinpath("entrega.txt").stat().st_mtime_ns == before


def test_close_drains_admitted_task_before_authority_can_be_closed(peers, monkeypatch):
    left, right, _, control, host, workspace = peers
    entered, release = threading.Event(), threading.Event()
    original = host.dispatch

    def pause_before_effect(**kwargs):
        entered.set()
        assert release.wait(10)
        return original(**kwargs)

    monkeypatch.setattr(host, "dispatch", pause_before_effect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        delivery = pool.submit(left.delegate, right.identity.node_id, SCOPE, task())
        assert entered.wait(10)
        stopping = pool.submit(right.close)
        try:
            assert right._stop.wait(5)
            # Listener shutdown alone cannot license closing the shared DB.
            with pytest.raises(TimeoutError):
                stopping.result(timeout=.5)
        finally:
            release.set()
        stopping.result(timeout=10)
        with pytest.raises(FederationUncertain):
            delivery.result(timeout=10)
    with right._handlers_lock:
        assert not right._handlers
    saved = next(iter(right.journal.intents().values()))
    receipt = saved["receipt"]
    assert receipt["remote_state"] == "UNCERTAIN"
    assert receipt["result_ready"] is False
    assert control.durable.operation_status(receipt["operation_id"], right.owner)["state"] == "UNCERTAIN"
    assert not workspace.joinpath("entrega.txt").exists()


@pytest.mark.parametrize("boundary", ["last_child", "aggregate_completed", "delivery"])
def test_review_revocation_preserves_partial_decisions_and_resumes_without_io(peers, monkeypatch, boundary):
    left, right, _, control, _, workspace = peers
    receipt = delegate_for_review(left, right)
    before = workspace.joinpath("entrega.txt").stat().st_mtime_ns
    waiting, release = threading.Event(), threading.Event()
    if boundary == "delivery":
        original = right._authorize_response
        def pause(frame, response):
            if frame.get("kind") == "review":
                waiting.set(); assert release.wait(10)
            return original(frame, response)
        monkeypatch.setattr(right, "_authorize_response", pause)
    else:
        original = control.transition_work_item
        target = receipt["step_work_item_ids"][-1] if boundary == "last_child" else receipt["work_item_id"]
        def pause(work_id, owner, state, **kwargs):
            result = original(work_id, owner, state, **kwargs)
            if work_id == target and state == "COMPLETED":
                waiting.set(); assert release.wait(10)
            return result
        monkeypatch.setattr(control, "transition_work_item", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(left.review, right.identity.node_id, receipt["intent_id"])
        try:
            assert waiting.wait(10)
            revoke_authority(right, control, left, "grant", capability="federation.review")
        finally:
            release.set()
        with pytest.raises(FederationUncertain):
            future.result(timeout=15)
    assert all(control.work_item_info(wi, right.owner)["state"] == "COMPLETED"
               for wi in receipt["step_work_item_ids"])
    expected = "IN_REVIEW" if boundary == "last_child" else "COMPLETED"
    assert control.work_item_info(receipt["work_item_id"], right.owner)["state"] == expected
    assert left.journal.get(receipt["intent_id"])["receipt"]["executed"] is False
    assert workspace.joinpath("entrega.txt").stat().st_mtime_ns == before
    # Restore the receiver, observe, then explicitly finish any remaining review.
    right.close()
    restored = PeerGateway(identity=right.identity, control=control, owner=right.owner,
        principal_id=right.principal_id, journal_dir=right.journal._path.parent,
        task_executor=right.task_executor)
    restored.listen()
    try:
        grant(control, right.owner, "federation.review")
        left.exchange_hello("127.0.0.1", restored.bound_port)
        restored.exchange_hello("127.0.0.1", left.bound_port)
        observed = left.reconcile(restored.identity.node_id, receipt["intent_id"])
        assert observed["verified"] is True
        assert observed["review_pending"] is (boundary != "delivery")
        reviewed = left.review(restored.identity.node_id, receipt["intent_id"])
        assert reviewed["review_approved"] is True and reviewed["executed"] is True
        assert left.review(restored.identity.node_id, receipt["intent_id"]) == reviewed
        assert all(control.work_item_info(wi, right.owner)["state"] == "COMPLETED"
                   for wi in receipt["step_work_item_ids"] + [receipt["work_item_id"]])
        assert control.durable.list_operations(receipt["run_id"], right.owner)["page"]["total"] == 3
    finally:
        restored.close()
    assert workspace.joinpath("entrega.txt").stat().st_mtime_ns == before


@pytest.mark.parametrize("journal_gap", ["none", "receiver", "sender"])
def test_lost_review_receipt_survives_sender_restart_and_observes_central_completion(peers, monkeypatch, journal_gap):
    left, right, local, remote, _, workspace = peers
    receipt = delegate_for_review(left, right)
    before = workspace.joinpath("entrega.txt").stat().st_mtime_ns
    if journal_gap == "receiver":
        original_mark = right.journal.mark
        def lose_projection(intent_id, state, **kwargs):
            if state == "CLOSED":
                raise FederationUncertain("QA interruption after central review commit")
            return original_mark(intent_id, state, **kwargs)
        monkeypatch.setattr(right.journal, "mark", lose_projection)
    else:
        left.drop_before_receipt = True
    if journal_gap == "sender":
        original_sender_mark = left.journal.mark
        def lose_uncertain_marker(intent_id, state, **kwargs):
            if state == "REVIEW_UNCERTAIN":
                raise FederationUncertain("QA interruption before sender uncertainty projection")
            return original_sender_mark(intent_id, state, **kwargs)
        monkeypatch.setattr(left.journal, "mark", lose_uncertain_marker)
    with pytest.raises(FederationUncertain):
        left.review(right.identity.node_id, receipt["intent_id"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if remote.durable.operation_status(receipt["operation_id"], right.owner)["state"] == "SUCCEEDED":
            break
        time.sleep(.05)
    assert remote.durable.operation_status(receipt["operation_id"], right.owner)["state"] == "SUCCEEDED"
    expected_sender_state = "REVIEW_DISPATCHED" if journal_gap == "sender" else "REVIEW_UNCERTAIN"
    assert left.journal.get(receipt["intent_id"])["state"] == expected_sender_state
    if journal_gap == "sender":
        monkeypatch.setattr(left.journal, "mark", original_sender_mark)
    if journal_gap == "receiver":
        assert right.journal.get(receipt["intent_id"])["receipt"]["executed"] is False
        monkeypatch.setattr(right.journal, "mark", original_mark)
    # No approval may be repeated while observing a lost response, including
    # when the local delivery Operation already succeeded before the review.
    def do_not_approve(*args, **kwargs):
        raise AssertionError("reconciliation must never repeat a review decision")
    monkeypatch.setattr(remote.governance, "decide_policy_stage", do_not_approve)
    left.close()
    restored = PeerGateway(identity=left.identity, control=local, owner=left.owner,
        principal_id=left.principal_id, journal_dir=left.journal._path.parent)
    restored.listen()
    try:
        restored.exchange_hello("127.0.0.1", right.bound_port)
        right.exchange_hello("127.0.0.1", restored.bound_port)
        assert restored.journal.get(receipt["intent_id"])["state"] == expected_sender_state
        with pytest.raises(FederationUncertain):
            restored.review(right.identity.node_id, receipt["intent_id"])
        observed = restored.reconcile(right.identity.node_id, receipt["intent_id"])
        assert observed["disposition"] == "found" and observed["executed"] is True and observed["verified"] is True
        final = restored.journal.get(receipt["intent_id"])
        assert final["state"] == "CLOSED" and final["receipt"]["review_approved"] is True
        assert final["receipt"]["artifact_sha256"] == receipt["artifact_sha256"]
        assert restored.review(right.identity.node_id, receipt["intent_id"]) == final["receipt"]
        assert restored.reconcile(right.identity.node_id, receipt["intent_id"])["disposition"] == "already_settled"
    finally:
        restored.close()
    assert remote.durable.list_operations(receipt["run_id"], right.owner)["page"]["total"] == 3
    assert workspace.joinpath("entrega.txt").stat().st_mtime_ns == before
