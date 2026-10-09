"""Tests: authenticated, current-policy operation observation/control boundary."""
from __future__ import annotations
import asyncio

import pytest

from sentra_runtime import (
    AuthorizedOperationGateway, AuthorizationRequired, Capability, ExecutorRegistry,
    InvalidOperation, Machine, OperationRequest, OperationResult, PolicyDecision,
)


class LabExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []
    async def start(self, request):
        self.calls.append("start")
        return OperationResult(request.operation_id, "ACCEPTED")
    async def discover(self, machine):
        return machine.capabilities
    async def observe(self, operation_id):
        self.calls.append("observe")
        return OperationResult(operation_id, "RUNNING")
    async def cancel(self, operation_id):
        self.calls.append("cancel")
        return OperationResult(operation_id, "CANCELLED")
    async def reconcile(self, operation_id):
        self.calls.append("reconcile")
        return OperationResult(operation_id, "UNCERTAIN")
    async def cleanup(self, operation_id):
        self.calls.append("cleanup")


def setup():
    adapter = LabExecutor()
    registry = ExecutorRegistry(lambda _: PolicyDecision(True, "test launch"))
    registry.register(
        Machine("lab", "test", "owner",
                (Capability("observe.ui", "inspect readonly"),)), adapter
    )
    request = OperationRequest(
        "test-operation", "owner", "lab", "observe.ui", "work1", "key1", {}
    )
    asyncio.run(registry.submit(request))
    return registry, adapter


def test_no_implicit_policy_or_anonymous_access():
    registry, adapter = setup()
    gateway = AuthorizedOperationGateway(registry, None)
    with pytest.raises(AuthorizationRequired):
        asyncio.run(gateway.perform(
            principal_id="member", operation_id="test-operation", action="observe"))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(gateway.perform(
            principal_id="", operation_id="test-operation", action="cancel"))
    assert adapter.calls == ["start"]


def test_revocation_and_workitem_context():
    registry, adapter = setup()
    revoked = False
    seen = []
    def policy(check):
        nonlocal revoked
        seen.append(check)
        return PolicyDecision(not revoked, "fresh grant check")
    gateway = AuthorizedOperationGateway(registry, policy)
    assert asyncio.run(gateway.perform(
        principal_id="member", operation_id="test-operation", action="observe")).state == "RUNNING"
    assert seen[0].owner_principal_id == "owner"
    assert seen[0].machine_id == "lab"
    assert seen[0].work_item_id == "work1"
    revoked = True
    with pytest.raises(AuthorizationRequired):
        asyncio.run(gateway.perform(
            principal_id="member", operation_id="test-operation", action="observe"))
    with pytest.raises(AuthorizationRequired):
        asyncio.run(gateway.perform(
            principal_id="member", operation_id="test-operation", action="cancel"))
    assert adapter.calls == ["start", "observe"]


def test_other_principal_denied_and_authorized_cancel():
    registry, adapter = setup()
    gateway = AuthorizedOperationGateway(
        registry, lambda a: PolicyDecision(a.principal_id == "owner", "only owner")
    )
    with pytest.raises(AuthorizationRequired):
        asyncio.run(gateway.perform(principal_id="other", operation_id="test-operation",
                                    action="cleanup"))
    assert asyncio.run(gateway.perform(principal_id="owner", operation_id="test-operation",
                                       action="cancel")).state == "CANCELLED"
    asyncio.run(gateway.perform(principal_id="owner", operation_id="test-operation",
                                action="cleanup"))
    assert adapter.calls == ["start", "cancel", "cleanup"]


def test_broken_async_policy_fails_closed():
    registry, adapter = setup()
    async def slow_policy(_):
        await asyncio.sleep(.05)
        return PolicyDecision(True, "late")
    gateway = AuthorizedOperationGateway(registry, slow_policy, policy_timeout_s=.001)
    with pytest.raises(AuthorizationRequired):
        asyncio.run(gateway.perform(principal_id="owner", operation_id="test-operation",
                                    action="observe"))
    assert adapter.calls == ["start"]


def test_constraints_deny_without_partial_access_leak():
    registry, adapter = setup()
    gateway = AuthorizedOperationGateway(
        registry, lambda _: PolicyDecision(True, "redact fields",
                                           {"field_whitelist": ["state"]})
    )
    with pytest.raises(AuthorizationRequired):
        asyncio.run(gateway.perform(principal_id="owner", operation_id="test-operation",
                                    action="observe"))
    assert adapter.calls == ["start"]


def test_unknown_operation_and_unsupported_action():
    registry, adapter = setup()
    gateway = AuthorizedOperationGateway(registry, lambda _: PolicyDecision(True, "test"))
    with pytest.raises(InvalidOperation):
        asyncio.run(gateway.perform(principal_id="owner", operation_id="missing",
                                    action="observe"))
    with pytest.raises(InvalidOperation):
        asyncio.run(gateway.perform(principal_id="owner", operation_id="test-operation",
                                    action="spawn_shell"))
    assert adapter.calls == ["start"]


def test_invalid_policy_result_and_exception_deny():
    registry, adapter = setup()
    def broken(_):
        raise ValueError("provider failed")
    for checker in (lambda _: None, broken):
        gateway = AuthorizedOperationGateway(registry, checker)
        with pytest.raises(AuthorizationRequired):
            asyncio.run(gateway.perform(principal_id="owner", operation_id="test-operation",
                                        action="reconcile"))
    assert adapter.calls == ["start"]
