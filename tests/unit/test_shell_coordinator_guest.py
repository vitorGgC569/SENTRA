"""A Dot with a VM runs its coordinator in that guest, not as a host process."""
from __future__ import annotations

import json
import uuid
from contextlib import closing

from sentra_canvas.shell_dot_vm import VmStore
from sentra_core.conversations import _decode
from test_sentra_runtime_canvas_center_http import request, running_canvas


SECRET = "dot-registry-secret-not-for-receipt"
VM_ID = "owned-guest-vm"


def _canvas(tmp_path, monkeypatch):
    canvas = running_canvas(tmp_path)
    app, server = canvas.__enter__()
    monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/chatgpt-web/gpt-6"]})
    project = app.create_workspace("CoordinatorGuest")["id"]
    runtime = app._runtime()
    run = runtime.run(project)
    if run["state"] != "RUNNING":
        runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
    home = app.shell_bridge({"action": "home", "project_id": project})["value"]
    space_id = home["space"]["space_id"]

    def call(action, **fields):
        code, body = request(server, "/api/shell/bridge", json_body={
            "action": action, "project_id": project, "space_id": space_id,
            "request_key": "guest-coord-" + uuid.uuid4().hex, **fields})
        assert code == 200, body
        assert body["ok"] is True, body
        return body["value"]

    return canvas, app, project, call


def _reserve(app, project, root, **extra):
    shell = app._shell_runtime
    VmStore(shell.control, shell.owner).reserve(project, root["dot_id"], {
        "cpus": 1, "memory_mb": 1024, "vm_id": VM_ID, "username": "sentra",
        "os_family": "linux", "root_dot_id": root["dot_id"], **extra,
    })


def _turn(shell, sent):
    with closing(shell.control.store.connect("shell")) as db:
        row = db.execute("SELECT protected_input FROM canvas_shell_queue WHERE operation_id=?",
            (sent["operation_id"],)).fetchone()
    payload = _decode(row["protected_input"])
    shell._execute_locked(sent["operation_id"], payload["message"], payload["dot"])
    return shell.control.durable.operation_status(sent["operation_id"], shell.owner)


def test_coordinator_with_a_dot_vm_stays_in_the_guest(tmp_path, monkeypatch):
    canvas, app, project, call = _canvas(tmp_path, monkeypatch)
    try:
        shell = app._shell_runtime
        monkeypatch.setattr(shell, "_execute", lambda _oid: None)

        def refuse_host(*_args, **_kwargs):
            raise AssertionError("coordinator started on the host")

        monkeypatch.setattr("sentra_canvas.shell_runtime.TaskProcess", refuse_host)
        calls = []

        class Guest:
            proven_guest = True
            execution_surface = "guest"

            def execute(self, request):
                calls.append(dict(request))
                return {
                    "stdout": "plano pronto",
                    "exit_code": 0,
                    "execution_surface": "guest",
                    "host_subprocess": False,
                    "claims_guest_execution": True,
                }

        monkeypatch.setattr("sentra_canvas.shell_dot_canvas._guest_terminal_executor", lambda _record: Guest())
        root = call("dot_create", name="Coord", role="coordinator", model="sentra/chatgpt-web/gpt-6")
        _reserve(app, project, root, password=SECRET)
        conversation = call("conversation_create", dot_id=root["dot_id"])
        sent = call("message_send", conversation_id=conversation["conversation_id"], content="planeje o projeto")
        operation = _turn(shell, sent)
        blob = json.dumps(operation, default=str)
        assert SECRET not in blob
        assert "password" not in blob
        assert calls and calls[0]["placement"] == "guest"
        assert calls[0]["tool"] == "sentra-cli"
        assert calls[0]["guest_workspace"] == "/home/sentra"
        assert calls[0]["vm_id"] == VM_ID
        assert "password" not in calls[0]
        assert SECRET not in json.dumps(calls)
        assert operation["state"] == "SUCCEEDED"
        assert operation["result"]["execution_surface"] == "guest"
        assert operation["result"]["host_subprocess"] is False
        assert operation["result"]["protected_journal"] is False
        assert operation["result"]["receipt_id"] == "guest:" + VM_ID + ":" + sent["operation_id"]
    finally:
        canvas.__exit__(None, None, None)


def test_coordinator_guest_failure_is_not_published(tmp_path, monkeypatch):
    canvas, app, project, call = _canvas(tmp_path, monkeypatch)
    try:
        shell = app._shell_runtime
        monkeypatch.setattr(shell, "_execute", lambda _oid: None)

        def refuse_host(*_args, **_kwargs):
            raise AssertionError("coordinator started on the host")

        monkeypatch.setattr("sentra_canvas.shell_runtime.TaskProcess", refuse_host)

        class Guest:
            proven_guest = True
            execution_surface = "guest"

            def execute(self, request):
                return {
                    "stdout": "plano pronto",
                    "exit_code": 1,
                    "execution_surface": "guest",
                    "host_subprocess": False,
                    "claims_guest_execution": True,
                }

        monkeypatch.setattr("sentra_canvas.shell_dot_canvas._guest_terminal_executor", lambda _record: Guest())
        root = call("dot_create", name="Coord", role="coordinator", model="sentra/chatgpt-web/gpt-6")
        _reserve(app, project, root, password=SECRET)
        conversation = call("conversation_create", dot_id=root["dot_id"])
        sent = call("message_send", conversation_id=conversation["conversation_id"], content="planeje o projeto")
        operation = _turn(shell, sent)
        assert operation["state"] == "UNCERTAIN"
        assert operation["progress"]["automatic_retry"] is False
        assert operation["progress"]["host_subprocess"] is False
        assert (operation.get("result") or {}).get("receipt_id") is None
    finally:
        canvas.__exit__(None, None, None)


