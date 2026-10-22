import base64
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from sentra_canvas.mobile_devices import DeviceRegistry
from sentra_canvas.shell_actor import _vm_input_identity
from sentra_executors.input_control import needs_input
from sentra_executors.virtualbox_vm import VirtualBoxClient
from sentra_executors.vm_atomic_input import chord_scancodes, drag_points


@pytest.mark.parametrize('action', ['input.drag', 'input.chord'])
@pytest.mark.parametrize('lost_confirmation', [False, True])
def test_atomic_gesture_releases_on_host_after_lost_confirmation(action,lost_confirmation):
    events=[]
    class Mouse:
        def PutMouseEventAbsolute(self,x,y,w,h,buttons):
            events.append(('mouse',x,y,buttons))
            if buttons and lost_confirmation:raise OSError('confirmation lost')
    class Keyboard:
        def PutScancodes(self,codes):
            events.append(('keys',codes))
            if codes==[29,46] and lost_confirmation:raise OSError('confirmation lost')
    client=VirtualBoxClient(path='fixture-only')
    @contextmanager
    def console(_):yield SimpleNamespace(Mouse=Mouse(),Keyboard=Keyboard(),Display=SimpleNamespace(GetScreenResolution=lambda _: (1280,800)))
    client.console=console
    arguments={'action':action,**({'points':[[1,2],[20,30]]} if action=='input.drag' else {'keys':[[29],[46]]})}
    if lost_confirmation:
        with pytest.raises(OSError):client.input(SimpleNamespace(vm_id='owned'),arguments)
    else:
        result=client.input(SimpleNamespace(vm_id='owned'),arguments)
        assert result.get('pointer_released') or result.get('keyboard_released')
    assert events[-1]==(('mouse',1 if lost_confirmation else 20,2 if lost_confirmation else 30,0) if action=='input.drag' else ('keys',[174,157]))
    assert needs_input(SimpleNamespace(arguments=arguments))
    assert _vm_input_identity(arguments) is not None


@pytest.mark.parametrize('arguments', [
    {'action':'input.drag','points':[[1,2]]},
    {'action':'input.drag','points':[[1,2],[True,4]]},
    {'action':'input.chord','keys':[[224,200]]},
    {'action':'input.chord','keys':[[29]],'vm_id':'foreign'},
])
def test_atomic_input_rejects_unbounded_or_foreign_targets(arguments):
    with pytest.raises(ValueError):
        (drag_points if arguments['action']=='input.drag' else chord_scancodes)(arguments)
    assert _vm_input_identity(arguments) is None


def test_rotation_recovers_same_credential_after_response_loss_and_revocation_wins(tmp_path,monkeypatch):
    monkeypatch.setattr('sentra_remote.secrets.protect_secret',lambda value:'protected:'+value)
    monkeypatch.setattr('sentra_remote.secrets.unprotect_secret',lambda value:value.removeprefix('protected:'))
    registry=DeviceRegistry(tmp_path/'devices.db','owner');offer=registry.invite();key=base64.b64encode(b'x'*32).decode()
    phone=registry.pair(offer['invite_id'],offer['invite'],key,'Phone')['device_id']
    scope={'project_id':'project','space_id':'space','dot_id':'dot','actions':['workspace_inventory']}
    registry.approve(phone,scope);original=registry.claim(phone,key)['credential']
    rotated=registry.rotate(phone,original,key,'durable-rotation-key')
    assert rotated['credential']!=original and rotated['scope']==scope
    assert registry.rotate(phone,original,key,'durable-rotation-key')==rotated
    with pytest.raises(PermissionError):registry.authenticate(phone,original,key)
    with pytest.raises(PermissionError):registry.rotate(phone,original,key,'another-rotation-key')
    with pytest.raises(PermissionError):registry.claim(phone,key)
    assert registry.authenticate(phone,rotated['credential'],key)==scope
    registry.revoke(phone)
    with pytest.raises(PermissionError):registry.rotate(phone,original,key,'durable-rotation-key')
    with pytest.raises(PermissionError):registry.authenticate(phone,rotated['credential'],key)
