"""Live Canvas machine quota blocks new I/O and does not recharge replay."""
from pathlib import Path

from test_sentra_runtime_canvas_center_http import running_canvas,request
from test_canvas_machine_documents_integration import configured


def test_machine_attempt_quota_is_reserved_once_and_denies_second_effect(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws,machine,prepared=configured(app,server)
        wid=prepared["work_item"]["work_item_id"]
        host=app._machine_service()
        host.control.budget_set(host.owner,scope_type="work_item",scope_id=wid,
                               limits={"quota_usage":1},mode="hard_stop")
        root=Path(app.store.workspace(ws)["path"])
        source=root/"data.csv";source.write_text("name,value\nAda,10\n",encoding="utf-8")
        body={"ws":ws,"machine_id":machine["machine_id"],"work_item_id":wid,
            "capability_id":"document:transform","operation_id":"op-budget-one","request_key":"budget-one",
            "arguments":{"action":"table.transform","input":str(source),"output":str(root/"first.csv"),"select":["name"]}}
        code,first=request(server,"/api/center/execute",json_body=body)
        assert code==200 and first["state"]=="SUCCEEDED",first
        code,replayed=request(server,"/api/center/execute",json_body=body)
        assert code==200 and replayed==first
        code,denied=request(server,"/api/center/execute",json_body={**body,"operation_id":"op-budget-two",
            "request_key":"budget-two","arguments":{**body["arguments"],"output":str(root/"second.csv")}})
        assert code==403,denied
        assert not (root/"second.csv").exists()
        db=host.control.store.connect("governance")
        try:
            assert db.execute("SELECT SUM(quota_usage) FROM cost_events WHERE owner=? AND work_item_id=?",
                              (host.owner,wid)).fetchone()[0]==1
        finally:db.close()
