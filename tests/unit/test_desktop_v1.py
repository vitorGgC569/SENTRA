from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from pathlib import Path

import pytest
from mcp import Client

from sentra_mcp.config import MCPConfig
from sentra_mcp.server import SentraMCPServer
from sentra_mcp.services.browser import BrowserControlService
from sentra_mcp.tool_policy import ToolPolicyProxy, filter_tool_names
from sentra_remote import desktop as desktop_mod
from sentra_remote import installer as installer_mod
from sentra_remote import update_helper as update_helper_mod
from sentra_remote.agent_config import AgentConfig
from sentra_remote.product import (
    PROFILE_POLICIES,
    ProductPaths,
    ProductSettings,
    configure_tunnel,
    create_snapshot,
    enqueue_task,
    list_tasks,
    load_tunnel_config,
    rollback_snapshot,
    agent_bootstrap_root,
    sync_agent_policy,
    sync_workspace_registry,
)
from sentra_remote.update_helper import INSTALL_MARKER, cleanup_install, rollback_update


def test_profile_contracts_are_materially_distinct() -> None:
    assert PROFILE_POLICIES["Safe"]["process_mode"] == "sandbox"
    assert PROFILE_POLICIES["Safe"]["tool_allowlist"]
    assert PROFILE_POLICIES["Developer"]["process_mode"] == "workspace"
    assert PROFILE_POLICIES["Developer"]["tool_allowlist"] == ()
    assert PROFILE_POLICIES["Full"]["surfaces"] == ("all",)


def test_quick_start_state_tracks_install_connect_ready_journey() -> None:
    progress, headline, action = desktop_mod._quick_start_state({}, has_tunnel=False)
    assert progress == 70
    assert headline == "Start SENTRA"
    assert "OpenAI is optional" in action

    progress, headline, action = desktop_mod._quick_start_state(
        {
            "mcp": {"ok": True},
            "relay": {"ok": True},
            "tunnel": {"ok": True},
            "credential_storage": {"configured": True, "ok": True},
        },
        has_tunnel=True,
    )
    assert progress == 100
    assert headline == "Ready"
    assert "terminal" in action.lower()
    assert "Codex" in action
    assert "ChatGPT" in action

    progress, headline, action = desktop_mod._quick_start_state(
        {
            "mcp": {"ok": True},
            "relay": {"ok": False},
            "tunnel": {"ok": False},
            "credential_storage": {"configured": True, "ok": True},
        },
        has_tunnel=True,
    )
    assert progress == 100
    assert headline == "Ready"
    assert "tunnel" in action.lower()

    progress, headline, action = desktop_mod._quick_start_state(
        {
            "credential_storage": {"configured": True, "ok": False},
        },
        has_tunnel=True,
    )
    assert progress == 70
    assert headline == "Start SENTRA"
    assert "OpenAI is optional" in action


def test_installer_error_message_is_actionable_for_tunnel_credentials() -> None:
    message = installer_mod._friendly_install_error(
        ValueError("both tunnel_id and Runtime API key are required")
    )
    assert "What to do:" in message
    assert "All permissions" in message


