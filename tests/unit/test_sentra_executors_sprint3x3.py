"""Sprint 3x3: THREE independent fixture E2Es, real SENTRA policy registry.

No user application, Daytona service, shell, unknown binary or benchmark VM.
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
from types import SimpleNamespace

import pytest

from sentra_runtime.contracts import PolicyDecision, OperationRequest
from sentra_runtime.executor import ExecutorRegistry
from sentra_executors import (
    DaytonaBinding, DaytonaSandboxLifecycle, SandboxCreateSpec, DaytonaSDKBackend,
    declare_daytona_machine, declare_windows_machine,
    WindowsUIABinding, discover_owned_tk_lab, plan_read_only_tk_lab,
    ReadOnlyUIAWorkflow, ReadStep,
)


def sync(coro):
    return asyncio.run(coro)


class Grant:
    def __init__(self):
        self.enabled = True
        self.denied_ids = set()
        self.calls = []

    def __call__(self, request):
        self.calls.append(request.operation_id)
        allowed = self.enabled and request.operation_id not in self.denied_ids
        return PolicyDecision(allowed, "allowed" if allowed else "revoked")


class TitleBackend:
    def __init__(self):
        self.calls = []
        self.changed = False

    def run(self, binding, args):
        self.calls.append(dict(args))
        if self.changed:
            raise RuntimeError("window changed before read")
        return {"pid": binding.pid, "hwnd": binding.hwnd,
                "window_title_sha256": hashlib.sha256(
                    binding.window_title.encode()).hexdigest()}


@pytest.mark.parametrize("owner,handle,should_raise", [
    (1234, 500, None),
    (1235, 500, PermissionError),
    (1234, 0, PermissionError),
    (None, None, LookupError),
])
def test_slice1_discover_exact_own_window_offline(owner, handle, should_raise):
    def exact_title_probe(title):
        assert title == "SENTRA-UIA-LAB-12345678"
        return None if owner is None else (owner, handle)
    if should_raise:
        with pytest.raises(should_raise):
            discover_owned_tk_lab(
                pid=1234, title="SENTRA-UIA-LAB-12345678",
                probe=exact_title_probe)
    else:
        found = discover_owned_tk_lab(
            pid=1234, title="SENTRA-UIA-LAB-12345678",
            probe=exact_title_probe)
        assert (found.pid, found.hwnd) == (1234, 500)


@pytest.mark.parametrize("title", ["Personal Editor", "SENTRA-UIA-LAB", ""])
def test_slice1_discovery_refuses_non_laboratory_titles(title):
    with pytest.raises(ValueError):
        discover_owned_tk_lab(
            pid=1234, title=title, probe=lambda _t: (1234, 123))


def test_slice1_exact_discovery_to_registry_read_only_fixture_e2e():
    found = discover_owned_tk_lab(
        pid=1234, title="SENTRA-UIA-LAB-12345678",
        probe=lambda _title: (1234, 500))
    grant, backend = Grant(), TitleBackend()
    plan = plan_read_only_tk_lab(
        machine_id="lab-win", owner_principal_id="lab",
        pid=found.pid, hwnd=found.hwnd, window_title=found.title,
        policy=grant, backend=backend)
    registry = ExecutorRegistry(authorize=grant)
    plan.declaration.register(registry)
    assert [x.capability_id for x in sync(plan.declaration.discover())] == [
        "lab.read_window_title"]
    request = plan.request(operation_id="read-1", idempotency_key="read-1",
                           work_item_id="work-1")
    first = sync(registry.submit(request))
    replay = sync(registry.submit(request))
    assert first.state == replay.state == "SUCCEEDED"
    assert first.evidence["window_title_sha256"] == hashlib.sha256(
        found.title.encode()).hexdigest()
    assert backend.calls == [{"pid": 1234, "hwnd": 500, "action": "read_window_title"}]
    grant.enabled = False
    from sentra_runtime.executor import AuthorizationRequired
    with pytest.raises(AuthorizationRequired):
        sync(registry.submit(request))
    assert len(backend.calls) == 1


def test_slice1_changed_window_backend_is_fail_closed():
    backend = TitleBackend()
    backend.changed = True
    grant = Grant()
    plan = plan_read_only_tk_lab(
        machine_id="lab-win", owner_principal_id="lab",
        pid=1234, hwnd=500, window_title="SENTRA-UIA-LAB-12345678",
        policy=grant, backend=backend)
    registry = ExecutorRegistry(authorize=grant)
    plan.declaration.register(registry)
    result = sync(registry.submit(plan.request(
        operation_id="op-1", idempotency_key="key-1", work_item_id="work")))
    assert result.state == "FAILED" and result.error == "backend_error"
    assert len(backend.calls) == 1


class SnapshotParams:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeSandbox:
    def __init__(self, sid, *, safe=True):
        self.id = sid
        self.public = not safe
        self.network_block_all = safe
        self.state = "started"
        self.process = self
        self.commands = []

    def exec(self, command, timeout):
        self.commands.append((command, timeout))
        return SimpleNamespace(exit_code=0, result="approved-output")


class SDKFixture:
    """Matches Daytona.get, .create(params), .delete(sandbox), .process.exec."""

    CreateSandboxFromSnapshotParams = SnapshotParams

    def __init__(self):
        self.sandboxes = {"preexisting": FakeSandbox("preexisting")}
        self.creates = []
        self.deletes = []
        self.gets = []

    def get(self, sandbox_id):
        self.gets.append(sandbox_id)
        return self.sandboxes[sandbox_id]

    def create(self, params):
        self.creates.append(params)
        sandbox = FakeSandbox("managed-" + str(len(self.creates)))
        self.sandboxes[sandbox.id] = sandbox
        return sandbox

    def delete(self, sandbox):
        self.deletes.append(sandbox.id)


def lifecycle(*, policy=None, sdk=None, approve=None, enabled=False):
    return DaytonaSandboxLifecycle(
        machine_id="daytona-machine", principal_id="lab",
        existing_ids=("preexisting",), policy=policy or Grant(),
        client=sdk or SDKFixture(), allow_provision=enabled,
        approve_provision=approve)


def test_slice2_sdk_fixture_discover_provision_registry_command_status_cleanup_e2e():
    sdk, grant = SDKFixture(), Grant()
    manager = lifecycle(
        sdk=sdk, policy=grant, enabled=True,
        approve=lambda spec, ref: spec.name == "sentra-lab-unit" and ref == "approved-42")
    listed = manager.discover_existing("preexisting", operation_id="disc-1")
    assert listed.sandbox_id == "preexisting" and listed.private and listed.network_blocked
    spec = SandboxCreateSpec("sentra-lab-unit", "trusted-snapshot")
    new = manager.provision(spec, operation_id="provision-1", approval_ref="approved-42")
    assert new.sandbox_id == "managed-1"
    assert new.private and new.network_blocked and new.state == "started"
    params = sdk.creates[0]
    assert params.public is False and params.network_block_all is True
    assert params.snapshot == "trusted-snapshot" and params.env_vars == {}
    assert params.ephemeral is True
    same = manager.provision(spec, operation_id="provision-1", approval_ref="approved-42")
    assert same.sandbox_id == new.sandbox_id
    assert len(sdk.creates) == 1
    binding = DaytonaBinding(
        "approved-command", new.sandbox_id, ("echo approved",), timeout_seconds=5)
    declaration = declare_daytona_machine(
        machine_id="daytona-machine", owner_principal_id="lab",
        bindings=(binding,), policy=grant,
        backend=DaytonaSDKBackend(client=sdk))
    registry = ExecutorRegistry(authorize=grant)
    declaration.register(registry)
    assert [cap.capability_id for cap in sync(declaration.discover())] == [
        "approved-command"]
    req = OperationRequest(
        operation_id="command-1", principal_id="lab", machine_id="daytona-machine",
        capability_id="approved-command", work_item_id="work",
        idempotency_key="command-1",
        arguments={"action": "exec", "sandbox_id": new.sandbox_id,
                   "command": "echo approved"})
    result = sync(registry.submit(req))
    assert result.state == "SUCCEEDED"
    assert sdk.sandboxes[new.sandbox_id].commands == [("echo approved", 5)]
    assert "approved-output" not in str(result.evidence)
    assert manager.status(new.sandbox_id, operation_id="status-1").state == "started"
    assert manager.cleanup(new.sandbox_id, operation_id="cleanup-1") == "DELETED"
    assert manager.cleanup(new.sandbox_id, operation_id="cleanup-1") == "DELETED"
    assert sdk.deletes == [new.sandbox_id]


@pytest.mark.parametrize("enabled,approval", [
    (False, True), (True, False),
])
def test_slice2_provision_requires_two_independent_grants(enabled, approval):
    sdk = SDKFixture()
    manager = lifecycle(
        sdk=sdk, enabled=enabled,
        approve=lambda _spec, _ref: approval)
    with pytest.raises(PermissionError):
        manager.provision(SandboxCreateSpec("sentra-lab-unit", "snapshot"),
                          operation_id="create-1", approval_ref="approval-ref")
    assert sdk.creates == []


def test_slice2_revoked_policy_cannot_discover_or_cleanup_or_provision():
    sdk, grant = SDKFixture(), Grant()
    manager = lifecycle(sdk=sdk, policy=grant, enabled=True,
                        approve=lambda _s, _r: True)
    grant.enabled = False
    with pytest.raises(PermissionError):
        manager.discover_existing("preexisting", operation_id="discover")
    with pytest.raises(PermissionError):
        manager.provision(SandboxCreateSpec("sentra-lab-unit", "snapshot"),
                          operation_id="create", approval_ref="ref")
    with pytest.raises(PermissionError):
        manager.cleanup("preexisting", operation_id="cleanup")
    assert sdk.creates == sdk.deletes == [] and sdk.gets == []


def test_slice2_no_unmanaged_delete_no_wrong_sandbox_no_shell_fallback():
    sdk = SDKFixture()
    manager = lifecycle(sdk=sdk)
    with pytest.raises(PermissionError):
        manager.cleanup("preexisting", operation_id="cleanup")
    with pytest.raises(PermissionError):
        manager.discover_existing("unregistered", operation_id="discover")
    sdk.sandboxes["preexisting"].public = True
    with pytest.raises(PermissionError):
        manager.discover_existing("preexisting", operation_id="disc-2")
    assert sdk.deletes == []
    # No program from the host is spawned; only the explicitly injected SDK is used.


class ReadBackend:
    def __init__(self, *, grant=None, revoke_after_first=False, block=False):
        self.calls = []
        self.grant = grant
        self.revoke_after_first = revoke_after_first
        self.block = block
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, binding, args):
        self.calls.append(dict(args))
        self.entered.set()
        if self.block:
            self.release.wait(1)
        if self.revoke_after_first and self.grant:
            self.grant.enabled = False
        return {"action": args["action"], "text_sha256": "safe-hash"}


def make_workflow(grant=None, backend=None, *, timeout=2):
    grant = grant or Grant()
    backend = backend or ReadBackend()
    binding = WindowsUIABinding(
        "read-safe", 1234, 500, "SENTRA-UIA-LAB-12345678",
        ("safe_text",), ("Text",), ("read_window_title", "read_text"),
        timeout_seconds=timeout)
    declaration = declare_windows_machine(
        machine_id="wf-win", owner_principal_id="lab",
        bindings=(binding,), policy=grant, backend=backend)
    registry = ExecutorRegistry(authorize=grant)
    declaration.register(registry)
    return ReadOnlyUIAWorkflow(declaration, registry), grant, backend, registry


def stages():
    return (ReadStep("read-safe", "read_window_title"),
            ReadStep("read-safe", "read_text", "safe_text", "Text"))


def test_slice3_multistep_registry_policy_trace_retry_e2e():
    workflow, grant, backend, registry = make_workflow()
    caps = sync(workflow.capabilities())
    assert [c.capability_id for c in caps] == ["read-safe"]
    run = sync(workflow.run(workflow_id="wf1", work_item_id="work", steps=stages()))
    assert run.state == "SUCCEEDED" and len(run.steps) == 2
    assert all(step.state == "SUCCEEDED" and step.evidence_sha256 for step in run.steps)
    assert len(backend.calls) == 2
    repeated = sync(workflow.run(workflow_id="wf1", work_item_id="work", steps=stages()))
    assert repeated == run
    assert len(backend.calls) == 2
    assert grant.calls.count("wf1:read:0") >= 2
    assert grant.calls.count("wf1:read:1") >= 2


def test_slice3_revoked_before_second_stage_denies_no_new_execution():
    grant = Grant()
    grant.denied_ids.add("wf2:read:1")
    workflow, _, backend, _ = make_workflow(grant=grant)
    result = sync(workflow.run(workflow_id="wf2", work_item_id="work", steps=stages()))
    assert result.state == "DENIED"
    assert [x.state for x in result.steps] == ["SUCCEEDED", "DENIED"]
    assert len(backend.calls) == 1
    grant.enabled = False
    retry = sync(workflow.run(workflow_id="wf2", work_item_id="work", steps=stages()))
    assert retry.state == "DENIED"
    assert len(backend.calls) == 1


def test_slice3_revoke_during_execution_uncertain_no_next_step():
    grant = Grant()
    backend = ReadBackend(grant=grant, revoke_after_first=True)
    workflow, _, _, _ = make_workflow(grant=grant, backend=backend)
    result = sync(workflow.run(workflow_id="wf3", work_item_id="work", steps=stages()))
    assert result.state == "UNCERTAIN"
    assert len(result.steps) == 1 and len(backend.calls) == 1
    retry = sync(workflow.run(workflow_id="wf3", work_item_id="work", steps=stages()))
    assert retry.state == "DENIED"
    assert len(backend.calls) == 1


def test_slice3_timeout_uncertain_never_replays_external_action():
    grant = Grant()
    backend = ReadBackend(block=True)
    workflow, _, _, _ = make_workflow(grant=grant, backend=backend, timeout=.04)
    async def scenario():
        task = asyncio.create_task(workflow.run(
            workflow_id="wf4", work_item_id="work", steps=stages()))
        try:
            assert await asyncio.to_thread(backend.entered.wait, 1)
            first = await task
            retry = await workflow.run(
                workflow_id="wf4", work_item_id="work", steps=stages())
        finally:
            backend.release.set()
        return first, retry
    first, retry = sync(scenario())
    assert first.state == retry.state == "UNCERTAIN"
    assert len(first.steps) == len(retry.steps) == 1
    assert len(backend.calls) == 1


@pytest.mark.parametrize("bad_step", [
    ("read-safe", "invoke"), ("read-safe", "shell"), ("unregistered", "read_window_title"),
])
def test_slice3_no_invoke_no_shell_no_unknown_capabilities(bad_step):
    wf, _, backend, _ = make_workflow()
    if bad_step[1] in ("invoke", "shell"):
        with pytest.raises(ValueError, match="workflow_only_read_actions"):
            ReadStep(*bad_step)
    else:
        with pytest.raises(ValueError, match="workflow_step_not_in_discovered_capability"):
            sync(wf.run(workflow_id="wf", work_item_id="work",
                        steps=(ReadStep(*bad_step),)))
    assert backend.calls == []


def test_slice2_same_operation_different_spec_cannot_reprovision():
    sdk = SDKFixture()
    manager = lifecycle(
        sdk=sdk, enabled=True, approve=lambda _spec, _ref: True)
    first = manager.provision(SandboxCreateSpec("sentra-lab-one", "snapshot"),
                              operation_id="create-1", approval_ref="grant")
    assert first.sandbox_id == "managed-1"
    with pytest.raises(ValueError, match="provision_idempotency_conflict"):
        manager.provision(SandboxCreateSpec("sentra-lab-two", "snapshot"),
                          operation_id="create-1", approval_ref="grant")
    assert len(sdk.creates) == 1


def test_slice2_remote_create_failure_is_uncertain_and_does_not_auto_retry():
    class BrokenSDK(SDKFixture):
        def create(self, params):
            self.creates.append(params)
            raise TimeoutError("remote create may have succeeded")
    sdk = BrokenSDK()
    manager = lifecycle(sdk=sdk, enabled=True, approve=lambda _s, _r: True)
    request = SandboxCreateSpec("sentra-lab-once", "snapshot")
    with pytest.raises(TimeoutError):
        manager.provision(request, operation_id="create-1", approval_ref="approved")
    with pytest.raises(RuntimeError, match="provision_uncertain_manual_reconcile"):
        manager.provision(request, operation_id="create-1", approval_ref="approved")
    assert len(sdk.creates) == 1


def test_slice2_remote_cleanup_failure_is_uncertain_and_does_not_auto_retry():
    class BrokenSDK(SDKFixture):
        def delete(self, sandbox):
            self.deletes.append(sandbox.id)
            raise TimeoutError("remote delete may have succeeded")
    sdk = BrokenSDK()
    manager = lifecycle(sdk=sdk, enabled=True, approve=lambda _s, _r: True)
    view = manager.provision(
        SandboxCreateSpec("sentra-lab-once", "snapshot"),
        operation_id="create-1", approval_ref="approved")
    with pytest.raises(TimeoutError):
        manager.cleanup(view.sandbox_id, operation_id="cleanup-1")
    with pytest.raises(RuntimeError, match="cleanup_uncertain_manual_reconcile"):
        manager.cleanup(view.sandbox_id, operation_id="cleanup-1")
    assert sdk.deletes == ["managed-1"]


def test_slice1_actual_pywinauto_backend_algorithm_using_uia_fixture(monkeypatch):
    """Exercises actual production PywinautoUIABackend, fake ONLY COM provider."""
    import sys
    import types
    from sentra_executors import PywinautoUIABackend
    grant = Grant()
    title = "SENTRA-UIA-LAB-12345678"

    class FakeElement:
        process_id = 1234
        handle = 500
    class FakeWindow:
        element_info = FakeElement()
        def __init__(self):
            self.title = title
        def window_text(self):
            return self.title
    window = FakeWindow()
    class FakeApplication:
        def __init__(self, backend):
            assert backend == "uia"
        def connect(self, process):
            assert process == 1234
            return self
        def window(self, handle):
            assert handle == 500
            return self
        def wrapper_object(self):
            return window

    package = types.ModuleType("pywinauto")
    package.__path__ = []
    app_module = types.ModuleType("pywinauto.application")
    app_module.Application = FakeApplication
    monkeypatch.setitem(sys.modules, "pywinauto", package)
    monkeypatch.setitem(sys.modules, "pywinauto.application", app_module)
    plan = plan_read_only_tk_lab(
        machine_id="lab", owner_principal_id="lab",
        pid=1234, hwnd=500, window_title=title,
        policy=grant, backend=PywinautoUIABackend())
    registry = ExecutorRegistry(authorize=grant)
    plan.declaration.register(registry)
    result = sync(registry.submit(plan.request(
        operation_id="real-backend-1", idempotency_key="key-1",
        work_item_id="work")))
    assert result.state == "SUCCEEDED"
    assert result.evidence["window_title_sha256"] == hashlib.sha256(
        title.encode()).hexdigest()

    # Change window between binding and COM access: no data exposed.
    window.title = "unrelated-private-window"
    next_request = plan.request(
        operation_id="real-backend-2", idempotency_key="key-2",
        work_item_id="work")
    denied = sync(registry.submit(next_request))
    assert denied.state == "FAILED"
    assert denied.error == "backend_error"
    assert denied.evidence == {}


def test_slice3_all_steps_prevalidated_no_partial_side_effect():
    wf, grant, backend, _ = make_workflow()
    good = ReadStep("read-safe", "read_window_title")
    invalid = ReadStep("missing", "read_window_title")
    with pytest.raises(ValueError, match="workflow_step_not_in_discovered_capability"):
        sync(wf.run(workflow_id="wf-invalid", work_item_id="work",
                    steps=(good, invalid)))
    assert backend.calls == []


def test_slice2_revoked_during_create_is_uncertain_not_replayed():
    grant = Grant()
    class RevokingSDK(SDKFixture):
        def create(self, params):
            result = super().create(params)
            grant.enabled = False
            return result
    sdk = RevokingSDK()
    manager = lifecycle(sdk=sdk, policy=grant, enabled=True,
                        approve=lambda _s, _r: True)
    spec = SandboxCreateSpec("sentra-lab-once", "snapshot")
    with pytest.raises(PermissionError, match="sandbox_lifecycle_policy_denied"):
        manager.provision(spec, operation_id="create", approval_ref="signed-ref")
    grant.enabled = True
    with pytest.raises(RuntimeError, match="provision_uncertain_manual_reconcile"):
        manager.provision(spec, operation_id="create", approval_ref="signed-ref")
    assert len(sdk.creates) == 1


def test_slice2_revoked_during_delete_is_uncertain_not_replayed():
    grant = Grant()
    class RevokingSDK(SDKFixture):
        def delete(self, sandbox):
            super().delete(sandbox)
            grant.enabled = False
    sdk = RevokingSDK()
    manager = lifecycle(sdk=sdk, policy=grant, enabled=True,
                        approve=lambda _s, _r: True)
    new = manager.provision(SandboxCreateSpec("sentra-lab-once", "snapshot"),
                            operation_id="create", approval_ref="signed-ref")
    with pytest.raises(PermissionError, match="sandbox_lifecycle_policy_denied"):
        manager.cleanup(new.sandbox_id, operation_id="delete")
    grant.enabled = True
    with pytest.raises(RuntimeError, match="cleanup_uncertain_manual_reconcile"):
        manager.cleanup(new.sandbox_id, operation_id="delete")
    assert sdk.deletes == [new.sandbox_id]
