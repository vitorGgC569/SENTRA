from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

from sentra_remote.desktop import _internal_deep_link_target
from sentra_remote.installer import (
    _desktop_deep_link_command,
    _enable_web_models_autostart,
    install,
)
from sentra_remote.local_runtime import LocalRuntime
from sentra_remote.product import (
    ProductPaths,
    ProductSettings,
    collect_product_status,
    tunnel_credential_storage,
)
from sentra_remote.secrets import protect_secret


def test_setup_optional_dependencies_are_lazy_by_default() -> None:
    signature = inspect.signature(install)
    assert signature.parameters["install_git"].default is False
    assert signature.parameters["install_docker"].default is False


def test_product_status_does_not_probe_optional_git_or_docker_by_default(
    tmp_path: Path,
) -> None:
    install_dir = tmp_path / "install"
    state_dir = tmp_path / "state"
    install_dir.mkdir()
    paths = ProductPaths(install_dir, state_dir)
    settings = ProductSettings(mcp_port=45401, relay_port=45402)

    status = collect_product_status(paths, settings)

    assert status["git"] == {
        "ok": None,
        "state": "not_checked",
        "lazy": True,
        "detail": "Checked only when the related feature is used.",
    }
    assert status["sandbox"] == status["git"]


def test_tunnel_credential_storage_reports_protection_without_secret(
    tmp_path: Path,
) -> None:
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    paths.state_dir.mkdir(parents=True)
    expected = "dpapi" if os.name == "nt" else "keyring"
    secret_marker = "definitely-not-a-real-secret"
    protected_value = (
        protect_secret(secret_marker)
        if os.name == "nt"
        else expected + ":" + secret_marker
    )
    paths.tunnel_config.write_text(
        json.dumps(
            {
                "tunnel_id": "tunnel_test_setup_v2",
                "runtime_key": protected_value,
            }
        ),
        encoding="utf-8",
    )

    report = tunnel_credential_storage(paths)

    assert report["ok"] is True
    assert report["scheme"] == expected
    assert report["expected_scheme"] == expected
    if os.name == "nt":
        assert report["decryptable"] is True
    assert secret_marker not in json.dumps(report)

    paths.tunnel_config.write_text(
        json.dumps(
            {
                "tunnel_id": "tunnel_test_setup_v2",
                "runtime_key": secret_marker,
            }
        ),
        encoding="utf-8",
    )
    assert tunnel_credential_storage(paths)["ok"] is False


def test_web_models_payload_enables_desktop_autostart_marker(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    state_dir = tmp_path / "state"
    launcher = install_dir / "web-models" / "win-unpacked" / "Codex Web GPT.exe"
    manifest = (
        install_dir
        / "web-models"
        / "win-unpacked"
        / "resources"
        / "runtime"
        / "manifest.json"
    )
    launcher.parent.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    launcher.write_bytes(b"MZ")
    manifest.write_text("{}", encoding="utf-8")

    report = _enable_web_models_autostart(
        ProductPaths(install_dir, state_dir),
        install_dir,
    )

    assert report["ok"] is True
    assert report["autostart"] is True
    assert (state_dir / "web-models-enabled").read_text(encoding="utf-8") == "enabled\n"


def test_internal_deep_links_are_allowlisted() -> None:
    assert _internal_deep_link_target("sentra://home") == "status"
    assert _internal_deep_link_target("sentra://status/") == "status"
    assert _internal_deep_link_target("sentra://onboarding") == "onboarding"
    assert _internal_deep_link_target("SENTRA://WEB-MODELS") == "web_models"
    assert _internal_deep_link_target("https://example.com") is None
    assert _internal_deep_link_target("sentra://../../cmd") is None


def test_protocol_command_quotes_path_and_deep_link_argument(tmp_path: Path) -> None:
    install_dir = tmp_path / "SENTRA Commander"
    command = _desktop_deep_link_command(install_dir)

    assert command == f'"{install_dir / "sentra-desktop.exe"}" --open-url "%1"'
    assert '\\"' not in command


def test_connect_verify_does_not_require_optional_browser_relay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_dir = tmp_path / "install"
    state_dir = tmp_path / "state"
    install_dir.mkdir()
    state_dir.mkdir()
    paths = ProductPaths(install_dir, state_dir)
    settings = ProductSettings(mcp_port=45401, relay_port=45402)
    runtime = LocalRuntime(paths, settings)

    monkeypatch.setattr(runtime, "start_all", lambda: {"mcp": {"ok": True}})
    monkeypatch.setattr(
        "sentra_remote.local_runtime.load_tunnel_config",
        lambda _paths: {"tunnel_id": "tunnel_test_setup_v2"},
    )
    monkeypatch.setattr(
        "sentra_remote.local_runtime.tunnel_credential_storage",
        lambda _paths: {"ok": True, "scheme": "dpapi"},
    )
    monkeypatch.setattr(
        runtime,
        "status",
        lambda: {
            "mcp": {"ok": True},
            "relay": {"ok": False},
            "tunnel": {"ok": True},
            "edge": {"ok": False},
            "web_models": {"ok": True, "autostart": True},
        },
    )

    report = runtime.connect_and_verify(timeout_s=0.1)

    assert report["core_ready"] is True
    assert report["onboarding_required"] is False
    relay = next(check for check in report["checks"] if check["id"] == "relay")
    assert relay == {"id": "relay", "required": False, "ok": False}


def test_msi_registers_sentra_protocol() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts" / "commander" / "build_msi.py").read_text(
        encoding="utf-8"
    )

    assert '"SENTRA_Protocol_Name"' in source
    assert '"SENTRA_Protocol_Flag"' in source
    assert '"SENTRA_Protocol_Command"' in source
    assert r'Software\Classes\sentra\shell\open\command' in source
    assert '--open-url "%1"' in source


