from pathlib import Path
import struct, uuid
import pytest
from sentra_executors.rpa import ExecutorFailure
from sentra_executors.virtualbox_vm import VirtualBoxBinding, VirtualBoxExecutor, machine_readable
from sentra_executors.virtualbox_installation import inspect_vdi, installation_plan, configure_disk_boot, verify_guest, classify_linux_guest, debian_postinstall_template, prepare_debian_installer_templates

def vdi(path, *, allocated=False, partitioned=False):
    ident=str(uuid.uuid4()); header=bytearray(512)
    struct.pack_into('<IIII',header,64,0xBEDA107F,0x10001,400,1)
    struct.pack_into('<II',header,340,512,8192)
    struct.pack_into('<QIIII',header,368,1073741824,1048576,0,1024,int(allocated))
    header[392:408]=uuid.UUID(ident).bytes_le
    table=[0xFFFFFFFF]*1024
    if allocated:table[0]=0
    with path.open('wb') as output:
        output.write(header);output.write(struct.pack('<1024I',*table));output.truncate(8192+int(allocated)*1048576)
        if partitioned:
            mbr=bytearray(512);mbr[510:512]=b'\x55\xaa';mbr[450]=0x83
            struct.pack_into('<II',mbr,454,2048,2000000)
            output.seek(8192);output.write(mbr)
    return ident

def client(tmp_path, *, state='running', allocated=False, partitioned=False):
    folder=tmp_path/'owned';folder.mkdir();path=folder/'system.vdi'
    disk_uuid=vdi(path,allocated=allocated,partitioned=partitioned)
    cfg={'base_folder':str(tmp_path),'name':'owned','disk_gb':1,'os_family':'linux','password':'private-password','iso_path':'debian-live-13.7-amd64.iso'}
    binding=VirtualBoxBinding(str(uuid.uuid4()),'marker',lambda:cfg)
    class Client:
        calls=[]
        def status(self,b):return {'VMState':state,'CfgFile':str(folder/'owned.vbox'),'SATA-ImageUUID-0-0':disk_uuid,'GuestAdditionsRunLevel':0}
        def disk_attachments(self,b):return [{'controller':'SATA','port':0,'device':0,'disk_uuid':disk_uuid,'location':str(path),'parent_uuid':None}]
        def run(self,*args,**kwargs):self.calls.append((args,kwargs));return ''
    return Client(),binding,cfg,path,disk_uuid

def test_complete_unallocated_base_vdi_proves_empty_without_guessing_os(tmp_path):
    c,b,cfg,path,ident=client(tmp_path)
    result=installation_plan(c,b,cfg)
    assert result['disk']['empty_observed'] and result['disk']['allocated_blocks']==0
    assert result['disk']['metadata_stable'] and result['disk']['disk_uuid']==ident
    assert result['status']=='empty_virtual_disk' and not result['installed_os_verified']
    assert not result['automatic_installation_ready'] and not c.calls
    assert 'running_guest_must_not_be_formatted' in result['blockers']

def test_wrong_vdi_uuid_and_differencing_image_refused(tmp_path):
    c,b,cfg,path,ident=client(tmp_path)
    with pytest.raises(ValueError):inspect_vdi(path,expected_uuid=str(uuid.uuid4()),expected_capacity=1073741824)
    with path.open('r+b') as output:output.seek(424);output.write(uuid.uuid4().bytes)
    with pytest.raises(ValueError):inspect_vdi(path,expected_uuid=ident,expected_capacity=1073741824)

def test_multiple_disks_or_foreign_path_cannot_enter_installation_flow(tmp_path):
    c,b,cfg,path,ident=client(tmp_path)
    actual=c.disk_attachments(b)
    c.disk_attachments=lambda b:actual*2
    with pytest.raises(ExecutorFailure):installation_plan(c,b,cfg)
    c.disk_attachments=lambda b:[{**actual[0],'location':str(tmp_path/'foreign.vdi')}]
    with pytest.raises(ExecutorFailure):installation_plan(c,b,cfg)
    assert not c.calls

def test_boot_disk_requires_poweroff_partitioned_owned_medium_and_never_formats(tmp_path):
    c,b,cfg,path,ident=client(tmp_path,state='poweroff',allocated=True,partitioned=True)
    result=configure_disk_boot(c,b,cfg)
    assert c.calls[0][0]==('modifyvm',b.vm_id,'--boot1','disk','--boot2','none','--boot3','none','--boot4','none')
    assert c.calls[1][0][-2:]==('--medium','none')
    assert result['disk_uuid']==ident and not result['disk_formatted'] and not result['vm_started']
    assert not result['installed_os_verified'] and not result['desktop_ready_verified']

