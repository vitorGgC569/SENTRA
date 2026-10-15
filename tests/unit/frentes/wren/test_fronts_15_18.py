"""Fronts 15 and 18. Loopback proof of teams, pairing, mTLS and reconciliation.

These tests use the installation Control Plane. They do not open a public
port, do not serve SQLite, and do not treat a VPN address as a grant.
"""
from __future__ import annotations

import hashlib
import json
import socket
import ssl
import time

import pytest

from sentra_collab.teams import SyncConflict, TeamDenied, TeamDirectory
from sentra_federation.bind import BindRefused, assert_destination, assert_private_bind
from sentra_federation.errors import FederationDenied, FederationUncertain
from sentra_federation.executor import EXECUTOR, verify_result_receipt
from sentra_federation.gateway import PeerGateway
from sentra_federation.identity import InstallationIdentity
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_remote.peer_surface import PeerGatewaySurface


PROJECT = {"kind": "project", "project_id": "project-wren"}
SPACE = {"kind": "space", "project_id": "project-wren", "space_id": "space-1"}
DOCUMENT = {
    "kind": "document",
    "project_id": "project-wren",
    "space_id": "space-1",
    "document_id": "doc-1",
}
OTHER_DOCUMENT = {
    "kind": "document",
    "project_id": "project-wren",
    "space_id": "space-1",
    "document_id": "doc-2",
}
PRESENTATION = {"layout": {}, "nodes": {}, "notes": {"note-1": "shared view"}}
NUMERIC = "Calcule 17 * 19 e entregue o resultado numerico."


def grant(control, owner, principal, capability, project="project-wren"):
    return control.authorization.grant(
        owner,
        principal_type="user",
        principal_id=principal,
        capability=capability,
        scope_type="project",
        scope_id=project,
    )


def gateway(tmp_path, name, owner, principal):
    control = ControlPlaneService.from_store(tmp_path / name / "control")
    identity = InstallationIdentity.load_or_create(tmp_path / name / "private-identity-folder")
    peer = PeerGateway(
        identity=identity,
        control=control,
        owner=owner,
        principal_id=principal,
        journal_dir=tmp_path / name / "journal",
    )
    surface = PeerGatewaySurface(peer)
    bound = surface.start()
    return control, peer, surface, bound


def pair(left, right, left_bound, right_bound):
    left.discover(left_bound["host"] and right_bound["host"], right_bound["port"])
    right.discover(left_bound["host"], left_bound["port"])
    left.exchange_hello(right_bound["host"], right_bound["port"])
    right.exchange_hello(left_bound["host"], left_bound["port"])
    code = left.confirmation_code_for(right.identity.node_id)
    assert code == right.confirmation_code_for(left.identity.node_id)
    one_side = left.confirm(right.identity.node_id, code)
    assert one_side["paired"] is False
    assert one_side["execution_authorized"] is False
    assert right.confirm(left.identity.node_id, code)["paired"] is True
    assert left.status()["peers"][0]["paired"] is True
    assert left.status()["execution_authorized"] is False
    assert right.status()["vpn_is_authorization"] is False


def allow_channel(left_control, right_control, capability):
    grant(left_control, "owner-left", "owner-left", capability)
    grant(right_control, "owner-right", "owner-right", capability)


def close_all(*resources):
    for resource in resources:
        try:
            resource.close()
        except Exception:
            pass


def test_bind_refuses_public_and_accepts_documented_private_networks():
    assert assert_private_bind("127.0.0.1") == "127.0.0.1"
    assert assert_private_bind("10.1.2.3") == "10.1.2.3"
    assert assert_private_bind("192.168.0.8") == "192.168.0.8"
    for refused in ("0.0.0.0", "8.8.8.8", "26.1.2.3", "::"):
        with pytest.raises(BindRefused):
            assert_private_bind(refused)
    with pytest.raises(BindRefused):
        assert_private_bind("26.1.2.3", documented=["0.0.0.0/0"])
    with pytest.raises(BindRefused):
        assert_private_bind("26.1.2.3", documented=["26.0.0.0/8"])
    with pytest.raises(BindRefused):
        assert_private_bind("8.8.8.8", documented=["8.8.8.0/24"])
    assert assert_destination("26.1.2.3", 443, documented=["26.0.0.0/8"]) == ("26.1.2.3", 443)


