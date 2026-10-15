"""A listed Grok id must not leave the Canvas shell as a web, OpenAI, or local turn."""
from __future__ import annotations

import uuid
from contextlib import closing

import pytest

from sentra_canvas.shell_web import ShellWebRuntime, UnverifiedTurn
from test_sentra_runtime_canvas_center_http import request, running_canvas


def test_web_execute_refuses_listed_grok_before_dispatch(monkeypatch):
    web = object.__new__(ShellWebRuntime)

    def boom(*_args, **_kwargs):
        raise AssertionError("web turn was submitted")

    monkeypatch.setattr("native_bridge.shell_multimodal.dispatch_shell_turn", boom)
    with pytest.raises(UnverifiedTurn, match="access is unverified"):
        web.execute({"operation_id": "op", "content": "oi"}, {"model": "sentra/grok/grok-4.7"})


def test_web_owned_grok_turn_is_not_submitted_and_not_resent(tmp_path, monkeypatch):
    from sentra_cli.client import ModelClient

    monkeypatch.setattr(ModelClient, "list_models", lambda self: ["sentra/chatgpt-web/gpt-6"])
    canvas = running_canvas(tmp_path)
    app, server = canvas.__enter__()
    try:
        project = app.create_workspace("GrokWebTurn")["id"]
        runtime = app._runtime()
        run = runtime.run(project)
        if run["state"] != "RUNNING":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": project, "request_key": "grok-home"})["value"]
        space_id = home["space"]["space_id"]
        created = app.shell_bridge({
            "action": "dot_create", "project_id": project, "space_id": space_id,
            "name": "GrokWeb", "role": "specialist", "model": "sentra/grok/grok-4.7",
            "request_key": "grok-dot",
        })["value"]
        conversation = app.shell_bridge({
            "action": "conversation_create", "project_id": project, "space_id": space_id,
            "dot_id": created["dot_id"], "request_key": "grok-conversation",
        })["value"]
        cid = conversation["conversation_id"]
        shell = app._shell_runtime
        with closing(shell.control.store.connect("shell")) as db, db:
            db.execute("INSERT INTO canvas_shell_web_conversations VALUES(?,?,?,?)",
                (shell.owner, project, cid, "remote-not-sent"))
        submitted = []

        def reject_web(*_args, **_kwargs):
            submitted.append("web")
            raise AssertionError("web turn was submitted")

        def reject_cli(arguments):
            submitted.append(("cli", arguments))
            raise AssertionError("CLI turn was submitted")

        monkeypatch.setattr("native_bridge.shell_multimodal.dispatch_shell_turn", reject_web)
        monkeypatch.setattr(shell.web, "execute", reject_web)
        monkeypatch.setattr(app, "_cli_command", reject_cli)
        key = "grok-send-" + uuid.uuid4().hex
        body = {
            "action": "message_send", "project_id": project, "space_id": space_id,
            "conversation_id": cid, "content": "oi", "request_key": key,
        }
        code, first = request(server, "/api/shell/bridge", json_body=body)
        assert code == 200, first
        sent = first["value"]
        assert sent["status"] == "not_submitted"
        assert sent["delivery"] == "not_submitted"
        assert sent["receipt"] == "access unverified"
        assert sent["resent"] is False
        assert sent["automatic_retry"] is False
        assert sent["model_access_verified"] is False
        assert sent["inference_executed"] is False
        assert "access is unverified" in sent["reason"]
        operation = runtime.durable.operation_status(sent["operation_id"], runtime.owner)
        assert operation["state"] == "FAILED"
        assert operation["progress"]["delivery"] == "not_submitted"
        assert operation["progress"]["automatic_retry"] is False
        assert operation["result"]["resent"] is False
        with closing(shell.control.store.connect("shell")) as db:
            queued = db.execute("SELECT state FROM canvas_shell_queue WHERE operation_id=?",
                (sent["operation_id"],)).fetchone()
            turns = db.execute("SELECT job_id FROM canvas_shell_web_turns WHERE operation_id=?",
                (sent["operation_id"],)).fetchone()
        assert queued is None
        assert turns is None
        code, replay = request(server, "/api/shell/bridge", json_body=body)
        assert code == 200, replay
        again = replay["value"]
        assert again["status"] == "not_submitted"
        assert again["receipt"] == "access unverified"
        assert again["resent"] is False
        assert again["inference_executed"] is False
        second = app.shell_bridge({
            "action": "message_send", "project_id": project, "space_id": space_id,
            "conversation_id": cid, "content": "de novo", "request_key": "grok-send-again",
        })["value"]
        assert second["status"] == "not_submitted"
        assert second["resent"] is False
        assert second["operation_id"] != sent["operation_id"]
        assert submitted == []
    finally:
        canvas.__exit__(None, None, None)
