"""Daytona capability, isolation and SDK contract tests (offline, no credentials)."""
import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from sentra_executors import DaytonaBinding, DaytonaExecutor, DaytonaSDKBackend
from sentra_runtime.contracts import PolicyDecision


@dataclass
class Request:
    operation_id: str = "daytona-1"
    idempotency_key: str = "dkey-1"
    work_item_id: str = "work-1"
    principal_id: str = "friend"
    machine_id: str = "daytona-machine"
    capability_id: str = "approved-check"
    arguments: dict = field(default_factory=lambda: {
        "action": "exec", "sandbox_id": "private-sandbox-1",
        "command": "python --version"})


def approved(_req):
    return PolicyDecision(True, "approved-command", constraints={
        "allowed_actions": ["exec"], "allowed_sandbox_ids": ["private-sandbox-1"]})


class FakeProcess:
    def __init__(self, exit_code=0):
        self.calls = []
        self.exit_code = exit_code
    def exec(self, command, timeout):
        self.calls.append((command, timeout))
        return SimpleNamespace(exit_code=self.exit_code, result="Python 3.12.10")


class Sandbox:
    def __init__(self):
        self.id = "private-sandbox-1"
        self.public = False
        self.network_block_all = True
        self.state = "started"
        self.process = FakeProcess()


class SDK:
    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.calls = []
    def get(self, identifier):
        self.calls.append(identifier)
        return self.sandbox


def executor(sdk, policy=approved):
    return DaytonaExecutor(
        machine_id="daytona-machine", owner_principal_id="friend",
        bindings=(DaytonaBinding(
            capability_id="approved-check", sandbox_id="private-sandbox-1",
            allowed_commands=("python --version",), timeout_seconds=6),),
        policy=policy, backend=DaytonaSDKBackend(client=sdk))


def run(coro):
    return asyncio.run(coro)


def test_existing_private_sandbox_exec_with_output_digest_only():
    sandbox = Sandbox()
    sdk = SDK(sandbox)
    r = run(executor(sdk).start(Request()))
    assert r.state == "SUCCEEDED"
    assert r.evidence["output_length"] == len("Python 3.12.10")
    assert "Python" not in str(r.evidence)
    assert sdk.calls == ["private-sandbox-1"]
    assert sandbox.process.calls == [("python --version", 6)]


@pytest.mark.parametrize("change", [
    ("id", "wrong-sandbox"), ("public", True),
    ("network_block_all", False), ("network_block_all", None),
    ("state", "stopped")
])
def test_insecure_or_wrong_sandbox_never_executes(change):
    sandbox = Sandbox()
    setattr(sandbox, *change)
    r = run(executor(SDK(sandbox)).start(Request()))
    assert r.state == "FAILED"
    assert sandbox.process.calls == []


@pytest.mark.parametrize("args", [
    {"action": "exec", "sandbox_id": "private-sandbox-2", "command": "python --version"},
    {"action": "exec", "sandbox_id": "private-sandbox-1", "command": "cat /etc/passwd"},
    {"action": "create", "sandbox_id": "private-sandbox-1", "command": "python --version"},
    {"action": "exec", "sandbox_id": "private-sandbox-1", "command": "python --version", "env": {"X": "secret"}},
])
def test_unapproved_command_or_lifecycle_is_denied(args):
    sandbox = Sandbox()
    r = run(executor(SDK(sandbox)).start(Request(arguments=args)))
    assert r.state == "FAILED"
    assert sandbox.process.calls == []


def test_denied_without_policy_and_no_get_call():
    sdk = SDK(Sandbox())
    assert run(executor(sdk, policy=None).start(Request())).state == "FAILED"
    assert sdk.calls == []


def test_nonzero_exit_code_fails_without_leaking_output():
    sandbox = Sandbox()
    sandbox.process = FakeProcess(exit_code=23)
    r = run(executor(SDK(sandbox)).start(Request()))
    assert r.state == "FAILED"
    assert r.error == "backend_error"
    assert "Python" not in str(r)


def test_same_key_conflict_does_not_execute_twice():
    sandbox = Sandbox()
    e = executor(SDK(sandbox))
    async def scenario():
        a = await e.start(Request())
        b = await e.start(Request(operation_id="daytona-2"))
        cleaned = await e.cleanup("daytona-1")
        return a, b, cleaned, await e.observe("daytona-1")
    a, b, cleaned, c = run(scenario())
    assert cleaned is None
    assert (a.state, b.state, c.state) == ("SUCCEEDED", "FAILED", "SUCCEEDED")
    assert len(sandbox.process.calls) == 1


def test_duplicate_binding_ids_rejected():
    a = DaytonaBinding("cap", "a", ("echo hello",))
    b = DaytonaBinding("cap", "b", ("echo hello",))
    with pytest.raises(ValueError, match="duplicate_capability"):
        DaytonaExecutor(machine_id="d", owner_principal_id="friend",
                        bindings=(a, b), policy=approved)
