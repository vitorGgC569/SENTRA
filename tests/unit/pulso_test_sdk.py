"""SDK value objects for explicitly synthetic Temporal client unit tests."""
from dataclasses import dataclass
from enum import IntEnum
import sys
from types import ModuleType


def install_temporal_value_objects(monkeypatch):
    class WorkflowIDReusePolicy(IntEnum):
        REJECT_DUPLICATE = 3

    @dataclass
    class RetryPolicy:
        maximum_attempts: int

    common = ModuleType("temporalio.common")
    common.WorkflowIDReusePolicy = WorkflowIDReusePolicy
    common.RetryPolicy = RetryPolicy
    package = ModuleType("temporalio")
    package.common = common
    monkeypatch.setitem(sys.modules, "temporalio", package)
    monkeypatch.setitem(sys.modules, "temporalio.common", common)
