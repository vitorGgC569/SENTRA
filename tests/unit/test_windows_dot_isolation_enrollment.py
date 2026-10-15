"""Real CP/MachineHost/fences/DPAPI; synthetic hypervisor and temporary VDIs only."""
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import pytest

from test_virtualbox_installation import client
from sentra_canvas.shell_dot_vm import VmStore, _public_vm_fields
from sentra_executors.central_integration import CentralExecutorFactory
from sentra_executors.discovery import MachineDeclaration
from sentra_executors.virtualbox_vm import VirtualBoxExecutor, VM_CAPABILITIES
from sentra_executors.virtualbox_storage_binding import storage_binding_candidate
from sentra_executors.virtualbox_storage_enrollment import (
    configured_storage_candidate, public_storage_candidate, owner_storage_enrollment_scope,
    storage_enrollment_callbacks,
    storage_enrollment_policy,
    dispatch_owner_storage_enrollment,
)
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import Machine, Capability
from sentra_runtime.machine_host import MachineHost


OWNER, PROJECT, ROOT, CID = 'owner-storage', 'project-storage', 'dot-storage', 'conversation-storage'
RUN, WORK, MACHINE, AGENT = 'run-storage', 'work-storage', 'machine-storage', 'agent-storage'


@pytest.fixture
def live(tmp_path, monkeypatch):
    fake,binding,cfg,disk,ident=client(tmp_path,allocated=True,partitioned=True)
    (disk.parent/'owned.vbox').write_text('<synthetic-vbox/>')
    storage=tmp_path/'private-disk';storage.mkdir();actual=storage/'system-localiso2.vdi';disk.rename(actual)
    attached=fake.disk_attachments(binding)[0]
    fake.disk_attachments=lambda b:[{**attached,'location':str(actual)}]
    state=tmp_path/'state';durable=DurableRunService(state)
    control=ControlPlaneService(durable,ContextBusService(state))
    control.durable.create_run(OWNER,run_id=RUN,workspace=str(tmp_path))
    control.ensure_agent(RUN,OWNER,agent_id=AGENT,role='worker')
    control.create_work_item(RUN,OWNER,work_item_id=WORK,objective='Synthetic storage commissioning',
        assignee_agent_id=AGENT,required_capabilities=list(VM_CAPABILITIES),
        metadata={'workspace_id':PROJECT,'machine_id':MACHINE,'conversation_id':CID,'root_dot_id':ROOT})
    control.transition_work_item(WORK,OWNER,'QUEUED')
    control.start_work_item_execution(WORK,OWNER,run_id=RUN,agent_id=AGENT)
    grants={cap:control.authorization.grant(OWNER,principal_type='agent',principal_id=AGENT,
        capability=cap,scope_type='work_item',scope_id=WORK)['grant_id'] for cap in VM_CAPABILITIES}
    cfg.update(vm_id=binding.vm_id,marker=binding.marker,machine_id=MACHINE,agent_id=AGENT,
               root_dot_id=ROOT,work_items={CID:WORK},cpus=1,memory_mb=1024)
    store=VmStore(control,OWNER)
    monkeypatch.setattr('sentra_canvas.shell_dot_vm.host_resources',lambda:{
        'max_cpus':4,'max_memory_mb':8192,'available_memory_mb':16384})
    store.reserve(PROJECT,ROOT,cfg)
    enroll,verify=storage_enrollment_callbacks(control,owner=OWNER,workspace_id=PROJECT,
                                              root_dot_id=ROOT,host_storage_roots=(storage,))
    binding=replace(binding,configuration=lambda:store.get(PROJECT,ROOT),
                    storage_enrollment=enroll,storage_approval=verify)
    candidate=storage_binding_candidate(fake,binding,cfg,storage_root=storage)
    factory=CentralExecutorFactory(control=control,owner=OWNER,agent_id=AGENT)
    factory.policy=store.policy(factory.policy,PROJECT,ROOT)
    factory.policy=storage_enrollment_policy(factory.policy,control=control,owner=OWNER,
                                             workspace_id=PROJECT,root_dot_id=ROOT)
    executor=VirtualBoxExecutor(machine_id=MACHINE,owner_principal_id=AGENT,
                                bindings={cap:binding for cap in VM_CAPABILITIES},client=fake,policy=factory.policy)
    declaration=MachineDeclaration(Machine(MACHINE,'virtualbox_vm',AGENT,
        tuple(Capability(cap,cap,'high') for cap in VM_CAPABILITIES)),executor)
    factory.register_execution(declaration)
    host=MachineHost(control,owner=OWNER)
    async def register():
        host._factories[MACHINE]=factory
        host._inventory[MACHINE]={'machine_id':MACHINE,'kind':'virtualbox_vm','workspace_id':PROJECT,
            'agent_id':AGENT,'vm_id':binding.vm_id,'root_dot_id':ROOT,'capabilities':list(VM_CAPABILITIES)}
    host._call(register())
    try:yield dict(control=control,host=host,store=store,candidate=candidate,binding=binding,
                   fake=fake,grants=grants,disk=actual,executor=executor)
    finally:host.close();durable.close()


