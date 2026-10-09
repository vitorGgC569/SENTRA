"""Low-risk UFO/RPA-inspired UIA workflow: registry-mediated, per-step grants.

Each read-only step is its own SENTRA OperationRequest with stable identity.
No shell, coordinate-based input, browser interaction, arbitrary UIA methods,
dynamic scripting, or implicit retry on uncertain effects.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sentra_runtime.contracts import OperationRequest
from sentra_runtime.executor import AuthorizationRequired, DuplicateOperation, InvalidOperation

from .discovery import MachineDeclaration
from .windows_uia import WindowsUIABinding


@dataclass(frozen=True)
class ReadStep:
    capability_id: str
    action: str
    automation_id: str = ""
    control_type: str = ""

    def __post_init__(self):
        if self.action not in {"read_window_title", "read_text"} or not self.capability_id:
            raise ValueError("workflow_only_read_actions")
        if self.action == "read_text" and (not self.automation_id or not self.control_type):
            raise ValueError("workflow_read_text_requires_selector")
        if self.action == "read_window_title" and (self.automation_id or self.control_type):
            raise ValueError("workflow_title_has_no_selector")


@dataclass(frozen=True)
class StepReceipt:
    operation_id: str
    state: str
    evidence_sha256: str | None
    error: str | None = None


@dataclass(frozen=True)
class WorkflowReceipt:
    workflow_id: str
    state: str
    steps: tuple[StepReceipt, ...]


class ReadOnlyUIAWorkflow:
    """No local result cache. Replays must reauthorize at ExecutorRegistry."""

    def __init__(self, declaration: MachineDeclaration, registry: Any):
        if declaration.machine.kind != "windows_uia":
            raise ValueError("only_windows_uia_machine")
        self.declaration = declaration
        self.registry = registry

    async def capabilities(self) -> tuple:
        advertised = await self.declaration.discover()
        result = []
        for cap in advertised:
            binding = self.declaration.adapter.bindings.get(cap.capability_id)
            if (isinstance(binding, WindowsUIABinding) and
                    any(a in binding.allowed_actions for a in ("read_window_title", "read_text"))):
                result.append(cap)
        return tuple(result)

    def _request(self, workflow_id: str, work_item_id: str,
                 index: int, step: ReadStep) -> OperationRequest:
        if not workflow_id or not work_item_id:
            raise ValueError("workflow_identity_required")
        binding = self.declaration.adapter.bindings.get(step.capability_id)
        if not isinstance(binding, WindowsUIABinding) or step.action not in binding.allowed_actions:
            raise ValueError("workflow_step_not_in_discovered_capability")
        args = {"pid": binding.pid, "hwnd": binding.hwnd, "action": step.action}
        if step.action == "read_text":
            if (step.automation_id not in binding.allowed_automation_ids or
                    step.control_type not in binding.allowed_control_types):
                raise ValueError("workflow_selector_not_in_allowlist")
            args.update(automation_id=step.automation_id,
                        control_type=step.control_type)
        op_id = f"{workflow_id}:read:{index}"
        return OperationRequest(
            operation_id=op_id,
            principal_id=self.declaration.machine.owner_principal_id,
            machine_id=self.declaration.machine.machine_id,
            capability_id=step.capability_id,
            work_item_id=work_item_id,
            idempotency_key=op_id,
            arguments=args,
        )

    async def run(self, *, workflow_id: str, work_item_id: str,
                  steps: tuple[ReadStep, ...]) -> WorkflowReceipt:
        if not steps or len(steps) > 16:
            raise ValueError("workflow_requires_1_to_16_steps")
        # Validate the entire DAG first: never begin a workflow with an
        # unallowlisted stage at the end.
        requests = tuple(
            self._request(workflow_id, work_item_id, index, step)
            for index, step in enumerate(steps)
        )
        history = []
        for req in requests:
            try:
                result = await self.registry.submit(req)
            except AuthorizationRequired:
                history.append(StepReceipt(req.operation_id, "DENIED", None,
                                           "live_policy_denied"))
                return WorkflowReceipt(workflow_id, "DENIED", tuple(history))
            except (DuplicateOperation, InvalidOperation):
                history.append(StepReceipt(req.operation_id, "FAILED", None,
                                           "operation_identity_conflict"))
                return WorkflowReceipt(workflow_id, "FAILED", tuple(history))
            evidence = dict(result.evidence or {})
            digest = hashlib.sha256(json.dumps(
                evidence, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")).hexdigest() if evidence else None
            history.append(StepReceipt(req.operation_id, result.state,
                                       digest, result.error))
            if result.state != "SUCCEEDED":
                return WorkflowReceipt(workflow_id, result.state, tuple(history))
        return WorkflowReceipt(workflow_id, "SUCCEEDED", tuple(history))
