from sentra_remote.onboarding import build_onboarding_snapshot


def _status(*, configured=False, mcp=False, tunnel=False, web=True, edge=False):
    return {
        "mcp": {"ok": mcp},
        "tunnel": {"ok": tunnel, "configured": configured},
        "credential_storage": {"ok": configured, "configured": configured},
        "web_models": {"ok": web},
        "edge": {"ok": edge},
        "relay": {"ok": True},
        "git": {"ok": None, "lazy": True},
        "sandbox": {"ok": None, "lazy": True},
    }


def test_local_onboarding_does_not_require_external_credentials():
    snapshot = build_onboarding_snapshot(_status())
    assert snapshot.stage == "START_SENTRA"
    assert snapshot.ready is False
    assert snapshot.actions[0].id == "start_verify"


def test_chatgpt_onboarding_still_explains_required_external_steps():
    snapshot = build_onboarding_snapshot(_status(), intent="chatgpt")
    assert snapshot.stage == "CONNECT_OPENAI"
    assert not snapshot.ready
    assert [a.id for a in snapshot.actions] == [
        "open_tunnels", "open_api_keys", "connect_verify"
    ]


def test_local_onboarding_starts_runtime_without_openai():
    snapshot = build_onboarding_snapshot(_status(configured=True))
    assert snapshot.stage == "START_SENTRA"
    assert snapshot.actions[0].id == "start_verify"


def test_local_ready_independently_of_tunnel_git_docker_and_edge():
    snapshot = build_onboarding_snapshot(_status(mcp=True, edge=False))
    assert snapshot.ready is True
    assert snapshot.stage == "READY"
    assert [s.id for s in snapshot.surfaces] == [
        "terminal", "chatgpt", "codex", "browser"
    ]
    assert next(s for s in snapshot.surfaces if s.id == "terminal").ready
    assert not next(s for s in snapshot.surfaces if s.id == "chatgpt").ready
    assert not next(s for s in snapshot.surfaces if s.id == "browser").ready
    assert all(tool.optional for tool in snapshot.optional_tools)


def test_chatgpt_ready_only_if_configured_and_healthy():
    snapshot = build_onboarding_snapshot(
        _status(configured=True, mcp=True, tunnel=True), intent="chatgpt"
    )
    assert snapshot.ready is True
    assert next(s for s in snapshot.surfaces if s.id == "chatgpt").ready


def test_reauth_blocks_chatgpt_but_not_local_use():
    status = _status(configured=True, mcp=True, tunnel=False)
    status["tunnel"]["reauth_required"] = True
    snapshot = build_onboarding_snapshot(status)
    assert snapshot.stage == "READY"
    assert "new Runtime API key with All permissions" in snapshot.detail
    chatgpt = build_onboarding_snapshot(status, intent="chatgpt")
    assert chatgpt.stage == "CONNECT_OPENAI"
    assert "invalidated" in chatgpt.detail


def test_unhealthy_credential_storage_blocks_only_external_integration():
    status = _status(configured=True, mcp=True, tunnel=True)
    status["credential_storage"]["ok"] = False
    local = build_onboarding_snapshot(status)
    assert local.ready is True
    assert not next(s for s in local.surfaces if s.id == "chatgpt").ready
    chatgpt = build_onboarding_snapshot(status, intent="chatgpt")
    assert not chatgpt.ready
    assert "not healthy" in chatgpt.detail


def test_relay_alone_is_not_a_paired_edge_extension():
    snapshot = build_onboarding_snapshot(_status(mcp=True, edge=False))
    edge = next(s for s in snapshot.surfaces if s.id == "browser")
    assert not edge.ready
    assert "Relay running" in edge.detail

def test_one_click_plugin_handoff_requires_real_local_and_tunnel_health():
    from sentra_remote.onboarding import chatgpt_plugin_install_plan

    missing = chatgpt_plugin_install_plan(_status(mcp=True))
    assert not missing["ready_to_install"]
    assert missing["requires_account_authorization"]
    offline = chatgpt_plugin_install_plan(
        _status(configured=True, mcp=True, tunnel=False),
        tunnel_id="tunnel_example_0123456789",
    )
    assert not offline["ready_to_install"]
    assert "not online" in offline["reason"]
    ready = chatgpt_plugin_install_plan(
        _status(configured=True, mcp=True, tunnel=True),
        tunnel_id="tunnel_example_0123456789",
    )
    assert ready["ready_to_install"]
    assert ready["tunnel_id"] == "tunnel_example_0123456789"
    assert ready["chatgpt_url"] == "https://chatgpt.com/"
    assert any("review" in text.lower() for text in ready["steps"])
    assert not any("key" in key for key in ready)


