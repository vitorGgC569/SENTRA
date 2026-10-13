"""Resource reservations, real central grants and VirtualBox command construction."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import uuid
import pytest
from test_shell_dot_features import shell, dot
from sentra_canvas.shell_dot_vm import VmStore, DotVmServices
from sentra_canvas.store import Denied
from sentra_executors.virtualbox_vm import VirtualBoxBinding, VirtualBoxClient, VirtualBoxExecutor
from sentra_runtime.contracts import OperationRequest

LIMITS = {'logical_cpus': 12, 'physical_memory_mb': 32768, 'max_cpus': 6, 'max_memory_mb': 16384,
    'resource_fraction': 0.5, 'limit_kind': 'configured_vcpu_and_ram'}


@pytest.fixture
def vm_scope(shell, monkeypatch):
    monkeypatch.setattr('sentra_canvas.shell_dot_vm.host_resources', lambda: dict(LIMITS))
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
    assert cfg['password'] not in str(install[0]) and install[1]['input'] == cfg['password'] + '\n'
    assert all('shell' not in options for _, options in calls)


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

def test_installation_verification_routes_through_guest_capability(vm_scope,monkeypatch):
    app,pid,call,service,params,root,other,ca,cb=vm_scope
    call('access_set',conversation_id=ca['conversation_id'],mode='full')
    configure(service,pid,params)
    calls=[]
    monkeypatch.setattr(service.host,'dispatch',lambda **fields:calls.append(fields) or {'state':'SUCCEEDED','evidence':{'installed_os_verified':False}})
    service.dispatch(pid,'dot_vm_execute',{**params,'arguments':{'action':'installation.verify'}},uuid.uuid4().hex)
    assert calls[0]['capability_id']=='vm:guest'
    assert calls[0]['arguments']=={'action':'installation.verify'}
