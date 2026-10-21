"""Automatic installation must be complete, offline-capable and honest on failure."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import urllib.error

import pytest

from sentra_remote import installer
from sentra_remote.installer_preflight import inspect_payload, write_payload_manifest


@pytest.fixture
def payload(tmp_path, monkeypatch):
    source, extension, docs = [tmp_path / name for name in ("payload", "edge_extension", "docs")]
    paths = [source / "sentra-canvas.exe", source / "sentra-cli.exe",
             source / "web-models/win-unpacked/Codex Web GPT.exe",
             source / "web-models/win-unpacked/resources/runtime/manifest.json",
             source / "web-models/integration-build.json",
             source / "web-models/licenses/codex-chatgpt-web/LICENSE",
             source / "sentra-electron/electron.exe", source / "runtime-components.json",
             source / "prerequisites/tunnel-client.zip", extension / "manifest.json",
             docs / "START_HERE.md", docs / "SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test fixture - not a runnable release")
    from sentra_remote import codex_registration_runtime as registration
    fixture_files = {name: hashlib.sha256(("fixture-" + name).encode()).hexdigest()
                     for name in registration.FILES}
    monkeypatch.setattr(registration, "FILES", fixture_files)
    registration_dir = source / "prerequisites/codex-registration"
    registration_dir.mkdir()
    for name in fixture_files:
        (registration_dir / name).write_bytes(("fixture-" + name).encode())
    (registration_dir / "provenance.json").write_text(json.dumps(registration.provenance()))
    products = ("sentra-canvas.exe", "sentra-cli.exe")
    from sentra_remote.enrollment_extension import stage_extensions
    stage_extensions(Path(installer.__file__).parent / "enrollment_extension", source / "prerequisites/browser-enrollment")
    write_payload_manifest(source, extension, docs, "1.0.0", products)
    return source, extension, docs, products


def test_complete_manifest_verifies_without_client_python(payload):
    result = inspect_payload(*payload, version="1.0.0", require_manifest=True)
    assert result["ok"] and result["verified"]
    assert result["python_required_on_client"] is False


def test_rehashed_manifest_cannot_approve_changed_codex_registration(payload):
    source, extension, docs, products = payload
    (source / "prerequisites/codex-registration/codex.exe").write_bytes(b"changed CLI")
    write_payload_manifest(source, extension, docs, "1.0.0", products)
    with pytest.raises(ValueError, match="checksum"):
        inspect_payload(*payload, version="1.0.0", require_manifest=True)


def test_rehashed_manifest_cannot_approve_changed_firefox_signed_bridge(payload):
    source, extension, docs, products = payload
    (source / "prerequisites/browser-enrollment/firefox-signed.xpi").write_bytes(b"changed XPI")
    write_payload_manifest(source, extension, docs, "1.0.0", products)
    with pytest.raises(ValueError, match="checksum"):
        inspect_payload(*payload, version="1.0.0", require_manifest=True)


@pytest.mark.parametrize("change", ["tamper", "missing", "extra", "version"])
def test_manifest_rejects_mixed_or_incomplete_release(payload, change):
    source = payload[0]
    version = "1.0.0"
    if change == "tamper":
        (source / "sentra-cli.exe").write_bytes(b"different executable")
    elif change == "missing":
        (source / "sentra-canvas.exe").unlink()
    elif change == "extra":
        (source / "web-models/injected.js").write_bytes(b"unexpected")
    else:
        version = "2.0.0"
    with pytest.raises(ValueError, match="manifest|checksum"):
        inspect_payload(*payload, version=version, require_manifest=True)


def test_build_leftovers_do_not_enter_setup_manifest(payload):
    source = payload[0]
    (source / "SENTRA-Setup.exe").write_bytes(b"old setup")
    (source / "web-models.staging-other").mkdir()
    (source / "web-models.staging-other/private.txt").write_text("not shipped")
    assert inspect_payload(*payload, version="1.0.0", require_manifest=True)["ok"]


def test_missing_payload_does_not_stop_or_overwrite_install(tmp_path, monkeypatch):
    target = tmp_path / "installed"
    target.mkdir()
    installer._write_install_marker(target, ["sentra-canvas.exe"])
    (target / "sentra-canvas.exe").write_bytes(b"previous version")
    before = (target / installer.INSTALL_MARKER).read_bytes()
    monkeypatch.setattr(installer, "check_install_payload", lambda _: {"ok": False, "missing": ["sentra-cli.exe"]})
    stop, copy, download = Mock(), Mock(), Mock()
    monkeypatch.setattr(installer, "_stop_installed_processes", stop)
    monkeypatch.setattr(installer, "_copy_product_files", copy)
    monkeypatch.setattr(installer, "prepare_tunnel_archive", download)
    with pytest.raises(FileNotFoundError, match="sentra-cli.exe"):
        installer.install(install_dir=target, state_dir=tmp_path / "state")
    stop.assert_not_called(); copy.assert_not_called(); download.assert_not_called()
    assert (target / installer.INSTALL_MARKER).read_bytes() == before
    assert (target / "sentra-canvas.exe").read_bytes() == b"previous version"


def test_bundled_dependency_works_without_network(tmp_path, monkeypatch):
    archive = tmp_path / "payload/prerequisites/tunnel-client.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"verified archive fixture")
    monkeypatch.setattr(installer, "TUNNEL_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    monkeypatch.setattr(installer, "payload_root", lambda: tmp_path / "payload")
    network = Mock(side_effect=AssertionError("offline"))
    monkeypatch.setattr(installer.urllib.request, "urlopen", network)
    assert installer.prepare_tunnel_archive(tmp_path / "cache") == archive
    network.assert_not_called()


def test_bad_dependency_never_reaches_install(tmp_path, monkeypatch):
    archive = tmp_path / "wrong.zip"
    archive.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="SHA-256"):
        installer.prepare_tunnel_archive(tmp_path / "cache", archive)


def test_download_retries_transport_and_reuses_verified_cache(tmp_path, monkeypatch):
    import io
    raw = b"downloaded fixture"
    monkeypatch.setattr(installer, "payload_root", lambda: tmp_path / "absent")
    monkeypatch.setattr(installer, "TUNNEL_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(installer.time, "sleep", lambda _: None)
    network = Mock(side_effect=[urllib.error.URLError("offline"), io.BytesIO(raw)])
    monkeypatch.setattr(installer.urllib.request, "urlopen", network)
    target = installer.prepare_tunnel_archive(tmp_path / "cache")
    assert target.read_bytes() == raw and network.call_count == 2
    assert installer.prepare_tunnel_archive(tmp_path / "cache") == target
    assert network.call_count == 2 and not list(target.parent.glob("*.part"))


@pytest.mark.parametrize("ready", [False, True])
def test_install_journal_tracks_verified_readiness_without_secrets(tmp_path, monkeypatch, ready):
    from sentra_remote import openai_auto_setup
    monkeypatch.setattr(openai_auto_setup, "verify_credential_protection", lambda: None)
    monkeypatch.setattr(installer, "check_install_payload", lambda _: {"ok": True})
    monkeypatch.setattr(installer, "prepare_tunnel_archive", lambda *_: tmp_path / "archive")
    monkeypatch.setattr(installer, "_install_product", lambda **_: {
        "connect_verify": {"core_ready": ready, "onboarding_required": not ready,
                           "chatgpt_onboarding": {"ready": ready},
                           "status": {"mcp": {"ok": ready}, "tunnel": {"ok": ready}, "web_models": {key: ready for key in ("payload_complete", "ready", "catalog_ready", "turn_ready")}}}})
    state = tmp_path / "state"
    installer.install(install_dir=tmp_path / "install", state_dir=state, runtime_key="never-log-this")
    raw = (state / "installer-progress.json").read_text(encoding="utf-8")
    assert "never-log-this" not in raw
    assert json.loads(raw)["status"] == ("account_authorization_pending" if ready else "needs_attention")


def test_check_is_read_only_and_does_not_launch_installer(monkeypatch):
    monkeypatch.setattr(installer, "check_install_payload", lambda _: {"ok": True})
    start = Mock(side_effect=AssertionError("should not install"))
    monkeypatch.setattr(installer, "install", start)
    assert installer.main(["--check"]) == 0
    start.assert_not_called()


def test_windowed_check_writes_a_report_without_a_console(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "check_install_payload", lambda _: {"ok": True, "verified": True})
    monkeypatch.setattr(installer.sys, "stdout", None)
    report = tmp_path / "evidence/check.json"
    assert installer.main(["--check", "--report-file", str(report)]) == 0
    data = json.loads(report.read_text())
    assert data["operation"] == "check" and data["payload_verified"]
    assert not data["ready"] and not data["homologated"]


@pytest.mark.parametrize("ready", [False, True])
def test_silent_report_records_health_but_never_provider_secrets(tmp_path, monkeypatch, ready):
    verification = {
        "core_ready": ready, "chatgpt_onboarding": {"ready": ready},
        "web_models_required": True,
        "status": {"mcp": {"ok": ready}, "tunnel": {"ok": ready, "api_key": "private-key"},
                   "web_models": {k: ready for k in ("payload_complete", "ready", "catalog_ready", "turn_ready")}},
    }
    monkeypatch.setattr(installer, "install", lambda **_: {
        "connect_verify": verification, "runtime_key": "private-key", "preflight": {"ok": True, "verified": True}})
    report = tmp_path / "install.json"
    assert installer.main(["--silent", "--report-file", str(report)]) == (0 if ready else 2)
    raw = report.read_text()
    assert "private-key" not in raw
    data = json.loads(raw)
    assert data["ready"] == ready
    assert data["checks"]["mcp"] == ready
    assert not data["account_authorization_verified"] and not data["homologated"]


def test_failed_install_report_cannot_pass_qa(tmp_path, monkeypatch):
    def fail(**_):
        raise OSError("api_key=private-key")
    monkeypatch.setattr(installer, "install", fail)
    report = tmp_path / "failure.json"
    assert installer.main(["--silent", "--state-dir", str(tmp_path / "state"),
                           "--report-file", str(report)]) == 2
    raw = report.read_text()
    assert "private-key" not in raw
    data = json.loads(raw)
    assert data["exit_code"] == 2 and not data["ready"]
    assert data["failure"] == {"error_type": "OSError", "stage": "install"}


@pytest.mark.parametrize("kind,expected,stage", [
    ("TimeoutExpired", "TimeoutExpired", "install"),
    ("ShortcutRegistrationError", "ShortcutRegistrationError", "windows_shortcuts"),
    ("CredentialProtectionUnavailable", "CredentialProtectionUnavailable", "credential_protection"),
    ("PRIVATE_CLASS_CANARY", "installation_error", "install"),
])
def test_setup_failure_report_identifies_safe_category_without_command_or_provider_data(tmp_path,kind,expected,stage):
    report=tmp_path/"failure.json"
    installer._write_setup_report(report,"install",{
        "error_type":kind,"message":"PRIVATE_MESSAGE_CANARY",
        "command":["PRIVATE_COMMAND_CANARY"],"provider_response":{"api_key":"PRIVATE_KEY_CANARY"},
    },2)
    raw=report.read_text()
    assert "CANARY" not in raw
    data=json.loads(raw)
    assert data["failure"]=={"error_type":expected,"stage":stage}
    assert data["ready"] is False and data["local_ready"] is False


def test_unwritable_report_does_not_return_success(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "check_install_payload", lambda _: {"ok": True, "verified": True})
    assert installer.main(["--check", "--report-file", str(tmp_path)]) == 2


@pytest.mark.parametrize("ready", [False, True])
def test_retry_verifies_without_reinstalling_or_stopping_sessions(tmp_path, monkeypatch, ready):
    target = tmp_path / "Commander"
    target.mkdir()
    installer._write_install_marker(target)
    runtime = Mock()
    runtime.connect_and_verify.return_value = {"core_ready": ready, "chatgpt_onboarding": {"ready": ready},
                                              "status": {"mcp": {"ok": ready}, "tunnel": {"ok": ready}, "web_models": {key: ready for key in ("payload_complete", "ready", "catalog_ready", "turn_ready")}}}
    monkeypatch.setattr(installer, "configure_codex", lambda *_, **__: {"ready": True})
    monkeypatch.setattr(installer, "LocalRuntime", Mock(return_value=runtime))
    monkeypatch.setattr("sentra_remote.display_probe.probe_installed_display", lambda *_: {"ok": True})
    copy = Mock(side_effect=AssertionError("retry must not recopy binaries"))
    monkeypatch.setattr(installer, "_copy_product_files", copy)
    launch = Mock()
    monkeypatch.setattr(installer.subprocess, "Popen", launch)
    result = installer.verify_installed_local(install_dir=target)
    assert result["reused_install"]
    runtime.stop_all.assert_not_called()
    copy.assert_not_called()
    assert launch.call_count == int(ready)
    if ready:
        assert launch.call_args.args[0] == [str(target / "sentra-canvas.exe")]


@pytest.mark.parametrize("verification,extra,exit_code", [
    ({"core_ready": True}, [], 2),
    ({"core_ready": True, "chatgpt_onboarding": {"ready": True},
      "status": {"mcp": {"ok": True}, "tunnel": {"ok": True}}}, [], 0),
    ({"core_ready": True, "onboarding_required": True}, [], 2),
    ({"core_ready": True}, ["--tunnel-id", "synthetic"], 2),
    ({"deferred": "post_update_restart"}, [], 2),
    ({"deferred": "post_update_restart"}, ["--offline-handoff", "test-handoff"], 0),
])
def test_unattended_exit_code_reflects_verification(monkeypatch, verification, extra, exit_code):
    monkeypatch.setattr(installer, "install", lambda **_: {"connect_verify": verification})
    assert installer.main(["--silent", *extra]) == exit_code


@pytest.mark.parametrize("frozen,requested,expected", [
    (True, "auto", "electron"), (False, "auto", "native"), (True, "native", "native"),
])
def test_installed_app_uses_bundled_renderer(monkeypatch, tmp_path, frozen, requested, expected):
    import sys
    from sentra_canvas import __main__ as canvas, broker, electron_host, native_app
    endpoint = object()
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(broker, "connect_or_start", Mock(return_value=endpoint))
    monkeypatch.setattr(electron_host, "electron_binary", lambda: Path("bundled/electron.exe"))
    electron, native = Mock(return_value=0), Mock()
    monkeypatch.setattr(electron_host, "launch_electron", electron)
    monkeypatch.setattr(native_app, "launch_native", native)
    assert canvas.main(["--root", str(tmp_path), "--ui", requested]) == 0
    assert electron.call_count == int(expected == "electron")
    assert native.call_count == int(expected == "native")


def test_double_click_uses_starter_workspace_outside_installation(tmp_path, monkeypatch):
    import sys
    from sentra_canvas import __main__ as canvas, broker, electron_host
    from sentra_remote.product import ProductPaths
    install = tmp_path / "SENTRA/Commander"
    state = tmp_path / "SENTRA/state"
    paths = ProductPaths(install, state)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(ProductPaths, "default", classmethod(lambda cls, *_: paths))
    connect = Mock(return_value=object())
    monkeypatch.setattr(broker, "connect_or_start", connect)
    monkeypatch.setattr(electron_host, "electron_binary", lambda: Path("bundled/electron.exe"))
    monkeypatch.setattr(electron_host, "launch_electron", Mock(return_value=0))
    assert canvas.main([]) == 0
    workspace = connect.call_args.args[0]
    assert workspace.is_dir()
    assert not workspace.is_relative_to(install)
    assert not workspace.is_relative_to(state)
    assert workspace.name == "Starter"
