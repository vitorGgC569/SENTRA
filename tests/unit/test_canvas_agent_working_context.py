"""Staged working context acceptance over owner routes and protected store."""
import json

import pytest

from test_sentra_runtime_canvas_center_http import running_canvas,request


def test_owner_agent_goal_is_protected_revisioned_and_survives_reopen(tmp_path):
    from sentra_canvas.agent_context import AgentWorkingContext
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace("Context")["id"]
        code,agent=request(server,"/api/agents",json_body={"ws":ws,"name":"Coordinator","model":"sentra/test",
            "role":"coordinator","start":False,"goal":"PRIVATE_GOAL_MARKER: analyze the assigned source modules"})
        assert code==200,agent
        code,context=request(server,"/api/agent/context",json_body={"ws":ws,"agent_id":agent["id"]})
        assert code==200 and context["revision"]==1 and "PRIVATE_GOAL_MARKER" in context["goal"]
        row=app.store.db.execute("SELECT content FROM canvas_working_context WHERE agent=?",(agent["id"],)).fetchone()
        assert "PRIVATE_GOAL_MARKER" not in row[0]
        code,new=request(server,"/api/agent/context",json_body={"ws":ws,"agent_id":agent["id"],
            "goal":"Review the actual output artifacts","expected_revision":1})
        assert code==200 and new["revision"]==2
        code,_=request(server,"/api/agent/context",json_body={"ws":ws,"agent_id":agent["id"],"goal":"stale","expected_revision":1})
        assert code==400
        assert AgentWorkingContext(app.store).get(ws,agent["id"])==new
        other=app.create_workspace("Other context")["id"]
        code,_=request(server,"/api/agent/context",json_body={"ws":other,"agent_id":agent["id"]})
        assert code!=200
        code,_=request(server,"/api/agent/context",json_body={"ws":ws,"agent_id":agent["id"]},authorized=False)
        assert code==401


def test_invalid_goal_is_rejected_before_agent_registration(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace("Validation before start")["id"]
        code,_=request(server,"/api/agents",json_body={"ws":ws,"name":"Must_not_exist","model":"sentra/test",
            "start":True,"goal":"x"*16001})
        assert code==400
        assert app.store.list_resources("agents",ws)==[]
        assert app.store.list_resources("terminals",ws)==[]


def test_context_snapshot_excludes_unconnected_notes_and_other_agent_tasks(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace("Directed context")["id"]
        a=app.create_agent(ws,"Self","sentra/test",goal="Own goal")
        b=app.create_agent(ws,"Other","sentra/test",goal="OTHER_AGENT_PRIVATE_GOAL")
        graph=app.graph_detail(ws)
        origin=next(n for n in graph["nodes"] if n["kind"]=="agent" and n["resource_id"]==a["id"])
        context=app._working_context_snapshot(ws,{a["id"]},{origin["id"]},graph)
        raw=json.dumps(context)
        assert "Own goal" in raw and "OTHER_AGENT_PRIVATE_GOAL" not in raw
        assert context["context_creates_permissions"] is False
        assert context["agents"][0]["id"]==a["id"]
