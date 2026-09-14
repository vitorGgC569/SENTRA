"""Compute policy: start small, escalate only with cause (OMA §18-19).

Default posture: 5 agents (1 master + 1 executor + 3 validators) + deterministic
core. Extra validators join ONLY on disagreement (DISPUTED reports), low
confidence (gate confidence failure), or critical tasks — bounded by max_agents.
A task solvable by 5 agents must never spend 500 calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import TaskPriority, TaskStatus, ValidatorRole

_ROLE_BY_NAME = {
    "logic": ValidatorRole.LOGIC,
    "requirements": ValidatorRole.REQUIREMENTS,
    "adversarial": ValidatorRole.ADVERSARIAL,
    "edge_cases": ValidatorRole.EDGE_CASES,
    "edge": ValidatorRole.EDGE_CASES,
    "security": ValidatorRole.SECURITY,
    "performance": ValidatorRole.PERFORMANCE,
}

DEFAULT_INITIAL = [ValidatorRole.LOGIC, ValidatorRole.REQUIREMENTS, ValidatorRole.ADVERSARIAL]
DEFAULT_STANDBY = [ValidatorRole.EDGE_CASES, ValidatorRole.SECURITY, ValidatorRole.PERFORMANCE]


def _escalation_roles(spec: Any, field: str) -> List[ValidatorRole]:
    """Accepts {add_roles: [...]} explicit, or {add_agents: N} = first N of the
    fixed standby order. Anything else is a config error (fail closed)."""
    if spec is None:
        return list(DEFAULT_STANDBY)
    if not isinstance(spec, dict):
        raise ValueError(f"compute_policy.escalation.{field} must be a mapping")
    if "add_roles" in spec:
        roles = parse_roles(spec["add_roles"], DEFAULT_STANDBY)
        if "add_agents" in spec and spec["add_agents"] != len(roles):
            raise ValueError(f"compute_policy.escalation.{field}: add_agents "
                             f"contradicts add_roles length")
        return roles
    n = spec.get("add_agents", len(DEFAULT_STANDBY))
    if type(n) is not int or n < 0:
        raise ValueError(f"compute_policy.escalation.{field}.add_agents must be int >= 0")
    return list(DEFAULT_STANDBY[:n])


def parse_roles(names: Optional[List[str]], default: List[ValidatorRole]) -> List[ValidatorRole]:
    if names is None:
        return list(default)
    if not isinstance(names, list):
        raise ValueError("compute_policy roles must be a list")
    out: List[ValidatorRole] = []
    for name in names:
        key = str(name).strip().lower()
        if key not in _ROLE_BY_NAME:
            raise ValueError(f"unknown validator role '{name}'; choose among {sorted(_ROLE_BY_NAME)}")
        role = _ROLE_BY_NAME[key]
        if role not in out:
            out.append(role)
    if not out:
        raise ValueError("compute_policy needs at least one validator role")
    return out


@dataclass
class ComputePolicy:
    """How many validators run and when more join. Agents counted as
    validators + executor + master for the max_agents cap."""
    initial_roles: List[ValidatorRole] = field(default_factory=lambda: list(DEFAULT_INITIAL))
    disagreement_add: List[ValidatorRole] = field(default_factory=lambda: list(DEFAULT_STANDBY))
    low_confidence_add: List[ValidatorRole] = field(default_factory=lambda: list(DEFAULT_STANDBY))
    critical_add: List[ValidatorRole] = field(default_factory=lambda: list(DEFAULT_STANDBY))
    max_agents: int = 500

    def agent_count(self, validator_roles: List[ValidatorRole]) -> int:
        return len(validator_roles) + 2  # executor + master

    def expand(self, active: List[ValidatorRole], extra: List[ValidatorRole]) -> List[ValidatorRole]:
        """Add standby roles not already active, respecting max_agents. Pure."""
        merged = list(active)
        for role in extra:
            if role in merged:
                continue
            if self.agent_count(merged) >= self.max_agents:
                break
            merged.append(role)
        return merged

    def initial_for_task(self, task) -> List[ValidatorRole]:
        roles = list(self.initial_roles)
        try:
            critical = (str(getattr(task, "risk", "") or "").upper() in {"HIGH", "CRITICAL"}
                        or str(getattr(getattr(task, "priority", ""), "value", task.priority) or "").upper() == "CRITICAL")
        except Exception:
            critical = False
        if critical:
            roles = self.expand(roles, self.critical_add)
        return roles


def from_config(data: Optional[Dict[str, Any]]) -> Optional[ComputePolicy]:
    """None when unconfigured: engine keeps its historical default behavior."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("oma.compute_policy must be a mapping")
    max_agents = data.get("max_agents", 500)
    if type(max_agents) is not int or max_agents < 5 or max_agents > 5000:
        raise ValueError("compute_policy.max_agents must be an int 5..5000")
    initial_roles = parse_roles(data.get("initial_roles"), DEFAULT_INITIAL)
    if len(initial_roles) + 2 > max_agents:
        raise ValueError("compute_policy initial agents exceed max_agents")
    if "initial_agents" in data and data["initial_agents"] != len(initial_roles) + 2:
        raise ValueError("compute_policy.initial_agents must equal len(initial_roles)+2 "
                         "(validators + executor + master)")
    escalation = data.get("escalation", {}) or {}
    if not isinstance(escalation, dict):
        raise ValueError("compute_policy.escalation must be a mapping")
    return ComputePolicy(
        initial_roles=initial_roles,
        disagreement_add=_escalation_roles(escalation.get("disagreement"), "disagreement"),
        low_confidence_add=_escalation_roles(escalation.get("low_confidence"), "low_confidence"),
        critical_add=_escalation_roles(escalation.get("critical_task"), "critical_task"),
        max_agents=max_agents,
    )
