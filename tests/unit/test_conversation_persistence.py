"""Actual persistence, separate-process recovery and effect replay checks."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from sentra_core.conversations import ConversationBusy, ConversationStore, UncertainCall
from sentra_cli.agent import SentraAgent
from sentra_cli.config import CLIConfig

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def test_keyring_without_desktop_service(monkeypatch):
    """Linux CI uses a deterministic in-memory keyring; Windows exercises DPAPI."""
    if os.name != "nt":
        from types import SimpleNamespace
        values = {}
        monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(
            set_password=lambda service, key, value: values.__setitem__((service,key), value),
            get_password=lambda service, key: values.get((service,key))))


def config(tmp_path, **kwargs):
    return CLIConfig(workspace=tmp_path, state_root=tmp_path / "state",
                     auto_start_gateway=False, openai_api_key="none", **kwargs)


def test_history_identity_and_cross_conversation_recall_survive_new_agent(tmp_path):
    first = SentraAgent(config(tmp_path))
    first.client.chat_stream = Mock(return_value=iter(["The chosen convention is blue_widget_17."]))
    assert "blue_widget_17" in "".join(first.step_stream("Save the decision about widgets"))
    saved = first.session_id
    thread = first.client._thread_id
    restored = SentraAgent(config(tmp_path, session_id=saved, resume_session=True))
    assert restored.client._thread_id == thread
    assert restored.messages == first.messages
    assert restored.client.last_delivery_state == "not_submitted"
    new = SentraAgent(config(tmp_path))
    assert new.session_id != saved
    recalled = json.loads(new.execute_directive("MEMORY", "search|blue_widget_17"))["items"]
    assert recalled[0]["session_id"] == saved
    assert "blue_widget_17" in recalled[0]["excerpt"]
    new.reset()
    assert first.store.messages(saved)


def test_workspace_and_principal_isolation(tmp_path):
    workspace = tmp_path / "one"
    workspace.mkdir()
    state = tmp_path / "state"
    alice = ConversationStore(state, principal="alice")
    sid = alice.open(workspace, session_id="alice-session")
    alice.append(sid, "user", "private_alice_context")
    with pytest.raises(PermissionError):
        alice.open(tmp_path / "other", session_id=sid, resume=True)
    bob = ConversationStore(state, principal="bob")
    with pytest.raises(PermissionError):
        bob.messages(sid)
    assert bob.search(workspace, "private") == []
    with pytest.raises(FileNotFoundError):
        alice.open(workspace, session_id="missing-session", resume=True)
    with pytest.raises(ValueError):
        alice.open(workspace, session_id="../escape")


def test_live_writer_is_not_recovered_by_second_agent(tmp_path):
    store = ConversationStore(tmp_path / "state")
    sid = store.open(tmp_path)
    with store.executing(sid):
        store.begin_turn(sid, "active")
        with pytest.raises(ConversationBusy):
            SentraAgent(config(tmp_path, session_id=sid, resume_session=True))
        assert store.status(sid)["state"] == "running"


def test_protection_failure_prevents_side_effect(tmp_path, monkeypatch):
    agent = SentraAgent(config(tmp_path))
    monkeypatch.setattr("sentra_core.conversations.protect_secret", lambda value: value)
    with pytest.raises(RuntimeError, match="OS protected"):
        agent.execute_directive("W", "must_not_exist.txt|data")
    assert not (tmp_path / "must_not_exist.txt").exists()


def test_context_window_retains_old_history_and_explains_omission(tmp_path):
    store = ConversationStore(tmp_path / "state")
    sid = store.open(tmp_path)
    for n in range(5):
        store.append(sid, "user", f"old_fact_{n}_" + "x" * 500)
    window = store.history_window(sid, max_messages=2, max_chars=2000)
    assert window["omitted"] == 3 and window["total"] == 5
    assert len(store.messages(sid)) == 5
    assert store.search(tmp_path, "old_fact_0")[0]["seq"] == 1


@pytest.mark.skipif(os.name != "nt", reason="separate processes use the actual Windows DPAPI backend")
@pytest.mark.parametrize("phase", ["before_effect", "after_effect", "after_commit"])
def test_real_process_crash_never_repeats_committed_or_uncertain_effect(tmp_path, phase):
    script = """
