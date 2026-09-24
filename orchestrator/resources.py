"""Deterministic resource catalog for SENTRA scheduling.

This registry is descriptive/admission-oriented only. It does not own leases,
fencing or task/run transitions; those remain Control Plane/Durable Core duties.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import importlib.util
import os
import platform
import shutil
import socket
from pathlib import Path
from typing import Any, Iterable


_READY_STATES = {"READY", "ONLINE", "IDLE"}


@dataclass
class ResourceDescriptor:
    resource_id: str
    resource_type: str
    state: str
    capacity: int = 1
    capabilities: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, resource_type: str, data: dict[str, Any]) -> "ResourceDescriptor":
        resource_id = str(data.get("resource_id") or "").strip()
        if not resource_id:
            raise ValueError("resource_id is required")
        state = str(data.get("state") or "OFFLINE").strip().upper()
        capacity = int(data.get("capacity") or 1)
        if capacity < 1:
            raise ValueError("resource capacity must be positive")
        capabilities = data.get("capabilities") or {}
        labels = data.get("labels") or {}
        if not isinstance(capabilities, dict) or not isinstance(labels, dict):
            raise ValueError("resource capabilities/labels must be objects")
        known = {"resource_id", "state", "capacity", "capabilities", "labels"}
        return cls(
            resource_id=resource_id,
            resource_type=str(resource_type or "").strip() or "generic",
            state=state,
            capacity=capacity,
            capabilities=dict(capabilities),
            labels=dict(labels),
            metadata={k: deepcopy(v) for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "state": self.state,
            "capacity": self.capacity,
            "capabilities": deepcopy(self.capabilities),
            "labels": deepcopy(self.labels),
            **deepcopy(self.metadata),
        }


class ResourceRegistry:
    """Merge scheduler-facing manifests and select compatible resources."""

    def __init__(self) -> None:
        self._resources: dict[str, ResourceDescriptor] = {}

    def ingest_manifest(self, manifest: dict[str, Any]) -> list[str]:
        if not isinstance(manifest, dict):
            raise TypeError("resource manifest must be an object")
        resource_type = str(manifest.get("resource_type") or "generic").strip()
        resources = manifest.get("resources") or []
        if not isinstance(resources, list):
            raise ValueError("resource manifest resources must be a list")

        seen: set[str] = set()
        for raw in resources:
            if not isinstance(raw, dict):
                raise ValueError("resource entry must be an object")
            item = ResourceDescriptor.from_dict(resource_type, raw)
            if item.resource_id in seen:
                raise ValueError("resource manifest contains duplicate resource_id")
            seen.add(item.resource_id)
            self._resources[item.resource_id] = item
        return sorted(seen)

    def remove(self, resource_id: str) -> bool:
        return self._resources.pop(str(resource_id), None) is not None

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            self._resources[key].to_dict()
            for key in sorted(self._resources)
        ]

    @staticmethod
    def _matches_value(actual: Any, expected: Any) -> bool:
        if isinstance(expected, list):
            if isinstance(actual, (list, tuple, set)):
                return all(item in actual for item in expected)
            return False
        if isinstance(expected, bool):
            return bool(actual) is expected
        return actual == expected

    def select(
        self,
        *,
        resource_type: str | None = None,
        requirements: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
        count: int = 1,
    ) -> list[dict[str, Any]]:
        if not 1 <= int(count) <= 1000:
            raise ValueError("count must be between 1 and 1000")
        requirements = dict(requirements or {})
        labels = dict(labels or {})
        candidates: list[ResourceDescriptor] = []
        for item in self._resources.values():
            if item.state not in _READY_STATES:
                continue
            if resource_type and item.resource_type != resource_type:
                continue
            if any(
                not self._matches_value(item.capabilities.get(key), expected)
                for key, expected in requirements.items()
            ):
                continue
            if any(
                not self._matches_value(item.labels.get(key), expected)
                for key, expected in labels.items()
            ):
                continue
            candidates.append(item)

        # Deterministic ordering. Capacity is a tie-break preference, not authority.
        candidates.sort(key=lambda item: (-item.capacity, item.resource_id))
        return [item.to_dict() for item in candidates[: int(count)]]



def _norm_capability(value: str) -> str:
    return str(value or "").strip().lower()


@dataclass(frozen=True)
class NodeCapabilityManifest:
    """Scheduler-facing capability projection for one execution node."""

    node_id: str
    os: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    workspaces: tuple[str, ...] = ()
    cpu_count: int = 0
    max_concurrency: int = 1
    health: str = "ONLINE"
    metadata: dict[str, Any] = field(default_factory=dict)

    def missing(self, required: Iterable[str]) -> list[str]:
        required_set = {
            _norm_capability(item)
            for item in required
            if _norm_capability(item)
        }
        return sorted(required_set - set(self.capabilities))

    def supports(self, required: Iterable[str]) -> bool:
        return not self.missing(required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "os": self.os,
            "capabilities": sorted(self.capabilities),
            "workspaces": list(self.workspaces),
            "cpu_count": self.cpu_count,
            "max_concurrency": self.max_concurrency,
            "health": self.health,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeCapabilityManifest":
        return cls(
            node_id=str(data.get("node_id") or "node"),
            os=_norm_capability(data.get("os") or platform.system()),
            capabilities=frozenset(
                _norm_capability(item)
                for item in data.get("capabilities", [])
                if _norm_capability(item)
            ),
            workspaces=tuple(
                str(item) for item in data.get("workspaces", [])
                if str(item).strip()
            ),
            cpu_count=max(0, int(data.get("cpu_count") or 0)),
            max_concurrency=max(1, int(data.get("max_concurrency") or 1)),
            health=str(data.get("health") or "ONLINE").upper(),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def probe_local(
        cls,
        workspace: str | Path,
        *,
        max_concurrency: int = 1,
        extra: Iterable[str] = (),
    ) -> "NodeCapabilityManifest":
        system = _norm_capability(platform.system())
        capabilities = {"local", "filesystem", "workspace", "python", system}
        if importlib.util.find_spec("pytest") is not None:
            capabilities.add("pytest")
        for capability, command in {
            "git": "git",
            "node": "node",
            "npm": "npm",
            "powershell": "powershell",
            "docker": "docker",
        }.items():
            if shutil.which(command):
                capabilities.add(capability)
        capabilities.update(
            _norm_capability(item) for item in extra if _norm_capability(item)
        )
        return cls(
            node_id=f"local:{socket.gethostname()}",
            os=system,
            capabilities=frozenset(capabilities),
            workspaces=(str(Path(workspace).resolve()),),
            cpu_count=os.cpu_count() or 0,
            max_concurrency=max(1, int(max_concurrency)),
            health="ONLINE",
            metadata={"source": "local-probe"},
        )

    def as_resource_descriptor(self) -> ResourceDescriptor:
        return ResourceDescriptor(
            resource_id=self.node_id,
            resource_type="node",
            state=self.health,
            capacity=self.max_concurrency,
            capabilities={name: True for name in sorted(self.capabilities)},
            labels={"os": self.os},
            metadata={
                "workspaces": list(self.workspaces),
                "cpu_count": self.cpu_count,
                **deepcopy(self.metadata),
            },
        )


class ResourceCapabilityRegistry:
    """Node-centric scheduler view backed by deterministic capability manifests."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeCapabilityManifest] = {}

    def upsert(self, manifest: NodeCapabilityManifest) -> None:
        if not isinstance(manifest, NodeCapabilityManifest):
            raise TypeError("manifest must be a NodeCapabilityManifest")
        self._nodes[manifest.node_id] = manifest

    def remove(self, node_id: str) -> None:
        self._nodes.pop(str(node_id), None)

    def get(self, node_id: str) -> NodeCapabilityManifest | None:
        return self._nodes.get(str(node_id))

    def compatible(self, required: Iterable[str]) -> list[NodeCapabilityManifest]:
        return sorted(
            (
                node for node in self._nodes.values()
                if node.health in _READY_STATES and node.supports(required)
            ),
            key=lambda node: (-node.max_concurrency, node.node_id),
        )

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            self._nodes[key].to_dict()
            for key in sorted(self._nodes)
        ]

    def to_resource_registry(self) -> ResourceRegistry:
        registry = ResourceRegistry()
        registry.ingest_manifest({
            "resource_type": "node",
            "resources": [
                node.as_resource_descriptor().to_dict()
                for node in self._nodes.values()
            ],
        })
        return registry