@pytest.mark.parametrize('state,allocated,partitioned',[('running',True,True),('poweroff',False,False),('poweroff',True,False)])
def test_boot_disk_invalid_preflight_performs_no_effect(tmp_path,state,allocated,partitioned):
    c,b,cfg,path,ident=client(tmp_path,state=state,allocated=allocated,partitioned=partitioned)
    with pytest.raises(ValueError):configure_disk_boot(c,b,cfg)
    assert not c.calls

def probe(ident, *, root='/dev/sda1',fstype='ext4',live='0',session='running'):
    return f'SENTRA_ROOT_SOURCE={root}\nSENTRA_ROOT_TYPE={fstype}\nSENTRA_ROOT_UUID=aaaa-bbbb-1234\nSENTRA_LIVE={live}\nSENTRA_VM_ID={ident}\nSENTRA_DISPLAY_MANAGER=active\nSENTRA_XFCE_SESSION={session}\n'

def test_live_overlay_and_foreign_guest_are_not_installed_or_ready():
    ident=str(uuid.uuid4())
    assert classify_linux_guest(probe(ident),expected_vm_id=ident)['desktop_ready_verified']
    for output in [probe(ident,root='overlay',fstype='overlay',live='1'),probe(str(uuid.uuid4())),probe(ident,root='/dev/sdb1')]:
        result=classify_linux_guest(output,expected_vm_id=ident)
        assert not result['installed_os_verified'] and not result['desktop_ready_verified']
    with pytest.raises(ValueError):classify_linux_guest(probe(ident)+'SENTRA_LIVE=0\n',expected_vm_id=ident)
    with pytest.raises(ValueError):classify_linux_guest('SENTRA_VM_ID='+ident,expected_vm_id=ident)

def test_fixed_guest_probe_uses_configured_credentials_via_stdin(tmp_path):
    c,b,cfg,path,ident=client(tmp_path,allocated=True,partitioned=True)
    def run(*args,**kwargs):c.calls.append((args,kwargs));return probe(b.vm_id)
    c.run=run
    value=verify_guest(c,b,cfg)
    assert value['installed_os_verified'] and value['disk_uuid']==ident
    args,options=c.calls[0]
    assert args[:3]==('guestcontrol',b.vm_id,'run') and '--passwordfile' in args
    assert cfg['password'] not in str(args) and options['password']==cfg['password']
    executor=VirtualBoxExecutor(machine_id='m',owner_principal_id='a',bindings={'vm:guest':b},client=c)
    with pytest.raises(ValueError):executor._validate(type('Request',(),{'capability_id':'vm:guest','arguments':{'action':'installation.verify','command':'echo fake'}})(),b)

def test_template_is_guest_only_does_not_format_and_preserves_kernel_boot_options():
    ident=str(uuid.uuid4())
    script=debian_postinstall_template(ident,kernel_parameters='tsc=unstable clocksource=acpi_pm nohz=off maxcpus=1')
    assert ident in script and '/etc/lightdm/lightdm.conf.d' in script
    assert 'update-grub' in script and 'autologin-user=sentra' in script
    assert all(command not in script for command in ('mkfs','sfdisk','parted','/dev/sdb','password'))
    with pytest.raises(ValueError):debian_postinstall_template(ident,kernel_parameters='arbitrary; command')

def test_virtualbox_quoted_medium_keys_are_parsed():
    assert machine_readable('"SATA-ImageUUID-0-0"="owned-medium"\n')['SATA-ImageUUID-0-0']=='owned-medium'

def test_empty_vdi_cannot_be_certified_installed_even_if_guest_could_report_other_root(tmp_path):
    c,b,cfg,path,ident=client(tmp_path)
    result=verify_guest(c,b,cfg)
    assert not result['installed_os_verified'] and not c.calls

def test_installer_templates_prepare_only_exact_empty_poweroff_guest_without_secret(tmp_path):
    c,b,cfg,path,ident=client(tmp_path,state='poweroff')
    plan=installation_plan(c,b,cfg)
    prepared=prepare_debian_installer_templates(plan)
    assert prepared['vm_id']==b.vm_id and prepared['disk_uuid']==ident
    assert 'xfce-desktop' in prepared['preseed_template']
    assert '@@VBOX_INSERT_USER_PASSWORD_SHACRYPT512@@' in prepared['preseed_template']
    assert cfg['password'] not in str(prepared)
    assert not c.calls and not prepared['physical_effects_performed']
    assert not prepared['automatic_installation_ready']
    with pytest.raises(ValueError):prepare_debian_installer_templates({**plan,'vm_state':'running'})
    with pytest.raises(ValueError):prepare_debian_installer_templates({**plan,'os_family':'windows'})
