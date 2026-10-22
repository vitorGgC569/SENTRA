import hashlib,json,sys
from pathlib import Path
import pytest
import threading,time
from scripts.commander.stage_mobile import FILES,validate_mobile_runtime
from scripts.commander.stage_terminal import validate_terminal_runtime,inventory
from sentra_canvas.instance_lock import InstanceLock
from sentra_canvas import mobile_host


def mobile(root):
    root.mkdir()
    for name in FILES:
        if name!='runtime.json':(root/name).write_bytes(('fixture '+name).encode())
    manifest={'schema':1,'protocol_version':1,'node_version':'v24.20.0',
              'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in FILES if name!='runtime.json'}}
    (root/'runtime.json').write_text(json.dumps(manifest),encoding='utf-8')
    return root


def test_mobile_runtime_requires_exact_licensed_hash_inventory(tmp_path):
    root=mobile(tmp_path/'sentra-mobile');assert validate_mobile_runtime(root)['schema']==1
    (root/'gateway.mjs').write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='integrity'):validate_mobile_runtime(root)


def test_mobile_runtime_refuses_unknown_files_and_missing_notices(tmp_path):
    root=mobile(tmp_path/'sentra-mobile');(root/'extra.js').touch()
    with pytest.raises(ValueError,match='Unexpected'):validate_mobile_runtime(root)
    (root/'extra.js').unlink();(root/'THIRD_PARTY_NOTICES.txt').unlink()
    with pytest.raises(ValueError,match='Unexpected'):validate_mobile_runtime(root)


def test_terminal_runtime_seals_read_only_engine_sources_and_dependencies(tmp_path):
    names=['src/worker.mjs','dist/engine.cjs','vendor/orca/LICENSE',
           'node_modules/@xterm/headless/lib-headless/xterm-headless.js',
           'node_modules/@xterm/addon-serialize/lib/addon-serialize.js',
           'node_modules/@xterm/addon-unicode11/lib/addon-unicode11.js']
    for name in names:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name,encoding='utf-8')
    hashes=inventory(tmp_path)
    payload={'sources':{name:hashes[name] for name in names if name.startswith(('src/','vendor/'))},
             'runtime_dependencies':{name:hashes[name] for name in names if name.startswith('node_modules/')},
             'output':hashes['dist/engine.cjs']}
    build_id=hashlib.sha256(json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    (tmp_path/'dist/manifest.json').write_text(json.dumps({'version':2,'build_id':build_id,**payload}),encoding='utf-8')
    (tmp_path/'runtime.json').write_text(json.dumps({'schema':2,'engine_build_id':build_id,'files':inventory(tmp_path)}),encoding='utf-8')
    assert len(validate_terminal_runtime(tmp_path)['files'])==7
    (tmp_path/names[-1]).write_text('tampered',encoding='utf-8')
    with pytest.raises(ValueError,match='integrity'):validate_terminal_runtime(tmp_path)


def test_activation_never_replaces_an_owned_but_unobservable_gateway(tmp_path,monkeypatch):
    import scripts.commander.stage_mobile as stage
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(stage,'validate_mobile_runtime',lambda root:{})
    monkeypatch.setattr(mobile_host,'host_status_ready',lambda state:False)
    monkeypatch.setattr('sentra_canvas.process_lifetime.launch_independent',lambda *a,**kw:pytest.fail('duplicate launch'))
    owner=InstanceLock(tmp_path/'mobile-host.lock')
    try:
        with pytest.raises(RuntimeError,match='still owns'):mobile_host.start_installed_host(tmp_path)
    finally:owner.close()


def test_activation_reuses_ready_gateway_and_rejects_public_bind(tmp_path,monkeypatch):
    import scripts.commander.stage_mobile as stage
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(stage,'validate_mobile_runtime',lambda root:{})
    monkeypatch.setattr(mobile_host,'host_status_ready',lambda state:True)
    assert mobile_host.start_installed_host(tmp_path,'100.88.1.2')=={'started':False,'already_running':True}
    with pytest.raises(ValueError):mobile_host.start_installed_host(tmp_path,'8.8.8.8')


def test_stop_is_bound_to_one_generation_and_preserves_pairing_files(tmp_path):
    instance='a'*32;descriptor=tmp_path/'mobile-host.json'
    descriptor.write_text(json.dumps({'instance_id':instance}),encoding='utf-8')
    pairing=tmp_path/'mobile-key.protected';pairing.write_bytes(b'unchanged protected identity')
    (tmp_path/'mobile-stop.json').write_text(json.dumps({'instance_id':'b'*32}),encoding='utf-8')
    assert not mobile_host.stop_requested(tmp_path,instance)
    ready=threading.Event();done=threading.Event()
    def host():
        lease=InstanceLock(tmp_path/'mobile-host.lock');ready.set()
        try:
            deadline=time.monotonic()+3
            while not mobile_host.stop_requested(tmp_path,instance) and time.monotonic()<deadline:time.sleep(.01)
            descriptor.unlink()
        finally:lease.close();done.set()
    thread=threading.Thread(target=host);thread.start();assert ready.wait(2)
    try:assert mobile_host.stop_installed_host(tmp_path)=={'stopped':True,'pairings_preserved':True}
    finally:assert done.wait(3);thread.join()
    assert pairing.read_bytes()==b'unchanged protected identity'


def test_legacy_descriptor_cannot_authorize_signaling_a_pid(tmp_path):
    (tmp_path/'mobile-host.json').write_text(json.dumps({'pid':1234}),encoding='utf-8')
    with pytest.raises(RuntimeError,match='predates'):mobile_host.stop_installed_host(tmp_path)
    assert not (tmp_path/'mobile-stop.json').exists()
