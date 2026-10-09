"""Scoped CLI recruitment contracts and actual Windows ConPTY coordination."""
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas
from sentra_canvas.store import Denied
from sentra_cli.canvas import CanvasBridge
from sentra_cli.agent import SentraAgent
from sentra_cli.config import CLIConfig
from sentra_core.conversations import ConversationStore


class FakePTY:
    """Contract double only; the ConPTY acceptance test below uses real children."""
    count=0

    def __init__(self,argv,cwd,append,**kwargs):
        type(self).count+=1
        self.pid=90000+type(self).count
        self.exit=None
        self.writes=[]

    def poll(self):return self.exit
    def close(self,**kwargs):self.exit=0
    def write(self,data):self.writes.append(data)


@pytest.fixture
def scoped(tmp_path,monkeypatch):
    monkeypatch.setattr("sentra_canvas.service.WindowsPTY",FakePTY)
    app=Canvas(tmp_path,principal="alice",max_terminals=4)
    app._agent_port=12345
    ws=app.create_workspace("project")["id"]
    agent=app.create_agent(ws,"coordinator","sentra/model",start=True)
    token=next(t for t,(_,ident) in app._agent_tokens.items() if ident==agent["terminal_id"])
    def call(action,value="",key="request",capability=token):
        return app.agent_control(capability,{"workspace":app.store.workspace(ws)["path"],
            "action":action,"value":value,"request_key":key})
    try:yield app,ws,agent,token,call
    finally:app.shutdown()


def test_recruitment_replay_pairs_team_and_quota(scoped):
    app,ws,coordinator,token,call=scoped
    first=call("create_agent","worker_a|sentra/model|worker","create-a")
    second=call("create_agent","worker_b|sentra/model","create-b")
    replay=call("create_agent","worker_a|sentra/model|worker","create-a")
    assert replay["idempotent_replay"] and replay["resource"]==first["resource"]
    assert not first["model_acknowledged"]
    assert len(app._sessions)==3
    listed=call("list")
    assert {n["id"] for n in listed}=={first["node_id"],second["node_id"]}
    origin=next(n for n in app.graph.snapshot(ws)["nodes"] if n["kind"]=="agent"
                and n["resource_id"]==coordinator["id"])
    assert first["link"]["source"]==origin["id"]
    paired=call("connect",first["node_id"]+"|"+second["node_id"],"pair")
    assert paired["link"]["source"]==first["node_id"]
    assert call("connect",first["node_id"]+"|"+second["node_id"],"pair")["idempotent_replay"]
    team=call("create_team","qa_team|"+coordinator["id"]+"|"+
              first["node_id"]+","+second["node_id"],"team")
    assert len(app.team_members(ws,team["resource"]["id"]))==3
    assert call("create_team","qa_team|"+coordinator["id"]+"|"+
                first["node_id"]+","+second["node_id"],"team")["idempotent_replay"]
    terminal=call("create_terminal","extra_cli|sentra/model","terminal")
    assert terminal["resource"]["shell"]=="sentra-cli"
    assert terminal["resource"]["conversation_id"]
    with pytest.raises(ValueError,match="quota"):
        call("create_agent","overflow|sentra/model","overflow")
    assert len(app.store.list_resources("agents",ws))==3
    with pytest.raises(ValueError,match="collision"):
        call("create_agent","changed|sentra/model","create-a")
    with pytest.raises(ValueError,match="already exists"):
        call("create_agent","worker_a|sentra/model","different-request")
    with pytest.raises(ValueError,match="identity"):
        call("connect",first["node_id"],None)


