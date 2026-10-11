"""Real entrypoints, temporary protected stores, and no external model calls."""
import json

from sentra_cli.agent import SentraAgent
from sentra_cli.config import CLIConfig
from sentra_cli.client import ModelClient
from sentra_mcp.services.authorization import AuthorizationService
from test_sentra_runtime_canvas_center_http import running_canvas, request


def config(tmp_path, **kwargs):
    return CLIConfig(workspace=tmp_path, state_root=tmp_path / "state", model="sentra/codex/current",
                     auto_start_gateway=False, openai_api_key="none", **kwargs)


def test_cli_goal_and_requested_choices_survive_restart_without_grant_or_send(tmp_path):
    first = SentraAgent(config(tmp_path))
    goal = first.goal_loop_command("goal", "set", objective="PRIVATE_GOAL_ENTRYPOINT")
    assert goal["state"] == "ACTIVE"
    blocked = first.goal_loop_command("loop", "start")
    assert blocked["state"] == "BLOCKED" and blocked["required_capability"] == "goal:iterate"
    first.config.model = "sentra/chatgpt-web/high"
    first.config.web_reasoning_effort = "high"
    first.persist_model_preferences()
    view = {"transport": "durable_v2", "messages": [{"request_id": "private-request-identifier", "state": "UNCONFIRMED"}]}
    first._web_delivery(view)
    second = SentraAgent(config(tmp_path, session_id=first.session_id, resume_session=True))
    assert second.config.model == "sentra/chatgpt-web/high"
    assert second.config.web_reasoning_effort == "high"
    assert second.goal_loop_command("goal")["goal_id"] == goal["goal_id"]
    assert "PRIVATE_GOAL_ENTRYPOINT" in second._context_system_prompt
    cached = second.store.web_delivery_status(second.session_id, workspace=tmp_path)
    assert cached["messages"][0]["state"] == "UNCONFIRMED" and cached["display_only"] is True
    assert "private-request-identifier" not in json.dumps(second.messages)
    assert AuthorizationService(second.store.telemetry_root).list_grants("cli:" + second.store.principal)["items"] == []
    assert not (second.store.telemetry_root / "browser" / "relay.sqlite3").exists()
    assert second.goal_loop_command("goal", "stop")["state"] == "CANCELLED"
    second._history()
    assert "PRIVATE_GOAL_ENTRYPOINT" not in second._context_system_prompt


def test_canvas_owner_goal_route_blocks_ungranted_loop_and_unknown_authority(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("Goal_entrypoint")["id"]
        code, result = request(server, "/api/center/goal-loop", json_body={"ws": ws, "action": "set", "objective": "Private Canvas goal"})
        assert code == 200 and result["goals"][0]["state"] == "ACTIVE"
        goal = result["goals"][0]["goal_id"]
        code, result = request(server, "/api/center/goal-loop", json_body={"ws": ws, "action": "start", "goal_id": goal})
        assert code == 200 and result["goals"][0]["state"] == "BLOCKED"
        assert result["grants_created"] is False
        code, deliveries = request(server, "/api/center/web-delivery?ws=" + ws)
        assert code == 200 and deliveries["messages"] == [] and deliveries["automatic_resend"] is False
        assert request(server, "/api/center/web-delivery?ws=" + ws, authorized=False)[0] == 401
        assert request(server, "/api/center/goal-loop", json_body={"ws": ws, "action": "stop", "goal_id": "other-goal"})[0] == 403
        assert request(server, "/api/center/compact-resume", json_body={"ws": ws, "action": "prepare", "arguments": {"operator_approved": True}})[0] == 400
        owner = app._runtime().owner
        assert app._machine_service().control.authorization.list_grants(owner)["items"] == []


def test_explicit_web_choice_never_downgrades_to_a_paid_or_local_provider(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    cfg.model = "sentra/chatgpt-web/high"
    cfg.openai_api_key = "test-key-never-used"
    client = ModelClient(cfg)
    monkeypatch.setattr(client, "probe_health", lambda: {"gateway": False, "local": True, "openai": True})
    monkeypatch.setattr(client, "_browser_host_ready", lambda: False)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Selected Web request cannot be sent to another provider")
    monkeypatch.setattr(client, "_chat_completions_stream", forbidden)
    output = "".join(client.chat_stream([{"role": "user", "content": "private"}]))
    assert "no fallback submitted" in output
    assert client.last_delivery_state == "not_submitted" and client.active_model == cfg.model
