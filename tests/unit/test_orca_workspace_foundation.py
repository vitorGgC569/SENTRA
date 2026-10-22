import base64
import pytest
from sentra_canvas.pty_daemon import PtyHost,OutputCache,UncertainPTY
from sentra_canvas.workspace_contract import delivery_projection
from sentra_canvas.mobile_devices import DeviceRegistry


class FakePTY:
    launches=0
    def __init__(self,argv,cwd,on_output,env=None):
        FakePTY.launches+=1;self.pid=100+FakePTY.launches;self.exit=None;self.writes=[];on_output(b'ready\n')
    def write(self,data):self.writes.append(data)
    def poll(self):return self.exit
    def close(self,**kwargs):self.exit=0
    def resize(self,*args):pass


def test_daemon_deduplicates_effect_and_rejects_changed_payload(tmp_path):
    host=PtyHost(tmp_path,FakePTY)
    fields={'workspace_id':'w1','terminal_id':'t1','argv':['example'],'cwd':str(tmp_path)}
    first=host.dispatch('create',fields,'create:t1')
    assert host.dispatch('create',fields,'create:t1')==first
    assert len(host.sessions)==1
    with pytest.raises(ValueError):host.dispatch('create',{**fields,'argv':['other']},'create:t1')
    data={'workspace_id':'w1','terminal_id':'t1','data':base64.b64encode(b'run\r').decode()}
    assert host.dispatch('write',data,'write:key1')['model_completed'] is False
    host.dispatch('write',data,'write:key1')
    assert host.sessions['t1']['pty'].writes==[b'run\r']
    with pytest.raises(PermissionError):host.dispatch('output',{'workspace_id':'w2','terminal_id':'t1'})
    host.close()
    restarted=PtyHost(tmp_path,FakePTY)
    with pytest.raises(UncertainPTY):restarted.dispatch('create',fields,'create:t1')
    assert not restarted.sessions
    restarted.close()


def test_partial_write_is_not_replayed(tmp_path):
    class Fails(FakePTY):
        def write(self,data):super().write(data);raise OSError('lost confirmation')
    host=PtyHost(tmp_path,Fails)
    host.dispatch('create',{'workspace_id':'w','terminal_id':'t','argv':['x'],'cwd':str(tmp_path)},'create:terminal')
    fields={'workspace_id':'w','terminal_id':'t','data':base64.b64encode(b'x').decode()}
    with pytest.raises(OSError):host.dispatch('write',fields,'write:original')
    with pytest.raises(UncertainPTY):host.dispatch('write',fields,'write:original')
    assert host.sessions['t']['pty'].writes==[b'x']
    host.close()


def test_drain_never_closes_existing_processes(tmp_path):
    host = PtyHost(tmp_path, FakePTY)
    fields = {'workspace_id':'w','terminal_id':'t','argv':['x'],'cwd':str(tmp_path)}
    host.dispatch('create', fields, 'create:drain-test')
    assert host.dispatch('drain', {})['live_sessions'] == 1
    assert host.dispatch('health', {})['state'] == 'draining'
    with pytest.raises(ValueError):
        host.dispatch('stop_when_idle', {})
    with pytest.raises(ValueError):
        host.dispatch('create', {**fields, 'terminal_id':'new'}, 'create:while-draining')
    assert host.sessions['t']['pty'].poll() is None
    host.dispatch('write', {'workspace_id':'w','terminal_id':'t','data':base64.b64encode(b'x').decode()}, 'write:during-drain')
    host.dispatch('close', {'workspace_id':'w','terminal_id':'t'}, 'close:drain-test')
    assert host.dispatch('stop_when_idle', {})['safe_to_stop']
    host.close()


def test_cache_utf8_bounds_and_explicit_gap():
    cache=OutputCache(12)
    cache.append('a','😀😀😀😀')
    assert cache.size<=12
    value=cache.read('a',0)
    assert value['text']=='😀😀😀' and value['base']==1 and value['truncated']
    cache.append('b','abcdefghijkl')
    assert cache.size<=12 and cache.read('a',0)['truncated']


def test_transport_delivery_never_counts_as_model_completion():
    for state in ['SENT','ACCEPTED','RUNNING','UNCERTAIN','completed','unknown']:
        assert delivery_projection({'status':state})['completed'] is False
    assert delivery_projection({'state':'UNCERTAIN'})['requires_reconciliation']
    assert delivery_projection({'state':'SUCCEEDED'})['completed']


def test_failed_dag_is_settled_but_never_successful():
    from sentra_runtime.orchestration_observation import convergence
    assert convergence([])['phase']=='empty'
    assert convergence([{'status':'failed'}])['all_settled']
    assert not convergence([{'status':'failed'}])['all_succeeded']
    assert convergence([{'status':'blocked'}])['phase']=='blocked'
    assert convergence([{'status':'completed'},{'state':'SUCCEEDED'}])['all_succeeded']


def test_packaged_entry_routes_daemon_before_injecting_ui_arguments(monkeypatch):
    from sentra_canvas import native_entry
    monkeypatch.setattr(native_entry,'canvas_main',lambda arguments:arguments)
    monkeypatch.setattr(native_entry,'root_dir',lambda:pytest.fail('daemon must not discover UI root'))
    assert native_entry.main(['--pty-daemon','isolated-state'])==['--pty-daemon','isolated-state']


def test_pairing_is_single_use_owner_approved_and_revocable(tmp_path,monkeypatch):
    # Test only the registry; production secrets still use DPAPI/Keychain.
    monkeypatch.setattr('sentra_remote.secrets.protect_secret',lambda v:'protected:'+v)
    monkeypatch.setattr('sentra_remote.secrets.unprotect_secret',lambda v:v.removeprefix('protected:'))
    devices=DeviceRegistry(tmp_path/'devices.db','alice')
    offer=devices.invite();key=base64.b64encode(b'x'*32).decode()
    pair=devices.pair(offer['invite_id'],offer['invite'],key,'Phone')
    with pytest.raises(PermissionError):devices.pair(offer['invite_id'],offer['invite'],key,'Second')
    assert devices.claim(pair['device_id'],key)=={'state':'pending'}
    scope={'project_id':'project','space_id':'space','dot_id':'dot','actions':['workspace_inventory']}
    with pytest.raises(PermissionError):DeviceRegistry(tmp_path/'devices.db','bob').approve(pair['device_id'],scope)
    devices.approve(pair['device_id'],scope)
    with pytest.raises(PermissionError):devices.claim(pair['device_id'],base64.b64encode(b'y'*32).decode())
    claim=devices.claim(pair['device_id'],key)
    assert devices.authenticate(pair['device_id'],claim['credential'],key)==scope
    devices.revoke(pair['device_id'])
    with pytest.raises(PermissionError):devices.authenticate(pair['device_id'],claim['credential'],key)
