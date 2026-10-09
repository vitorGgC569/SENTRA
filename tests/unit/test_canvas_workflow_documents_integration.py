"""Staged production-route acceptance: real CSV, durable recovery and outcome gates."""
from pathlib import Path

from test_sentra_runtime_canvas_center_http import running_canvas,request


def setup_workflow(app,server,*,with_wait=True):
    ws=app.create_workspace("Workflow documents")["id"]
    agent=app.create_agent(ws,"Workflow worker","sentra/test",start=False)
    root=Path(app.store.workspace(ws)["path"])
    source,output,expected=root/"source.csv",root/"result.csv",root/"expected.csv"
    source.write_text("name,value,extra\nAda,10,x\nLinus,20,y\n",encoding="utf-8")
    expected.write_text("name,value\nAda,10\nLinus,20\n",encoding="utf-8")
    steps=[{"step_id":"transform","inputs":{"action":"table.transform",
        "input":{"source":"input","path":["source"]},"output":{"source":"input","path":["output"]},
        "select":["name","value"]}}]
    if with_wait:steps.append({"step_id":"approval","kind":"wait","dependencies":["transform"],"signal_name":"approved"})
    steps.append({"step_id":"verify","dependencies":["approval" if with_wait else "transform"],
        "inputs":{"action":"artifact.verify","input":{"source":"input","path":["output"]},
            "expected":{"source":"input","path":["expected"]},"metric":"table"}})
    code,machine=request(server,"/api/center/machine/configure",json_body={"ws":ws,"agent_id":agent["id"],
        "kind":"workflow","definitions":[{"definition_id":"report","version":"1","steps":steps}]})
    assert code==200,machine
    code,task=request(server,"/api/center/task/prepare",json_body={"ws":ws,"machine_id":machine["machine_id"],
        "capabilities":machine["capabilities"],"objective":"Transform real CSV and independently verify its result"})
    assert code==200,task
    return ws,machine,task,source,output,expected


def dispatch(server,ws,machine,task,cap,args,oid):
    body={"ws":ws,"machine_id":machine["machine_id"],"work_item_id":task["work_item"]["work_item_id"],
        "capability_id":cap,"operation_id":oid,"request_key":oid+"-key","arguments":args}
    code,result=request(server,"/api/center/execute",json_body=body)
    assert code==200,result
    return result


def payload(result):
    assert result["state"]=="SUCCEEDED",result
    return result["evidence"]["payload"]


