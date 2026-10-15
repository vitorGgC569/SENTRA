import json
from sentra_canvas.dot_tool_runner import build_dispatch_prompt, verify_receipt


def receipt(tool, text, info):
    return verify_receipt(tool, text, '', 0, info, 'own-operation', 'own-work', 'own-request')


def test_boolean_exit_code_is_not_a_verified_inference():
    from sentra_canvas.dot_tool_runner import verify_receipt
    _, info = build_dispatch_prompt("Sem arquivos, responda o desafio.", "NONCE_5fc782a")
    answer = "REVERSE_NONCE=" + info["reverse"]
    refused = verify_receipt("sentra-cli", answer, "", False, info, "own-operation", "own-work", "own-request")
    assert refused["verified"] is False
    assert receipt("sentra-cli", answer, info)["verified"] is True


def test_echoing_the_entire_dispatched_prompt_is_not_inference():
    prompt, info = build_dispatch_prompt('Sem arquivos, responda o desafio.', 'NONCE_5fc782a')
    assert info['reverse'] not in prompt and info['sha256'] not in prompt
    result = receipt('sentra-cli', prompt, info)
    assert result['verified'] is False and result['echo_only_detected'] is True


def test_opencode_user_event_cannot_impersonate_assistant_output():
    _, info = build_dispatch_prompt('Teste', 'NONCE_5fc782a')
    answer = 'REVERSE_NONCE=' + info['reverse']
    echoed = json.dumps({'type': 'user', 'part': {'type': 'text', 'text': answer}})
    assert receipt('opencode', echoed, info)['verified'] is False
    assistant = json.dumps({'type': 'text', 'part': {'type': 'text', 'text': answer}})
    assert receipt('opencode', assistant, info)['verified'] is True


def test_guest_placement_does_not_run_on_the_host_without_a_proven_executor(tmp_path, monkeypatch):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool

    def boom(*_args, **_kwargs):
        raise AssertionError("host execution")

    monkeypatch.setattr("sentra_canvas.dot_tool_runner.subprocess.run", boom)
    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-block",
        placement="guest",
        guest_executor={"verified": True, "pid": 4242, "evidence_sha256": "a" * 64},
        runner=boom,
    )
    assert receipt["blocked"] is True
    assert receipt["execution_uncertain"] is True
    assert receipt["execution_surface"] == "blocked"
    assert receipt["claims_guest_execution"] is False
    assert receipt["host_subprocess"] is False
    assert receipt["guest_executor_used"] is False
    assert receipt["verified"] is False
    assert receipt["launch_failed"] is False
    assert receipt["automatic_retry"] is False


def test_injected_guest_executor_is_called_and_the_receipt_is_not_host(tmp_path, monkeypatch):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool
    from sentra_executors.guest_execution import InjectableGuestExecutor

    def boom(*_args, **_kwargs):
        raise AssertionError("host execution")

    monkeypatch.setattr("sentra_canvas.dot_tool_runner.subprocess.run", boom)

    def answer(request):
        assert request["placement"] == "guest"
        assert request["tool"] == "sentra-cli"
        info = request["nonce_info"]
        return {"exit_code": 0, "stdout": "REVERSE_NONCE=" + info["reverse"], "stderr": ""}

    guest = InjectableGuestExecutor(answer)
    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-run",
        placement="guest", guest_executor=guest, runner=boom,
    )
    assert len(guest.calls) == 1
    assert receipt["execution_surface"] == "guest"
    assert receipt["claims_guest_execution"] is True
    assert receipt["host_subprocess"] is False
    assert receipt["guest_executor_used"] is True
    assert receipt["verified"] is True
    assert receipt["blocked"] is False


def test_refused_guest_workspace_does_not_count_as_execution(tmp_path):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool
    from sentra_executors.guest_execution import VirtualBoxGuestControlExecutor

    class Client:
        def run(self, *parts, **kwargs):
            raise AssertionError("guestcontrol ran after a refusal")

    guest = VirtualBoxGuestControlExecutor(
        Client(), vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-refuse",
        placement="guest", guest_executor=guest,
        guest_workspace="/etc/passwd",
    )
    assert receipt["blocked"] is True
    assert receipt["execution_surface"] == "blocked"
    assert receipt["claims_guest_execution"] is False
    assert receipt["guest_executor_used"] is False
    assert receipt["host_subprocess"] is False
    assert receipt["verified"] is False
    assert receipt["execution_uncertain"] is True
    assert receipt["automatic_retry"] is False
    assert "Dot home" in receipt["error"]