def test_discovery_and_one_sided_confirmation_do_not_authorize(tmp_path):
    left_control, left, left_surface, left_bound = gateway(tmp_path, "left", "owner-left", "owner-left")
    right_control, right, _right_surface, right_bound = gateway(tmp_path, "right", "owner-right", "owner-right")
    try:
        assert left_bound["host"] == "127.0.0.1" and left_bound["host_class"] == "loopback"
        assert right_bound["host_class"] == "loopback"
        assert left_control.store.root != right_control.store.root
        status = left.status()
        assert status["physical_proof"] is False
        assert status["image_installer"] is False
        assert status["public_bind"] is False
        assert status["vpn_is_authorization"] is False
        with pytest.raises(FederationDenied, match="Latch"):
            left.delegate(right.identity.node_id, PROJECT, "run installer/windows/install.ps1", vpn_member=True)
        assert left_control.durable.list_runs("owner-left")["page"]["total"] == 0
        found = left.discover(right_bound["host"], right_bound["port"])
        assert found["execution_authorized"] is False
        assert found["vpn_is_authorization"] is False
        assert found["paired"] is False
        with pytest.raises(FederationDenied):
            left.delegate(right.identity.node_id, PROJECT, "do work", vpn_member=True)
        assert left_control.durable.list_runs("owner-left")["page"]["total"] == 0
        left.exchange_hello(right_bound["host"], right_bound["port"])
        right.exchange_hello(left_bound["host"], left_bound["port"])
        code = left.confirmation_code_for(right.identity.node_id)
        with pytest.raises(FederationDenied, match="confirmation code"):
            left.confirm(right.identity.node_id, "ffff-ffff-ffff-ffff")
        shown = left.confirm(right.identity.node_id, code)
        assert shown["paired"] is False
        assert shown["execution_authorized"] is False
        allow_channel(left_control, right_control, "federation.conversation")
        with pytest.raises(FederationDenied):
            left.send_chat(right.identity.node_id, "hello", PROJECT, vpn_member=True)
        assert right_control.durable.list_runs("owner-right")["page"]["total"] == 0
        diagnostics = left_surface.diagnostics()
        encoded = json.dumps(diagnostics)
        assert diagnostics["database_exposed"] is False
        assert diagnostics["public_bind"] is False
        assert "private-identity-folder" not in encoded
        assert "sqlite" not in encoded.lower()
    finally:
        close_all(left, right, left_control.durable, right_control.durable)


