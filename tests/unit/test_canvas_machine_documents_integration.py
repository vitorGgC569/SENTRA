"""Real Canvas API -> durable authority -> document I/O -> restart evidence."""
from __future__ import annotations

from pathlib import Path

import pytest

from test_sentra_runtime_canvas_center_http import running_canvas, request


def configured(app, server, *, name="Documents"):
    ws = app.create_workspace(name)["id"]
    agent = app.create_agent(ws, "Document worker", "sentra/test", start=False)
    code, machine = request(server, "/api/center/machine/configure", json_body={
        "ws": ws, "agent_id": agent["id"], "kind": "documents"})
    assert code == 200, machine
    code, task = request(server, "/api/center/task/prepare", json_body={
        "ws": ws, "machine_id": machine["machine_id"],
        "capabilities": ["document:transform"], "objective": "Select verified CSV columns"})
    assert code == 200, task
    return ws, machine, task


def test_production_canvas_routes_transform_real_csv_and_recover_evidence(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws, machine, task = configured(app, server)
        workspace = Path(app.store.workspace(ws)["path"])
        source, output = workspace / "source.csv", workspace / "result.csv"
        source.write_text("name,value,other\nAda,10,x\nLinus,20,y\n", encoding="utf-8")
        body = {"ws": ws, "machine_id": machine["machine_id"],
            "work_item_id": task["work_item"]["work_item_id"], "capability_id": "document:transform",
            "operation_id": "op-document-http", "request_key": "document-http-key",
            "arguments": {"action": "table.transform", "input": str(source),
                          "output": str(output), "select": ["name", "value"]}}
        code, result = request(server, "/api/center/execute", json_body=body)
        assert code == 200 and result["state"] == "SUCCEEDED", result
        assert output.read_text(encoding="utf-8").splitlines() == ["name,value", "Ada,10", "Linus,20"]
        assert source.read_text(encoding="utf-8").startswith("name,value,other")
        before = output.stat().st_mtime_ns
        code, repeated = request(server, "/api/center/execute", json_body=body)
        assert code == 200 and repeated == result
        assert output.stat().st_mtime_ns == before
        code, observed = request(server, "/api/center/operation?ws=" + ws + "&operation_id=op-document-http")
        assert code == 200 and observed == result
        # Owner can still inspect a result after revoking the executing agent.
        host = app._machine_service()
        for gid in task["grant_ids"]:
            host.control.authorization_revoke(gid, host.owner)
        code, observed = request(server, "/api/center/operation?ws=" + ws + "&operation_id=op-document-http")
        assert code == 200 and observed == result
        code, denied = request(server, "/api/center/execute", json_body={**body,
            "operation_id": "op-document-revoked", "request_key": "document-revoked-key"})
        assert code == 403, denied


def test_canvas_machine_routes_require_bearer_workspace_and_scoped_capability(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws, machine, task = configured(app, server)
        code, _ = request(server, "/api/center/machines?ws=" + ws, authorized=False)
        assert code == 401
        other = app.create_workspace("Other")["id"]
        code, denied = request(server, "/api/center/task/prepare", json_body={
            "ws": other, "machine_id": machine["machine_id"],
            "capabilities": ["document:transform"], "objective": "outside workspace"})
        assert code != 200
        code, denied = request(server, "/api/center/task/prepare", json_body={
            "ws": ws, "machine_id": machine["machine_id"],
            "capabilities": ["execute:anything"], "objective": "unregistered capability"})
        assert code != 200


def test_machine_host_restart_reads_existing_result_without_launching_provider(tmp_path):
    from sentra_runtime.machine_host import MachineHost
    with running_canvas(tmp_path) as (app, server):
        ws, machine, task = configured(app, server)
        workspace = Path(app.store.workspace(ws)["path"])
        source = workspace / "values.csv"
        source.write_text("name\nAda\n", encoding="utf-8")
        body = {"ws": ws, "machine_id": machine["machine_id"],
            "work_item_id": task["work_item"]["work_item_id"], "capability_id": "document:transform",
            "operation_id": "op-restart-evidence", "request_key": "restart-evidence-key",
            "arguments": {"action": "table.transform", "input": str(source),
                          "output": str(workspace / "copied.csv")}}
        code, result = request(server, "/api/center/execute", json_body=body)
        assert code == 200 and result["state"] == "SUCCEEDED", result
        host = app._machine_service()
        restarted = MachineHost(host.control, owner=host.owner)
        try:
            assert restarted.inventory(ws) == []
            assert restarted.observe(workspace_id=ws, operation_id=body["operation_id"], as_owner=True) == result
        finally:
            restarted.close()