def test_guest_tool_receives_the_imported_folder_and_not_the_host_path(tmp_path):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool
    from sentra_executors.guest_execution import InjectableGuestExecutor

    def answer(request):
        info = request["nonce_info"]
        return {"exit_code": 0, "stdout": "REVERSE_NONCE=" + info["reverse"], "stderr": ""}

    guest = InjectableGuestExecutor(answer)
    imported = "/home/sentra/Imports/one/project"
    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-folder",
        placement="guest", guest_executor=guest, guest_workspace=imported,
    )
    assert guest.calls[0]["guest_workspace"] == imported
    assert str(tmp_path) not in guest.calls[0]["guest_workspace"]
    assert "workspace" not in guest.calls[0]
    assert receipt["verified"] is True
    assert receipt["execution_surface"] == "guest"

    same_host = InjectableGuestExecutor(answer)
    execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-host-path",
        placement="guest", guest_executor=same_host, guest_workspace=str(tmp_path),
    )
    assert "guest_workspace" not in same_host.calls[0]


def test_refused_guest_workspace_does_not_count_as_execution(tmp_path):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool
    from sentra_executors.guest_execution import VirtualBoxGuestControlExecutor

    class Client:
        def run(self, *parts, **kwargs):
            raise AssertionError("guestcontrol ran for a refused workspace")

    guest = VirtualBoxGuestControlExecutor(
        Client(), vm_id="owned-guest-vm", username="dotuser", password="dot-secret",
    )
    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-outside",
        placement="guest", guest_executor=guest, guest_workspace="/home/sentra/Imports/one",
    )
    assert receipt["blocked"] is True
    assert receipt["guest_executor_used"] is False
    assert receipt["claims_guest_execution"] is False
    assert receipt["execution_uncertain"] is True
    assert receipt["automatic_retry"] is False
    assert receipt["execution_surface"] == "blocked"
    assert receipt["verified"] is False


def test_guest_surface_without_a_guest_claim_is_not_success(tmp_path):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool

    class Bare:
        proven_guest = True
        execution_surface = "guest"

        def execute(self, request):
            info = request["nonce_info"]
            return {
                "exit_code": 0,
                "stdout": "REVERSE_NONCE=" + info["reverse"],
                "stderr": "",
                "execution_surface": "guest",
                "host_subprocess": False,
                "claims_guest_execution": False,
            }

    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-unclaimed",
        placement="guest", guest_executor=Bare(),
    )
    assert receipt["claims_guest_execution"] is False
    assert receipt["verified"] is False
    assert receipt["blocked"] is True
    assert receipt["execution_uncertain"] is True
    assert receipt["automatic_retry"] is False


def test_uncertain_guest_result_is_not_a_verified_tool(tmp_path):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool

    class Uncertain:
        proven_guest = True
        execution_surface = "guest"

        def execute(self, request):
            return {
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "execution_surface": "guest",
                "host_subprocess": False,
                "claims_guest_execution": True,
                "execution_uncertain": True,
            }

    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-uncertain",
        placement="guest", guest_executor=Uncertain(),
    )
    assert receipt["claims_guest_execution"] is False
    assert receipt["verified"] is False
    assert receipt["execution_uncertain"] is True
    assert receipt["automatic_retry"] is False


def test_guest_tool_without_a_guest_result_does_not_claim_success(tmp_path):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool

    class Bare:
        proven_guest = True
        execution_surface = "guest"

        def execute(self, request):
            info = request["nonce_info"]
            return {"exit_code": 0, "stdout": "REVERSE_NONCE=" + info["reverse"], "stderr": ""}

    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-unproven",
        placement="guest", guest_executor=Bare(),
    )
    assert receipt["claims_guest_execution"] is False
    assert receipt["verified"] is False
    assert receipt["blocked"] is True
    assert receipt["execution_uncertain"] is True
    assert receipt["automatic_retry"] is False
    assert receipt["execution_surface"] == "blocked"
    assert receipt["host_subprocess"] is False


