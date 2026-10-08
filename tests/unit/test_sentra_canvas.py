"""Native SENTRA Canvas contract and Windows end-to-end tests."""
from __future__ import annotations
import http.client
import json
import os
import threading
import time
from pathlib import Path
import pytest
from sentra_canvas.service import Canvas
from sentra_canvas.store import Denied, Store
from sentra_canvas.__main__ import CanvasServer

@pytest.fixture
def canvas(tmp_path):
    app=Canvas(tmp_path)
    try:
        yield app
    finally:
        app.shutdown()

def test_persistent_namespaces_and_isolation(canvas):
    w1=canvas.create_workspace("projeto_A")
    w2=canvas.create_workspace("projeto_B")
    assert w1["id"] != w2["id"]
    assert Path(w1["path"]).parent == Path(w2["path"]).parent
    assert Path(w1["path"]).is_dir()
    assert len(canvas.workspaces())==2
    with pytest.raises(ValueError):
        canvas.create_workspace("../escape")
    with pytest.raises(ValueError):
        canvas.create_workspace("projeto_A")
    a1=canvas.create_agent(w1["id"],"AgentA","sentra/chatgpt-web/high")
    a2=canvas.create_agent(w1["id"],"AgentB","sentra/chatgpt-web/high")
    a3=canvas.create_agent(w1["id"],"AgentC","sentra/chatgpt-web/high")
    with pytest.raises(Denied):
        canvas.store.resource("agents",a1["id"],w2["id"])
    with pytest.raises(Denied):
        canvas.create_team(w2["id"],"bad",a1["id"],[a2["id"]])
    team=canvas.create_team(w1["id"],"equipe",a1["id"],[a2["id"],a3["id"]])
    members=canvas.team_members(w1["id"],team["id"])
    assert {m["team_role"] for m in members}=={"coordinator","worker"}
    with pytest.raises(Denied):
        canvas.team_members(w2["id"],team["id"])
    assert any(e["kind"]=="team.created" for e in canvas.store.events(w1["id"]))

def test_async_delegation_idempotency_and_approval(canvas):
    ws=canvas.create_workspace("dev")
    a=canvas.create_agent(ws["id"],"coord","modelo/test")
    b=canvas.create_agent(ws["id"],"worker","modelo/test")
    team=canvas.create_team(ws["id"],"time",a["id"],[b["id"]])
    with pytest.raises(Denied):
        canvas.delegate(ws["id"],team["id"],b["id"],"modificar fonte","real",
                        provider="sentra-cli")
    first=canvas.delegate(ws["id"],team["id"],b["id"],"tarefa simulada","req-1")
    second=canvas.delegate(ws["id"],team["id"],b["id"],"tarefa simulada","req-1")
    assert first["id"]==second["id"]
    with pytest.raises(ValueError):
        canvas.delegate(ws["id"],team["id"],b["id"],"outra tarefa","req-1")
    for _ in range(50):
        row=canvas.store.resource("tasks",first["id"],ws["id"])
        if row["status"]=="succeeded":break
        time.sleep(.02)
    assert row["status"]=="succeeded"
    assert "PROVEDOR DE TESTE" in row["result"]
    with pytest.raises(Denied):
        canvas.store.resource("tasks",first["id"],"outra-workspace")
    assert any(e["kind"]=="task.succeeded" for e in canvas.store.events(ws["id"]))

def test_reopen_recovers_only_persisted_metadata(tmp_path):
    db=tmp_path/"canvas.sqlite"
    projects=tmp_path/"projects";projects.mkdir()
    first=Store(db,projects)
    ws=first.create_workspace("Persistente")
    terminal=first.create_terminal(ws["id"],"shell","cmd")
    first.terminal_state(ws["id"],terminal["id"],"running",pid=999999)
    first.close()
    second=Store(db,projects)
    row=second.resource("terminals",terminal["id"],ws["id"])
    assert row["status"]=="interrupted"
    assert row["pid"] is None
    assert len(second.workspaces())==1
    second.close()

