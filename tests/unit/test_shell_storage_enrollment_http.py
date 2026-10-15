"""Real owner HTTP/factory wiring; only the hypervisor and tiny VDI are fixtures."""
import uuid

import pytest

from test_shell_dot_features import shell
from test_shell_dot_vm import vm_scope, configure
from test_virtualbox_installation import client
from test_sentra_runtime_canvas_center_http import request
from sentra_canvas.shell_dot_vm import configure_virtualbox_machine


@pytest.fixture
def enrolled_scope(vm_scope, shell, tmp_path, monkeypatch):
    app, pid, call, service, params, root, other, ca, cb = vm_scope
    call('access_set', conversation_id=ca['conversation_id'], mode='full')
    configure(service, pid, params)
    folder = tmp_path / 'synthetic-hypervisor'; folder.mkdir()
    fake, unused, layout, disk, disk_id = client(folder, allocated=True, partitioned=True)
    (disk.parent / 'owned.vbox').write_text('<synthetic-vbox/>')
    attachment = fake.disk_attachments(unused)[0]
    legacy = disk.with_name('system-localiso2.vdi'); disk.rename(legacy)
    fake.disk_attachments = lambda binding: [{**attachment, 'location': str(legacy)}]
    service.store.patch(pid, root['dot_id'], base_folder=layout['base_folder'], name=layout['name'], disk_gb=1)
    cfg = service.store.get(pid, root['dot_id'])
    monkeypatch.setattr('sentra_executors.virtualbox_vm.VirtualBoxClient', lambda *args, **kwargs: fake)
    async def forget_registration():
        service.host._inventory.pop(cfg['machine_id'])
        service.host._factories.pop(cfg['machine_id'])
    service.host._call(forget_registration())
    configure_virtualbox_machine(service.host, workspace_id=pid, workspace_root=app.store.workspace(pid)['path'],
        agent_id=root['agent_id'], root_dot_id=root['dot_id'])
    app._shell_dot_vm = service
    # vm_scope's owner callback uses the real HTTP server from shell.
    return app, pid, call, service, params, root, cfg, fake, legacy, shell[1]


def test_owner_http_selects_review_scope_then_canonical_plan_and_replay(enrolled_scope):
    app, pid, call, service, params, root, cfg, fake, disk, server = enrolled_scope
    candidate = call('dot_vm_execute', **{k:v for k,v in params.items() if k != 'space_id'},
        arguments={'action':'storage.candidate'})
    assert candidate['state'] == 'SUCCEEDED', candidate
    evidence = candidate['evidence']
    assert evidence['applied'] is evidence['authorization_granted'] is False
    assert str(disk) not in str(evidence)
    key = 'owner-reviewed-storage-' + uuid.uuid4().hex
    envelope = {'action':'dot_vm_execute', 'project_id':pid, 'request_key':key, **params,
        'arguments':{'action':'storage.enroll','expected_candidate_sha256':evidence['candidate_sha256']}}
    denied, _ = request(server, '/api/shell/bridge', json_body=envelope, authorized=False)
    assert denied == 401 and 'storage_binding' not in service.store.get(pid, root['dot_id'])
    status, first = request(server, '/api/shell/bridge', json_body=envelope)
    assert status == 200, first
    assert first['ok'] and first['value']['state'] == 'SUCCEEDED', first
    assert request(server, '/api/shell/bridge', json_body=envelope) == (200, first)
    plan = call('dot_vm_execute', **{k:v for k,v in params.items() if k != 'space_id'},
        arguments={'action':'installation.plan'})
    assert plan['state'] == 'SUCCEEDED', plan
    assert plan['evidence']['disk']['storage_binding_sha256'] == evidence['candidate_sha256']
    assert not plan['evidence']['installed_os_verified']
    assert not fake.calls


def test_shared_agent_dispatch_cannot_install_owner_review_scope(enrolled_scope):
    app, pid, call, service, params, root, cfg, fake, disk, server = enrolled_scope
    candidate = call('dot_vm_execute', **{k:v for k,v in params.items() if k != 'space_id'},
        arguments={'action':'storage.candidate'})['evidence']
    with pytest.raises(PermissionError, match='live grant denied'):
        service.dispatch(pid, 'dot_vm_execute', {**params,
            'arguments':{'action':'storage.enroll','expected_candidate_sha256':candidate['candidate_sha256']}},
            'agent-forged-storage-' + uuid.uuid4().hex)
    assert 'storage_binding' not in service.store.get(pid, root['dot_id'])
    assert not fake.calls


def test_owner_enrollment_rejects_renderer_approval_flags(enrolled_scope):
    app, pid, call, service, params, root, cfg, fake, disk, server = enrolled_scope
    with pytest.raises(ValueError, match='exact_owner_storage'):
        app.shell_bridge({'action':'dot_vm_execute','project_id':pid,**params,
            'request_key':'forged-review-flags', 'arguments':{'action':'storage.enroll',
            'expected_candidate_sha256':'a'*64,'approved':True}})
    assert 'storage_binding' not in service.store.get(pid, root['dot_id'])
    assert not fake.calls
