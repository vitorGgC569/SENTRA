import pytest
from test_sentra_executors_integral_forja import central
from sentra_executors.input_control import InputControl
from sentra_runtime.contracts import OperationRequest


def setup(central):
    control,owner,agent,work,_=central
    now=[100.0]
    lease=InputControl(control,owner=owner,clock=lambda:now[0])
    grant=control.authorization.grant(owner,principal_type='agent',principal_id=agent,
        capability='uia:input',scope_type='work_item',scope_id=work)['grant_id']
    request=OperationRequest('op-auto',agent,'machine-forja','uia:input',work,'auto-request',{'action':'invoke'})
    args=dict(resource_id='desktop-forja',workspace_id='ws-forja',machine_id='machine-forja',
        holder='agent',expected_epoch=0,request_key='auto-1',request=request,only_if_available=True)
    return control,owner,lease,now,args,grant


def test_expired_possession_acquires_current_granted_work_and_fresh_epoch(central):
    control,owner,lease,now,args,grant=setup(central)
    first=lease.handoff(**args,ttl_seconds=10)
    assert first['epoch']==1 and not first['grant_created']
    now[0]=111
    acquired=lease.handoff(**{**args,'expected_epoch':1,'request_key':'auto-2'})
    assert acquired['epoch']==2
    assert lease.status(resource_id='desktop-forja',workspace_id='ws-forja')['work_item_id']==args['request'].work_item_id


@pytest.mark.parametrize('holder',['human','agent'])
def test_automatic_acquisition_never_takes_live_possession(central,holder):
    control,owner,lease,now,args,grant=setup(central)
    lease.handoff(**{**args,'holder':holder,'request_key':'existing','only_if_available':False})
    with pytest.raises(PermissionError,match='cannot be acquired automatically'):
        lease.handoff(**{**args,'expected_epoch':1,'request_key':'auto-2'})
    status=lease.status(resource_id='desktop-forja',workspace_id='ws-forja')
    assert status['epoch']==1 and status['holder']==holder


def test_revoked_grant_cannot_acquire_expired_possession(central):
    control,owner,lease,now,args,grant=setup(central)
    lease.handoff(**args,ttl_seconds=10)
    now[0]=111;control.authorization.revoke(grant,owner)
    with pytest.raises(PermissionError):
        lease.handoff(**{**args,'expected_epoch':1,'request_key':'auto-2'})
