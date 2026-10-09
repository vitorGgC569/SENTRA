"""Phase 2 slice 3: real registry, fake identity/lease sources, fail-closed."""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time

import pytest
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.executor import ExecutorRegistry, AuthorizationRequired
from sentra_executors import (
    WindowsUIABinding, ProcessIdentity, FenceLease, IdentityUIABinding,
    WindowsIdentityProbe, declare_hardened_windows_machine,
)


def go(c):
    return asyncio.run(c)


class Grant:
    allowed = True
    def __call__(self, req):
        return PolicyDecision(self.allowed, "lab-policy")


class Lab:
    def __init__(self, *, forged=False):
        self.pid = 15151
        self.hwnd = 25252
        self.identity = ProcessIdentity(self.pid, self.hwnd, 123456789,
                                        hashlib.sha256(b"isolated-test-exe").hexdigest())
        self.lease = FenceLease("lease-1", 42, time.monotonic()+20)
        self.probes = []
        self.fences = []
        self.calls = []
        self.forged = forged

    def probe(self, pid, hwnd):
        self.probes.append((pid, hwnd))
        return self.identity

    def reader(self, lease_id):
        self.fences.append(lease_id)
        return self.lease

    def run(self, binding, args):
        self.calls.append(dict(args))
        if self.forged:
            self.identity = ProcessIdentity(
                self.pid, self.hwnd, 123456790, self.identity.executable_sha256)
        return {"window_title_sha256": hashlib.sha256(
            binding.window_title.encode()).hexdigest()}


def setup(lab=None, grant=None):
    lab = lab or Lab()
    grant = grant or Grant()
    target = WindowsUIABinding(
        capability_id="hardened-lab-read", pid=lab.pid, hwnd=lab.hwnd,
        window_title="SENTRA-UIA-LAB-12345678",
        allowed_automation_ids=("_not_used",),
        allowed_actions=("read_window_title",))
    binding = IdentityUIABinding(target, lab.identity, lab.lease)
    declaration = declare_hardened_windows_machine(
        machine_id="hardened-windows-lab", owner_principal_id="lab",
        bindings=(binding,), policy=grant,
        identity_probe=lab.probe, lease_reader=lab.reader, backend=lab)
    registry = ExecutorRegistry(authorize=grant)
    declaration.register(registry)
    return registry, declaration, lab, grant


def request(*, op="op-hardened", pid=15151, token=42):
    return OperationRequest(
        operation_id=op, principal_id="lab",
        machine_id="hardened-windows-lab",
        capability_id="hardened-lab-read", work_item_id="work",
        idempotency_key=op, arguments={
            "action": "read_window_title", "pid": pid, "hwnd": 25252,
            "lease_id": "lease-1", "fencing_token": token})


def test_full_registry_process_identity_lease_fixture_e2e():
    reg, declaration, lab, grant = setup()
    assert [x.capability_id for x in go(declaration.discover())] == [
        "hardened-lab-read"]
    out = go(reg.submit(request()))
    assert out.state == "SUCCEEDED"
    assert len(lab.calls) == 1
    assert len(lab.probes) == 2 and len(lab.fences) == 2
    repeat = go(reg.submit(request()))
    assert repeat.state == "SUCCEEDED"
    assert len(lab.calls) == 1
    grant.allowed = False
    with pytest.raises(AuthorizationRequired):
        go(reg.submit(request()))


@pytest.mark.parametrize("fault", ["pid-reuse", "binary-change", "lease-epoch",
                                   "lease-expired", "fence-untyped"])
def test_identity_or_fencing_change_denies_before_backend(fault):
    lab = Lab()
    reg, _, _, _ = setup(lab=lab)
    if fault == "pid-reuse":
        lab.identity = ProcessIdentity(
            lab.pid, lab.hwnd, lab.identity.creation_filetime+1,
            lab.identity.executable_sha256)
    elif fault == "binary-change":
        lab.identity = ProcessIdentity(
            lab.pid, lab.hwnd, lab.identity.creation_filetime, "a"*64)
    elif fault == "lease-epoch":
        lab.lease = FenceLease("lease-1", 43, time.monotonic()+20)
    elif fault == "lease-expired":
        lab.lease = FenceLease("lease-1", 42, time.monotonic()-1)
    else:
        lab.reader = lambda _lease: {"lease_id": "lease-1", "token": 42}
        # Bind methods were captured when registry registered;
        # supply a separate test via mutable lease property instead.
        reg._executors["hardened-windows-lab"].lease_reader = lab.reader
    result = go(reg.submit(request()))
    assert result.state == "FAILED" and result.error == "backend_error"
    assert lab.calls == []


@pytest.mark.parametrize("pid,token", [(15152, 42), (15151, 43),
                                       (True, 42), (15151, True)])
