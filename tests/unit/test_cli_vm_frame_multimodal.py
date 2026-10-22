import base64
import json
from types import SimpleNamespace

import pytest

from sentra_cli.agent import SentraAgent
from sentra_cli.client import ModelClient


# A tiny byte sequence with a PNG signature is enough here: validation is about
# the authenticated transport envelope and format signature, not image decoding.
PNG = b"\x89PNG\r\n\x1a\n" + b"test-image-bytes"
ENCODED = base64.b64encode(PNG).decode("ascii")


def _receipt(*, state="SUCCEEDED", transport="virtualbox-com-framebuffer", verified=True):
    return {
        "operation_id": "op-vm-frame-1",
        "state": state,
        "evidence": {
            "vm_id": "vm-authenticated-1",
            "image_base64": ENCODED,
            "mime_type": "image/png",
            "width": 64,
            "height": 48,
            "transport": transport,
            "desktop_verified": verified,
        },
    }


def _frame_request(capability="vm:observe", action="frame"):
    return "machine_execute|" + json.dumps({
        "capability_id": capability,
        "arguments": {"action": action},
    })


def test_only_successful_authorized_virtualbox_frame_becomes_ephemeral_image():
    raw = SentraAgent._machine_receipt(json.dumps(_receipt()))
    safe, frame = SentraAgent._model_machine_result("CANVAS", _frame_request(), raw, "call-1")

    assert frame == {
        "mime_type": "image/png", "data_base64": ENCODED,
        "vm_id": "vm-authenticated-1", "width": 64, "height": 48,
    }
    assert ENCODED not in safe
    assert '"frame_available": true' in safe
    assert "[SENTRA_VM_FRAME call_id=call-1]" in safe
    assert '"desktop_verified": false' in safe
    assert '"installed_os_verified": false' in safe


def test_framebuffer_proof_accepts_setup_image_without_claiming_installed_desktop():
    value = _receipt()
    value['evidence'].update(framebuffer_verified=True, desktop_verified=False, installed_os_verified=False)
    safe, frame = SentraAgent._model_machine_result('CANVAS', _frame_request(), json.dumps(value), 'call-setup')
    assert frame is not None
    assert '"framebuffer_verified": true' in safe
    assert '"desktop_verified": false' in safe
    value['evidence'].update(framebuffer_verified=False, desktop_verified=True)
    assert SentraAgent._model_machine_result('CANVAS', _frame_request(), json.dumps(value), 'call-invalid')[1] is None


def test_virtualbox_capture_proves_framebuffer_only_even_with_valid_png():
    from contextlib import contextmanager
    from sentra_executors.virtualbox_vm import VirtualBoxClient, VirtualBoxBinding
    display = SimpleNamespace(GetScreenResolution=lambda _: (1024, 768), TakeScreenShotToArray=lambda *_: PNG)
    @contextmanager
    def console(_):
        yield SimpleNamespace(Display=display)
    client = VirtualBoxClient(path='synthetic-no-execution')
    client.console = console
    evidence = client.frame(VirtualBoxBinding('owned-vm', 'owned-marker', lambda: {}))
    assert evidence['framebuffer_verified'] is True
    assert evidence['desktop_verified'] is evidence['installed_os_verified'] is False


@pytest.mark.parametrize("result,request_args", [
    (_receipt(state="FAILED"), _frame_request()),
    (_receipt(transport="other-provider"), _frame_request()),
    (_receipt(verified=False), _frame_request()),
    (_receipt(), _frame_request(capability="vm:manage")),
    (_receipt(), _frame_request(action="status")),
])
def test_invalid_or_failed_frame_is_redacted_and_never_attached(result, request_args):
    safe, frame = SentraAgent._model_machine_result(
        "CANVAS", request_args, json.dumps(result), "call-2")
    assert frame is None
    assert ENCODED not in safe
    assert "redacted image payload" in safe


def test_observed_frame_must_match_exact_operation_receipt():
    payload = SentraAgent._machine_receipt(json.dumps(_receipt()))
    observed = payload
    _, good = SentraAgent._model_machine_result(
        "CANVAS", "machine_observe|op-vm-frame-1", observed, "call-3")
    _, wrong = SentraAgent._model_machine_result(
        "CANVAS", "machine_observe|some-other-operation", observed, "call-4")
    assert good is not None
    assert wrong is None