def test_capability_cannot_recruit_cross_workspace_or_hijack_other_origins(scoped):
    app,ws,coordinator,token,call=scoped
    other=app.create_workspace("other")["id"]
    with pytest.raises(Denied):
        app.agent_control(token,{"workspace":app.store.workspace(other)["path"],
            "action":"create_agent","value":"rogue|sentra/model","request_key":"rogue"})
    stranger=app.create_agent(ws,"stranger","sentra/model",start=True)
    state=app.graph_detail(ws)
    hidden=next(n for n in state["nodes"] if n["kind"]=="agent" and n["resource_id"]==stranger["id"])
    worker=call("create_agent","mine|sentra/model","mine")
    with pytest.raises(Denied):call("connect",hidden["id"],"hidden")
    source=next(n for n in state["nodes"] if n["kind"]=="agent" and n["resource_id"]==coordinator["id"])
    app.graph_link(ws,source["id"],hidden["id"])
    # A read/dispatch connection grants no ability to forge that peer's outbound links.
    with pytest.raises(Denied):call("connect",hidden["id"]+"|"+worker["node_id"],"hijack")
    stranger_token=next(t for t,(_,ident) in app._agent_tokens.items() if ident==stranger["terminal_id"])
    with pytest.raises(Denied):call("connect",worker["node_id"],"other-actor",stranger_token)
    app.store.principal="bob"
    try:
        with pytest.raises(Denied):
            app.agent_control(token,{"workspace":state["workspace"]["path"],"action":"list"})
    finally:app.store.principal="alice"
    app.terminal_close(ws,coordinator["terminal_id"])
    with pytest.raises(Denied):call("create_agent","closed|sentra/model","closed")


def test_uncertain_recruitment_never_spawns_again(scoped,monkeypatch):
    app,ws,coordinator,token,call=scoped
    original=app.create_agent
    spawns=[]
    def interrupted(*args,**kwargs):
        spawns.append(original(*args,**kwargs))
        raise OSError("failure after process creation")
    monkeypatch.setattr(app,"create_agent",interrupted)
    with pytest.raises(OSError):call("create_agent","partial|sentra/model","partial")
    replay=call("create_agent","partial|sentra/model","partial")
    assert replay["status"]=="uncertain" and replay["idempotent_replay"]
    assert not replay["model_acknowledged"] and len(spawns)==1


def test_coordinator_restart_keeps_worker_connections_and_dispatch(scoped):
    app,ws,coordinator,token,call=scoped
    created=[call("create_agent",name+"|sentra/model",name) for name in ("worker_a","worker_b")]
    app.terminal_close(ws,coordinator["terminal_id"])
    replacement=app.restart_agent(ws,coordinator["id"])
    new_token=next(t for t,(_,ident) in app._agent_tokens.items() if ident==replacement["terminal_id"])
    listed=call("list",capability=new_token)
    assert {n["id"] for n in listed}=={r["node_id"] for r in created}
    for index,result in enumerate(created):
        replay=call("create_agent",result["resource"]["name"]+"|sentra/model",
                    result["resource"]["name"],new_token)
        assert replay["idempotent_replay"] and replay["node_id"]==result["node_id"]
        dispatched=call("dispatch",result["node_id"]+"|restart message",str(index),new_token)
        assert dispatched["status"]=="sent"
        session=app._sessions[result["resource"]["terminal_id"]]
        assert session.pty.writes==[b"restart message\r"]
    assert len(app.store.list_resources("agents",ws))==3


def test_unattached_cli_uses_its_terminal_as_coordination_origin(scoped):
    app,ws,coordinator,token,call=scoped
    terminal=app._start(ws,"standalone","sentra-cli",["fake-cli"])
    own_token=next(t for t,(_,ident) in app._agent_tokens.items() if ident==terminal["id"])
    worker=call("create_agent","worker|sentra/model","standalone-worker",own_token)
    origin=next(n for n in app.graph.snapshot(ws)["nodes"] if n["kind"]=="terminal"
                and n["resource_id"]==terminal["id"])
    assert worker["link"]["source"]==origin["id"]
    assert [n["id"] for n in call("list",capability=own_token)]==[worker["node_id"]]


