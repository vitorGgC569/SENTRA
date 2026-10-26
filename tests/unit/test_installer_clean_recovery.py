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
    (app / ".sentra-install.json").write_text(json.dumps({"product": "SENTRA Desktop", "installation_id": "keep-identity", "owned_files": ["sentra-canvas.exe", "_runtime_sentra-canvas/old.dll"]}))
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
def test_explicit_clean_install_refuses_unrecognized_component_collisions(tmp_path, offline, marker):
    app=tmp_path/"app";app.mkdir();(app/"sentra-canvas.exe").write_bytes(b"old")
    if marker is not None:(app/".sentra-install.json").write_text(marker)
    with pytest.raises(recovery.InstallationRecoveryError,match="unowned_clean_conflict"):
        recovery.prepare_clean_install(app,tmp_path/"state",("sentra-canvas.exe",))
    assert (app/"sentra-canvas.exe").read_bytes()==b"old"
    assert not list(tmp_path.glob('.sentra-clean-*'))


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
    (app/'.sentra-install.json').write_text(json.dumps({'product':'SENTRA Desktop','owned_files':['sentra-canvas.exe','sentra-mcp.exe']}))
    rename=Path.rename
    def fail(path,target):
        if recovery.resolved_path(path)==app/"sentra-mcp.exe":raise OSError("fixture failure")
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
        recovery.prepare_clean_install(app,state,(),incoming=['runtime/private-state/data.db'])
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


def test_clean_preserves_unowned_files_inside_owned_directories(tmp_path, offline):
    app=tmp_path/'app';app.mkdir()
    for folder in ('docs', 'runtime', 'licenses'):
        (app/folder).mkdir()
        (app/folder/'personal.txt').write_text('user data')
        (app/folder/'owned.txt').write_text('old product')
    (app/'.sentra-install.json').write_text(json.dumps({'product':'SENTRA Desktop',
        'owned_files':[f'{folder}/owned.txt' for folder in ('docs','runtime','licenses')]}))
    result=recovery.prepare_clean_install(app,tmp_path/'state',(),incoming=[f'{p}/owned.txt' for p in ('docs','runtime','licenses')])
    backup=Path(result['backup'])
    for folder in ('docs','runtime','licenses'):
        assert (app/folder/'personal.txt').read_text()=='user data'
        assert (backup/folder/'owned.txt').read_text()=='old product'
        assert not (app/folder/'owned.txt').exists()


def test_clean_conflict_fails_before_any_old_file_moves(tmp_path, offline):
    app=tmp_path/'app';(app/'docs').mkdir(parents=True)
    (app/'docs'/'START_HERE.md').write_text('personal file')
    (app/'sentra-canvas.exe').write_bytes(b'old')
    (app/'.sentra-install.json').write_text(json.dumps({'product':'SENTRA Desktop','owned_files':['sentra-canvas.exe']}))
    with pytest.raises(recovery.InstallationRecoveryError,match='unowned_clean_conflict'):
        recovery.prepare_clean_install(app,tmp_path/'state',('sentra-canvas.exe',),incoming=['sentra-canvas.exe','docs/START_HERE.md'])
    assert (app/'docs'/'START_HERE.md').read_text()=='personal file'
    assert (app/'sentra-canvas.exe').read_bytes()==b'old'
    assert not list(tmp_path.glob('.sentra-clean-*'))


def test_backup_registered_before_first_move(tmp_path, offline):
    app=tmp_path/'app';app.mkdir();old=app/'sentra-canvas.exe';old.write_bytes(b'old')
    (app/'.sentra-install.json').write_text(json.dumps({'product':'SENTRA Desktop','owned_files':[old.name]}))
    observed=[]
    def callback(value):
        observed.append(value)
        assert old.read_bytes()==b'old'
        assert json.loads((Path(value['backup'])/'clean-install.json').read_text())['schema']==2
    recovery.prepare_clean_install(app,tmp_path/'state',(old.name,),on_backup=callback)
    assert len(observed)==1