def test_connect_installed_openai_reuses_existing_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_dir = tmp_path / "install"
    state_dir = tmp_path / "state"
    install_dir.mkdir()
    (install_dir / installer_mod.INSTALL_MARKER).write_text(
        json.dumps({"product": "SENTRA Desktop", "version": "test"}),
        encoding="utf-8",
    )
    calls: list[tuple[str, str]] = []
    progress: list[tuple[str, int]] = []

    def fake_configure(_paths, tunnel_id: str, runtime_key: str) -> None:
        calls.append((tunnel_id, runtime_key))

    class FakeRuntime:
        def __init__(self, _paths, _settings) -> None:
            pass

        def connect_and_verify(self, timeout_s: float = 12.0):
            assert timeout_s == 12.0
            return {
                "core_ready": True,
                "chatgpt_onboarding": {"ready": True},
                "onboarding_required": False,
                "started": {"mcp": True},
                "status": {
                    "mcp": {"ok": True},
                    "relay": {"ok": True},
                    "tunnel": {"ok": True},
                },
                "next_url": "sentra://home",
            }

    monkeypatch.setattr(installer_mod, "configure_tunnel", fake_configure)
    monkeypatch.setattr(
        installer_mod,
        "_enable_web_models_autostart",
        lambda _paths, _install_dir: {"ok": True, "autostart": True},
    )
    monkeypatch.setattr(installer_mod, "LocalRuntime", FakeRuntime)

    result = installer_mod.connect_installed_openai(
        install_dir=install_dir,
        state_dir=state_dir,
        tunnel_id="tunnel_test",
        runtime_key="runtime-test-key",
        launch=False,
        progress=lambda label, percent: progress.append((label, percent)),
    )

    assert result["reused_install"] is True
    assert result["connect_verify"]["core_ready"] is True
    assert calls == [("tunnel_test", "runtime-test-key")]
    assert progress[-1] == ("Ready", 100)


def test_product_settings_normalize_workspace_permissions(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    state = tmp_path / "desktop.json"
    settings = ProductSettings(
        profile="Safe",
        allowed_roots=[str(workspace)],
        workspace_permissions={str(workspace): ["write", "READ", "unknown"]},
    )
    settings.save(state)
    loaded = ProductSettings.load(state)
    root = str(workspace.resolve())
    assert loaded.allowed_roots == [root]
    assert loaded.workspace_permissions[root] == ["read", "write"]



def test_gateway_stop_restores_codex_route_before_shutdown() -> None:
    calls: list[str] = []

    class Launcher:
        def route(self, action: str = "status"):
            calls.append(action)
            if action == "status":
                return {"points_to_sentra": True}
            if action == "disconnect":
                return {"points_to_sentra": False}
            raise AssertionError(action)

    desktop = desktop_mod.SentraDesktop.__new__(desktop_mod.SentraDesktop)
    desktop.web_gateway = type("Gateway", (), {"launcher": Launcher()})()
    restored, detail = desktop._restore_codex_route_before_gateway_stop()
    assert restored is True
    assert detail == ""
    assert calls == ["status", "disconnect"]


def test_gateway_stop_refuses_when_codex_route_cannot_be_restored() -> None:
    class Launcher:
        def route(self, action: str = "status"):
            if action == "status":
                return {"points_to_sentra": True}
            raise RuntimeError("rollback failed")

    desktop = desktop_mod.SentraDesktop.__new__(desktop_mod.SentraDesktop)
    desktop.web_gateway = type("Gateway", (), {"launcher": Launcher()})()
    restored, detail = desktop._restore_codex_route_before_gateway_stop()
    assert restored is False
    assert "rollback failed" in detail


def test_codex_route_recovery_detects_sentra_gateway(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'model = "gpt-6-sol"\nopenai_base_url = "http://127.0.0.1:17842/v1"\n',
        encoding="utf-8",
    )
    assert desktop_mod._codex_route_points_to_sentra(config) is True

    config.write_text(
        'model = "gpt-6-sol"\nopenai_base_url = "https://chatgpt.com/backend-api/codex"\n',
        encoding="utf-8",
    )
    assert desktop_mod._codex_route_points_to_sentra(config) is False


def test_product_settings_persist_valid_web_model_default(tmp_path: Path) -> None:
    state = tmp_path / "desktop.json"
    settings = ProductSettings(web_model_name=" sentra/chatgpt-web/high ")
    settings.save(state)
    loaded = ProductSettings.load(state)
    assert loaded.web_model_name == "sentra/chatgpt-web/high"

    gemini_state = tmp_path / "gemini.json"
    ProductSettings(web_model_name="sentra/gemini-web/flash").save(gemini_state)
    assert ProductSettings.load(gemini_state).web_model_name == "sentra/gemini-web/flash"

    with pytest.raises(ValueError, match="sentra/chatgpt-web/"):
        ProductSettings(web_model_name="chatgpt-web/high").save(tmp_path / "invalid.json")


def _write_web_models_fixture(
    tmp_path: Path,
    *,
    patch_hash: str | None = None,
    built_files: list[str] | None = None,
) -> tuple[Path, Path]:
    install = tmp_path / "install"
    integration = install / "integrations" / "codex_chatgpt_web"
    payload = install / "dist" / "web-models"
    launcher = payload / "win-unpacked" / "Codex Web GPT.exe"
    integration.mkdir(parents=True)
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"MZ")
    patch = integration / "sentra-upstream.patch"
    patch.write_text("sentra-patch\n", encoding="utf-8")
    expected_files = ["launcher/electron/main.cjs", "src/config.ts"]
    (integration / "upstream.json").write_text(
        json.dumps({"patch_files": expected_files}),
        encoding="utf-8",
    )
    (payload / "integration-build.json").write_text(
        json.dumps(
            {
                "patch_sha256": patch_hash or hashlib.sha256(patch.read_bytes()).hexdigest(),
                "patch_files": expected_files if built_files is None else built_files,
            }
        ),
        encoding="utf-8",
    )
    return install, launcher