def test_request_survives_restart_and_actor_terminal_replacement(scoped,monkeypatch):
    app,ws,coordinator,token,call=scoped
    created=call("create_agent","durable|sentra/model","durable")
    root=app.project_dir
    app.shutdown()
    restored=Canvas(root,principal="alice")
    restored._agent_port=12345
    try:
        replacement=restored.restart_agent(ws,coordinator["id"])
        assert replacement["terminal_id"]!=coordinator["terminal_id"]
        new_token=next(t for t,(_,ident) in restored._agent_tokens.items() if ident==replacement["terminal_id"])
        def request(action,value,key):
            return restored.agent_control(new_token,{"workspace":restored.store.workspace(ws)["path"],
                "action":action,"value":value,"request_key":key})
        replay=request("create_agent","durable|sentra/model","durable")
        assert replay["idempotent_replay"] and replay["node_id"]==created["node_id"]
        assert replay["resource"]["conversation_id"]==created["resource"]["conversation_id"]
        assert len(restored._sessions)==1  # No worker automatically restarted by replay.
        assert {n["id"] for n in restored.agent_control(new_token,
            {"workspace":restored.store.workspace(ws)["path"],"action":"list"})}=={created["node_id"]}
        assert request("connect",created["node_id"],"reconnect")["status"]=="connected"
        # Simulate a crash between durable reservation and mutation/result commit.
        fingerprint=hashlib.sha256(json.dumps(["create_agent","crash|sentra/model"]).encode()).hexdigest()
        with restored.store.tx():
            restored.store.db.execute("INSERT INTO canvas_agent_requests VALUES(?,?,?,?,?,?,?,?)",
                ("alice",ws,"agent:"+coordinator["id"],"crash",fingerprint,"pending","{}",time.time()))
        pending=request("create_agent","crash|sentra/model","crash")
        assert pending["status"]=="uncertain" and len(restored._sessions)==1
    finally:restored.shutdown()


def test_frozen_cli_prefers_installed_sibling(tmp_path,monkeypatch):
    project=tmp_path/"workspace";project.mkdir()
    (project/"dist").mkdir()
    (project/"dist"/"sentra-cli.exe").write_bytes(b"stale build")
    sibling=tmp_path/"installed";sibling.mkdir()
    (sibling/"sentra-cli.exe").write_bytes(b"installed")
    app=Canvas(project)
    try:
        monkeypatch.setattr(sys,"frozen",True,raising=False)
        monkeypatch.setattr(sys,"executable",str(sibling/"sentra-canvas.exe"))
        assert app._cli_command(["--no-auto-start"])==[str(sibling/"sentra-cli.exe"),"--no-auto-start"]
        (sibling/"sentra-cli.exe").unlink()
        assert app._cli_command([])==[str(project/"dist"/"sentra-cli.exe")]
    finally:app.shutdown()


def test_bridge_preserves_persistent_request_and_canvas_prompt(tmp_path,monkeypatch):
    monkeypatch.setenv("SENTRA_CANVAS_AGENT_TOKEN","a"*48)
    monkeypatch.setenv("SENTRA_CANVAS_AGENT_PORT","12345")
    captured=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):return b'{"status":"started","model_acknowledged":false}'
    def open_request(request,timeout):
        captured.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(urllib.request,"build_opener",lambda *args:SimpleNamespace(open=open_request))
    bridge=CanvasBridge(SimpleNamespace(workspace=tmp_path))
    with pytest.raises(ValueError):bridge.execute("create_agent|worker|sentra/model",None)
    bridge.execute("create_agent|worker|sentra/model","durable-id")
    assert captured==[{"action":"create_agent","workspace":str(tmp_path),
        "value":"worker|sentra/model","request_key":"durable-id"}]
    agent=SentraAgent(CLIConfig(workspace=tmp_path,state_root=tmp_path/"state",auto_start_gateway=False))
    prompt=agent.messages[0]["content"]
    assert "[[CANVAS|create_agent|" in prompt and "[[CANVAS|create_team|" in prompt
    assert "[[MAESTRI|" not in prompt


