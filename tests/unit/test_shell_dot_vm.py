"""Resource reservations, real central grants and VirtualBox command construction."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import uuid
import pytest
from test_shell_dot_features import shell, dot
from sentra_canvas.shell_dot_vm import VmStore, DotVmServices, host_resources, _memavailable_bytes
from sentra_canvas.store import Denied
from sentra_executors.virtualbox_vm import VirtualBoxBinding, VirtualBoxClient, VirtualBoxExecutor
from sentra_runtime.contracts import OperationRequest

LIMITS = {'logical_cpus': 12, 'physical_memory_mb': 32768, 'available_memory_mb': 32768,
    'max_cpus': 6, 'max_memory_mb': 16384,
    'resource_fraction': 0.5, 'limit_kind': 'configured_vcpu_and_ram'}


@pytest.fixture
def vm_scope(shell, monkeypatch):
    monkeypatch.setattr('sentra_canvas.shell_dot_vm.host_resources', lambda: dict(LIMITS))
    # This fixture simulates the provider's commands, so its availability must
    # also be simulated; it must not depend on a host VirtualBox installation.
    monkeypatch.setattr('sentra_executors.virtualbox_vm.executable',lambda:'fixture-VBoxManage')
    monkeypatch.setattr(VirtualBoxClient, 'run', lambda self, *args, **kwargs: '')
    app, server, scope, call = shell
    root, other = dot(call, 'VM owner'), dot(call, 'Other VM')
    ca, cb = call('conversation_create', dot_id=root['dot_id']), call('conversation_create', dot_id=other['dot_id'])
    service = DotVmServices(app)
    params = {**scope, 'dot_id': root['dot_id'], 'conversation_id': ca['conversation_id']}
    params.pop('project_id')
    yield app, scope['project_id'], call, service, params, root, other, ca, cb


def configure(service, pid, params, **changes):
    return service.dispatch(pid, 'dot_vm_configure', {**params, 'os_family': 'linux', 'cpus': 2,
        'memory_mb': 4096, 'disk_gb': 64, 'iso_path': '', **changes}, uuid.uuid4().hex)


def test_vm_status_fields_do_not_include_the_guest_password():
    from sentra_canvas.shell_dot_vm import _public_vm_fields, _status_installation
    secret = 'dot-registry-secret-value'
    record = {
        'vm_id': 'owned-guest-vm',
        'password': secret,
        'guest_password': secret,
        'username': 'sentra',
        'marker': 'SENTRA-DOT:owned',
        'last_project_import': {'guest_path': '/home/sentra/Imports/one', 'note': 'path ' + secret},
        'installation_verification': {'status': 'installed_guest_verified', 'detail': secret},
    }
    public = _public_vm_fields(record)
    installation = _status_installation(record)
    assert 'password' not in public
    assert 'guest_password' not in public
    assert 'marker' not in public
    assert secret not in str(public)
    assert public['username'] == 'sentra'
    assert public['last_project_import']['guest_path'] == '/home/sentra/Imports/one'
    assert installation['status'] == 'installed_guest_verified'
    assert secret not in str(installation)


def test_reservation_aggregate_atomic_scope_and_encrypted_password(vm_scope):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    value = configure(service, pid, params)
    assert value['vm']['vm_state'] == 'not_created' and value['image_required']
    assert value['host']['reserved_cpus'] == 2
    assert 'password' not in value['vm'] and 'marker' not in value['vm']
    other_params = {**params, 'dot_id': other['dot_id'], 'conversation_id': cb['conversation_id']}
    configure(service, pid, other_params, cpus=4, memory_mb=12288)
    assert service.store.budget()['reserved_cpus'] == 6
    assert service.store.budget()['reserved_memory_mb'] == 16384
    with pytest.raises(ValueError, match='50%'):
        configure(service, pid, params, cpus=3)
    assert service.store.get(pid, root['dot_id'])['cpus'] == 2
    with pytest.raises(Denied):
        service.dispatch(pid, 'dot_vm_status', {**params, 'conversation_id': cb['conversation_id']})
    saved = service.store.get(pid, root['dot_id'])
    with app._shell_service().store.connect('shell') as db:
        raw = db.execute('SELECT body FROM shell_dot_vms WHERE root=?', (root['dot_id'],)).fetchone()['body']
    assert saved['password'] not in raw
    assert saved['username'] == 'sentra'


def test_same_configuration_key_is_durable_and_no_image_creates_no_vm(vm_scope):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    fields = {**params, 'os_family':'windows', 'cpus':2, 'memory_mb':4096, 'disk_gb':64, 'iso_path':''}
    key = uuid.uuid4().hex
    first = service.dispatch(pid, 'dot_vm_configure', fields, key)
    second = service.dispatch(pid, 'dot_vm_configure', fields, key)
    assert first == second
    result = service.dispatch(pid, 'dot_vm_execute', {**params, 'arguments':{'action':'provision'}}, uuid.uuid4().hex)
    assert result['state'] == 'SUCCEEDED' and result['evidence']['status'] == 'pending_image'
    assert result['evidence']['created'] is False
    with pytest.raises(ValueError):
        configure(service, pid, params, os_family='windows', disk_gb=16)


def test_configure_keeps_the_requested_dot_account(vm_scope):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    del app, call, other, ca, cb
    configure(service, pid, params, username='dotuser')
    assert service.store.get(pid, root['dot_id'])['username'] == 'dotuser'
    with pytest.raises(ValueError, match='guest account'):
        configure(service, pid, params, username='../sentra')


def test_vm_grants_are_independent_of_host_profile_and_human_takeover_fences_effects(vm_scope):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    record = service.store.get(pid, root['dot_id'])
    factory = service.host._factories[record['machine_id']]
    def probe(cap, args):
        return OperationRequest('vm-test-' + uuid.uuid4().hex, root['agent_id'], record['machine_id'], cap,
            record['work_item_id'], uuid.uuid4().hex, args)
    request = probe('vm:manage', {'action':'provision'})
    assert factory.policy(request).allowed is True
    initial = service.host.input_status(workspace_id=pid, machine_id=record['machine_id'])
    handoff = service.dispatch(pid, 'dot_vm_handoff', {**params, 'holder':'human', 'expected_epoch':initial['epoch']}, uuid.uuid4().hex)
    assert handoff['input']['holder'] == 'human' and handoff['input']['live']
    assert factory.policy(request).allowed is False
    assert factory.policy(probe('vm:guest', {'action':'guest.run','command':'echo ok'})).allowed is False
    assert factory.policy(probe('vm:input', {'action':'input.key','scancodes':[28,156]})).allowed is False
    handoff = service.dispatch(pid, 'dot_vm_handoff', {**params, 'holder':'agent','expected_epoch':handoff['input']['epoch']}, uuid.uuid4().hex)
    assert handoff['input']['holder'] == 'agent'
    assert factory.policy(request).allowed is True
    call('access_set', conversation_id=ca['conversation_id'], mode='ask')
    assert factory.policy(request).allowed is True
    assert factory.policy(probe('vm:observe', {'action':'status'})).allowed is True
    control, owner = app._shell_service(), app._runtime().owner
    for grant in control.authorization.list_grants(owner, principal_type='agent', principal_id=root['agent_id'])['items']:
        if grant['scope_id'] == record['work_item_id'] and grant['capability'] == 'vm:manage':
            control.authorization.revoke(grant['grant_id'], owner)
    assert factory.policy(request).allowed is False


def test_executor_uses_real_argv_stdin_credentials_and_detected_os(tmp_path):
    image = tmp_path / 'install image.iso'; image.write_bytes(b'local image fixture')
    cfg = {'iso_path':str(image), 'iso_sha256':hashlib.sha256(image.read_bytes()).hexdigest(), 'os_family':'windows',
        'name':'SENTRA-Dot-fixture', 'base_folder':str(tmp_path / 'owned'), 'cpus':2, 'memory_mb':4096,
        'disk_gb':64, 'password':'test-private-password'}
    ident = str(uuid.uuid4()); marker = 'SENTRA-DOT:' + ident
    calls = []
    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        output = ''
        if argv[1:3] == ['unattended','detect']:
            output = 'detectedOSTypeId="Windows11_64"\nisUnattendedInstallSupported=true\n'
        if argv[1] == 'showvminfo':
            output = 'UUID="' + ident + '"\ndescription="' + marker + '"\nVMState="running"\n'
        return SimpleNamespace(returncode=0, stdout=output, stderr='')
    client = VirtualBoxClient('owned-VBoxManage.exe', runner)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage':None}, client=client)
    result = executor._execute(VirtualBoxBinding(ident, marker, lambda:cfg), {'action':'provision'})
    assert result['status'] == 'installation_started' and result['os_ready_verified'] is False
    assert any(argv[1] == 'createvm' and ident in argv for argv, _ in calls)
    assert any(argv[1] == 'modifyvm' and '--cpus' in argv and '2' in argv for argv, _ in calls)
    install = next((argv, options) for argv, options in calls if argv[1:3] == ['unattended','install'])
    assert '--user-password-file' in install[0] and 'stdin' in install[0]
    assert install[0][install[0].index('--user') + 1] == 'sentra'
    assert cfg['password'] not in str(install[0]) and install[1]['input'] == cfg['password'] + '\n'
    assert all('shell' not in options for _, options in calls)


def test_unattended_install_uses_the_dot_account(tmp_path):
    image = tmp_path / 'install.iso'
    image.write_bytes(b'local image fixture')
    cfg = {'iso_path': str(image), 'iso_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
        'os_family': 'linux', 'name': 'SENTRA-Dot-fixture', 'base_folder': str(tmp_path / 'owned'),
        'cpus': 1, 'memory_mb': 2048, 'disk_gb': 16, 'password': 'test-private-password',
        'username': 'dotuser'}
    ident = str(uuid.uuid4())
    marker = 'SENTRA-DOT:' + ident
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        output = ''
        if argv[1:3] == ['unattended', 'detect']:
            output = 'detectedOSTypeId="Debian_64"\nisUnattendedInstallSupported=true\n'
        if argv[1] == 'showvminfo':
            output = 'UUID="' + ident + '"\ndescription="' + marker + '"\nVMState="poweroff"\n'
        return SimpleNamespace(returncode=0, stdout=output, stderr='')

    client = VirtualBoxClient('owned-VBoxManage.exe', runner)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage': None}, client=client)
    executor._execute(VirtualBoxBinding(ident, marker, lambda: cfg), {'action': 'provision'})
    install = next(argv for argv in calls if argv[1:3] == ['unattended', 'install'])
    assert install[install.index('--user') + 1] == 'dotuser'


def test_frame_reads_vm_console_and_input_cannot_target_host_or_foreign_uuid():
    events = []
    image = b'\x89PNG\r\n\x1a\n' + b'frame fixture'
    class Display:
        def GetScreenResolution(self, screen):
            return (1280, 800, 32, 0, 0, 1)
        def TakeScreenShotToArray(self, *args):
            events.append(('frame', args)); return image
    console = SimpleNamespace(Display=Display(), Keyboard=SimpleNamespace(PutScancodes=lambda scans:events.append(('keys',scans))),
        Mouse=SimpleNamespace(PutMouseEventAbsolute=lambda *args:events.append(('mouse',args))))
    class Client(VirtualBoxClient):
        @contextmanager
        def console(self, binding):
            assert binding.vm_id == 'own-vm'; yield console
    client = Client('owned.exe')
    binding = VirtualBoxBinding('own-vm','marker',lambda:{})
    frame = client.frame(binding)
    assert frame['transport'] == 'virtualbox-com-framebuffer' and frame['source_width'] == 1280
    client.input(binding, {'action':'input.key','scancodes':[30,158]})
    client.input(binding, {'action':'input.mouse','x':100,'y':200,'buttons':1})
    assert events[-1] == ('mouse',(100,200,0,0,1))
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:input':binding}, client=client)
    request = SimpleNamespace(capability_id='vm:input', arguments={'action':'input.mouse','x':1,'y':1,'buttons':0,'vm_id':'other-vm'})
    with pytest.raises(ValueError):
        executor._validate(request, binding)


def test_root_and_child_have_independent_vm_identity_and_conversation_grants(vm_scope):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    child = dot(call, 'Child VM', canvas_root_dot_id=root['dot_id'])
    cc = call('conversation_create', dot_id=child['dot_id'])
    child_params = {**params, 'dot_id':child['dot_id'], 'conversation_id':cc['conversation_id']}
    own = configure(service, pid, params)
    descendant = configure(service, pid, child_params)
    assert own['vm']['vm_id'] != descendant['vm']['vm_id']
    assert own['vm']['machine_id'] != descendant['vm']['machine_id']
    assert service.store.budget()['reserved_cpus'] == 4
    with pytest.raises(Denied):
        service.dispatch(pid, 'dot_vm_status', {**child_params, 'conversation_id':ca['conversation_id']})
    assert service.dispatch(pid, 'dot_vm_status', child_params)['vm']['vm_id'] == descendant['vm']['vm_id']


def test_virtualbox_72_partial_detect_boots_iso_without_false_unattended_claim(tmp_path, monkeypatch):
    iso = tmp_path / 'debian-live-amd64.iso'
    iso.write_bytes(b'iso fixture')
    ident = str(uuid.uuid4())
    marker = 'SENTRA-DOT:' + ident
    cfg = {'iso_path':str(iso), 'iso_sha256':hashlib.sha256(iso.read_bytes()).hexdigest(),
        'os_family':'linux', 'name':'SENTRA-Dot-fixture',
        'base_folder':str(tmp_path / 'owned'), 'cpus':2, 'memory_mb':4096,
        'disk_gb':32, 'password':'secret-only-in-memory'}
    commands=[]
    def runner(argv, **kw):
        commands.append(argv)
        if argv[1:3] == ['unattended','detect']:
            return SimpleNamespace(returncode=1,
                stdout='OSTypeId="Debian"\nIsInstallSupported="on"\n',
                stderr='VBoxManage.exe: error: Code E_NOTIMPL (0x80004001)')
        if argv[1] == 'showvminfo':
            return SimpleNamespace(returncode=0,
                stdout='UUID="' + ident + '"\ndescription="' + marker + '"\nVMState="running"\n', stderr='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    client=VirtualBoxClient('owned-VBoxManage.exe',runner)
    executor=VirtualBoxExecutor(machine_id='m',owner_principal_id='a',bindings={'vm:manage':None},client=client)
    selected=[]
    monkeypatch.setattr(client,'frame',lambda binding:{'image_base64':_debian_live_menu_fixture()})
    monkeypatch.setattr(client,'input',lambda binding,args:selected.append(args))
    result=executor._execute(VirtualBoxBinding(ident,marker,lambda:cfg),{'action':'provision'})
    assert result['live_boot']=='selection_sent'
    assert selected == [{'action':'input.key','scancodes':[28,156]}]
    assert result['status'] == 'installer_boot_started'
    assert result['installation_mode'] == 'manual_iso_boot'
    assert result['os_ready_verified'] is False
    assert any(cmd[1] == 'startvm' for cmd in commands)
    create = next(cmd for cmd in commands if cmd[1] == 'createvm')
    assert '--ostype' in create and create[create.index('--ostype') + 1] == 'Debian_64'
    assert '--os-type' not in create
    assert not any(cmd[1:3] == ['unattended','install'] for cmd in commands)


def test_execute_refuses_a_path_vm_id_before_the_hypervisor():
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            calls.append(parts)
            return ''

        def status(self, binding):
            raise AssertionError('hypervisor status ran')

    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:observe': None}, client=Client())
    with pytest.raises(ValueError, match='hypervisor token'):
        executor._execute(VirtualBoxBinding('../other', 'marker', lambda: {}), {'action': 'status'})
    assert calls == []


def test_status_matches_a_braced_uuid_and_rejects_another_machine(tmp_path):
    from sentra_executors.rpa import ExecutorFailure
    ident = str(uuid.uuid4())
    marker = 'SENTRA-DOT:' + ident

    def same(argv, **kw):
        assert argv[2] == ident
        return SimpleNamespace(returncode=0, stdout='UUID="{' + ident.upper() + '}"\ndescription="' + marker + '"\nVMState="poweroff"\n', stderr='')

    info = VirtualBoxClient('owned-VBoxManage.exe', same).status(VirtualBoxBinding(ident, marker, lambda: {}))
    assert info['VMState'] == 'poweroff'

    def other(argv, **kw):
        return SimpleNamespace(returncode=0, stdout='UUID="{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}"\ndescription="' + marker + '"\nVMState="poweroff"\n', stderr='')

    with pytest.raises(ExecutorFailure, match='identity_changed'):
        VirtualBoxClient('owned-VBoxManage.exe', other).status(VirtualBoxBinding(ident, marker, lambda: {}))
    calls = []

    def record(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    with pytest.raises(ExecutorFailure, match='identity_changed'):
        VirtualBoxClient('owned-VBoxManage.exe', record).status(VirtualBoxBinding('../other', marker, lambda: {}))
    assert calls == []


def test_provision_refuses_a_path_vm_name_before_create(tmp_path):
    iso = tmp_path / 'debian-live-amd64.iso'
    iso.write_bytes(b'iso fixture')
    ident = str(uuid.uuid4())
    cfg = {'iso_path': str(iso), 'iso_sha256': hashlib.sha256(iso.read_bytes()).hexdigest(),
        'os_family': 'linux', 'name': '../outside',
        'base_folder': str(tmp_path / 'owned'), 'cpus': 2, 'memory_mb': 2048,
        'disk_gb': 32, 'password': 'secret-only-in-memory', 'username': 'sentra'}
    commands = []

    def runner(argv, **kw):
        commands.append(argv)
        if argv[1:3] == ['unattended', 'detect']:
            return SimpleNamespace(returncode=0, stdout='OSTypeId="Debian_64"\nIsInstallSupported="on"\n', stderr='')
        if argv[1:3] == ['list', 'vms']:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    client = VirtualBoxClient('owned-VBoxManage.exe', runner)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage': None}, client=client)
    with pytest.raises(ValueError, match='hypervisor token'):
        executor._provision(VirtualBoxBinding(ident, 'SENTRA-DOT:' + ident, lambda: cfg), cfg)
    assert not any(cmd[1] == 'createvm' for cmd in commands)
    cfg['name'] = 'SENTRA-Dot-linux'
    cfg['base_folder'] = 'owned'
    commands.clear()
    with pytest.raises(ValueError, match='host path'):
        executor._provision(VirtualBoxBinding(ident, 'SENTRA-DOT:' + ident, lambda: cfg), cfg)
    assert not any(cmd[1] == 'createvm' for cmd in commands)
    cfg['base_folder'] = str(tmp_path / 'owned')
    commands.clear()
    with pytest.raises(ValueError, match='vm marker'):
        executor._provision(VirtualBoxBinding(ident, 'SENTRA-DOT\nUUID="other"', lambda: cfg), cfg)
    assert not any(cmd[1] == 'createvm' for cmd in commands)


def test_provision_does_not_treat_a_longer_name_as_this_vm(tmp_path):
    iso = tmp_path / 'debian-live-amd64.iso'
    iso.write_bytes(b'iso fixture')
    ident = str(uuid.uuid4())
    marker = 'SENTRA-DOT:' + ident
    cfg = {'iso_path': str(iso), 'iso_sha256': hashlib.sha256(iso.read_bytes()).hexdigest(),
        'os_family': 'linux', 'name': 'SENTRA-Dot-linux',
        'base_folder': str(tmp_path / 'owned'), 'cpus': 2, 'memory_mb': 2048,
        'disk_gb': 32, 'password': 'secret-only-in-memory', 'username': 'sentra'}
    commands = []

    def runner(argv, **kw):
        commands.append(argv)
        if argv[1:3] == ['unattended', 'detect']:
            return SimpleNamespace(returncode=0, stdout='OSTypeId="Debian_64"\nIsInstallSupported="on"\n', stderr='')
        if argv[1:3] == ['list', 'vms']:
            return SimpleNamespace(returncode=0,
                stdout='"SENTRA-Dot-' + ident + '-child" {other-uuid}\n', stderr='')
        if argv[1] == 'showvminfo':
            return SimpleNamespace(returncode=0,
                stdout='UUID="' + ident + '"\ndescription="' + marker + '"\nVMState="poweroff"\n', stderr='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    client = VirtualBoxClient('owned-VBoxManage.exe', runner)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage': None}, client=client)
    result = executor._provision(VirtualBoxBinding(ident, marker, lambda: cfg), cfg)
    assert result.get('status') != 'existing_vm'
    assert any(cmd[1] == 'createvm' and ident in cmd for cmd in commands)

    commands.clear()

    def listed(argv, **kw):
        commands.append(argv)
        if argv[1:3] == ['unattended', 'detect']:
            return SimpleNamespace(returncode=0, stdout='OSTypeId="Debian_64"\nIsInstallSupported="on"\n', stderr='')
        if argv[1:3] == ['list', 'vms']:
            return SimpleNamespace(returncode=0, stdout='"Dot" {' + ident + '}\n', stderr='')
        if argv[1] == 'showvminfo':
            return SimpleNamespace(returncode=0,
                stdout='UUID="' + ident + '"\ndescription="' + marker + '"\nVMState="poweroff"\n', stderr='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    client = VirtualBoxClient('owned-VBoxManage.exe', listed)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage': None}, client=client)
    found = executor._provision(VirtualBoxBinding(ident, marker, lambda: cfg), cfg)
    assert found['status'] == 'existing_vm'
    assert found['automatic_retry'] is False
    assert not any(cmd[1] == 'createvm' for cmd in commands)


def test_vm_list_matches_the_uuid_and_not_a_longer_name():
    from sentra_canvas.shell_dot_vm import _vm_is_listed
    ident = "owned-guest-vm"
    listing = '"owned-guest-vm-child" {other-uuid}\n"Dot" {owned-guest-vm}\n'
    assert _vm_is_listed(listing, ident) is True
    assert _vm_is_listed('"owned-guest-vm-child" {aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}', ident) is False
    assert _vm_is_listed(listing, "../owned-guest-vm") is False
    assert _vm_is_listed(None, ident) is False


def test_windows10_partial_detect_uses_unattended_install(tmp_path):
    iso = tmp_path / 'Windows.iso'
    iso.write_bytes(b'iso fixture')
    ident = str(uuid.uuid4())
    marker = 'SENTRA-DOT:' + ident
    cfg = {'iso_path': str(iso), 'iso_sha256': hashlib.sha256(iso.read_bytes()).hexdigest(),
        'os_family': 'windows', 'name': 'SENTRA-Dot-windows',
        'base_folder': str(tmp_path / 'owned'), 'cpus': 2, 'memory_mb': 4096,
        'disk_gb': 64, 'password': 'secret-only-in-memory'}
    commands = []

    def runner(argv, **kw):
        commands.append(argv)
        if argv[1:3] == ['unattended', 'detect']:
            return SimpleNamespace(returncode=1,
                stdout='OSTypeId="Windows10_64"\nOSVersion="2004"\nIsInstallSupported="on"\n',
                stderr='VBoxManage.exe: error: Code E_NOTIMPL (0x80004001)')
        if argv[1] == 'showvminfo':
            return SimpleNamespace(returncode=0,
                stdout='UUID="' + ident + '"\ndescription="' + marker + '"\nVMState="running"\n', stderr='')
        if argv[1:3] == ['list', 'vms']:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    client = VirtualBoxClient('owned-VBoxManage.exe', runner)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage': None}, client=client)
    result = executor._execute(VirtualBoxBinding(ident, marker, lambda: cfg), {'action': 'provision'})
    assert result['installation_mode'] == 'unattended'
    assert result['detected_os_type'] == 'Windows10_64'
    assert result['unattended_supported'] is True
    assert result['windows_usable'] is False
    assert result['activation_claimed'] is False
    assert any(cmd[1:3] == ['unattended', 'install'] for cmd in commands)
    assert not any(cmd[1] == 'startvm' for cmd in commands)


def test_iso_selector_uses_trusted_installation_root_not_only_workspace(vm_scope):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    directory = app.project_dir / 'Isos'
    directory.mkdir(exist_ok=True)
    image = directory / 'debian-test.iso'
    with image.open('wb') as output:
        output.truncate(128 * 1024 * 1024)
    choices = service.dispatch(pid, 'dot_vm_images', params)['items']
    assert any(row['name'] == 'debian-test.iso' and row['path'] == str(image.resolve())
        for row in choices)
    assert all(row['path'].endswith('.iso') for row in choices)

def test_uncertain_provision_is_durable_and_never_treated_as_ready(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    monkeypatch.setattr(service.host, 'dispatch',
        lambda **fields: {'state':'UNCERTAIN', 'operation_id':fields['operation_id'],
                           'error':'physical_effect_error_requires_reconciliation'})
    result = service.dispatch(pid, 'dot_vm_execute',
        {**params, 'arguments':{'action':'provision'}}, uuid.uuid4().hex)
    assert result['state'] == 'UNCERTAIN'
    assert service.store.get(pid, root['dot_id'])['provisioning_status'] == 'uncertain_requires_reconciliation'
    assert service.store.budget()['reserved_cpus'] == 2

def test_persisted_dot_vm_rebinds_canonical_machine_when_computer_opens(vm_scope):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    configured = configure(service, pid, params)
    mid = configured['vm']['machine_id']
    service.host._inventory.pop(mid, None)
    service.host._factories.pop(mid, None)
    assert mid not in service.host._inventory
    after = service.dispatch(pid, 'dot_vm_status', params)
    assert after['vm']['machine_id'] == mid
    assert mid in service.host._inventory and mid in service.host._factories
    assert after['vm']['conversation_authorized'] is True


def test_dot_actor_can_observe_and_input_only_its_own_vm_workitem(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    app._shell_service()
    actor=app._shell_runtime.actors
    app._shell_dot_vm=service
    stored=service.store.get(pid, root['dot_id'])
    message={'project_id':pid,'space_id':params['space_id'],
        'conversation_id':ca['conversation_id'],'operation_id':'op-real-qa'}
    submitted=[]
    monkeypatch.setattr(service.host,'dispatch',
        lambda **kwargs: submitted.append(kwargs) or {'state':'SUCCEEDED','evidence':{'input_sent':True}})
    actor._vm_action('inactive',{'action':'vm_input','request_key':'stable-original',
        'value':'{"action":"input.key","scancodes":[28,156]}'},message,root)
    assert submitted[-1]['work_item_id'] == stored['work_items'][ca['conversation_id']]
    assert submitted[-1]['machine_id'] == stored['machine_id']
    assert submitted[-1]['capability_id'] == 'vm:input'
    first_operation = submitted[-1]['operation_id']
    actor._vm_action('inactive',{'action':'vm_input','request_key':'stable-original',
        'value':'{"action":"input.key","scancodes":[28,156]}'},message,root)
    assert submitted[-1]['operation_id'] == first_operation
    actor._vm_action('inactive',{'action':'vm_frame'},message,root)
    assert submitted[-1]['capability_id'] == 'vm:observe'
    assert submitted[-1]['arguments'] == {'action':'frame'}
    with pytest.raises(Denied):
        actor._vm_action('inactive',{'action':'vm_input','request_key':'other',
            'value':'{"action":"input.key","scancodes":[28,156]}'},
            {**message,'conversation_id':cb['conversation_id']},root)
    call('access_set', conversation_id=ca['conversation_id'], mode='ask')
    actor._vm_action('inactive',{'action':'vm_input','request_key':'another',
        'value':'{"action":"input.key","scancodes":[28,156]}'},message,root)
    assert submitted[-1]['work_item_id'] == stored['work_items'][ca['conversation_id']]


def test_uncertain_vm_key_is_not_sent_again(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    actor = app._shell_runtime.actors
    app._shell_dot_vm = service
    message = {'project_id': pid, 'space_id': params['space_id'],
        'conversation_id': ca['conversation_id'], 'operation_id': 'op-uncertain-input'}
    sent = []

    def dispatch(**kwargs):
        sent.append(kwargs['arguments'])
        return {'state': 'UNCERTAIN', 'operation_id': kwargs['operation_id']}

    monkeypatch.setattr(service.host, 'dispatch', dispatch)
    payload = {'action': 'vm_input', 'request_key': 'uncertain-key-1',
        'value': '{"action":"input.key","scancodes":[28,156]}'}
    first = actor._vm_action('inactive', payload, message, root)
    assert first['state'] == 'UNCERTAIN' and first['automatic_resend'] is False
    assert sent == [{'action': 'input.key', 'scancodes': [28, 156]}]
    second = actor._vm_action('inactive', {**payload, 'request_key': 'uncertain-key-2'}, message, root)
    assert second['state'] == 'UNCERTAIN' and second['dispatched'] is False
    assert second['automatic_resend'] is False
    assert sent == [{'action': 'input.key', 'scancodes': [28, 156]}]


def _debian_live_menu_fixture(*, selected=True):
    """Small deterministic image exercising the Debian-selected-menu guard."""
    import base64
    import io
    from PIL import Image, ImageDraw
    picture = Image.new('RGB', (640,480), (38,71,91))
    if selected:
        ImageDraw.Draw(picture).rectangle((96,248,577,263), fill=(116,155,191))
    content = io.BytesIO()
    picture.save(content, format='PNG')
    return base64.b64encode(content.getvalue()).decode('ascii')


def test_debian_live_boot_menu_guard_refuses_unrelated_screens():
    encoded = _debian_live_menu_fixture()
    assert VirtualBoxExecutor._debian_live_boot_menu(encoded)
    assert not VirtualBoxExecutor._debian_live_boot_menu(_debian_live_menu_fixture(selected=False))
    assert not VirtualBoxExecutor._debian_live_boot_menu('not-an-image')


def test_debian_live_autoboot_sends_one_enter_only_after_verified_menu(monkeypatch, tmp_path):
    cfg={'os_family':'linux', 'iso_path':str(tmp_path/'debian-live-13.7.0-amd64-xfce.iso')}
    calls=[]
    menu=_debian_live_menu_fixture()
    class Client:
        def frame(self,binding):
            calls.append('observe')
            return {'image_base64':menu}
        def input(self,binding,args):
            calls.append(('input',args))
    executor = VirtualBoxExecutor(machine_id='m',owner_principal_id='a',
        bindings={'vm:manage':None},client=Client())
    monkeypatch.setattr('sentra_executors.virtualbox_vm.effect_checkpoint',lambda:None)
    binding=VirtualBoxBinding('owned','SENTRA-DOT:owned',lambda:cfg)
    result=executor._advance_debian_live(binding,cfg,attempts=1)
    assert result['live_boot']=='selection_sent'
    assert calls == ['observe',('input',{'action':'input.key','scancodes':[28,156]})]
    calls.clear()
    result=executor._advance_debian_live(binding,{**cfg,'os_family':'windows'},attempts=1)
    assert result['live_boot']=='not_applicable' and not calls
    calls.clear()
    executor.client.frame=lambda _:{'image_base64':_debian_live_menu_fixture(selected=False)}
    result=executor._advance_debian_live(binding,cfg,attempts=1)
    assert result['live_boot']=='menu_not_confirmed' and not calls


def test_authorized_human_takeover_can_type_without_weakening_agent_fence(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    original=service.store.get(pid,root['dot_id'])
    factory=service.host._factories[original['machine_id']]
    adapter=factory._declarations[original['machine_id']].adapter
    keys=[]
    monkeypatch.setattr(adapter.client,'status',lambda binding:{'VMState':'running'})
    monkeypatch.setattr(adapter.client,'input',lambda binding,args:keys.append(args) or {
        'input_sent':True,'vm_id':binding.vm_id,'action':args['action']})
    before=service.status(pid,root['dot_id'],ca['conversation_id'])['input']
    handoff=service.dispatch(pid,'dot_vm_handoff',{**params,
        'holder':'human','expected_epoch':before['epoch']},uuid.uuid4().hex)
    assert handoff['input']['holder']=='human' and handoff['input']['live']
    request=OperationRequest('qa-agent-input-denied',root['agent_id'],original['machine_id'],
        'vm:input',original['work_item_id'],'qa-denied',{'action':'input.key','scancodes':[28,156]})
    assert factory.policy(request).allowed is False
    receipt=service.dispatch(pid,'dot_vm_input',{**params,
        'arguments':{'action':'input.key','scancodes':[28,156]},
        'expected_epoch':handoff['input']['epoch']},uuid.uuid4().hex)
    assert receipt['state']=='SUCCEEDED' and keys==[{'action':'input.key','scancodes':[28,156]}]


def test_product_vm_input_does_not_repeat_an_uncertain_key(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    del app, other, cb
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    sent = []

    def dispatch_human(**kwargs):
        sent.append(kwargs['arguments'])
        return {'state': 'UNCERTAIN', 'operation_id': kwargs['operation_id']}

    monkeypatch.setattr(service.host, 'dispatch_human', dispatch_human)
    arguments = {'action': 'input.key', 'scancodes': [28, 156]}
    first = service.dispatch(pid, 'dot_vm_input', {**params, 'arguments': arguments}, 'uncertain-vm-input-1')
    assert first['state'] == 'UNCERTAIN' and first['automatic_resend'] is False
    assert sent == [arguments]
    second = service.dispatch(pid, 'dot_vm_input', {**params, 'arguments': arguments}, 'uncertain-vm-input-2')
    assert second['state'] == 'UNCERTAIN' and second['dispatched'] is False
    assert second['automatic_resend'] is False
    assert sent == [arguments]


def test_unfenced_vm_click_is_not_sent(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    del app, root, other, cb
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    sent = []
    monkeypatch.setattr(service.host, 'dispatch_human', lambda **kwargs: sent.append(kwargs) or {'state': 'SUCCEEDED'})
    result = service.dispatch(pid, 'dot_vm_input', {**params, 'arguments': {
        'action': 'input.mouse', 'x': 1.5, 'y': 2, 'buttons': 1,
    }}, 'unfenced-vm-click')
    assert result['state'] == 'BLOCKED'
    assert result['dispatched'] is False
    assert result['automatic_resend'] is False
    assert sent == []


def test_dot_create_on_already_registered_vm_reuses_same_machine_without_provision(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    app._shell_service()
    app._shell_dot_vm=service
    actor=app._shell_runtime.actors
    calls=[]
    actual=service.status(pid,root['dot_id'],ca['conversation_id'])
    actual['vm']['vm_state']='running'
    def guarded_dispatch(pid_value,action,fields,key=None):
        calls.append(action)
        if action!='dot_vm_status':raise AssertionError('registered VM must not be recreated')
        return actual
    monkeypatch.setattr(service,'dispatch',guarded_dispatch)
    message={'project_id':pid,'space_id':params['space_id'],
        'conversation_id':ca['conversation_id'],'operation_id':'qa-already-existing'}
    result=actor._vm_action('inactive',{'action':'vm_create','request_key':'qa-already-existing-123',
        'value':json.dumps({'os_family':'linux','cpus':2,'memory_mb':4096,'disk_gb':64,
            'iso_path':'fake.iso'})},message,root)
    assert result['status']=='existing_vm' and result['new_vm_created'] is False
    assert result['next_step']=='vm_frame or vm_input'
    assert calls == ['dot_vm_status']

def test_same_dot_new_conversation_reuses_os_with_independent_authority(vm_scope):
    app,pid,call,service,params,root,other,ca,cb=vm_scope
    call('access_set',conversation_id=ca['conversation_id'],mode='full')
    first=configure(service,pid,params)['vm']
    second_convo=call('conversation_create',dot_id=root['dot_id'])
    second_params={**params,'conversation_id':second_convo['conversation_id']}
    before=service.dispatch(pid,'dot_vm_status',second_params)['vm']
    assert before['vm_id']==first['vm_id'] and not before['conversation_authorized']
    with pytest.raises(Denied):
        service.dispatch(pid,'dot_vm_execute',{**second_params,'arguments':{'action':'provision'}},uuid.uuid4().hex)
    second=configure(service,pid,second_params)['vm']
    assert second['vm_id']==first['vm_id'] and second['machine_id']==first['machine_id']
    assert second['work_item_id']!=first['work_item_id']
    record=service.store.get(pid,root['dot_id'])
    assert record['work_items'][ca['conversation_id']]==first['work_item_id']
    assert record['work_items'][second_convo['conversation_id']]==second['work_item_id']
    request=OperationRequest('qa-new-conversation',root['agent_id'],second['machine_id'],
        'vm:manage',second['work_item_id'],'qa-new-conversation',{'action':'provision'})
    factory=service.host._factories[second['machine_id']]
    assert factory.policy(request).allowed
    call('access_set',conversation_id=second_convo['conversation_id'],mode='full')
    assert factory.policy(request).allowed
    call('access_set',conversation_id=ca['conversation_id'],mode='ask')
    assert factory.policy(request).allowed

def test_vm_record_patch_merges_conversation_bindings_atomically(vm_scope):
    app,pid,call,service,params,root,other,ca,cb=vm_scope
    configure(service,pid,params)
    service.store.patch(pid,root['dot_id'],work_items={'second':'wi-second'})
    service.store.patch(pid,root['dot_id'],work_items={'third':'wi-third'})
    value=service.store.get(pid,root['dot_id'])
    assert ca['conversation_id'] in value['work_items']
    assert value['work_items']['second']=='wi-second' and value['work_items']['third']=='wi-third'

def test_power_action_cannot_store_a_path_as_provisioning_status():
    from sentra_canvas.shell_dot_vm import project_vm_execution
    started = project_vm_execution(
        {'provisioning_status': 'pending_image'},
        {'action': 'provision'},
        {'state': 'SUCCEEDED', 'evidence': {'status': 'installation_started'}},
    )
    assert started['provisioning_status'] == 'installation_started'
    powered = project_vm_execution(
        {'provisioning_status': 'pending_image'},
        {'action': 'start'},
        {'state': 'SUCCEEDED', 'evidence': {'status': 'running', 'vm_state': 'running'}},
    )
    assert 'provisioning_status' not in powered
    advanced = project_vm_execution(
        {'provisioning_status': 'pending_image'},
        {'action': 'installation.advance'},
        {'state': 'SUCCEEDED', 'evidence': {
            'status': '/etc/passwd', 'physical_effects_performed': True}},
    )
    assert 'provisioning_status' not in advanced
    assert advanced['installation_advance']['status'] is None
    assert advanced['installation_advance']['physical_effects_performed'] is True
    stepped = project_vm_execution(
        {'provisioning_status': 'pending_image'},
        {'action': 'installation.advance'},
        {'state': 'SUCCEEDED', 'evidence': {
            'status': 'prior_attempt_not_replayed',
            'next_authorized_step': {'action': '/bin/sh'},
        }},
    )
    assert stepped['installation_advance']['status'] == 'prior_attempt_not_replayed'
    assert stepped['installation_advance']['next_action'] is None
    kept_step = project_vm_execution(
        {},
        {'action': 'installation.advance'},
        {'state': 'SUCCEEDED', 'evidence': {
            'next_authorized_step': {'action': 'installation.verify'},
        }},
    )
    assert kept_step['installation_advance']['next_action'] == 'installation.verify'
    string_step = project_vm_execution({}, {'action': 'installation.advance'}, {
        'state': 'SUCCEEDED', 'evidence': {'next_authorized_step': 'installation.verify'},
    })
    assert string_step['installation_advance']['next_action'] is None
    usable = project_vm_execution({}, {'action': 'installation.advance'}, {
        'state': 'SUCCEEDED',
        'evidence': {'windows_usable': True, 'desktop_ready_verified': True},
    })
    assert usable['installation_advance']['windows_usable'] is False
    assert usable['installation_advance']['desktop_ready_verified'] is False
    assert usable['installation_advance']['installed_os_verified'] is False


def test_import_and_verify_do_not_replace_provisioning_status():
    from sentra_canvas.shell_dot_vm import project_vm_execution
    imported = project_vm_execution(
        {'provisioning_status': 'pending_image'},
        {'action': 'project.import'},
        {'state': 'SUCCEEDED', 'evidence': {
            'status': 'project_imported', 'receipt_state': 'SUCCEEDED',
            'guest_path': '/home/sentra/Imports/one/project'}},
    )
    assert 'provisioning_status' not in imported
    assert imported['last_project_import']['guest_path'] == '/home/sentra/Imports/one/project'
    verified = project_vm_execution(
        {'provisioning_status': 'installation_launch_sent'},
        {'action': 'installation.verify'},
        {'state': 'SUCCEEDED', 'evidence': {
            'status': 'installed_guest_verified', 'installed_os_verified': True,
            'boot_mode': 'installed_disk', 'root_source': '/dev/sda1'}},
    )
    assert 'provisioning_status' not in verified
    assert verified['installation_verification']['installed_os_verified'] is True


def test_installation_verification_drops_an_unbound_root_source():
    from sentra_canvas.shell_dot_vm import project_vm_execution
    stored = project_vm_execution({}, {'action': 'installation.verify'}, {
        'state': 'SUCCEEDED',
        'evidence': {
            'status': 'installed_guest_verified',
            'installed_os_verified': True,
            'root_source': '/etc/passwd',
            'root_uuid': 'abcdef12-3456-7890-abcd-ef1234567890',
        },
    })
    verification = stored['installation_verification']
    assert 'installed_os_verified' not in verification
    assert 'root_source' not in verification
    assert verification['root_uuid'] == 'abcdef12-3456-7890-abcd-ef1234567890'
    kept = project_vm_execution({}, {'action': 'installation.verify'}, {
        'state': 'SUCCEEDED',
        'evidence': {'root_source': '/dev/sda1', 'installed_os_verified': True},
    })
    assert kept['installation_verification']['root_source'] == '/dev/sda1'
    poisoned = project_vm_execution({}, {'action': 'installation.verify'}, {
        'state': 'SUCCEEDED',
        'evidence': {
            'status': '/etc/passwd',
            'installed_os_verified': 'true',
            'boot_mode': 'installed_disk',
        },
    })
    fields = poisoned['installation_verification']
    assert 'status' not in fields
    assert 'installed_os_verified' not in fields
    assert fields['boot_mode'] == 'installed_disk'
    windows = project_vm_execution({}, {'action': 'installation.verify'}, {
        'state': 'SUCCEEDED',
        'evidence': {'installed_os_verified': True, 'desktop_ready_verified': False},
    })
    assert windows['installation_verification']['installed_os_verified'] is True
    assert windows['installation_verification']['desktop_ready_verified'] is False
    desktop = project_vm_execution({}, {'action': 'installation.verify'}, {
        'state': 'SUCCEEDED',
        'evidence': {'installed_os_verified': False, 'desktop_ready_verified': True},
    })
    assert desktop['installation_verification']['desktop_ready_verified'] is False
    live = project_vm_execution({}, {'action': 'installation.verify'}, {
        'state': 'SUCCEEDED',
        'evidence': {
            'boot_mode': 'live',
            'installed_os_verified': True,
            'desktop_ready_verified': True,
            'root_source': '/dev/sda1',
        },
    })
    assert live['installation_verification']['installed_os_verified'] is False
    assert live['installation_verification']['desktop_ready_verified'] is False


def test_installation_verification_routes_through_guest_capability(vm_scope,monkeypatch):
    app,pid,call,service,params,root,other,ca,cb=vm_scope
    call('access_set',conversation_id=ca['conversation_id'],mode='full')
    configure(service,pid,params)
    calls=[]
    monkeypatch.setattr(service.host,'dispatch',lambda **fields:calls.append(fields) or {'state':'SUCCEEDED','evidence':{'installed_os_verified':False}})
    service.dispatch(pid,'dot_vm_execute',{**params,'arguments':{'action':'installation.verify'}},uuid.uuid4().hex)
    assert calls[0]['capability_id']=='vm:guest'
    assert calls[0]['arguments']=={'action':'installation.verify'}


def test_host_resources_publishes_windows_available_and_linux_memavailable(monkeypatch):
    monkeypatch.setattr(os, 'name', 'nt')
    def status(memory):
        memory.total = 32 * 1024 * 1048576
        memory.available = (6 * 1024 * 1048576) + 4096
        memory.page_available = 99 * 1024 * 1048576
        return 1
    monkeypatch.setattr('sentra_canvas.shell_dot_vm._global_memory_status', status)
    host = host_resources()
    assert host['physical_memory_mb'] == 32768
    assert host['available_memory_mb'] == 6144
    assert host['max_memory_mb'] == 16384
    assert host['resource_fraction'] == 0.5
    monkeypatch.setattr('sentra_canvas.shell_dot_vm._global_memory_status', lambda memory: 0)
    with pytest.raises(RuntimeError, match='physical host memory unavailable'):
        host_resources()

    monkeypatch.setattr(os, 'name', 'posix')
    monkeypatch.setattr(os, 'sysconf', lambda name: 4096 if name == 'SC_PAGE_SIZE' else 8 * 1024 * 1024, raising=False)
    monkeypatch.setattr('sentra_canvas.shell_dot_vm._linux_available_bytes', lambda: (5 * 1024 * 1048576) + 2048)
    host = host_resources()
    assert host['physical_memory_mb'] == 32768
    assert host['available_memory_mb'] == 5120
    assert host['max_memory_mb'] == 16384


def test_live_host_resources_publishes_available_memory_under_the_half_ceiling():
    host = host_resources()
    assert host['available_memory_mb'] <= host['physical_memory_mb']
    assert host['max_memory_mb'] * 2 <= host['physical_memory_mb']
    assert host['resource_fraction'] == 0.5
    assert host['limit_kind'] == 'configured_vcpu_and_ram'


def test_memavailable_parser_ignores_memfree():
    text = 'MemTotal: 33554432 kB\nMemFree: 1024 kB\nMemAvailable: 5242880 kB\n'
    assert _memavailable_bytes(text) == 5242880 * 1024
    with pytest.raises(RuntimeError, match='physical host memory unavailable'):
        _memavailable_bytes('MemFree: 999999 kB\nBuffers: 1 kB\nCached: 1 kB\n')


def test_new_reservation_stops_at_free_ram_and_existing_row_stays(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    resources = dict(LIMITS)
    monkeypatch.setattr('sentra_canvas.shell_dot_vm.host_resources', lambda: dict(resources))
    # 4096 == 5120 - 1024 is still inside the headroom and inside the 50% ceiling.
    resources['available_memory_mb'] = 5120
    service.store.reserve(pid, root['dot_id'], {'cpus': 2, 'memory_mb': 4096, 'vm_id': 'already-admitted'})
    assert service.store.get(pid, root['dot_id'])['memory_mb'] == 4096
    resources['available_memory_mb'] = 5119
    with pytest.raises(ValueError, match='available host RAM'):
        service.store.reserve(pid, other['dot_id'], {'cpus': 1, 'memory_mb': 4096, 'vm_id': 'too-large'})
    assert service.store.get(pid, other['dot_id']) is None
    service.store.reserve(pid, root['dot_id'], {'cpus': 2, 'memory_mb': 4096, 'vm_id': 'already-admitted'})
    assert service.store.get(pid, root['dot_id'])['memory_mb'] == 4096
    resources['available_memory_mb'] = 32768
    with pytest.raises(ValueError, match='50%'):
        service.store.reserve(pid, other['dot_id'], {'cpus': 2, 'memory_mb': 16384, 'vm_id': 'over-ceiling'})
    with app._shell_service().store.connect('shell') as db:
        count = db.execute('SELECT COUNT(*) AS n FROM shell_dot_vms').fetchone()['n']
    assert count == 1


def test_low_available_ram_does_not_revoke_reserved_vm(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    resources = dict(LIMITS, available_memory_mb=32768)
    monkeypatch.setattr('sentra_canvas.shell_dot_vm.host_resources', lambda: dict(resources))
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    resources['available_memory_mb'] = 1024
    record = service.store.get(pid, root['dot_id'])
    assert record['memory_mb'] == 4096
    factory = service.host._factories[record['machine_id']]
    request = OperationRequest('vm-free-ram-' + uuid.uuid4().hex, root['agent_id'], record['machine_id'],
        'vm:manage', record['work_item_id'], uuid.uuid4().hex, {'action': 'provision'})
    assert factory.policy(request).allowed is True
    with pytest.raises(ValueError, match='available host RAM'):
        service.store.reserve(pid, other['dot_id'], {'cpus': 1, 'memory_mb': 2048, 'vm_id': 'blocked-new'})
    assert service.store.get(pid, root['dot_id'])['memory_mb'] == 4096
    assert service.store.budget()['reserved_memory_mb'] == 4096


def test_vm_status_distinguishes_registered_vm_from_live_guest_channel(vm_scope, monkeypatch):
    """A VM may exist and run without Guest Additions or a usable guest CLI."""
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    configure(service, pid, params, os_family='windows')
    record = service.store.get(pid, root['dot_id'])
    monkeypatch.setattr('sentra_executors.virtualbox_vm.executable',
                        lambda: r'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe')
    monkeypatch.setattr(VirtualBoxClient, 'run',
                        lambda self, *args, **kwargs: f'"Dot" {{{record["vm_id"]}}}')
    observed = {'VMState': 'running', 'GuestAdditionsRunLevel': '0'}
    monkeypatch.setattr(VirtualBoxClient, 'status', lambda self, binding: dict(observed))
    first = service.dispatch(pid, 'dot_vm_status', params)
    assert first['vm']['vm_state'] == 'running'
    assert first['guest_control']['ready'] is False
    assert first['guest_control']['reason'] == 'guest_additions_unavailable'
    observed['GuestAdditionsRunLevel'] = '2'
    second = service.dispatch(pid, 'dot_vm_status', params)
    assert second['guest_control']['ready'] is True
    assert second['guest_control']['transport'] == 'virtualbox-guestcontrol'
    assert second['os_ready_verified'] is False
    observed['VMState'] = 'aborted'
    third = service.dispatch(pid, 'dot_vm_status', params)
    assert third['guest_control']['ready'] is False
    assert third['guest_control']['reason'] == 'vm_not_running'


def test_vm_status_exposes_observed_guest_channel_without_credentials(vm_scope, monkeypatch):
    from sentra_executors import virtualbox_vm
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    del app, call, other, ca, cb
    configure(service, pid, params)
    record = service.store.get(pid, root["dot_id"])
    vm_id = record["vm_id"]
    monkeypatch.setattr(virtualbox_vm, "executable", lambda: "VBoxManage.exe")

    def observed(self, *args, **kwargs):
        if args[:2] == ("list", "vms"):
            return '"owned" {' + vm_id + '}\n'
        if args[0] == "showvminfo":
            return (f'UUID="{vm_id}"\n'
                    f'description="{record["marker"]}"\n'
                    'VMState="running"\nGuestAdditionsRunLevel=2\n'
                    'cpus=2\nmemory=4096\n')
        raise AssertionError("only read-only hypervisor inventory is permitted")

    monkeypatch.setattr(VirtualBoxClient, "run", observed)
    status = service.dispatch(pid, "dot_vm_status", params)
    assert status["guest_control"]["ready"] is True
    assert status["guest_control"]["runlevel"] == "2"
    assert status["vm"]["vm_state"] == "running"
    assert "password" not in str(status)
    assert "marker" not in str(status)

    def stopped(self, *args, **kwargs):
        result = observed(self, *args, **kwargs)
        return result.replace('VMState="running"', 'VMState="aborted"') if args[0] == "showvminfo" else result

    monkeypatch.setattr(VirtualBoxClient, "run", stopped)
    disconnected = service.dispatch(pid, "dot_vm_status", params)
    assert disconnected["guest_control"]["ready"] is False
    assert disconnected["guest_control"]["reason"] == "vm_not_running"


def test_legacy_vm_registry_is_adopted_without_new_vm_uuid_or_double_reservation(vm_scope, monkeypatch):
    """Adopt an existing verified Windows VM row whose old DB key is not a Dot ID."""
    import sqlite3
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    del app, call, other, ca, cb
    existing_uuid = str(uuid.uuid4())
    marker = "SENTRA-DOT:" + existing_uuid
    legacy = {
        "root_dot_id": root["dot_id"], "vm_id": existing_uuid,
        "marker": marker, "machine_id": "virtualbox-windows-validation",
        "name": "SENTRA-Dot-" + existing_uuid.replace("-", "")[:16],
        "base_folder": "C:\\legacy\\dot-vms", "os_family": "windows",
        "cpus": 2, "memory_mb": 4096, "disk_gb": 64, "iso_path": "",
        "iso_sha256": None, "username": "sentra",
        "password": "existing-secret-kept-in-registry",
        "provisioning_status": "installation_started",
    }
    service.store.reserve(pid, "dot-windows10-validation", legacy)

    def inventory(self, *args, **kwargs):
        if args[:2] == ("list", "vms"):
            return '"existing" {' + existing_uuid + '}'
        if args[0] == "showvminfo":
            return (f'UUID="{existing_uuid}"\n'
                    f'description="{marker}"\n'
                    'VMState="aborted"\ncpus=2\nmemory=4096\n')
        raise AssertionError("adoption must never change a VirtualBox disk")

    monkeypatch.setattr(VirtualBoxClient, "run", inventory)
    before = service.dispatch(pid, "dot_vm_status", params)
    assert before["vm"]["adoption_required"] is True
    assert before["vm"]["vm_id"] == existing_uuid
    assert before["vm"]["conversation_authorized"] is False

    after = configure(service, pid, params, os_family="windows", cpus=2, memory_mb=4096)
    assert after["vm"]["vm_id"] == existing_uuid
    assert after["vm"]["vm_state"] == "aborted"
    assert after["vm"]["conversation_authorized"] is True
    assert after["vm"].get("adoption_required") is not True
    assert after["host"]["reserved_cpus"] == 2
    assert after["host"]["reserved_memory_mb"] == 4096
    record = service.store.get(pid, root["dot_id"])
    assert record["agent_id"] == root["agent_id"]
    assert record["machine_id"] != "virtualbox-windows-validation"
    assert record["password"] == legacy["password"]
    assert record["provisioning_status"] == "installation_started"
    assert len(record["work_items"]) == 1
    with service.host.control.store.connect("shell") as db:
        roots = [r[0] for r in db.execute("select root from shell_dot_vms")]
    assert roots == [root["dot_id"]]


def test_legacy_vm_adoption_rejects_hypervisor_marker_mismatch(vm_scope, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    del app, call, other, ca, cb
    existing_uuid = str(uuid.uuid4())
    legacy = {
        "root_dot_id": root["dot_id"], "vm_id": existing_uuid,
        "marker": "SENTRA-DOT:" + existing_uuid, "os_family": "windows",
        "cpus": 2, "memory_mb": 4096, "disk_gb": 64, "iso_path": "",
        "iso_sha256": None, "username": "sentra", "password": "existing-secret",
    }
    service.store.reserve(pid, "dot-windows10-validation", legacy)

    def mismatched(self, *args, **kwargs):
        if args[:2] == ("list", "vms"):
            return '"existing" {' + existing_uuid + '}'
        if args[0] == "showvminfo":
            return (f'UUID="{existing_uuid}"\n'
                    'description="WRONG-VM"\nVMState="aborted"\ncpus=2\nmemory=4096\n')
        raise AssertionError("no physical mutator should be dispatched")

    monkeypatch.setattr(VirtualBoxClient, "run", mismatched)
    with pytest.raises(Exception, match="identity_changed"):
        configure(service, pid, params, os_family="windows", cpus=2, memory_mb=4096)
    assert service.store.get(pid, root["dot_id"]) is None
    assert service.store.get(pid, "dot-windows10-validation")["vm_id"] == existing_uuid
