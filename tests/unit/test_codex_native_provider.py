import json
from pathlib import Path

import pytest

from sentra_cli.codex_native import parse_response,NativeModelError
from sentra_cli.client import ModelClient
from sentra_cli.config import CLIConfig


def test_native_model_is_default_only_without_an_explicit_choice(tmp_path,monkeypatch):
    from sentra_cli.__main__ import parse_args
    monkeypatch.delenv("SENTRA_CLI_MODEL",raising=False)
    monkeypatch.setattr("sentra_cli.codex_native.authenticated",lambda:True)
    assert CLIConfig(workspace=tmp_path).model=="sentra/codex/current"
    assert parse_args([]).model=="sentra/codex/current"
    assert parse_args(["--model","sentra/gemini-web/flash"]).model=="sentra/gemini-web/flash"
    monkeypatch.setenv("SENTRA_CLI_MODEL","sentra/chatgpt-web/high")
    assert CLIConfig(workspace=tmp_path).model=="sentra/chatgpt-web/high"
    assert parse_args([]).model=="sentra/chatgpt-web/high"
    monkeypatch.delenv("SENTRA_CLI_MODEL")
    monkeypatch.setattr("sentra_cli.codex_native.authenticated",lambda:False)
    assert CLIConfig(workspace=tmp_path).model=="sentra/chatgpt-web/auto"

def test_saved_model_beats_native_default_but_not_explicit_model(tmp_path,monkeypatch):
    from sentra_remote.product import ProductSettings
    from sentra_cli.__main__ import parse_args
    monkeypatch.delenv("SENTRA_CLI_MODEL",raising=False)
    monkeypatch.setattr("sentra_cli.codex_native.authenticated",lambda:True)
    state=tmp_path/"state"
    preferred="sentra/gemini-web/pro"
    ProductSettings(web_model_name=preferred).save(state/"desktop.json")
    assert CLIConfig(workspace=tmp_path,state_root=state).model==preferred
    assert parse_args(["--state-dir",str(state)]).model==preferred
    assert CLIConfig(workspace=tmp_path,state_root=state,model="sentra/codex/current").model=="sentra/codex/current"
    assert parse_args(["--state-dir",str(state),"--model","sentra/codex/current"]).model=="sentra/codex/current"
    monkeypatch.setenv("SENTRA_CLI_MODEL","sentra/chatgpt-web/high")
    assert CLIConfig(workspace=tmp_path,state_root=state).model=="sentra/chatgpt-web/high"
    assert parse_args(["--state-dir",str(state)]).model=="sentra/chatgpt-web/high"


def encoded(*events):return b"\n".join(json.dumps(event).encode() for event in events)


def test_only_completed_native_agent_message_is_accepted():
    text,thread,usage=parse_response(encoded(
        {"type":"thread.started","thread_id":"actual-native-thread"},
        {"type":"item.completed","item":{"type":"agent_message","text":"[[W|file.txt|value]]"}},
        {"type":"turn.completed","usage":{"input_tokens":42,"output_tokens":7,"private":"excluded"}},
    ),0)
    assert text=="[[W|file.txt|value]]" and thread=="actual-native-thread"
    assert usage=={"input_tokens":42,"output_tokens":7}


@pytest.mark.parametrize("data,code",[
    (encoded({"type":"item.completed","item":{"type":"agent_message","text":"[[W|effect|partial]]"}}),0),
    (encoded({"type":"turn.failed"}),1),
    (encoded({"type":"item.completed","item":{"type":"command_execution","command":"write"}}),0),
    (encoded({"type":"turn.completed"},{"type":"item.completed","item":{"type":"agent_message","text":"late"}}),0),
    (b"invalid json",0),
])
def test_native_partial_failure_or_native_tool_never_becomes_a_response(data,code):
    with pytest.raises((NativeModelError,ValueError)):parse_response(data,code)


def test_explicit_native_selection_never_contacts_gateway_or_api_fallback(tmp_path,monkeypatch):
    client=ModelClient(CLIConfig(workspace=tmp_path,model="sentra/codex/current",auto_start_gateway=False,state_root=tmp_path/"state"))
    monkeypatch.setattr(client,"probe_health",lambda:pytest.fail("native model must not probe Web/API transports"))
    calls=[]
    def generate(config,messages,model,delivery,**kwargs):
        calls.append(model);delivery("codex-cli","fixture-turn","submitted")
        delivery("codex-cli","fixture-turn","uncertain")
        raise NativeModelError("lost native response")
    monkeypatch.setattr("sentra_cli.codex_native.generate",generate)
    assert "not replayed automatically" in "".join(client.chat_stream([]))
    assert calls==["sentra/codex/current"] and client.last_delivery_state=="uncertain" and client.last_error