def test_desktop_accepts_current_web_models_payload(tmp_path: Path) -> None:
    install, launcher = _write_web_models_fixture(tmp_path)
    assert desktop_mod._validated_web_models_launcher(install) == launcher


def test_desktop_rejects_stale_web_models_patch_hash(tmp_path: Path) -> None:
    install, _ = _write_web_models_fixture(tmp_path, patch_hash="0" * 64)
    with pytest.raises(RuntimeError, match="payload is stale"):
        desktop_mod._validated_web_models_launcher(install)


def test_desktop_rejects_stale_web_models_patch_file_set(tmp_path: Path) -> None:
    install, _ = _write_web_models_fixture(tmp_path, built_files=["src/config.ts"])
    with pytest.raises(RuntimeError, match="patch file set is stale"):
        desktop_mod._validated_web_models_launcher(install)


def test_workspace_registry_sync_has_explicit_permissions(tmp_path: Path) -> None:
    install = tmp_path / "install"
    state = tmp_path / "state"
    workspace = tmp_path / "repo"
    install.mkdir()
    workspace.mkdir()
    paths = ProductPaths(install, state)
    settings = ProductSettings(
        allowed_roots=[str(workspace)],
        workspace_permissions={str(workspace.resolve()): ["read"]},
    )
    registry = sync_workspace_registry(paths, settings)
    data = json.loads(registry.read_text(encoding="utf-8"))
    assert len(data["grants"]) == 1
    assert data["grants"][0]["path"] == str(workspace.resolve())
    assert data["grants"][0]["permissions"] == ["read"]
    assert data["grants"][0]["source"] == "approved"


def test_state_root_is_independent_from_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state = tmp_path / "private-state"
    workspace.mkdir()
    config = MCPConfig(allowed_roots=(workspace,), state_root=state)
    server = SentraMCPServer(config)
    try:
        assert server.browser.relay_token_path == state.resolve() / "browser" / "relay-token"
        assert server.workspaces.state_path == state.resolve() / "workspaces.json"
        assert server.jobs.db_path == state.resolve() / "jobs.sqlite3"
        assert server.research.db_path == state.resolve() / "research.sqlite3"
    finally:
        server.jobs.close()
        server.search.close()
        server.processes.shutdown()
        server.remote_store.close()


def test_tool_policy_filters_registration() -> None:
    names: list[str] = []

    class FakeMCP:
        def tool(self, *args, **kwargs):
            def decorate(func):
                names.append(kwargs.get("name") or func.__name__)
                return func
            return decorate

    proxy = ToolPolicyProxy(FakeMCP(), ("sentra_read_file",))

    @proxy.tool()
    def sentra_read_file():
        return None

    @proxy.tool()
    def sentra_write_file():
        return None

    assert names == ["sentra_read_file"]
    assert filter_tool_names(["a", "b", "c"], ("b",)) == ["b"]


