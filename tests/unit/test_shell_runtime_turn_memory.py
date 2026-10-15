"""Shell turn memory and a second read of an UNCERTAIN pending turn."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from contextlib import closing
from pathlib import Path

from sentra_core.conversations import _decode, _encode
from test_sentra_runtime_canvas_center_http import request, running_canvas


def _shell(tmp_path, monkeypatch):
    canvas = running_canvas(tmp_path)
    app, server = canvas.__enter__()
    monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/test-one"]})
    project = app.create_workspace("Dot_turn_memory")["id"]
    runtime = app._runtime()
    run = runtime.run(project)
    if run["state"] != "RUNNING":
        runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
    home = app.shell_bridge({"action": "home", "project_id": project})["value"]
    space_id = home["space"]["space_id"]

    def call(action, **fields):
        code, body = request(server, "/api/shell/bridge", json_body={
            "action": action, "project_id": project, "space_id": space_id,
            "request_key": "turn-" + uuid.uuid4().hex, **fields})
        assert code == 200, body
        assert body["ok"] is True, body
        return body["value"]

    return canvas, app, project, space_id, call


def test_published_turn_keeps_real_steps_for_a_new_process(tmp_path, monkeypatch):
    canvas, app, project, space_id, call = _shell(tmp_path, monkeypatch)
    try:
        runtime = app._runtime()
        owner = runtime.owner
        shell = app._shell_runtime
        monkeypatch.setattr(shell, "_execute", lambda _oid: None)
        root = call("dot_create", name="TurnDot", role="specialist", model="sentra/test-one")
        conversation = call("conversation_create", dot_id=root["dot_id"])
        cid = conversation["conversation_id"]
        sent = call("message_send", conversation_id=cid, content="pedido com etapas reais")
        workspace = app.store.workspace(project)["path"]
        shell.conversations.open(workspace, session_id=cid)
        turn, _message = shell.conversations.begin_turn(cid, "pedido com etapas reais")
        call_id, _prior = shell.conversations.start_tool(cid, turn, "read", "notes.txt")
        shell.conversations.finish_tool(cid, call_id, "lido")
        answer = "resultado " + ("etapa " * 120)
        assert len(answer) > 500
        shell.conversations.finish_response(cid, turn, answer)
        shell.conversations.end_turn(cid, turn, "completed")
        operation_id = sent["operation_id"]
        state = runtime.durable.operation_status(operation_id, owner)["state"]
        if state == "QUEUED":
            runtime.durable.update_operation(operation_id, owner, state="STARTING")
            state = "STARTING"
        if state == "STARTING":
            runtime.durable.update_operation(operation_id, owner, state="RUNNING")
        message = {
            "project_id": project,
            "space_id": space_id,
            "conversation_id": cid,
            "message_id": sent["message_id"],
            "work_item_id": sent["work_item_id"],
            "operation_id": operation_id,
            "run_id": sent.get("run_id") or runtime.run(project)["run_id"],
            "agent_id": root["agent_id"],
        }
        shell._publish_answer(message, answer, "conversation:" + cid + ":2",
            evidence={"protected_journal": True})
        stored = Path(workspace) / ".sentra"
        from orchestrator.memory import LiveDotSession
        loaded = LiveDotSession(stored, owner, root["dot_id"], cid).load_dot()
        plan = loaded["plan"]["body"]
        assert plan["objective"] == answer.strip()
        assert len(plan["objective"]) > 500
        titles = [step["title"] for step in plan["steps"]]
        assert "READ" in titles
        assert "pedido com etapas reais" in titles
        assert any(plan["objective"].startswith(step["title"]) for step in plan["steps"])
        assert "handoff" not in json.dumps(plan).lower()
        assert loaded["context"]["body"]["summary"] == answer.strip()
        assert loaded["authorizes_effects"] is False

        repo = Path(__file__).resolve().parents[2]
        code = r"""
