"""Hermetic streaming and scoped preview checks; no live provider is contacted."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest

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


def test_feed_names_coordinating_and_uncertain_without_closing_the_trio(tmp_path, monkeypatch):
    previews = ShellLivePreviews(tmp_path)
    turn = previews.begin(project_id="w", conversation_id="c", operation_id="op")
    for name, value in previews.environment(turn).items():
        monkeypatch.setenv(name, value)
    writer = LivePreviewWriter()
    writer.activity("coordinating")
    first = previews.view("w", "c")
    assert first["activity"] == "Coordenando"
    assert first["authoritative"] is False
    assert first["closes_trio"] is False
    assert first["partial"] is True
    writer.send("Ol")
    writer.activity("delivery_uncertain")
    later = previews.view("w", "c")
    assert later["content"] == "Ol"
    assert later["activity"] == "Entrega incerta. Não reenvie."
    assert later["authoritative"] is False
    assert later["closes_trio"] is False
    assert "unit_gate" not in later
    previews.close(turn)


def test_provider_round_replaces_prior_prose_with_new_content_revision(tmp_path, monkeypatch):
    previews = ShellLivePreviews(tmp_path)
    record = previews.begin(project_id="w", conversation_id="c", operation_id="operation-one")
    for name, value in previews.environment(record).items():
        monkeypatch.setenv(name, value)
    writer = LivePreviewWriter()
    writer.send("resposta provisória mais longa")
    first = previews.view("w", "c")
    assert first["content_revision"] == 0
    writer.activity("provider_submitted")
    waiting = previews.view("w", "c")
    assert waiting["content"] == first["content"]
    assert waiting["content_revision"] == 0
    writer.send("Nova")
    second = previews.view("w", "c")
    assert second["content"] == "Nova"
    assert second["content_revision"] == 1
    previews.close(record)


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


def test_native_preview_pins_created_handle_and_never_reopens_for_fragments(tmp_path, monkeypatch):
    previews=ShellLivePreviews(tmp_path)
    turn=previews.begin(project_id='w',conversation_id='c',operation_id='op')
    for name,value in previews.environment(turn).items():monkeypatch.setenv(name,value)
    writer=LivePreviewWriter()
    reader=turn['reader']
    def refuse_reopen(*_args,**_kwargs):raise AssertionError('preview reader must reuse its created handle')
    # The writer uses builtin open; no read path may reopen this pathname.
    monkeypatch.setattr(Path,'open',refuse_reopen)
    for fragment in ['primeiro 🪐',' repetido',' repetido']:
        writer.send(fragment)
        previews.update(turn)
    assert previews.view('w','c')['content']=='primeiro 🪐 repetido repetido'
    assert turn['reader'] is reader and not reader.closed
    previews.close(turn)
    assert reader.closed and not turn['path'].exists()


def test_pinned_preview_refuses_changed_file_identity_and_truncation(tmp_path,monkeypatch):
    previews=ShellLivePreviews(tmp_path)
    turn=previews.begin(project_id='w',conversation_id='c',operation_id='op')
    for name,value in previews.environment(turn).items():monkeypatch.setenv(name,value)
    writer=LivePreviewWriter();writer.send('conteúdo original');previews.update(turn)
    original=turn['path']
    replacement=tmp_path/'replacement.jsonl'
    replacement.write_text(json.dumps({'nonce':turn['nonce'],'kind':'delta','text':'não pode aparecer'})+'\n',encoding='utf-8')
    turn['path']=replacement
    previews.update(turn)
    assert previews.view('w','c')['status']=='preview_unavailable'
    assert turn['text']=='conteúdo original'
    turn['path']=original
    original.write_bytes(b'')
    previews.update(turn)
    assert turn['phase']=='preview_unavailable' and turn['text']=='conteúdo original'
    previews.close(turn)
    assert turn['reader'].closed


def test_failed_close_callback_still_releases_native_handle_and_registration(tmp_path):
    previews=ShellLivePreviews(tmp_path,on_change=lambda *_:(_ for _ in ()).throw(OSError('induced persistence failure')))
    turn=previews.begin(project_id='w',conversation_id='c',operation_id='op')
    with pytest.raises(OSError,match='induced persistence failure'):previews.close(turn)
    assert turn['done'] and turn['reader'].closed
    assert not previews.has_active('w','c') and not turn['path'].exists()


def test_pinned_preview_accepts_append_from_a_separate_native_child(tmp_path):
    previews=ShellLivePreviews(tmp_path)
    turn=previews.begin(project_id='w',conversation_id='c',operation_id='op')
    try:
        child=subprocess.run([sys.executable,'-B','-c',
            "from sentra_cli.shell_live_preview import LivePreviewWriter; LivePreviewWriter().send('child Unicode 🪐')"],
            env={**os.environ,**previews.environment(turn)},capture_output=True,timeout=15)
        assert child.returncode==0,child.stderr.decode(errors='replace')
        assert previews.view('w','c')['content']=='child Unicode 🪐'
    finally:previews.close(turn)


def test_superseded_native_handle_closes_without_publishing_into_new_operation(tmp_path,monkeypatch):
    published=[]
    previews=ShellLivePreviews(tmp_path,on_change=lambda record,view:published.append((record['operation_id'],view)))
    old=previews.begin(project_id='w',conversation_id='c',operation_id='old')
    new=previews.begin(project_id='w',conversation_id='c',operation_id='new')
    assert old['done'] and old['reader'].closed and not old['path'].exists()
    assert not new['reader'].closed and not published
    previews.close(old)
    assert not new['reader'].closed and previews.has_active('w','c') and not published
    for name,value in previews.environment(new).items():monkeypatch.setenv(name,value)
    LivePreviewWriter().send('only the new turn')
    assert previews.view('w','c')['content']=='only the new turn'
    assert all(operation=='new' for operation,_ in published)
    previews.close(new);previews.close(old)
    assert new['reader'].closed and not previews.has_active('w','c')


def test_close_all_releases_every_handle_even_after_a_callback_error(tmp_path):
    def fail(*_args):raise OSError('induced shutdown failure')
    previews=ShellLivePreviews(tmp_path,on_change=fail)
    records=[previews.begin(project_id='w',conversation_id='c'+str(i),operation_id='op'+str(i)) for i in range(3)]
    with pytest.raises(OSError,match='induced shutdown failure'):previews.close_all()
    assert not previews.has_active()
    assert all(record['reader'].closed and not record['path'].exists() for record in records)


def test_fdopen_failure_after_taking_ownership_preserves_error_and_cleans_tempfile(tmp_path,monkeypatch):
    previews=ShellLivePreviews(tmp_path)
    def fail(fd,*_args,**_kwargs):
        os.close(fd)
        raise OSError('induced fdopen ownership failure')
    monkeypatch.setattr(os,'fdopen',fail)
    with pytest.raises(OSError,match='induced fdopen ownership failure'):
        previews.begin(project_id='w',conversation_id='c',operation_id='op')
    assert not list(tmp_path.iterdir()) and not previews.has_active()


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