def test_coordinator_does_not_publish_an_uncertain_guest_result(tmp_path, monkeypatch):
    canvas, app, project, call = _canvas(tmp_path, monkeypatch)
    try:
        shell = app._shell_runtime
        monkeypatch.setattr(shell, "_execute", lambda _oid: None)

        def refuse_host(*_args, **_kwargs):
            raise AssertionError("coordinator started on the host")

        monkeypatch.setattr("sentra_canvas.shell_runtime.TaskProcess", refuse_host)

        class Guest:
            proven_guest = True
            execution_surface = "guest"

            def execute(self, request):
                return {
                    "stdout": "plano pronto",
                    "exit_code": 0,
                    "execution_surface": "guest",
                    "host_subprocess": False,
                    "claims_guest_execution": True,
                    "execution_uncertain": True,
                }

        monkeypatch.setattr("sentra_canvas.shell_dot_canvas._guest_terminal_executor", lambda _record: Guest())
        root = call("dot_create", name="Coord", role="coordinator", model="sentra/chatgpt-web/gpt-6")
        _reserve(app, project, root, password=SECRET)
        conversation = call("conversation_create", dot_id=root["dot_id"])
        sent = call("message_send", conversation_id=conversation["conversation_id"], content="planeje o projeto")
        operation = _turn(shell, sent)
        assert operation["state"] == "UNCERTAIN"
        assert operation["progress"]["automatic_retry"] is False
        assert (operation.get("result") or {}).get("receipt_id") is None
        assert SECRET not in json.dumps(operation, default=str)
    finally:
        canvas.__exit__(None, None, None)


def test_coordinator_without_guest_proof_does_not_start_on_the_host(tmp_path, monkeypatch):
    canvas, app, project, call = _canvas(tmp_path, monkeypatch)
    try:
        shell = app._shell_runtime
        monkeypatch.setattr(shell, "_execute", lambda _oid: None)

        def refuse_host(*_args, **_kwargs):
            raise AssertionError("coordinator started on the host")

        monkeypatch.setattr("sentra_canvas.shell_runtime.TaskProcess", refuse_host)

        class Guest:
            proven_guest = True
            execution_surface = "guest"

            def execute(self, request):
                return {"stdout": "ok", "execution_surface": "guest", "host_subprocess": True,
                    "claims_guest_execution": True}

        monkeypatch.setattr("sentra_canvas.shell_dot_canvas._guest_terminal_executor", lambda _record: Guest())
        root = call("dot_create", name="Coord", role="coordinator", model="sentra/chatgpt-web/gpt-6")
        _reserve(app, project, root, password=SECRET)
        conversation = call("conversation_create", dot_id=root["dot_id"])
        sent = call("message_send", conversation_id=conversation["conversation_id"], content="planeje o projeto")
        operation = _turn(shell, sent)
        assert SECRET not in json.dumps(operation, default=str)
        assert operation["state"] == "UNCERTAIN"
        assert operation["progress"]["automatic_retry"] is False
        assert operation["progress"]["host_subprocess"] is False
        assert operation["result"] is None or "receipt_id" not in (operation.get("result") or {})
    finally:
        canvas.__exit__(None, None, None)


def test_incomplete_dot_vm_does_not_start_the_coordinator_on_the_host(tmp_path, monkeypatch):
    canvas, app, project, call = _canvas(tmp_path, monkeypatch)
    try:
        shell = app._shell_runtime
        monkeypatch.setattr(shell, "_execute", lambda _oid: None)

        def refuse_host(*_args, **_kwargs):
            raise AssertionError("coordinator started on the host")

        monkeypatch.setattr("sentra_canvas.shell_runtime.TaskProcess", refuse_host)

        def refuse_executor(_record):
            raise AssertionError("guest executor was built without credentials")

        monkeypatch.setattr("sentra_canvas.shell_dot_canvas._guest_terminal_executor", refuse_executor)
        root = call("dot_create", name="Coord", role="coordinator", model="sentra/chatgpt-web/gpt-6")
        _reserve(app, project, root)
        conversation = call("conversation_create", dot_id=root["dot_id"])
        sent = call("message_send", conversation_id=conversation["conversation_id"], content="planeje o projeto")
        operation = _turn(shell, sent)
        assert operation["state"] == "UNCERTAIN"
        assert operation["progress"]["automatic_retry"] is False
        assert operation["progress"]["host_subprocess"] is False
        assert operation["progress"]["execution_surface"] == "blocked"
    finally:
        canvas.__exit__(None, None, None)