def wait_until(check,timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if check():return
        time.sleep(.05)
    raise AssertionError("real CLI/ConPTY coordination timed out")


def post(server,token,body):
    request=urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/agent/control",
        data=json.dumps(body).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=8) as response:return json.load(response)


@pytest.mark.skipif(os.name!="nt",reason="actual Windows ConPTY/DPAPI")
def test_real_single_cli_recruits_two_workers_dispatches_and_preserves_history(tmp_path):
    # All processes, files, broker and persistence belong only to this QA instance.
    app=Canvas(tmp_path,max_terminals=4)
    server=CanvasServer(app)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    ws=None
    try:
        ws=app.create_workspace("qa_recruitment")["id"]
        root=Path(app.store.workspace(ws)["path"])
        coordinator=app.create_agent(ws,"coordinator","sentra/model",start=True)
        terminal=coordinator["terminal_id"]
        token=next(t for t,(_,ident) in app._agent_tokens.items() if ident==terminal)
        def command(value):app.terminal_input(ws,terminal,"[[CANVAS|"+value+"]]\r")
        # Recruitment is performed by the real interactive CLI, not by the test broker.
        for name in ("worker_a","worker_b"):
            command("create_agent|"+name+"|sentra/model|worker")
            wait_until(lambda:any(a["name"]==name for a in app.store.list_resources("agents",ws)))
        agents=app.store.list_resources("agents",ws)
        workers=[a for a in agents if a["id"]!=coordinator["id"]]
        assert len(workers)==2 and len({s.pty.pid for s in app._sessions.values()})==3
        graph=app.graph_detail(ws)
        nodes=[next(n for n in graph["nodes"] if n["kind"]=="agent" and n["resource_id"]==a["id"]) for a in workers]
        command("connect|"+nodes[0]["id"]+"|"+nodes[1]["id"])
        wait_until(lambda:any(l["source"]==nodes[0]["id"] and l["target"]==nodes[1]["id"]
                              for l in app.graph.snapshot(ws)["links"]))
        command("create_team|qa_team|"+coordinator["id"]+"|"+",".join(n["id"] for n in nodes))
        wait_until(lambda:len(app.store.list_resources("teams",ws))==1)
        for index,node in enumerate(nodes):
            marker="REAL_WORKER_"+str(index)
            command("dispatch|"+node["id"]+"|[[W|worker_"+str(index)+".txt|"+marker+"]]")
            effect=root/("worker_"+str(index)+".txt")
            wait_until(effect.is_file)
            assert effect.read_text()==marker
        command("check|"+nodes[1]["id"])
        wait_until(lambda:"REAL_WORKER_1" in app.terminal_output(ws,terminal)["text"])
        output=post(server,token,{"workspace":str(root),"action":"check","value":nodes[1]["id"]})
        assert "REAL_WORKER_1" in output["text"] and output["persisted"]
        with app.store.lock:
            requests=[dict(r) for r in app.store.db.execute("SELECT * FROM canvas_agent_requests")]
        creation=next(r for r in requests if json.loads(r["result"]).get("resource",{}).get("name")=="worker_a")
        replay=post(server,token,{"workspace":str(root),"action":"create_agent",
            "value":"worker_a|sentra/model|worker","request_key":creation["request_key"]})
        assert replay["idempotent_replay"] and len(app._sessions)==3
        handoffs=app.graph.handoffs(ws)
        assert len(handoffs)==2 and all(h["status"]=="sent" for h in handoffs)
        assert not replay["model_acknowledged"]
        conversations=ConversationStore(app.state_dir.parent)
        history=conversations.history_window(coordinator["conversation_id"])["messages"]
        assert any("create_agent|worker_a" in m["content"] for m in history)
        assert any("REAL_WORKER_1" in m["content"] for m in history)
        ids=[a["terminal_id"] for a in agents]
        sessions=list(app._sessions.values())
    finally:
        server.shutdown();thread.join(5);server.server_close();app.shutdown()
    assert all(s.pty.poll() is not None for s in sessions)
    restored=Canvas(tmp_path)
    try:
        assert not restored._sessions
        assert "REAL_WORKER_1" in restored.terminal_output(ws,ids[0])["text"]
        assert len(restored.store.list_resources("agents",ws))==3
        assert len(restored.graph.handoffs(ws))==2
    finally:restored.shutdown()