def test_paired_channel_chat_canvas_revoke_and_hidden_sqlite(tmp_path):
    left_control, left, left_surface, left_bound = gateway(tmp_path, "left", "owner-left", "owner-left")
    right_control, right, _right_surface, right_bound = gateway(tmp_path, "right", "owner-right", "owner-right")
    try:
        pair(left, right, left_bound, right_bound)
        allow_channel(left_control, right_control, "federation.conversation")
        allow_channel(left_control, right_control, "federation.canvas.project")
        receipt = left.send_chat(right.identity.node_id, "hello from left", PROJECT, vpn_member=True)
        assert receipt["executed"] is False
        assert receipt["automatic_resend"] is False
        assert receipt["grant_id"].startswith("grant-")
        assert left_control.durable.list_runs("owner-left")["page"]["total"] == 1
        runs_before_canvas = right_control.durable.list_runs("owner-right")["page"]["total"]
        assert right.history(left.identity.node_id)[0]["text"] == "hello from left"
        with pytest.raises(FederationDenied):
            left.project_canvas(
                right.identity.node_id, PROJECT,
                {"layout": {}, "nodes": {}, "notes": {}, "runs": {}},
            )
        projected = left.project_canvas(right.identity.node_id, PROJECT, PRESENTATION)
        assert projected["executed"] is False
        assert right_control.durable.list_runs("owner-right")["page"]["total"] == runs_before_canvas
        view = right.canvas_view(PROJECT)
        assert view["presentation"]["notes"]["note-1"] == "shared view"
        assert view["executed"] is False
        surface = left_surface.network(PROJECT)
        assert surface["renderer"] == "lumen"
        assert surface["physical_proof"] is False
        assert surface["vpn_is_authorization"] is False
        assert surface["database_exposed"] is False
        assert surface["dots"][0]["paired"] is True
        assert surface["dots"][0]["execution_authorized"] is False
        assert surface["dots"][0]["conversation"][0]["text"] == "hello from left"
        assert surface["canvas"]["presentation"]["notes"]["note-1"] == "shared view"
        operations = right_control.durable.list_operations(
            projected["run_id"], "owner-right",
        )
        assert operations["page"]["total"] >= 1
        assert all(item["effect_started"] is False for item in operations["items"])
        left.revoke(right.identity.node_id)
        with pytest.raises(FederationDenied):
            left.send_chat(right.identity.node_id, "after revoke", PROJECT)
        _assert_sqlite_is_not_served(right_bound["host"], right_bound["port"])
        encoded = json.dumps(left_surface.diagnostics())
        assert "private-identity-folder" not in encoded
        assert "sqlite" not in encoded.lower()
        assert left_surface.DATABASE_EXPOSED is False
    finally:
        close_all(left, right, left_control.durable, right_control.durable)


def test_grant_revocation_and_unpaired_certificate_do_not_admit_work(tmp_path):
    left_control, left, _surface, left_bound = gateway(tmp_path, "left", "owner-left", "owner-left")
    right_control, right, _other, right_bound = gateway(tmp_path, "right", "owner-right", "owner-right")
    attacker_control, attacker, _attacker_surface, _attacker_bound = gateway(
        tmp_path, "attacker", "owner-attacker", "owner-attacker",
    )
    try:
        pair(left, right, left_bound, right_bound)
        issued = grant(left_control, "owner-left", "owner-left", "federation.delegate")
        with pytest.raises(FederationDenied):
            left.delegate(right.identity.node_id, PROJECT, "record only", vpn_member=True)
        assert right_control.durable.list_runs("owner-right")["page"]["total"] == 0
        grant(right_control, "owner-right", "owner-right", "federation.delegate")
        receipt = left.delegate(right.identity.node_id, PROJECT, NUMERIC, vpn_member=True)
        assert receipt["result_ready"] is True
        assert receipt["passed"] is True
        assert receipt["executed"] is False
        assert receipt["executor"] == EXECUTOR
        assert receipt["task"] == NUMERIC
        assert receipt["project_id"] == "project-wren"
        assert receipt["work_item_state"] == "IN_REVIEW"
        assert receipt["remote_state"] == "WAITING_EXTERNAL"
        assert verify_result_receipt(receipt, objective=NUMERIC, scope=PROJECT) == receipt["artifact_sha256"]
        artifact = right_control.durable.read_artifact(receipt["artifact_id"], max_bytes=100000)
        assert artifact.decode("utf-8") == receipt["result_document"]
        parsed = json.loads(artifact)
        assert parsed["task"] == NUMERIC
        assert parsed["project_id"] == "project-wren"
        assert parsed["result"]["deliverable"] == "323"
        assert parsed["result"]["deliverable"] != parsed["task"]
        remote_item = right_control.work_item_info(receipt["work_item_id"], "owner-right")
        remote_operation = right_control.durable.operation_status(receipt["operation_id"], "owner-right")
        assert remote_item["state"] == "IN_REVIEW"
        assert remote_operation["state"] == "WAITING_EXTERNAL"
        assert remote_operation["progress"]["phase"] == "waiting_review"
        assert remote_operation["progress"]["automatic_resend"] is False
        # Reviewing is a separate authority from permission to delegate.
        allow_channel(left_control, right_control, "federation.review")
        closed = left.review(right.identity.node_id, receipt["intent_id"])
        assert closed["executed"] is True
        assert closed["artifact_id"] == receipt["artifact_id"]
        assert closed["artifact_sha256"] == receipt["artifact_sha256"]
        assert right_control.work_item_info(receipt["work_item_id"], "owner-right")["state"] == "COMPLETED"
        left_control.authorization.revoke(issued["grant_id"], "owner-left")
        with pytest.raises(FederationDenied):
            left.delegate(right.identity.node_id, PROJECT, "again")
        attacker.exchange_hello(right_bound["host"], right_bound["port"])
        grant(attacker_control, "owner-attacker", "owner-attacker", "federation.conversation")
        peer = attacker.peers[right.identity.node_id]
        peer["pair_state"] = "paired"
        peer["local_confirmed"] = True
        peer["remote_confirmed"] = True
        with pytest.raises(FederationDenied):
            attacker.send_chat(right.identity.node_id, "not paired on the server", PROJECT)
        assert right_control.work_item_info(receipt["work_item_id"], "owner-right")["state"] == "COMPLETED"
    finally:
        close_all(
            left, right, attacker,
            left_control.durable, right_control.durable, attacker_control.durable,
        )


