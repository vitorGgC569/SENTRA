import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from sentra_remote import installer, installer_recovery as recovery
from sentra_remote.installer_diagnostics import diagnose


@pytest.fixture
def offline(monkeypatch):
    from sentra_remote import app_exit_update
    guard = Mock()
    monkeypatch.setattr(app_exit_update, "assert_installation_offline", guard)
    return guard


def test_clean_install_preserves_data_unknown_files_identity_and_desktop_receipt(tmp_path, offline):
    app = tmp_path / "app"; app.mkdir()
    state = app / ".sentra"; state.mkdir()
    (state / "desktop.json").write_text("old settings")
    (app / "projects").mkdir(); (app / "projects/work.txt").write_text("user work")
    (app / "notes.txt").write_text("unrelated")
    (app / "desktop-launcher.json").write_text("old desktop ownership")
    (app / ".sentra-install.json").write_text(json.dumps({"product": "SENTRA Desktop", "installation_id": "keep-identity"}))
    (app / "sentra-canvas.exe").write_bytes(b"old program")
    support = app / "_runtime_sentra-canvas"; support.mkdir()
    (support / "old.dll").write_bytes(b"old support")
    result = recovery.prepare_clean_install(app, state, ("sentra-canvas.exe",))
    backup = Path(result["backup"])
    assert backup.parent == app.parent and backup.name.startswith(".sentra-clean-")
    assert (backup / "sentra-canvas.exe").read_bytes() == b"old program"
    assert (backup / "_runtime_sentra-canvas/old.dll").read_bytes() == b"old support"
    assert not (app / "sentra-canvas.exe").exists()
    assert (state / "desktop.json").read_text() == "old settings"
    assert (app / "projects/work.txt").read_text() == "user work"
    assert (app / "notes.txt").read_text() == "unrelated"
    assert (app / "desktop-launcher.json").read_text() == "old desktop ownership"
    marker = json.loads((app / ".sentra-install.json").read_text())
    assert marker["installation_id"] == "keep-identity" and marker["owned_files"] == []
    offline.assert_called_once_with(app)


@pytest.mark.parametrize("marker", [None, "{broken"])
def test_explicit_clean_install_handles_unrecognized_previous_components(tmp_path, offline, marker):
    app=tmp_path/"app";app.mkdir();(app/"sentra-canvas.exe").write_bytes(b"old")
    if marker is not None:(app/".sentra-install.json").write_text(marker)
    result=recovery.prepare_clean_install(app,tmp_path/"state",("sentra-canvas.exe",))
    assert (Path(result["backup"])/"sentra-canvas.exe").read_bytes()==b"old"
    assert json.loads((app/".sentra-install.json").read_text())["product"]=="SENTRA Desktop"


def test_clean_install_does_not_move_components_when_process_guard_refuses(tmp_path, offline):
    app=tmp_path/"app";app.mkdir();program=app/"sentra-canvas.exe";program.write_bytes(b"running")
    offline.side_effect=RuntimeError("installed process still alive")
    with pytest.raises(RuntimeError,match="still alive"):
        recovery.prepare_clean_install(app,tmp_path/"state",(program.name,))
    assert program.read_bytes()==b"running" and not list(tmp_path.glob(".sentra-clean-*"))


def test_clean_install_restores_moved_components_if_preparation_fails(tmp_path,offline,monkeypatch):
    app=tmp_path/"app";app.mkdir()
    (app/"sentra-canvas.exe").write_bytes(b"canvas")
    (app/"sentra-mcp.exe").write_bytes(b"mcp")
    rename=Path.rename
    def fail(path,target):
        if path==app/"sentra-mcp.exe":raise OSError("fixture failure")
        return rename(path,target)
    monkeypatch.setattr(Path,"rename",fail)
    with pytest.raises(OSError,match="fixture failure"):
        recovery.prepare_clean_install(app,tmp_path/"state",("sentra-canvas.exe","sentra-mcp.exe"))
    assert (app/"sentra-canvas.exe").read_bytes()==b"canvas"
    assert (app/"sentra-mcp.exe").read_bytes()==b"mcp"


def test_clean_install_rejects_git_project_and_state_root(tmp_path, offline):
    app=tmp_path/"project";app.mkdir();(app/".git").mkdir()
    with pytest.raises(recovery.InstallationRecoveryError):
        recovery.prepare_clean_install(app,tmp_path/"state",())
    with pytest.raises(recovery.InstallationRecoveryError):
        recovery.prepare_clean_install(tmp_path,tmp_path,())
    offline.assert_not_called()


