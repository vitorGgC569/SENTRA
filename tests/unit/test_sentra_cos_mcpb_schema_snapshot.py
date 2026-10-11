"""Real central SQLite selective publication, tombstones and schema refresh epoch."""
import pytest
from sentra_mcp.services.control_store import SQLiteControlPlaneStore
from sentra_mcp.services.tool_exposure import ToolExposureRegistry


def test_schema_snapshot_versioned_selective_and_collision_tombstone(tmp_path):
    store = SQLiteControlPlaneStore(tmp_path / "state")
    catalog = ToolExposureRegistry(store)
    catalog.reserve_core_names(["sentra_core_tool"])
    v1 = [{"name": "example_a", "inputSchema": {"type": "object", "properties": {
        "q": {"type": "string"}}}}, {"name": "example_b", "description": "other"}]
    catalog.reserve("provider-a", v1, enabled=True)
    catalog.reserve("provider-b", [{"name": "different"}], enabled=True)
    a = catalog.publication_snapshot(["provider-a"], allowed_names=["example_a"])
    assert [x["name"] for x in a["tools"]] == ["example_a"]
    assert a["changed"] and a["grants_created"] is False
    assert a["external_account_verified"] is False
    assert not catalog.publication_snapshot(
        ["provider-a"], allowed_names=["example_a"], previous=a)["changed"]
    with pytest.raises(PermissionError):
        catalog.publication_snapshot(["provider-a"], allowed_names=["different"])
    with pytest.raises(PermissionError):
        catalog.reserve("provider-b", [{"name": "EXAMPLE_A"}], enabled=True)
    with pytest.raises(ValueError):
        catalog.reserve("sentra-core", [{"name": "fake_core"}], enabled=True)
    v1[0]["inputSchema"]["properties"]["q"]["type"] = "integer"
    catalog.reserve("provider-a", v1, enabled=True)
    b = catalog.publication_snapshot(["provider-a"], allowed_names=["example_a"],
                                     previous=a)
    assert b["changed"] and b["generation"] > a["generation"]
    assert b["schema_sha256"] != a["schema_sha256"]
    # Even an A->B->A update is seen, thanks to persistent epoch.
    v1[0]["inputSchema"]["properties"]["q"]["type"] = "string"
    catalog.reserve("provider-a", v1, enabled=True)
    c = catalog.publication_snapshot(["provider-a"], allowed_names=["example_a"],
                                     previous=a)
    assert c["changed"] and c["schema_sha256"] == a["schema_sha256"]
    catalog.disable("provider-a")
    hidden = ToolExposureRegistry(store).publication_snapshot(["provider-a"], previous=c)
    assert hidden["tools"] == [] and hidden["changed"]
    with pytest.raises(PermissionError):
        catalog.reserve("provider-new", [{"name": "example_a"}], enabled=True)
    with pytest.raises(PermissionError):
        catalog.reserve("provider-new", [{"name": "sentra_core_tool"}], enabled=True)
