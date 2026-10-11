"""Real ControlPlane Run, WorkItem, SQLite and immutable skill revision lifecycle."""
import pytest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService


def test_pinned_skill_activation_replace_revoke_and_worker_isolation(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    control = ControlPlaneService(DurableRunService(tmp_path / "state"),
                                  ContextBusService(tmp_path / "state"))
    owner = "owner"
    control.durable.create_run(owner, run_id="run-skill-a", workspace=str(ws))
    control.ensure_agent("run-skill-a", owner, agent_id="worker-a", role="worker")
    control.ensure_agent("run-skill-a", owner, agent_id="worker-b", role="worker")
    control.create_work_item("run-skill-a", owner, work_item_id="WI-skill-a",
                             objective="Immutable authorized skill",
                             assignee_agent_id="worker-a")
    control.transition_work_item("WI-skill-a", owner, "RUNNING")
    lib = control.skill_library
    v1 = "---\nname: fixed-skill\ndescription: Read only\n---\noriginal"
    v2 = v1 + "\nrevised"
    first = lib.import_files(owner, ws, {"SKILL.md": v1}, source="fixture:one")
    second = lib.import_files(owner, ws, {"SKILL.md": v2}, source="fixture:two")
    assert first["package_id"] != second["package_id"]
    ctx = ("owner", ws, "WI-skill-a", "worker-a")
    assert lib.disclose(*ctx)["items"] == []
    with pytest.raises(PermissionError):
        lib.disclose(*ctx, package_id=first["package_id"])
    lib.activate(owner, ws, first["package_id"], "WI-skill-a", "worker-a")
    assert lib.disclose(*ctx, package_id=first["package_id"])["content"] == v1
    with pytest.raises(PermissionError):
        lib.disclose(owner, ws, "WI-skill-a", "worker-b",
                     package_id=first["package_id"])
    with pytest.raises(PermissionError):
        lib.replace_activation(owner, ws, "incorrect", second["package_id"],
                               "WI-skill-a", "worker-a")
    assert lib.disclose(*ctx, package_id=first["package_id"])["content"] == v1
    switched = lib.replace_activation(owner, ws, first["package_id"],
                                      second["package_id"], "WI-skill-a", "worker-a")
    assert switched["package_id"] == second["package_id"]
    with pytest.raises(PermissionError):
        lib.disclose(*ctx, package_id=first["package_id"])
    assert lib.disclose(*ctx, package_id=second["package_id"])["content"] == v2
    assert lib.deactivate(owner, ws, second["package_id"], "WI-skill-a",
                          "worker-a")["deactivated"]
    assert not lib.deactivate(owner, ws, second["package_id"], "WI-skill-a",
                              "worker-a")["deactivated"]
    assert lib.disclose(*ctx)["items"] == []
    lib.activate(owner, ws, second["package_id"], "WI-skill-a", "worker-a")
    lib.revoke(owner, ws, second["package_id"], second["revision"])
    with pytest.raises(PermissionError):
        lib.disclose(*ctx, package_id=second["package_id"])
    assert lib.disclose(*ctx)["items"] == []
    control.durable.close()