def dispatch(live,tag,action,cap='vm:manage',**fields):
    return live['host'].dispatch(workspace_id=PROJECT,work_item_id=WORK,machine_id=MACHINE,
        capability_id=cap,operation_id='op-'+tag,idempotency_key='request-'+tag,
        arguments={'action':action,**fields})


@contextmanager
def owner(live,tag,**changes):
    args=dict(owner=OWNER,workspace_id=PROJECT,root_dot_id=ROOT,conversation_id=CID,
              operation_id='op-'+tag,expected_sha256=live['candidate']['sha256'])
    with owner_storage_enrollment_scope(live['control'],**(args|changes)):yield


def enroll(live,tag='enroll'):
    with owner(live,tag):
        return dispatch(live,tag,'storage.enroll',expected_candidate_sha256=live['candidate']['sha256'])


def test_owner_scope_crosses_real_machine_host_and_records_canonical_approval(live):
    result=enroll(live)
    assert result['state']=='SUCCEEDED',result
    assert result['evidence']['metadata_recorded'] and result['evidence']['vm_or_disk_mutated'] is False
    assert result['evidence']['activation_requires_operation_succeeded']
    observed=live['host'].observe(workspace_id=PROJECT,operation_id=result['operation_id'])
    assert observed==result
    plan=dispatch(live,'read-plan','installation.plan','vm:observe')
    assert plan['state']=='SUCCEEDED',plan
    assert plan['evidence']['disk']['storage_binding_sha256']==live['candidate']['sha256']
    assert not plan['evidence']['installed_os_verified'] and not live['fake'].calls
    raw=live['control'].store.path_for('shell').read_bytes()
    assert str(live['disk']).encode() not in raw


def test_vm_manage_grant_alone_does_not_let_an_agent_self_approve(live):
    with pytest.raises(PermissionError,match='live grant denied'):
        dispatch(live,'agent-forgery','storage.enroll',expected_candidate_sha256=live['candidate']['sha256'])
    assert 'storage_binding' not in live['store'].get(PROJECT,ROOT)
    assert not live['fake'].calls


@pytest.mark.parametrize('changes',[{'operation_id':'op-another'},{'conversation_id':'another-conversation'},
    {'root_dot_id':'another-root'},{'workspace_id':'another-project'},{'owner':'another-owner'},
    {'expected_sha256':'b'*64}])
def test_review_scope_is_exact_not_a_reusable_owner_boolean(live,changes):
    with owner(live,'wrong-scope',**changes):
        with pytest.raises(PermissionError,match='live grant denied'):
            dispatch(live,'wrong-scope','storage.enroll',expected_candidate_sha256=live['candidate']['sha256'])
    assert 'storage_binding' not in live['store'].get(PROJECT,ROOT)


def test_candidate_is_recomputed_at_enrollment_and_changed_file_is_rejected(live):
    replacement=live['disk'].with_name('replacement.vdi')
    replacement.write_bytes(live['disk'].read_bytes());replacement.replace(live['disk'])
    result=enroll(live)
    assert result['state']=='UNCERTAIN' and 'storage_binding' not in live['store'].get(PROJECT,ROOT)


def test_revoked_grant_refuses_metadata_write_even_with_exact_owner_review(live):
    live['control'].authorization.revoke(live['grants']['vm:manage'],OWNER)
    with pytest.raises(PermissionError,match='live grant denied'):enroll(live)
    assert 'storage_binding' not in live['store'].get(PROJECT,ROOT)