def test_tool_allowlist_applies_to_real_mcp(tmp_path: Path) -> None:
    config = MCPConfig(
        allowed_roots=(tmp_path,),
        state_root=tmp_path / ".state",
        tool_surfaces=("core",),
        tool_allowlist=("sentra_session_open", "sentra_read_file"),
    )
    server = SentraMCPServer(config)

    async def scenario() -> set[str]:
        async with Client(server.mcp) as client:
            listed = await client.list_tools()
            return {tool.name for tool in listed.tools}

    tools = asyncio.run(scenario())
    assert "sentra_health" in tools
    assert "sentra_session_open" in tools
    assert "sentra_read_file" in tools
    assert "sentra_write_file" not in tools
    assert "sentra_start_process" not in tools


def test_snapshot_and_workspace_rollback_are_real(tmp_path: Path) -> None:
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "a.txt").write_text("before", encoding="utf-8")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "b.txt").write_text("stable", encoding="utf-8")
    snapshot = create_snapshot(paths, workspace)
    (workspace / "a.txt").write_text("after", encoding="utf-8")
    (workspace / "new.txt").write_text("new", encoding="utf-8")
    result = rollback_snapshot(Path(snapshot["snapshot"]), workspace)
    assert result["restored"] == 2
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "before"
    assert (workspace / "sub" / "b.txt").read_text(encoding="utf-8") == "stable"
    assert not (workspace / "new.txt").exists()


def test_persistent_desktop_queue(tmp_path: Path) -> None:
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    first = enqueue_task(paths, workspace, "Run the focused tests")
    second = enqueue_task(paths, workspace, "Inspect the diff")
    rows = list_tasks(paths)
    assert {row["id"] for row in rows} == {first["task_id"], second["task_id"]}
    assert all(row["state"] == "QUEUED" for row in rows)


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-specific")
def test_tunnel_runtime_key_is_dpapi_protected(tmp_path: Path) -> None:
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    secret = "sk-runtime-not-a-real-key-" + "x" * 24
    configure_tunnel(paths, "tunnel_example_123456", secret)
    raw = paths.tunnel_config.read_text(encoding="utf-8")
    assert secret not in raw
    assert "dpapi:" in raw
    loaded = load_tunnel_config(paths, reveal_secret=True)
    assert loaded["runtime_key"] == secret


