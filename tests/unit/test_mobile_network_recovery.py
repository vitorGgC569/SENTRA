import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from sentra_canvas.mobile_devices import DeviceRegistry
from sentra_canvas.mobile_network import host_secret, host_status, local_ipv4, atomic_json
from sentra_canvas.mobile_host import supervise_broker


@pytest.mark.skipif(os.name != 'nt', reason='real Windows DPAPI identity adoption')
def test_host_key_survives_restarts_and_adopts_existing_login_identity(tmp_path):
    from sentra_remote.secrets import protect_secret
    original=base64.b64encode(b'x'*32).decode()
    path=tmp_path/'mobile-key.protected'
    path.write_text(protect_secret(original))
    before=path.read_bytes()
    assert host_secret(tmp_path)==original==host_secret(tmp_path)
    assert path.read_bytes()==before
    path.write_text('damaged identity')
    with pytest.raises(ValueError):host_secret(tmp_path)
    assert path.read_text()=='damaged identity'


@pytest.mark.skipif(os.name != 'nt', reason='real Windows DPAPI key creation')
def test_new_host_key_is_os_protected_and_stable(tmp_path):
    key=host_secret(tmp_path)
    assert host_secret(tmp_path)==key
    stored=(tmp_path/'mobile-key.protected').read_text()
    assert key not in stored and 'dpapi:' in stored


def test_claim_confirmation_can_be_recovered_but_not_after_revocation(tmp_path,monkeypatch):
    monkeypatch.setattr('sentra_remote.secrets.protect_secret',lambda v:'protected:'+v)
    monkeypatch.setattr('sentra_remote.secrets.unprotect_secret',lambda v:v.removeprefix('protected:'))
    path=tmp_path/'devices.db';devices=DeviceRegistry(path,'owner')
    invite=devices.invite();key=base64.b64encode(b'x'*32).decode()
    pair=devices.pair(invite['invite_id'],invite['invite'],key,'Phone')
    scope={'project_id':'p','space_id':'s','dot_id':'d','actions':['workspace_inventory']}
    devices.approve(pair['device_id'],scope)
    first=devices.claim(pair['device_id'],key)
    assert DeviceRegistry(path,'owner').claim(pair['device_id'],key)==first
    with pytest.raises(PermissionError):devices.claim(pair['device_id'],base64.b64encode(b'y'*32).decode())
    assert devices.authenticate(pair['device_id'],first['credential'],key)==scope
    with devices.db() as db:db.execute('UPDATE mobile_claim_receipts SET expires=0')
    with pytest.raises(PermissionError):devices.claim(pair['device_id'],key)
    # Expiring the delivery receipt never expires the approved login itself.
    assert devices.authenticate(pair['device_id'],first['credential'],key)==scope
    devices.revoke(pair['device_id'])
    with pytest.raises(PermissionError):devices.claim(pair['device_id'],key)
    with pytest.raises(PermissionError):devices.authenticate(pair['device_id'],first['credential'],key)


def test_only_supported_lan_families_and_ranges_are_advertised():
    for address in ('10.0.0.1','192.168.0.8','172.31.4.9','127.0.0.1'):assert local_ipv4(address)
    for address in ('0.0.0.0','::1','fe80::1','169.254.1.2','203.0.113.5','224.0.0.1'):assert not local_ipv4(address)


def test_descriptor_must_match_live_listener_identity(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        key=base64.b64encode(b'x'*32).decode()
        def do_GET(self):
            assert self.headers.get('Authorization') is None
            body=json.dumps({'ok':True,'protocol_version':1,'public_key':self.key,
                'endpoint':endpoint,'broker_available':True}).encode()
            self.send_response(200);self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    endpoint=f'ws://127.0.0.1:{server.server_port}/sentra/mobile/v1'
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        atomic_json(tmp_path/'mobile-host.json',{'endpoint':endpoint,'public_key':Handler.key})
        state=host_status(tmp_path)
        assert state['available'] and state['lan'] is False and state['addresses']==['127.0.0.1']
        assert 'bearer' not in state and 'secret_key' not in state
        Handler.key='changed-host'
        assert not host_status(tmp_path)['available']
    finally:server.shutdown();server.server_close();worker.join(5)
    assert not host_status(tmp_path)['available']


def test_supervisor_updates_future_requests_and_reports_broker_downtime(monkeypatch,tmp_path):
    import io
    old=SimpleNamespace(server_port=10001,secret='old',runtime_id='before')
    new=SimpleNamespace(server_port=10002,secret='new',runtime_id='after')
    endpoints=iter([None,new]);polls=iter([None,None,0]);pipe=io.StringIO()
    process=SimpleNamespace(stdin=pipe,poll=lambda:next(polls))
    monkeypatch.setattr('sentra_canvas.mobile_host.time.sleep',lambda _:None)
    monkeypatch.setattr('sentra_canvas.mobile_host.read_endpoint',lambda _:next(endpoints))
    supervise_broker(process,tmp_path,old)
    messages=[json.loads(line) for line in pipe.getvalue().splitlines()]
    assert messages[0]=={'type':'broker_update','available':False}
    assert messages[1]['broker']=='http://127.0.0.1:10002' and messages[1]['runtime_id']=='after'
    assert all('request' not in item for item in messages)
