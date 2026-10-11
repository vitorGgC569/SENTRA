"""Owner MCP account change is an intent, NOT a claim that Free->Plus occurred."""
import json
import sqlite3

from sentra_canvas.mcp_account_switch import MCPAccountSwitch
from sentra_remote.connector_proof import ConnectorProof
from test_sentra_runtime_canvas_center_http import running_canvas, request


def _fake_public_tunnel(root):
    # Never put an actual key or live account identifier in tests.
    root.mkdir(parents=True, exist_ok=True)
    (root / "tunnel.json").write_text(
        json.dumps({"tunnel_id": "tunnel_sample123456789"}), encoding="utf-8")


def test_owner_account_switch_intent_is_durable_and_never_verifies_plus(tmp_path):
    root=tmp_path/"state"
    _fake_public_tunnel(root)
    wizard=MCPAccountSwitch(root)
    empty=wizard.status("owner")
    assert empty["tunnel_configured"] and not empty["active"]
    assert empty["chatgpt_plan_verified"] is False
    try:
        wizard.begin("owner")
        assert False, "owner consent required"
    except PermissionError:
        pass
    first=wizard.begin("owner",approved=True)
    assert first["active"] and first["requested_plan"]=="Plus"
    assert not first["chatgpt_account_verified"]
    assert first["attempt_id"]==wizard.begin("owner",approved=True)["attempt_id"]
    again=MCPAccountSwitch(root)
    assert again.status("owner")["attempt_id"]==first["attempt_id"]
    assert not again.status("other")["active"]
    ConnectorProof(root).record_tool(surface="core",authenticated=True,
                                      transport="streamable-http")
    observation=again.status("owner")
    assert observation["new_mcp_activity_observed"]
    assert observation["chatgpt_account_verified"] is False
    assert observation["chatgpt_plan_verified"] is False
    assert observation["safe_to_claim_plus_active"] is False
    claimed=again.mark_steps("owner",first["attempt_id"],approved=True)
    assert claimed["operator_steps_completed"] and not claimed["chatgpt_plan_verified"]
    try:
        again.cancel("owner","wrong_attempt",approved=True)
        assert False, "wrong attempt must be rejected"
    except PermissionError:
        pass
    closed=again.cancel("owner",first["attempt_id"],approved=True)
    assert not closed["active"]
    assert closed["old_free_connection_revoked"]=="unverified"
    with sqlite3.connect(root/"mcp-account-switch.sqlite3") as db:
        text=json.dumps(db.execute("SELECT * FROM chatgpt_mcp_switches").fetchall())
        assert "sk-" not in text and "keyring:" not in text and "dpapi:" not in text


def test_canvas_mcp_account_switch_http_is_authenticated_workspace_bounded(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace("First")["id"]
        other=app.create_workspace("Second")["id"]
        route="/api/center/mcp-account"
        code,initial=request(server,route+"?ws="+ws)
        assert code==200 and initial["chatgpt_plan_verified"] is False
        assert not initial["tunnel_configured"]
        assert request(server,route+"?ws="+ws,authorized=False)[0]==401
        assert request(server,route,json_body={"ws":ws,"action":"begin","approve":True})[0]==400
        _fake_public_tunnel(app.state_dir.parent)
        payload={"ws":ws,"action":"begin","approve":True}
        assert request(server,route,json_body=payload,authorized=False)[0]==401
        assert request(server,route,json_body={**payload,"approve":False})[0]==403
        assert request(server,route,json_body={**payload,"runtime_key":"bad"})[0]==400
        code,started=request(server,route,json_body=payload)
        assert code==200,started
        attempt=started["attempt_id"]
        assert started["tunnel_id"]=="tunnel_sample123456789"
        assert not started["chatgpt_plugin_installation_verified"]
        assert not started["chatgpt_account_verified"]
        assert request(server,route,json_body={**payload,"ws":"missing"})[0] in (403,404,500)
        code,current=request(server,route+"?ws="+other)
        assert code==200 and current["attempt_id"]==attempt
        # The switch belongs to the desktop owner (MCP connection is
        # user-wide), not to a temporary Canvas workspace.
        assert request(server,route,json_body={"ws":ws,"action":"mark_steps",
                    "attempt_id":"other","approve":True})[0]==403
        code,marked=request(server,route,json_body={"ws":ws,"action":"mark_steps",
                     "attempt_id":attempt,"approve":True})
        assert code==200 and marked["operator_steps_completed"]
        assert not marked["safe_to_claim_plus_active"]
        code,closed=request(server,route,json_body={"ws":ws,"action":"cancel",
                     "attempt_id":attempt,"approve":True})
        assert code==200 and not closed["active"]
        assert request(server,route,json_body={"ws":ws,"action":"cancel",
                        "attempt_id":attempt,"approve":True})[0]==403
