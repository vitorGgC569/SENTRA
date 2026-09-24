"""Authorized projection of SENTRA Remote Agents into scheduler resources."""
from __future__ import annotations

import re
from typing import Any

from orchestrator.resources import NodeCapabilityManifest, ResourceCapabilityRegistry
from sentra_remote.gateway import RemoteGatewayService


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _platform_capabilities(value: Any) -> set[str]:
    text = _norm(value)
    out: set[str] = set()
    if not text:
        return out
    out.add("platform:" + text[:160])
    if "windows" in text:
        out.add("windows")
    if "linux" in text:
        out.add("linux")
    if "darwin" in text or "macos" in text or "mac os" in text:
        out.update({"darwin", "macos"})
    return out


def _flatten_truthy_capabilities(value: Any, prefix: str = "") -> set[str]:
    """Flatten advertised booleans/lists without inventing authority semantics."""
    found: set[str] = set()
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = _norm(raw_key)
            if not key:
                continue
            path = f"{prefix}.{key}" if prefix else key
            if child is True:
                found.add(path)
                found.add(key)
            elif isinstance(child, dict):
                found.update(_flatten_truthy_capabilities(child, path))
            elif isinstance(child, (list, tuple, set)):
                for item in child:
                    item_text = _norm(item)
                    if item_text:
                        found.add(f"{path}:{item_text}")
                        if key in {"surfaces", "capabilities"}:
                            found.add(item_text)
            elif isinstance(child, str) and child.strip():
                found.add(f"{path}:{_norm(child)}")
    return found


class RemoteResourceProjection:
    """Read-only scheduler projection; caller must supply an authorized principal."""

    def __init__(self, gateway: RemoteGatewayService) -> None:
        self.gateway = gateway

    @staticmethod
    def _manifest(device: dict[str, Any]) -> NodeCapabilityManifest:
        device_id = str(device.get("device_id") or "").strip()
        if not device_id:
            raise ValueError("remote device is missing device_id")
        status = str(device.get("status") or "OFFLINE").upper()
        compatibility = dict(device.get("compatibility") or {})
        compatible = compatibility.get("compatible") is True
        if status == "REVOKED":
            health = "REVOKED"
        elif status != "ONLINE":
            health = "OFFLINE"
        elif not compatible:
            health = "STALE"
        else:
            health = "ONLINE"

        raw_caps = dict(device.get("capabilities") or {})
        sentra = raw_caps.get("sentra")
        sentra = sentra if isinstance(sentra, dict) else {}
        advertised = sentra.get("capabilities")
        advertised = advertised if isinstance(advertised, dict) else {}
        resource_manifest = sentra.get("resources")
        resource_manifest = resource_manifest if isinstance(resource_manifest, dict) else {}
        resource_entries = resource_manifest.get("resources")
        resource_entries = resource_entries if isinstance(resource_entries, list) else []
        resource_entry = next(
            (
                item for item in resource_entries
                if isinstance(item, dict)
                and (
                    str(item.get("node_id") or "") == device_id
                    or str(item.get("resource_id") or "") in {
                        f"node:{device_id}",
                        f"remote:{device_id}",
                    }
                )
            ),
            {},
        )

        capabilities = {"remote"}
        capabilities.update(_platform_capabilities(device.get("platform")))
        capabilities.update(_platform_capabilities(raw_caps.get("platform")))
        capabilities.update(_flatten_truthy_capabilities(advertised))
        capabilities.update(_flatten_truthy_capabilities(raw_caps.get("server_capabilities") or {}))
        capabilities.update(
            _flatten_truthy_capabilities(
                resource_entry.get("capabilities") if isinstance(resource_entry, dict) else {}
            )
        )
        if raw_caps.get("python"):
            capabilities.add("python")
            capabilities.add("python:" + _norm(raw_caps.get("python")))
        if raw_caps.get("hostname"):
            capabilities.add("host:" + _norm(raw_caps.get("hostname"))[:128])
        for tool in device.get("allowed_tools") or []:
            name = _norm(tool)
            if name:
                capabilities.add("tool:" + name)

        max_concurrency = 1
        for source in (resource_manifest, advertised, raw_caps):
            candidate = source.get("max_concurrency") if isinstance(source, dict) else None
            if type(candidate) is int and 1 <= candidate <= 1024:
                max_concurrency = candidate
                break
        if max_concurrency == 1 and isinstance(resource_entry, dict):
            candidate = resource_entry.get("capacity")
            if type(candidate) is int and 1 <= candidate <= 1024:
                max_concurrency = candidate

        server = sentra.get("server")
        server = server if isinstance(server, dict) else {}
        contract = sentra.get("contract")
        contract = contract if isinstance(contract, dict) else {}
        reasons = compatibility.get("reasons")
        reasons = reasons if isinstance(reasons, list) else []

        return NodeCapabilityManifest(
            node_id="remote:" + device_id,
            os=_norm(device.get("platform") or raw_caps.get("platform") or "unknown"),
            capabilities=frozenset(capabilities),
            workspaces=tuple(
                str(item) for item in raw_caps.get("workspaces", [])
                if isinstance(item, str) and item.strip()
            ),
            cpu_count=max(0, int(raw_caps.get("cpu_count") or 0)),
            max_concurrency=max_concurrency,
            health=health,
            metadata={
                "source": "sentra-remote-heartbeat",
                "device_id": device_id,
                "name": str(device.get("name") or ""),
                "last_seen": device.get("last_seen"),
                "compatible": compatible,
                "compatibility_reasons": reasons[:20],
                "build_id": server.get("build_id"),
                "source_hash": server.get("source_hash"),
                "schema_hash": contract.get("schema_hash"),
                "protocol_version": server.get("protocol_version"),
                "allowed_tools": list(device.get("allowed_tools") or []),
                "resource_id": resource_entry.get("resource_id") if isinstance(resource_entry, dict) else None,
                "resource_schema_version": resource_manifest.get("schema_version"),
            },
        )

    def inventory(self, principal: str) -> dict[str, Any]:
        principal = str(principal or "").strip()
        if not principal:
            raise PermissionError("authorized remote principal is required")
        raw = self.gateway.list_devices(principal)
        devices = list(raw.get("devices") or raw.get("items") or [])
        manifests = [self._manifest(dict(item)) for item in devices]
        registry = ResourceCapabilityRegistry()
        for manifest in manifests:
            registry.upsert(manifest)
        eligible = [
            item.to_dict() for item in manifests if item.health == "ONLINE"
        ]
        return {
            "principal": principal,
            "nodes": [item.to_dict() for item in manifests],
            "eligible": eligible,
            "eligible_count": len(eligible),
            "total_count": len(manifests),
        }

    def registry(self, principal: str) -> ResourceCapabilityRegistry:
        inventory = self.inventory(principal)
        registry = ResourceCapabilityRegistry()
        for item in inventory["nodes"]:
            registry.upsert(NodeCapabilityManifest.from_dict(item))
        return registry