def test_host_runner_stays_on_the_host_even_if_a_guest_executor_is_present(tmp_path):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool
    from sentra_executors.guest_execution import InjectableGuestExecutor

    guest = InjectableGuestExecutor(lambda _request: {"exit_code": 0, "stdout": "nope", "stderr": ""})

    def host_runner(_argv, _prompt, info):
        return (0, "REVERSE_NONCE=" + info["reverse"], "")

    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-host", "wi-host", "req-host-run",
        placement="host", runner=host_runner, guest_executor=guest,
    )
    assert guest.calls == []
    assert receipt["execution_surface"] == "host"
    assert receipt["claims_guest_execution"] is False
    assert receipt["host_subprocess"] is False
    assert receipt["guest_executor_used"] is False
    assert receipt["verified"] is True


def test_compose_forwards_guest_authority_and_drops_the_host_runner(monkeypatch):
    from sentra_runtime import dot_tool_dispatch as module
    from sentra_executors.guest_execution import InjectableGuestExecutor

    seen = {}

    def capture(control, owner, **kwargs):
        seen.update(kwargs)
        return {"status": "captured"}

    monkeypatch.setattr(module, "execute_dot_tool_dispatch", capture)
    guest = InjectableGuestExecutor(lambda request: {"exit_code": 0, "stdout": "", "stderr": ""})
    host_runner = lambda *_args: None
    module.compose_dot_tool_dispatch(
        None, "owner",
        {"kind": "dot_tool_dispatch", "tool": "sentra-cli", "runner": host_runner, "target_dot_id": "dot"},
        {
            "project_id": "p", "conversation_id": "c", "run_id": "r", "work_item_id": "w",
            "parent_operation_id": "op-parent", "agent_id": "agent", "operation_id": "op-parent",
            "placement": "guest",
            "guest_process": {"verified": True, "pid": 4, "evidence_sha256": "ab" * 32},
            "guest_executor": guest,
        },
    )
    assert seen["placement"] == "guest"
    assert seen["runner"] is None
    assert seen["guest_executor"] is guest
    assert seen["guest_process"]["pid"] == 4
    module.compose_dot_tool_dispatch(
        None, "owner",
        {"kind": "dot_tool_dispatch", "tool": "sentra-cli", "runner": host_runner, "target_dot_id": "dot"},
        {
            "project_id": "p", "conversation_id": "c", "run_id": "r", "work_item_id": "w",
            "parent_operation_id": "op-parent", "agent_id": "agent", "operation_id": "op-parent",
        },
    )
    assert seen["placement"] == "host"
    assert seen["runner"] is host_runner
    assert seen["guest_executor"] is None


def test_production_guestcontrol_executor_does_not_run_on_the_host(tmp_path, monkeypatch):
    from sentra_canvas.dot_tool_runner import execute_non_interactive_tool
    from sentra_executors.guest_execution import VirtualBoxGuestControlExecutor

    def boom(*_args, **_kwargs):
        raise AssertionError("host execution")

    monkeypatch.setattr("sentra_canvas.dot_tool_runner.subprocess.run", boom)

    class FakeClient:
        def __init__(self):
            self.calls = []

        def run(self, *parts, **kwargs):
            assert parts[0] == "guestcontrol"
            assert parts[1] == "owned-guest-vm"
            assert "SENTRA-Dot-b1a7b4555800414f" not in parts
            self.calls.append((parts, kwargs))
            return "guestcontrol-stdout"

    client = FakeClient()
    guest = VirtualBoxGuestControlExecutor(
        client, vm_id="owned-guest-vm", username="sentra", password="dot-secret",
    )
    receipt = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-vbox",
        placement="guest", guest_executor=guest, runner=boom,
    )
    assert len(client.calls) == 1
    assert receipt["execution_surface"] == "guest"
    assert receipt["claims_guest_execution"] is True
    assert receipt["host_subprocess"] is False
    assert receipt["guest_executor_used"] is True
    assert receipt["guest_witness"] == "guestcontrol"
    assert receipt["vm_id"] == "owned-guest-vm"
    assert receipt["verified"] is False
    assert receipt["blocked"] is False
    command = client.calls[0][0][-1]
    assert str(tmp_path) not in command
    assert "/home/sentra" in command
    assert "SENTRA-Dot-b1a7b4555800414f" not in command

    client.guest_additions_runlevel = lambda vm_id: "0"
    refused = execute_non_interactive_tool(
        tmp_path, tmp_path, "sentra-cli", "inspect", "op-guest", "wi-guest", "req-guest-windows",
        placement="guest", guest_executor=guest, runner=boom,
    )
    assert len(client.calls) == 1
    assert refused["blocked"] is True
    assert refused["execution_surface"] == "blocked"
    assert refused["claims_guest_execution"] is False
    assert refused["host_subprocess"] is False
    assert refused["guest_executor_used"] is False
    assert refused["verified"] is False


