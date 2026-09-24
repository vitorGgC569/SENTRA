from __future__ import annotations

import pytest

from sentra_mcp.services.resource_projection import RemoteResourceProjection


class FakeGateway:
    def __init__(self, devices):
        self.devices = devices
        self.principals = []

    def list_devices(self, principal):
        self.principals.append(principal)
        return {"devices": list(self.devices)}


def _device(device_id="dev-1", *, status="ONLINE", compatible=True):
    reasons = [] if compatible else [{"code": "REMOTE_AGENT_STALE", "message": "stale"}]
    return {
        "device_id": device_id,
        "name": "Worker",
        "platform": "Windows-11",
        "status": status,
        "last_seen": 123.0,
        "allowed_tools": ["sentra_repo_read", "sentra_repo_test"],
        "compatibility": {"compatible": compatible, "reasons": reasons},
        "capabilities": {
            "python": "3.12.10",
            "hostname": "WORKER-01",
            "cpu_count": 12,
            "sentra": {
                "server": {
                    "build_id": "build-1",
                    "source_hash": "a" * 64,
                    "protocol_version": "2026-07-28",
                },
                "contract": {"schema_hash": "b" * 64},
                "capabilities": {
                    "durable_run": True,
                    "process_tree": True,
                    "surfaces": ["core", "browser"],
                    "max_concurrency": 4,
                },
            },
        },
    }


def test_remote_projection_requires_explicit_authorized_principal() -> None:
    projection = RemoteResourceProjection(FakeGateway([]))
    with pytest.raises(PermissionError):
        projection.inventory("")


def test_remote_projection_preserves_principal_and_flattens_capabilities() -> None:
    gateway = FakeGateway([_device()])
    projection = RemoteResourceProjection(gateway)
    result = projection.inventory("local-operator")

    assert gateway.principals == ["local-operator"]
    assert result["eligible_count"] == 1
    node = result["eligible"][0]
    assert node["node_id"] == "remote:dev-1"
    assert node["health"] == "ONLINE"
    assert node["max_concurrency"] == 4
    caps = set(node["capabilities"])
    assert {"remote", "windows", "python", "durable_run", "process_tree", "core", "browser"} <= caps
    assert "tool:sentra_repo_read" in caps
    assert "tool:sentra_repo_test" in caps
    assert node["metadata"]["build_id"] == "build-1"
    assert node["metadata"]["schema_hash"] == "b" * 64


def test_stale_offline_and_revoked_nodes_are_diagnostic_only() -> None:
    devices = [
        _device("good", status="ONLINE", compatible=True),
        _device("stale", status="ONLINE", compatible=False),
        _device("offline", status="OFFLINE", compatible=True),
        _device("revoked", status="REVOKED", compatible=True),
    ]
    projection = RemoteResourceProjection(FakeGateway(devices))
    result = projection.inventory("principal-A")

    health = {item["node_id"]: item["health"] for item in result["nodes"]}
    assert health == {
        "remote:good": "ONLINE",
        "remote:stale": "STALE",
        "remote:offline": "OFFLINE",
        "remote:revoked": "REVOKED",
    }
    assert [item["node_id"] for item in result["eligible"]] == ["remote:good"]

    registry = projection.registry("principal-A")
    assert [node.node_id for node in registry.compatible(["python", "browser"])] == ["remote:good"]
    assert registry.compatible(["definitely-missing"]) == []


def test_projection_does_not_treat_allowed_tools_as_generic_capabilities() -> None:
    projection = RemoteResourceProjection(FakeGateway([_device()]))
    node = projection.inventory("principal")["nodes"][0]
    caps = set(node["capabilities"])
    assert "tool:sentra_repo_read" in caps
    assert "sentra_repo_read" not in caps



def test_projection_consumes_standard_resource_manifest_when_present() -> None:
    device = _device()
    device["capabilities"]["sentra"]["resources"] = {
        "schema_version": 1,
        "resource_type": "remote_node",
        "max_concurrency": 3,
        "resources": [
            {
                "resource_id": "node:dev-1",
                "node_id": "dev-1",
                "state": "ONLINE",
                "capacity": 3,
                "capabilities": {
                    "remote_node": True,
                    "gpu": True,
                    "browser_engine": "chromium",
                },
                "labels": {"agent_name": "Worker"},
            }
        ],
    }
    projection = RemoteResourceProjection(FakeGateway([device]))
    node = projection.inventory("principal")["eligible"][0]

    assert node["max_concurrency"] == 3
    assert "gpu" in set(node["capabilities"])
    assert "browser_engine:chromium" in set(node["capabilities"])
    assert node["metadata"]["resource_id"] == "node:dev-1"
    assert node["metadata"]["resource_schema_version"] == 1
