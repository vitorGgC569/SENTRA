import tarfile
import pytest
from sentra_executors.virtualbox_project import snapshot_project


def test_snapshot_is_deterministic_and_excludes_credentials_and_repository_state(tmp_path):
    root = tmp_path/'project'; root.mkdir()
    (root/'app.py').write_text('print("hello")\n')
    for name in ('.git','.sentra','.ssh'):
        (root/name).mkdir(); (root/name/'private').write_text('secret')
    for name in ('.env','.env.local','auth.json','private.pem'):
        (root/name).write_text('secret')
    first, second = tmp_path/'a.tar', tmp_path/'b.tar'
    result = snapshot_project(root, first)
    again = snapshot_project(root, second)
    assert result['sha256'] == again['sha256']
    assert result['files'] == 1 and result['excluded_count'] == 7
    with tarfile.open(first) as archive:
        assert archive.getnames() == ['app.py']
        assert archive.getmember('app.py').mtime == 0


def test_snapshot_refuses_escape_sensitive_selection_and_budgets(tmp_path):
    root = tmp_path/'project'; root.mkdir()
    (root/'large').write_bytes(b'x'*100)
    for selection in ('..', '.sentra', '.git', '.env'):
        with pytest.raises(ValueError):
            snapshot_project(root, tmp_path/'bad.tar', relative_path=selection)
    with pytest.raises(ValueError):
        snapshot_project(root, tmp_path/'size.tar', max_bytes=50)
    assert not (tmp_path/'size.tar').exists()


def test_snapshot_rejects_symlink_files_and_external_directory(tmp_path):
    root = tmp_path/'project'; root.mkdir()
    outside = tmp_path/'outside'; outside.mkdir()
    secret = outside/'secret'; secret.write_text('not exported')
    try:
        (root/'link').symlink_to(secret)
        (root/'directory').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlinks unavailable to test token')
    result = snapshot_project(root, tmp_path/'safe.tar')
    assert result['files'] == 0 and result['excluded_count'] == 2
    with pytest.raises(ValueError):
        snapshot_project(root, tmp_path/'bad.tar', relative_path='directory')

def test_import_targets_guest_directory_and_verifies_exact_archive(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    root = tmp_path/'project'; root.mkdir()
    (root/'hello.txt').write_text('safe payload',encoding='utf8')
    monkeypatch.setattr(module,'verify_guest',lambda client,binding,cfg: {'installed_os_verified':True})
    class Client:
        def __init__(self): self.calls=[]
        def run(self,*parts,**kwargs):
            self.calls.append((parts,kwargs))
            if 'run' in parts and any('sha256sum -c' in str(part) for part in parts):
                return 'SENTRA_IMPORT_COMPLETE'
            return ''
    client=Client()
    binding=SimpleNamespace(workspace_root=str(root),vm_id='valid-own-vm')
    (tmp_path/'owned').mkdir()  # existing, bound VM directory established by provisioner
    config={'base_folder':str(tmp_path),'name':'owned','password':'only-for-mock'}
    result=module.import_project(client,binding,config)
    assert result['status']=='project_imported'
    assert result['files']==1 and result['sha256']
    copy = next(parts for parts,_ in client.calls if 'copyto' in parts)
    assert copy[copy.index('--target-directory')+1].startswith('/home/sentra/Imports/')
    assert not copy[copy.index('--target-directory')+1].endswith('.tar')
    copied_archive = copy[-1].split('\\')[-1].split('/')[-1]
    verify = next(parts for parts,_ in client.calls if 'sha256sum -c' in str(parts))
    assert copied_archive in str(verify)
    for parts, _ in client.calls:
        if 'run' in parts:
            assert parts[parts.index('--') + 1] == '-c'
            assert parts.count('/bin/sh') == 1
    assert not list((tmp_path/'owned'/'imports').glob('*.tar'))


def test_import_never_starts_when_guest_is_not_verified(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    monkeypatch.setattr(module,'verify_guest',lambda client,binding,cfg: {'installed_os_verified':False})
    root=tmp_path/'project';root.mkdir()
    client=SimpleNamespace(run=lambda *a,**k: (_ for _ in ()).throw(AssertionError('no effects')))
    with pytest.raises(ValueError,match='authenticated persistent guest'):
        module.import_project(client,SimpleNamespace(workspace_root=str(root),vm_id='owned'),
            {'base_folder':str(tmp_path),'name':'owned','password':'mock'})
