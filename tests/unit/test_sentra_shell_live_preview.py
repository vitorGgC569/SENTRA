"""Hermetic streaming and scoped preview checks; no live provider is contacted."""
import json
from pathlib import Path
from types import SimpleNamespace

from sentra_canvas.shell_live import ShellLivePreviews
from sentra_cli.shell_live_preview import LivePreviewWriter


def test_temporary_preview_is_scoped_and_deleted(tmp_path, monkeypatch):
    previews = ShellLivePreviews(tmp_path)
    turn = previews.begin(project_id="workspace-a", conversation_id="conversation-a", operation_id="op-a")
    for name, value in previews.environment(turn).items():
        monkeypatch.setenv(name, value)
    writer = LivePreviewWriter()
    writer.send("Olá ")
    writer.send("ao SENTRA")
    preview = previews.view("workspace-a", "conversation-a")
    assert preview["status"] == "generating"
    assert preview["content"] == "Olá ao SENTRA"
    assert preview["partial"] is True and preview["authoritative"] is False
    assert previews.view("workspace-b", "conversation-a")["status"] == "idle"
    assert previews.view("workspace-a", "conversation-b")["status"] == "idle"
    path = Path(turn["path"])
    assert path.is_file()
    previews.close(turn)
    assert not path.exists()
    assert previews.view("workspace-a", "conversation-a")["status"] == "idle"


def test_preview_rejects_other_nonce_and_large_text(tmp_path):
    previews = ShellLivePreviews(tmp_path)
    turn = previews.begin(project_id="w", conversation_id="c", operation_id="op")
    with turn["path"].open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"nonce": "unknown", "kind": "delta", "text": "SECRET"}) + "\n")
        fh.write(json.dumps({"nonce": turn["nonce"], "kind": "delta", "text": "A"*45000}) + "\n")
    result = previews.view("w", "c")
    assert "SECRET" not in result["content"]
    assert len(result["content"]) <= 32768
    previews.close(turn)


def test_native_cli_yields_prose_without_exposing_tool_directives():
    from sentra_cli.agent import SentraAgent

    class FakeStore:
        def finish_response(self, *args): return {"role": "assistant", "content": args[-1]}
        def end_turn(self, *args): return None
        def append(self, *args, **kwargs): return {"role":"user"}
    agent = object.__new__(SentraAgent)
    agent.session_id = "s"
    agent._turn_id = "t"
    agent.messages = []
    agent.config = SimpleNamespace(max_tool_rounds=2)
    agent.maestri = SimpleNamespace(is_available=False)
    agent._history = lambda: []
    agent.store = FakeStore()
    agent.client = SimpleNamespace(chat_stream=lambda _: iter(["Bom", " dia", "!",]),
                                   last_error=None)
    yielded = list(agent._step_stream("teste"))
    assert yielded == ["Bom", " dia", "!"]
    assert "".join(yielded) == "Bom dia!"


def test_native_stream_never_exposes_partial_tool_directive():
    from sentra_cli.agent import SentraAgent

    class FakeStore:
        def finish_response(self, *args): return {"role": "assistant", "content": args[-1]}
        def end_turn(self, *args): return None
        def append(self, *args, **kwargs): return {"role": "user"}
    rounds = iter([iter(["Antes ", "[[CAN", "VAS|machine_list]]"]),
                   iter(["Depois de consultar."])])
    agent = object.__new__(SentraAgent)
    agent.session_id = "s"
    agent._turn_id = "t"
    agent.messages = []
    agent.config = SimpleNamespace(max_tool_rounds=2)
    agent.maestri = SimpleNamespace(is_available=False)
    agent._history = lambda: []
    agent.store = FakeStore()
    agent.client = SimpleNamespace(chat_stream=lambda _: next(rounds), last_error=None)
    called = []
    agent.execute_directive = lambda op, args: called.append((op, args)) or "[]"
    yielded = "".join(agent._step_stream("consulta"))
    assert "Antes" in yielded and "Depois de consultar." in yielded
    assert "[[CANVAS" not in yielded
    assert called == [("CANVAS", "machine_list")]
    assert yielded.count("Antes") == 1
