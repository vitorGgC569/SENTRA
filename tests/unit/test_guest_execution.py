"""Production guestcontrol executor. Fake VirtualBox client only."""
from __future__ import annotations

import pytest

import subprocess

from sentra_executors.guest_execution import (
    GuestExecutionRefused,
    InjectableGuestExecutor,
    VirtualBoxGuestControlExecutor,
    is_proven_guest_executor,
    resolve_guest_executor,
    resolve_guest_executor_from_authority,
)


class FakeClient:
    def __init__(self, stdout="guestcontrol-stdout"):
        self.calls = []
        self.stdout = stdout

    def run(self, *parts, **kwargs):
        assert parts[0] == "guestcontrol"
        self.calls.append((parts, kwargs))
        return self.stdout


def test_production_executor_is_proven_guest_and_calls_guestcontrol():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    assert is_proven_guest_executor(guest) is True
    assert guest.proven_guest is True
    assert guest.execution_surface == "guest"
    produced = guest.execute({
        "placement": "guest",
        "tool": "sentra-cli",
        "prompt": "inspect the workspace",
        "timeout_s": 12,
        "workspace": r"C:\Users\vitor\host-workspace",
    })
    assert produced["execution_surface"] == "guest"
    assert produced["host_subprocess"] is False
    assert produced["claims_guest_execution"] is True
    assert produced["guest_witness"] == "guestcontrol"
    assert produced["vm_id"] == "owned-guest-vm"
    assert produced["exit_code"] == 0
    assert produced["stdout"] == "guestcontrol-stdout"
    assert len(client.calls) == 1
    parts, options = client.calls[0]
    assert parts[:3] == ("guestcontrol", "owned-guest-vm", "run")
    assert parts[parts.index("--exe") + 1] == "/bin/sh"
    assert parts[parts.index("--") + 1] == "-c"
    assert parts.count("/bin/sh") == 1
    assert parts[parts.index("--username") + 1] == "sentra"
    assert "--passwordfile" in parts and "stdin" in parts
    assert "dot-secret" not in parts
    assert options["password"] == "dot-secret"
    command = parts[-1]
    assert "sentra-cli" in command
    assert r"C:\Users\vitor\host-workspace" not in command
    assert "/home/sentra" in command


def test_guest_additions_probe_does_not_query_a_path():
    from types import SimpleNamespace
    from sentra_executors.virtualbox_vm import VirtualBoxClient
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='GuestAdditionsRunLevel="2"\n', stderr='')

    client = VirtualBoxClient('owned-VBoxManage.exe', runner)
    assert client.guest_additions_runlevel('../other') == '0'
    assert calls == []
    assert client.guest_additions_runlevel('owned-guest-vm') == '2'
    assert calls and calls[0][2] == 'owned-guest-vm'


def test_guest_executor_refuses_a_path_as_the_vm_id():
    client = FakeClient()
    with pytest.raises(ValueError, match="vm_id"):
        VirtualBoxGuestControlExecutor(
            client, vm_id="../other", username="sentra", password="dot-secret",
        )
    assert client.calls == []


def test_windows_guestcontrol_uses_powershell_and_keeps_password_off_argv():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-win-vm", username="sentra", password="win-secret",
        os_family="windows",
    )
    guest.execute({"placement": "guest", "command": "Write-Output ready"})
    parts, options = client.calls[0]
    assert "powershell.exe" in parts[parts.index("--exe") + 1]
    assert parts[parts.index("--") + 1] == "-NoLogo"
    assert "powershell.exe" not in parts[parts.index("--") + 1:]
    assert options["password"] == "win-secret"
    assert "win-secret" not in parts


def test_windows_cli_stops_when_the_dot_folder_cannot_be_opened():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-win-vm", username="sentra", password="win-secret",
        os_family="windows",
    )
    guest.execute({
        "placement": "guest",
        "tool": "sentra-cli",
        "prompt": "inspect the workspace",
        "model": "sentra/chatgpt-web/gpt-6",
        "effort": "high",
        "guest_workspace": r"C:\Users\sentra\Imports\one",
    })
    command = client.calls[0][0][-1]
    assert "Set-Location -LiteralPath 'C:\\Users\\sentra\\Imports\\one' -ErrorAction Stop" in command
    assert "exit 1" in command
    assert command.index("Set-Location") < command.index("exit 1") < command.index("sentra-cli")
    assert "win-secret" not in command


def test_guest_command_that_contains_the_password_is_not_sent():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    with pytest.raises(ValueError, match="credential"):
        guest.execute({"placement": "guest", "command": "echo dot-secret"})
    assert client.calls == []
    assert guest.calls == []
    with pytest.raises(ValueError, match="credential"):
        guest.execute({
            "placement": "guest", "tool": "sentra-cli", "prompt": "inspect",
            "model": "sentra/chatgpt-web/gpt-6", "effort": "high",
            "guest_workspace": "/home/sentra/dot-secret",
        })
    assert client.calls == []
    named = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="chatgpt-web",
    )
    with pytest.raises(ValueError, match="credential"):
        named.execute({
            "placement": "guest", "tool": "sentra-cli", "prompt": "inspect",
            "model": "sentra/chatgpt-web/gpt-6", "effort": "high",
        })
    assert client.calls == []