def test_canvas_handoff_receipts_are_destination_bound_and_idempotent(scoped):
    app, ws, coordinator, coordinator_token, call = scoped
    worker = call("create_agent", "receipt_worker|sentra/model", "add-receipt-worker")
    node = worker["node_id"]
    request = call("dispatch", node + "|receipt ping", "receipt-ping")
    assert request["status"] == "sent"
    worker_token = next(token for token, (_, ident) in app._agent_tokens.items()
                        if ident == worker["resource"]["terminal_id"])
    workspace = app.store.workspace(ws)["path"]

    def receipt(token, action, **kwargs):
        return app.agent_control(token, {"workspace": workspace, "action": action, **kwargs})

    assert receipt(coordinator_token, "claim", value="receipt ping") == {"status":"not_found"}
    with pytest.raises(PermissionError):
        receipt(coordinator_token, "receipt", handoff_id=request["id"],
                receipt_status="answered")
    assert receipt(worker_token, "claim", value="not this message") == {"status":"not_found"}
    first = receipt(worker_token, "claim", value="receipt ping")
    assert first["id"] == request["id"] and first["receipt_status"] == "running"
    assert receipt(worker_token, "claim", value="receipt ping") == {"status":"not_found"}
    acknowledged = receipt(worker_token, "receipt", handoff_id=request["id"],
                           receipt_status="answered")
    assert acknowledged["receipt_status"] == "answered"
    assert not acknowledged["idempotent_replay"]
    assert receipt(worker_token, "receipt", handoff_id=request["id"],
                   receipt_status="answered")["idempotent_replay"]
    with pytest.raises(ValueError):
        receipt(worker_token, "receipt", handoff_id=request["id"],
                receipt_status="failed")
    observed = call("check", node)
    assert observed["handoffs"][0]["receipt_status"] == "answered"
    assert app.graph.handoffs(ws)[0]["receipt_status"] == "answered"


def test_canvas_handoff_running_receipt_becomes_uncertain_on_recovery(scoped):
    app,ws,coordinator,token,call = scoped
    worker=call("create_agent","recovery_worker|sentra/model","recovery-worker")
    request=call("dispatch",worker["node_id"]+"|need receipt","recovery-dispatch")
    target_token=next(t for t,(_,ident) in app._agent_tokens.items()
                      if ident==worker["resource"]["terminal_id"])
    ws_path=app.store.workspace(ws)["path"]
    receipt=app.agent_control(target_token,{"workspace":ws_path,"action":"claim",
                                           "value":"need receipt"})
    assert receipt["id"]==request["id"]
    app.graph.recover_handoffs([ws])
    assert app.graph.handoffs(ws)[0]["receipt_status"]=="uncertain"
    with pytest.raises(ValueError):
        app.agent_control(target_token,{"workspace":ws_path,"action":"receipt",
                                        "handoff_id":request["id"],"receipt_status":"answered"})

def test_terminal_exit_marks_unconfirmed_web_handoff_uncertain(scoped):
    app,ws,_,_,call=scoped
    worker=call("create_agent","interrupt_worker|sentra/model","interrupt-worker")
    delivery=call("dispatch",worker["node_id"]+"|unconfirmed work","interrupt-dispatch")
    assert app.graph.handoffs(ws)[0]["receipt_status"]=="pending"
    app.terminal_close(ws,worker["resource"]["terminal_id"])
    h=app.graph.handoffs(ws)[0]
    assert h["id"]==delivery["id"]
    assert h["status"]=="sent"
    assert h["receipt_status"]=="uncertain"
