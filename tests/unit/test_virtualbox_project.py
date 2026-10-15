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
    assert result['contemporary_guest_copy'] is True
    assert result['guest_copy_proven'] is True
    assert result['claims_guest_execution'] is True
    assert result['execution_surface']=='guest'
    assert result['host_subprocess'] is False
    assert result['guest_witness']=='guestcontrol_hash'
    assert result['entry_kind']=='directory'
    assert result['files']==1 and result['sha256']
    copy = next(parts for parts,_ in client.calls if 'copyto' in parts)
    assert copy[copy.index('--target-directory')+1].startswith('/home/sentra/Imports/')
    assert copy[copy.index('--target-directory')+1].endswith('.tar')
    copied_archive = copy[-1].split('\\')[-1].split('/')[-1]
    verify = next(parts for parts,_ in client.calls if 'sha256sum -c' in str(parts))
    assert copied_archive in str(verify)
    for parts, _ in client.calls:
        if 'run' in parts:
            assert parts[parts.index('--') + 1] == '-c'
            assert parts.count('/bin/sh') == 1
    assert not list((tmp_path/'owned'/'imports').glob('*.tar'))


def test_windows_import_does_not_report_success_when_extract_fails(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.txt').write_text('safe payload', encoding='utf8')
    monkeypatch.setattr(module, 'verify_guest', lambda client, binding, cfg: {'installed_os_verified': True})
    seen = []

    class Client:
        def run(self, *parts, **kwargs):
            seen.append(parts)
            if any('SENTRA_IMPORT_COMPLETE' in str(part) for part in parts):
                command = next(part for part in parts if 'SENTRA_IMPORT_COMPLETE' in str(part))
                assert 'tar -xf' in command
                assert command.index('tar -xf') < command.index('$LASTEXITCODE -ne 0') < command.index('SENTRA_IMPORT_COMPLETE')
                assert 'Remove-Item -Force $archive' in command
                assert command.index('$LASTEXITCODE -ne 0') < command.index('Remove-Item -Force $archive')
                return 'extract failed'
            return ''

    (tmp_path / 'owned').mkdir()
    binding = SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm')
    config = {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock', 'os_family': 'windows'}
    with pytest.raises(RuntimeError, match='unconfirmed'):
        module.import_project(Client(), binding, config)
    assert seen
    assert not list((tmp_path / 'owned' / 'imports').glob('*.receipt.json'))


def test_import_refuses_a_path_vm_name_before_any_copy(tmp_path):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.txt').write_text('safe payload', encoding='utf-8')
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            calls.append(parts)
            return ''

    with pytest.raises(ValueError, match='hypervisor token'):
        module.import_project(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='owned-vm'),
            {'base_folder': str(tmp_path), 'name': '../outside', 'password': 'only-for-mock'},
        )
    assert calls == []
    assert not list(tmp_path.rglob('*.tar'))
    assert not (tmp_path.parent / 'outside').exists()


def test_import_never_starts_when_guest_is_not_verified(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    monkeypatch.setattr(module,'verify_guest',lambda client,binding,cfg: {'installed_os_verified':False})
    root=tmp_path/'project';root.mkdir()
    client=SimpleNamespace(run=lambda *a,**k: (_ for _ in ()).throw(AssertionError('no effects')))
    with pytest.raises(ValueError,match='authenticated persistent guest'):
        module.import_project(client,SimpleNamespace(workspace_root=str(root),vm_id='owned'),
            {'base_folder':str(tmp_path),'name':'owned','password':'mock'})


def test_injected_guest_executor_imports_without_host_guestcontrol(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    from sentra_executors.guest_execution import InjectableGuestExecutor
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.txt').write_text('safe payload', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda client, binding, cfg: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()

    class Client:
        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol copied without a proven guest executor')

    def copy(request):
        assert request['placement'] == 'guest'
        assert request['action'] == 'project.import'
        assert len(request['sha256']) == 64
        return {'copied': True, 'sha256': request['sha256'], 'exit_code': 0}

    guest = InjectableGuestExecutor(copy)
    result = module.import_project(
        Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
        {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
        guest_executor=guest,
    )
    assert len(guest.calls) == 1
    assert result['execution_surface'] == 'guest'
    assert result['claims_guest_execution'] is True
    assert result['contemporary_guest_copy'] is True
    assert result['host_subprocess'] is False
    assert result['guest_copy_proven'] is True
    assert not list((tmp_path / 'owned' / 'imports').glob('*.tar'))


def test_uncertain_guest_import_is_not_a_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    from sentra_executors.guest_execution import InjectableGuestExecutor
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.txt').write_text('safe payload', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda client, binding, cfg: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()

    class Client:
        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol copied an uncertain import')

    def copy(request):
        return {
            'copied': True, 'sha256': request['sha256'], 'exit_code': 0,
            'execution_uncertain': True,
        }

    with pytest.raises(RuntimeError, match='unconfirmed'):
        module.import_project(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
            {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
            guest_executor=InjectableGuestExecutor(copy),
        )
    assert not list((tmp_path / 'owned' / 'imports').glob('*.receipt.json'))


def test_guest_import_that_claims_a_host_process_is_not_success(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.txt').write_text('safe payload', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()

    class Client:
        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol copied an unproven import')

    class Bare:
        proven_guest = True
        execution_surface = 'guest'

        def execute(self, request):
            return {
                'copied': True, 'sha256': request['sha256'],
                'execution_surface': 'guest', 'host_subprocess': True,
                'claims_guest_execution': True,
            }

    with pytest.raises(RuntimeError, match='unconfirmed'):
        module.import_project(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
            {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
            guest_executor=Bare(),
        )
    receipts = list((tmp_path / 'owned' / 'imports' / 'ledger').glob('*.receipt.json'))
    assert receipts == []


def test_guest_import_with_a_failed_exit_is_not_success(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    from sentra_executors.guest_execution import InjectableGuestExecutor
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.txt').write_text('safe payload', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()

    class Client:
        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol copied a failed import')

    def copy(request):
        return {
            'copied': True, 'sha256': request['sha256'], 'exit_code': 1,
            'execution_surface': 'guest', 'host_subprocess': False,
            'claims_guest_execution': True,
        }

    with pytest.raises(RuntimeError, match='unconfirmed'):
        module.import_project(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
            {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
            guest_executor=InjectableGuestExecutor(copy),
        )
    assert list((tmp_path / 'owned' / 'imports' / 'ledger').glob('*.receipt.json')) == []


def test_unconfirmed_guest_import_is_not_replayed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    from sentra_executors.guest_execution import InjectableGuestExecutor
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.txt').write_text('safe payload', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol')

    def fail(request):
        calls.append(request['sha256'])
        return {'copied': False, 'sha256': request['sha256']}

    with pytest.raises(RuntimeError, match='unconfirmed'):
        module.import_project(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
            {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
            guest_executor=InjectableGuestExecutor(fail),
        )
    assert len(calls) == 1
    with pytest.raises(ValueError, match='uncertain and was not replayed'):
        module.import_project(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
            {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
            guest_executor=InjectableGuestExecutor(fail),
        )
    assert len(calls) == 1


def test_same_request_finishes_the_uncertain_guest_copy_without_a_new_snapshot(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    from sentra_executors.guest_execution import InjectableGuestExecutor
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.txt').write_text('safe payload', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()

    class Client:
        def __init__(self):
            self.calls = []

        def run(self, *parts, **kwargs):
            self.calls.append(parts)
            if any('sha256sum -c' in str(part) for part in parts):
                return 'SENTRA_IMPORT_COMPLETE'
            return ''

    client = Client()

    def fail(request):
        return {'copied': False, 'sha256': request['sha256'], 'execution_surface': 'guest'}

    binding = SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm')
    config = {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'}
    with pytest.raises(RuntimeError, match='unconfirmed'):
        module.import_project(
            client, binding, config, request_key='import-key-0001',
            guest_executor=InjectableGuestExecutor(fail),
        )
    assert client.calls == []
    with pytest.raises(ValueError, match='uncertain and was not replayed'):
        module.import_project(client, binding, config, request_key='import-key-0002')
    assert client.calls == []

    def refuse_snapshot(*args, **kwargs):
        raise AssertionError('host snapshot repeated')

    monkeypatch.setattr(module, 'snapshot_project', refuse_snapshot)
    finished = module.import_project(client, binding, config, request_key='import-key-0001')
    assert finished['receipt_state'] == 'SUCCEEDED'
    assert finished['reconciled_uncertain'] is True
    assert finished['execution_surface'] == 'guest'
    assert finished['guest_copy_proven'] is True
    assert finished['host_subprocess'] is False
    assert client.calls


def test_import_output_that_contains_the_password_is_not_a_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'one.txt').write_text('one file', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()

    class Client:
        def run(self, *parts, **kwargs):
            if any('sha256sum -c' in str(part) for part in parts):
                return 'SENTRA_IMPORT_COMPLETE only-for-mock'
            return ''

    with pytest.raises(RuntimeError, match='credential'):
        module.import_project(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
            {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
            relative_path='one.txt', request_key='file-secret-1',
        )
    assert list((tmp_path / 'owned' / 'imports' / 'ledger').glob('*.receipt.json')) == []


def test_dot_can_copy_one_file_or_a_folder_into_the_guest(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    folder = root / 'notes'
    folder.mkdir(parents=True)
    (root / 'one.txt').write_text('one file', encoding='utf-8')
    (folder / 'inside.txt').write_text('folder file', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()

    class Client:
        def __init__(self):
            self.calls = []
        def run(self, *parts, **kwargs):
            self.calls.append(parts)
            if any('sha256sum -c' in str(part) for part in parts):
                return 'SENTRA_IMPORT_COMPLETE'
            return ''

    binding = SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm')
    config = {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'}
    single = module.import_project(Client(), binding, config, relative_path='one.txt', request_key='file-copy-1')
    assert single['entry_kind'] == 'file' and single['files'] == 1
    assert single['guest_copy_proven'] is True
    nested = module.import_project(Client(), binding, config, relative_path='notes', request_key='folder-copy-1')
    assert nested['entry_kind'] == 'directory' and nested['files'] == 1
    assert nested['guest_path'].endswith('/project')


def test_windows_guest_copy_uses_powershell_and_checks_the_hash(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'one.txt').write_text('windows file', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            calls.append(parts)
            if any('Get-FileHash' in str(part) for part in parts):
                return 'SENTRA_IMPORT_COMPLETE'
            return ''

    result = module.import_project(
        Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
        {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock', 'os_family': 'windows'},
        relative_path='one.txt', request_key='win-file-1',
    )
    assert result['entry_kind'] == 'file'
    assert result['guest_path'].startswith('C:\\Users\\sentra\\Imports\\')
    assert result['guest_path'].endswith('\\project')
    assert result['guest_witness'] == 'guestcontrol_hash'
    assert any('powershell.exe' in str(parts) for parts in calls)
    assert not any('/bin/sh' in str(parts) for parts in calls)
    joined = [' '.join(str(part) for part in parts) for parts in calls]
    remove_at = next(i for i, text in enumerate(joined) if 'Remove-Item' in text)
    copy_at = next(i for i, text in enumerate(joined) if 'copyto' in text)
    assert remove_at < copy_at


def test_uncertain_import_refuses_a_shell_metacharacter_archive_name(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import json
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    root.mkdir()
    folder = tmp_path / 'owned' / 'imports'
    ledger = folder / 'ledger'
    ledger.mkdir(parents=True)
    archive = folder / 'abc;id.tar'
    archive.write_bytes(b'payload')
    digest = __import__('hashlib').sha256(archive.read_bytes()).hexdigest()
    (ledger / 'bad-name.intent.json').write_text(json.dumps({
        'phase': 'uncertain', 'vm_id': 'valid-own-vm', 'archive': 'abc;id.tar',
        'sha256': digest,
    }), encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})

    class Client:
        def run(self, *parts, **kwargs):
            raise AssertionError('guestcontrol ran for an unsafe archive name')

    with pytest.raises(ValueError, match='archive name is not usable'):
        module.reconcile_uncertain_import(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
            {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
        )


def test_uncertain_import_is_finished_without_a_second_snapshot(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import json
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    root.mkdir()
    owned = tmp_path / 'owned'
    folder = owned / 'imports'
    ledger = folder / 'ledger'
    ledger.mkdir(parents=True)
    archive = folder / 'abc123.tar'
    archive.write_bytes(b'not-a-real-tar-but-hashed')
    digest = __import__('hashlib').sha256(archive.read_bytes()).hexdigest()
    (ledger / 'live-file-copy.intent.json').write_text(json.dumps({
        'phase': 'uncertain', 'vm_id': 'valid-own-vm', 'archive': 'abc123.tar',
        'sha256': digest, 'request_key': 'live-file-copy', 'relative_path': 'one.txt',
        'host_folder': None, 'selection': 'bound_project_relative',
    }), encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            calls.append(parts)
            if any('sha256sum -c' in str(part) for part in parts):
                return 'SENTRA_IMPORT_COMPLETE'
            return ''

    result = module.reconcile_uncertain_import(
        Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
        {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock'},
    )
    assert result['reconciled_uncertain'] is True
    assert result['guest_copy_proven'] is True
    assert not archive.exists()
    assert not list(ledger.glob('*.intent.json'))
    assert (ledger / 'live-file-copy.receipt.json').is_file()
    assert any('copyto' in parts for parts in calls)


def test_import_uses_the_configured_dot_account(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import sentra_executors.virtualbox_project as module
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'one.txt').write_text('account', encoding='utf-8')
    monkeypatch.setattr(module, 'verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    (tmp_path / 'owned').mkdir()
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            calls.append(parts)
            if any('sha256sum -c' in str(part) for part in parts):
                return 'SENTRA_IMPORT_COMPLETE'
            return ''

    result = module.import_project(
        Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
        {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock', 'username': 'dotuser'},
        relative_path='one.txt', request_key='account-copy-1',
    )
    assert result['guest_path'].startswith('/home/dotuser/Imports/')
    assert 'sentra' not in result['guest_path']
    assert any(parts[parts.index('--username') + 1] == 'dotuser' for parts in calls if '--username' in parts)
    with pytest.raises(ValueError, match='guest account'):
        module.import_project(
            Client(), SimpleNamespace(workspace_root=str(root), vm_id='valid-own-vm'),
            {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock', 'username': '../sentra'},
            relative_path='one.txt', request_key='account-copy-2',
        )
