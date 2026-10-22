from types import SimpleNamespace
import json
import pytest
from sentra_cli.canvas import CanvasBridge

@pytest.mark.parametrize('action',['create_agent','create_team','connect','dispatch'])
def test_shell_convenience_keeps_scoped_actor_envelope(monkeypatch,tmp_path,action):
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_SCOPE','shell')
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_TOKEN','x'*40)
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_PORT','1234')
    bridge=CanvasBridge(SimpleNamespace(workspace=tmp_path));sent=[]
    monkeypatch.setattr(bridge,'_request',lambda body:sent.append(body) or {'status':'waiting_approval'})
    result=json.loads(bridge.execute(action+'|bounded-value','same-request-key'))
    assert result['status']=='waiting_approval'
    assert sent==[{'action':action,'workspace':str(tmp_path),'value':'bounded-value','request_key':'same-request-key'}]

def test_legacy_terminal_bootstrap_stays_unavailable_in_shell(monkeypatch,tmp_path):
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_SCOPE','shell')
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_TOKEN','x'*40)
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_PORT','1234')
    with pytest.raises(PermissionError):CanvasBridge(SimpleNamespace(workspace=tmp_path)).execute('create_terminal|name','key')