def test_guestcontrol_output_that_contains_the_password_is_not_a_claim():
    import json
    client = FakeClient(stdout="prefix dot-secret suffix")
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    result = guest.execute({"placement": "guest", "command": "echo hi"})
    assert result["claims_guest_execution"] is False
    assert result["stdout"] == ""
    assert result["credential_discarded"] is True
    assert "dot-secret" not in json.dumps(result)
    assert len(client.calls) == 1


def test_bound_argv_must_be_guestcontrol_for_this_vm():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    guest.execute({
        "placement": "guest",
        "argv": ["guestcontrol", "owned-guest-vm", "run", "--exe", "/bin/sh",
                 "--username", "sentra", "--passwordfile", "stdin", "--", "-c", "echo ok"],
    })
    assert client.calls[0][0][1] == "owned-guest-vm"
    with pytest.raises(ValueError, match="bound VM"):
        guest.execute({"placement": "guest", "argv": ["python", "-c", "print(1)"]})
    with pytest.raises(ValueError, match="bound VM"):
        guest.execute({
            "placement": "guest",
            "argv": ["guestcontrol", "other-vm", "run", "--exe", "/bin/sh"],
        })
    assert len(client.calls) == 1


def test_guestcontrol_timeout_longer_than_the_host_wait_is_not_sent():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    with pytest.raises(GuestExecutionRefused, match="host wait"):
        guest.execute({
            "placement": "guest",
            "timeout_s": 120,
            "argv": ["guestcontrol", "owned-guest-vm", "run", "--timeout", "600000",
                     "--exe", "/bin/sh", "--", "-c", "echo ok"],
        })
    assert client.calls == []
    assert guest.calls == []
    guest.execute({
        "placement": "guest",
        "timeout_s": 600,
        "argv": ["guestcontrol", "owned-guest-vm", "run", "--timeout", "600000",
                 "--exe", "/bin/sh", "--", "-c", "echo ok"],
    })
    assert len(client.calls) == 1
    assert client.calls[0][1]["timeout"] == 610


def test_guestcontrol_wait_that_ends_early_is_not_a_confirmed_command():
    class TimingOut(FakeClient):
        def run(self, *parts, **kwargs):
            self.calls.append((parts, kwargs))
            raise subprocess.TimeoutExpired(cmd=parts, timeout=kwargs.get("timeout", 0))

    client = TimingOut()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    result = guest.execute({"placement": "guest", "command": "echo ok", "timeout_s": 30})
    assert result["claims_guest_execution"] is False
    assert result["stdout"] == ""
    assert result["execution_uncertain"] is True
    assert result["automatic_retry"] is False
    assert result["exit_code"] is None
    assert "dot-secret" not in str(result)
    assert len(client.calls) == 1


def test_missing_dot_credentials_stay_blocked_and_injected_executor_wins():
    client = FakeClient()
    assert resolve_guest_executor(client=client) is None
    assert resolve_guest_executor(vm_id="owned-guest-vm", username="sentra", client=client) is None
    assert resolve_guest_executor(vm_id="owned-guest-vm", password="x", client=client) is None
    assert resolve_guest_executor_from_authority(
        {"placement": "guest", "vm_id": "owned-guest-vm", "virtualbox_client": client},
    ) is None
    double = InjectableGuestExecutor(lambda request: {"exit_code": 0, "stdout": "ok", "stderr": ""})
    assert resolve_guest_executor(
        double, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
        client=client,
    ) is double
    built = resolve_guest_executor_from_authority({
        "vm_id": "owned-guest-vm",
        "username": "sentra",
        "password": "dot-secret",
        "virtualbox_client": client,
    })
    assert isinstance(built, VirtualBoxGuestControlExecutor)
    assert built.vm_id == "owned-guest-vm"
    assert client.calls == []


def test_unready_guest_channel_never_reaches_guestcontrol(monkeypatch):
    class Unready:
        def guest_additions_runlevel(self, vm_id):
            return "0"

        def run(self, *args, **kwargs):
            raise AssertionError("guestcontrol must not run")

    client = Unready()
    monkeypatch.setattr(
        "sentra_executors.virtualbox_vm.VirtualBoxClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("VirtualBoxClient must not be constructed")),
    )
    for vm_id in ("windows-installing", "owned-guest-vm"):
        assert resolve_guest_executor(
            vm_id=vm_id, username="sentra", password="dot-secret", os_family="windows",
            client=client,
        ) is None
        with pytest.raises(ValueError, match="guest channel is not ready"):
            VirtualBoxGuestControlExecutor(
                client, vm_id=vm_id, username="sentra", password="dot-secret",
                os_family="windows",
            )
    double = InjectableGuestExecutor(lambda request: {"exit_code": 0, "stdout": "ok", "stderr": ""})
    double.vm_id = "windows-installing"
    assert resolve_guest_executor(
        double, vm_id="windows-installing", username="sentra", password="dot-secret",
        client=client,
    ) is None
    assert double.calls == []


