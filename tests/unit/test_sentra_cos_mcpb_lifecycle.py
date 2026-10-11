"""Real centrally governed MCPB staged update, denial and retained-audit uninstall."""
import json
import zipfile

import pytest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService


def bundle(ws, version, author="Publisher"):
    path = ws / f"{version.replace('.', '_')}.mcpb"
    manifest = {
        "manifest_version": "0.3", "name": "plugin-workflow", "version": version,
        "author": {"name": author}, "server": {
            "type": "python", "entry_point": "server/main.py",
            "mcp_config": {"command": "python",
                           "args": ["${__dirname}/server/main.py"]},
        },
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("server/main.py", "print('never execute during update')\n")
    return path


def test_operator_approved_update_uninstall_tombstone_central_governance(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    cat = cp.bundle_catalog
    older = cat.stage("owner", ws, bundle(ws, "1.0.0"))["package_sha256"]
    newer = cat.stage("owner", ws, bundle(ws, "1.1.0"))["package_sha256"]
    old = cat.register("owner", ws, older, cp.governance)
    with pytest.raises(PermissionError):
        cat.update("owner", ws, older, newer, cp.governance)
    assert cat.registration("owner", ws, older)["status"] == "REGISTERED"
    changed = cat.update("owner", ws, older, newer, cp.governance, approved=True)
    assert changed["status"] == "REGISTERED" and not changed["worker_started"]
    assert changed["grants_created"] is False
    assert cat.registration("owner", ws, older)["status"] == "DISABLED"
    assert cp.governance.plugin_info(old["plugin_id"], "owner")["state"] == "DISABLED"
    assert cat.registration("owner", ws, newer)["status"] == "REGISTERED"
    with pytest.raises(PermissionError):
        cat.launch_spec("owner", ws, older, cp.governance)
    with pytest.raises(PermissionError):
        cat.uninstall("owner", ws, newer, cp.governance)
    removed = cat.uninstall("owner", ws, newer, cp.governance, approved=True)
    assert removed["status"] == "REMOVED" and removed["archived_for_audit"]
    assert removed["disk_purge_completed"] is False
    assert cat.uninstall("owner", ws, newer, cp.governance, approved=True)["status"] == "REMOVED"
    assert cat.registration("owner", ws, newer)["status"] == "REMOVED"
    with pytest.raises(PermissionError):
        cat.register("owner", ws, newer, cp.governance)
    with pytest.raises(PermissionError):
        cat.disable("owner", ws, newer, cp.governance)
    assert (cat.target / ".archives" / (newer + ".mcpb")).is_file()
    assert not cp.governance.plugin_info(changed["plugin_id"], "owner")["verified_methods"]
    cp.durable.close()


def test_update_rejects_untrusted_publisher_without_disabling_old(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    cat = cp.bundle_catalog
    a = cat.stage("owner", ws, bundle(ws, "1.0.0"))["package_sha256"]
    b = cat.stage("owner", ws, bundle(ws, "2.0.0", author="Other"))["package_sha256"]
    cat.register("owner", ws, a, cp.governance)
    with pytest.raises(PermissionError, match="provenance"):
        cat.update("owner", ws, a, b, cp.governance, approved=True)
    assert cat.registration("owner", ws, a)["status"] == "REGISTERED"
    assert cat.registration("owner", ws, b) is None
    cp.durable.close()


def test_operator_explicit_rollback_fails_closed_without_worker(tmp_path):
    ws = tmp_path / "rollback-ws"
    ws.mkdir()
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    cat = cp.bundle_catalog
    old = cat.stage("owner", ws, bundle(ws, "1.0.0"))["package_sha256"]
    new = cat.stage("owner", ws, bundle(ws, "1.2.0"))["package_sha256"]
    cat.register("owner", ws, old, cp.governance)
    cat.update("owner", ws, old, new, cp.governance, approved=True)
    with pytest.raises(PermissionError):
        cat.rollback("owner", ws, new, old, cp.governance)
    record = cat.rollback("owner", ws, new, old, cp.governance, approved=True)
    assert record["status"] == "REGISTERED"
    assert record["worker_started"] is False and record["grants_created"] is False
    assert cat.registration("owner", ws, old)["status"] == "REGISTERED"
    assert cat.registration("owner", ws, new)["status"] == "DISABLED"
    assert cp.governance.plugin_info(cat.registration("owner", ws, old)["plugin_id"], "owner")["state"] == "REGISTERED"
    cat.uninstall("owner", ws, old, cp.governance, approved=True)
    with pytest.raises(PermissionError):
        cat.rollback("owner", ws, new, old, cp.governance, approved=True)
    cp.durable.close()
