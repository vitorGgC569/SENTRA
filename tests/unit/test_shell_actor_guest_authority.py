"""ShellActorService.compose copies a Dot VM binding into guest dispatch authority.

The password may reach the dispatch. It must not come back in the receipt,
fleet gate, logs, or exception text. No test starts guestcontrol.
"""
import hashlib
import json
import sys
from contextlib import closing
from pathlib import Path

import pytest

UNIT = Path(__file__).resolve().parents[1]
if str(UNIT) not in sys.path:
    sys.path.insert(0, str(UNIT))

from sentra_canvas.shell_actor import ShellActorService
from sentra_canvas.shell_dot_vm import VmStore
from sentra_core.conversations import _encode
from test_shell_dot_features import shell


FORBIDDEN_VM = "SENTRA-Dot-b1a7b4555800414f"
VM_ID = "owned-guest-vm"
USERNAME = "sentra"
SECRET = "dot-registry-secret-not-for-receipt"


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _leaked(blob, secret):
    if isinstance(blob, str):
        text = blob
    else:
        text = json.dumps(blob, default=str)
    return bool(secret) and secret in text


def _has_secret_key(value):
    if isinstance(value, dict):
        if "password" in value or "guest_password" in value:
            return True
        return any(_has_secret_key(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_secret_key(item) for item in value)
    return False


def _refuse_leak(blob, secret, where):
    if _leaked(blob, secret) or _has_secret_key(blob):
        pytest.fail("guest password leaked into " + where)


def _intent(dot_id):
    return {
        "kind": "dot_tool_dispatch",
        "tool": "sentra-cli",
        "target_dot_id": dot_id,
        "instruction": "inspect",
    }


def _authority(scope, **extra):
    body = {
        "project_id": scope["project_id"],
        "space_id": scope["space_id"],
        "conversation_id": "conversation-guest",
        "run_id": "run-guest",
        "work_item_id": "work-guest",
        "operation_id": "op-guest",
        "parent_operation_id": "op-parent-guest",
        "agent_id": "agent-guest",
        "request_key": "req-guest",
        "guest_process": {"verified": True, "pid": 4, "evidence_sha256": "ab" * 32},
    }
    body.update(extra)
    return body


def _store_vm(app, project_id, root_dot_id, body):
    control = app._shell_service()
    owner = app._runtime().owner
    VmStore(control, owner)
    with closing(control.store.connect("shell")) as db, db:
        db.execute("DELETE FROM shell_dot_vms WHERE owner=? AND project=? AND root=?",
            (owner, project_id, root_dot_id))
        db.execute(
            "INSERT INTO shell_dot_vms(owner,project,root,cpus,memory_mb,body) VALUES(?,?,?,?,?,?)",
            (owner, project_id, root_dot_id, 1, 512, _encode(body)),
        )


def _credentials_absent(kwargs):
    if any(kwargs.get(key) is not None for key in ("vm_id", "username", "password", "guest_executor")):
        pytest.fail("guest credentials were forwarded without a complete Dot registry")


def _arm(monkeypatch):
    from sentra_executors.guest_execution import VirtualBoxGuestControlExecutor
    from sentra_runtime import dot_tool_dispatch as dispatch_module

    seen = []
    clients = []
    authorities = []

    def capture(control, owner, **kwargs):
        seen.append(kwargs)
        secret = kwargs.get("password") if isinstance(kwargs.get("password"), str) else ""
        placement = kwargs.get("placement") or "host"
        if placement == "guest" and kwargs.get("guest_executor") is None:
            surface = "blocked"
        elif placement == "guest":
            surface = "prepared"
        else:
            surface = placement
        return {
            "status": "uncertain",
            "tool_executed": False,
            "execution_surface": surface,
            "claims_guest_execution": False,
            "claims_success": False,
            "physical_inference": False,
            "fleet_gate": {
                "placement": placement,
                "claims_guest_execution": False,
                "physical_inference": False,
                "detail": secret,
            },
            "receipt": {
                "blocked": surface == "blocked",
                "evidence_source": "guest_executor_missing" if kwargs.get("guest_executor") is None else "not_executed",
                "error": ("boom " + secret) if secret else "blocked",
                "vm_id": kwargs.get("vm_id"),
            },
        }

    class FakeVirtualBoxClient:
        def __init__(self, path=None, runner=None):
            self.calls = []
            clients.append(self)

        def run(self, *parts, **kwargs):
            self.calls.append(tuple(str(part) for part in parts))
            raise AssertionError("guestcontrol must not run")

    real_compose = dispatch_module.compose_dot_tool_dispatch

    def wrapped(control, owner, intent, authority):
        password = authority.get("password")
        authorities.append({
            "vm_id": authority.get("vm_id"),
            "username": authority.get("username"),
            "password_digest": _digest(password) if isinstance(password, str) else None,
            "marker": "marker" in authority,
            "base_folder": "base_folder" in authority,
        })
        return real_compose(control, owner, intent, authority)

    monkeypatch.setattr(dispatch_module, "execute_dot_tool_dispatch", capture)
    monkeypatch.setattr(dispatch_module, "compose_dot_tool_dispatch", wrapped)
    monkeypatch.setattr("sentra_executors.virtualbox_vm.VirtualBoxClient", FakeVirtualBoxClient)
    monkeypatch.setattr(
        "sentra_canvas.dot_tool_runner.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("host execution")),
    )
    prepared = []
    retained = []
    monkeypatch.setattr(
        "orchestrator.providers.fleet_admission.prepare_live_trio",
        lambda **kwargs: prepared.append(kwargs) or {
            "executed": False, "vboxmanage_used": False, "physical_inference": False,
        },
    )
    monkeypatch.setattr(
        "sentra_runtime.dot_tool_dispatch.retain_coordinator_turn",
        lambda *args, **kwargs: retained.append((args, kwargs)) or {
            "status": "not_inference", "physical_inference": False,
        },
    )
    return seen, clients, prepared, retained, authorities, VirtualBoxGuestControlExecutor


def test_guest_compose_reads_the_dot_registry_and_keeps_the_password_out_of_the_result(shell, monkeypatch, caplog):
    app, _server, scope, call = shell
    root = call("dot_create", name="GuestRoot", role="coordinator", model="sentra/test-one")
    child = call("dot_create", name="GuestChild", role="worker", model="sentra/test-one",
        canvas_root_dot_id=root["dot_id"])
    other = call("dot_create", name="GuestOther", role="coordinator", model="sentra/test-one")
    actor = ShellActorService(app._shell_runtime)
    monkeypatch.setattr(actor, "_checkpoint", lambda: None)
    seen, clients, prepared, retained, authorities, executor_type = _arm(monkeypatch)
    caplog.set_level(0)

    missing = _authority(scope, placement="guest")
    blocked = actor.compose(_intent(child["dot_id"]), missing)
    _credentials_absent(seen[-1])
    assert blocked["execution_surface"] == "blocked"
    assert blocked["tool_executed"] is False
    assert blocked["physical_inference"] is False
    assert clients == []
    if "password" in missing:
        pytest.fail("compose wrote the guest password back onto the caller authority")

    _store_vm(app, scope["project_id"], root["dot_id"], {
        "vm_id": VM_ID,
        "username": USERNAME,
        "password": SECRET,
        "marker": "SENTRA-DOT:owned-guest-vm",
        "base_folder": "C:\\dot-vms\\not-public",
        "os_family": "linux",
        "agent_id": root["agent_id"],
    })
    caller = _authority(scope, placement="guest")
    prepared_turn = actor.compose(_intent(child["dot_id"]), caller)
    forwarded = seen[-1]
    assert isinstance(forwarded["guest_executor"], executor_type)
    assert forwarded["guest_executor"].vm_id == VM_ID
    assert forwarded["guest_executor"]._username == USERNAME
    assert _digest(forwarded["guest_executor"]._password) == _digest(SECRET)
    assert forwarded["vm_id"] == VM_ID
    assert forwarded["username"] == USERNAME
    assert _digest(forwarded["password"]) == _digest(SECRET)
    assert authorities[-1]["vm_id"] == VM_ID
    assert authorities[-1]["username"] == USERNAME
    assert authorities[-1]["password_digest"] == _digest(SECRET)
    assert authorities[-1]["marker"] is False
    assert authorities[-1]["base_folder"] is False
    assert forwarded["runner"] is None
    assert FORBIDDEN_VM not in forwarded["vm_id"]
    assert clients and clients[-1].calls == []
    assert all(FORBIDDEN_VM not in part for client in clients for call in client.calls for part in call)
    if "password" in caller:
        pytest.fail("compose wrote the guest password back onto the caller authority")
    _refuse_leak(prepared_turn, SECRET, "compose result")
    _refuse_leak(prepared, SECRET, "trio preparation")
    _refuse_leak(retained, SECRET, "retention")
    _refuse_leak(caplog.text, SECRET, "log")
    assert prepared_turn["physical_inference"] is False
    assert prepared_turn["claims_success"] is False
    assert prepared_turn["fleet_gate"]["claims_guest_execution"] is False

    host = _authority(scope, placement="host")
    host_turn = actor.compose(_intent(child["dot_id"]), host)
    assert seen[-1]["placement"] == "host"
    _credentials_absent(seen[-1])
    assert host_turn["execution_surface"] == "host"
    if "password" in host:
        pytest.fail("compose wrote the guest password back onto the caller authority")

    foreign = actor.compose(_intent(other["dot_id"]), _authority(scope, placement="guest"))
    _credentials_absent(seen[-1])
    assert foreign["execution_surface"] == "blocked"
    _refuse_leak(foreign, SECRET, "foreign dot result")

    _store_vm(app, scope["project_id"], root["dot_id"], {
        "vm_id": VM_ID,
        "password": SECRET,
        "marker": "SENTRA-DOT:owned-guest-vm",
        "base_folder": "C:\\dot-vms\\not-public",
    })
    incomplete = actor.compose(_intent(root["dot_id"]), _authority(scope, placement="guest"))
    _credentials_absent(seen[-1])
    assert incomplete["execution_surface"] == "blocked"
    assert incomplete["tool_executed"] is False
    _refuse_leak(incomplete, SECRET, "incomplete registry result")
    assert clients[-1].calls == []

    assert "retain_coordinator_turn" in ShellActorService.compose.__code__.co_names
    assert "prepare_live_trio" in ShellActorService.compose.__code__.co_names
    assert "_authority_with_dot_vm" in ShellActorService.compose.__code__.co_names


def test_canvas_dispatch_uses_the_dot_vm_when_placement_is_omitted(shell, monkeypatch):
    """A live coordinator authority has no placement. The Dot VM still receives the tool."""
    from orchestrator.providers.fleet_admission import place_execution
    from sentra_quality.production_audit import _refuse_admission_shape

    app, _server, scope, call = shell
    root = call("dot_create", name="CanvasVmRoot", role="coordinator", model="sentra/test-one")
    child = call("dot_create", name="CanvasVmChild", role="worker", model="sentra/test-one",
        canvas_root_dot_id=root["dot_id"])
    actor = ShellActorService(app._shell_runtime)
    monkeypatch.setattr(actor, "_checkpoint", lambda: None)
    seen, clients, _prepared, _retained, _authorities, executor_type = _arm(monkeypatch)
    _store_vm(app, scope["project_id"], root["dot_id"], {
        "vm_id": VM_ID,
        "username": USERNAME,
        "password": SECRET,
        "marker": "SENTRA-DOT:owned-guest-vm",
        "base_folder": "C:\\dot-vms\\not-public",
        "os_family": "linux",
        "agent_id": root["agent_id"],
        "last_project_import": {
            "receipt_state": "SUCCEEDED",
            "guest_path": "/home/sentra/Imports/one/project",
            "host_folder": r"C:\Users\vitor\host-project",
        },
    })
    authority = _authority(scope)
    authority.pop("placement", None)
    turned = actor.compose(_intent(child["dot_id"]), authority)
    forwarded = seen[-1]
    assert forwarded["placement"] == "guest"
    assert forwarded["runner"] is None
    assert forwarded["guest_process"] == {
        "vm_registry_bound": True,
        "vm_id": VM_ID,
        "verified": False,
    }
    assert isinstance(forwarded["guest_executor"], executor_type)
    assert forwarded["guest_executor"].os_family == "linux"
    assert forwarded["os_family"] == "linux"
    assert forwarded["guest_workspace"] == "/home/sentra/Imports/one/project"
    assert SECRET not in forwarded["guest_workspace"]
    assert clients and clients[-1].calls == []
    _refuse_leak(turned, SECRET, "omitted placement result")
    if "password" in authority:
        pytest.fail("compose wrote the guest password back onto the caller authority")
    placed = place_execution("guest", forwarded["guest_process"])
    assert placed["claims_guest_execution"] is False
    assert placed["guest_process_verified"] is False
    assert placed["vm_registry_bound"] is True
    _refuse_admission_shape({"admitted": True, "inference_executed": False, "placement": placed})
    with pytest.raises(PermissionError, match="verified guest process"):
        place_execution("guest", {"verified": False, "pid": 4})
    with pytest.raises(PermissionError, match="vm registry binding is not a guest execution"):
        _refuse_admission_shape({
            "admitted": True,
            "inference_executed": False,
            "placement": {**placed, "claims_guest_execution": True},
        })


def test_another_canvas_vm_is_not_used_for_the_tool(shell, monkeypatch):
    app, _server, scope, call = shell
    root = call("dot_create", name="FamilyRoot", role="coordinator", model="sentra/test-one")
    other = call("dot_create", name="OtherFamily", role="coordinator", model="sentra/test-one")
    conversation = call("conversation_create", dot_id=root["dot_id"])
    actor = ShellActorService(app._shell_runtime)
    monkeypatch.setattr(actor, "_checkpoint", lambda: None)
    seen, clients, _prepared, _retained, _authorities, _executor_type = _arm(monkeypatch)
    other_secret = "other-family-secret-not-for-dispatch"
    _store_vm(app, scope["project_id"], other["dot_id"], {
        "vm_id": "other-family-vm",
        "username": "sentra",
        "password": other_secret,
        "os_family": "linux",
    })
    authority = _authority(scope, conversation_id=conversation["conversation_id"])
    authority.pop("placement", None)
    turned = actor.compose(_intent(other["dot_id"]), authority)
    forwarded = seen[-1]
    assert forwarded["placement"] == "guest"
    _credentials_absent(forwarded)
    assert turned["execution_surface"] == "blocked"
    assert turned["tool_executed"] is False
    _refuse_leak(turned, other_secret, "other family result")
    assert clients == [] or clients[-1].calls == []


def test_guest_dispatch_exception_does_not_carry_the_registry_password(shell, monkeypatch, caplog):
    from sentra_runtime import dot_tool_dispatch as dispatch_module

    app, _server, scope, call = shell
    root = call("dot_create", name="GuestRootExc", role="coordinator", model="sentra/test-one")
    actor = ShellActorService(app._shell_runtime)
    monkeypatch.setattr(actor, "_checkpoint", lambda: None)
    caplog.set_level(0)

    def explode(control, owner, **kwargs):
        secret = kwargs.get("password") if isinstance(kwargs.get("password"), str) else ""
        raise RuntimeError("dispatch failed: " + secret)

    monkeypatch.setattr(dispatch_module, "execute_dot_tool_dispatch", explode)
    monkeypatch.setattr(
        "sentra_executors.virtualbox_vm.VirtualBoxClient",
        type("FakeVirtualBoxClient", (), {
            "__init__": lambda self, path=None, runner=None: None,
            "run": lambda self, *parts, **kwargs: (_ for _ in ()).throw(AssertionError("guestcontrol must not run")),
        }),
    )
    _store_vm(app, scope["project_id"], root["dot_id"], {
        "vm_id": VM_ID,
        "username": USERNAME,
        "password": SECRET,
        "marker": "SENTRA-DOT:owned-guest-vm",
        "base_folder": "C:\\dot-vms\\not-public",
    })
    with pytest.raises(RuntimeError) as caught:
        actor.compose(_intent(root["dot_id"]), _authority(scope, placement="guest"))
    if SECRET in str(caught.value) or SECRET in repr(caught.value):
        pytest.fail("guest password leaked into the exception")
    if SECRET in caplog.text:
        pytest.fail("guest password leaked into the log")
