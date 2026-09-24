from __future__ import annotations

from sentra_remote.agent import build_resource_manifest
from sentra_remote.agent_config import AgentConfig


def test_remote_agent_resource_manifest_is_scheduler_friendly():
    config = AgentConfig(
        relay_url="http://127.0.0.1:8766",
        device_id="device-1",
        device_token="secret",
        name="worker-a",
        allowed_roots=["C:/repo"],
        audit_log="C:/tmp/audit.jsonl",
        process_mode="workspace",
    )
    manifest = build_resource_manifest(config, {"tool_count": 90})

    assert manifest["schema_version"] == 1
    assert manifest["resource_type"] == "remote_node"
    assert manifest["max_concurrency"] == 1
    assert len(manifest["resources"]) == 1

    node = manifest["resources"][0]
    assert node["resource_id"] == "node:device-1"
    assert node["node_id"] == "device-1"
    assert node["capacity"] == 1
    assert node["state"] == "ONLINE"
    assert node["capabilities"]["remote_node"] is True
    assert node["capabilities"]["process_mode"] == "workspace"
    assert node["capabilities"]["mcp_tool_count"] == 90
    assert node["labels"]["agent_name"] == "worker-a"
