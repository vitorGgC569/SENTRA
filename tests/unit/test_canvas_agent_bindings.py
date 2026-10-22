import base64
import hashlib
import json
import sqlite3

import pytest
from sentra_canvas.agent_bindings import AgentBindings
from sentra_cli.canvas_binding import read_binding
from sentra_cli.authority_environment import provider_child_environment


@pytest.fixture
def bindings(tmp_path,monkeypatch):
    monkeypatch.setattr('sentra_canvas.agent_bindings.protect_secret',
        lambda value:'dpapi:'+base64.b64encode(value.encode()).decode())
    monkeypatch.setattr('sentra_canvas.agent_bindings.unprotect_secret',
        lambda value:base64.b64decode(value[6:]).decode())
    return AgentBindings(tmp_path,'owner')


def proof(token,**fields):
    return {'workspace_id':'workspace','terminal_id':'terminal','process_live':True,
        'pid':100,'runtime_id':'daemon-runtime','agent_token_sha256':hashlib.sha256(token.encode()).hexdigest(),**fields}


def test_only_exact_live_daemon_identity_recovers_the_limited_credential(bindings):
    token='terminal-specific-secret-abcde12345'
    path=bindings.reserve('workspace','terminal',token)
    assert token.encode() not in bindings.path.read_bytes()
    assert bindings.recover(proof(token,process_live=False)) is None
    assert bindings.recover(proof('another-token')) is None
    assert bindings.recover(proof(token,workspace_id='other')) is None
    assert bindings.recover(proof(token))==token
    assert bindings.recover(proof(token,pid=101)) is None
    assert bindings.recover(proof(token,runtime_id='another-runtime')) is None
    assert AgentBindings(bindings.root.parent,'other-owner').recover(proof(token)) is None
    assert not path.exists()


def test_signed_descriptor_has_no_token_and_checks_scope_pid_reuse_and_tamper(bindings,monkeypatch):
    token='terminal-specific-secret-abcde12345';workspace=str(bindings.root)
    path=bindings.reserve('workspace','terminal',token)
    bindings.publish('terminal',token,'workspace',workspace,6543,'broker-runtime')
    assert token not in path.read_text()
    assert read_binding(path,token,workspace)['port']==6543
    with pytest.raises(PermissionError):read_binding(path,token,'other-workspace')
    monkeypatch.setattr('sentra_cli.canvas_binding.process_stamp',lambda _:'reused-pid')
    with pytest.raises(PermissionError,match='process'):read_binding(path,token,workspace)
    monkeypatch.undo()
    value=json.loads(path.read_text());value['port']=6544
    path.write_text(json.dumps(value))
    with pytest.raises(PermissionError,match='signature'):read_binding(path,token,workspace)


def test_revocation_removes_endpoint_and_prevents_restoration(bindings):
    token='terminal-specific-secret-abcde12345'
    path=bindings.reserve('workspace','terminal',token)
    bindings.publish('terminal',token,'workspace','path',6543,'runtime')
    bindings.revoke('terminal')
    assert not path.exists() and bindings.recover(proof(token)) is None
    with pytest.raises(PermissionError):bindings.publish('terminal',token,'workspace','path',6544,'runtime')


def test_future_binding_schema_refuses_downgrade(tmp_path):
    root=tmp_path/'agent-bindings';root.mkdir()
    with sqlite3.connect(root/'bindings.sqlite3') as db:db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError,match='newer'):AgentBindings(tmp_path,'owner')


def test_children_do_not_inherit_host_terminal_capabilities(tmp_path):
    inherited={'PATH':'normal','SENTRA_CANVAS_AGENT_BINDING_FILE':'private.json',
        'SENTRA_CANVAS_AGENT_TOKEN':'private-token','SENTRA_CANVAS_AGENT_PORT':'6543'}
    assert provider_child_environment(tmp_path,inherited)=={'PATH':'normal'}