def test_live_human_possession_is_not_bypassed_by_owner_enrollment_scope(live):
    from sentra_executors.input_control import InputControl
    from sentra_executors.windows_dot_isolation import console_resource_id
    InputControl(live['control'],owner=OWNER).handoff(resource_id=console_resource_id(live['binding'].vm_id),
        workspace_id=PROJECT,machine_id=MACHINE,holder='human',expected_epoch=0,request_key='human-storage-test')
    with pytest.raises(PermissionError,match='live grant denied'):enroll(live)
    assert 'storage_binding' not in live['store'].get(PROJECT,ROOT)


def test_approval_reference_without_canonical_success_cannot_activate_storage(live):
    original=live['binding'].storage_enrollment
    def interrupted(*args):
        original(*args)
        raise RuntimeError('synthetic interruption after metadata write')
    changed=replace(live['binding'],storage_enrollment=interrupted)
    live['executor'].bindings['vm:manage']=changed
    result=enroll(live)
    assert result['state']=='UNCERTAIN'
    assert live['store'].get(PROJECT,ROOT)['storage_binding']['approval_operation_id']==result['operation_id']
    from sentra_runtime.executor import DuplicateOperation
    with pytest.raises(DuplicateOperation):
        dispatch(live,'after-interruption','installation.plan','vm:observe')


def test_tampered_canonical_approval_artifact_prevents_activation(live):
    result=enroll(live);assert result['state']=='SUCCEEDED'
    durable=live['control'].durable
    op=durable.operation_status(result['operation_id'],OWNER)
    artifact=durable.artifact_info(op['result']['evidence_artifact_id'],OWNER)
    Path(artifact['path']).write_bytes(b'forged approval JSON')
    plan=dispatch(live,'tampered-approval','installation.plan','vm:observe')
    assert plan['state']!='SUCCEEDED'


def test_request_schema_refuses_approval_booleans_json_records_and_paths(live):
    for index,extra in enumerate([{'approved':True},{'record':live['candidate']['record']},
                                  {'storage_root':str(live['disk'].parent)},{'owner':OWNER}]):
        with owner(live,'schema-'+str(index)):
            with pytest.raises(PermissionError,match='live grant denied'):
                dispatch(live,'schema-'+str(index),'storage.enroll',
                         expected_candidate_sha256=live['candidate']['sha256'],**extra)
    assert 'storage_binding' not in live['store'].get(PROJECT,ROOT)


def test_public_candidate_has_no_paths_file_ids_or_private_record(live):
    value=public_storage_candidate(live['candidate'])
    assert value['candidate_sha256']==live['candidate']['sha256']
    assert not {'record','disk_path','storage_root','config_path','file_inode','file_device'} & value.keys()
    text=json.dumps(value)
    assert str(live['disk']) not in text and 'private-disk' not in text


def test_real_public_vm_projection_never_exposes_private_enrollment(live):
    result=enroll(live);assert result['state']=='SUCCEEDED'
    value=live['store'].get(PROJECT,ROOT)
    assert 'storage_binding' in value
    shown=_public_vm_fields(value)
    assert 'storage_binding' not in shown
    assert str(live['disk']) not in json.dumps(shown)
    assert not {'file_inode','file_device','disk_path','config_path'} & shown.keys()


def test_host_roots_cannot_be_discovered_from_an_arbitrary_attachment(live):
    with pytest.raises(Exception,match='outside_host_roots'):
        configured_storage_candidate(live['fake'],live['binding'],live['store'].get(PROJECT,ROOT))


@pytest.mark.parametrize('reference',['op-missing-proof','op-unrelated-status'])
def test_an_operation_id_string_is_never_canonical_storage_approval(live,reference):
    if reference=='op-unrelated-status':
        assert dispatch(live,'unrelated-status','status','vm:observe')['state']=='SUCCEEDED'
    candidate=live['candidate']
    envelope={key:candidate[key] for key in ('schema','record','sha256')}|{'approval_operation_id':reference}
    live['store'].patch(PROJECT,ROOT,storage_binding=envelope)
    plan=dispatch(live,'fake-proof-read','installation.plan','vm:observe')
    assert plan['state']!='SUCCEEDED'