def test_compose_builds_guestcontrol_executor_only_with_dot_credentials(monkeypatch):
    from sentra_runtime import dot_tool_dispatch as module
    from sentra_executors.guest_execution import VirtualBoxGuestControlExecutor

    seen = {}

    def capture(control, owner, **kwargs):
        seen.update(kwargs)
        return {"status": "captured"}

    monkeypatch.setattr(module, "execute_dot_tool_dispatch", capture)

    class FakeClient:
        def run(self, *parts, **kwargs):
            raise AssertionError("compose must not call guestcontrol")

    host_runner = lambda *_args: None
    client = FakeClient()
    module.compose_dot_tool_dispatch(
        None, "owner",
        {"kind": "dot_tool_dispatch", "tool": "sentra-cli", "runner": host_runner, "target_dot_id": "dot"},
        {
            "project_id": "p", "conversation_id": "c", "run_id": "r", "work_item_id": "w",
            "parent_operation_id": "op-parent", "agent_id": "agent", "operation_id": "op-parent",
            "placement": "guest",
            "guest_process": {"verified": True, "pid": 4, "evidence_sha256": "ab" * 32},
        },
    )
    assert seen["runner"] is None
    assert seen["guest_executor"] is None
    assert seen["vm_id"] is None
    module.compose_dot_tool_dispatch(
        None, "owner",
        {"kind": "dot_tool_dispatch", "tool": "sentra-cli", "runner": host_runner, "target_dot_id": "dot"},
        {
            "project_id": "p", "conversation_id": "c", "run_id": "r", "work_item_id": "w",
            "parent_operation_id": "op-parent", "agent_id": "agent", "operation_id": "op-parent",
            "placement": "guest",
            "vm_id": "owned-guest-vm",
            "username": "sentra",
            "password": "dot-secret",
            "virtualbox_client": client,
            "guest_process": {"verified": True, "pid": 4, "evidence_sha256": "ab" * 32},
        },
    )
    assert seen["runner"] is None
    assert isinstance(seen["guest_executor"], VirtualBoxGuestControlExecutor)
    assert seen["guest_executor"].vm_id == "owned-guest-vm"
    assert seen["vm_id"] == "owned-guest-vm"
    assert seen["username"] == "sentra"
    assert seen["password"] == "dot-secret"
    assert seen["virtualbox_client"] is client

    class UnreadyClient:
        def guest_additions_runlevel(self, vm_id):
            return "0"

        def run(self, *parts, **kwargs):
            raise AssertionError("compose must not call guestcontrol")

    module.compose_dot_tool_dispatch(
        None, "owner",
        {"kind": "dot_tool_dispatch", "tool": "sentra-cli", "runner": host_runner, "target_dot_id": "dot"},
        {
            "project_id": "p", "conversation_id": "c", "run_id": "r", "work_item_id": "w",
            "parent_operation_id": "op-parent", "agent_id": "agent", "operation_id": "op-parent",
            "placement": "guest",
            "vm_id": "owned-guest-vm",
            "username": "sentra",
            "password": "dot-secret",
            "os_family": "windows",
            "virtualbox_client": UnreadyClient(),
            "guest_process": {"verified": True, "pid": 4, "evidence_sha256": "ab" * 32},
        },
    )
    assert seen["runner"] is None
    assert seen["guest_executor"] is None


def test_codex_uncompleted_agent_item_is_not_final_evidence():
    _, info = build_dispatch_prompt('Teste', 'NONCE_5fc782a')
    item = {'type': 'agent_message', 'text': 'REVERSE_NONCE=' + info['reverse']}
    assert receipt('codex', json.dumps({'type': 'item.started', 'item': item}), info)['verified'] is False
    assert receipt('codex', json.dumps({'type': 'item.completed', 'item': item}), info)['verified'] is True