def test_valid_dot_binding_uses_virtualbox_client_without_calling_it(monkeypatch):
    created = []

    class SentinelClient:
        def __init__(self, *args, **kwargs):
            created.append(self)

        def run(self, *args, **kwargs):
            raise AssertionError("resolve must not call guestcontrol")

    monkeypatch.setattr("sentra_executors.virtualbox_vm.VirtualBoxClient", SentinelClient)
    built = resolve_guest_executor(vm_id="owned-guest-vm", username="sentra", password="dot-secret")
    assert isinstance(built, VirtualBoxGuestControlExecutor)
    assert built.proven_guest is True
    assert built.execution_surface == "guest"
    assert created and built._client is created[0]
    assert built.vm_id == "owned-guest-vm"


def test_import_shaped_request_does_not_fake_a_proven_copy():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    with pytest.raises(ValueError, match="guest command or tool prompt required"):
        guest.execute({
            "action": "project.import",
            "placement": "guest",
            "sha256": "abc",
            "vm_id": "owned-guest-vm",
            "guest_path": "/home/sentra/Imports/one/project",
            "archive": r"C:\Users\vitor\host\project.tar",
        })
    assert client.calls == []


def test_unsupported_model_and_host_workspace_do_not_call_guestcontrol():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    with pytest.raises(ValueError, match="GPT-6"):
        guest.execute({
            "placement": "guest", "tool": "sentra-cli", "prompt": "inspect",
            "model": "sentra/other",
        })
    with pytest.raises(ValueError, match="host workspace"):
        guest.execute({
            "placement": "guest", "tool": "codex", "prompt": "inspect",
            "workspace": r"C:\Users\vitor\host-workspace",
            "guest_workspace": r"C:\Users\vitor\host-workspace",
        })
    guest.execute({
        "placement": "guest", "tool": "codex", "prompt": "inspect the guest",
        "model": "gpt-6", "workspace": r"C:\Users\vitor\host-workspace",
    })
    command = client.calls[0][0][-1]
    assert "codex" in command and "/home/sentra" in command
    assert r"C:\Users\vitor\host-workspace" not in command
    assert "gpt-6" in command
    assert len(client.calls) == 1
    guest.execute({
        "placement": "guest", "tool": "sentra-cli", "prompt": "inspect the guest",
        "model": "sentra/grok/grok-4.7",
    })
    grok_command = client.calls[1][0][-1]
    assert "sentra/grok/grok-4.7" in grok_command
    assert "sentra/chatgpt-web/gpt-6" not in grok_command
    guest.execute({
        "placement": "guest", "tool": "opencode", "prompt": "edit the import",
        "guest_workspace": "/home/sentra/Imports/one/project",
    })
    opencode_command = client.calls[2][0][-1]
    folder, command = opencode_command.split(" && ", 1)
    assert folder.startswith("cd ") and "/home/sentra/Imports/one/project" in folder
    assert command.startswith("opencode ")
    assert "opencode" in opencode_command
    with pytest.raises(ValueError, match="Dot home"):
        guest.execute({
            "placement": "guest", "tool": "opencode", "prompt": "escape",
            "guest_workspace": "/home/sentra/../../etc",
        })
    calls_before = len(client.calls)
    with pytest.raises(ValueError, match="Dot home"):
        guest.execute({
            "placement": "guest", "tool": "opencode", "prompt": "metachar",
            "guest_workspace": "/home/sentra/Imports/a;id",
        })
    assert len(client.calls) == calls_before


def test_guest_workspace_follows_the_dot_account():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="dotuser", password="dot-secret",
    )
    guest.execute({
        "placement": "guest", "tool": "opencode", "prompt": "edit the import",
        "guest_workspace": "/home/dotuser/Imports/one/project",
    })
    command = client.calls[0][0][-1]
    assert "/home/dotuser/Imports/one/project" in command
    assert "/home/sentra" not in command
    guest.execute({"placement": "guest", "tool": "codex", "prompt": "work at home"})
    home_command = client.calls[1][0][-1]
    assert "/home/dotuser" in home_command
    assert "/home/sentra" not in home_command
    with pytest.raises(ValueError, match="Dot home"):
        guest.execute({
            "placement": "guest", "tool": "opencode", "prompt": "wrong home",
            "guest_workspace": "/home/sentra/Imports/one/project",
        })


def test_host_placement_and_foreign_vm_are_refused():
    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    with pytest.raises(ValueError, match="host placement"):
        guest.execute({"placement": "host", "command": "echo no"})
    with pytest.raises(ValueError, match="different VM"):
        guest.execute({"placement": "guest", "vm_id": "other-vm", "command": "echo no"})
    assert client.calls == []