@pytest.mark.skipif(os.name!="nt",reason="requires native Windows ConPTY")
def test_windows_three_real_terminals_and_isolation(canvas):
    w1=canvas.create_workspace("area_A")["id"]
    w2=canvas.create_workspace("area_B")["id"]
    terminals=[
        canvas.create_terminal(w1,"cmd_a","cmd"),
        canvas.create_terminal(w1,"cmd_b","cmd"),
        canvas.create_terminal(w2,"cmd_c","cmd")
    ]
    assert len({t["pid"] for t in terminals})==3
    for ws,t in [(w1,terminals[0]),(w1,terminals[1]),(w2,terminals[2])]:
        assert t["status"]=="running"
        canvas.terminal_input(ws,t["id"],"echo E2E_"+t["name"]+"\r")
    deadline=time.time()+7
    for ws,t in [(w1,terminals[0]),(w1,terminals[1]),(w2,terminals[2])]:
        while time.time()<deadline:
            output=canvas.terminal_output(ws,t["id"])["text"]
            if "E2E_"+t["name"] in output:break
            time.sleep(.1)
        assert "E2E_"+t["name"] in output
    with pytest.raises(Denied):
        canvas.terminal_input(w2,terminals[0]["id"],"echo CROSS\r")
    canvas.terminal_resize(w1,terminals[0]["id"],120,30)
    for ws,t in [(w1,terminals[0]),(w1,terminals[1]),(w2,terminals[2])]:
        canvas.terminal_close(ws,t["id"])
    assert all(t["status"]=="closed" for t in canvas.store.list_resources("terminals",w1))

@pytest.mark.skipif(os.name!="nt",reason="requires real Windows CLI/ConPTY")
def test_two_independent_cli_sessions(canvas):
    ws=canvas.create_workspace("cli_project")["id"]
    a=canvas.create_agent(ws,"cli_alpha","sentra/chatgpt-web/high",start=True)
    b=canvas.create_agent(ws,"cli_beta","sentra/chatgpt-web/high",start=True)
    assert a["terminal_id"] != b["terminal_id"]
    ids=[a["terminal_id"],b["terminal_id"]]
    assert all(canvas.store.resource("terminals",i,ws)["pid"] for i in ids)
    deadline=time.time()+12
    outputs={}
    while time.time()<deadline:
        outputs={i:canvas.terminal_output(ws,i)["text"] for i in ids}
        if all("SENTRA CLI" in s or "Workspace:" in s for s in outputs.values()):
            break
        time.sleep(.2)
    assert all("SENTRA CLI" in s or "Workspace:" in s for s in outputs.values()), outputs
    for i in ids: canvas.terminal_close(ws,i)

def test_loopback_authentication_and_origin(canvas):
    server=CanvasServer(canvas)
    t=threading.Thread(target=server.serve_forever,daemon=True)
    t.start()
    port=server.server_port
    def request(method,path,body=None,token=None,origin=None,host=None):
        conn=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
        headers={}
        if token:headers["Authorization"]="Bearer "+token
        if origin:headers["Origin"]=origin
        if host:headers["Host"]=host
        if body is not None:headers["Content-Type"]="application/json"
        conn.request(method,path,json.dumps(body).encode() if body is not None else None,headers)
        res=conn.getresponse()
        data=res.read()
        status=res.status
        conn.close()
        return status,json.loads(data) if "application/json" in res.getheader("Content-Type","") else data
    try:
        assert request("GET","/api/workspaces")[0]==401
        assert request("GET","/api/workspaces",token="incorrect")[0]==401
        assert request("GET","/api/workspaces",token=server.secret,
                       origin="https://malicious.example")[0]==403
        assert request("GET","/api/workspaces",token=server.secret,
                       host="evil.example")[0]==403
        assert request("GET","/")[0]==200
        status,ws=request("POST","/api/workspaces",{"name":"via_api"},server.secret)
        assert status==200 and ws["name"]=="via_api"
        status,detail=request("GET","/api/workspace?ws="+ws["id"],token=server.secret)
        assert status==200 and detail["workspace"]["id"]==ws["id"]
        assert request("POST","/api/workspaces",{"name":"../escape"},server.secret)[0]==400
        assert request("POST","/api/terminal/input",{"ws":ws["id"],"id":"untrusted","data":"echo x"},
                       server.secret)[0]==403
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=3)