def test_lost_receipt_is_reconciled_once_and_never_resent(tmp_path):
    left_control, left, _surface, left_bound = gateway(tmp_path, "left", "owner-left", "owner-left")
    right_control, right, _other, right_bound = gateway(tmp_path, "right", "owner-right", "owner-right")
    try:
        pair(left, right, left_bound, right_bound)
        allow_channel(left_control, right_control, "federation.delegate")
        intent_id = "intent-" + "ab" * 16
        left.drop_before_receipt = True
        with pytest.raises(FederationUncertain):
            left.delegate(right.identity.node_id, PROJECT, NUMERIC, intent_id=intent_id)
        deadline = time.time() + 3
        remote = None
        while time.time() < deadline:
            remote = right.journal.get(intent_id)
            if remote and remote.get("receipt"):
                break
            time.sleep(0.05)
        assert remote is not None and remote.get("receipt")
        remote_ops = right_control.durable.list_operations(remote["receipt"]["run_id"], "owner-right")
        assert remote_ops["page"]["total"] == 1
        with pytest.raises(FederationUncertain):
            left.delegate(right.identity.node_id, PROJECT, NUMERIC, intent_id=intent_id)
        assert right_control.durable.list_operations(remote["receipt"]["run_id"], "owner-right")["page"]["total"] == 1
        with pytest.raises(FederationUncertain):
            left.reconcile(right.identity.node_id, intent_id)
        left.restore_link(right.identity.node_id)
        settled = left.reconcile(right.identity.node_id, intent_id)
        assert settled["disposition"] == "found"
        assert settled["executed"] is False
        assert settled["automatic_resend"] is False
        assert remote["receipt"]["result_ready"] is True
        assert remote["receipt"]["passed"] is True
        assert remote["receipt"]["work_item_state"] == "IN_REVIEW"
        assert json.loads(remote["receipt"]["result_document"])["result"]["deliverable"] == "323"
        again = left.reconcile(right.identity.node_id, intent_id)
        assert again["disposition"] == "already_settled"
        assert right_control.durable.list_operations(remote["receipt"]["run_id"], "owner-right")["page"]["total"] == 1
        local = left.journal.get(intent_id)
        local_operation = left_control.durable.operation_status(local["operation_id"], "owner-left")
        assert local_operation["state"] == "SUCCEEDED"
        assert local_operation["result"]["verified"] is True
        assert local_operation["result"]["executed"] is False
        assert right_control.work_item_info(remote["receipt"]["work_item_id"], "owner-right")["state"] == "IN_REVIEW"
        left.drop_before_send = False
        left.drop_before_receipt = False
        allow_channel(left_control, right_control, "federation.review")
        closed = left.review(right.identity.node_id, intent_id)
        assert closed["executed"] is True
        assert closed["artifact_id"] == remote["receipt"]["artifact_id"]
        assert right_control.durable.list_operations(remote["receipt"]["run_id"], "owner-right")["page"]["total"] == 1

        missing = "intent-" + "cd" * 16
        left.drop_before_send = True
        left.drop_before_receipt = False
        with pytest.raises(FederationUncertain):
            left.delegate(right.identity.node_id, PROJECT, "never left", intent_id=missing)
        left.restore_link(right.identity.node_id)
        absent = left.reconcile(right.identity.node_id, missing)
        assert absent["disposition"] == "absent"
        assert absent["automatic_resend"] is False
        with pytest.raises(FederationUncertain):
            left.delegate(right.identity.node_id, PROJECT, "never left", intent_id=missing)
        assert right.journal.get(missing) is None
        failed = left_control.durable.operation_status(left.journal.get(missing)["operation_id"], "owner-left")
        assert failed["state"] == "FAILED"
        assert failed["error"]["executed"] is False
    finally:
        close_all(left, right, left_control.durable, right_control.durable)


