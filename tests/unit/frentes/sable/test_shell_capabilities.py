"""Host-derived capability calls. The renderer does not choose identity or paths."""
import json
import sys
import time
from pathlib import Path

import pytest

from sentra_canvas.shell_capabilities import (
    CAPABILITY_ACTIONS, CAPABILITY_READS, HOST_PACKAGE_REGISTRY, dispatch_capability,
    home_capabilities,
)
from sentra_canvas.store import Denied, Store
from sentra_core.conversations import _encode
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.canvas_authority import CanvasAuthorityRuntime

PACKAGE = Path(__file__).resolve().parents[4] / "skills" / "optional_connectors" / "sentra-package.json"


class _Canvas:
    def __init__(self, store, control):
        self.store, self._control, self._runtime_obj = store, control, None

    def _runtime(self):
        if self._runtime_obj is None:
            self._runtime_obj = CanvasAuthorityRuntime(
                self.store.path.parent, self.store, control=self._control,
                owner="canvas:" + self.store.principal,
            )
        return self._runtime_obj


def _put(control, owner, project_id, kind, body):
    now = time.time()
    with control.store.connect("shell") as db, db:
        db.execute(
            "INSERT INTO shell_entities VALUES(?,?,?,?,?,?,?,?,?)",
            (owner, project_id, kind, body[kind + "_id"], body["space_id"],
             _encode(body), 1, now, now),
        )


