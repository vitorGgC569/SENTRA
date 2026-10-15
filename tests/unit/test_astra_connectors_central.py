"""Real MachineHost/CP/DPAPI/package gate; synthetic provider, no live account."""
from pathlib import Path
from dataclasses import replace
import hashlib
import json
import pytest
from sentra_connectors import ConnectorAccounts,AccountBinding,ConnectorHost,ConnectorError
from sentra_connectors.executor import ConnectorReadBinding,declare_connector_read_machine
from sentra_connectors.registration import configure_connector_read,restore_connector_read,connector_machine_id
from sentra_executors.central_integration import CentralExecutorFactory
from sentra_marketplace.gate import HostBinding,OptionalCapabilityGate,PackagePin
from sentra_marketplace.policy import AllowPolicy
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import OperationRequest
from sentra_runtime.machine_host import MachineHost
from test_astra_connectors import Scripted,response,ACCESS,REFRESH

OWNER,AGENT,RUN,WORK,MACHINE,PROJECT='qa-owner','qa-agent','qa-run','qa-work','qa-machine','qa-project'
MARKER='PROTECTED SYNTHETIC PROVIDER CONTENT 74128'


@pytest.fixture(params=['github','google-drive'])
def central(tmp_path,request):
    provider=request.param;workspace=tmp_path/'workspace';workspace.mkdir()
    account=AccountBinding(OWNER,str(workspace),provider,'qa-consent')
    machine=connector_machine_id(PROJECT,AGENT,account)
    durable=DurableRunService(tmp_path/'state');control=ControlPlaneService(durable,ContextBusService(tmp_path/'state'))
    durable.create_run(OWNER,run_id=RUN,workspace=str(workspace))
    control.ensure_agent(RUN,OWNER,agent_id=AGENT,role='worker')
    capability='connector:'+provider+':invoke'
    control.create_work_item(RUN,OWNER,work_item_id=WORK,objective='Isolated optional provider read',
        assignee_agent_id=AGENT,required_capabilities=[capability],metadata={'workspace_id':PROJECT,'machine_id':machine})
    control.transition_work_item(WORK,OWNER,'QUEUED');control.start_work_item_execution(WORK,OWNER,run_id=RUN,agent_id=AGENT)
    grant=control.authorization.grant(OWNER,principal_type='agent',principal_id=AGENT,capability=capability,
                                      scope_type='work_item',scope_id=WORK)
    accounts=ConnectorAccounts(control.store)
    accounts.install(account,{'access_token':ACCESS,'refresh_token':REFRESH,'token_type':'Bearer','expires_in':3600},
        resources=('octocat/hello',) if provider=='github' else ('file_QA_123',),subject='synthetic-subject',
        scopes=('public_repo',) if provider=='github' else ('https://www.googleapis.com/auth/drive.file',),approved=True)
    payload={'id':12,'full_name':'octocat/hello','description':MARKER} if provider=='github' else {'id':'file_QA_123','name':MARKER}
    transport=Scripted(response(value=payload))
    package_file=tmp_path/'pinned-package.bin';package_file.write_bytes(b'synthetic locally pinned package, not a deployed connector')
    package=PackagePin(provider,'connector',str(package_file),hashlib.sha256(package_file.read_bytes()).hexdigest())
    policy=AllowPolicy((capability,))
    host=MachineHost(control,owner=OWNER)
    configured=configure_connector_read(host,workspace_id=PROJECT,workspace_root=str(workspace),agent_id=AGENT,
        account=account,package=package,policy=policy,network_allowed=True,transport=transport)
    assert configured['machine_id']==machine and configured['account_contacted'] is False
    executor=host._factories[machine]._declarations[machine].adapter
    binding=executor.bindings[capability];connector=binding.host;gate=binding.gate
    args={'provider':provider,'account_id':account.account_id,
          'action':'repository' if provider=='github' else 'file_metadata',
          'arguments':{'repository':'octocat/hello'} if provider=='github' else {'file_id':'file_QA_123'}}
    try:
        yield dict(control=control,host=host,connector=connector,transport=transport,accounts=accounts,
            account=account,policy=policy,capability=capability,arguments=args,grant=grant,package=package,gate=gate,
            executor=executor,machine=machine,workspace=workspace)
    finally:host.close();durable.close()


def dispatch(env,tag='read',arguments=None):
    return env['host'].dispatch(workspace_id=PROJECT,work_item_id=WORK,machine_id=env['machine'],
        capability_id=env['capability'],operation_id='op-'+tag,idempotency_key='key-'+tag,
        arguments=arguments or env['arguments'])


