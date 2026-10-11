"""No unsafe Docker rm: cross-run operation claims, SQLite restart and identity proof."""
import time
import pytest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.mcpb_orphans import MCPBDockerOwnership, DockerOwnershipDenied

IMAGE = "sha256:" + "a" * 64
CID = "b" * 64


def test_orphan_claim_bound_to_existing_central_operation_and_no_prefix_gc(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    cp.durable.create_run("owner", run_id="run-sandbox", workspace=str(ws))
    cp.ensure_agent("run-sandbox", "owner", agent_id="worker", role="worker")
    cp.create_work_item("run-sandbox", "owner", work_item_id="WI-sandbox",
                        objective="MCP Docker operation", assignee_agent_id="worker")
    cp.transition_work_item("WI-sandbox", "owner", "RUNNING")
    cp.durable.create_operation("run-sandbox", "owner", kind="sentra.machine",
        operation_id="op-sandbox", idempotency_key="sandbox-request")
    cp.durable.update_operation("op-sandbox", "owner",
                                progress={"work_item_id": "WI-sandbox"})
    ledger = MCPBDockerOwnership(cp)
    kwargs = dict(owner="owner", workspace=str(ws), run_id="run-sandbox",
                  work_item_id="WI-sandbox", operation_id="op-sandbox", image_id=IMAGE)
    with pytest.raises(DockerOwnershipDenied):
        ledger.prepare(**{**kwargs, "image_id":"latest"})
    spec = ledger.prepare(**kwargs)
    assert spec["needs_durable_fence"]
    with pytest.raises(DockerOwnershipDenied, match="already reserved"):
        ledger.prepare(**kwargs)
    proof = {"Id": CID, "Image": IMAGE, "Name": "/" + spec["container_name"],
             "Config": {"Labels": spec["docker_labels"]}}
    with pytest.raises(DockerOwnershipDenied):
        ledger.bind("other", "op-sandbox", proof)
    with pytest.raises(DockerOwnershipDenied):
        ledger.bind("owner", "op-sandbox", {**proof, "Image": "sha256:" + "c"*64})
    assert ledger.bind("owner", "op-sandbox", proof)["container_id"] == CID
    with pytest.raises(DockerOwnershipDenied):
        ledger.cleanup_candidate(owner="owner", operation_id="op-sandbox",
                                 inspect=proof, approved=False)
    with pytest.raises(DockerOwnershipDenied):
        ledger.cleanup_candidate(owner="owner", operation_id="op-sandbox",
                                 inspect=proof, approved=True)
    # Simulate elapsed grace and terminal central Operation, without docker CLI.
    cp.durable.update_operation("op-sandbox", "owner", state="RUNNING")
    cp.durable.update_operation("op-sandbox", "owner", state="SUCCEEDED")
    with cp.store.connect("plugin_bundle") as db:
        db.execute("UPDATE mcpb_docker_ownership SET created_at=?,updated_at=? "
                   "WHERE operation_id='op-sandbox'", (time.time()-180,time.time()-180))
    reopened = MCPBDockerOwnership(cp)
    with pytest.raises(DockerOwnershipDenied):
        reopened.cleanup_candidate(owner="owner", operation_id="op-sandbox",
            inspect={**proof, "Id": "d"*64}, approved=True)
    with pytest.raises(DockerOwnershipDenied):
        reopened.cleanup_candidate(owner="owner", operation_id="op-sandbox",
            inspect={**proof, "Config": {"Labels": {"sentra.owner_claim":"other"}}},
            approved=True)
    candidate = reopened.cleanup_candidate(owner="owner", operation_id="op-sandbox",
                                            inspect=proof, approved=True)
    assert candidate["container_id"] == CID and not candidate["performed"]
    with pytest.raises(DockerOwnershipDenied):
        reopened.mark_cleaned("owner", "op-sandbox")
    assert reopened.mark_cleaned("owner", "op-sandbox", observed_absent=True)["cleaned"]
    with pytest.raises(DockerOwnershipDenied):
        reopened.cleanup_candidate(owner="owner", operation_id="op-sandbox",
                                    inspect=proof, approved=True)
    cp.durable.close()