def test_update_helper_rolls_back_previous_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = tmp_path / "SENTRA" / "Commander"
    import hashlib
    backup = tmp_path / "SENTRA" / "Rollback" / hashlib.sha256(b"qa-install").hexdigest() / "previous"
    state_dir = tmp_path / "state"
    install.mkdir(parents=True)
    backup.mkdir(parents=True)
    state_dir.mkdir()
    marker = json.dumps({"product": "SENTRA Desktop", "version": "1.0.0", "installation_id": "qa-install", "owned_files": ["current.txt"]})
    (install / INSTALL_MARKER).write_text(marker, encoding="utf-8")
    (backup / INSTALL_MARKER).write_text(marker, encoding="utf-8")
    (install / "current.txt").write_text("new", encoding="utf-8")
    (backup / "previous.txt").write_text("old", encoding="utf-8")
    (state_dir / "update-state.json").write_text(
        json.dumps({
            "previous_backup": str(backup),
            "install_dir": str(install),
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state_dir))
    assert rollback_update(install, parent_pid=0) == 0
    assert not (install / "current.txt").exists()
    assert (install / "previous.txt").read_text(encoding="utf-8") == "old"
    state = json.loads((state_dir / "update-state.json").read_text(encoding="utf-8"))
    assert Path(state["previous_backup"]).name.startswith("replaced-")

def test_product_state_override_and_port_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "isolated-state"
    install = tmp_path / "install"
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    paths = ProductPaths.default(install)
    assert paths.state_dir == state.resolve()

    settings = ProductSettings(mcp_port=18080, relay_port=18080)
    with pytest.raises(ValueError, match="must be different"):
        settings.save(tmp_path / "desktop.json")


def test_edge_relay_override_is_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRA_EDGE_RELAY_URL", "http://127.0.0.1:18765")
    assert BrowserControlService._configured_relay_url() == "http://127.0.0.1:18765"

    monkeypatch.setenv("SENTRA_EDGE_RELAY_URL", "http://8.8.8.8:18765")
    with pytest.raises(ValueError, match="loopback"):
        BrowserControlService._configured_relay_url()

    monkeypatch.setenv("SENTRA_EDGE_RELAY_URL", "https://127.0.0.1:18765")
    with pytest.raises(ValueError, match="loopback http URL"):
        BrowserControlService._configured_relay_url()


def test_update_helper_cleanup_removes_install_tree(tmp_path: Path) -> None:
    install = tmp_path / "SENTRA" / "Commander"
    install.mkdir(parents=True)
    (install / INSTALL_MARKER).write_text(
        json.dumps({"product": "SENTRA Desktop", "version": "1.0.0",
                    "owned_files": ["sentra-desktop.exe", "edge_extension/manifest.json"]}),
        encoding="utf-8",
    )
    (install / "sentra-desktop.exe").write_bytes(b"dummy")
    (install / "edge_extension").mkdir()
    (install / "edge_extension" / "manifest.json").write_text("{}", encoding="utf-8")

    assert cleanup_install(install, parent_pid=0) == 0
    assert not install.exists()

def test_update_helper_cleanup_refuses_unmarked_directory(tmp_path: Path) -> None:
    install = tmp_path / "SENTRA" / "Commander"
    install.mkdir(parents=True)
    (install / "keep.txt").write_text("do not delete", encoding="utf-8")

    with pytest.raises(ValueError, match="install marker"):
        cleanup_install(install, parent_pid=0)

    assert (install / "keep.txt").is_file()


def test_upgrade_cli_preserves_existing_profile_and_ports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_install(**kwargs):
        captured.update(kwargs)
        return {"doctor": {"mcp": {"ok": True}, "relay": {"ok": True}}}

    monkeypatch.setattr(installer_mod, "install", fake_install)
    code = installer_mod.main([
        "--silent",
        "--upgrade",
        "--install-dir", str(tmp_path / "Commander"),
        "--state-dir", str(tmp_path / "state"),
        "--no-git",
        "--no-launch",
        "--no-system-registration",
    ])
    assert code == 0
    assert captured["profile"] is None
    assert captured["mcp_port"] is None
    assert captured["relay_port"] is None


@pytest.mark.parametrize("existing", [False, True])
def test_install_defaults_full_computer_and_preserves_existing_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, existing: bool,
) -> None:
    install_dir = tmp_path / "Commander"
    state_dir = tmp_path / "state"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    paths = ProductPaths(install_dir, state_dir)
    if existing:
        ProductSettings(
            profile="Developer", access_scope="workspace", mcp_port=18991,
            tool_allowlist=["sentra_health"], allowed_roots=[str(workspace)],
        ).save(paths.settings)

    captured = {}

    class Runtime:
        def __init__(self, _paths, settings):
            captured["settings"] = settings

        def connect_and_verify(self, timeout_s):
            return {
                "core_ready": True, "onboarding_required": False,
                "started": {}, "status": {"mcp": {"ok": True}},
            }

    monkeypatch.setattr(installer_mod, "_copy_product_files", lambda target: target.mkdir(exist_ok=True))
    monkeypatch.setattr(installer_mod, "download_tunnel_client", lambda *_: {"ok": True})
    monkeypatch.setattr(installer_mod, "_enable_web_models_autostart", lambda *_: {"ok": True})
    monkeypatch.setattr(installer_mod, "LocalRuntime", Runtime)
    installer_mod.install(
        install_dir=install_dir, state_dir=state_dir, workspace=workspace,
        launch=False, register_system=False,
    )
    persisted = ProductSettings.load(paths.settings)
    assert persisted.profile == ("Developer" if existing else "Full")
    assert persisted.access_scope == ("workspace" if existing else "computer")
    assert captured["settings"].profile == persisted.profile
    if existing:
        assert persisted.mcp_port == 18991
        assert persisted.tool_allowlist == ["sentra_health"]
    else:
        assert persisted.tool_allowlist == []
        registry = json.loads(sync_workspace_registry(paths, persisted).read_text())
        broad = [grant for grant in registry["grants"] if grant["source"] == "access_scope"]
        assert broad
        assert all(grant["permissions"] == ["read", "write", "execute"] for grant in broad)


