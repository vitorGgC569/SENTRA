"""Provider-bound model selection and live Codex effort controls."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from rich.console import Console

from sentra_cli.__main__ import parse_args
from sentra_cli.config import CLIConfig
from sentra_cli.repl import SentraREPL
from sentra_cli.codex_native import generate, NativeModelError


def make_repl(tmp_path,model="sentra/codex/current",effort="low",models=None):
    config=CLIConfig(workspace=tmp_path,state_root=tmp_path/".state",
                     model=model,reasoning_effort=effort,openai_api_key="none")
    repl=SentraREPL.__new__(SentraREPL)
    repl.config=config
    repl.console=Console(record=True,force_terminal=False,width=130)
    def list_models():
        return models if models is not None else ["sentra/codex/current","sentra/chatgpt-web/high"]
    client=SimpleNamespace(active_model=model,list_models=list_models)
    repl.agent=SimpleNamespace(client=client)
    return repl


def test_native_model_switch_ignores_gateway_catalog(tmp_path,monkeypatch):
    repl=make_repl(tmp_path,model="sentra/chatgpt-web/high",models=["sentra/chatgpt-web/high"])
    monkeypatch.setattr("sentra_cli.codex_native.authenticated",lambda:True)
    assert repl.handle_slash_command("/model sentra/codex/current")
    assert repl.config.model=="sentra/codex/current"
    assert repl.agent.client.active_model=="sentra/codex/current"
    assert repl.handle_slash_command("/model sentra/codex/gpt-5.5-codex")
    assert repl.config.model=="sentra/codex/gpt-5.5-codex"
    assert "validates" in repl.console.export_text()


def test_invalid_or_unavailable_model_never_changes_selection(tmp_path,monkeypatch):
    repl=make_repl(tmp_path)
    monkeypatch.setattr("sentra_cli.codex_native.authenticated",lambda:False)
    for choice in ("sentra/codex/current","sentra/codex/../unsafe","other/invalid"):
        assert repl.handle_slash_command("/model "+choice)
    assert repl.config.model=="sentra/codex/current"
    repl=make_repl(tmp_path,model="sentra/chatgpt-web/high")
    assert repl.handle_slash_command("/model unlisted-model")
    assert repl.config.model=="sentra/chatgpt-web/high"


def test_effort_changes_only_when_valid(tmp_path):
    repl=make_repl(tmp_path)
    assert repl.handle_slash_command("/effort")
    assert "low" in repl.console.export_text()
    for effort in ("medium","high","xhigh","low"):
        assert repl.handle_slash_command("/effort "+effort)
        assert repl.config.reasoning_effort==effort
    repl.handle_slash_command("/effort speculative")
    assert repl.config.reasoning_effort=="low"
    web=make_repl(tmp_path,model="sentra/chatgpt-web/high")
    web.handle_slash_command("/effort high")
    assert "Codex turns only" in web.console.export_text()
    assert "does not use" in web._effort_label()


def test_effort_cli_argument_and_bad_config(tmp_path):
    assert parse_args(["--effort","high"]).effort=="high"
    with pytest.raises(SystemExit):
        parse_args(["--effort","secret"])
    with pytest.raises(ValueError,match="reasoning effort"):
        CLIConfig(workspace=tmp_path,reasoning_effort="high;evil")


def test_native_codex_command_uses_selected_effort_and_model(tmp_path,monkeypatch):
    import sentra_cli.codex_native as native
    result=b"\n".join([
        json.dumps({"type":"thread.started","thread_id":"thread-ok"}).encode(),
        json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"OK"}}).encode(),
        json.dumps({"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":2}}).encode(),
    ])
    captured=[]
    class FakeProcess:
        returncode=0
        def __init__(self,argv,**kwargs):
            captured.append(argv)
        def communicate(self,input=None,timeout=None):
            return result,b""
        def terminate_tree(self):
            raise AssertionError("Should not terminate successful call")
    monkeypatch.setattr(native,"TaskProcess",FakeProcess)
    monkeypatch.setattr(native,"find_cli",lambda:tmp_path/"codex.exe")
    monkeypatch.setattr(native,"authenticated",lambda:True)
    config=CLIConfig(workspace=tmp_path,state_root=tmp_path/".state",
                     model="sentra/codex/current",reasoning_effort="xhigh")
    events=[]
    output=generate(config,[{"role":"user","content":"ping"}],
                    "sentra/codex/current",lambda *x:events.append(x))
    assert output=="OK"
    assert 'model_reasoning_effort="xhigh"' in captured[0]
    assert "--model" not in captured[0]
    assert ("codex-cli",events[0][1],"completed") in events
    config.reasoning_effort="medium"
    generate(config,[{"role":"user","content":"ping"}],
             "sentra/codex/gpt-5.5-codex",lambda *x:None)
    assert 'model_reasoning_effort="medium"' in captured[1]
    assert captured[1][captured[1].index("--model")+1]=="gpt-5.5-codex"
    config.reasoning_effort="invalid"
    with pytest.raises(NativeModelError,match="unsupported"):
        generate(config,[],config.model,lambda *x:None)