def test_canvas_workflow_real_output_signal_and_restart_without_replay(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws,machine,task,source,output,expected=setup_workflow(app,server)
        scope={"workflow_id":"report-run","namespace":""}
        creation={"workflow_id":"report-run","definition_id":"report","definition_version":"1",
            "inputs":{"source":str(source),"output":str(output),"expected":str(expected)}}
        payload(dispatch(server,ws,machine,task,"workflow:create",creation,"op-wf-create"))
        assert not output.exists()
        ready=payload(dispatch(server,ws,machine,task,"workflow:advance",scope,"op-wf-plan"))["ready"]
        assert len(ready)==1 and ready[0]["step_id"]=="transform"
        result=dispatch(server,ws,machine,task,ready[0]["capability_id"],ready[0]["arguments"],"op-wf-transform")
        assert result["state"]=="SUCCEEDED",result
        artifact=result["evidence"]["payload"]["artifacts"][0]
        assert artifact["durable_capture"] is True and artifact["artifact_id"]
        durable=app._runtime().durable
        assert durable.read_artifact(artifact["artifact_id"])==output.read_bytes()
        assert output.read_text(encoding="utf-8").splitlines()==expected.read_text(encoding="utf-8").splitlines()
        assert source.read_text(encoding="utf-8").startswith("name,value,extra")
        mtime=output.stat().st_mtime_ns
        assert dispatch(server,ws,machine,task,ready[0]["capability_id"],ready[0]["arguments"],"op-wf-transform")==result
        assert output.stat().st_mtime_ns==mtime
        # A fresh host rebuilds bindings from protected configuration. Its first
        # observation does not need to invoke a document backend or republish.
        old=app._machine_host;old.close();app._machine_host=None
        state=payload(dispatch(server,ws,machine,task,"workflow:observe",scope,"op-wf-restart-read"))
        assert state["steps"]["transform"]["state"]=="PENDING_ACK"
        waiting=payload(dispatch(server,ws,machine,task,"workflow:advance",scope,"op-wf-approval-wait"))
        assert waiting["ready"]==[]
        assert output.stat().st_mtime_ns==mtime
        payload(dispatch(server,ws,machine,task,"workflow:signal",{**scope,"name":"approved","signal_id":"approval-1","payload":{"approved":True}},"op-wf-signal"))
        next_steps=payload(dispatch(server,ws,machine,task,"workflow:advance",scope,"op-wf-after-signal"))["ready"]
        assert next_steps[0]["step_id"]=="verify"
        payload(dispatch(server,ws,machine,task,next_steps[0]["capability_id"],next_steps[0]["arguments"],"op-wf-verify"))
        completed=payload(dispatch(server,ws,machine,task,"workflow:advance",scope,"op-wf-finish"))
        assert completed["status"]=="SUCCEEDED" and completed["ready"]==[]
        assert output.stat().st_mtime_ns==mtime


def test_workflow_acceptance_mismatch_is_failed_and_cannot_advance_as_success(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws,machine,task,source,output,expected=setup_workflow(app,server,with_wait=False)
        scope={"workflow_id":"mismatch-run","namespace":""}
        payload(dispatch(server,ws,machine,task,"workflow:create",{"workflow_id":scope["workflow_id"],
            "definition_id":"report","definition_version":"1","inputs":{"source":str(source),"output":str(output),"expected":str(expected)}},"op-mismatch-create"))
        ready=payload(dispatch(server,ws,machine,task,"workflow:advance",scope,"op-mismatch-first"))["ready"][0]
        payload(dispatch(server,ws,machine,task,ready["capability_id"],ready["arguments"],"op-mismatch-transform"))
        expected.write_text("name,value\nAda,999\nLinus,20\n",encoding="utf-8")
        check=payload(dispatch(server,ws,machine,task,"workflow:advance",scope,"op-mismatch-next"))["ready"][0]
        failed=dispatch(server,ws,machine,task,check["capability_id"],check["arguments"],"op-mismatch-verify")
        assert failed["state"]=="FAILED" and failed["error"]=="ACCEPTANCE_FAILED",failed
        end=payload(dispatch(server,ws,machine,task,"workflow:advance",scope,"op-mismatch-finish"))
        assert end["status"]=="FAILED" and end["ready"]==[]
        assert output.read_text(encoding="utf-8").splitlines()[1]=="Ada,10"


def test_workflow_task_revoke_prevents_activity_file_publication(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws,machine,task,source,output,expected=setup_workflow(app,server)
        scope={"workflow_id":"revoked-run","namespace":""}
        payload(dispatch(server,ws,machine,task,"workflow:create",{"workflow_id":scope["workflow_id"],
            "definition_id":"report","definition_version":"1","inputs":{"source":str(source),"output":str(output),"expected":str(expected)}},"op-revoke-create"))
        ready=payload(dispatch(server,ws,machine,task,"workflow:advance",scope,"op-revoke-plan"))["ready"][0]
        host=app._machine_service()
        for grant in task["grant_ids"]:host.control.authorization_revoke(grant,host.owner)
        code,denied=request(server,"/api/center/execute",json_body={"ws":ws,"machine_id":machine["machine_id"],
            "work_item_id":task["work_item"]["work_item_id"],"capability_id":ready["capability_id"],
            "operation_id":"op-revoked-activity","request_key":"revoked-key","arguments":ready["arguments"]})
        assert code==403,denied
        assert not output.exists()
