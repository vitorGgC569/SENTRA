import uuid
import os
from pathlib import Path
import pytest
from test_shell_dot_features import shell, dot


def execute(app, scope, profile, cap, args, oid=None):
    oid = oid or 'op-access-test-' + uuid.uuid4().hex
    return app.center_execute(scope['project_id'], profile['work_item_id'], profile['machine_id'], cap, oid, args, oid)


def test_full_access_writes_outside_project_and_runs_real_shell(shell, tmp_path):
    app, server, scope, call = shell
    agent = dot(call, 'Computer')
    cid = call('conversation_create', dot_id=agent['dot_id'])['conversation_id']
    profile = call('access_set', conversation_id=cid, mode='full')
    outside = tmp_path / 'outside-access.txt'
    root = Path(app.store.workspace(scope['project_id'])['path'])
    assert not outside.is_relative_to(root)
    result = execute(app, scope, profile, 'computer:file.write', {'action': 'write', 'path': str(outside), 'content': 'first'})
    assert result['state'] == 'SUCCEEDED', result
    assert outside.read_text() == 'first'
    command = "[IO.File]::WriteAllText('" + str(outside).replace("'", "''") + "', 'terminal')"
    result = execute(app, scope, profile, 'computer:execute', {'command': command, 'cwd': str(tmp_path)})
    assert result['state'] == 'SUCCEEDED' and result['evidence']['exit_code'] == 0, result
    assert outside.read_text() == 'terminal'
    binary = tmp_path / 'outside-binary.bin'
    result = execute(app, scope, profile, 'computer:file.write', {'action': 'write', 'path': str(binary), 'base64': '/wABAg=='})
    assert result['state'] == 'SUCCEEDED' and binary.read_bytes() == b'\xff\x00\x01\x02'
    execute(app, scope, profile, 'computer:file.delete', {'action': 'delete', 'path': str(outside)})
    assert not outside.exists()
    assert call('access_status', conversation_id=cid)['mode'] == 'full'


def test_approval_executes_exact_requested_action_and_downgrade_blocks_old_grant(shell, tmp_path):
    app, server, scope, call = shell
    agent = dot(call, 'Approvals')
    cid = call('conversation_create', dot_id=agent['dot_id'])['conversation_id']
    full = call('access_set', conversation_id=cid, mode='full')
    profile = call('access_set', conversation_id=cid, mode='ask')
    outside = tmp_path / 'ask.txt'
    with pytest.raises(PermissionError):
        execute(app, scope, full, 'computer:file.write', {'action': 'write', 'path': str(outside), 'content': 'stale'})
    oid = 'op-access-request-' + uuid.uuid4().hex
    with pytest.raises(PermissionError):
        execute(app, scope, profile, 'computer:file.write', {'action': 'write', 'path': str(outside), 'content': 'approved'}, oid)
    assert not outside.exists()
    assert call('access_status', conversation_id=cid)['requests'][0]['operation_id'] == oid
    approved = call('access_approve', conversation_id=cid, target_operation_id=oid)
    assert approved['result']['state'] == 'SUCCEEDED', approved
    assert outside.read_text() == 'approved'
    observed = execute(app, scope, profile, 'computer:file.write', {'action': 'write', 'path': str(outside), 'content': 'approved'}, oid)
    assert observed['state'] == 'SUCCEEDED' and outside.read_text() == 'approved'
    assert not call('access_status', conversation_id=cid)['requests']
    other = call('conversation_create', dot_id=agent['dot_id'])['conversation_id']
    assert call('access_status', conversation_id=other)['mode'] == 'ask'


def test_auto_approves_project_edit_but_requests_delete_and_external_write(shell, tmp_path):
    app, server, scope, call = shell
    agent = dot(call, 'Auto')
    cid = call('conversation_create', dot_id=agent['dot_id'])['conversation_id']
    profile = call('access_set', conversation_id=cid, mode='auto')
    path = Path(app.store.workspace(scope['project_id'])['path']) / 'inside.txt'
    result = execute(app, scope, profile, 'computer:file.write', {'action': 'write', 'path': str(path), 'content': 'ok'})
    assert result['state'] == 'SUCCEEDED', result
    with pytest.raises(PermissionError):
        execute(app, scope, profile, 'computer:file.delete', {'action': 'delete', 'path': str(path)})
    assert path.exists()
    with pytest.raises(PermissionError):
        execute(app, scope, profile, 'computer:file.write', {'action': 'write', 'path': str(tmp_path / 'external.txt'), 'content': 'no'})
    with pytest.raises(PermissionError):
        execute(app, scope, profile, 'computer:execute', {'command': 'Get-Content ..\\external.txt', 'cwd': str(path.parent)})
    assert len(call('access_status', conversation_id=cid)['requests']) == 3


@pytest.mark.skipif(os.name != 'nt', reason='Windows desktop interpreter')
def test_desktop_pythonw_launches_console_cli(monkeypatch, tmp_path):
    from sentra_canvas.service import Canvas
    import sys
    window = tmp_path / 'pythonw.exe'
    console = tmp_path / 'python.exe'
    window.touch(); console.touch()
    monkeypatch.setattr(sys, 'executable', str(window))
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    command = object.__new__(Canvas)._cli_command(['--model', 'sentra/test-one'])
    assert command[0] == str(console)
    assert command[1] == '-u'


def test_custom_read_only_removes_write_and_command_authority(shell, tmp_path):
    app, server, scope, call = shell
    agent = dot(call, 'ReadOnly')
    cid = call('conversation_create', dot_id=agent['dot_id'])['conversation_id']
    profile = call('access_set', conversation_id=cid, mode='custom', scope='computer', approval='never', capabilities=['computer:file.read'])
    existing = tmp_path / 'existing.txt'
    existing.write_text('keep')
    result = execute(app, scope, profile, 'computer:file.read', {'action': 'read', 'path': str(existing)})
    assert result['state'] == 'SUCCEEDED' and result['evidence']['content'] == 'keep'
    with pytest.raises(PermissionError):
        execute(app, scope, profile, 'computer:file.delete', {'action': 'delete', 'path': str(existing)})
    with pytest.raises(PermissionError):
        execute(app, scope, profile, 'computer:execute', {'command': 'Write-Output forbidden'})
    assert existing.read_text() == 'keep'


def test_owner_conversation_starts_with_effective_ask_profile(shell, tmp_path):
    app, server, scope, call = shell
    agent = dot(call, 'Default')
    cid = call('conversation_create', dot_id=agent['dot_id'])['conversation_id']
    profile = call('access_status', conversation_id=cid)
    assert profile['mode'] == 'ask' and profile['work_item_id']
    with pytest.raises(PermissionError):
        execute(app, scope, profile, 'computer:file.write', {'action': 'write', 'path': str(tmp_path / 'default.txt'), 'content': 'wait'})
    assert not (tmp_path / 'default.txt').exists()
