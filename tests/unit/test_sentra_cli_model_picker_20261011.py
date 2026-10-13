"""The centered CLI selects models without dispatching numbered replies."""
from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from rich.console import Console

from sentra_cli.terminal_ui import CenteredTerminalUI, geometry
from sentra_cli.repl import SentraREPL
from sentra_cli.codex_native import native_failure_category, parse_response, NativeModelError


def test_native_picker_is_centered_and_numbered():
    stream = io.StringIO()
    ui = CenteredTerminalUI(stream, enabled=True)
    choices = ["sentra/chatgpt-web/auto", "sentra/chatgpt-web/gpt-6",
               "sentra/codex/current"]
    dims = geometry(110, 36, has_history=True)
    ui._draw(dims, model="sentra/codex/current", effort="low", turns=[],
             value="", cursor=0, choices=choices)
    output = stream.getvalue()
    assert "MODELOS" in output
    assert "1  sentra/chatgpt-web/auto" in output
    assert "2  sentra/chatgpt-web/gpt-6" in output
    assert "0 cancela" in output


def test_model_chooser_uses_number_without_model_turn(monkeypatch):
    from sentra_cli import terminal_ui

    class FakeUI:
        def __init__(self):
            self.enabled = True
            self.choices_seen = []
        def read(self, *, model, effort, turns, choices=None):
            self.choices_seen.append(choices)
            return next(inputs)

    fake_ui = FakeUI()
    monkeypatch.setattr(terminal_ui, "CenteredTerminalUI", lambda: fake_ui)
    inputs = iter(["/models", "2", "/exit"])
    config = SimpleNamespace(model="sentra/chatgpt-web/auto",
                             web_reasoning_effort="medium", reasoning_effort="low")
    models = ["sentra/chatgpt-web/auto", "sentra/chatgpt-web/gpt-6",
              "sentra/codex/current"]

    class Client:
        active_model = None
        def list_models(self):
            return models
        def chat_stream(self, *_args, **_kwargs):
            pytest.fail("Model choice must never be sent as a prompt")
    client = Client()
    agent = SimpleNamespace(client=client,
        jobs=SimpleNamespace(completed_notifications=lambda: []),
        persist_model_preferences=lambda: None)
    repl = object.__new__(SentraREPL)
    repl.config = config
    repl.agent = agent
    repl.console = Console(file=io.StringIO(), force_terminal=False, width=120)
    repl.run_interactive()
    assert config.model == "sentra/chatgpt-web/gpt-6"
    assert client.active_model == config.model
    assert fake_ui.choices_seen[1] == models


def test_codex_failure_category_never_exposes_provider_raw_message():
    event = {"type": "turn.failed",
             "error": {"message": "Rate limit 429, private token secret-abc"}}
    assert native_failure_category(event) == "rate_limited"
    with pytest.raises(NativeModelError) as exc:
        parse_response(json.dumps(event).encode(), 1)
    assert "rate_limited" in str(exc.value)
    assert "private token" not in str(exc.value)


def test_provider_failure_visible_once_and_keeps_uncertainty():
    from sentra_cli.agent import SentraAgent
    error = "\nNative Codex turn failed and was not replayed automatically: native model turn failed\n"

    class Store:
        def __init__(self): self.events = []
        def append(self, session, role, body, kind=None):
            self.events.append(("append", kind, body))
            return {"role": role, "content": body}
        def end_turn(self, session, turn, state="done"):
            self.events.append(("end", state))
    agent = object.__new__(SentraAgent)
    agent.session_id = "session-test"
    agent._turn_id = "turn-test"
    agent.store = Store()
    agent.config = SimpleNamespace(max_tool_rounds=1)
    agent.maestri = SimpleNamespace(is_available=False)
    agent._history = lambda: []
    agent.messages = []
    agent.client = SimpleNamespace(
        chat_stream=lambda _: iter([error[:34], error[34:]]),
        last_error="native model turn failed", last_delivery_state="uncertain")
    chunks = list(agent._step_stream("Ola"))
    assert "".join(chunks).count("Native Codex turn failed") == 1
    assert agent.store.events[-1] == ("end", "uncertain")
    assert any(event[0] == "append" and event[1] == "provider_error"
               for event in agent.store.events)
