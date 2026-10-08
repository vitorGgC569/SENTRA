"""Crash and transport ambiguity must survive Canvas restart without replay."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.graph import GraphStore
from sentra_core.conversations import ConversationStore

pytestmark=pytest.mark.skipif(os.name!="nt",reason="actual Windows protected state")


def test_handoff_intent_is_committed_before_write_and_partial_failure_not_replayed(tmp_path):
    app=Canvas(tmp_path)
    try:
        ws=app.create_workspace("delivery")["id"]
        terminal=app.store.create_terminal(ws,"receiver","sentra-cli")
        graph=app.graph_detail(ws)
        target=next(n for n in graph["nodes"] if n["resource_id"]==terminal["id"])
        source=app.graph_note(ws,"origin","context")
        app.graph_link(ws,source["id"],target["id"])
        calls=[]
        message="PRIVATE_HANDOFF_MARKER_418"
        def write(data):
            row=app.graph.handoffs(ws)[0]
            assert row["status"]=="sending" and row["content"]==message
            assert message.encode() not in app.graph.path.read_bytes()
            calls.append(data)
            raise OSError("pipe failed after accepting a prefix")
        pty=SimpleNamespace(poll=lambda:None,write=write,close=lambda **kwargs:None)
        app._sessions[terminal["id"]]=SimpleNamespace(pty=pty,exit_input=b"/exit\r")
        with pytest.raises(OSError):
            app.handoff(ws,source["id"],target["id"],message,True,"request-418")
        replay=app.handoff(ws,source["id"],target["id"],message,True,"request-418")
        assert replay["status"]=="uncertain" and replay["idempotent_replay"]
        assert len(calls)==1
        with pytest.raises(ValueError,match="collision"):
            app.handoff(ws,source["id"],target["id"],"different",True,"request-418")
    finally:
        app.shutdown()


def test_actual_process_crash_after_handoff_effect_has_uncertain_recovery(tmp_path):
    root=Path(__file__).resolve().parents[2]
    db=tmp_path/"graph.sqlite3"
    script="""from pathlib import Path
