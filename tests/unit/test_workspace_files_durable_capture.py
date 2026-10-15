"""Real file publication/capture through MachineHost's central physical fence."""
import hashlib

import pytest

from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.effect_boundary import CentralEffectContext
from sentra_runtime.machine_host import MachineHost


@pytest.fixture
def file_host(tmp_path):
    control = ControlPlaneService.from_store(tmp_path / "control")
    owner, agent, project = "capture-owner", "capture-agent", "capture-project"
    run = control.durable.create_run(owner, workspace=project)
    control.ensure_agent(run["run_id"], owner, agent_id=agent, role="worker")
    root = tmp_path / "workspace"; root.mkdir()
    host = MachineHost(control, owner=owner)
    machine = host.configure_workspace_files(workspace_id=project, workspace_root=str(root), agent_id=agent)
    item = control.create_work_item(run["run_id"], owner, objective="Publish one UTF-8 file",
        assignee_agent_id=agent, required_capabilities=["workspace:file.write"],
        metadata={"workspace_id": project, "machine_id": machine["machine_id"]})
    control.start_work_item_execution(item["work_item_id"], owner, run_id=run["run_id"], agent_id=agent)
    grant = control.authorization.grant(owner, principal_type="agent", principal_id=agent,
        capability="workspace:file.write", scope_type="work_item", scope_id=item["work_item_id"])
    def dispatch(arguments, oid="op-capture-test"):
        return host.dispatch(workspace_id=project, work_item_id=item["work_item_id"],
            machine_id=machine["machine_id"], capability_id="workspace:file.write",
            operation_id=oid, arguments=arguments, idempotency_key=oid)
    try:
        yield control, owner, host, root, item, grant, dispatch
    finally:
        host.close(); control.durable.close()


def test_relative_workspace_write_captures_exact_published_bytes(file_host):
    control, owner, _, root, item, _, dispatch = file_host
    content = "Captura durável: ação e 漢字.\n"
    result = dispatch({"action": "write", "path": "result.txt", "content": content})
    assert result["state"] == "SUCCEEDED", result
    assert result["evidence"]["durable_capture"] is True
    aid = result["evidence"]["artifact_id"]
    assert control.durable.read_artifact(aid, max_bytes=1000) == content.encode("utf-8")
    artifact = control.durable.artifact_info(aid, owner)
    assert artifact["metadata"]["work_item_id"] == item["work_item_id"]
    assert artifact["sha256"] == hashlib.sha256(root.joinpath("result.txt").read_bytes()).hexdigest()
    before = root.joinpath("result.txt").stat().st_mtime_ns
    again = dispatch({"action": "write", "path": "result.txt", "content": content})
    assert again["state"] == "SUCCEEDED"
    assert root.joinpath("result.txt").stat().st_mtime_ns == before


@pytest.mark.parametrize("path", ["../escape.txt", "C:/outside.txt", "/outside.txt", "result.txt:stream"])
def test_relative_output_binding_cannot_escape_authorized_root(file_host, path):
    _, _, _, root, _, _, dispatch = file_host
    result = dispatch({"action": "write", "path": path, "content": "denied"})
    assert result["state"] != "SUCCEEDED"
    assert not root.joinpath("result.txt").exists()
    assert not root.parent.joinpath("escape.txt").exists()


def test_capture_failure_after_publication_stays_uncertain_and_never_replays(file_host, monkeypatch):
    control, owner, _, root, _, _, dispatch = file_host
    original = CentralEffectContext.capture_output
    calls = []
    def fail_capture(self, path, **kwargs):
        calls.append(path)
        assert path.read_bytes() == b"already published"
        raise OSError("induced artifact storage failure")
    monkeypatch.setattr(CentralEffectContext, "capture_output", fail_capture)
    args = {"action": "write", "path": "result.txt", "content": "already published"}
    result = dispatch(args)
    assert result["state"] == "UNCERTAIN"
    assert root.joinpath("result.txt").read_bytes() == b"already published"
    before = root.joinpath("result.txt").stat().st_mtime_ns
    monkeypatch.setattr(CentralEffectContext, "capture_output", original)
    again = dispatch(args)
    assert again["state"] == "UNCERTAIN"
    assert len(calls) == 1
    assert root.joinpath("result.txt").stat().st_mtime_ns == before
    assert control.durable.operation_status(result["operation_id"], owner)["state"] == "UNCERTAIN"


def test_revocation_between_publication_and_capture_withholds_success(file_host, monkeypatch):
    control, owner, _, root, item, grant, dispatch = file_host
    original = CentralEffectContext.capture_output
    def revoke_at_capture(self, path, **kwargs):
        assert path.exists()
        control.authorization.revoke(grant["grant_id"], owner)
        return original(self, path, **kwargs)
    monkeypatch.setattr(CentralEffectContext, "capture_output", revoke_at_capture)
    args = {"action": "write", "path": "result.txt", "content": "published before revocation"}
    result = dispatch(args)
    assert result["state"] == "UNCERTAIN", result
    before = root.joinpath("result.txt").stat().st_mtime_ns
    assert control.durable.operation_status(result["operation_id"], owner)["state"] == "UNCERTAIN"
    # Reauthorization permits observation, never replays this old intent.
    monkeypatch.setattr(CentralEffectContext, "capture_output", original)
    control.authorization.grant(owner, principal_type="agent", principal_id="capture-agent",
        capability="workspace:file.write", scope_type="work_item", scope_id=item["work_item_id"])
    assert dispatch(args)["state"] == "UNCERTAIN"
    assert root.joinpath("result.txt").stat().st_mtime_ns == before
