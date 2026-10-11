"""Physical extracted MCPB removal only when globally unowned; audit archive retained."""
import zipfile
import pytest

from test_sentra_cos_mcpb_lifecycle import bundle
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.plugin_host import PluginWorkerHost


def _setup(tmp_path):
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    PluginWorkerHost(tmp_path / "state", processes=object(),
                     governance=cp.governance, authorization=cp.authorization,
                     store=cp.store)
    ws = tmp_path / "ws"
    ws.mkdir()
    package = bundle(ws, "1.0.0")
    sha = cp.bundle_catalog.stage("owner", ws, package)["package_sha256"]
    reg = cp.bundle_catalog.register("owner", ws, sha, cp.governance)
    return cp, ws, sha, reg


def test_uninstall_physically_purges_owned_unpack_directory_without_worker(tmp_path):
    cp, ws, sha, reg = _setup(tmp_path)
    cat = cp.bundle_catalog
    target = cat.target / sha
    archive = cat.target / ".archives" / (sha + ".mcpb")
    assert target.is_dir() and archive.is_file()
    with pytest.raises(PermissionError):
        cat.purge_uninstalled_extracted("owner", ws, sha, cp)
    with pytest.raises(PermissionError):
        cat.purge_uninstalled_extracted("owner", ws, sha, cp, approved=True)
    cat.uninstall("owner", ws, sha, cp.governance, approved=True)
    cleaned = cat.purge_uninstalled_extracted("owner", ws, sha, cp, approved=True)
    assert cleaned["extracted_removed"] is True
    assert cleaned["archive_retained"] is True
    assert not target.exists() and archive.is_file()
    assert cat.registration("owner", ws, sha)["status"] == "REMOVED"
    again = cat.purge_uninstalled_extracted("owner", ws, sha, cp, approved=True)
    assert again["extracted_removed"] and archive.exists()
    with pytest.raises((PermissionError, FileNotFoundError, ValueError)):
        cat.register("owner", ws, sha, cp.governance)
    cp.durable.close()


def test_purge_denies_shared_staged_workspace_and_unreconciled_docker(tmp_path):
    cp, ws, sha, reg = _setup(tmp_path)
    cat = cp.bundle_catalog
    other = tmp_path / "other"
    other.mkdir()
    source = bundle(other, "1.0.0")
    sha2 = cat.stage("second-owner", other, source)["package_sha256"]
    assert sha == sha2
    cat.uninstall("owner", ws, sha, cp.governance, approved=True)
    with pytest.raises(PermissionError, match="staged|workspace"):
        cat.purge_uninstalled_extracted("owner", ws, sha, cp, approved=True)
    cat.register("second-owner", other, sha, cp.governance)
    cat.uninstall("second-owner", other, sha, cp.governance, approved=True)
    with cp.store.connect("plugin_bundle") as db:
        db.execute("""CREATE TABLE IF NOT EXISTS mcpb_docker_ownership(
            operation_id TEXT PRIMARY KEY,owner TEXT,workspace TEXT,run_id TEXT,
            work_item_id TEXT,container_name TEXT,image_id TEXT,claim TEXT,
            container_id TEXT,state TEXT,created_at REAL,updated_at REAL)""")
        db.execute("INSERT INTO mcpb_docker_ownership VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("op-owned", "owner", str(ws.resolve()), "run", "wi",
                    "sentra-test", "sha256:"+"a"*64, "claim", None,
                    "PREPARED", 0, 0))
    with pytest.raises(PermissionError, match="Docker"):
        cat.purge_uninstalled_extracted("owner", ws, sha, cp, approved=True)
    assert (cat.target / sha).exists()
    with cp.store.connect("plugin_bundle") as db:
        db.execute("UPDATE mcpb_docker_ownership SET state='CLEANED' WHERE operation_id='op-owned'")
    assert cat.purge_uninstalled_extracted("owner", ws, sha, cp, approved=True)["extracted_removed"]
    cp.durable.close()
