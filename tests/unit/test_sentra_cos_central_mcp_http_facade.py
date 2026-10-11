"""Real authenticated Canvas->Control Plane MCP HTTP catalog, no MCP effect.

This is only operator catalog management. Tools cannot be called via this
surface, and no WorkItem, Authorization grant or worker is created by it.
"""
from test_sentra_runtime_canvas_center_http import running_canvas, request


def test_mcp_http_catalog_owner_bearer_approval_exact_schema_and_revocation(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        workspace = app.create_workspace("TrustedHTTP")
        ws = workspace["id"]
        other = app.create_workspace("OtherHTTP")["id"]
        path = "/api/center/mcp-http"
        code, state = request(server, path+"?ws="+ws)
        assert code == 200 and state["servers"] == []
        assert state["grants_created"] is False
        assert state["remote_chatgpt_tools_verified"] is False
        data = dict(ws=ws, action="register", server_id="trusted-mcp",
                    endpoint="http://127.0.0.1:17777/mcp", approve=True)
        assert request(server,path,json_body=data,authorized=False)[0] == 401
        assert request(server,path,json_body={**data,"approve":False})[0] == 403
        assert request(server,path,json_body={**data,"access_token":"bad"})[0] == 400
        assert request(server,path,json_body={**data,"endpoint":"http://example.com/mcp"})[0] in (400,403)
        code, created = request(server,path,json_body=data)
        assert code == 200, created
        assert created["enabled"] == 1 and created["revision"] == 1
        assert created["grants_created"] is False and created["worker_started"] is False
        code, view = request(server,path+"?ws="+ws)
        assert code == 200
        assert len(view["servers"]) == 1
        assert view["servers"][0]["server_id"] == "trusted-mcp"
        assert request(server,path+"?ws="+other)[1]["servers"] == []
        assert app._machine_service().control.authorization.list_grants(
            app._runtime().owner)["items"] == []
        assert request(server,path,json_body={"ws":ws,"action":"disable",
               "server_id":"trusted-mcp","approve":False})[0] == 403
        assert request(server,path,json_body={"ws":other,"action":"disable",
               "server_id":"trusted-mcp","approve":True})[0] in (403,404)
        code, disabled = request(server,path,json_body={"ws":ws,"action":"disable",
               "server_id":"trusted-mcp","approve":True})
        assert code == 200, disabled
        assert disabled["enabled"] == 0
        assert disabled["revision"] == 2
        assert request(server,path,json_body=data)[0] in (400,403)
        code, current = request(server,path+"?ws="+ws)
        assert code == 200 and current["servers"][0]["enabled"] == 0


def test_mcp_http_catalog_host_facade_is_inert_until_workitem_gate(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws=app.create_workspace("Empty")["id"]
        control=app._machine_service().control
        root=app.store.workspace(ws)["path"]
        owner=app._runtime().owner
        response=control.mcp_http_register(owner,root,"local","http://127.0.0.1:17777/mcp",approved=True)
        assert response["grants_created"] is False
        assert response["worker_started"] is False
        assert control.mcp_http_list(owner,root)["servers"][0]["enabled"] == 1
        # A registered endpoint is not an executable provider grant.
        assert control.authorization.list_grants(owner)["items"] == []
        assert control.mcp_http_disable(owner,root,"local",approved=True)["enabled"] == 0
