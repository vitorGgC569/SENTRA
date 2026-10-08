"""Real child/process recovery and the shared durable registry, without inference."""
import os
from pathlib import Path
import sqlite3
import sys
import time

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.task_runtime import TaskRuntime
from sentra_canvas.store import Store,Denied

pytestmark=pytest.mark.skipif(os.name!="nt",reason="Windows protected task state")


def wait(check,timeout=15):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=check()
        if value:return value
        time.sleep(.05)
    raise AssertionError("persistent queue condition did not complete")


def team(app):
    ws=app.create_workspace("task_queue")["id"]
    coordinator=app.create_agent(ws,"coordinator","sentra/model")
    workers=[app.create_agent(ws,"worker"+str(i),"sentra/model") for i in range(3)]
    group=app.create_team(ws,"team",coordinator["id"],[w["id"] for w in workers])
    return ws,group["id"],[w["id"] for w in workers]


def terminal(app,ws,task):
    row=app.store.resource("tasks",task["id"],ws)
    return row if row["status"] not in {"queued","running"} else None


def test_bounded_real_queue_cancel_and_approved_recovery(tmp_path,monkeypatch):
    app=Canvas(tmp_path,max_task_workers=1,max_pending_tasks=3)
    restored=None
    try:
        ws,group,workers=team(app)
        root=Path(app.store.workspace(ws)["path"])
        child=tmp_path/"holding_worker.py"
        child.write_text('''import sys,time
from pathlib import Path
from sentra_core.conversations import ConversationStore
args=sys.argv;root=args[args.index('--workspace')+1]
state=args[args.index('--state-dir')+1];sid=args[args.index('--session-id')+1]
s=ConversationStore(state);s.open(root,session_id=sid)
with s.executing(sid):
 turn,_=s.begin_turn(sid,'owned interruption test')
 s.start_tool(sid,turn,'W','hold_effect.txt|one effect')
 Path(root,'hold_effect.txt').write_text('one effect')
 time.sleep(60)
''',encoding="utf-8")
        monkeypatch.setenv("PYTHONPATH",str(Path(__file__).resolve().parents[2]))
        monkeypatch.setattr(app,"_cli_command",lambda args:[sys.executable,"-B",str(child),*args])
        first=app.delegate(ws,group,workers[0],"hold","first","sentra-cli",True)
        wait(lambda:(root/"hold_effect.txt").is_file())
        assert "hold" not in app._task_processes[first["id"]].process.args
        assert "--prompt-stdin" in app._task_processes[first["id"]].process.args
        second=app.delegate(ws,group,workers[1],"[[W|cancelled.txt|never]]","second","sentra-cli",True)
        third=app.delegate(ws,group,workers[2],"[[W|queued_effect.txt|PRIVATE_QUEUE_MARKER_827]]","third","sentra-cli",True)
        assert app.task_scheduler_status()["active_workers"]==1
        assert app.store.resource("tasks",third["id"],ws)["status"]=="queued"
        assert app.delegate(ws,group,workers[2],third["prompt"],"third","sentra-cli",True)["id"]==third["id"]
        with pytest.raises(ValueError,match="quota"):
            app.delegate(ws,group,workers[2],"fourth","fourth","sentra-cli",True)
        app.cancel_task(ws,second["id"])
        assert app.store.resource("tasks",second["id"],ws)["status"]=="cancelled"
        app.shutdown()
        restored=Canvas(tmp_path,max_task_workers=1,max_pending_tasks=3)
        # This recovery launches the real source CLI, executing a direct tool.
        wait(lambda:(root/"queued_effect.txt").is_file())
        finished=wait(lambda:terminal(restored,ws,third))
        assert finished["status"]=="succeeded"
        assert (root/"queued_effect.txt").read_text()=="PRIVATE_QUEUE_MARKER_827"
        assert not (root/"cancelled.txt").exists()
        assert restored.store.resource("tasks",first["id"],ws)["status"]=="uncertain"
        runtime=restored._runtime()
        wait(lambda:runtime.operation(finished)["state"]=="SUCCEEDED")
        operation=runtime.operation(finished)
        assert operation["progress"]["conversation_id"]=="task_"+third["id"]
        assert "PRIVATE_QUEUE_MARKER_827" not in str(operation)
        raw=restored.store.db.execute("SELECT prompt,result,protected_prompt,protected_result FROM tasks WHERE id=?",(third["id"],)).fetchone()
        assert raw["prompt"]==raw["result"]==""
        assert raw["protected_prompt"].startswith("dpapi:") and raw["protected_result"].startswith("dpapi:")
        replay=restored.delegate(ws,group,workers[2],third["prompt"],"third","sentra-cli",True)
        assert replay["id"]==third["id"] and replay["status"]=="succeeded"
    finally:
        if restored:restored.shutdown()
        app.shutdown()