import json, sys
from orchestrator.memory import LiveDotSession
root, owner, dot, session_id = sys.argv[1:5]
loaded = LiveDotSession.reopen(root, owner, dot, session_id).load_dot()
json.dump({"objective": loaded["plan"]["body"]["objective"],
    "steps": loaded["plan"]["body"]["steps"],
    "summary": loaded["context"]["body"]["summary"],
    "authorizes_effects": loaded["authorizes_effects"]}, sys.stdout)
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, "-c", code, str(stored), owner, root["dot_id"], cid],
            check=False, cwd=str(repo), env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stderr
        reread = json.loads(completed.stdout)
        assert reread["objective"] == answer.strip()
        assert len(reread["objective"]) > 500
        assert "READ" in [step["title"] for step in reread["steps"]]
        assert "handoff" not in json.dumps(reread).lower()
        assert reread["authorizes_effects"] is False

        monkeypatch.setattr(shell, "_execute", lambda _oid: None)
        again = call("message_send", conversation_id=cid, content="segunda leitura")
        with closing(runtime.control.store.connect("shell")) as db:
            row = db.execute("SELECT protected_input FROM canvas_shell_queue WHERE operation_id=?",
                (again["operation_id"],)).fetchone()
        view = _decode(row["protected_input"])["message"]["live_dot_session"]
        assert view["present"] is True
        assert view["provider_handoff"] is False
        assert view["authorizes_effects"] is False
        assert "READ" in [step["title"] for step in view["steps"]]
        assert all(step["id"] != "handoff" and step["title"].lower() != "handoff" for step in view["steps"])
    finally:
        canvas.__exit__(None, None, None)


def test_consulting_uncertain_again_keeps_it_uncertain(tmp_path, monkeypatch):
    canvas, app, project, space_id, call = _shell(tmp_path, monkeypatch)
    try:
        runtime = app._runtime()
        owner = runtime.owner
        shell = app._shell_runtime
        root = call("dot_create", name="UncertainDot", role="specialist", model="sentra/test-one")
        conversation = call("conversation_create", dot_id=root["dot_id"])
        cid = conversation["conversation_id"]
        shell.conversations.open(app.store.workspace(project)["path"], session_id=cid)
        items = runtime.control.list_work_items(owner, run_id=root["run_id"], limit=1000)["items"]
        item = next(row for row in items if row["assignee_agent_id"] == root["agent_id"])
        operation_id = "uncertain-consult-" + uuid.uuid4().hex
        created = runtime.durable.create_operation(item["run_id"], owner, kind="shell.consult",
            operation_id=operation_id, idempotency_key=operation_id, cleanup_policy="manual",
            initial_state="RUNNING")
        runtime.durable.update_operation(created["operation_id"], owner, state="UNCERTAIN",
            result={"web_attested_final": True}, progress={"automatic_retry": False})
        message = {
            "project_id": project, "space_id": space_id, "conversation_id": cid,
            "message_id": "uncertain-message", "work_item_id": item["work_item_id"],
            "operation_id": operation_id, "run_id": item["run_id"],
            "content": "consulta incerta", "agent_id": root["agent_id"],
        }
        with closing(runtime.control.store.connect("shell")) as db, db:
            db.execute("INSERT INTO canvas_shell_queue VALUES(?,?,?,?,?,?,?,?,?)",
                (operation_id, owner, project, cid, message["message_id"],
                 _encode({"dot": root, "message": message, "request_key": "uncertain-consult"}),
                 "running", 1.0, None))
            db.execute("INSERT INTO canvas_shell_web_conversations VALUES(?,?,?,?)",
                (owner, project, cid, "fixture-remote-only"))
        before = runtime.durable.operation_status(operation_id, owner)
        observed, executed = [], []

        def observe(pending, dot):
            observed.append(pending["operation_id"])
            return {"content": "nao-publicar", "receipt_id": "web:job:msg", "web_attested_final": True}

        def execute(*args, **kwargs):
            executed.append(args)
            raise AssertionError("uncertain turn was resent")

        monkeypatch.setattr(shell.web, "availability", lambda: {
            "model_delivery_available": True, "proves_model_delivery": False,
            "model_delivery_reason": None})
        monkeypatch.setattr(shell.web, "observe", observe)
        monkeypatch.setattr(shell.web, "execute", execute)
        monkeypatch.setattr(shell, "_execute", lambda oid: executed.append(("worker", oid)))
        first = shell.dispatch_message(project, owner, root, message, "consult-uncertain-1")
        second = shell.reconcile_message(project, owner, message)
        shell.recover_completed()
        after = runtime.durable.operation_status(operation_id, owner)
        assert first["status"] == "uncertain"
        assert first["resent"] is False
        assert second["status"] == "uncertain"
        assert second["resent"] is False
        assert after["state"] == "UNCERTAIN"
        assert after["updated_at"] == before["updated_at"]
        assert observed == []
        assert executed == []
        with closing(runtime.control.store.connect("shell")) as db:
            row = db.execute("SELECT state FROM canvas_shell_queue WHERE operation_id=?",
                (operation_id,)).fetchone()
        assert row["state"] == "running"
    finally:
        canvas.__exit__(None, None, None)
