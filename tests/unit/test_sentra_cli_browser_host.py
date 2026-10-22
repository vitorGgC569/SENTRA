import io
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from sentra_cli.client import ModelClient
from sentra_cli.config import CLIConfig


def test_turn_authority_token_uses_product_state(tmp_path: Path):
    token_dir = tmp_path / "web-models"
    token_dir.mkdir(parents=True)
    expected = "t" * 64
    (token_dir / "turn-authority.token").write_text(expected + "\n", encoding="utf-8")
    fake_paths = MagicMock(state_dir=tmp_path)
    with patch.dict("os.environ", {"SENTRA_TURN_AUTHORITY_TOKEN": ""}, clear=False), patch(
        "sentra_remote.product.ProductPaths.default", return_value=fake_paths
    ):
        assert ModelClient._turn_authority_token() == expected


def test_spawn_browser_host_injects_sentra_authority(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path)
    client = ModelClient(cfg)
    executable = tmp_path / "Codex Web GPT.exe"
    executable.write_bytes(b"test")
    process = MagicMock(pid=4321)
    process.poll.return_value = None
    with patch.object(client, "_browser_host_ready", side_effect=[False, True]), patch.object(
        client, "_browser_host_executable_path", return_value=executable
    ), patch.object(
        client, "_browser_relay_token_file", return_value=None
    ), patch.object(
        client, "_turn_authority_token", return_value="a" * 64
    ), patch("sentra_cli.client.subprocess.Popen", return_value=process) as popen:
        result = client._spawn_browser_host()
    assert result == "browser-host pid=4321"
    env = popen.call_args.kwargs["env"]
    assert env["SENTRA_BROWSER_HOST_ONLY"] == "1"
    assert env["SENTRA_MANAGED_TUNNEL"] == "1"
    assert env["SENTRA_TURN_AUTHORITY_TOKEN"] == "a" * 64
    assert env["SENTRA_WEB_GATEWAY_URL"] == cfg.gateway_url

def test_pid_running_recognizes_current_process():
    import os
    assert ModelClient._pid_running(os.getpid()) is True

def test_wait_browser_host_turn_ready_waits_through_session_refresh(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path, gateway_start_timeout_s=5.0)
    client = ModelClient(cfg)
    descriptor = tmp_path / "launcher-browser.json"
    descriptor.write_text(
        '{"control":{"endpoint":"http://127.0.0.1:62080",'
        '"token":"' + ('x' * 48) + '"}}',
        encoding="utf-8",
    )
    busy = urllib.error.HTTPError(
        "http://127.0.0.1:62080/v1/session/inspect",
        400,
        "bad request",
        {},
        io.BytesIO(
            b'{"error":"ChatGPT browser is busy with session refresh"}'
        ),
    )
    response = MagicMock()
    response.status = 200
    response.read.return_value = (
        b'{"authenticated":true,"temporary":true,"url":"https://chatgpt.com/"}'
    )
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    with patch.object(
        client, "_browser_descriptor_path", return_value=descriptor
    ), patch.object(
        client, "_provider_http",
        side_effect=[busy, response],
    ), patch("sentra_cli.client.time.sleep", return_value=None):
        ready, detail = client._wait_browser_host_turn_ready(timeout_s=1.0)
    assert ready is True
    assert detail == "ready"


@pytest.mark.parametrize('endpoint',[
    'http://127.0.0.1:62080@evil.invalid', 'http://127.0.0.1:62080/other',
    'http://127.0.0.1:62080?secret=bad', 'http://127.0.0.1:notaport',
])
def test_session_probe_never_transmits_owner_token_to_untrusted_descriptor(tmp_path,endpoint):
    import json
    client=ModelClient(CLIConfig(workspace=tmp_path))
    descriptor=tmp_path/'browser.json';descriptor.write_text(json.dumps({'control':{'endpoint':endpoint,'token':'x'*48}}))
    with patch.object(client,'_browser_descriptor_path',return_value=descriptor),patch.object(client,'_provider_http') as transport:
        ready,_=client._wait_browser_host_turn_ready(timeout_s=.001)
    assert not ready;transport.assert_not_called()


def test_session_refresh_uses_real_loopback_http_and_rechecks_admission(tmp_path):
    import json,threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    calls=[];checkpoints=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            calls.append((self.path,self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            body=json.dumps({'error':'busy with session refresh'} if len(calls)==1 else {'authenticated':True,'temporary':True}).encode()
            self.send_response(409 if len(calls)==1 else 200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    descriptor=tmp_path/'browser.json';descriptor.write_text(json.dumps({'control':{'endpoint':f'http://127.0.0.1:{server.server_port}','token':'x'*48}}))
    client=ModelClient(CLIConfig(workspace=tmp_path));client.on_before_http=lambda provider:checkpoints.append(provider)
    try:
        with patch.object(client,'_browser_descriptor_path',return_value=descriptor):assert client._wait_browser_host_turn_ready(timeout_s=3)==(True,'ready')
        assert calls==[('/v1/session/inspect','Bearer '+'x'*48,{'detectCapabilities':False})]*2
        assert len(checkpoints)==2
    finally:server.shutdown();server.server_close();thread.join(2)