def test_non_arithmetic_delegation_stays_unresolved_and_is_not_replayed(tmp_path):
    left_control, left, _surface, left_bound = gateway(tmp_path, "left", "owner-left", "owner-left")
    right_control, right, _other, right_bound = gateway(tmp_path, "right", "owner-right", "owner-right")
    try:
        pair(left, right, left_bound, right_bound)
        allow_channel(left_control, right_control, "federation.delegate")
        receipt = left.delegate(right.identity.node_id, PROJECT, "record only", vpn_member=True)
        assert receipt["result_ready"] is False
        assert receipt["passed"] is False
        assert receipt["executed"] is False
        assert receipt["automatic_resend"] is False
        assert receipt["work_item_state"] == "REPAIRING"
        assert receipt.get("result_document") in (None, "")
        assert "deliverable" not in receipt
        remote_item = right_control.work_item_info(receipt["work_item_id"], "owner-right")
        remote_operation = right_control.durable.operation_status(receipt["operation_id"], "owner-right")
        assert remote_item["state"] == "REPAIRING"
        assert remote_item["execution_state"]["quality_gate"]["passed"] is False
        assert remote_operation["state"] == "WAITING_EXTERNAL"
        assert remote_operation["progress"]["phase"] == "waiting_executor"
        assert remote_operation["progress"]["effect_started"] is False
        assert remote_operation["progress"]["automatic_resend"] is False
        with pytest.raises(FederationDenied, match="not ready"):
            verify_result_receipt(receipt, objective="record only", scope=PROJECT)
        with pytest.raises(FederationDenied, match="nothing to review"):
            left.review(right.identity.node_id, receipt["intent_id"])
        with pytest.raises(FederationUncertain, match="not re-executed"):
            left.delegate(right.identity.node_id, PROJECT, "record only", intent_id=receipt["intent_id"])
        assert right_control.durable.list_operations(receipt["run_id"], "owner-right")["page"]["total"] == 1
        assert right_control.work_item_info(receipt["work_item_id"], "owner-right")["state"] == "REPAIRING"

        echoed = dict(receipt)
        echoed["result_ready"] = True
        echoed["passed"] = True
        echoed["work_item_state"] = "IN_REVIEW"
        echoed["result_document"] = json.dumps({
            "schema": 1, "project_id": "project-wren", "task": "record only", "work_item_id": receipt["work_item_id"],
            "result": {"status": "submitted_for_review", "deliverable": "record only"},
        }, sort_keys=True, separators=(",", ":"))
        echoed["artifact_id"] = "artifact-echo"
        echoed["artifact_sha256"] = hashlib.sha256(echoed["result_document"].encode("utf-8")).hexdigest()
        with pytest.raises(FederationDenied, match="echoes the task"):
            verify_result_receipt(echoed, objective="record only", scope=PROJECT)

        lost = "intent-" + "ef" * 16
        ops_before = right_control.durable.list_operations(receipt["run_id"], "owner-right")["page"]["total"]
        left.drop_before_receipt = True
        with pytest.raises(FederationUncertain):
            left.delegate(right.identity.node_id, PROJECT, "Write the project brief", intent_id=lost)
        deadline = time.time() + 3
        remote = None
        while time.time() < deadline:
            remote = right.journal.get(lost)
            if remote and remote.get("receipt"):
                break
            time.sleep(0.05)
        assert remote["receipt"]["passed"] is False
        assert remote["receipt"]["result_ready"] is False
        assert right_control.durable.list_operations(receipt["run_id"], "owner-right")["page"]["total"] == ops_before + 1
        left.restore_link(right.identity.node_id)
        settled = left.reconcile(right.identity.node_id, lost)
        assert settled["disposition"] == "found"
        assert settled["executed"] is False
        assert settled["verified"] is False
        assert settled["automatic_resend"] is False
        local = left.journal.get(lost)
        assert local["state"] == "UNRESOLVED"
        assert local["receipt"]["passed"] is False
        local_operation = left_control.durable.operation_status(local["operation_id"], "owner-left")
        assert local_operation["state"] == "FAILED"
        assert local_operation["error"]["verified"] is False
        assert local_operation["error"]["automatic_resend"] is False
        again = left.reconcile(right.identity.node_id, lost)
        assert again["disposition"] == "already_settled"
        assert right_control.durable.list_operations(receipt["run_id"], "owner-right")["page"]["total"] == ops_before + 1
        assert right_control.work_item_info(remote["receipt"]["work_item_id"], "owner-right")["state"] == "REPAIRING"
    finally:
        close_all(left, right, left_control.durable, right_control.durable)


