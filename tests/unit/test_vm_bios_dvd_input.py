"""The BIOS Windows DVD keystroke macro is a single fenced vm:input effect."""
from contextlib import contextmanager
from types import SimpleNamespace
import uuid

import pytest

from sentra_canvas.shell_actor import _vm_input_identity
from sentra_executors.virtualbox_vm import VirtualBoxClient, VirtualBoxExecutor, VirtualBoxBinding


def test_bios_dvd_macro_has_bounded_keys_and_keeps_unverified_result(monkeypatch):
    from sentra_executors import virtualbox_vm
    delays, events = [], []
    monkeypatch.setattr(virtualbox_vm.time, "sleep", lambda delay: delays.append(delay))

    class Client(VirtualBoxClient):
        @contextmanager
        def console(self, binding):
            yield SimpleNamespace(Keyboard=SimpleNamespace(PutScancodes=lambda scans: events.append(list(scans))))

    cid = str(uuid.uuid4())
    client = Client("test-owned.exe")
    binding = VirtualBoxBinding(cid, "SENTRA-DOT:" + cid, lambda: {"os_family": "windows"})
    result = client.input(binding, {"action": "input.bios_dvd"})
    assert events[0] == [0x1D, 0x38, 0xE0, 0x53, 0xE0, 0xD3, 0xB8, 0x9D]
    assert events[1:] == [[0x39, 0xB9]] * 11
    assert len(delays) == 12
    assert delays[0] == 1.4
    assert result["input_sent"] is True
    assert result["windows_setup_verified"] is False
    assert result["automatic_retry"] is False


def test_bios_dvd_requires_owned_running_windows_iso_and_no_extra_arguments():
    cid = str(uuid.uuid4())
    cfg = {"os_family": "windows"}
    binding = VirtualBoxBinding(cid, "SENTRA-DOT:" + cid, lambda: cfg)
    good = dict(VMState="running", boot1="dvd", **{"IDE-0-0": "C:/SENTRA/Isos/Windows.iso"})
    calls = []
    client = SimpleNamespace(status=lambda token: dict(good), input=lambda token, args: (calls.append(args) or {"input_sent":True}))
    executor = VirtualBoxExecutor(machine_id="machine-1", owner_principal_id="agent", bindings={"vm:input": binding}, client=client)
    args = {"action":"input.bios_dvd"}
    assert executor._validate(SimpleNamespace(arguments=args,capability_id="vm:input"),binding) == args
    assert executor._execute(binding, args)["input_sent"] is True
    assert calls == [args]
    with pytest.raises(ValueError):
        executor._validate(SimpleNamespace(arguments={"action":"input.bios_dvd", "scancodes":[0x39]},capability_id="vm:input"),binding)
    for changed in (
        {"VMState":"poweroff"}, {"boot1":"disk"},
        {"IDE-0-0":"C:/SENTRA/Isos/aux.viso"}):
        client.status = lambda token, changed=changed: {**good,**changed}
        with pytest.raises(Exception, match="windows_dvd_boot_preconditions_unverified"):
            executor._execute(binding,args)
    cfg["os_family"] = "linux"
    with pytest.raises(ValueError, match="Windows-installation-only"):
        executor._execute(binding,args)


def test_bios_dvd_is_distinct_fenced_input_identity():
    assert _vm_input_identity({"action":"input.bios_dvd"}) == (
        "keyboard", "vm-bios-dvd-shortcut", "ctrl-alt-del-then-space")
    assert _vm_input_identity({"action":"input.bios_dvd", "scancodes":[57]}) is None
