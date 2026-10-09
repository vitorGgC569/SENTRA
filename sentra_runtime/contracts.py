"""Immutable types used across SENTRA machine, agent and tool executors."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Capability:
    capability_id: str
    description: str
    risk_level: str = "low"

    def __post_init__(self):
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("capability_id required")
        if self.risk_level not in {"low", "medium", "high", "critical"}:
            raise ValueError("invalid risk level")


@dataclass(frozen=True, slots=True)
class Machine:
    machine_id: str
    kind: str
    owner_principal_id: str
    capabilities: tuple[Capability, ...] = ()

    def __post_init__(self):
        if not self.machine_id or not self.kind or not self.owner_principal_id:
            raise ValueError("machine identity required")
        ids = [cap.capability_id for cap in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate machine capabilities")


@dataclass(frozen=True, slots=True)
class OperationRequest:
    operation_id: str
    principal_id: str
    machine_id: str
    capability_id: str
    work_item_id: str
    idempotency_key: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("operation_id", "principal_id", "machine_id", "capability_id",
                     "work_item_id", "idempotency_key"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} required")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    constraints: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.reason:
            raise ValueError("policy reason required")


@dataclass(frozen=True, slots=True)
class OperationResult:
    operation_id: str
    state: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self):
        if not self.operation_id or self.state not in {
            "ACCEPTED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"
        }:
            raise ValueError("invalid operation result")
