"""Persistent worker ownership test with real governance/SQLite after a vanished session."""
import time

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.plugin_host import PluginWorkerHost


class ProcessEvidence:
    sessions = []
    def list_sessions(self, owner):
        return [item for item in self.sessions if item["owner"] == owner]


def test_worker_liveness_fences_mismatched_session_and_restart_is_not_automatic(tmp_path):
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    plugin = cp.governance.register_plugin("owner",
        manifest={"name":"worker-health","version":"1.0.0","capabilities":[]},
        verified_methods=[], narrowed_capabilities=[], trusted_ui=False,
        metadata={"origin":"test"})
    process = ProcessEvidence()
    host = PluginWorkerHost(tmp_path / "state", processes=process,
                            governance=cp.governance, authorization=cp.authorization,
                            store=cp.store)
    worker_id = "plugin-worker-health"
    now = time.time()
    with host._connect() as db:
        db.execute("INSERT INTO plugin_workers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (worker_id, "owner", plugin["plugin_id"], "session-exact",
                    "run-health", "op-health", "READY", 1,
                    '["run"]', '{"run":"safe"}', '[]', 0, now, now))
    host.exposure.reserve(plugin["plugin_id"], [{"name":"verified_tool"}], enabled=True)
    process.sessions = [{"session_id":"session-exact", "owner":"owner",
                         "run_id":"run-health", "operation_id":"op-health",
                         "running":True}]
    assert host.health(worker_id, "owner")["status"] == "HEALTHY"
    # PID need not be checked; a session replacement cannot steal authority.
    process.sessions = [{"session_id":"different", "owner":"owner",
                         "run_id":"run-health", "operation_id":"op-health",
                         "running":True}]
    assert host.health(worker_id, "owner")["status"] == "UNAVAILABLE"
    assert host.reconcile_worker(worker_id, "owner")["operator_must_reauthorize"]
    assert host.info(worker_id, "owner")["state"] == "FAILED"
    assert cp.governance.plugin_info(plugin["plugin_id"], "owner")["state"] == "DISABLED"
    assert host.exposure.publication([plugin["plugin_id"]]) == []
    assert host.health(worker_id, "owner")["can_auto_restart"] is False
    cp.durable.close()
