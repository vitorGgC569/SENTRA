"""The paired gateway uses the real shell, with disposable Canvas state."""
import base64
import uuid

import pytest

from test_shell_dot_features import shell, dot
from sentra_canvas.mobile_devices import registry, gateway_call


def test_mobile_scope_filters_conversations_and_revokes_immediately(shell):
    app, _server, scope, call = shell
    first, other = dot(call, 'Paired'), dot(call, 'Other')
    conversation = call('conversation_create', dot_id=first['dot_id'])
    foreign = call('conversation_create', dot_id=other['dot_id'])
    devices = registry(app)
    offer = devices.invite()
    public_key = base64.b64encode(b'x' * 32).decode()
    paired = devices.pair(offer['invite_id'], offer['invite'], public_key, 'Test phone')
    allowed = {**scope, 'dot_id': first['dot_id'], 'actions': [
        'workspace_inventory', 'conversation_list', 'conversation_get', 'message_list',
        'coordinator_approval_list', 'coordinator_approval_reply']}
    devices.approve(paired['device_id'], allowed)
    claimed = devices.claim(paired['device_id'], public_key)

    def mobile(action, **fields):
        return gateway_call(app, {'method': 'request', 'public_key': public_key,
            'device_id': paired['device_id'], 'credential': claimed['credential'],
            'request': {**scope, 'dot_id': first['dot_id'], 'action': action, **fields}})

    inventory = mobile('workspace_inventory')['value']
    assert inventory['protocol_version'] == 1
    listed = mobile('conversation_list')['value']['items']
    assert [c['conversation_id'] for c in listed] == [conversation['conversation_id']]
    assert mobile('conversation_get', conversation_id=conversation['conversation_id'])['ok']
    assert mobile('message_list', conversation_id=conversation['conversation_id'], tail=True, limit=50)['ok']
    with pytest.raises(PermissionError, match='outside paired Dot'):
        mobile('conversation_get', conversation_id=foreign['conversation_id'])
    with pytest.raises(PermissionError, match='outside paired scope'):
        mobile('workspace_inventory', dot_id=other['dot_id'])
    with pytest.raises(PermissionError):
        mobile('message_send', conversation_id=conversation['conversation_id'],
               content='Forbidden', request_key=uuid.uuid4().hex)
    from sentra_runtime.coordinator_approvals import CoordinatorApprovalInbox
    inbox = CoordinatorApprovalInbox(app._shell_service(), app._runtime().owner)
    for actor, conv, name in [(first,conversation,'first'), (other,foreign,'other')]:
        inbox.record(project_id=scope['project_id'],space_id=scope['space_id'],
            conversation_id=conv['conversation_id'],parent_operation_id='op-'+name,
            work_item_id='work-'+name,agent_id=actor['agent_id'],approval_id='coordinator-'+name,
            capability='canvas.coordinator.delegate',intent={'kind':'delegate','name':name})
    approvals = mobile('coordinator_approval_list')['value']['items']
    assert [a['approval_id'] for a in approvals] == ['coordinator-first']
    with pytest.raises(PermissionError, match='outside paired Dot'):
        mobile('coordinator_approval_reply',approval_id='coordinator-other',answer='reject',request_key=uuid.uuid4().hex)
    assert mobile('coordinator_approval_reply',approval_id='coordinator-first',answer='reject',request_key=uuid.uuid4().hex)['value']['state']=='rejected'
    devices.revoke(paired['device_id'])
    with pytest.raises(PermissionError, match='revoked'):
        mobile('workspace_inventory')


def test_mobile_message_receipt_observes_without_resend(shell,monkeypatch):
    app, _server, scope, call = shell
    actor = dot(call, 'Messages')
    conversation = call('conversation_create', dot_id=actor['dot_id'])
    monkeypatch.setattr(app._shell_runtime, '_execute', lambda _: None)
    devices = registry(app); offer = devices.invite()
    key = base64.b64encode(b'z'*32).decode()
    pair = devices.pair(offer['invite_id'],offer['invite'],key,'Phone')
    devices.approve(pair['device_id'],{**scope,'dot_id':actor['dot_id'],
        'actions':['message_send','message_request_status','message_list']})
    claim = devices.claim(pair['device_id'],key)
    def mobile(action, **fields):
        return gateway_call(app,{'method':'request','public_key':key,'device_id':pair['device_id'],
            'credential':claim['credential'],'request':{**scope,'dot_id':actor['dot_id'],
                'conversation_id':conversation['conversation_id'],'action':action,**fields}})
    intent = uuid.uuid4().hex
    first = mobile('message_send',content='Exactly once',request_key=intent)
    assert mobile('message_send',content='Exactly once',request_key=intent)==first
    observed = mobile('message_request_status',request_key=intent)['value']
    assert observed['found'] and observed['resent'] is False
    assert observed['message']['message_id']==first['value']['message_id']