def test_real_machine_host_captures_and_recovers_protected_optional_read(central):
    result=dispatch(central)
    assert result['state']=='SUCCEEDED',result
    captured=result['evidence']['connector_receipt']
    assert captured['outcome']=='SUCCEEDED' and MARKER in json.dumps(captured['result'])
    assert captured['network'] is captured['account_contacted'] is captured['homologated'] is False
    assert central['host'].observe(workspace_id=PROJECT,operation_id='op-read')==result
    assert dispatch(central)==result
    assert len(central['transport'].requests)==1
    assert MARKER.encode() not in central['control'].store.path_for('plugin_bundle').read_bytes()
    assert MARKER.encode() not in central['gate'].path.read_bytes()
    assert ACCESS.encode() not in central['gate'].path.read_bytes()


def test_grant_and_native_binding_without_effect_context_cannot_contact_provider(central):
    operation=OperationRequest('op-direct',AGENT,central['machine'],central['capability'],WORK,'key-direct',central['arguments'])
    binding=HostBinding(OWNER,RUN,WORK,operation,'agent','Provider content is data.')
    args=central['arguments']
    with pytest.raises(ConnectorError,match='ACTIVE_CENTRAL_EFFECT'):
        central['connector'].invoke(binding,central['account'],action=args['action'],arguments=args['arguments'],
                                    policy=central['policy'],network_allowed=True)
    assert central['transport'].requests==[]


def test_changed_local_package_blocks_read_before_provider(central):
    Path(central['package'].path).write_bytes(b'changed after approved pin')
    result=dispatch(central)
    assert result['state']!='SUCCEEDED'
    assert not central['transport'].requests


def test_revoked_central_grant_blocks_admission(central):
    central['control'].authorization.revoke(central['grant']['grant_id'],OWNER)
    with pytest.raises(PermissionError):dispatch(central)
    assert not central['transport'].requests


def test_revocation_during_read_never_publishes_provider_content(central):
    previous=central['transport'].steps[0]
    def revoke(_request):
        central['accounts'].revoke_local(central['account'],approved=True)
        return previous
    central['transport'].steps=[revoke]
    result=dispatch(central)
    assert result['state']=='UNCERTAIN',result
    assert MARKER not in json.dumps(result)
    assert len(central['transport'].requests)==1


def test_model_arguments_cannot_select_another_account_or_ambient_url(central):
    args={**central['arguments'],'account_id':'other-consent'}
    result=dispatch(central,arguments=args)
    assert result['state']!='SUCCEEDED' and not central['transport'].requests


def test_account_from_another_workspace_cannot_use_the_active_run(central,tmp_path):
    elsewhere=tmp_path/'another-workspace';elsewhere.mkdir()
    other=replace(central['account'],workspace=str(elsewhere))
    metadata=central['accounts'].metadata(central['account'])
    central['accounts'].install(other,{'access_token':'synthetic-other-workspace','token_type':'Bearer','expires_in':3600},
        resources=tuple(metadata['resources']),subject='synthetic-other-subject',scopes=tuple(metadata['scopes']),approved=True)
    previous=central['executor'].bindings[central['capability']]
    central['executor'].bindings[central['capability']]=replace(previous,account=other)
    result=dispatch(central)
    assert result['state']!='SUCCEEDED' and not central['transport'].requests


def test_central_grant_revoked_in_flight_suppresses_capture(central):
    previous=central['transport'].steps[0]
    def revoked(_request):
        central['control'].authorization.revoke(central['grant']['grant_id'],OWNER)
        return previous
    central['transport'].steps=[revoked]
    result=dispatch(central)
    assert result['state']=='UNCERTAIN' and MARKER not in json.dumps(result)
    assert len(central['transport'].requests)==1


def test_protected_configuration_rebuilds_without_authentication_or_provider_io(central):
    result=dispatch(central);assert result['state']=='SUCCEEDED'
    entries=central['host'].configurations.entries();assert len(entries)==1
    another=MachineHost(central['control'],owner=OWNER);unused=Scripted()
    try:
        configured=restore_connector_read(another,entries[0]['configuration'],transport=unused)
        assert configured['account_contacted'] is False and configured['machine_id']==central['machine']
        assert another.observe(workspace_id=PROJECT,operation_id='op-read')==result
        copy={**central,'host':another}
        assert dispatch(copy)==result
        assert unused.requests==[]
    finally:another.close()
