from __future__ import annotations

from orchestrator.resources import ResourceRegistry


def test_resource_registry_merges_browser_and_remote_manifests():
    registry = ResourceRegistry()
    registry.ingest_manifest({
        "resource_type": "browser",
        "resources": [{
            "resource_id": "browser:builder",
            "state": "READY",
            "capacity": 1,
            "capabilities": {
                "browser": True,
                "chat": True,
                "persistent_profile": True,
                "cdp_attach": False,
            },
            "labels": {"role": "builder"},
        }],
    })
    registry.ingest_manifest({
        "resource_type": "remote_node",
        "resources": [{
            "resource_id": "node:pc-1",
            "state": "ONLINE",
            "capacity": 1,
            "capabilities": {
                "remote_node": True,
                "process_mode": "workspace",
                "os": "windows",
                "mcp_tool_count": 90,
            },
            "labels": {"agent_name": "PC-1"},
        }],
    })

    browser = registry.select(
        resource_type="browser",
        requirements={"browser": True, "persistent_profile": True},
    )
    assert [item["resource_id"] for item in browser] == ["browser:builder"]

    node = registry.select(
        resource_type="remote_node",
        requirements={"remote_node": True, "os": "windows"},
    )
    assert [item["resource_id"] for item in node] == ["node:pc-1"]


def test_resource_registry_is_descriptive_and_deterministic():
    registry = ResourceRegistry()
    registry.ingest_manifest({
        "resource_type": "remote_node",
        "resources": [
            {
                "resource_id": "node:b",
                "state": "ONLINE",
                "capacity": 1,
                "capabilities": {"python": True},
            },
            {
                "resource_id": "node:a",
                "state": "ONLINE",
                "capacity": 2,
                "capabilities": {"python": True},
            },
            {
                "resource_id": "node:offline",
                "state": "OFFLINE",
                "capacity": 99,
                "capabilities": {"python": True},
            },
        ],
    })
    selected = registry.select(
        resource_type="remote_node",
        requirements={"python": True},
        count=10,
    )
    assert [item["resource_id"] for item in selected] == ["node:a", "node:b"]
    assert registry.snapshot()[0]["resource_id"] == "node:a"


def test_resource_registry_rejects_duplicate_manifest_ids():
    registry = ResourceRegistry()
    try:
        registry.ingest_manifest({
            "resource_type": "browser",
            "resources": [
                {"resource_id": "same", "state": "READY"},
                {"resource_id": "same", "state": "READY"},
            ],
        })
    except ValueError as exc:
        assert "duplicate resource_id" in str(exc)
    else:
        raise AssertionError("duplicate resource ids must be rejected")