def test_team_scope_uses_the_installation_control_plane(tmp_path):
    control = ControlPlaneService.from_store(tmp_path / "control")
    owner = "owner-left"
    try:
        directory = TeamDirectory(
            control, owner=owner, actor_id=owner, directory=tmp_path / "teams",
        )
        assert directory.control is control
        with pytest.raises(TeamDenied):
            directory.register_account({
                "account_id": "account-1",
                "principal_id": "member-1",
                "display_name": "Ada",
                "project_id": "project-wren",
                "token": "sk-secret",
            })
        with pytest.raises(TeamDenied):
            directory.register_account({
                "account_id": "account-1",
                "principal_id": "member-1",
                "display_name": "BEGIN PRIVATE KEY",
                "project_id": "project-wren",
            })
        with pytest.raises(TeamDenied):
            directory.register_account({
                "account_id": "account-1",
                "principal_id": "member-1",
                "display_name": "Ada",
                "project_id": "project-wren",
            })
        register = grant(control, owner, owner, "collab.account.register")
        manage = grant(control, owner, owner, "collab.team.manage")
        directory.register_account({
            "account_id": "account-1",
            "principal_id": "member-1",
            "display_name": "Ada",
            "project_id": "project-wren",
        })
        exported = directory.export_account("account-1")
        assert exported["credentials_stored"] is False
        assert "token" not in exported
        directory.create_team({"team_id": "team-1", "project_id": "project-wren", "name": "Wren"})
        directory.add_member({"team_id": "team-1", "account_id": "account-1", "scope": DOCUMENT})
        write = grant(control, owner, "member-1", "collab.sync.write")
        read = grant(control, owner, "member-1", "collab.sync.read")
        with pytest.raises(TeamDenied):
            directory.sync({
                "team_id": "team-1",
                "account_id": "account-1",
                "principal_id": "member-1",
                "scope": PROJECT,
                "presentation": PRESENTATION,
                "expected_revision": 0,
            })
        with pytest.raises(TeamDenied):
            directory.sync({
                "team_id": "team-1",
                "account_id": "account-1",
                "principal_id": "member-1",
                "scope": OTHER_DOCUMENT,
                "presentation": PRESENTATION,
                "expected_revision": 0,
            })
        stored = directory.sync({
            "team_id": "team-1",
            "account_id": "account-1",
            "principal_id": "member-1",
            "scope": DOCUMENT,
            "presentation": PRESENTATION,
            "expected_revision": 0,
        })
        assert stored["revision"] == 1
        assert stored["executed"] is False
        assert stored["credentials_stored"] is False
        assert stored["control_plane"] == "installation"
        assert stored["grant_id"] == write["grant_id"]
        with pytest.raises(SyncConflict):
            directory.sync({
                "team_id": "team-1",
                "account_id": "account-1",
                "principal_id": "member-1",
                "scope": DOCUMENT,
                "presentation": PRESENTATION,
                "expected_revision": 0,
            })
        seen = directory.read_sync({
            "team_id": "team-1",
            "account_id": "account-1",
            "principal_id": "member-1",
            "scope": DOCUMENT,
        })
        assert seen["presentation"]["notes"]["note-1"] == "shared view"
        assert seen["grant_id"] == read["grant_id"]
        control.authorization.revoke(write["grant_id"], owner)
        with pytest.raises(TeamDenied):
            directory.sync({
                "team_id": "team-1",
                "account_id": "account-1",
                "principal_id": "member-1",
                "scope": DOCUMENT,
                "presentation": PRESENTATION,
                "expected_revision": 1,
            })
        assert directory.export_account("account-1")["credentials_stored"] is False
        assert register["grant_id"] != manage["grant_id"]
        space_member = directory.add_member({"team_id": "team-1", "account_id": "account-1", "scope": SPACE})
        assert space_member["scope"]["kind"] == "space"
        assert space_member["credentials_stored"] is False
        control.authorization.revoke(register["grant_id"], owner)
        with pytest.raises(TeamDenied):
            directory.export_account("account-1")
    finally:
        control.durable.close()