def test_claim_projection_failure_never_launches_a_child(tmp_path,monkeypatch):
    original=TaskRuntime.project
    failed=[]
    def interrupt_after_claim(self,task):
        original(self,task)
        if task["status"]=="running" and not failed:
            failed.append(task["id"])
            raise sqlite3.OperationalError("injected publication outage after durable commit")
    monkeypatch.setattr(TaskRuntime,"project",interrupt_after_claim)
    app=Canvas(tmp_path)
    try:
        ws,group,workers=team(app)
        task=app.delegate(ws,group,workers[0],"[[W|must_not_exist.txt|never]]","claim-outage","sentra-cli",True)
        row=wait(lambda:terminal(app,ws,task))
        assert row["status"]=="failed" and failed==[task["id"]]
        assert not Path(app.store.workspace(ws)["path"],"must_not_exist.txt").exists()
        wait(lambda:app._runtime().operation(row)["state"]=="FAILED")
        assert app.delegate(ws,group,workers[0],task["prompt"],"claim-outage","sentra-cli",True)["id"]==task["id"]
    finally:app.shutdown()


def test_legacy_queued_task_requires_authorization_and_protection_failure_rolls_back(tmp_path,monkeypatch):
    app=Canvas(tmp_path)
    restored=None
    try:
        ws,group,workers=team(app)
        prompt="[[W|approved_effect.txt|APPROVED_QUEUE_REAL_TOOL]]"
        task,_=app.store.create_task(ws,group,workers[0],"sentra-cli",prompt,"legacy",approved=False)
        # Reconstruct a real v3 record: no stored authorization or protected fields.
        app.shutdown()
        with sqlite3.connect(app.state_dir/"canvas.sqlite3") as db:
            db.execute("DROP TABLE task_projection_outbox")
            db.execute("DROP INDEX task_queue")
            db.execute("ALTER TABLE workspaces DROP COLUMN run_id")
            db.execute("ALTER TABLE tasks DROP COLUMN run_id")
            for field in ("approved","cancel_requested","revision","protected_prompt","protected_result"):
                db.execute("ALTER TABLE tasks DROP COLUMN "+field)
            db.execute("UPDATE tasks SET prompt=? WHERE id=?",(prompt,task["id"]))
            db.execute("PRAGMA user_version=3")
        restored=Canvas(tmp_path)
        root=Path(restored.store.workspace(ws)["path"])
        row=restored.store.resource("tasks",task["id"],ws)
        assert not row["approved"] and row["status"]=="queued"
        # Metadata projection proves the scheduler inspected the unapproved row.
        wait(lambda:restored._runtime().operation(row)["progress"].get("authorized") is False)
        assert not (root/"approved_effect.txt").exists()
        with pytest.raises(ValueError,match="collision"):
            restored.delegate(ws,group,workers[0],"changed content","legacy","sentra-cli",True)
        approved=restored.delegate(ws,group,workers[0],prompt,"legacy","sentra-cli",True)
        assert approved["id"]==task["id"] and approved["approved"]
        assert wait(lambda:terminal(restored,ws,task))["status"]=="succeeded"
        assert (root/"approved_effect.txt").read_text()=="APPROVED_QUEUE_REAL_TOOL"
        monkeypatch.setattr("sentra_canvas.store.protect_secret",lambda text:text)
        with pytest.raises(RuntimeError,match="OS protection"):
            restored.delegate(ws,group,workers[1],"private content","no-protection","sentra-cli",True)
        assert not any(t["request_key"]=="no-protection" for t in restored.store.list_resources("tasks",ws))
    finally:
        if restored:restored.shutdown()
        app.shutdown()


def test_legacy_content_migration_only_changes_current_logical_owner(tmp_path):
    projects=tmp_path/"projects";projects.mkdir()
    path=tmp_path/"canvas.sqlite3"
    records=[]
    for owner in ("alice","bob"):
        store=Store(path,projects,principal=owner)
        try:
            ws=store.create_workspace(owner)["id"]
            coordinator=store.create_agent(ws,"coordinator","sentra/model","coordinator")
            worker=store.create_agent(ws,"worker","sentra/model","worker")
            group=store.create_team(ws,"team",coordinator["id"],[worker["id"]])
            task,_=store.create_task(ws,group["id"],worker["id"],"sentra-cli","private "+owner,owner)
            records.append((ws,task["id"],"private "+owner))
        finally:store.close()
    with sqlite3.connect(path) as db:
        for _,ident,text in records:
            db.execute("UPDATE tasks SET prompt=?,protected_prompt='' WHERE id=?",(text,ident))
    store=Store(path,projects,principal="alice")
    try:
        owned,foreign=records
        assert store.resource("tasks",owned[1],owned[0])["prompt"]==owned[2]
        row=store.db.execute("SELECT prompt,protected_prompt FROM tasks WHERE id=?",(owned[1],)).fetchone()
        assert row["prompt"]=="" and row["protected_prompt"].startswith("dpapi:")
        row=store.db.execute("SELECT prompt,protected_prompt FROM tasks WHERE id=?",(foreign[1],)).fetchone()
        assert row["prompt"]==foreign[2] and row["protected_prompt"]==""
        with pytest.raises(Denied):store.resource("tasks",foreign[1],foreign[0])
    finally:store.close()
