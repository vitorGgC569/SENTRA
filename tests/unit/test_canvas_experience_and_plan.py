"""Experience provenance/expiry and plan undo across real committed file I/O."""
from pathlib import Path

import pytest

from test_sentra_runtime_canvas_center_http import running_canvas,request
from test_canvas_machine_documents_integration import configured


def executed(app,server):
    ws,machine,prepared=configured(app,server)
    wid=prepared["work_item"]["work_item_id"]
    folder=Path(app.store.workspace(ws)["path"])
    source=folder/"source.csv";source.write_text("name,value\nAda,10\n",encoding="utf-8")
    code,result=request(server,"/api/center/execute",json_body={"ws":ws,"machine_id":machine["machine_id"],
        "work_item_id":wid,"capability_id":"document:transform","operation_id":"op-experience-csv",
        "request_key":"experience-key","arguments":{"action":"table.transform","input":str(source),
        "output":str(folder/"result.csv"),"select":["name"]}})
    assert code==200 and result["state"]=="SUCCEEDED",result
    return ws,machine,prepared,source,result


def test_second_task_recovers_origin_and_changed_source_is_not_reused(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws,machine,first,source,result=executed(app,server)
        second=app.center_prepare_task(ws,machine["machine_id"],["document:transform"],"Another table transform")
        value=app.center_experiences(ws,second["work_item"]["work_item_id"],machine["machine_id"],"table transform")
        assert value["knowledge_only"] is True and len(value["experiences"])==1
        memory=value["experiences"][0]
        assert memory["origin"]["operation_id"]==result["operation_id"]
        assert memory["origin"]["work_item_id"]==first["work_item"]["work_item_id"]
        source.write_text("name,value\nChanged,99\n",encoding="utf-8")
        assert app.center_experiences(ws,second["work_item"]["work_item_id"],machine["machine_id"],"table transform")["experiences"]==[]
        host=app._machine_service()
        for grant in second["grant_ids"]:host.control.authorization_revoke(grant,host.owner)
        with pytest.raises(PermissionError):
            app.center_experiences(ws,second["work_item"]["work_item_id"],machine["machine_id"],"table transform")


def test_plan_undo_retains_executed_step_without_repeating_csv_effect(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws,machine,prepared,source,result=executed(app,server)
        wid=prepared["work_item"]["work_item_id"]
        proposed={"id":"prepare","title":"Review table","capability_id":"document:transform"}
        first=app.center_plan(ws,wid,"revise",[proposed],0)
        completed={"id":"transform","title":"CSV transformation","capability_id":"document:transform",
                   "operation_id":result["operation_id"],"depends_on":["prepare"]}
        app.center_plan(ws,wid,"revise",[proposed,completed],first["revision"])
        output=source.parent/"result.csv";before=output.stat().st_mtime_ns
        undone=app.center_plan(ws,wid,"undo",expected_revision=2)
        assert undone["revision"]==1 and undone["executed_step_ids"]==["transform"]
        assert completed in undone["steps"] and undone["proposal_only"] is True
        assert output.stat().st_mtime_ns==before
        with pytest.raises(ValueError):
            app.center_plan(ws,wid,"revise",[proposed,{**completed,"title":"changed executed step"}],1)
        redone=app.center_plan(ws,wid,"redo",expected_revision=1)
        assert redone["revision"]==2 and output.stat().st_mtime_ns==before
