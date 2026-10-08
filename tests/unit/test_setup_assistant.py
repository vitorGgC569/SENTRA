"""Acceptance tests for zero-config, consent-based SENTRA setup."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from sentra_remote.setup_assistant import (
    SetupAssistant, detect_capabilities, first_workspace, grant_workspace,
)
from sentra_remote.local_runtime import LocalRuntime
from sentra_remote.product import ProductPaths, ProductSettings


def _paths(tmp_path: Path) -> ProductPaths:
    return ProductPaths(tmp_path / "install", tmp_path / "state")


def test_installer_reopens_existing_local_setup_instead_of_reinstall(tmp_path):
    import json
    from sentra_remote import installer
    folder = tmp_path / "Commander"
    folder.mkdir()
    (folder / installer.INSTALL_MARKER).write_text(
        json.dumps({"product": "SENTRA Desktop", "version": "test"}),
        encoding="utf-8",
    )
    for name in (*installer.PRODUCTS, "tunnel-client.exe"):
        (folder / name).write_bytes(b"installed")
    wizard = object.__new__(installer.InstallerWizard)
    wizard.install_dir = Mock(get=lambda: str(folder))
    wizard.tunnel_id = Mock(get=lambda: "")
    wizard.runtime_key = Mock(get=lambda: "")
    wizard._installed = False
    wizard._open_existing_install = Mock()
    wizard._install = Mock()

    wizard._primary_action()

    wizard._open_existing_install.assert_called_once_with(folder.resolve())
    wizard._install.assert_not_called()


def test_installer_routes_credentials_to_existing_install(tmp_path):
    import json
    from sentra_remote import installer
    folder = tmp_path / "Commander"
    folder.mkdir()
    (folder / installer.INSTALL_MARKER).write_text(
        json.dumps({"product": "SENTRA Desktop", "version": "test"}),
        encoding="utf-8",
    )
    wizard = object.__new__(installer.InstallerWizard)
    wizard.install_dir = Mock(get=lambda: str(folder))
    wizard.tunnel_id = Mock(get=lambda: "tunnel_someidentifier123")
    wizard.runtime_key = Mock(get=lambda: "restricted-runtime-key-value")
    wizard._installed = False
    wizard._open_existing_install = Mock()
    wizard._install = Mock()

    wizard._primary_action()

    wizard._install.assert_called_once_with(require_openai=True)
    wizard._open_existing_install.assert_not_called()


def test_local_model_download_requires_consent(tmp_path, monkeypatch):
    from sentra_remote import setup_assistant as mod
    run = Mock(return_value=Mock(returncode=0, stderr="", stdout="success"))
    monkeypatch.setattr(mod, "_ollama_binary", lambda: "C:/Ollama/ollama.exe")
    monkeypatch.setattr(mod.subprocess, "run", run)
    assistant = SetupAssistant(_paths(tmp_path), ProductSettings(), Mock())

    with pytest.raises(PermissionError):
        assistant.install_local_model()
    run.assert_not_called()

    result = assistant.install_local_model(approved=True)
    assert result["ok"] is True
    assert result["model"] == mod.STARTER_LOCAL_MODEL
    command = run.call_args.args[0]
    assert command == ["C:/Ollama/ollama.exe", "pull", mod.STARTER_LOCAL_MODEL]


def test_local_model_probe_requires_model_not_just_server(tmp_path, monkeypatch):
    import io
    from sentra_remote import setup_assistant as mod
    payload = b'{"models": [{"name": "qwen2.5:0.5b-instruct-q4_K_M"}]}'
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(payload))
    result = mod.local_model_status()
    assert result["ready"] and result["starter_installed"]
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(b'{"models": []}'))
    result = mod.local_model_status()
    assert not result["ready"] and result["daemon_ready"]


def test_gateway_online_does_not_imply_ai_model_authenticated(tmp_path):
    base = {"mcp": {"ok": True}, "tunnel": {"configured": False},
            "web_models": {"ready": True, "catalog_ready": False, "turn_ready": True}}
    report = detect_capabilities(base, paths=_paths(tmp_path), settings=ProductSettings())
    models = {item["id"]: item for item in report["capabilities"]}
    assert models["codex"]["state"] == "ready"
    assert models["ai_model"]["state"] == "optional"
    base["web_models"].update({"catalog_ready": True, "turn_ready": True})
    report = detect_capabilities(base)
    models = {item["id"]: item for item in report["capabilities"]}
    assert models["ai_model"]["state"] == "ready"


def test_bundled_offline_visual_setup_guide_has_valid_media():
    from html.parser import HTMLParser
    from sentra_remote.onboarding import tutorial_video_path

    class GuideParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.videos = []
            self.inputs = []
            self.links = []
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "video":
                self.videos.append(values.get("src"))
            if tag in {"input", "form", "script"}:
                self.inputs.append(tag)
            if tag == "a":
                self.links.append(values.get("href"))

    first = tutorial_video_path(Path("nonexistent-install"), "tunnel")
    guide = first.parent / "SENTRA_SETUP_GUIDE.html"
    assert guide.is_file()
    parser = GuideParser()
    parser.feed(guide.read_text(encoding="utf-8"))
    assert set(parser.videos) == {
        "mcp-create-tunnel.mp4", "mcp-connect-connector.mp4"
    }
    assert not parser.inputs
    assert all(link.startswith("https://") for link in parser.links)
    for video in parser.videos:
        assert (guide.parent / video).is_file()


def test_tutorial_media_are_packaged_and_allowlisted(tmp_path):
    from sentra_remote.onboarding import tutorial_video_path
    for stage in ("tunnel", "connector"):
        path = tutorial_video_path(tmp_path / "install", stage)
        assert path.is_file()
        assert path.suffix == ".mp4"
    with pytest.raises(ValueError):
        tutorial_video_path(tmp_path / "install", "../../credentials")


def test_autostart_toggle_only_controls_own_launcher(tmp_path, monkeypatch):
    from sentra_remote import installer
    start = Mock()
    stop = Mock()
    monkeypatch.setattr(installer, "_register_startup", start)
    monkeypatch.setattr(installer, "_unregister_startup", stop)
    folder = tmp_path / "SENTRA"
    folder.mkdir()
    with pytest.raises(FileNotFoundError):
        installer.set_desktop_autostart(folder, enabled=True)
    start.assert_not_called()
    (folder / "sentra-desktop.exe").write_bytes(b"test")
    installer.set_desktop_autostart(folder, enabled=True)
    start.assert_called_once_with(folder.resolve())
    installer.set_desktop_autostart(folder, enabled=False)
    stop.assert_called_once()


def test_autostart_pref_roundtrip(tmp_path):
    file = tmp_path / "settings.json"
    settings = ProductSettings(autostart_desktop=False)
    settings.save(file)
    loaded = ProductSettings.load(file)
    assert loaded.autostart_desktop is False


def test_first_workspace_is_confined_and_idempotent(tmp_path):
    paths = _paths(tmp_path)
    settings = ProductSettings()
    initial = first_workspace(paths, settings)
    assert initial == tmp_path / "SENTRA Projects" / "Starter"
    assert initial.is_dir()
    assert not initial.is_relative_to(paths.state_dir)
    assert not initial.is_relative_to(paths.install_dir)
    assert settings.allowed_roots == [str(initial)]
    assert first_workspace(paths, settings) == initial
    assert settings.allowed_roots == [str(initial)]
    assert settings.workspace_permissions[str(initial)] == ["read", "write", "execute"]


def test_safe_starter_workspace_has_read_only_permissions(tmp_path):
    paths = _paths(tmp_path)
    settings = ProductSettings(profile="Safe")
    root = first_workspace(paths, settings)
    assert settings.workspace_permissions[str(root)] == ["read"]


def test_saved_web_model_selection_reaches_terminal(tmp_path, monkeypatch):
    from sentra_cli.config import CLIConfig
    monkeypatch.setenv("SENTRA_STATE_DIR", str(tmp_path / "prefs"))
    monkeypatch.delenv("SENTRA_CLI_MODEL", raising=False)
    selected = ProductSettings(web_model_name="sentra/gemini-web/gemini-2.5-pro")
    selected.save(tmp_path / "prefs" / "desktop.json")
    config = CLIConfig(workspace=tmp_path, openai_api_key="none")
    assert config.model == selected.web_model_name
    monkeypatch.setenv("SENTRA_CLI_MODEL", "sentra/chatgpt-web/custom")
    explicit = CLIConfig(workspace=tmp_path, openai_api_key="none")
    assert explicit.model == "sentra/chatgpt-web/custom"


def test_custom_workspace_requires_approval(tmp_path):
    paths = _paths(tmp_path)
    settings = ProductSettings()
    folder = tmp_path / "other-project"
    folder.mkdir()
    with pytest.raises(PermissionError):
        grant_workspace(paths, settings, folder)
    assert not settings.allowed_roots


def test_custom_workspace_uses_approved_scoped_permissions(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    settings = ProductSettings()
    folder = tmp_path / "other-project"
    folder.mkdir()
    import sentra_remote.setup_assistant as mod
    monkeypatch.setattr(mod, "sync_workspace_registry", lambda *_: None)
    monkeypatch.setattr(mod, "sync_agent_policy", lambda *_: None)
    granted = grant_workspace(paths, settings, folder, permissions=("write",), approved=True)
    assert granted == str(folder.resolve())
    assert settings.workspace_permissions[granted] == ["read", "write"]


def test_capabilities_local_ready_without_other_accounts(tmp_path):
    paths = _paths(tmp_path)
    status = {
        "mcp": {"ok": True}, "tunnel": {"configured": False, "ok": False},
        "relay": {"ok": True}, "edge": {"ok": False},
        "web_models": {"ready": False}, "sandbox": {"ok": False},
    }
    report = detect_capabilities(status, paths=paths, settings=ProductSettings())
    assert report["ready"] is True
    states = {entry["id"]: entry["state"] for entry in report["capabilities"]}
    assert states["local"] == "ready"
    assert states["chatgpt"] == "optional"
    assert states["edge"] == "optional"


def test_install_optional_needs_consent_before_invoking_installer(tmp_path, monkeypatch):
    from sentra_remote import setup_assistant as mod
    fake = Mock()
    monkeypatch.setattr(mod, "shutil", Mock(which=lambda name: None))
    import sentra_remote.installer as installer
    monkeypatch.setattr(installer, "install_winget_package", fake)
    assistant = SetupAssistant(_paths(tmp_path), ProductSettings(), Mock())
    with pytest.raises(PermissionError):
        assistant.install_optional("git")
    fake.assert_not_called()
    assistant.install_optional("git", approved=True)
    fake.assert_called_once_with("Git.Git")
    with pytest.raises(ValueError):
        assistant.install_optional("random", approved=True)


def test_local_repair_does_not_start_tunnel(tmp_path):
    paths = _paths(tmp_path)
    status = {"mcp": {"ok": True}, "relay": {"ok": True}}
    runtime = Mock()
    runtime.start_mcp.return_value = {"ok": True}
    runtime.start_relay.return_value = {"ok": True}
    runtime.status.return_value = status
    assistant = SetupAssistant(paths, ProductSettings(), runtime)
    result = assistant.start_local()
    assert result["ok"]
    runtime.start_mcp.assert_called_once()
    runtime.start_relay.assert_called_once()
    runtime.start_tunnel.assert_not_called()


def test_self_heal_local_bounded_and_no_external_tunnel(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    runtime = LocalRuntime(paths, ProductSettings())
    mcp = Mock(return_value={"ok": False, "reason": "port_in_use_by_unmanaged_process"})
    relay = Mock(return_value={"ok": True})
    monkeypatch.setattr(runtime, "start_mcp", mcp)
    monkeypatch.setattr(runtime, "start_relay", relay)
    unhealthy = {"mcp": {"ok": False}, "relay": {"ok": False}}
    assert runtime.supervise_local_once(unhealthy, now=100)["mcp"]["state"] == "GRACE"
    assert runtime.supervise_local_once(unhealthy, now=110)["mcp"]["state"] == "NEEDS_ATTENTION"
    assert mcp.call_count == 1
    assert runtime.supervise_local_once(unhealthy, now=111)["mcp"]["state"] == "BACKOFF"
    runtime.supervise_local_once(unhealthy, now=145)
    runtime.supervise_local_once(unhealthy, now=180)
    assert runtime.supervise_local_once(unhealthy, now=220)["mcp"]["state"] == "NEEDS_ATTENTION"
    assert mcp.call_count == 3
    assert runtime.supervise_local_once({"mcp": {"ok": True}, "relay": {"ok": True}}, now=221)["mcp"]["state"] == "HEALTHY"