def test_failed_install_restores_missing_without_overwriting_partial_or_user_files(tmp_path,offline,monkeypatch):
    app=tmp_path/'app';app.mkdir();state=tmp_path/'state'
    (app/'sentra-canvas.exe').write_bytes(b'old canvas')
    (app/'sentra-mcp.exe').write_bytes(b'old mcp')
    (app/'.sentra-install.json').write_text(json.dumps({'product':'SENTRA Desktop','owned_files':['sentra-canvas.exe','sentra-mcp.exe']}))
    monkeypatch.setattr(installer,'check_install_payload',lambda _: {'ok':True})
    monkeypatch.setattr(installer,'prepare_tunnel_archive',lambda *_: None)
    monkeypatch.setattr('sentra_remote.openai_auto_setup.verify_credential_protection',lambda:None)
    monkeypatch.setattr(recovery,'planned_clean_targets',lambda *args,**kwargs: ['sentra-canvas.exe','sentra-mcp.exe'])
    def partial(**kwargs):
        (app/'sentra-canvas.exe').write_bytes(b'new or concurrent bytes')
        raise OSError('simulated copy failure')
    monkeypatch.setattr(installer,'_install_product',partial)
    with pytest.raises(OSError) as failure:
        installer.install(install_dir=app,state_dir=state,clean_install=True,local_only=True)
    info=failure.value._sentra_clean_install
    backup=Path(info['backup'])
    assert (backup/'sentra-canvas.exe').read_bytes()==b'old canvas'
    assert (backup/'sentra-mcp.exe').read_bytes()==b'old mcp'
    assert (app/'sentra-canvas.exe').read_bytes()==b'new or concurrent bytes'
    assert (app/'sentra-mcp.exe').read_bytes()==b'old mcp'
    assert info['recovery']['manual_recovery_required'] is True
    journal=json.loads((state/'installer-progress.json').read_text())
    assert journal['status']=='failed' and journal['clean_install']['backup']==str(backup)
    retained=list((state/'installer-clean-recoveries').glob('*.json'))
    assert len(retained)==1
    receipt=json.loads(retained[0].read_text())
    assert receipt['status']=='failed' and receipt['backup_directory']==str(backup)
    # A later installer progress update does not overwrite this independent receipt.
    (state/'installer-progress.json').write_text('{"status":"new run"}')
    assert json.loads(retained[0].read_text())['backup_directory']==str(backup)


def test_failed_install_does_not_restore_while_installation_is_active(tmp_path,offline,monkeypatch):
    app=tmp_path/'app';app.mkdir();state=tmp_path/'state'
    (app/'sentra-canvas.exe').write_bytes(b'old')
    (app/'.sentra-install.json').write_text(json.dumps({'product':'SENTRA Desktop','owned_files':['sentra-canvas.exe']}))
    offline.side_effect=[None,RuntimeError('installed process still alive')]
    monkeypatch.setattr(installer,'check_install_payload',lambda _: {'ok':True})
    monkeypatch.setattr(installer,'prepare_tunnel_archive',lambda *_: None)
    monkeypatch.setattr('sentra_remote.openai_auto_setup.verify_credential_protection',lambda:None)
    monkeypatch.setattr(recovery,'planned_clean_targets',lambda *args,**kwargs: ['sentra-canvas.exe'])
    monkeypatch.setattr(installer,'_install_product',Mock(side_effect=OSError('copy failed')))
    with pytest.raises(OSError) as failure:
        installer.install(install_dir=app,state_dir=state,clean_install=True,local_only=True)
    info=failure.value._sentra_clean_install
    assert not (app/'sentra-canvas.exe').exists()
    assert (Path(info['backup'])/'sentra-canvas.exe').read_bytes()==b'old'
    assert info['recovery']['manual_recovery_required'] is True


def test_clean_copy_refuses_race_with_unowned_file(tmp_path):
    from sentra_remote.product_copy import copy_product_file,protect_clean_targets
    source=tmp_path/'source';source.write_text('new product')
    destination=tmp_path/'target';destination.write_text('other data')
    with protect_clean_targets(), pytest.raises(FileExistsError):
        copy_product_file(source,destination,root=tmp_path)
    assert destination.read_text()=='other data'


def test_failed_worker_reports_backup_to_user(tmp_path, monkeypatch):
    def fail(**kwargs):
        error=OSError('copy failed');error._sentra_clean_install={'requested':True,'backup':str(tmp_path/'backup'),'recovery':{'manual_recovery_required':True}}
        raise error
    monkeypatch.setattr(installer,'install',fail)
    report=tmp_path/'report.json';message=tmp_path/'message.txt'
    assert installer.main(['--silent','--local-only','--state-dir',str(tmp_path/'state'),
        '--report-file',str(report),'--failure-message-file',str(message),'--setup-language','pt-BR'])==2
    assert str(tmp_path/'backup') in message.read_text(encoding='utf-8-sig')
    assert json.loads(report.read_text())['clean_install']['backup_directory']==str(tmp_path/'backup')


