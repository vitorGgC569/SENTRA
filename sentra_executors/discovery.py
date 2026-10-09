"""Declarative Machine/Capability discovery for opt-in SENTRA executors.

No OS enumeration, remote calls, app launch, credential access, or implicit
policy grant. A declaration is NOT attestation and NOT authorization: only
SENTRA ExecutorRegistry and its policy checker may submit operations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from sentra_runtime.contracts import Capability, Machine, OperationRequest

from .daytona import DaytonaBinding, DaytonaExecutor
from .windows_uia import WindowsUIABinding, WindowsUIAExecutor
from ._base import GuardedExecutor

if TYPE_CHECKING:
    from sentra_runtime.executor import ExecutorRegistry


@dataclass(frozen=True)
class MachineDeclaration:
    """Immutable advertised machine plus configured adapter; no side effects."""

    machine: Machine
    adapter: GuardedExecutor

    async def discover(self) -> tuple[Capability, ...]:
        """Return only statically declared capabilities, never host enumeration."""
        result = await self.adapter.discover(self.machine)
        if tuple(c.capability_id for c in result) != tuple(
            cap.capability_id for cap in self.machine.capabilities
        ):
            raise ValueError("advertised_capability_mismatch")
        return result

    def register(self, registry: "ExecutorRegistry") -> None:
        """Delegate policy enforcement to SENTRA's real registry."""
        registry.register(self.machine, self.adapter)


def _machine(machine_id: str, owner: str, kind: str, identifiers: tuple[str, ...]) -> Machine:
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise ValueError("missing_or_duplicate_capabilities")
    return Machine(
        machine_id=machine_id,
        kind=kind,
        owner_principal_id=owner,
        capabilities=tuple(
            Capability(capability_id=identifier,
                       description=f"Explicitly configured {kind} capability",
                       risk_level="high")
            for identifier in identifiers
        ),
    )


def declare_windows_machine(
    *,
    machine_id: str,
    owner_principal_id: str,
    bindings: tuple[WindowsUIABinding, ...],
    policy: Callable[[OperationRequest], Any] | None,
    backend: Any = None,
) -> MachineDeclaration:
    """Inventory strictly from caller-configured bindings, no process enumeration."""
    machine = _machine(machine_id, owner_principal_id, "windows_uia",
                       tuple(b.capability_id for b in bindings))
    executor = WindowsUIAExecutor(
        machine_id=machine_id, owner_principal_id=owner_principal_id,
        bindings=bindings, policy=policy, backend=backend)
    return MachineDeclaration(machine, executor)


def declare_daytona_machine(
    *,
    machine_id: str,
    owner_principal_id: str,
    bindings: tuple[DaytonaBinding, ...],
    policy: Callable[[OperationRequest], Any] | None,
    backend: Any = None,
) -> MachineDeclaration:
    """Inventory only existing pre-bound sandbox IDs, never contact Daytona."""
    machine = _machine(machine_id, owner_principal_id, "daytona",
                       tuple(b.capability_id for b in bindings))
    executor = DaytonaExecutor(
        machine_id=machine_id, owner_principal_id=owner_principal_id,
        bindings=bindings, policy=policy, backend=backend)
    return MachineDeclaration(machine, executor)


@dataclass(frozen=True)
class ReadOnlyLabPlan:
    """Pre-registered lab target, with no launch or discover side effect."""

    declaration: MachineDeclaration
    binding: WindowsUIABinding

    def request(self, *, operation_id: str, idempotency_key: str,
                work_item_id: str) -> OperationRequest:
        """Build typed request. Submission requires the actual policy registry."""
        return OperationRequest(
            operation_id=operation_id,
            principal_id=self.declaration.machine.owner_principal_id,
            machine_id=self.declaration.machine.machine_id,
            capability_id=self.binding.capability_id,
            work_item_id=work_item_id,
            idempotency_key=idempotency_key,
            arguments={"pid": self.binding.pid, "hwnd": self.binding.hwnd,
                       "action": "read_window_title"},
        )


def plan_read_only_tk_lab(
    *,
    machine_id: str,
    owner_principal_id: str,
    pid: int,
    hwnd: int,
    window_title: str,
    policy: Callable[[OperationRequest], Any],
    backend: Any = None,
) -> ReadOnlyLabPlan:
    """Explicit, allowlisted title-only test path, NOT a general window scanner.

    A title prefix alone does not prove process origin, ownership, or isolation.
    Caller MUST independently verify that the PID/HWND belongs to the fresh Tk
    child it created; PywinautoUIABackend validates again on execution.
    """
    if (not isinstance(window_title, str) or
            not window_title.startswith("SENTRA-UIA-LAB-") or
            len(window_title) > 80):
        raise ValueError("only_sentra_laboratory_window_permitted")
    if type(pid) is not int or type(hwnd) is not int or pid <= 0 or hwnd <= 0:
        raise ValueError("invalid_lab_target")
    if not callable(policy):
        raise ValueError("lab_requires_trusted_policy_callback")
    binding = WindowsUIABinding(
        capability_id="lab.read_window_title",
        pid=pid, hwnd=hwnd, window_title=window_title,
        allowed_automation_ids=("_unused",),
        allowed_control_types=("Text",),
        allowed_actions=("read_window_title",),
        timeout_seconds=8.0,
    )
    return ReadOnlyLabPlan(
        declaration=declare_windows_machine(
            machine_id=machine_id, owner_principal_id=owner_principal_id,
            bindings=(binding,), policy=policy, backend=backend),
        binding=binding,
    )
