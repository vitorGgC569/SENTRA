"""Capability-scoped Machine Runtime executors (opt-in backends)."""

from ._base import LocalOperationResult
from .windows_uia import WindowsUIABinding, WindowsUIAExecutor, PywinautoUIABackend
from .daytona import DaytonaBinding, DaytonaExecutor, DaytonaSDKBackend
from .discovery import (
    MachineDeclaration, ReadOnlyLabPlan, declare_windows_machine,
    declare_daytona_machine, plan_read_only_tk_lab,
)
from .lab_discovery import LabWindow, discover_owned_tk_lab
from .daytona_lifecycle import (
    SandboxView, SandboxCreateSpec, DaytonaSandboxLifecycle,
)
from .uia_workflow import (
    ReadStep, StepReceipt, WorkflowReceipt, ReadOnlyUIAWorkflow,
)
from .browser_lab import (
    BrowserReadBinding, BrowserLabExecutor, PlaywrightReadOnlyBackend,
    parse_browser_read_query, declare_browser_lab_machine,
)
from .remote_readonly import (
    RemoteReadBinding, RemoteReadOnlyExecutor,
    AuthenticatedLoopbackTransport, declare_remote_readonly_machine,
)
from .windows_identity import (
    ProcessIdentity, FenceLease, IdentityUIABinding, WindowsIdentityProbe,
    IdentityGuardedUIAExecutor, declare_hardened_windows_machine,
)
from .gvisor_runsc import (
    RunscLease, RunscBinding, RunscExecutor, PinnedRunscRunner,
    validate_oci_bundle, declare_runsc_machine,
)
from .winhcs_boundary import (
    HCSBinding, HCSBoundaryExecutor, declare_winhcs_machine,
)
from .tk_benchmark import (
    BASELINE_VERSION, BenchCase, TkBaseline, BenchmarkStep, BenchmarkReport,
    OwnTkBenchmark,
)
from .central_integration import CentralExecutorFactory, CentralRegisteredMachine

__all__ = [
    "LocalOperationResult", "WindowsUIABinding", "WindowsUIAExecutor",
    "PywinautoUIABackend", "DaytonaBinding", "DaytonaExecutor", "DaytonaSDKBackend",
    "MachineDeclaration", "ReadOnlyLabPlan", "declare_windows_machine",
    "declare_daytona_machine", "plan_read_only_tk_lab",
    "LabWindow", "discover_owned_tk_lab",
    "SandboxView", "SandboxCreateSpec", "DaytonaSandboxLifecycle",
    "ReadStep", "StepReceipt", "WorkflowReceipt", "ReadOnlyUIAWorkflow",
    "BrowserReadBinding", "BrowserLabExecutor", "PlaywrightReadOnlyBackend",
    "parse_browser_read_query", "declare_browser_lab_machine",
    "RemoteReadBinding", "RemoteReadOnlyExecutor", "AuthenticatedLoopbackTransport",
    "declare_remote_readonly_machine", "ProcessIdentity", "FenceLease",
    "IdentityUIABinding", "WindowsIdentityProbe", "IdentityGuardedUIAExecutor",
    "declare_hardened_windows_machine",
    "RunscLease", "RunscBinding", "RunscExecutor", "PinnedRunscRunner",
    "validate_oci_bundle", "declare_runsc_machine",
    "HCSBinding", "HCSBoundaryExecutor", "declare_winhcs_machine",
    "BASELINE_VERSION", "BenchCase", "TkBaseline", "BenchmarkStep",
    "BenchmarkReport", "OwnTkBenchmark",
    "CentralExecutorFactory", "CentralRegisteredMachine",
]
