from __future__ import annotations

import asyncio
import hashlib
import json
import os
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
    sync_workspace_registry,
)
from sentra_remote.update_helper import INSTALL_MARKER, cleanup_install, rollback_update


def test_profile_contracts_are_materially_distinct() -> None:
    assert PROFILE_POLICIES["Safe"]["process_mode"] == "sandbox"
    assert PROFILE_POLICIES["Safe"]["tool_allowlist"]
    assert PROFILE_POLICIES["Developer"]["process_mode"] == "workspace"
    assert PROFILE_POLICIES["Developer"]["tool_allowlist"] == ()
    assert PROFILE_POLICIES["Full"]["surfaces"] == ("all",)


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



def test_product_settings_persist_valid_web_model_default(tmp_path: Path) -> None:
    state = tmp_path / "desktop.json"
    settings = ProductSettings(web_model_name=" sentra/chatgpt-web/high ")
    settings.save(state)
    loaded = ProductSettings.load(state)
    assert loaded.web_model_name == "sentra/chatgpt-web/high"

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
    backup = tmp_path / "SENTRA" / "Rollback" / "previous"
    state_dir = tmp_path / "state"
    install.mkdir(parents=True)
    backup.mkdir(parents=True)
    state_dir.mkdir()
    marker = json.dumps({"product": "SENTRA Desktop", "version": "1.0.0"})
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
        json.dumps({"product": "SENTRA Desktop", "version": "1.0.0"}),
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


def test_update_helper_does_not_override_ports_without_explicit_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = tmp_path / "SENTRA" / "Commander"
    install.mkdir(parents=True)
    marker = {"product": "SENTRA Desktop", "version": "1.0.0"}
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