def test_namespaces_are_stable_and_valid(canvas):
    from sentra_canvas.namespaces import Namespace
    ws=canvas.create_workspace("namespace_ok")
    agent=canvas.create_agent(ws["id"],"implementer","sentra/model")
    root=Namespace(ws["id"])
    child=Namespace(ws["id"],agent=agent["id"])
    assert root.path == "workspace/"+ws["id"]
    assert child.path == root.path+"/agent/"+agent["id"]
    assert canvas.workspace_detail(ws["id"])["agents"][0]["namespace"]==child.path
    with pytest.raises(ValueError):
        Namespace("../other",agent=agent["id"])
    with pytest.raises(ValueError):
        Namespace(ws["id"],task=agent["id"])

def test_exclusive_runtime_instance_lock(tmp_path):
    first=Canvas(tmp_path)
    try:
        with pytest.raises(RuntimeError,match="already running"):
            Canvas(tmp_path)
    finally:
        first.shutdown()
    second=Canvas(tmp_path)
    second.shutdown()

def test_process_quota_and_missing_shell_are_fail_closed(tmp_path):
    app=Canvas(tmp_path,max_terminals=1)
    try:
        ws=app.create_workspace("only_one")["id"]
        if os.name=="nt":
            one=app.create_terminal(ws,"first","cmd")
            with pytest.raises(ValueError,match="concurrency quota"):
                app.create_terminal(ws,"second","cmd")
            assert app.store.list_resources("terminals",ws)[0]["pid"]==one["pid"]
            app.terminal_close(ws,one["id"])
        with pytest.raises(ValueError,match="unsupported shell"):
            app.create_terminal(ws,"evil","bash")
    finally:
        app.shutdown()

def test_workspace_owner_denied(tmp_path):
    state=tmp_path/"db.sqlite"
    root=tmp_path/"root"
    root.mkdir()
    a=Store(state,root,principal="original")
    workspace=a.create_workspace("original_project")["id"]
    a.close()
    b=Store(state,root,principal="different")
    with pytest.raises(Denied):
        b.workspace(workspace)
    assert b.workspaces()==[]
    b.close()

@pytest.mark.skipif(os.name!="nt",reason="requires real Windows ConPTY")
def test_terminal_rename_duplicate_and_workspace_permissions(canvas):
    ws1=canvas.create_workspace("rdev")["id"]
    ws2=canvas.create_workspace("rother")["id"]
    original=canvas.create_terminal(ws1,"source","cmd")
    try:
        renamed=canvas.terminal_rename(ws1,original["id"],"renamed")
        assert renamed["name"]=="renamed" and renamed["pid"]==original["pid"]
        duplicate=canvas.terminal_duplicate(ws1,original["id"],"separate")
        try:
            assert duplicate["pid"] != original["pid"]
            assert duplicate["shell"]=="cmd"
            with pytest.raises(ValueError):
                canvas.terminal_rename(ws1,original["id"],"separate")
            with pytest.raises(Denied):
                canvas.terminal_duplicate(ws2,original["id"],"unauthorized")
            assert any(e["kind"]=="terminal.renamed" for e in canvas.store.events(ws1))
        finally:
            canvas.terminal_close(ws1,duplicate["id"])
    finally:
        canvas.terminal_close(ws1,original["id"])

def test_audit_search_is_scoped_and_safe(canvas):
    left=canvas.create_workspace("audit_left")["id"]
    right=canvas.create_workspace("audit_right")["id"]
    canvas.store.event(left,"session1","terminal.renamed","renomeacao")
    canvas.store.event(right,"session2","terminal.renamed","segredo_do_outro")
    filtered=canvas.store.events(left,search="renomeacao")
    assert len(filtered)==1 and filtered[0]["detail"]=="renomeacao"
    assert canvas.store.events(left,search="segredo_do_outro")==[]
    assert canvas.store.events(left,search="%' OR 1=1 --")==[]
    with pytest.raises(ValueError):
        canvas.store.events(left,search="A"*121)
