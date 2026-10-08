"""Actual MCP SDK -> authenticated native broker -> real CLI task execution."""
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import threading

import pytest
from mcp import Client

from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.broker import publish_endpoint,remove_endpoint
from sentra_mcp.config import MCPConfig
from sentra_mcp.server import SentraMCPServer
from sentra_mcp.services.native_canvas import NativeCanvasService
from sentra_mcp import identity

pytestmark=pytest.mark.skipif(os.name!="nt",reason="actual Windows DPAPI and CLI")


def test_real_mcp_native_coordination_pause_resume_and_scope(tmp_path,monkeypatch):
    public=tmp_path/"public";public.mkdir()
    repo=public/"existing_repo";repo.mkdir()
    state=tmp_path/"state"
    monkeypatch.setattr(identity,"_SESSION_SECRET_PATH",tmp_path/"isolated-session-secret")
    app=Canvas(tmp_path,state_dir=state/"canvas")
    http=CanvasServer(app);publish_endpoint(http)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    hidden=app.create_workspace("outside_grant")
    config=MCPConfig(allowed_roots=(public,),state_root=state,audit_log=state/"mcp-audit.jsonl",
                     remote_store_path=state/"remote.sqlite3")
    async def probe():
        runtime=SentraMCPServer(config)
        async with Client(runtime.mcp) as client:
            names={tool.name for tool in (await client.list_tools()).tools}
            assert "sentra_canvas" in names
            opened=await client.call_tool("sentra_session_open",{})
            token=opened.structured_content["data"]["session_token"]
            async def call(action,workspace=None,params=None,key=None,confirm=False):
                result=await client.call_tool("sentra_canvas",{"action":action,"workspace":workspace,
                    "params":params,"request_key":key,"confirm":confirm,"session_token":token})
                return result.structured_content
            assert (await call("status"))["data"]["running"]
            attached=await call("workspace_attach",params={"path":str(repo),"name":"existing_repo"})
            assert attached["ok"],attached
            ws=attached["data"]["id"]
            assert [w["id"] for w in (await call("workspaces"))["data"]["items"]]==[ws]
            denied=await call("workspace",hidden["id"])
            assert not denied["ok"] and denied["error"]["code"]=="forbidden"
            agents=[]
            for name in ("coordinator","worker"):
                response=await call("agent_create",ws,{"name":name,"model":"sentra/model","start":False},name)
                assert response["ok"],response
                agents.append(response["data"]["result"])
            group=await call("team_create",ws,{"name":"team","coordinator":agents[0]["id"],
                "workers":[agents[1]["id"]]},"team")
            assert group["ok"],group
            paused=await call("run_pause",ws,key="pause")
            assert paused["data"]["result"]["state"]=="PAUSED"
            params={"team":group["data"]["result"]["id"],"agent":agents[1]["id"],
                    "prompt":"[[W|mcp_effect.txt|REAL_NATIVE_MCP_EFFECT]]"}
            refused=await call("task_delegate",ws,params,"no-approval")
            assert not refused["ok"] and refused["error"]["code"]=="forbidden"
            task=await call("task_delegate",ws,params,"delegate",True)
            assert task["ok"],task
            task_id=task["data"]["result"]["id"]
            old_run=task["data"]["result"]["run_id"]
            assert not (repo/"mcp_effect.txt").exists()
            assert app.task_scheduler_status()["active_workers"]==0
            resumed=await call("run_resume",ws,key="resume")
            assert resumed["ok"],resumed
            end=asyncio.get_running_loop().time()+15
            while asyncio.get_running_loop().time()<end:
                status=await call("task_status",ws,{"id":task_id})
                if status["data"]["status"]=="succeeded":break
                await asyncio.sleep(.1)
            assert status["data"]["status"]=="succeeded",status
            assert (repo/"mcp_effect.txt").read_text()=="REAL_NATIVE_MCP_EFFECT"
            governed=await call("task_governance",ws,{"id":task_id})
            assert governed["ok"] and governed["data"]["work_item"]["state"]=="VALIDATING",governed
            assert governed["data"]["cost"]["quota"]==1
            assert not (await call("task_governance",hidden["id"],{"id":task_id}))["ok"]
            budget=await call("budget_set",ws,{"scope":"workspace","limits":{"quota_usage":0}},"budget")
            assert budget["ok"],budget
            policy_id=budget["data"]["result"]["budget_policy_id"]
            budgets=await call("budget_list",ws)
            assert budgets["data"]["items"][0]["budget_policy_id"]==policy_id
            held=await call("task_delegate",ws,{**params,"prompt":"[[W|budget_denied.txt|never]]"},"held",True)
            assert held["ok"],held
            held_id=held["data"]["result"]["id"]
            assert (await call("task_block",ws,{"id":held_id},"block"))["ok"]
            assert (await call("task_unblock",ws,{"id":held_id},"unblock"))["ok"]
            assert (await call("task_governance",ws,{"id":held_id}))["data"]["admission"]["allowed"] is False
            assert not (repo/"budget_denied.txt").exists()
            replay=await call("task_delegate",ws,params,"delegate",True)
            assert replay["ok"],replay
            assert replay["data"]["idempotent_replay"] and replay["data"]["result"]["id"]==task_id
            collision=await call("task_delegate",ws,{**params,"prompt":"different"},"delegate",True)
            assert not collision["ok"] and "collision" in collision["error"]["message"]
            assert (await call("run_cancel",ws,key="cancel",confirm=True))["ok"]
            fresh=await call("run_resume",ws,key="fresh-run")
            assert fresh["data"]["result"]["run_id"]!=old_run
            assert app.store.resource("tasks",task_id,ws)["run_id"]==old_run
            bad=await call("task_delegate",ws,{**params,"checks":[{"path":"../outside","text":"invalid"}]},"bad-check",True)
            assert not bad["ok"] and bad["error"]["code"]!="operation_uncertain"
            await call("budget_set",ws,{"policy_id":policy_id,"enabled":False},"disable-policy")
            checked_params={**params,"prompt":"[[W|verified_mcp.txt|REAL_MCP_FILE_CHECK]]",
                "checks":[{"path":"verified_mcp.txt","text":"REAL_MCP_FILE_CHECK"}]}
            checked=await call("task_delegate",ws,checked_params,"checked",True)
            assert checked["ok"],checked
            checked_id=checked["data"]["result"]["id"]
            end=asyncio.get_running_loop().time()+20
            while asyncio.get_running_loop().time()<end:
                observed=await call("task_governance",ws,{"id":checked_id})
                if observed["data"]["work_item"]["state"]=="COMPLETED":break
                await asyncio.sleep(.1)
            assert observed["data"]["work_item"]["state"]=="COMPLETED",observed
            verified=await call("task_verify",ws,{"id":checked_id},"reverify")
            assert verified["ok"] and verified["data"]["result"]["status"]=="passed"
            # A genuine broker mutation can commit before its reply is lost.
            # Fault injection replaces only the reply; the HTTP operation is real.
            original_request=runtime.canvas._request
            lost=[]
            def lose_reply(endpoint,path,body=None):
                value=original_request(endpoint,path,body)
                if path=="/api/graph/note" and not lost:
                    lost.append(value["id"])
                    raise TimeoutError("injected reply loss after the real note committed")
                return value
            monkeypatch.setattr(runtime.canvas,"_request",lose_reply)
            failed=await call("note_create",ws,{"title":"durable_note","body":"PRIVATE_MCP_RECEIPT_762"},"lost-reply")
            assert not failed["ok"] and failed["error"]["code"]=="operation_uncertain"
            repeat=await call("note_create",ws,{"title":"durable_note","body":"PRIVATE_MCP_RECEIPT_762"},"lost-reply")
            assert not repeat["ok"] and len(lost)==1
            receipt=await call("request_status",ws,key="lost-reply")
            assert receipt["data"]["status"]=="uncertain"
            notes=[n for n in app.graph.snapshot(ws)["nodes"] if n["title"]=="durable_note"]
            assert len(notes)==1 and notes[0]["id"]==lost[0]
            resolved=await call("request_resolve",ws,{"executed":True,"evidence":"verified persisted note "+lost[0]},"lost-reply",True)
            assert resolved["ok"] and not resolved["data"]["automatically_replayed"]
            recovered=await call("note_create",ws,{"title":"durable_note","body":"PRIVATE_MCP_RECEIPT_762"},"lost-reply")
            assert recovered["ok"] and recovered["data"]["idempotent_replay"]
            # Caller payload cannot replace the checked workspace or bypass sandbox policy.
            injected=await call("note_create",ws,{"title":"bad","ws":hidden["id"]},"injected")
            assert not injected["ok"]
            sandbox=NativeCanvasService(replace(config,process_mode="sandbox"),runtime.workspaces,runtime.filesystem,runtime.audit)
            with pytest.raises(PermissionError,match="sandbox"):
                sandbox.execute("terminal_create",owner="local-operator",principal="local-operator",workspace=ws,
                    params={"name":"blocked","shell":"cmd"},request_key="sandbox")
    try:asyncio.run(probe())
    finally:
        http.shutdown();thread.join(5);http.server_close();app.shutdown();remove_endpoint(http)
