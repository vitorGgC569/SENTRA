import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from sentra_cli.canvas import CanvasBridge
from sentra_canvas.agent_bindings import AgentBindings


def test_refreshing_signed_endpoint_never_retries_a_request_after_possible_effect(tmp_path,monkeypatch):
    token='terminal-limited-capability-1234567890';observed=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.headers['Authorization']=='Bearer '+token
            observed.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            # The physical receiver recorded the effect, but its confirmation is lost.
            if len(observed)==1:self.close_connection=True;return
            body=json.dumps({'confirmed':True}).encode()
            self.send_response(200);self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr('sentra_canvas.agent_bindings.protect_secret',lambda value:'dpapi:fake')
    registry=AgentBindings(tmp_path,'owner');path=registry.reserve('ws','terminal',token)
    registry.publish('terminal',token,'ws',str(tmp_path),server.server_port,'runtime-one')
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_TOKEN',token)
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_PORT','1')
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_BINDING_FILE',str(path))
    bridge=CanvasBridge(SimpleNamespace(workspace=str(tmp_path)))
    try:
        with pytest.raises(Exception):bridge._request({'action':'machine_execute','request_key':'original'})
        assert len(observed)==1
        registry.publish('terminal',token,'ws',str(tmp_path),server.server_port,'runtime-two')
        assert len(observed)==1
        assert bridge._request({'action':'context','workspace':str(tmp_path)})=={'confirmed':True}
        assert [row['action'] for row in observed]==['machine_execute','context']
    finally:server.shutdown();server.server_close();thread.join(5)


@pytest.mark.parametrize('action,deadline',[('context',30),('machine_list',30),('dispatch',130),('coordinator_intent',130),('checkpoint',30)])
def test_shell_deadlines_keep_one_request_identity_and_never_retry(tmp_path,monkeypatch,action,deadline):
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_TOKEN','t'*40);monkeypatch.setenv('SENTRA_CANVAS_AGENT_PORT','12345')
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_SCOPE','shell');seen=[]
    class Opener:
        def open(self,request,timeout):
            seen.append((json.loads(request.data),timeout));raise TimeoutError('confirmation lost')
    monkeypatch.setattr('urllib.request.build_opener',lambda *_:Opener())
    bridge=CanvasBridge(SimpleNamespace(workspace=str(tmp_path)))
    original={'action':action,'workspace':str(tmp_path),'request_key':'same-original','value':'{}'}
    with pytest.raises(TimeoutError):bridge._request(original)
    assert seen==[(original,deadline)]
