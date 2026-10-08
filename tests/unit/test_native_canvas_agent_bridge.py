"""Exercise the real Canvas HTTP broker and SENTRA CLI under Windows ConPTY."""
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas

pytestmark=pytest.mark.skipif(os.name!="nt",reason="actual Windows ConPTY and DPAPI")


def wait_until(check,timeout=15):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if check():return
        time.sleep(.05)
    raise AssertionError("real Canvas/CLI condition did not complete")


def post(server,token,path,body):
    request=urllib.request.Request(f"http://127.0.0.1:{server.server_port}"+path,
        data=json.dumps(body).encode(),headers={"Authorization":"Bearer "+token,
                                                "Content-Type":"application/json"})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=5) as response:return json.load(response)


def test_real_cli_native_coordination_and_scoped_capability(tmp_path):
    app=Canvas(tmp_path)
    server=CanvasServer(app)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        ws=app.create_workspace("native_coordination")["id"]
        other=app.create_workspace("other")["id"]
        source=app.create_agent(ws,"coordinator","sentra/model",start=True)
        target=app.create_agent(ws,"worker","sentra/model",start=True)
        graph=app.graph_detail(ws)
        origin=next(n for n in graph["nodes"] if n["kind"]=="agent" and n["resource_id"]==source["id"])
        receiver=next(n for n in graph["nodes"] if n["kind"]=="agent" and n["resource_id"]==target["id"])
        note=app.graph_note(ws,"shared_note","initial context")
        hidden=app.graph_note(ws,"hidden_note","not connected")
        app.graph_link(ws,origin["id"],receiver["id"])
        app.graph_link(ws,origin["id"],note["id"])
        token=next(t for t,(_,ident) in app._agent_tokens.items() if ident==source["terminal_id"])
        workspace=app.store.workspace(ws)["path"]
        payload={"workspace":workspace,"action":"list"}
        listed=post(server,token,"/api/agent/control",payload)
        assert {x["id"] for x in listed}=={note["id"],receiver["id"]}
        for rejected_token,path,body in (
            (server.secret,"/api/agent/control",payload),
            (token,"/api/runtime/shutdown",{"confirm":True}),
            (token,"/api/agent/control",{**payload,"workspace":app.store.workspace(other)["path"]}),
            (token,"/api/agent/control",{**payload,"action":"note_read","value":hidden["id"]}),
        ):
            with pytest.raises(urllib.error.HTTPError) as exc:
                post(server,rejected_token,path,body)
            assert exc.value.code in (401,403)

        # Genuine interactive CLI receives its private environment via CreateProcessW.
        # These are real direct tools, deliberately making no model-inference claim.
        source_terminal=source["terminal_id"]
        app.terminal_input(ws,source_terminal,
            f"[[CANVAS|note_write|{note['id']}|context from real CLI]]\r")
        wait_until(lambda:next(n for n in app.graph.snapshot(ws)["nodes"]
                              if n["id"]==note["id"])["body"]=="context from real CLI")
        effect=Path(workspace)/"native_effect.txt"
        app.terminal_input(ws,source_terminal,
            f"[[CANVAS|dispatch|{receiver['id']}|[[W|native_effect.txt|NATIVE_CANVAS_REAL_CLI]]]]\r")
        wait_until(effect.is_file)
        assert effect.read_text()=="NATIVE_CANVAS_REAL_CLI"
        rows=app.graph.handoffs(ws)
        assert len(rows)==1 and rows[0]["status"]=="sent" and rows[0]["request_key"]
        # Repeating the same persistent delivery identity never submits again.
        replay=post(server,token,"/api/agent/control",{
            **payload,"action":"dispatch","value":receiver["id"]+"|"+rows[0]["content"],
            "request_key":rows[0]["request_key"]})
        assert replay["idempotent_replay"] and not replay["model_acknowledged"]
        assert len(app.graph.handoffs(ws))==1
        group=app.create_team(ws,"native_team",source["id"],[target["id"]])
        app.graph_link(ws,receiver["id"],note["id"])
        task=app.delegate(ws,group["id"],target["id"],
            f"[[CANVAS|note_write|{note['id']}|context from real queued task]]",
            "native-task-context","sentra-cli",True)
        wait_until(lambda:app.store.resource("tasks",task["id"],ws)["status"]=="succeeded")
        assert next(n for n in app.graph.snapshot(ws)["nodes"] if n["id"]==note["id"])["body"]=="context from real queued task"
        wait_until(lambda:not any(identity=="task:"+task["id"] for _,identity in app._agent_tokens.values()))
        app.terminal_close(ws,source_terminal)
        with pytest.raises(urllib.error.HTTPError) as exc:
            post(server,token,"/api/agent/control",payload)
        assert exc.value.code==403
        assert token not in app.terminal_output(ws,target["terminal_id"])["text"]
    finally:
        server.shutdown();thread.join(5);server.server_close();app.shutdown()