def test_update_helper_does_not_override_ports_without_explicit_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = tmp_path / "SENTRA" / "Commander"
    install.mkdir(parents=True)
    marker = {"product": "SENTRA Desktop", "version": "1.0.0", "installation_id": "qa-install"}
    (install / INSTALL_MARKER).write_text(json.dumps(marker), encoding="utf-8")
    (install / "old.txt").write_text("old", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()
    setup = package / "SENTRA-Setup.exe"
    setup.write_bytes(b"dummy")
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    captured: list[str] = []

    def fake_run(command, **kwargs):
        captured.extend(str(item) for item in command)
        install.mkdir(parents=True, exist_ok=True)
        (install / INSTALL_MARKER).write_text(json.dumps(marker), encoding="utf-8")
        (install / "sentra-desktop.exe").write_bytes(b"dummy")
        return update_helper_mod.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(update_helper_mod.subprocess, "run", fake_run)
    assert update_helper_mod.apply_update(
        setup,
        install,
        parent_pid=0,
        version="1.0.0",
        manifest_url="",
        state_dir=state,
        register_system=False,
        stop_after_doctor=True,
        restart_desktop=False,
    ) == 0
    assert "--mcp-port" not in captured
    assert "--relay-port" not in captured
    assert "--state-dir" in captured
    assert "--no-system-registration" in captured
    assert "--stop-after-doctor" in captured


def test_access_scope_user_adds_broad_grant_without_removing_workspace_override(tmp_path: Path) -> None:
    install = tmp_path / "install"
    state = tmp_path / "state"
    workspace = tmp_path / "repo"
    install.mkdir()
    workspace.mkdir()
    paths = ProductPaths(install, state)
    settings = ProductSettings(
        profile="Developer",
        access_scope="user",
        allowed_roots=[str(workspace)],
        workspace_permissions={str(workspace.resolve()): ["read"]},
    )
    registry = sync_workspace_registry(paths, settings)
    data = json.loads(registry.read_text(encoding="utf-8"))
    explicit = next(item for item in data["grants"] if item["source"] == "approved")
    broad = next(item for item in data["grants"] if item["source"] == "access_scope")
    assert explicit["permissions"] == ["read"]
    assert broad["path"] == str(Path.home().resolve())
    assert broad["permissions"] == ["read", "write", "execute"]
    assert data["access_scope"] == "user"


def test_safe_computer_scope_stays_read_only(tmp_path: Path) -> None:
    state = tmp_path / "desktop.json"
    settings = ProductSettings(profile="Safe", access_scope="computer")
    settings.save(state)
    loaded = ProductSettings.load(state)
    assert loaded.access_scope == "computer"

    paths = ProductPaths(tmp_path / "install", tmp_path / "private")
    registry = sync_workspace_registry(paths, loaded)
    data = json.loads(registry.read_text(encoding="utf-8"))
    broad = [item for item in data["grants"] if item["source"] == "access_scope"]
    assert broad
    assert all(item["permissions"] == ["read"] for item in broad)


def test_remote_agent_policy_tracks_desktop_profile_and_scope(tmp_path: Path) -> None:
    install = tmp_path / "install"
    state = tmp_path / "state"
    workspace = tmp_path / "repo"
    install.mkdir()
    state.mkdir()
    workspace.mkdir()
    paths = ProductPaths(install, state)
    agent_path = state / "agent.json"
    AgentConfig(
        relay_url="https://relay.example.test",
        device_id="device-1",
        device_token="device-secret-" + "x" * 48,
        name="PC",
        allowed_roots=[str(workspace)],
        audit_log=str(state / "agent-audit.jsonl"),
        process_mode="workspace",
    ).save(agent_path)

    settings = ProductSettings(
        profile="Safe",
        access_scope="user",
        allowed_roots=[str(workspace)],
        workspace_permissions={str(workspace.resolve()): ["read"]},
    )
    settings.save(paths.settings)
    synced = sync_agent_policy(paths, settings)
    assert synced == agent_path

    loaded = AgentConfig.load(agent_path)
    assert loaded.profile == "Safe"
    assert loaded.access_scope == "user"
    assert loaded.process_mode == "sandbox"
    assert loaded.allowed_roots == [str(agent_bootstrap_root(paths))]
    assert loaded.state_root == str(state.resolve())
    assert loaded.tool_surfaces == ["core", "developer", "browser", "oma"]
    assert loaded.tool_allowlist

    registry = json.loads((state / "workspaces.json").read_text(encoding="utf-8"))
    explicit = next(item for item in registry["grants"] if item["source"] == "approved")
    broad = next(item for item in registry["grants"] if item["source"] == "access_scope")
    assert explicit["path"] == str(workspace.resolve())
    assert explicit["permissions"] == ["read"]
    assert broad["path"] == str(Path.home().resolve())
    assert broad["permissions"] == ["read"]



def test_runtime_authority_registry_is_safe_under_concurrent_writers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    workers = 12
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []

    def write(index: int) -> None:
        try:
            install = tmp_path / f"install-{index}"
            state = tmp_path / f"state-{index}"
            install.mkdir()
            state.mkdir()
            barrier.wait(timeout=5)
            ProductPaths(install, state).persist_runtime_authority()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=write, args=(index,), daemon=True)
        for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)

    registry = (
        tmp_path / "localappdata" / "SENTRA" / "runtime-authorities.json"
    )
    payload = json.loads(registry.read_text(encoding="utf-8"))
    authorities = payload["authorities"]
    assert len(authorities) == workers
    for index in range(workers):
        install = tmp_path / f"install-{index}"
        key = ProductPaths._authority_key(install)
        assert authorities[key]["install_dir"] == str(install.resolve())
        assert authorities[key]["state_dir"] == str((tmp_path / f"state-{index}").resolve())


