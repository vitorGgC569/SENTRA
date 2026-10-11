"""Offline wheelhouse proof with real MCPB archive, SHA and central governance."""
import hashlib
import io
import json
import zipfile

import pytest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.mcpb_offline import preflight_offline_wheels, OfflineDependencyDenied


def fixture(tmp_path, *, bad_lock=False):
    ws = tmp_path / "ws"
    ws.mkdir()
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", "VALUE = 42\n")
        archive.writestr("demo-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n")
        archive.writestr("demo-1.0.0.dist-info/METADATA", "Name: demo\nVersion: 1.0.0\n")
        archive.writestr("demo-1.0.0.dist-info/RECORD", "")
    digest = hashlib.sha256(wheel.getvalue()).hexdigest()
    line = ("--index-url https://invalid.example/" if bad_lock else
            "demo==1.0.0 --hash=sha256:" + digest)
    manifest = {
        "manifest_version":"0.3", "name":"dependency-plugin", "version":"1.0.0",
        "author":{"name":"Fixture"}, "server":{"type":"python",
        "entry_point":"server/main.py",
        "mcp_config":{"command":"python","args":["${__dirname}/server/main.py"]}}}
    archive = ws / "tested.mcpb"
    with zipfile.ZipFile(archive, "w") as zipout:
        zipout.writestr("manifest.json", json.dumps(manifest))
        zipout.writestr("server/main.py", "# no execution\n")
        zipout.writestr("requirements.lock", line + "\n")
        zipout.writestr("wheels/demo-1.0.0-py3-none-any.whl", wheel.getvalue())
    sha = cp.bundle_catalog.stage("owner", ws, archive)["package_sha256"]
    cp.bundle_catalog.register("owner", ws, sha, cp.governance)
    return cp, ws, sha


def test_pinned_wheels_offline_plan_inert(tmp_path):
    cp, ws, sha = fixture(tmp_path)
    plan = preflight_offline_wheels(cp.bundle_catalog, "owner", ws, sha, cp.governance)
    assert len(plan["dependencies"]) == 1
    assert plan["dependencies"][0]["name"] == "demo"
    assert "--no-index" in plan["sandbox_command_candidate"]
    assert "--require-hashes" in plan["sandbox_command_candidate"]
    assert "--no-deps" in plan["sandbox_command_candidate"]
    assert not plan["installed"] and plan["requires_sandbox"]
    assert not any((ws / "demo").exists() for _ in range(1))
    cp.durable.close()


def test_lock_rejects_online_dependency_and_mutation(tmp_path):
    cp, ws, sha = fixture(tmp_path, bad_lock=True)
    with pytest.raises(OfflineDependencyDenied, match="pin"):
        preflight_offline_wheels(cp.bundle_catalog, "owner", ws, sha, cp.governance)
    cp.durable.close()


def test_offline_dependency_integrity_after_staging(tmp_path):
    cp, ws, sha = fixture(tmp_path)
    (cp.bundle_catalog.target / sha / "requirements.lock").write_text(
        "demo==1.0.0 --hash=sha256:" + "0" * 64 + "\n")
    with pytest.raises(ValueError, match="integrity|changed|mismatch"):
        preflight_offline_wheels(cp.bundle_catalog, "owner", ws, sha, cp.governance)
    cp.durable.close()
