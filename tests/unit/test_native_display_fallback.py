"""Use the supported native renderer without hiding credential/payload failures."""
from pathlib import Path
from unittest.mock import Mock
import json,sys
import pytest
from sentra_canvas import __main__ as entry
from sentra_remote import display_probe

@pytest.mark.parametrize('requested,fallback',[('auto',True),('electron',False)])
def test_windows_launch_refusal_falls_back_only_in_auto(tmp_path,monkeypatch,requested,fallback):
    endpoint=object()
    monkeypatch.setattr('sentra_canvas.broker.connect_or_start',lambda *_,**__:endpoint)
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr('sentra_canvas.electron_host.electron_binary',lambda:Path('electron.exe'))
    error=OSError('Windows refused renderer');error.winerror=4551
    launch=Mock(side_effect=error);native=Mock()
    monkeypatch.setattr('sentra_canvas.electron_host.launch_electron',launch)
    monkeypatch.setattr('sentra_canvas.native_app.launch_native',native)
    args=['--root',str(tmp_path),'--state-dir',str(tmp_path/'state'),'--ui',requested]
    if fallback:
        assert entry.main(args)==0
        assert native.call_args.args==(endpoint,)
        assert native.call_args.kwargs['serve'] is False
        assert native.call_args.kwargs['state_dir']==tmp_path/'state'
    else:
        with pytest.raises(OSError):entry.main(args)
        native.assert_not_called()
    launch.assert_called_once()

def test_auto_does_not_hide_a_missing_broker_credential(tmp_path,monkeypatch):
    monkeypatch.setattr('sentra_canvas.broker.connect_or_start',lambda *_,**__:object())
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr('sentra_canvas.electron_host.electron_binary',lambda:Path('electron.exe'))
    monkeypatch.setattr('sentra_canvas.electron_host.launch_electron',Mock(side_effect=PermissionError('missing authenticated broker credential')))
    native=Mock();monkeypatch.setattr('sentra_canvas.native_app.launch_native',native)
    with pytest.raises(PermissionError):entry.main(['--root',str(tmp_path)])
    native.assert_not_called()

def test_integrity_verified_native_display_is_reported_separately(tmp_path,monkeypatch):
    monkeypatch.setattr('scripts.commander.stage_electron.validate_electron_payload',lambda *_: {})
    failure={'ok':False,'reason':'display_probe_failed'}
    monkeypatch.setattr(display_probe,'_run_display_probe',lambda *_,**__:failure)
    monkeypatch.setattr(display_probe,'_run_native_display_probe',lambda *_,**__:{'ok':True,'backend':'native','reason':'native_display_verified'})
    result=display_probe.probe_installed_display(tmp_path)
    assert result['ok'] and result['backend']=='native'
    assert result['external_bar_available'] is False and result['electron']==failure

@pytest.mark.parametrize('corrupt',['nonce','frozen','renderer_loaded','network_blocked','window_destroyed'])
def test_native_probe_cannot_pass_from_exit_code_alone(tmp_path,monkeypatch,corrupt):
    (tmp_path/'sentra-canvas.exe').write_bytes(b'synthetic, never executed')
    class FakeTask:
        returncode=0
        def __init__(self,args,**_):self.path=Path(args[2]);self.nonce=args[3]
        def communicate(self,**_):
            value={'schema':1,'nonce':self.nonce,'backend':'native','frozen':True,'renderer_loaded':True,
                   'node_absent':True,'network_blocked':True,'window_destroyed':True}
            value[corrupt]='stale' if corrupt=='nonce' else False
            self.path.write_text(json.dumps(value));return None,None
        def terminate_tree(self):pass
    monkeypatch.setattr('sentra_canvas.owned_process.TaskProcess',FakeTask)
    result=display_probe._run_native_display_probe(tmp_path,timeout_s=10)
    assert not result['ok']