def test_local_runtime_stop_adopts_verified_persisted_pid_after_desktop_restart(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace
    from sentra_remote import local_runtime as local_runtime_mod
    from sentra_remote.local_runtime import LocalRuntime

    install = tmp_path / "install"
    state = tmp_path / "state"
    install.mkdir()
    executable = install / "sentra-mcp.exe"
    executable.write_bytes(b"MZ")

    runtime = LocalRuntime(ProductPaths(install, state), ProductSettings())
    pid_file = runtime.runtime_dir / "mcp.pid"
    pid_file.write_text("4242", encoding="ascii")
    monkeypatch.setattr(local_runtime_mod.os, "name", "nt")
    monkeypatch.setattr(
        runtime, "_windows_process_path", lambda pid: executable.resolve()
    )

    calls = []

    def fake_run(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(local_runtime_mod.subprocess, "run", fake_run)

    assert runtime.processes == {}
    assert runtime.stop("mcp") is True
    assert calls[0][0][:4] == ["taskkill", "/PID", "4242", "/T"]
    assert calls[0][0][-1] == "/F"
    assert not pid_file.exists()


def test_sync_workspace_registry_preserves_runtime_state(tmp_path: Path) -> None:
    install = tmp_path / "install"
    state = tmp_path / "state"
    managed = tmp_path / "managed"
    runtime = tmp_path / "runtime"
    install.mkdir()
    state.mkdir()
    managed.mkdir()
    runtime.mkdir()

    paths = ProductPaths(install, state)
    existing = {
        "version": 2,
        "access_scope": "workspace",
        "grants": [{
            "workspace_id": "ws:runtime",
            "alias": "runtime",
            "path": str(runtime.resolve()),
            "permissions": ["read"],
            "scope": "permanent",
            "owner": None,
            "expires_at": None,
            "source": "approved",
            "created_at": 1.0,
            "approved_at": 2.0,
        }],
        "pending": {
            "REQ123": {
                "kind": "add",
                "status": "PENDING",
                "created_at": 3.0,
                "workspace": {"path": str(runtime.resolve())},
            }
        },
        "history": [{"request_id": "OLD", "status": "APPROVED"}],
    }
    (state / "workspaces.json").write_text(
        json.dumps(existing),
        encoding="utf-8",
    )

    settings = ProductSettings(
        allowed_roots=[str(managed)],
        workspace_permissions={str(managed.resolve()): ["read", "write"]},
    )
    registry_path = sync_workspace_registry(paths, settings)
    data = json.loads(registry_path.read_text(encoding="utf-8"))

    assert data["pending"] == existing["pending"]
    assert data["history"] == existing["history"]
    assert any(item.get("workspace_id") == "ws:runtime" for item in data["grants"])
    assert any(item.get("workspace_id", "").startswith("desktop:") for item in data["grants"])


def test_failed_web_models_start_restores_codex_route_and_closes_gateway() -> None:
    events: list[str] = []

    class FakeLauncher:
        def route(self, action: str = "status"):
            events.append("route:" + action)
            if action == "status":
                return {"points_to_sentra": True}
            return {"points_to_sentra": False}

        def stop(self):
            events.append("launcher:stop")
            return {}

    class FakeGateway:
        launcher = FakeLauncher()

        def shutdown(self):
            events.append("gateway:shutdown")

        def server_close(self):
            events.append("gateway:close")

    desktop = desktop_mod.SentraDesktop.__new__(desktop_mod.SentraDesktop)
    desktop.web_gateway = FakeGateway()
    desktop.web_gateway_thread = object()

    detail = desktop._cleanup_failed_web_models_start()

    assert "rota Codex restaurada" in detail
    assert events == [
        "route:status",
        "route:disconnect",
        "launcher:stop",
        "gateway:shutdown",
        "gateway:close",
    ]
    assert desktop.web_gateway is None
    assert desktop.web_gateway_thread is None

def test_installer_primary_action_chooses_shortest_valid_path() -> None:
    class Field:
        def __init__(self, value: str) -> None:
            self.value = value

        def get(self) -> str:
            return self.value

    calls: list[bool] = []
    wizard = object.__new__(installer_mod.InstallerWizard)
    wizard._installed = False
    wizard.tunnel_id = Field("tunnel_test")
    wizard.runtime_key = Field("runtime-key-test")
    wizard._install = lambda require_openai=True: calls.append(require_openai)

    wizard._primary_action()
    assert calls == [True]

    calls.clear()
    wizard.tunnel_id = Field("")
    wizard.runtime_key = Field("")
    wizard._primary_action()
    assert calls == [False]

    calls.clear()
    wizard._installed = True
    wizard._primary_action()
    # Local usage remains key-free even for an already-installed product.
    assert calls == [False]

def test_user_path_registration_is_idempotent_and_reversible() -> None:
    install = Path(r"C:\Users\Vitor\AppData\Local\SENTRA\Commander")
    current = r"C:\Windows;C:\Tools"

    updated, changed = installer_mod._with_user_path_entry(current, install)
    assert changed is True
    assert updated.endswith(str(install))

    repeated, changed_again = installer_mod._with_user_path_entry(
        updated + "\\",
        Path(r"c:\users\vitor\appdata\local\sentra\commander"),
    )
    assert changed_again is False
    assert installer_mod._normalize_windows_path_entry(str(install)) in {
        installer_mod._normalize_windows_path_entry(item)
        for item in repeated.split(";")
    }

    removed, did_remove = installer_mod._without_user_path_entry(
        updated,
        Path(r"c:/users/vitor/appdata/local/sentra/commander"),
    )
    assert did_remove is True
    assert removed == current

    unchanged, did_remove_again = installer_mod._without_user_path_entry(
        removed,
        install,
    )
    assert did_remove_again is False
    assert unchanged == current
