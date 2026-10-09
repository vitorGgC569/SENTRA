"""Staged owner overview acceptance over production routes and real CSV I/O."""
from pathlib import Path

from test_sentra_runtime_canvas_center_http import running_canvas,request
from test_canvas_machine_documents_integration import configured


def test_center_overview_contains_current_real_operation_without_result_body(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws,machine,task=configured(app,server)
        root=Path(app.store.workspace(ws)["path"]);source=root/"input.csv";output=root/"output.csv"
        source.write_text("name,value\nAda,10\n",encoding="utf-8")
        body={"ws":ws,"machine_id":machine["machine_id"],"work_item_id":task["work_item"]["work_item_id"],
            "capability_id":"document:transform","operation_id":"op-overview-document","request_key":"overview-document",
            "arguments":{"action":"table.transform","input":str(source),"output":str(output)}}
        code,result=request(server,"/api/center/execute",json_body=body)
        assert code==200 and result["state"]=="SUCCEEDED",result
        code,view=request(server,"/api/center/overview?ws="+ws)
        assert code==200,view
        assert view["run"]["state"]=="RUNNING"
        assert view["operations"]["state_counts"]["SUCCEEDED"]==1
        entry=view["operations"]["items"][0]
        assert entry["operation_id"]==body["operation_id"] and entry["work_item_id"]==body["work_item_id"]
        assert entry["machine_id"]==machine["machine_id"] and entry["effect_started"] is True
        assert "result" not in entry and "arguments" not in entry
        assert view["machines"][0]["registered"] is True
        assert view["provider_registration_proves_execution"] is False
        assert view["cost"]["quota"]==1
        other=app.create_workspace("Unrelated")["id"]
        code,other_view=request(server,"/api/center/overview?ws="+other)
        assert code==200 and other_view["operations"]["items"]==[] and other_view["machines"]==[]
        code,_=request(server,"/api/center/overview?ws="+ws,authorized=False)
        assert code==401
        code,_=request(server,"/api/center/overview?ws="+ws+"&operation_offset=-1")
        assert code==400


def test_durable_operation_metadata_pagination_is_owner_scoped(tmp_path):
    from sentra_mcp.services.durable import DurableRunService
    service=DurableRunService(tmp_path)
    try:
        run=service.create_run("owner",run_id="run-overview",workspace=str(tmp_path))
        for i in range(3):service.create_operation(run["run_id"],"owner",kind="example",operation_id="op-page-"+str(i))
        first=service.list_operations(run["run_id"],"owner",limit=2)
        second=service.list_operations(run["run_id"],"owner",limit=2,offset=first["page"]["next_offset"])
        assert first["page"]["total"]==3 and second["page"]["returned"]==1
        assert len({item["operation_id"] for item in first["items"]+second["items"]})==3
        import pytest
        with pytest.raises((FileNotFoundError,PermissionError)):service.list_operations(run["run_id"],"another-owner")
    finally:service.close()