def test_planned_targets_include_registration_and_translate_staged_payload(tmp_path):
    import zipfile
    source=tmp_path/'payload';extension=tmp_path/'edge';docs=tmp_path/'docs'
    for root in (source,extension,docs):root.mkdir()
    (source/'sentra-canvas.exe').write_bytes(b'exe')
    (source/'prerequisites/browser-enrollment/chromium').mkdir(parents=True)
    (source/'prerequisites/browser-enrollment/chromium/manifest.json').write_text('{}')
    (source/'prerequisites/codex-registration').mkdir(parents=True)
    (source/'prerequisites/codex-registration/main.js').write_text('fixture')
    (extension/'manifest.json').write_text('{}');(docs/'START_HERE.md').write_text('guide')
    archive=tmp_path/'tunnel.zip'
    with zipfile.ZipFile(archive,'w') as out:
        out.writestr('tunnel-client.exe',b'exe');out.writestr('package/LICENSE','license')
    targets=set(recovery.planned_clean_targets(source,extension,docs,['sentra-canvas.exe'],archive))
    assert {'sentra-canvas.exe','tunnel-client.exe','edge_extension/manifest.json','docs/START_HERE.md',
        'browser-enrollment/chromium/manifest.json','runtime/codex-registration/main.js',
        'licenses/tunnel-client/LICENSE','browser-enrollment/native-config.json'} <= targets
    assert not any(name.startswith('prerequisites/') for name in targets)
    without_registration=set(recovery.planned_clean_targets(source,extension,docs,['sentra-canvas.exe'],archive,include_registration=False))
    assert 'browser-enrollment/native-config.json' not in without_registration


@pytest.mark.skipif(os.name != 'nt', reason='Win32 extended paths')
def test_clean_backup_and_restore_support_deep_owned_file(tmp_path, offline):
    from sentra_remote.windows_paths import filesystem_path
    app=tmp_path/'app';app.mkdir()
    relative=Path('web-models')/('nested-'+'a'*55)/('nested-'+'b'*55)/('nested-'+'c'*55)/('file-'+'d'*70+'.js')
    old=Path(filesystem_path(app/relative,resolve=False));old.parent.mkdir(parents=True);old.write_bytes(b'deep old bytes')
    assert len(str(app/relative))>260
    (app/'.sentra-install.json').write_text(json.dumps({'product':'SENTRA Desktop','owned_files':[relative.as_posix()]}))
    result=recovery.prepare_clean_install(app,tmp_path/'state',(),incoming=[relative.as_posix()])
    assert not old.exists()
    assert Path(filesystem_path(Path(result['backup'])/relative,resolve=False)).read_bytes()==b'deep old bytes'
    restored=recovery.restore_missing_clean_backup(app,result['backup'])
    assert restored['restored_missing']>=1 and old.read_bytes()==b'deep old bytes'


def test_restore_copy_failure_never_exposes_a_partial_original(tmp_path, offline, monkeypatch):
    app = tmp_path / 'app'
    app.mkdir()
    (app / 'sentra-canvas.exe').write_bytes(b'original executable')
    (app / '.sentra-install.json').write_text(json.dumps({
        'product': 'SENTRA Desktop', 'owned_files': ['sentra-canvas.exe'],
    }))
    result = recovery.prepare_clean_install(app, tmp_path / 'state', ('sentra-canvas.exe',))

    def interrupted_copy(source, destination):
        destination.write(source.read(3))
        raise OSError('simulated disk failure')

    monkeypatch.setattr(recovery.shutil, 'copyfileobj', interrupted_copy)
    with pytest.raises(OSError, match='simulated disk failure'):
        recovery.restore_missing_clean_backup(app, result['backup'])
    assert not (app / 'sentra-canvas.exe').exists()
    assert not list(app.glob('.sentra-restore-*.tmp'))
    assert (Path(result['backup']) / 'sentra-canvas.exe').read_bytes() == b'original executable'