def test_native_responses_sends_png_as_input_image_and_keeps_text_separate():
    client = ModelClient.__new__(ModelClient)
    client.config = SimpleNamespace(workspace="C:/workspace")
    client._session_id = "session"
    message = {"role": "user", "id": "msg1", "content": "Inspect this VM screen.",
               "images": [{"mime_type": "image/png", "data_base64": ENCODED}]}
    request = client._native_responses_input([message], "turn")
    projected = next(item for item in request if item.get("id") == "msg_msg1")
    assert projected["content"][0] == {"type": "input_text", "text": "Inspect this VM screen."}
    assert projected["content"][1]["type"] == "input_image"
    assert projected["content"][1]["image_url"] == "data:image/png;base64," + ENCODED
    assert ENCODED not in projected["content"][0]["text"]


def test_native_responses_rejects_malformed_image_payload():
    client = ModelClient.__new__(ModelClient)
    client.config = SimpleNamespace(workspace="C:/workspace")
    client._session_id = "session"
    message = {"role": "user", "content": "Inspect.",
               "images": [{"mime_type": "image/png", "data_base64": "not-base64"}]}
    with pytest.raises(ValueError, match="malformed model image payload"):
        client._native_responses_input([message], "turn")


def test_agent_attaches_only_the_latest_validated_frame_to_its_tool_observation():
    agent = SentraAgent.__new__(SentraAgent)
    agent._vm_frame = ("call-latest", {
        "mime_type": "image/png", "data_base64": ENCODED,
        "vm_id": "vm-authenticated-1", "width": 64, "height": 48,
    })
    messages = [
        {"role": "user", "content": "[SENTRA_VM_FRAME call_id=call-old] old"},
        {"role": "user", "content": "[SENTRA_VM_FRAME call_id=call-latest] latest"},
    ]
    agent._attach_vm_frame(messages)
    assert "images" not in messages[0]
    assert messages[1]["images"] == [{"mime_type": "image/png", "data_base64": ENCODED}]


def test_codex_cli_provider_does_not_silently_drop_vm_images():
    client = ModelClient.__new__(ModelClient)
    client.config = SimpleNamespace(model="sentra/codex/current")
    client.last_error = None
    client.last_delivery_state = None
    client._provider_admission_error = None
    output = "".join(client._chat_stream([
        {"role": "user", "content": "Inspect.", "images": [{"mime_type": "image/png", "data_base64": ENCODED}]}
    ]))
    assert "cannot receive" in output
    assert client.last_delivery_state == "not_submitted"
    assert ENCODED not in output

def test_vm_frame_directive_delivers_authenticated_png_without_exposing_base64():
    from sentra_cli.canvas import CanvasBridge
    agent = SentraAgent.__new__(SentraAgent)
    good = json.dumps(_receipt())
    safe, frame = SentraAgent._model_machine_result("CANVAS", "vm_frame", good, "qa-vm-frame")
    assert frame and frame["data_base64"] == ENCODED
    assert ENCODED not in safe
    assert "frame_available" in safe
    bridge = CanvasBridge.__new__(CanvasBridge)
    bridge.is_available = True
    bridge.is_shell_scope = False
    bridge.workspace = "C:/authorized"
    collected = []
    bridge._request = lambda body: collected.append(body) or {"state":"SUCCEEDED"}
    bridge.execute("vm_frame","original-qa-identity")
    assert collected[0] == {"action":"vm_frame","workspace":"C:/authorized"}


def test_vm_input_has_scoped_canonical_arguments_and_persistent_identity():
    from sentra_cli.canvas import CanvasBridge
    bridge = CanvasBridge.__new__(CanvasBridge)
    bridge.is_available = True
    bridge.is_shell_scope = False
    bridge.workspace = "C:/authorized"
    collected = []
    bridge._request = lambda body: collected.append(body) or {"state":"SUCCEEDED"}
    result = bridge.execute('vm_input|{"action":"input.key","scancodes":[28,156]}',"original-call-1")
    assert json.loads(result)["state"] == "SUCCEEDED"
    assert collected[0]["request_key"] == "original-call-1"
    assert "machine_id" not in collected[0] and "work_item_id" not in collected[0]
    with pytest.raises(ValueError):
        bridge.execute('vm_input|{"action":"input.key","vm_id":"foreign"}',"call-2")
