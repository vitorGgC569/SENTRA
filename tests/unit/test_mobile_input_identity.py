import pytest
from test_sentra_executors_integral_forja import central
from sentra_executors.input_control import InputControl,human_input_scope


def test_mobile_possession_is_fenced_by_host_derived_client_identity(central):
    control,owner,_agent,_work,_root=central
    lease=InputControl(control,owner=owner)
    scope=dict(resource_id='screen',workspace_id='ws-forja',machine_id='machine-forja')
    lease.handoff(**scope,holder='human',expected_epoch=0,request_key='phone-a-claim',client_id='mobile:a')
    assert lease.status(resource_id='screen',workspace_id='ws-forja')['client_id']=='mobile:a'
    for client in ['', 'mobile:b']:
        with pytest.raises(PermissionError):
            with human_input_scope(control,owner=owner,**scope,expected_epoch=1,client_id=client):pass
    with human_input_scope(control,owner=owner,**scope,expected_epoch=1,client_id='mobile:a'):pass
    with pytest.raises(PermissionError):
        lease.handoff(**scope,holder='none',expected_epoch=1,request_key='phone-b-release',client_id='mobile:b')
    # Explicit desktop takeover advances the central epoch and fences the phone.
    lease.handoff(**scope,holder='human',expected_epoch=1,request_key='desktop-takeover')
    with pytest.raises(PermissionError):
        with human_input_scope(control,owner=owner,**scope,expected_epoch=2,client_id='mobile:a'):pass
    with human_input_scope(control,owner=owner,**scope,expected_epoch=2):pass