@pytest.mark.parametrize("content", ["{broken", "[]", '{"mcp_port":"bad"}', '{"profile":"bad"}'])
def test_settings_reset_requires_consent_and_preserves_original(tmp_path, content):
    path=tmp_path/"desktop.json";path.write_text(content)
    with pytest.raises(recovery.InstallationRecoveryError,match="settings_invalid"):
        recovery.load_install_settings(path)
    assert path.read_text()==content
    settings,result=recovery.load_install_settings(path,repair_damaged=True)
    assert settings.profile=="Safe" and settings.access_scope=="workspace" and settings.allowed_roots==[]
    assert (tmp_path/result["backup"]).read_text()==content
    assert json.loads(path.read_text())["profile"]=="Safe"


def test_valid_settings_are_not_reset_by_clean_install_and_web_alias_is_migrated(tmp_path):
    path=tmp_path/"desktop.json"
    content=json.dumps({"profile":"Developer","access_scope":"workspace","web_model_name":"gpt-6"})
    path.write_text(content)
    settings,record=recovery.load_install_settings(path,repair_damaged=True)
    assert settings.profile=="Developer" and settings.web_model_name=="sentra/chatgpt-web/gpt-6"
    assert record is None and path.read_text()==content


def test_worker_reports_fixed_cause_without_provider_secrets(tmp_path,monkeypatch):
    def fail(**kwargs):raise recovery.InstallationRecoveryError("settings_invalid")
    monkeypatch.setattr(installer,"install",fail)
    report=tmp_path/"report.json";message=tmp_path/"message.txt"
    assert installer.main(["--silent","--local-only","--state-dir",str(tmp_path/"state"),
        "--report-file",str(report),"--failure-message-file",str(message),"--setup-language","pt-BR"])==2
    value=json.loads(report.read_text())
    assert value["diagnostic"]["reason"]=="settings_invalid"
    assert "Seguro" in message.read_text(encoding="utf-8-sig")
    assert diagnose({"message":"api_key=PRIVATE_CANARY", "provider_response":"PRIVATE_CANARY"},2)["reason"]=="installation_failed"


def test_port_conflict_is_distinct_from_login_or_display_failure():
    result={"connect_verify":{"core_ready":False,"started":{"mcp":{"reason":"port_in_use_by_different_instance"}}}}
    assert diagnose(result,2)["reason"]=="port_conflict"


def test_clean_requires_verified_payload_before_moving_old_program(tmp_path,monkeypatch):
    app=tmp_path/"app";app.mkdir();old=app/"sentra-canvas.exe";old.write_bytes(b"old")
    monkeypatch.setattr(installer,"check_install_payload",lambda _: {"ok":False,"missing":["fixture"]})
    with pytest.raises(FileNotFoundError):
        installer.install(install_dir=app,state_dir=tmp_path/"state",clean_install=True)
    assert old.read_bytes()==b"old" and not list(tmp_path.glob(".sentra-clean-*"))


def test_clean_rejects_private_state_inside_program_component(tmp_path,offline):
    app=tmp_path/"app";state=app/"runtime/private-state";state.mkdir(parents=True)
    sentinel=state/"data.db";sentinel.write_bytes(b"preserve")
    with pytest.raises(recovery.InstallationRecoveryError):
        recovery.prepare_clean_install(app,state,())
    assert sentinel.read_bytes()==b"preserve" and not list(tmp_path.glob(".sentra-clean-*"))


def test_valid_bom_settings_do_not_need_reset_and_native_model_names_stay_strict(tmp_path):
    from sentra_remote.product import ProductSettings
    path=tmp_path/"desktop.json";path.write_text('{"profile":"Safe"}',encoding="utf-8-sig")
    settings,record=recovery.load_install_settings(path)
    assert settings.profile=="Safe" and record is None
    with pytest.raises(ValueError):ProductSettings._normalize_web_model_name("gpt-6")


def test_unknown_exception_reason_cannot_leak_to_saved_diagnostic(tmp_path,monkeypatch):
    class PrivateError(RuntimeError):reason="PRIVATE_REASON_CANARY"
    monkeypatch.setattr(installer,"install",Mock(side_effect=PrivateError("failed")))
    report=tmp_path/"report.json"
    assert installer.main(["--silent","--local-only","--state-dir",str(tmp_path/"state"),"--report-file",str(report)])==2
    assert "PRIVATE_REASON_CANARY" not in report.read_text()
    assert "PRIVATE_REASON_CANARY" not in (tmp_path/"state/installer-error.json").read_text()