import os,sys
from sentra_canvas.graph import GraphStore
g=GraphStore(Path(sys.argv[1]))
a=g.note('owned','source','');b=g.note('owned','target','');g.link('owned',a['id'],b['id'])
c=g.note('other','source','');d=g.note('other','target','');g.link('other',c['id'],d['id'])
one,_=g.prepare_handoff('owned',a['id'],b['id'],'protected owned text','owned-key')
two,_=g.prepare_handoff('other',c['id'],d['id'],'other text','other-key')
g.handoff_state('owned',one['id'],'sending');g.handoff_state('other',two['id'],'sending')
Path(sys.argv[2]).write_text('one physical effect')
os._exit(19)
"""
    result=subprocess.run([sys.executable,"-B","-c",script,str(db),str(tmp_path/"effect.txt")],
                          cwd=root,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==19
    g=GraphStore(db)
    try:
        g.recover_handoffs(["owned"])
        row=g.handoffs("owned")[0]
        assert row["status"]=="uncertain"
        assert g.handoffs("other")[0]["status"]=="sending"
        replay,created=g.prepare_handoff("owned",row["source"],row["target"],row["content"],"owned-key")
        assert not created and replay["status"]=="uncertain"
        assert (tmp_path/"effect.txt").read_text()=="one physical effect"
    finally:
        g.close()


def test_task_outcome_uses_protected_journal_not_only_exit_or_cancel(tmp_path):
    app=Canvas(tmp_path)
    try:
        ws=app.create_workspace("task_delivery")["id"]
        root=app.store.workspace(ws)["path"]
        task={"id":"journal_task_481"}
        store=ConversationStore(app.state_dir.parent)
        sid=store.open(root,session_id="task_"+task["id"])
        turn,_=store.begin_turn(sid,"task")
        call,_=store.start_tool(sid,turn,"W","effect.txt|content")
        assert app._task_outcome(ws,task,1,True)=="uncertain"
        store.resolve_call(sid,call,executed=True,evidence="verified effect file")
        with store.executing(sid):
            turn,_=store.continue_turn(sid)
            store.end_turn(sid,turn,"completed")
        assert app._task_outcome(ws,task,0,True)=="succeeded"
    finally:
        app.shutdown()


def test_actual_task_child_crash_after_effect_is_uncertain_and_not_redelegated(tmp_path,monkeypatch):
    import time
    app=Canvas(tmp_path)
    try:
        ws=app.create_workspace("crashed_worker")["id"]
        coordinator=app.create_agent(ws,"coordinator","sentra/model")
        worker=app.create_agent(ws,"worker","sentra/model")
        team=app.create_team(ws,"team",coordinator["id"],[worker["id"]])
        script=tmp_path/"worker_crash.py"
        script.write_text('''import sys,os
from pathlib import Path
from sentra_core.conversations import ConversationStore
args=sys.argv
state=args[args.index('--state-dir')+1];sid=args[args.index('--session-id')+1]
root=args[args.index('--workspace')+1]
s=ConversationStore(state);s.open(root,session_id=sid)
with s.executing(sid):
 t,_=s.begin_turn(sid,'task')
 s.start_tool(sid,t,'W','effect.txt|one effect')
 Path(root,'effect.txt').write_text('one effect')
 os._exit(23)
''',encoding="utf-8")
        # Run a genuine child and crash, replacing only the unavailable external
        # model transport. This test makes no claim of real model inference.
        repo=Path(__file__).resolve().parents[2]
        monkeypatch.setenv("PYTHONPATH",str(repo))
        monkeypatch.setattr(app,"_cli_command",lambda args:[sys.executable,"-B",str(script),*args])
        task=app.delegate(ws,team["id"],worker["id"],"owned crash test","crash-key","sentra-cli",True)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            status=app.store.resource("tasks",task["id"],ws)
            if status["status"] not in {"queued","running"}:break
            time.sleep(.05)
        assert status["status"]=="uncertain"
        replay=app.delegate(ws,team["id"],worker["id"],"owned crash test","crash-key","sentra-cli",True)
        assert replay["id"]==task["id"] and replay["status"]=="uncertain"
        assert Path(app.store.workspace(ws)["path"],"effect.txt").read_text()=="one effect"
        with pytest.raises(ValueError,match="terminal state"):
            app.store.task_state(ws,task["id"],"succeeded")
    finally:
        app.shutdown()


def test_shutdown_waits_for_actual_task_process_tree_before_closing_store(tmp_path,monkeypatch):
    import ctypes
    import time
    from sentra_canvas.store import Store
    app=Canvas(tmp_path)
    ws=app.create_workspace("shutdown_worker")["id"]
    coordinator=app.create_agent(ws,"coordinator","sentra/model")
    worker=app.create_agent(ws,"worker","sentra/model")
    team=app.create_team(ws,"team",coordinator["id"],[worker["id"]])
    script=tmp_path/"sleeping_worker.py"
    script.write_text('''import sys,time,subprocess
from pathlib import Path
from sentra_core.conversations import ConversationStore
args=sys.argv;state=args[args.index('--state-dir')+1];sid=args[args.index('--session-id')+1]
root=args[args.index('--workspace')+1]
s=ConversationStore(state);s.open(root,session_id=sid)
with s.executing(sid):
 t,_=s.begin_turn(sid,'task');s.start_tool(sid,t,'W','effect.txt|one effect')
 Path(root,'effect.txt').write_text('one effect')
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
 Path(root,'grandchild.pid').write_text(str(child.pid))
 time.sleep(60)
''',encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH",str(Path(__file__).resolve().parents[2]))
    monkeypatch.setattr(app,"_cli_command",lambda args:[sys.executable,"-B",str(script),*args])
    handle=None
    try:
        task=app.delegate(ws,team["id"],worker["id"],"owned cancellation test","shutdown-key","sentra-cli",True)
        pidfile=Path(app.store.workspace(ws)["path"])/"grandchild.pid"
        end=time.monotonic()+15
        while not pidfile.exists() and time.monotonic()<end:time.sleep(.05)
        assert pidfile.exists()
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x00100000,False,int(pidfile.read_text()))
        assert handle
        process=app._task_processes[task["id"]]
        thread=app._task_threads[task["id"]]
        app.shutdown()
        assert process.poll() is not None and not thread.is_alive()
        assert kernel.WaitForSingleObject(handle,5000)==0
        reopened=Store(app.state_dir/"canvas.sqlite3",app.state_dir/"projects")
        try:
            assert reopened.resource("tasks",task["id"],ws)["status"]=="uncertain"
        finally:reopened.close()
        with pytest.raises(RuntimeError,match="shutting down"):
            app.delegate(ws,team["id"],worker["id"],"late","late","sentra-cli",True)
    finally:
        app.shutdown()
        if handle:kernel.CloseHandle(handle)