def test_connect_verify_does_not_require_optional_edge_or_web_models(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    settings = ProductSettings()
    runtime = LocalRuntime(paths, settings)
    monkeypatch.setattr(runtime, "start_all", lambda: {"mcp": {"ok": True}})
    monkeypatch.setattr(
        runtime,
        "status",
        lambda: {
            "mcp": {"ok": True},
            "relay": {"ok": True},
            "tunnel": {"ok": True},
            "edge": {"ok": False},
            "web_models": {"ok": True, "autostart": False},
        },
    )
    monkeypatch.setattr(
        "sentra_remote.local_runtime.load_tunnel_config",
        lambda _paths: {"tunnel_id": "tunnel_setup_v2"},
    )
    monkeypatch.setattr(
        "sentra_remote.local_runtime.tunnel_credential_storage",
        lambda _paths: {"ok": True, "scheme": "dpapi"},
    )

    result = runtime.connect_and_verify(timeout_s=0.1)

    assert result["core_ready"] is True
    assert result["onboarding_required"] is False
    assert result["next_url"] == "sentra://home"
    checks = {item["id"]: item for item in result["checks"]}
    assert checks["edge"] == {"id": "edge", "required": False, "ok": False}
    assert checks["web_models"]["required"] is False
    assert checks["web_models"]["installed"] is True
    assert checks["web_models"]["autostart"] is False
    assert checks["web_models"]["ok"] is False


def test_connect_verify_requires_tunnel_configuration_for_completed_onboarding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    settings = ProductSettings()
    runtime = LocalRuntime(paths, settings)
    monkeypatch.setattr(runtime, "start_all", lambda: {})
    monkeypatch.setattr(
        runtime,
        "status",
        lambda: {
            "mcp": {"ok": True},
            "relay": {"ok": True},
            "tunnel": {"ok": False},
            "edge": {"ok": False},
            "web_models": {"ok": False, "autostart": False},
        },
    )
    monkeypatch.setattr(
        "sentra_remote.local_runtime.load_tunnel_config",
        lambda _paths: {},
    )
    monkeypatch.setattr(
        "sentra_remote.local_runtime.tunnel_credential_storage",
        lambda _paths: {"ok": False, "configured": False},
    )

    result = runtime.connect_and_verify(timeout_s=0.1)

    assert result["core_ready"] is True
    assert result["onboarding_required"] is False
    assert result["next_url"] == "sentra://home"


def test_connect_verify_does_not_confuse_web_models_autostart_with_readiness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    runtime = LocalRuntime(paths, ProductSettings())
    monkeypatch.setattr(runtime, "start_all", lambda: {})
    monkeypatch.setattr(
        runtime,
        "status",
        lambda: {
            "mcp": {"ok": True},
            "relay": {"ok": False},
            "tunnel": {"ok": True},
            "edge": {"ok": False},
            "web_models": {
                "ok": True,
                "installed": True,
                "autostart": True,
                "ready": False,
            },
        },
    )
    monkeypatch.setattr(
        "sentra_remote.local_runtime.load_tunnel_config",
        lambda _paths: {"tunnel_id": "tunnel_setup_v2"},
    )
    monkeypatch.setattr(
        "sentra_remote.local_runtime.tunnel_credential_storage",
        lambda _paths: {"ok": True, "scheme": "dpapi"},
    )

    result = runtime.connect_and_verify(timeout_s=0.1)

    checks = {item["id"]: item for item in result["checks"]}
    assert result["core_ready"] is True
    assert checks["web_models"]["installed"] is True
    assert checks["web_models"]["autostart"] is True
    assert checks["web_models"]["ok"] is False


def test_product_status_reports_live_web_models_gateway_readiness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_dir = tmp_path / "install"
    state_dir = tmp_path / "state"
    launcher = install_dir / "web-models" / "win-unpacked" / "Codex Web GPT.exe"
    manifest = (
        install_dir
        / "web-models"
        / "win-unpacked"
        / "resources"
        / "runtime"
        / "manifest.json"
    )
    launcher.parent.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    launcher.write_bytes(b"MZ")
    manifest.write_text("{}", encoding="utf-8")
    (state_dir / "web-models-enabled").write_text("enabled\n", encoding="utf-8")
    monkeypatch.setattr("sentra_remote.product.tcp_open", lambda *_args, **_kwargs: False)

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"service":"sentra-model-gateway","ready":true}'

    monkeypatch.setattr(
        "sentra_remote.product.urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(),
    )

    status = collect_product_status(
        ProductPaths(install_dir, state_dir),
        ProductSettings(mcp_port=45411, relay_port=45412),
    )

    assert status["web_models"]["ok"] is True
    assert status["web_models"]["ready"] is True
    assert status["web_models"]["scheduled"] is False
    assert status["web_models"]["gateway"]["reachable"] is True
