"""ACP Registry *metadata only*: versions and distributions are never executed.

The upstream registry is not a trust root. SENTRA must pin the exact catalog
schema and exact selected agent versions, then separately authorize executable
paths, argv and workspace using PolicyDecision at launch time.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping
from .registry_install import ACPDistribution, ACPInstallationPlan, build_installation_plan

AGENT_ID = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PREVIEW_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+-preview\.[0-9]+$")
MAX_INDEX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ACPRegistryEntry:
    agent_id: str
    name: str
    version: str
    distribution_kind: str
    distribution_name: str
    distributions: tuple[ACPDistribution, ...] = ()
    channel: str = "stable"

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], *, pinned_version: str, channel: str = "stable"
    ) -> "ACPRegistryEntry":
        if not isinstance(raw, Mapping) or channel not in {"stable", "preview"}:
            raise ValueError("invalid registry manifest")
        agent_id, name = raw.get("id"), raw.get("name")
        if not isinstance(agent_id, str) or not AGENT_ID.fullmatch(agent_id):
            raise ValueError("invalid agent ID")
        if not isinstance(name, str) or not name.strip() or len(name) > 256:
            raise ValueError("invalid agent name")
        if channel == "stable":
            version = raw.get("version")
            distribution = raw.get("distribution")
            valid_version = bool(isinstance(version, str) and VERSION.fullmatch(version))
        else:
            preview = raw.get("preview")
            if not isinstance(preview, Mapping):
                raise ValueError("preview channel unavailable")
            version = preview.get("version")
            distribution = preview.get("distribution")
            valid_version = bool(isinstance(version, str) and
                                 (VERSION.fullmatch(version) or PREVIEW_VERSION.fullmatch(version)))
        if not valid_version or version != pinned_version:
            raise ValueError("registry version pin mismatch")
        if not isinstance(distribution, Mapping) or not distribution or set(distribution) - {"npx", "uvx", "binary"}:
            raise ValueError("ambiguous registry distribution")
        descriptors = tuple(ACPDistribution.parse(k, v, version=version) for k, v in sorted(distribution.items()))
        if len(descriptors) > 1:
            return cls(agent_id, name, version, "multiple", "explicit-selection-required", descriptors, channel)
        kind = next(iter(distribution))
        if kind not in {"npx", "uvx", "binary"}:
            raise ValueError("untrusted distribution kind")
        spec = distribution[kind]
        if not isinstance(spec, Mapping):
            raise ValueError("invalid distribution spec")
        if kind == "binary":
            if not spec or not all(
                isinstance(target, str) and isinstance(target_info, Mapping)
                for target, target_info in spec.items()
            ):
                raise ValueError("invalid binary targets")
            # Do NOT fetch, trust remote hashes or execute registry-provided cmd.
            package = "binary:manual-approval-required"
        else:
            package = descriptors[0].package
        return cls(agent_id, name, version, kind, package, descriptors, channel)

    def installation_plan(self, *, system: str, architecture: str, kind: str | None = None,
                          available_dependencies: frozenset[str] = frozenset()) -> ACPInstallationPlan:
        return build_installation_plan(self, system=system, architecture=architecture, kind=kind,
                                       available_dependencies=available_dependencies)


@dataclass(frozen=True, slots=True)
class ACPVersionedCatalog:
    """Immutable and pinned subset of upstream ACP metadata.

    Snapshot hash is for auditing/dedupe, NOT a cryptographic publisher signature.
    Source/catalog changes require explicit reapproval by SENTRA.
    """

    schema_version: str
    entries: tuple[ACPRegistryEntry, ...]
    snapshot_sha256: str

    @classmethod
    def from_index(
        cls, raw: Mapping[str, Any], *,
        schema_version: str,
        pinned_versions: Mapping[str, str],
        channels: Mapping[str, str] | None = None,
    ) -> "ACPVersionedCatalog":
        if (not isinstance(raw, Mapping) or set(raw) != {"version", "agents"}
            or not isinstance(schema_version, str)
            or not VERSION.fullmatch(schema_version)
            or raw.get("version") != schema_version):
            raise ValueError("unknown ACP registry schema version")
        if (not isinstance(pinned_versions, Mapping) or not pinned_versions
            or not all(isinstance(name, str) and AGENT_ID.fullmatch(name)
                       and isinstance(version, str) for name, version in pinned_versions.items())):
            raise ValueError("catalog requires explicit agent version pins")
        channel_pins = dict(channels or {})
        if set(channel_pins) - set(pinned_versions):
            raise ValueError("unknown preview channel pin")
        try:
            serialized = json.dumps(raw, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValueError("invalid ACP registry JSON") from exc
        if len(serialized) > MAX_INDEX_BYTES:
            raise ValueError("ACP registry index exceeds size limit")
        agents = raw.get("agents")
        if not isinstance(agents, list) or len(agents) > 10000:
            raise ValueError("invalid ACP registry agent index")
        seen: set[str] = set()
        selected: dict[str, ACPRegistryEntry] = {}
        for row in agents:
            if not isinstance(row, Mapping):
                raise ValueError("invalid ACP agent entry")
            agent_id = row.get("id")
            if not isinstance(agent_id, str) or not AGENT_ID.fullmatch(agent_id):
                raise ValueError("invalid ACP agent ID in index")
            if agent_id in seen:
                raise ValueError("duplicate ACP agent ID")
            seen.add(agent_id)
            if agent_id in pinned_versions:
                selected[agent_id] = ACPRegistryEntry.from_mapping(
                    row, pinned_version=pinned_versions[agent_id],
                    channel=channel_pins.get(agent_id, "stable"),
                )
        if set(selected) != set(pinned_versions):
            raise ValueError("ACP pinned agent is missing")
        return cls(schema_version, tuple(selected[key] for key in sorted(selected)),
                   hashlib.sha256(serialized).hexdigest())

    def select(self, agent_id: str, *, version: str) -> ACPRegistryEntry:
        for entry in self.entries:
            if entry.agent_id == agent_id and entry.version == version:
                return entry
        raise ValueError("ACP agent/version is not pinned")

    def installation_plan(self, agent_id: str, *, version: str, system: str, architecture: str,
                          kind: str | None = None,
                          available_dependencies: frozenset[str] = frozenset()) -> ACPInstallationPlan:
        entry = self.select(agent_id, version=version)
        return build_installation_plan(entry, system=system, architecture=architecture, kind=kind,
            available_dependencies=available_dependencies, catalog_sha256=self.snapshot_sha256)