def test_concurrent_configuration_update_is_preserved_instead_of_overwritten(live):
    previous=live['fake'].disk_attachments
    changed=False
    def update_during_inventory(binding):
        nonlocal changed
        if not changed:
            changed=True
            live['store'].patch(PROJECT,ROOT,other_owner_configuration='preserve-this-update')
        return previous(binding)
    live['fake'].disk_attachments=update_during_inventory
    result=enroll(live)
    assert result['state']=='UNCERTAIN'
    cfg=live['store'].get(PROJECT,ROOT)
    assert 'storage_binding' not in cfg and cfg['other_owner_configuration']=='preserve-this-update'


def test_native_owner_dispatch_uses_existing_request_journal_and_replay_is_read_only(live):
    from sentra_canvas.shell_requests import ShellHostRequests
    journal=ShellHostRequests(live['control'],OWNER)
    class NativeOwnerServiceFixture:
        host=live['host']
        requests=journal
        calls=0
        def scope(self,pid,params):
            assert pid==PROJECT and params['dot_id']==ROOT and params['conversation_id']==CID
            return ROOT,{}, {'conversation_id':CID}
        def dispatch(self,pid,action,params,key):
            def run():
                self.calls+=1
                return self.host.dispatch(workspace_id=pid,work_item_id=WORK,machine_id=MACHINE,
                    capability_id='vm:manage',operation_id=journal.operation_id(pid,key,action),
                    idempotency_key=key,arguments=params['arguments'])
            return journal.invoke(pid,action,params,key,run)
    service=NativeOwnerServiceFixture()
    params={'dot_id':ROOT,'space_id':'space-fixture','conversation_id':CID,
            'arguments':{'action':'storage.enroll','expected_candidate_sha256':live['candidate']['sha256']}}
    result=dispatch_owner_storage_enrollment(service,PROJECT,params,'native-owner-storage-review')
    assert result['state']=='SUCCEEDED'
    assert dispatch_owner_storage_enrollment(service,PROJECT,params,'native-owner-storage-review')==result
    assert service.calls==1 and not live['fake'].calls


def test_native_owner_dispatch_does_not_accept_paths_or_approval_flags(live):
    from types import SimpleNamespace
    service=SimpleNamespace(scope=lambda *_:pytest.fail('unbounded request reached the owner scope'))
    params={'dot_id':ROOT,'space_id':'space-fixture','conversation_id':CID,
            'arguments':{'action':'storage.enroll','expected_candidate_sha256':live['candidate']['sha256'],'approved':True}}
    with pytest.raises(ValueError,match='exact_owner_storage'):
        dispatch_owner_storage_enrollment(service,PROJECT,params,'native-owner-storage-review')


def test_disabled_enrollment_is_rejected_before_any_physical_boundary(live):
    from sentra_runtime.contracts import OperationRequest
    binding=replace(live['binding'],storage_enrollment=None,storage_approval=None)
    request=OperationRequest('op-disabled',AGENT,MACHINE,'vm:manage',WORK,'key-disabled',
                            {'action':'storage.enroll','expected_candidate_sha256':live['candidate']['sha256']})
    with pytest.raises(ValueError,match='callbacks are not configured'):
        live['executor']._validate(request,binding)
    assert 'storage_binding' not in live['store'].get(PROJECT,ROOT)


@pytest.mark.parametrize('classification',['observation','cleanup'])
def test_enrollment_refuses_non_mutating_or_cleanup_operation_admission(live,classification):
    # Exercise real admission with a misconfigured trusted classifier, rather
    # than accepting a caller-provided operation kind or forged receipt.
    authority=live['host']._factories[MACHINE].durable_intent_authority
    if classification=='observation':
        authority.observation_predicate=lambda request:True
    else:
        authority.allow_cleanup=True
    result=enroll(live,'wrong-admission-'+classification)
    assert result['state']!='SUCCEEDED',result
    operation=live['control'].durable.operation_status(result['operation_id'],OWNER)
    assert operation['kind']=='sentra.machine.'+classification
    assert 'storage_binding' not in live['store'].get(PROJECT,ROOT)
    assert not live['fake'].calls
