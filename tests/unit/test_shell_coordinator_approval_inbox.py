"""Durable owner consent requests never implicitly grant or replay coordinator actions."""
import uuid
import pytest
from sentra_runtime.coordinator_approvals import CoordinatorApprovalInbox
from test_shell_dot_features import shell, dot
from test_sentra_runtime_canvas_center_http import request


def test_pending_approval_is_owner_scoped_persistent_and_explicitly_rejected(shell):
    app, server, scope, call = shell
    member = dot(call, 'Coordinator')
    conversation = call('conversation_create', dot_id=member['dot_id'])
    owner = app._runtime().owner
    inbox = CoordinatorApprovalInbox(app._shell_service(), owner)
    approval = 'coordinator-' + uuid.uuid4().hex
    kwargs = dict(project_id=scope['project_id'], space_id=scope['space_id'],
        conversation_id=conversation['conversation_id'], parent_operation_id='not-live',
        work_item_id='not-live', agent_id=member['agent_id'], approval_id=approval,
        capability='canvas.coordinator.dot_create',
        intent={'kind':'create_dot','name':'Terminal_Teste'})
    inbox.record(**kwargs)
    inbox.record(**kwargs)
    view = call('coordinator_approval_list')
    matching = [v for v in view['items'] if v['approval_id'] == approval]
    assert len(matching) == 1
    assert matching[0]['activity'] == 'expired'
    assert matching[0]['summary']['name'] == 'Terminal_Teste'
    assert matching[0]['automatic_execution'] is False
    assert 'password' not in str(view)
    rejected = call('coordinator_approval_reply', approval_id=approval, answer='reject')
    assert rejected['state'] == 'rejected'
    assert not call('coordinator_approval_list')['items']


def test_approval_cannot_grant_or_cross_project_by_forging_fields(shell):
    app, server, scope, call = shell
    member = dot(call, 'Coordinator')
    conversation = call('conversation_create', dot_id=member['dot_id'])
    inbox = CoordinatorApprovalInbox(app._shell_service(), app._runtime().owner)
    approval = 'coordinator-' + uuid.uuid4().hex
    inbox.record(project_id=scope['project_id'],space_id=scope['space_id'],
        conversation_id=conversation['conversation_id'],parent_operation_id='no-active-operation',
        work_item_id='no-work-item',agent_id=member['agent_id'],approval_id=approval,
        capability='canvas.coordinator.dot_create',intent={'kind':'create_dot','name':'Child'})
    before = app._shell_service().authorization.list_grants(app._runtime().owner,
        principal_type='agent',principal_id=member['agent_id'])['items']
    code, _ = request(server, '/api/shell/bridge', json_body={
        'action':'coordinator_approval_reply',**scope,
        'approval_id':approval,'answer':'approve', 'capability':'computer:execute',
        'request_key':uuid.uuid4().hex})
    assert code != 200
    code, _ = request(server, '/api/shell/bridge', json_body={
        'action':'coordinator_approval_reply',**scope,
        'approval_id':approval,'answer':'approve','request_key':uuid.uuid4().hex})
    assert code != 200
    assert len(call('coordinator_approval_list')['items']) == 1
    after = app._shell_service().authorization.list_grants(app._runtime().owner,
        principal_type='agent',principal_id=member['agent_id'])['items']
    assert {grant['grant_id'] for grant in after} == {grant['grant_id'] for grant in before}


def test_center_decision_recovers_original_receipt_without_reply_or_grant(shell, monkeypatch):
    from test_workspace_request_recovery import selector
    app, server, scope, call = shell
    member = dot(call, 'Receipt coordinator')
    cid = call('conversation_create', dot_id=member['dot_id'])['conversation_id']
    other = call('conversation_create', dot_id=member['dot_id'])['conversation_id']
    inbox = CoordinatorApprovalInbox(app._shell_service(), app._runtime().owner)
    approval = 'coordinator-' + uuid.uuid4().hex
    inbox.record(project_id=scope['project_id'], space_id=scope['space_id'],
        conversation_id=cid, parent_operation_id='not-live', work_item_id='not-live',
        agent_id=member['agent_id'], approval_id=approval,
        capability='canvas.coordinator.dot_create', intent={'kind':'create_dot','name':'Child'})
    body = {'action':'coordinator_approval_reply', **scope, 'approval_id':approval,
        'answer':'reject', 'request_key':uuid.uuid4().hex}
    assert app.shell_bridge(body)['value']['state'] == 'rejected'
    # Simulate the first response being unavailable to the renderer. Inspection
    # must work even after the item disappeared from the pending inbox.
    assert not call('coordinator_approval_list')['items']
    monkeypatch.setattr(CoordinatorApprovalInbox, 'mark',
        lambda *_a, **_kw: pytest.fail('inspection dispatched a decision again'))
    read = call('conversation_permission_status', conversation_id=cid, selector=selector(body))
    assert read['resolved'] and read['result']['state'] == 'rejected'
    assert read['request_key'] == body['request_key'] and read['automatic_retry'] is False
    assert request(server, '/api/shell/bridge', json_body={
        'action':'conversation_permission_status', **scope,
        'conversation_id':other, 'selector':selector(body)})[0] == 403
