"""Canvas shell adapter for the installation peer gateway."""
from contextlib import closing
import json

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.shell_federation import (
    NETWORK_ACTIONS, NETWORK_READS, dispatch_network, home_network,
)
from sentra_canvas.store import Denied
from sentra_core.conversations import _decode
from sentra_federation.errors import FederationDenied


def _scope(app):
    project = app.create_workspace("Federation")["id"]
    app.create_agent(project, "Dot", "sentra/test-one", "worker", start=False)
    control = app._shell_service()
    owner = app._runtime().owner
    shell_project = control.shell._project(owner, project)
    space_id = control.shell._migrate(owner, shell_project)
    with closing(control.store.connect("shell")) as db:
        rows = db.execute(
            "SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND kind='dot'",
            (owner, project),
        ).fetchall()
    dot_id = _decode(rows[0]["body"])["dot_id"]
    return control, owner, project, space_id, dot_id


def _allow(control, owner, capability, project):
    control.authorization.grant(
        owner, principal_type="user", principal_id=owner,
        capability=capability, scope_type="project", scope_id=project,
    )


def test_home_does_not_listen_and_mutations_use_the_canvas_control(tmp_path):
    left = Canvas(tmp_path / "left", state_dir=tmp_path / "left-state", principal="left")
    right = Canvas(tmp_path / "right", state_dir=tmp_path / "right-state", principal="right")
    try:
        assert "network_enable" in NETWORK_ACTIONS and "network_home" in NETWORK_READS
        left_control, left_owner, left_project, left_space, left_dot = _scope(left)
        right_control, right_owner, right_project, right_space, right_dot = _scope(right)
        assert left_control is left._shell_service()
        assert right_owner == "canvas:" + right.store.principal
        home = home_network(left, left_project)
        assert home["enabled"] is False and home["listening"] is False
        assert home["renderer"] == "lumen" and home["physical_proof"] is False
        assert not (left.state_dir / "federation").exists()
        with pytest.raises(Denied):
            dispatch_network(left, left_project, "network_enable", {
                "space_id": left_space, "dot_id": left_dot, "renderer": "lumen",
            }, request_key="enable-left-1")
        with pytest.raises(Denied):
            dispatch_network(left, left_project, "network_enable", {
                "space_id": left_space, "dot_id": left_dot,
            }, request_key="enable-left-2")
        for control, owner, project, names in (
            (left_control, left_owner, left_project, (
                "federation.gateway.enable", "federation.invite", "federation.conversation",
                "federation.delegate", "federation.review",
            )),
            (right_control, right_owner, right_project, (
                "federation.gateway.enable", "federation.invite", "federation.conversation",
                "federation.delegate", "federation.review",
            )),
        ):
            for name in names:
                _allow(control, owner, name, project)
        enabled = dispatch_network(left, left_project, "network_enable", {
            "space_id": left_space, "dot_id": left_dot,
        }, request_key="enable-left-2")
        assert enabled["status"] == "committed"
        assert enabled["host_class"] == "loopback" and enabled["public_bind"] is False
        assert "grant_id" not in json.dumps(enabled)
        central = enabled["central"]
        effect = left_control.work_item_info(central["work_item_id"], left_owner)
        assert effect["state"] == "IN_REVIEW"
        assert effect["assignee_agent_id"] == central["assignee_agent_id"]
        assert left_control.durable.operation_status(central["operation_id"], left_owner)["state"] == "SUCCEEDED"
        assert central["fencing_token"] >= 1
        again = dispatch_network(left, left_project, "network_enable", {
            "space_id": left_space, "dot_id": left_dot,
        }, request_key="enable-left-2")
        assert again == enabled
        shown = home_network(left, left_project)
        assert shown["enabled"] is True and shown["listening"] is True and shown["disconnected"] is False
        assert shown["configuration"]["private_bind"] is True
        assert shown["renderer"] == "lumen" and "sqlite" not in json.dumps(shown).lower()
        assert "grant_id" not in json.dumps(shown) and "fingerprint" not in json.dumps(shown)
        other = dispatch_network(right, right_project, "network_enable", {
            "space_id": right_space, "dot_id": right_dot,
        }, request_key="enable-right-1")
        invited = dispatch_network(left, left_project, "network_invite", {
            "space_id": left_space, "dot_id": left_dot,
            "address": "127.0.0.1", "port": other["port"],
        }, request_key="invite-left-1")
        assert invited["execution_authorized"] is False
        back = dispatch_network(right, right_project, "network_invite", {
            "space_id": right_space, "dot_id": right_dot,
            "address": "127.0.0.1", "port": enabled["port"],
        }, request_key="invite-right-1")
        assert invited["confirmation_code"] == back["confirmation_code"]
        dispatch_network(left, left_project, "network_invite", {
            "space_id": left_space, "dot_id": left_dot,
            "address": "127.0.0.1", "port": other["port"],
            "confirmation": invited["confirmation_code"],
        }, request_key="invite-left-2")
        paired = dispatch_network(right, right_project, "network_invite", {
            "space_id": right_space, "dot_id": right_dot,
            "address": "127.0.0.1", "port": enabled["port"],
            "confirmation": back["confirmation_code"],
        }, request_key="invite-right-2")
        assert paired["peer"]["paired"] is True
        node = invited["peer"]["node_id"]
        spoken = dispatch_network(left, left_project, "network_converse", {
            "space_id": left_space, "dot_id": left_dot, "node_id": node, "text": "hello dot",
        }, request_key="talk-left-1")
        assert spoken["receipt"]["executed"] is False
        unresolved = dispatch_network(left, left_project, "network_delegate", {
            "space_id": left_space, "dot_id": left_dot, "node_id": node, "task": "Write the project brief",
        }, request_key="task-left-plain")
        assert unresolved["receipt"]["result_ready"] is False
        assert unresolved["receipt"]["passed"] is False
        assert unresolved["receipt"]["work_item_state"] == "REPAIRING"
        assert not unresolved["result_document"]
        plain = right_control.work_item_info(unresolved["receipt"]["work_item_id"], right_owner)
        assert plain["execution_state"]["quality_gate"]["passed"] is False
        with pytest.raises(FederationDenied, match="nothing to review"):
            dispatch_network(left, left_project, "network_review", {
                "space_id": left_space, "dot_id": left_dot,
                "node_id": node, "intent_id": unresolved["receipt"]["intent_id"],
            }, request_key="review-left-plain")
        delegated = dispatch_network(left, left_project, "network_delegate", {
            "space_id": left_space, "dot_id": left_dot, "node_id": node,
            "task": "Calcule 17 * 19 e entregue o resultado numerico.",
        }, request_key="task-left-1")
        receipt = delegated["receipt"]
        assert receipt["result_ready"] is True and receipt["passed"] is True
        assert receipt["work_item_state"] == "IN_REVIEW"
        assert receipt["project_id"] == right_project
        assert delegated["result_document"]
        artifact = right_control.durable.read_artifact(receipt["artifact_id"], max_bytes=100000)
        assert artifact.decode("utf-8") == delegated["result_document"]
        assert json.loads(artifact)["result"]["deliverable"] == "323"
        reviewed = dispatch_network(left, left_project, "network_review", {
            "space_id": left_space, "dot_id": left_dot,
            "node_id": node, "intent_id": receipt["intent_id"],
        }, request_key="review-left-1")
        assert reviewed["receipt"]["executed"] is True
        assert reviewed["receipt"]["artifact_id"] == receipt["artifact_id"]
        assert reviewed["central"]["operation_state"] == "SUCCEEDED"
        assert right_control.work_item_info(receipt["work_item_id"], right_owner)["state"] == "COMPLETED"
        # The same authenticated bridge accepts an explicit non-arithmetic
        # task and maps distinct installation project IDs without widening it.
        host = right._machine_service()
        remote_agent = other["central"]["assignee_agent_id"]
        workspace_root = right.store.workspace(right_project)["path"]
        host.configure_workspace_files(workspace_id=right_project,
            workspace_root=workspace_root, agent_id=remote_agent)
        for cap in ("workspace:file.write", "workspace:file.read"):
            right_control.authorization.grant(right_owner, principal_type="agent", principal_id=remote_agent,
                capability=cap, scope_type="workspace", scope_id=workspace_root)
        task = {"schema": 1, "objective": "Entregar arquivo no projeto remoto", "steps": [
            {"machine_kind": "workspace-files", "capability_id": "workspace:file.write",
             "arguments": {"action": "write", "path": "fed-bridge.txt", "content": "Entrega real pelo Canvas"}},
            {"machine_kind": "workspace-files", "capability_id": "workspace:file.read",
             "arguments": {"action": "read", "path": "fed-bridge.txt"}},
        ]}
        real = dispatch_network(left, left_project, "network_delegate", {
            "space_id": left_space, "dot_id": left_dot, "node_id": node, "task": task,
        }, request_key="task-real-files")
        assert real["receipt"]["result_ready"] is True, real
        assert real["receipt"]["project_id"] == right_project
        assert real["receipt"]["request_scope"]["project_id"] == left_project
        assert json.loads(real["result_document"])["steps"][1]["evidence"]["content"] == "Entrega real pelo Canvas"
        closed = dispatch_network(left, left_project, "network_review", {
            "space_id": left_space, "dot_id": left_dot, "node_id": node,
            "intent_id": real["receipt"]["intent_id"],
        }, request_key="review-real-files")
        assert closed["receipt"]["review_approved"] is True
        dispatch_network(left, left_project, "network_revoke", {
            "space_id": left_space, "dot_id": left_dot, "node_id": node,
        }, request_key="revoke-left-1")
        dispatch_network(left, left_project, "network_disable", {
            "space_id": left_space, "dot_id": left_dot,
        }, request_key="disable-left-1")
        left._federation_gateways.clear()
        restored = home_network(left, left_project)
        assert restored["listening"] is False and restored["disconnected"] is True
        assert restored["configured"] is True and restored["enabled"] is False
        assert not (left.state_dir / "federation" / left_project / "identity" / "key.pem").stat().st_size == 0
    finally:
        for app in (left, right):
            for session in getattr(app, "_federation_gateways", {}).values():
                session.gateway.close()
            if getattr(app, "_machine_host", None) is not None:
                app._machine_host.close()
            app._runtime().close()
            app._shell_service().durable.close()