def test_team_membership_narrows_a_paired_projection(tmp_path):
    left_control, left, _surface, left_bound = gateway(tmp_path, "left", "owner-left", "owner-left")
    right_control, right, _other, right_bound = gateway(tmp_path, "right", "owner-right", "owner-right")
    try:
        teams = TeamDirectory(
            right_control, owner="owner-right", actor_id="owner-right",
            directory=tmp_path / "right-teams",
        )
        grant(right_control, "owner-right", "owner-right", "collab.account.register")
        grant(right_control, "owner-right", "owner-right", "collab.team.manage")
        teams.register_account({
            "account_id": "account-right",
            "principal_id": "owner-right",
            "display_name": "Right",
            "project_id": "project-wren",
        })
        teams.create_team({"team_id": "team-right", "project_id": "project-wren", "name": "Right"})
        teams.add_member({"team_id": "team-right", "account_id": "account-right", "scope": DOCUMENT})
        right.teams = teams
        pair(left, right, left_bound, right_bound)
        allow_channel(left_control, right_control, "federation.canvas.project")
        with pytest.raises((FederationDenied, TeamDenied)):
            left.project_canvas(right.identity.node_id, PROJECT, PRESENTATION)
        assert right.canvas_view(PROJECT) is None
        assert right_control.durable.list_runs("owner-right")["page"]["total"] == 0
    finally:
        close_all(left, right, left_control.durable, right_control.durable)


def _assert_sqlite_is_not_served(host, port):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((host, port), timeout=3)
    tls = context.wrap_socket(raw, server_hostname=None)
    try:
        tls.sendall(b"GET /canvas.sqlite3 HTTP/1.1\r\nHost: sentra-peer\r\n\r\n")
        data = b""
        tls.settimeout(2)
        while True:
            try:
                chunk = tls.recv(1024)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
            if len(data) > 4096:
                break
        assert b"sqlite" not in data.lower()
        assert b"CREATE TABLE" not in data
        assert data.startswith(b"HTTP/1.1 404")
    finally:
        tls.close()