import os,sys
from pathlib import Path
from sentra_core.conversations import ConversationStore
workspace=Path(sys.argv[1]);phase=sys.argv[2]
store=ConversationStore(workspace/'state')
sid=store.open(workspace,session_id='crash-session')
with store.executing(sid):
    turn,_=store.begin_turn(sid,'private_crash_context_marker')
    call,_=store.start_tool(sid,turn,'W','effect.txt|exactly once')
    if phase=='before_effect':os._exit(17)
    (workspace/'effect.txt').write_text('exactly once')
    (workspace/'counter.txt').write_text('1')
    if phase=='after_effect':os._exit(17)
    store.finish_tool(sid,call,'write completed')
    os._exit(17)
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path), phase],
                            cwd=ROOT, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 17, result.stderr.decode("utf-8", "replace")
    agent = SentraAgent(config(tmp_path, session_id="crash-session", resume_session=True))
    status = agent.store.status(agent.session_id)
    assert status["state"] == "interrupted"
    if phase != "after_commit":
        assert len(status["uncertain_calls"]) == 1
        with pytest.raises(UncertainCall):
            list(agent.step_stream("", continue_previous=True))
        call = status["uncertain_calls"][0]["id"]
        executed = phase == "after_effect"
        agent.store.resolve_call(agent.session_id, call, executed=executed,
                                 evidence="Verified effect file presence and counter" if executed else "Verified effect file is absent")
    agent.client.chat_stream = Mock(side_effect=[iter(["[[W|effect.txt|exactly once]]"]), iter(["Finished."])])
    real = agent._execute_directive
    agent._execute_directive = Mock(wraps=real)
    output = "".join(agent.step_stream("", continue_previous=True))
    assert "Finished" in output
    if phase == "before_effect":
        agent._execute_directive.assert_called_once()
        assert (tmp_path / "effect.txt").read_text() == "exactly once"
    else:
        agent._execute_directive.assert_not_called()
        assert (tmp_path / "counter.txt").read_text() == "1"
    assert agent.store.status(agent.session_id)["state"] == "completed"
    database = agent.store.path.read_bytes()
    assert b"private_crash_context_marker" not in database
    assert b"exactly once" not in database


def test_uncertain_provider_blocks_new_submission_and_resume_never_resends(tmp_path):
    store = ConversationStore(tmp_path / "state")
    sid = store.open(tmp_path)
    with store.executing(sid):
        turn, _ = store.begin_turn(sid, "provider request")
        store.provider_state(sid, turn, "gateway", "provider-old-turn", "submitted")
        store.end_turn(sid, turn, "interrupted")
    resumed = SentraAgent(config(tmp_path, session_id=sid, resume_session=True))
    resumed.client.chat_stream = Mock()
    with pytest.raises(UncertainCall):
        list(resumed.step_stream("continue"))
    resumed.client.chat_stream.assert_not_called()
    status = resumed.store.status(sid)
    assert status["uncertain_calls"][0]["provider_id"] == "provider-old-turn"


def test_provider_reply_is_committed_with_its_call_state(tmp_path):
    store = ConversationStore(tmp_path / "state")
    sid = store.open(tmp_path)
    with store.executing(sid):
        turn, _ = store.begin_turn(sid, "question")
        store.provider_state(sid, turn, "gateway", "native-turn", "submitted")
        store.provider_state(sid, turn, "gateway", "native-turn", "completed")
        # A received reply is not durable completion until its text is committed.
        store.finish_response(sid, turn, "durable answer")
        store.end_turn(sid, turn)
    store.open(tmp_path, session_id=sid, resume=True)
    assert store.status(sid)["uncertain_calls"] == []
    assert store.messages(sid)[-1]["content"] == "durable answer"


def test_closing_consumer_after_final_reply_does_not_downgrade_recorded_completion(tmp_path):
    agent = SentraAgent(config(tmp_path))
    agent.client.chat_stream = Mock(return_value=iter(["Complete answer without tools."]))
    stream = agent.step_stream("question")
    assert next(stream) == "Complete answer without tools."
    stream.close()
    assert agent.store.status(agent.session_id)["state"] == "completed"
