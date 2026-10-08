"""Restart, retention and isolation checks for durable terminal transcripts."""
from __future__ import annotations

import os
import sqlite3
import time

import pytest

from sentra_canvas.service import Canvas, Session
from sentra_canvas.store import Denied, Store, TRANSCRIPT_LIMIT


def test_restart_does_not_interrupt_another_principals_resources(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    first = Store(tmp_path / "canvas.sqlite3", projects, principal="alice")
    second = None
    try:
        ws = first.create_workspace("owned")["id"]
        terminal = first.create_terminal(ws, "live", "cmd")["id"]
        first.terminal_state(ws, terminal, "running", pid=12345)
        coordinator = first.create_agent(ws, "coordinator", "test/model", "coordinator")["id"]
        worker = first.create_agent(ws, "worker", "test/model", "worker")["id"]
        team = first.create_team(ws, "team", coordinator, [worker])["id"]
        task, _ = first.create_task(ws, team, worker, "test", "work", "request")
        first.task_state(ws, task["id"], "running")
        second = Store(first.path, projects, principal="bob")
        assert first.resource("terminals", terminal, ws)["status"] == "running"
        assert first.resource("tasks", task["id"], ws)["status"] == "running"
        with pytest.raises(Denied):
            second.terminal_output(ws, terminal)
    finally:
        if second:
            second.close()
        first.close()


@pytest.mark.skipif(os.name != "nt", reason="validates real Windows DPAPI storage")
def test_encrypted_transcript_survives_restart_and_keeps_absolute_cursors(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    db = tmp_path / "canvas.sqlite3"
    store = Store(db, projects)
    ws = store.create_workspace("durable")["id"]
    terminal = store.create_terminal(ws, "terminal", "cmd")["id"]
    text = "transcript_private_marker \x1b[31mcafé 🔒\x1b[0m\r\n"
    try:
        cursor = store.append_terminal_output(ws, terminal, text)
        assert cursor == len(text)
        assert store.terminal_output(ws, terminal)["text"] == text
        assert store.terminal_output(ws, terminal, cursor)["text"] == ""
        assert store.terminal_output(ws, terminal, cursor + 99)["cursor"] == cursor
        store.terminal_state(ws, terminal, "running", pid=12345)
    finally:
        store.close()
    assert text.encode("utf-8") not in db.read_bytes()
    restored = Store(db, projects)
    try:
        assert restored.terminal_output(ws, terminal) == {
            "text": text, "cursor": cursor, "truncated": False}
        assert restored.resource("terminals", terminal, ws)["status"] == "interrupted"
        assert any(e["kind"] == "terminal.interrupted" for e in restored.events(ws))
        for _ in range(20):
            cursor = restored.append_terminal_output(ws, terminal, "x" * 8192)
        retained = restored.terminal_output(ws, terminal)
        assert retained["text"] == "x" * TRANSCRIPT_LIMIT
        assert retained["cursor"] == cursor and retained["truncated"]
        base = cursor - TRANSCRIPT_LIMIT
        assert not restored.terminal_output(ws, terminal, base)["truncated"]
        assert restored.terminal_output(ws, terminal, cursor - 7)["text"] == "x" * 7
    finally:
        restored.close()


def test_version_one_migration_preserves_existing_workspace(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    db = tmp_path / "canvas.sqlite3"
    original = Store(db, projects)
    ws = original.create_workspace("legacy")
    original.close()
    with sqlite3.connect(db) as legacy:
        legacy.execute("ALTER TABLE agents DROP COLUMN conversation_id")
        legacy.execute("DROP TABLE terminal_output_chunks")
        legacy.execute("DROP TABLE terminal_output_state")
        legacy.execute("DROP TABLE task_projection_outbox")
        legacy.execute("DROP INDEX task_queue")
        legacy.execute("ALTER TABLE workspaces DROP COLUMN run_id")
        legacy.execute("ALTER TABLE tasks DROP COLUMN run_id")
        for field in ("approved","cancel_requested","revision","protected_prompt","protected_result"):
            legacy.execute("ALTER TABLE tasks DROP COLUMN "+field)
        legacy.execute("PRAGMA user_version=1")
    migrated = Store(db, projects)
    try:
        assert migrated.workspace(ws["id"]) == ws
        assert migrated.db.execute("PRAGMA user_version").fetchone()[0] == 5
    finally:
        migrated.close()


def test_plaintext_protection_failure_does_not_commit_a_transcript(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    store = Store(tmp_path / "canvas.sqlite3", projects)
    try:
        ws = store.create_workspace("protection")["id"]
        terminal = store.create_terminal(ws, "terminal", "cmd")["id"]
        monkeypatch.setattr("sentra_canvas.store.protect_secret", lambda text: text)
        with pytest.raises(RuntimeError, match="OS protected"):
            store.append_terminal_output(ws, terminal, "private transcript")
        assert store.terminal_output(ws, terminal) == {
            "text": "", "cursor": 0, "truncated": False}
        assert store.db.execute("SELECT count(*) FROM terminal_output_chunks").fetchone()[0] == 0
    finally:
        store.close()


def test_canvas_uses_authoritative_state_directory_across_launch_locations(tmp_path):
    state = tmp_path / "user_state" / "canvas"
    first = Canvas(tmp_path / "installation_v1", state_dir=state)
    try:
        ws = first.create_workspace("project")
    finally:
        first.shutdown()
    updated = Canvas(tmp_path / "installation_v2", state_dir=state)
    try:
        assert updated.store.workspace(ws["id"]) == ws
        assert updated.state_dir == state.resolve()
    finally:
        updated.shutdown()


def test_failed_persistence_keeps_reader_alive_and_does_not_shift_durable_cursor():
    calls = []
    def broken(text):
        calls.append(text)
        raise OSError("private disk failure text")
    errors = []
    session = Session(broken, errors.append)
    data = "café 🔒".encode()
    session.append(data[:5])
    session.append(data[5:])
    assert session.output()["text"] == "café 🔒"
    assert session.persistence_error == "OSError"
    assert errors == ["OSError"] and len(calls) == 1


def test_reader_survives_failed_telemetry_and_slices_retained_cursor_correctly():
    def broken(*args):
        raise OSError("disk offline")
    session = Session(broken, broken)
    session.append(b"hello")
    assert session.output()["text"] == "hello"
    session.append(b"x" * TRANSCRIPT_LIMIT)
    assert session.output()["truncated"]
    assert not session.output(5)["truncated"]
    assert session.output(TRANSCRIPT_LIMIT + 5)["text"] == ""


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows ConPTY and DPAPI")
def test_real_terminal_output_survives_canvas_restart_without_claiming_reattachment(tmp_path):
    app = Canvas(tmp_path)
    try:
        ws = app.create_workspace("restart")["id"]
        terminal = app.create_terminal(ws, "shell", "cmd")["id"]
        app.terminal_input(ws, terminal, "echo CANVAS_DURABLE_OUTPUT\r")
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            output = app.terminal_output(ws, terminal)
            if "CANVAS_DURABLE_OUTPUT" in output["text"]:
                break
            time.sleep(.05)
        assert "CANVAS_DURABLE_OUTPUT" in output["text"] and output["persisted"]
        cursor = output["cursor"]
    finally:
        app.shutdown()
    restarted = Canvas(tmp_path)
    try:
        recovered = restarted.terminal_output(ws, terminal)
        assert "CANVAS_DURABLE_OUTPUT" in recovered["text"]
        assert recovered["cursor"] >= cursor
        assert recovered["persisted"] and not recovered["recoverable"]
        assert recovered["status"] == "interrupted"
    finally:
        restarted.shutdown()


@pytest.mark.skipif(os.name != "nt", reason="real persistent Windows CLI agent")
def test_agent_restart_restores_conversation_identity_in_shared_state(tmp_path):
    from sentra_core.conversations import ConversationStore
    app = Canvas(tmp_path)
    try:
        ws = app.create_workspace("agent_restart")["id"]
        agent = app.create_agent(ws, "persistent_agent", "sentra/chatgpt-web/high", start=True)
        assert app.restart_agent(ws, agent["id"])["terminal_id"] == agent["terminal_id"]
        store = ConversationStore(app.state_dir.parent)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                status = store.status(agent["conversation_id"])
                break
            except PermissionError:
                time.sleep(.05)
        assert status["workspace"] == app.store.workspace(ws)["path"]
        store.append(agent["conversation_id"], "user", "CANVAS_SAVED_AGENT_CONTEXT")
        app.terminal_close(ws, agent["terminal_id"])
        original = agent["terminal_id"]
    finally:
        app.shutdown()
    restored = Canvas(tmp_path)
    try:
        restarted = restored.restart_agent(ws, agent["id"])
        assert restarted["conversation_id"] == agent["conversation_id"]
        assert restarted["terminal_id"] != original
        terminal = restored.store.resource("terminals", restarted["terminal_id"], ws)
        assert terminal["shell"] == "sentra-cli" and terminal["status"] == "running"
        assert store.messages(agent["conversation_id"])[-1]["content"] == "CANVAS_SAVED_AGENT_CONTEXT"
        assert not store.status(agent["conversation_id"])["uncertain_calls"]
    finally:
        restored.shutdown()