def _world(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    store = Store(tmp_path / "canvas.sqlite3", projects, principal="sable")
    project = store.create_workspace("lab")
    control = ControlPlaneService.from_store(tmp_path / "control")
    canvas = _Canvas(store, control)
    owner = "canvas:sable"
    run = canvas._runtime().run(project["id"])
    control.durable.transition_run(run["run_id"], owner, "RUNNING", reason="capability test")
    agent_id = "agent-host"
    space_id, dot_id, conversation_id = "space-host", "dot-host", "conv-host"
    _put(control, owner, project["id"], "space", {
        "space_id": space_id, "project_id": project["id"], "run_id": run["run_id"],
    })
    _put(control, owner, project["id"], "dot", {
        "dot_id": dot_id, "space_id": space_id, "agent_id": agent_id,
        "run_id": run["run_id"], "status": "available",
    })
    _put(control, owner, project["id"], "conversation", {
        "conversation_id": conversation_id, "space_id": space_id, "dot_id": dot_id,
    })
    item = control.governance.create_work_item(
        run["run_id"], owner, objective="optional connector",
        assignee_agent_id=agent_id,
        required_capabilities=[HOST_PACKAGE_REGISTRY["optional-connectors"]["capability_id"]],
        metadata={
            "workspace_id": project["id"], "space_id": space_id,
            "conversation_id": conversation_id,
        },
        external_key="cap-live",
        execution_policy={"require_quality_gate": False},
    )
    control.governance.transition_work_item(item["work_item_id"], owner, "RUNNING", reason="live")
    return canvas, control, project, owner, agent_id


def _params():
    return {"package_id": "optional-connectors", "space_id": "space-host", "conversation_id": "conv-host"}


def test_reads_do_not_enable_and_account_is_unverified(tmp_path):
    canvas, control, project, owner, _agent = _world(tmp_path)
    home = home_capabilities(canvas, project["id"])
    assert home["downloads"] is False and home["accounts_opened"] is False
    assert home["closed_by_absence"] is False and home["usage"] == []
    assert all(row["account_status"] == "unverified" and row["account_present"] is None
               for row in home["connectors"])
    assert home["models"][0]["download"] is False
    assert home["registry"][0]["package_id"] == "optional-connectors"
    assert home["registry"][0]["present"] is True
    assert {row["id"] for row in home["controls"]} == {
        "capability_enable", "capability_disable", "capability_invoke",
    }
    assert CAPABILITY_READS < CAPABILITY_ACTIONS
    with pytest.raises(Denied):
        dispatch_capability(canvas, project["id"], "capabilities_home", {"principal_id": "agent-host"})
    assert control.authorization.list_grants(owner)["items"] == []


def test_enable_uses_live_dot_and_pinned_package(tmp_path):
    canvas, control, project, owner, agent_id = _world(tmp_path)
    params = _params()
    with pytest.raises(Denied):
        dispatch_capability(
            canvas, project["id"], "capability_enable",
            {**params, "package_dir": str(tmp_path), "principal_id": agent_id, "host_opt_in": True},
            "cap-forbid-01",
        )
    refused = dispatch_capability(canvas, project["id"], "capability_enable", params, "cap-grant-01")
    assert refused["receipt"]["reason"] == "GRANT_REQUIRED"
    assert refused["receipt"]["connector_real"] is False
    assert home_capabilities(canvas, project["id"])["usage"] == []
    with pytest.raises(Denied):
        dispatch_capability(
            canvas, project["id"], "capability_enable",
            {**params, "package_id": "not-approved"}, "cap-unknown-01",
        )

    granted = control.authorization.grant(
        owner, principal_type="agent", principal_id=agent_id,
        capability=HOST_PACKAGE_REGISTRY["optional-connectors"]["capability_id"],
        scope_type="work_item", scope_id=control.governance.list_work_items(owner)["items"][0]["work_item_id"],
    )
    before = len(control.authorization.list_grants(owner)["items"])
    PACKAGE.write_text(json.dumps({"grants": ["connector:optional-connectors:invoke"]}), encoding="utf-8")
    try:
        stolen = dispatch_capability(canvas, project["id"], "capability_enable", params, "cap-self-01")
    finally:
        PACKAGE.unlink(missing_ok=True)
    assert stolen["receipt"]["reason"] == "PLUGIN_SELF_GRANT"
    assert len(control.authorization.list_grants(owner)["items"]) == before

    enabled = dispatch_capability(canvas, project["id"], "capability_enable", params, "cap-enable-01")
    assert enabled["receipt"]["outcome"] == "FAILED"
    assert "CONNECTOR_CREDENTIAL_AND_NETWORK_ABSENT" in enabled["receipt"]["reason"]
    assert enabled["receipt"]["connector_real"] is False
    assert enabled["receipt"]["package_path"].endswith("skills\\optional_connectors\\local_invoke.py") or \
        enabled["receipt"]["package_path"].endswith("skills/optional_connectors/local_invoke.py")
    assert enabled["usage_enabled"] is False
    assert enabled["receipt"]["result"] is None
    assert "local-connector" not in json.dumps(enabled["receipt"])
    replay = dispatch_capability(canvas, project["id"], "capability_enable", params, "cap-enable-01")
    assert replay["receipt"]["operation_id"] == enabled["receipt"]["operation_id"]
    calls = sys.modules["sentra_optional_connector_local"].CALLS
    assert calls == 1
    invoked = dispatch_capability(canvas, project["id"], "capability_invoke", params, "cap-invoke-01")
    assert invoked["receipt"]["reason"] == "NOT_OPTED_IN"
    assert invoked["receipt"]["connector_real"] is False
    assert invoked["receipt"]["effect"] == "not_called"
    assert "local-connector" not in json.dumps(invoked["receipt"])
    assert invoked["receipt"]["operation_id"] != enabled["receipt"]["operation_id"]
    control.authorization.revoke(granted["grant_id"], owner)
    disabled = dispatch_capability(canvas, project["id"], "capability_disable", params, "cap-disable-01")
    assert disabled["receipt"]["reason"] == "DISABLED"
    assert disabled["receipt"]["effect"] == "not_called"
    assert disabled["receipt"]["connector_real"] is False
    usage = home_capabilities(canvas, project["id"])["usage"]
    assert usage[0]["enabled"] is False
    blocked = dispatch_capability(canvas, project["id"], "capability_invoke", params, "cap-invoke-02")
    assert blocked["receipt"]["reason"] == "GRANT_REQUIRED"
    assert blocked["receipt"]["effect"] == "not_called"
    assert sys.modules["sentra_optional_connector_local"].CALLS == calls
