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
    assert "capabilities unavailable" in web.console.export_text()
    assert web.config.web_reasoning_effort is None
    web.agent.client.supported_efforts = lambda model: ["medium", "high"]
    web.handle_slash_command("/effort high")
    assert web.config.web_reasoning_effort == "high"
    assert "physical confirmation" in web._effort_label()
    web.handle_slash_command("/effort xhigh")
    assert web.config.web_reasoning_effort == "high"


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



def test_model_command_opens_numbered_interactive_selector_and_switches_web(tmp_path, monkeypatch):
    repl = make_repl(tmp_path, models=[
        "sentra/codex/current", "sentra/chatgpt-web/high", "sentra/chatgpt-web/high"
    ])
    monkeypatch.setattr("sentra_cli.codex_native.authenticated", lambda: True)
    monkeypatch.setattr(repl.console, "input", lambda prompt: "2")
    assert repl.handle_slash_command("/model")
    assert repl.config.model == "sentra/chatgpt-web/high"
    assert repl.agent.client.active_model == repl.config.model
    display = repl.console.export_text()
    assert "Selecionar modelo" in display
    assert "1" in display and "2" in display
    assert "Model selected" in display
    assert display.count("sentra/chatgpt-web/high") >= 1


@pytest.mark.parametrize("selection", ("", "0", "q", "99", "-1", "abc", "1;bad"))
def test_model_selector_cancel_or_bad_choice_never_mutates(tmp_path, monkeypatch, selection):
    repl = make_repl(tmp_path, model="sentra/codex/current")
    monkeypatch.setattr("sentra_cli.codex_native.authenticated", lambda: True)
    monkeypatch.setattr(repl.console, "input", lambda prompt: selection)
    assert repl.handle_slash_command("/model")
    assert repl.config.model == "sentra/codex/current"
    assert repl.agent.client.active_model == "sentra/codex/current"


def test_model_selector_does_not_select_unauthenticated_native_model(tmp_path, monkeypatch):
    repl = make_repl(tmp_path, model="sentra/chatgpt-web/high",
                     models=["sentra/codex/current", "sentra/chatgpt-web/high"])
    monkeypatch.setattr("sentra_cli.codex_native.authenticated", lambda: False)
    monkeypatch.setattr(repl.console, "input", lambda prompt: "1")
    repl.handle_slash_command("/model")
    assert repl.config.model == "sentra/chatgpt-web/high"
    assert "not authenticated" in repl.console.export_text()


def test_model_selector_missing_catalog_is_noninteractive_and_preserves_state(tmp_path, monkeypatch):
    repl = make_repl(tmp_path, model="sentra/chatgpt-web/high")
    def offline():
        raise OSError("gateway unreachable")
    repl.agent.client.list_models = offline
    monkeypatch.setattr(repl.console, "input", lambda prompt: (_ for _ in ()).throw(
        AssertionError("must not prompt when no models available")))
    repl.handle_slash_command("/model")
    assert repl.config.model == "sentra/chatgpt-web/high"
    assert "catálogo" not in repl.console.export_text().lower() or "disponível" in repl.console.export_text().lower()


def test_direct_model_switch_and_catalog_listing_still_work(tmp_path, monkeypatch):
    repl = make_repl(tmp_path, model="sentra/chatgpt-web/high")
    monkeypatch.setattr("sentra_cli.codex_native.authenticated", lambda: True)
    monkeypatch.setattr(repl.console, "input", lambda prompt: (_ for _ in ()).throw(
        AssertionError("list and explicit ID must never request another input")))
    repl.handle_slash_command("/model list")
    repl.handle_slash_command("/models")
    repl.handle_slash_command("/model sentra/codex/current")
    assert repl.config.model == "sentra/codex/current"