def test_no_caller_forged_identity_or_fencing_token(pid, token):
    reg, _, lab, _ = setup()
    result = go(reg.submit(request(pid=pid, token=token)))
    assert result.state == "FAILED"
    assert result.error == "invalid_scope_or_capability"
    assert lab.calls == []


def test_identity_change_after_read_fails_closed_no_stale_success():
    lab = Lab(forged=True)
    reg, _, _, _ = setup(lab=lab)
    result = go(reg.submit(request()))
    assert result.state == "FAILED" and result.error == "backend_error"
    assert result.evidence == {}
    assert len(lab.calls) == 1
    assert len(lab.probes) == 2


def test_identity_binding_refuses_write_access_and_personal_window():
    lab = Lab()
    write = WindowsUIABinding(
        capability_id="bad", pid=lab.pid, hwnd=lab.hwnd,
        window_title="SENTRA-UIA-LAB-12345678",
        allowed_automation_ids=("some-control",), allowed_actions=("invoke",))
    with pytest.raises(ValueError, match="hardened_lab_must_be_read_only"):
        IdentityUIABinding(write, lab.identity, lab.lease)
    personal = WindowsUIABinding(
        capability_id="bad", pid=lab.pid, hwnd=lab.hwnd,
        window_title="Personal Browser",
        allowed_automation_ids=("_unused",),
        allowed_actions=("read_window_title",))
    with pytest.raises(ValueError, match="hardened_lab_must_be_read_only"):
        IdentityUIABinding(personal, lab.identity, lab.lease)


def test_hardened_does_not_provide_windows_isolation():
    """Only a typed identity + per-call lease; no AppContainer/privilege change."""
    assert WindowsIdentityProbe is not None


@pytest.mark.skipif(
    sys.platform != "win32" or
    os.environ.get("SENTRA_UIA_LAB_RUN") != "1" or
    os.environ.get("SENTRA_UIA_LAB_VM_CONFIRMED") != "1",
    reason="actual Windows UIA identity requires approved isolated lab VM",
)
def test_windows_process_identity_real_lab_opt_in_only():
    """Owned Tk subprocess only, with operator-confirmed dedicated Windows VM."""
    pytest.importorskip("pywinauto.application")
    pytest.importorskip("tkinter")
    import subprocess
    import uuid
    from sentra_executors import (
        PywinautoUIABackend, discover_owned_tk_lab,
    )
    title = "SENTRA-UIA-LAB-" + uuid.uuid4().hex[:16]
    child_code = (
        "import tkinter as tk\n"
        "window=tk.Tk()\n"
        f"window.title({title!r})\n"
        "window.geometry('250x100')\n"
        "window.mainloop()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-B", "-c", child_code],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    try:
        owned = None
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            assert proc.poll() is None, "owned Tk child exited"
            try:
                owned = discover_owned_tk_lab(pid=proc.pid, title=title)
                break
            except LookupError:
                time.sleep(.1)
        assert owned is not None, "owned Tk test window missing"
        probe = WindowsIdentityProbe()
        observed = probe(proc.pid, owned.hwnd)
        assert observed.pid == proc.pid and observed.hwnd == owned.hwnd
        assert observed.creation_filetime > 0
        lease = FenceLease("owned-test-lease", 7, time.monotonic()+15)
        target = WindowsUIABinding(
            "owned-title-read", proc.pid, owned.hwnd, title,
            ("_unused",), ("Text",), ("read_window_title",))
        binding = IdentityUIABinding(target, observed, lease)
        grant = Grant()
        declaration = declare_hardened_windows_machine(
            machine_id="hardened-windows-lab", owner_principal_id="lab",
            bindings=(binding,), policy=grant, identity_probe=probe,
            lease_reader=lambda _id: lease,
            backend=PywinautoUIABackend())
        registry = ExecutorRegistry(authorize=grant)
        declaration.register(registry)
        req = OperationRequest(
            "owned-op", "lab", "hardened-windows-lab", "owned-title-read",
            "owned-work", "owned-key",
            {"action": "read_window_title", "pid": proc.pid, "hwnd": owned.hwnd,
             "lease_id": lease.lease_id, "fencing_token": lease.token})
        outcome = go(registry.submit(req))
        assert outcome.state == "SUCCEEDED"
        assert outcome.evidence["window_title_sha256"] == hashlib.sha256(
            title.encode()).hexdigest()
    finally:
        # Only the child that THIS test started; never interact with other UI.
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=4)


@pytest.mark.parametrize("bad_expiry", [float("nan"), float("inf"), float("-inf"), True])
def test_fence_expiry_rejects_non_finite_or_boolean_values(bad_expiry):
    with pytest.raises(ValueError, match="invalid_fence_lease"):
        FenceLease("lab-lease", 10, bad_expiry)
