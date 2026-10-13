"""Read-only VM diagnostics must stay inside the owned registered directory."""
from pathlib import Path
import pytest
from sentra_executors.virtualbox_vm import VirtualBoxBinding, VirtualBoxClient, VirtualBoxExecutor

def test_owned_log_identifies_hyperv_without_asserting_live_os_is_installed(tmp_path, monkeypatch):
    folder = tmp_path / 'owned-vm'
    (folder / 'Logs').mkdir(parents=True)
    (folder / 'Logs/VBox.log').write_text('HM: HMR3Init: Attempting fall back to NEM: AMD-V is not available\nNEM: WHvCapabilityCodeHypervisorPresent is TRUE\n')
    client = VirtualBoxClient('owned.exe')
    monkeypatch.setattr(client, 'status', lambda _: {'CfgFile':str(folder / 'owned.vbox'), 'VMState':'running', 'GuestAdditionsRunLevel':0, 'graphicscontroller':'vmsvga'})
    result = client.diagnostics(VirtualBoxBinding('owned', 'owned-marker', None),
        {'base_folder':str(tmp_path), 'name':'owned-vm', 'iso_path':'debian-live-amd64.iso'})
    assert result['execution_backend'] == 'hyperv_nem' and result['hardware_virtualization_fallback']
    assert not result['installed_os_verified'] and not result['guest_command_channel_ready']
    assert not result['desktop_ready_verified'] and not result['automatic_reboot']
    assert str(tmp_path) not in str(result)

def test_foreign_vm_log_path_is_not_read(tmp_path, monkeypatch):
    own = tmp_path / 'owned-vm'
    other = tmp_path / 'foreign-vm'
    (own / 'Logs').mkdir(parents=True)
    (own / 'Logs/VBox.log').write_text('WHvCapabilityCodeHypervisorPresent is TRUE')
    client = VirtualBoxClient('owned.exe')
    monkeypatch.setattr(client, 'status', lambda _: {'CfgFile':str(other / 'foreign.vbox'), 'VMState':'running'})
    result = client.diagnostics(VirtualBoxBinding('owned', 'owned-marker', None),
        {'base_folder':str(tmp_path), 'name':'owned-vm'})
    assert result['execution_backend'] == 'unknown' and not result['log_identity_verified']

def test_restart_resets_only_existing_running_owned_vm():
    calls = []
    class Client:
        def status(self, binding):
            assert binding.vm_id == 'owned-vm' and binding.marker == 'owned-marker'
            calls.append('identity_checked')
            return {'VMState':'running'}
        def run(self, *args):
            calls.append(args)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a',
        bindings={'vm:manage':None}, client=Client())
    result = executor._execute(VirtualBoxBinding('owned-vm','owned-marker',lambda:{}), {'action':'restart'})
    assert calls == ['identity_checked', ('controlvm','owned-vm','reset'), 'identity_checked']
    assert result['requested_action'] == 'restart' and result['os_ready_verified'] is False

def test_restart_refuses_powered_off_vm_before_any_effect():
    class Client:
        def status(self, binding): return {'VMState':'poweroff'}
        def run(self, *args): raise AssertionError('must not start or recreate VM')
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage':None}, client=Client())
    with pytest.raises(ValueError, match='running'):
        executor._execute(VirtualBoxBinding('owned','marker',lambda:{}), {'action':'restart'})

def _menu_image(editor=False):
    import base64,io
    from PIL import Image,ImageDraw
    picture=Image.new('RGB',(640,480),(38,71,91));draw=ImageDraw.Draw(picture)
    if editor:
        draw.rectangle((8,443,13,451),fill=(15,228,231))
        draw.rectangle((30,443,220,448),fill=(230,230,230))
    else:draw.rectangle((96,248,577,263),fill=(116,155,191))
    content=io.BytesIO();picture.save(content,format='PNG')
    return base64.b64encode(content.getvalue()).decode()

def test_debian_nem_boot_uses_confirmed_editor_bounded_keys_and_one_enter(monkeypatch):
    events=[]
    class Client:
        def frame(self,binding):
            return {'image_base64':_menu_image(editor=bool(events))}
        def diagnostics(self,binding,cfg):return {'execution_backend':'hyperv_nem'}
        def input(self,binding,args):events.append(args['scancodes'])
    monkeypatch.setattr('sentra_executors.virtualbox_vm.effect_checkpoint',lambda:None)
    cfg={'os_family':'linux','iso_path':'debian-live-13.7.0-amd64-xfce.iso','name':'owned','base_folder':'owned'}
    executor=VirtualBoxExecutor(machine_id='m',owner_principal_id='a',bindings={'vm:manage':None},client=Client())
    result=executor._advance_debian_live(VirtualBoxBinding('vm','marker',lambda:cfg),cfg,attempts=1)
    assert events[0]==[15,143] and events[-1]==[28,156]
    assert sum(batch==[28,156] for batch in events)==1 and all(len(batch)<=32 for batch in events)
    assert result['boot_compatibility']=='debian_hyperv_nem' and not result['desktop_ready_verified']
    assert result['kernel_parameters']=='tsc=unstable clocksource=acpi_pm nohz=off maxcpus=1'

def test_boot_editor_must_be_confirmed_before_any_parameters_or_enter(monkeypatch):
    events=[]
    class Client:
        def frame(self,binding):return {'image_base64':_menu_image()}
        def diagnostics(self,binding,cfg):return {'execution_backend':'hyperv_nem'}
        def input(self,binding,args):events.append(args['scancodes'])
    monkeypatch.setattr('sentra_executors.virtualbox_vm.effect_checkpoint',lambda:None)
    cfg={'os_family':'linux','iso_path':'debian-live-13.7.0-amd64-xfce.iso','name':'owned','base_folder':'owned'}
    executor=VirtualBoxExecutor(machine_id='m',owner_principal_id='a',bindings={'vm:manage':None},client=Client())
    result=executor._advance_debian_live(VirtualBoxBinding('vm','marker',lambda:cfg),cfg,attempts=1)
    assert events==[[15,143]] and result['live_boot']=='editor_not_confirmed'
    assert result['automatic_retry'] is False

def test_start_bootstrap_survives_existing_vm_projection_status(monkeypatch):
    calls=[]
    class Client:
        def status(self,binding):return {'VMState':'running'}
        def run(self,*args):calls.append(args)
    executor=VirtualBoxExecutor(machine_id='m',owner_principal_id='a',bindings={'vm:manage':None},client=Client())
    cfg={'provisioning_status':'existing_vm'}
    monkeypatch.setattr(executor,'_advance_debian_live',lambda binding,value: {'live_boot':'selection_sent'})
    result=executor._execute(VirtualBoxBinding('owned','marker',lambda:cfg),{'action':'start'})
    assert calls==[('startvm','owned','--type','headless')]
    assert result['live_boot']=='selection_sent' and not result['os_ready_verified']
