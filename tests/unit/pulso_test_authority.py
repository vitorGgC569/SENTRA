"""Real SQLite admission for synthetic Pulso provider unit tests."""
from sentra_interop.central import CentralInteropAdapter
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import Capability, Machine


def make_authority(path, capability, *, owner="owner1"):
    capabilities = (capability,) if isinstance(capability, str) else tuple(capability)
    durable = DurableRunService(path)
    control = ControlPlaneService(durable, ContextBusService(path))
    durable.create_run(owner, run_id="run1", workspace=str(path.parent))
    control.ensure_agent("run1", owner, agent_id="agent1", role="worker")
    control.create_work_item("run1", owner, work_item_id="wi1", objective="Synthetic channel test",
                             assignee_agent_id="agent1", required_capabilities=list(capabilities),
                             metadata={"workspace_id":"ws1"})
    control.transition_work_item("wi1", owner, "RUNNING")
    for item in capabilities:
        control.authorization_grant(owner, principal_type="agent", principal_id="agent1",
                                    capability=item, scope_type="work_item", scope_id="wi1")
    return CentralInteropAdapter(control=control, owner=owner, run_id="run1",
        machine=Machine("machine1", "channels", owner, tuple(Capability(item, item) for item in capabilities)))
