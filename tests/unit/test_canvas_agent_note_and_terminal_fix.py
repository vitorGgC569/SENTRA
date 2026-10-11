"""Regression: note -> CLI is readable, but does not grant writes or other powers.

The real CanvasServer and scoped agent capability are used with a controlled
fake PTY (never touches the user's active terminal/model sessions).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas
from sentra_canvas.store import Denied
from sentra_cli.canvas import CanvasBridge


class SafePTY:
    pid_counter=0
    def __init__(self,argv,cwd,append,**kwargs):
        type(self).pid_counter+=1
        self.pid=71000+type(self).pid_counter
        self._exit=None
    def poll(self):
        return self._exit
    def close(self,**kwargs):
        self._exit=0
    def write(self,data):
        pass


@pytest.fixture
def canvas(tmp_path,monkeypatch):
    monkeypatch.setattr("sentra_canvas.service.WindowsPTY",SafePTY)
    app=Canvas(tmp_path,max_terminals=4)
    server=CanvasServer(app,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        ws=app.create_workspace("NotesQA")["id"]
        origin=app.create_agent(ws,"Coordinator","sentra/codex/current",start=True)
        other=app.create_agent(ws,"Another","sentra/codex/current",start=True)
        token=next(t for t,(_,tid) in app._agent_tokens.items() if tid==origin["terminal_id"])
        monkeypatch.setenv("SENTRA_CANVAS_AGENT_TOKEN",token)
        monkeypatch.setenv("SENTRA_CANVAS_AGENT_PORT",str(server.server_port))
        bridge=CanvasBridge(SimpleNamespace(workspace=Path(app.store.workspace(ws)["path"])))
        assert bridge.is_available
        yield app,ws,origin,other,bridge
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        app.shutdown()


def test_note_directed_to_cli_reaches_context_and_can_be_read_only(canvas):
    app,ws,origin,other,bridge=canvas
    snap=app.graph_detail(ws)
    agent_node=next(n for n in snap["nodes"] if n["kind"]=="agent" and n["resource_id"]==origin["id"])
    note=app.graph_note(ws,"Instructions","Read this context only; do not edit it.")
    app.graph_link(ws,note["id"],agent_node["id"])  # user's actual direction

    context=bridge.working_context()
    notes={n["id"]:n for n in context["notes"]}
    assert note["id"] in notes
    assert notes[note["id"]]["title"]=="Instructions"
    assert notes[note["id"]]["body"]=="Read this context only; do not edit it."
    assert any(c["id"]==note["id"] and c["access"]=="read_only" for c in context["connections"])

    available=json.loads(bridge.execute("list",None))
    entry=next(x for x in available if x["id"]==note["id"])
    assert entry["direction"]=="incoming" and entry["access"]=="read_only"

    read=json.loads(bridge.execute("note_read|"+note["id"],None))
    assert read["body"]==notes[note["id"]]["body"]
    assert read["access"]=="read_only"
    with pytest.raises(RuntimeError,match="HTTP 403"):
        bridge.execute("note_write|"+note["id"]+"|illegal edit","invalid-note-write")
    assert next(n for n in app.graph.snapshot(ws)["nodes"] if n["id"]==note["id"])["body"]==notes[note["id"]]["body"]


def test_other_agent_or_unconnected_notes_are_not_visible(canvas):
    app,ws,origin,other,bridge=canvas
    graph=app.graph_detail(ws)
    other_node=next(n for n in graph["nodes"] if n["kind"]=="agent" and n["resource_id"]==other["id"])
    foreign=app.graph_note(ws,"OtherSecret","DO_NOT_LEAK_OTHER_AGENT_NOTE")
    invisible=app.graph_note(ws,"Disconnected","DO_NOT_LEAK_DISCONNECTED_NOTE")
    app.graph_link(ws,foreign["id"],other_node["id"])
    context=json.dumps(bridge.working_context(),ensure_ascii=False)
    assert "DO_NOT_LEAK_" not in context
    lst=json.loads(bridge.execute("list",None))
    assert not any(n["id"] in {foreign["id"],invisible["id"]} for n in lst)
    for x in (foreign,invisible):
        with pytest.raises(RuntimeError,match="HTTP 403"):
            bridge.execute("note_read|"+x["id"],None)


def test_outgoing_note_retains_explicit_write_permission(canvas):
    app,ws,origin,other,bridge=canvas
    graph=app.graph_detail(ws)
    source=next(n for n in graph["nodes"] if n["kind"]=="agent" and n["resource_id"]==origin["id"])
    note=app.graph_note(ws,"Writable","old")
    app.graph_link(ws,source["id"],note["id"])
    assert json.loads(bridge.execute("note_read|"+note["id"],None))["body"]=="old"
    bridge.execute("note_write|"+note["id"]+"|updated", "note-update-1")
    assert next(n for n in app.graph.snapshot(ws)["nodes"] if n["id"]==note["id"])["body"]=="updated"


def test_cli_invalid_name_gets_useful_safe_400_and_valid_creation_connects(canvas):
    app,ws,origin,other,bridge=canvas
    with pytest.raises(RuntimeError,match=r"HTTP 400.*name must be 1-48 ASCII"):
        bridge.execute("create_terminal|Terminal 1|sentra/codex/current","invalid-id-1")
    assert all(t["name"]!="Terminal 1" for t in app.store.list_resources("terminals",ws))

    created=json.loads(bridge.execute(
        "create_terminal|Terminal_4|sentra/codex/current","valid-id-2"))
    assert created["status"]=="started" and created["resource"]["name"]=="Terminal_4"
    graph=app.graph_detail(ws)
    source=next(n for n in graph["nodes"] if n["kind"]=="agent" and n["resource_id"]==origin["id"])
    target=next(n for n in graph["nodes"] if n["kind"]=="terminal"
                and n["resource_id"]==created["resource"]["id"])
    assert any(link["source"]==source["id"] and link["target"]==target["id"]
               for link in graph["links"])


def test_canvas_bridge_does_not_expose_arbitrary_server_error(monkeypatch,tmp_path):
    import io
    token="b"*48
    monkeypatch.setenv("SENTRA_CANVAS_AGENT_TOKEN",token)
    monkeypatch.setenv("SENTRA_CANVAS_AGENT_PORT","19000")
    bridge=CanvasBridge(SimpleNamespace(workspace=tmp_path))
    secret="DO_NOT_LEAK_SERVER_SECRET"
    class Opener:
        def open(self,*args,**kwargs):
            raise urllib.error.HTTPError(
                "http://127.0.0.1:19000/api/agent/control",
                400,"Bad Request",hdrs={},
                fp=io.BytesIO(json.dumps({"error":secret}).encode()))
    monkeypatch.setattr(urllib.request,"build_opener",lambda *a:Opener())
    with pytest.raises(RuntimeError) as err:
        bridge.execute("create_terminal|Terminal_4|sentra/codex/current","req-3")
    assert "HTTP 400" in str(err.value)
    assert secret not in str(err.value)



def test_note_pointing_to_terminal_not_agent_reaches_cli_context(canvas):
    app,ws,origin,other,bridge=canvas
    graph=app.graph_detail(ws)
    target=next(n for n in graph["nodes"]
                if n["kind"]=="terminal" and n["resource_id"]==origin["terminal_id"])
    note=app.graph_note(ws,"OwnerNote","User-directed terminal note reaches CLI.")
    app.graph_link(ws,note["id"],target["id"])
    result=bridge.working_context()
    assert any(n["id"]==note["id"] and
               "User-directed terminal note" in n["body"] for n in result["notes"])
    assert json.loads(bridge.execute("note_read|OwnerNote",None))["body"]==note["body"]
    with pytest.raises(RuntimeError,match="HTTP 403"):
        bridge.execute("note_write|OwnerNote|not-authorized","qa-deny-note-edit")
    assert next(n for n in app.graph.snapshot(ws)["nodes"] if n["id"]==note["id"])["body"]==note["body"]
