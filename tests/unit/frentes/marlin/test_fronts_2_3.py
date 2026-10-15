"""Fronts 2 and 3: interface install step, honest Windows license, explicit import."""
import asyncio
import uuid
from types import SimpleNamespace

import pytest

from sentra_executors.virtualbox_bootstrap import advance, install_script
from sentra_executors.virtualbox_installation import (
    WINDOWS_GUEST_PROBE, assess_windows_license, classify_windows_guest, verify_windows_guest, windows_usable)
from sentra_executors.virtualbox_project import import_project, resolve_import_root
from sentra_executors.virtualbox_vm import VirtualBoxBinding, VirtualBoxClient, VirtualBoxExecutor
from sentra_runtime.contracts import OperationRequest, PolicyDecision


def _cfg(tmp_path, **extra):
    value = {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'only-for-mock',
        'os_family': 'linux', 'cpus': 2, 'memory_mb': 2048, 'disk_gb': 32}
    value.update(extra)
    return value


def _binding(tmp_path, cfg, root):
    return VirtualBoxBinding(str(uuid.uuid4()), 'SENTRA-DOT:test', lambda: cfg, workspace_root=str(root))


class _Silent:
    def __getattr__(self, name):
        raise AssertionError('no hypervisor call: ' + name)


def test_resource_cap_call_site_refuses_without_central_authority_and_does_not_touch_vbox(tmp_path):
    from sentra_executors.virtualbox_vm import VM_ACTIONS
    cfg = _cfg(tmp_path)
    binding = _binding(tmp_path, cfg, tmp_path)
    calls = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        raise AssertionError('vbox was called')

    client = VirtualBoxClient(path='not-vboxmanage', runner=runner)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage': binding}, client=client)
    result = executor._execute(binding, {'action': 'resource.cap', 'cpus': 2, 'memory_mb': 4096, 'cpu_execution_cap': 40,
        'vm_id': binding.vm_id, 'controlled_proof': False, 'workload_inspected': False,
        'host': {'total_mb': 32000, 'available_mb': 16000, 'ram_percent': 40, 'cpu_percent': None},
        'surfaces': {'vm': {'rss_mb': 0}}, 'state_root': str(tmp_path)})
    assert 'resource.cap' in VM_ACTIONS['vm:manage']
    assert result['refused'] is True and result['executed'] is False and result['applied'] is False
    assert result['mutated'] is False and result['authorizes_effects'] is False
    assert result['reason'] == 'autoridade central ausente'
    assert calls == []


def test_debian_seed_script_creates_user_and_xfce_desktop():
    script = install_script(str(uuid.uuid4()), 32 * 1024**3, 'local-secret').decode()
    assert 'useradd' in script and 'xfce4' in script and 'lightdm' in script
    assert 'autologin-user=sentra' in script


def test_verified_receipt_is_observed_without_reinstall_or_guest_contact(tmp_path):
    cfg = _cfg(tmp_path)
    binding = _binding(tmp_path, cfg, tmp_path)
    bootstrap = tmp_path / 'owned' / 'bootstrap'
    receipts = tmp_path / 'owned' / 'runbook-receipts'
    bootstrap.mkdir(parents=True)
    receipts.mkdir()
    (bootstrap / 'launch-intent.json').write_text('{"recorded":true}', encoding='utf-8')
    (receipts / '07-verify-guest-unconfirmed.json').write_text('{"installed_os_verified":false}', encoding='utf-8')
    (receipts / '07-verify-guest.json').write_text(
        '{"status":"installed_guest_verified","boot_mode":"installed_disk","installed_os_verified":true,'
        '"desktop_ready_verified":true,"root_source":"/dev/sda1","root_uuid":"root-uuid","disk_uuid":"disk-uuid",'
        '"vm_id":"' + binding.vm_id + '"}', encoding='utf-8')
    result = advance(_Silent(), binding, cfg, confirm_launch=True)
    assert result['status'] == 'installed_guest_observed'
    assert result['observation_only'] is True and result['contemporary_probe'] is False
    assert result['installed_os_verified'] is True and result['desktop_ready_verified'] is True
    assert result['physical_effects_performed'] is False and result['replays_launch_intent'] is False
    assert result['interface_action'] == 'installation.advance'
    assert result['next_authorized_step']['action'] == 'installation.verify'
    assert result['next_authorized_step']['emits_credentials'] is False
    assert result['next_authorized_step']['credential_source'] == 'stored VM record'
    assert 'installation.launch' in result['next_authorized_step']['must_not']


def test_orphan_import_archive_is_not_replayed_or_deleted(tmp_path):
    root = tmp_path / 'project'
    chosen = root / 'chosen'
    chosen.mkdir(parents=True)
    (chosen / 'hello.txt').write_text('safe', encoding='utf-8')
    cfg = _cfg(tmp_path)
    folder = tmp_path / 'owned' / 'imports'
    folder.mkdir(parents=True)
    orphan = folder / 'fcca0db011b44f4593381b0164c82c88.tar'
    orphan.write_bytes(b'old-uncertain')
    client = SimpleNamespace(run=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('guest contacted')))
    with pytest.raises(ValueError, match='uncertain and was not replayed'):
        import_project(client, _binding(tmp_path, cfg, root), cfg, host_folder=str(chosen),
            request_key='fcca0db011b44f4593381b0164c82c88')
    assert orphan.read_bytes() == b'old-uncertain'


def test_advance_refuses_recorded_launch_without_touching_the_guest(tmp_path):
    cfg = _cfg(tmp_path)
    bootstrap = tmp_path / 'owned' / 'bootstrap'
    bootstrap.mkdir(parents=True)
    (bootstrap / 'launch-intent.json').write_text('{"vm_id":"recorded"}', encoding='utf-8')
    result = advance(_Silent(), _binding(tmp_path, cfg, tmp_path), cfg, confirm_launch=True)
    assert result['status'] == 'prior_attempt_not_replayed'
    assert result['interface_action'] == 'installation.advance'
    assert result['physical_effects_performed'] is False and result['automatic_retry'] is False
    assert result['installed_os_verified'] is False and result['windows_usable'] is False


def test_advance_requires_a_resource_reservation(tmp_path):
    cfg = _cfg(tmp_path, cpus=0)
    result = advance(_Silent(), _binding(tmp_path, cfg, tmp_path), cfg)
    assert result['status'] == 'resource_reservation_required'
    assert result['physical_effects_performed'] is False


def test_advance_prepares_user_desktop_seed_only_for_an_empty_powered_off_disk(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr('sentra_executors.virtualbox_installation.installation_plan', lambda *args, **kwargs: {
        'os_family': 'linux', 'vm_state': 'poweroff', 'status': 'empty_virtual_disk',
        'disk': {'empty_observed': True, 'partition_table_observed': False}})
    monkeypatch.setattr('sentra_executors.virtualbox_bootstrap.prepare', lambda *args, **kwargs: {
        'status': 'installation_seed_prepared', 'installed_os_verified': False, 'vm_id': 'owned'})
    monkeypatch.setattr('sentra_executors.virtualbox_bootstrap.launch', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('launch')))
    result = advance(_Silent(), _binding(tmp_path, cfg, tmp_path), cfg)
    assert result['status'] == 'installation_seed_prepared'
    assert result['user_and_desktop_scripted'] is True
    assert result['physical_effects_performed'] is True
    assert result['installed_os_verified'] is False
    assert result['resource_reservation']['reserved'] is True


def test_advance_keeps_a_verified_desktop_and_a_prepared_seed_unrepeated(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr('sentra_executors.virtualbox_installation.installation_plan', lambda *args, **kwargs: {
        'os_family': 'linux', 'vm_state': 'running', 'status': 'disk_data_os_unverified',
        'disk': {'empty_observed': False, 'partition_table_observed': True}})
    monkeypatch.setattr('sentra_executors.virtualbox_installation.verify_guest', lambda *args, **kwargs: {
        'installed_os_verified': True, 'desktop_ready_verified': True, 'vm_id': 'owned'})
    result = advance(_Silent(), _binding(tmp_path, cfg, tmp_path), cfg, confirm_launch=True)
    assert result['status'] == 'desktop_already_verified'
    assert result['physical_effects_performed'] is False
    bootstrap = tmp_path / 'owned' / 'bootstrap'
    bootstrap.mkdir(parents=True)
    (bootstrap / 'admission.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr('sentra_executors.virtualbox_installation.installation_plan', lambda *args, **kwargs: {
        'os_family': 'linux', 'vm_state': 'running', 'status': 'empty_virtual_disk',
        'disk': {'empty_observed': True, 'partition_table_observed': False}})
    waiting = advance(_Silent(), _binding(tmp_path, cfg, tmp_path), cfg)
    assert waiting['status'] == 'launch_requires_distinct_admission'
    assert waiting['physical_effects_performed'] is False


def test_windows_license_is_honest_and_blocks_an_unattested_install(tmp_path):
    cfg = _cfg(tmp_path, os_family='windows', cpus=2, memory_mb=4096, disk_gb=64)
    refused = advance(_Silent(), _binding(tmp_path, cfg, tmp_path), cfg)
    assert refused['status'] == 'windows_license_not_admitted'
    assert refused['windows_usable'] is False and refused['activation_claimed'] is False
    assert refused['product_key_stored'] is False and refused['physical_effects_performed'] is False
    with pytest.raises(ValueError, match='product keys'):
        assess_windows_license({**cfg, 'product_key': 'not-stored'})
    evaluation = assess_windows_license({**cfg, 'windows_license': {
        'channel': 'evaluation_unactivated', 'product_key_stored': False}})
    owner = assess_windows_license({**cfg, 'windows_license': {
        'channel': 'owner_attested_license', 'product_key_stored': False, 'attested_by': 'owner'}})
    desktop = classify_windows_guest('SENTRA_USER=present\nSENTRA_EXPLORER=running\nSENTRA_LICENSE_STATUS=Licensed\n')
    evaluation_desktop = classify_windows_guest('SENTRA_USER=present\nSENTRA_EXPLORER=running\nSENTRA_LICENSE_STATUS=Notification\n')
    unlicensed = classify_windows_guest('SENTRA_USER=present\nSENTRA_EXPLORER=running\nSENTRA_LICENSE_STATUS=Unlicensed\n')
    assert windows_usable(desktop, owner) is True and owner['activation_claimed'] is False
    assert windows_usable(evaluation_desktop, evaluation) is True
    assert windows_usable(unlicensed, owner) is False and unlicensed['installed_os_verified'] is True
    assert 'PartialProductKey' not in WINDOWS_GUEST_PROBE and 'product_key' not in WINDOWS_GUEST_PROBE
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            calls.append((parts, kwargs))
            return 'SENTRA_USER=present\nSENTRA_EXPLORER=running\nSENTRA_LICENSE_STATUS=Licensed\n'

    disk = {'disk_uuid': 'owned-disk', 'partition_table_observed': True}
    observed = verify_windows_guest(Client(), SimpleNamespace(vm_id='owned-vm'), {**cfg, 'windows_license': {
        'channel': 'owner_attested_license', 'product_key_stored': False, 'attested_by': 'owner'}}, disk)
    assert observed['windows_usable'] is True and observed['activation_claimed'] is False
    assert observed['activation_observed'] is True and observed['product_key_stored'] is False
    argv, options = calls[0]
    assert argv[argv.index('--') + 1] == '-NoLogo'
    assert 'powershell.exe' not in argv[argv.index('--') + 1:]
    assert cfg['password'] not in str(argv) and options['password'] == cfg['password']


def test_provision_rejects_a_bad_account_before_any_hypervisor_call(tmp_path):
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            calls.append(parts)
            return ''

        def detect(self, iso):
            calls.append(('detect', iso))
            return {}

    image = tmp_path / 'image.iso'
    image.write_bytes(b'iso')
    cfg = _cfg(tmp_path)
    cfg['username'] = '../sentra'
    cfg['iso_path'] = str(image)
    cfg['iso_sha256'] = __import__('hashlib').sha256(b'iso').hexdigest()
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage': object()}, client=Client())
    with pytest.raises(ValueError, match='guest account'):
        executor._provision(_binding(tmp_path, cfg, tmp_path), cfg)
    assert calls == []


def test_provision_rejects_a_windows_product_key_before_any_hypervisor_call(tmp_path):
    calls = []

    class Client:
        def run(self, *parts, **kwargs):
            calls.append(parts)
            return ''

    cfg = _cfg(tmp_path, os_family='windows', cpus=2, memory_mb=4096, disk_gb=64, product_key='not-stored')
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage': object()}, client=Client())
    with pytest.raises(ValueError, match='product keys'):
        executor._provision(_binding(tmp_path, cfg, tmp_path), cfg)
    assert calls == []


def test_guest_run_does_not_repeat_the_executable(tmp_path):
    from sentra_executors.guest_execution import InjectableGuestExecutor

    seen = {}

    class Client:
        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol was substituted for the guest executor')

    def record(request):
        seen['argv'] = tuple(request['argv'])
        return {'stdout': 'ok', 'exit_code': 0}

    cfg = _cfg(tmp_path)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': object()},
        client=Client(), guest_executor=InjectableGuestExecutor(record))
    result = executor._execute(_binding(tmp_path, cfg, tmp_path), {'action': 'guest.run', 'command': 'echo ok'})
    parts = seen['argv']
    assert parts[parts.index('--') + 1] == '-lc'
    assert parts.count('/bin/sh') == 1
    assert result['execution_surface'] == 'guest'
    assert result['claims_guest_execution'] is True
    assert result['host_subprocess'] is False
    assert result['guest_process_confirmed'] is True


def test_guest_run_uses_the_configured_dot_account(tmp_path):
    from sentra_executors.guest_execution import InjectableGuestExecutor

    seen = {}

    class Client:
        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol was substituted for the guest executor')

    def record(request):
        seen['argv'] = tuple(request['argv'])
        return {'stdout': 'ok', 'exit_code': 0}

    cfg = {**_cfg(tmp_path), 'username': 'dotuser'}
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': object()},
        client=Client(), guest_executor=InjectableGuestExecutor(record))
    executor._execute(_binding(tmp_path, cfg, tmp_path), {'action': 'guest.run', 'command': 'echo ok'})
    parts = seen['argv']
    assert parts[parts.index('--username') + 1] == 'dotuser'
    assert 'sentra' not in parts


def test_guest_run_waits_as_long_as_the_authorized_timeout(tmp_path):
    from sentra_executors.guest_execution import InjectableGuestExecutor

    seen = {}

    class Client:
        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol was substituted for the guest executor')

    def record(request):
        seen.update(request)
        return {'stdout': 'ok', 'exit_code': 0}

    cfg = _cfg(tmp_path)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': object()},
        client=Client(), guest_executor=InjectableGuestExecutor(record))
    executor._execute(_binding(tmp_path, cfg, tmp_path), {
        'action': 'guest.run', 'command': 'echo ok', 'timeout_seconds': 600,
    })
    assert seen['timeout_s'] == 600
    parts = tuple(seen['argv'])
    assert parts[parts.index('--timeout') + 1] == 600000


def test_guest_run_discards_output_that_contains_the_password(tmp_path):
    import json
    from sentra_executors.guest_execution import InjectableGuestExecutor

    class Client:
        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol ran')

    def record(request):
        return {
            'stdout': 'leak only-for-mock end', 'exit_code': 0,
            'execution_surface': 'guest', 'host_subprocess': False,
            'claims_guest_execution': True,
        }

    cfg = _cfg(tmp_path)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': object()},
        client=Client(), guest_executor=InjectableGuestExecutor(record))
    result = executor._execute(_binding(tmp_path, cfg, tmp_path), {'action': 'guest.run', 'command': 'echo ok'})
    assert result['blocked'] is True
    assert result['guest_process_confirmed'] is False
    assert result['execution_uncertain'] is True
    assert result['automatic_retry'] is False
    assert result['stdout'] == ''
    assert 'only-for-mock' not in json.dumps(result)


def test_guest_run_does_not_confirm_an_uncertain_result(tmp_path):
    from sentra_executors.guest_execution import InjectableGuestExecutor

    class Client:
        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol ran')

    def record(request):
        return {
            'stdout': 'ok', 'exit_code': 0, 'execution_surface': 'guest',
            'host_subprocess': False, 'claims_guest_execution': True,
            'execution_uncertain': True,
        }

    cfg = _cfg(tmp_path)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': object()},
        client=Client(), guest_executor=InjectableGuestExecutor(record))
    result = executor._execute(_binding(tmp_path, cfg, tmp_path), {'action': 'guest.run', 'command': 'echo ok'})
    assert result['guest_process_confirmed'] is False
    assert result['claims_guest_execution'] is False
    assert result['execution_uncertain'] is True
    assert result['automatic_retry'] is False
    assert result['stdout'] == ''


def test_guest_run_without_a_guest_claim_does_not_confirm(tmp_path):
    class Bare:
        proven_guest = True
        execution_surface = 'guest'

        def execute(self, request):
            return {
                'stdout': 'ok', 'exit_code': 0, 'execution_surface': 'guest',
                'host_subprocess': False, 'claims_guest_execution': False,
            }

    class Client:
        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol ran')

    cfg = _cfg(tmp_path)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': object()},
        client=Client(), guest_executor=Bare())
    result = executor._execute(_binding(tmp_path, cfg, tmp_path), {'action': 'guest.run', 'command': 'echo ok'})
    assert result['claims_guest_execution'] is False
    assert result['guest_process_confirmed'] is False
    assert result['execution_uncertain'] is True
    assert result['automatic_retry'] is False
    assert result['blocked'] is True


def test_guest_run_without_a_guest_result_does_not_claim_success(tmp_path):
    class Bare:
        proven_guest = True
        execution_surface = 'guest'

        def execute(self, request):
            return {'stdout': 'ok'}

    class Client:
        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol ran')

    cfg = _cfg(tmp_path)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': object()},
        client=Client(), guest_executor=Bare())
    result = executor._execute(_binding(tmp_path, cfg, tmp_path), {'action': 'guest.run', 'command': 'echo ok'})
    assert result['claims_guest_execution'] is False
    assert result['guest_process_confirmed'] is False
    assert result['execution_uncertain'] is True
    assert result['automatic_retry'] is False
    assert result['blocked'] is True


def test_guest_run_without_a_proven_executor_does_not_call_the_host(tmp_path):
    class Client:
        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            raise AssertionError('host guestcontrol ran without a proven guest executor')

    cfg = _cfg(tmp_path)
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': object()}, client=Client())
    result = executor._execute(_binding(tmp_path, cfg, tmp_path), {'action': 'guest.run', 'command': 'echo ok'})
    assert result['blocked'] is True
    assert result['execution_uncertain'] is True
    assert result['execution_surface'] == 'blocked'
    assert result['guest_process_confirmed'] is False
    assert result['claims_guest_execution'] is False
    assert result['host_subprocess'] is False
    assert result['automatic_retry'] is False


def test_blocked_guest_run_is_uncertain_and_is_not_repeated(tmp_path):
    calls = []

    class Client:
        def status(self, binding):
            calls.append('status')
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            calls.append('run')
            raise AssertionError('host guestcontrol')

    cfg = _cfg(tmp_path)
    binding = _binding(tmp_path, cfg, tmp_path)
    executor = VirtualBoxExecutor(
        machine_id='m', owner_principal_id='a', bindings={'vm:guest': binding}, client=Client(),
        policy=lambda request: PolicyDecision(True, 'granted'))
    request = OperationRequest(
        operation_id='op-guest-run-blocked', principal_id='a', machine_id='m',
        capability_id='vm:guest', work_item_id='wi-guest-run', idempotency_key='guest-run-blocked',
        arguments={'action': 'guest.run', 'command': 'echo ok'})
    first = asyncio.run(executor.start(request))
    assert first.state == 'UNCERTAIN'
    assert first.evidence['execution_surface'] == 'blocked'
    assert first.evidence['host_subprocess'] is False
    assert 'run' not in calls
    second = asyncio.run(executor.start(request))
    assert second.state == 'UNCERTAIN'
    assert calls == ['status']


def test_explicit_host_folder_is_bounded(tmp_path):
    root = tmp_path / 'project'
    chosen = root / 'chosen'
    chosen.mkdir(parents=True)
    (root / '.ssh').mkdir()
    resolved, selection = resolve_import_root(root, str(chosen))
    assert resolved == chosen.resolve() and selection == 'explicit_host_folder'
    with pytest.raises(ValueError, match='absolute'):
        resolve_import_root(root, 'chosen')
    with pytest.raises(ValueError, match='host root'):
        resolve_import_root(root, str(Path_anchor(tmp_path)))
    outside = tmp_path / 'outside'
    outside.mkdir()
    with pytest.raises(ValueError, match='outside'):
        resolve_import_root(root, str(outside))
    with pytest.raises(ValueError, match='sensitive'):
        resolve_import_root(root, str(root / '.ssh'))


def Path_anchor(path):
    from pathlib import Path
    return Path(path.anchor)


def test_prior_import_and_duplicate_payload_are_not_replayed(tmp_path):
    root = tmp_path / 'project'
    chosen = root / 'chosen'
    other = root / 'other'
    chosen.mkdir(parents=True)
    other.mkdir()
    (chosen / 'hello.txt').write_text('safe', encoding='utf-8')
    cfg = _cfg(tmp_path)
    binding = _binding(tmp_path, cfg, root)
    ledger = tmp_path / 'owned' / 'imports' / 'ledger'
    ledger.mkdir(parents=True)
    (ledger / 'old.intent.json').write_text('{"phase":"uncertain"}', encoding='utf-8')
    client = SimpleNamespace(run=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('guest contacted')))
    with pytest.raises(ValueError, match='uncertain and was not replayed'):
        import_project(client, binding, cfg, host_folder=str(chosen), request_key='import-key-0001')
    (ledger / 'old.intent.json').unlink()
    receipt = {'request_key': 'import-key-0001', 'host_folder': str(chosen.resolve()), 'relative_path': '.',
        'receipt_state': 'SUCCEEDED', 'sha256': 'abc', 'guest_path': '/home/sentra/Imports/old/project',
        'status': 'project_imported'}
    (ledger / 'import-key-0001.receipt.json').write_text(__import__('json').dumps(receipt), encoding='utf-8')
    replayed = import_project(client, binding, cfg, host_folder=str(chosen), request_key='import-key-0001')
    assert replayed['replayed'] is True and replayed['physical_effects_performed'] is False
    assert replayed['receipt_state'] == 'SUCCEEDED'
    with pytest.raises(ValueError, match='duplicate import request'):
        import_project(client, binding, cfg, host_folder=str(other), request_key='import-key-0001')


def test_explicit_folder_import_succeeds_once_through_the_executor(tmp_path, monkeypatch):
    monkeypatch.setattr('sentra_executors.virtualbox_project.verify_guest', lambda *args, **kwargs: {'installed_os_verified': True})
    root = tmp_path / 'project'
    chosen = root / 'chosen'
    chosen.mkdir(parents=True)
    (chosen / 'hello.txt').write_text('safe payload', encoding='utf-8')
    (tmp_path / 'owned').mkdir()
    cfg = _cfg(tmp_path)
    binding = _binding(tmp_path, cfg, root)

    class Client:
        def __init__(self):
            self.calls = []

        def status(self, binding):
            return {'VMState': 'running'}

        def run(self, *parts, **kwargs):
            self.calls.append(parts)
            if any('sha256sum -c' in str(part) for part in parts):
                return 'SENTRA_IMPORT_COMPLETE'
            return ''

    client = Client()
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': binding},
        client=client, policy=lambda request: PolicyDecision(True, 'granted'))
    request = OperationRequest(operation_id='op-import-1', principal_id='a', machine_id='m',
        capability_id='vm:guest', work_item_id='wi-import-1', idempotency_key='import-key-0001',
        arguments={'action': 'project.import', 'host_folder': str(chosen), 'relative_path': '.',
            'request_key': 'import-key-0001'})
    result = asyncio.run(executor.start(request))
    assert result.state == 'SUCCEEDED'
    assert result.evidence['receipt_state'] == 'SUCCEEDED'
    assert result.evidence['selection'] == 'explicit_host_folder'
    assert result.evidence['files'] == 1 and len(result.evidence['sha256']) == 64
    assert result.evidence['guest_path'].endswith('/project')
    assert result.evidence['bidirectional_sync'] is False
    copy = next(parts for parts in client.calls if 'copyto' in parts)
    target = copy[copy.index('--target-directory') + 1]
    assert target.startswith('/home/sentra/Imports/')
    assert target.endswith('.tar')
    copied = copy[-1].replace('\\', '/').rsplit('/', 1)[-1]
    verify = next(parts for parts in client.calls if any('sha256sum -c' in str(part) for part in parts))
    assert copied in str(verify)
    for parts in client.calls:
        if 'run' in parts:
            assert parts[parts.index('--') + 1] == '-c'
            assert parts.count('/bin/sh') == 1
    assert not list((tmp_path / 'owned' / 'imports').glob('*.tar'))
    sent = len(client.calls)
    again = asyncio.run(executor.start(request))
    assert again.state == 'SUCCEEDED' and again.evidence['sha256'] == result.evidence['sha256']
    assert len(client.calls) == sent
    fresh = Client()
    other = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:guest': binding},
        client=fresh, policy=lambda request: PolicyDecision(True, 'granted'))
    observed = asyncio.run(other.start(OperationRequest(
        operation_id='op-import-2', principal_id='a', machine_id='m', capability_id='vm:guest',
        work_item_id='wi-import-1', idempotency_key='import-key-0002',
        arguments={'action': 'project.import', 'host_folder': str(chosen), 'relative_path': '.',
            'request_key': 'import-key-0001'})))
    assert observed.state == 'SUCCEEDED' and observed.evidence['replayed'] is True
    assert observed.evidence['physical_effects_performed'] is False
    assert not any('copyto' in parts for parts in fresh.calls)


def test_bridge_publishes_advance_and_keeps_a_recorded_attempt(tmp_path, monkeypatch):
    from sentra_canvas.shell_dot_vm import project_vm_execution
    from sentra_executors.virtualbox_vm import BRIDGE_INTERFACE, bridge_capability
    advance_contract = BRIDGE_INTERFACE['installation.advance']
    import_contract = BRIDGE_INTERFACE['project.import']
    assert advance_contract['route'] == 'dot_vm_execute'
    assert advance_contract['capability'] == 'vm:manage'
    assert advance_contract['arguments'] == ['confirm_launch']
    assert advance_contract['screen_button'] is False
    assert advance_contract['replays_launch_intent'] is False
    assert advance_contract['physical_proof'] is False
    assert import_contract['replays_duplicate_operation'] is False
    assert import_contract['physical_proof'] is False
    assert bridge_capability('installation.advance') == 'vm:manage'
    assert bridge_capability('project.import') == 'vm:guest'
    recorded = {'provisioning_status': 'installation_launch_sent'}
    observed = project_vm_execution(recorded, {'action': 'installation.advance'}, {
        'state': 'SUCCEEDED', 'evidence': {
            'status': 'prior_attempt_not_replayed', 'interface_action': 'installation.advance',
            'physical_effects_performed': False, 'automatic_retry': False}})
    assert 'provisioning_status' not in observed
    assert observed['installation_advance']['route'] == 'dot_vm_execute'
    assert observed['installation_advance']['replays_launch_intent'] is False
    assert observed['installation_advance']['physical_effects_performed'] is False
    uncertain = project_vm_execution({'provisioning_status': 'ready_to_create'}, {'action': 'provision'},
        {'state': 'UNCERTAIN', 'evidence': {}})
    assert uncertain['provisioning_status'] == 'uncertain_requires_reconciliation'
    replay = project_vm_execution({}, {'action': 'project.import'}, {'state': 'SUCCEEDED', 'evidence': {
        'status': 'project_imported', 'receipt_state': 'SUCCEEDED', 'sha256': 'abc', 'replayed': True,
        'physical_effects_performed': False, 'guest_path': '/home/sentra/Imports/old/project'}})
    assert replay['last_project_import']['replayed'] is True
    assert replay['last_project_import']['replays_duplicate_operation'] is False
    assert replay['last_project_import']['physical_effects_performed'] is False
    refused = project_vm_execution(
        {'last_project_import': {'receipt_state': 'SUCCEEDED', 'guest_path': '/home/sentra/Imports/keep'}},
        {'action': 'project.import'},
        {'state': 'SUCCEEDED', 'evidence': {
            'status': 'project_imported', 'receipt_state': 'FAILED',
            'guest_path': '/home/sentra/Imports/a;id'}})
    assert 'last_project_import' not in refused
    escaped = project_vm_execution({}, {'action': 'project.import'}, {'state': 'SUCCEEDED', 'evidence': {
        'receipt_state': 'SUCCEEDED', 'guest_path': '/home/sentra/../../etc'}})
    assert 'last_project_import' not in escaped

    from pathlib import Path
    import json
    import sys
    import uuid
    unit = Path(__file__).resolve().parents[2]
    if str(unit) not in sys.path:
        sys.path.insert(0, str(unit))
    from test_sentra_runtime_canvas_center_http import request, running_canvas
    from test_shell_dot_features import dot
    from sentra_canvas.shell_dot_vm import DotVmServices
    from sentra_executors.virtualbox_vm import VirtualBoxClient
    monkeypatch.setattr('sentra_canvas.shell_dot_vm.host_resources', lambda: {
        'logical_cpus': 12, 'physical_memory_mb': 32768, 'max_cpus': 6, 'max_memory_mb': 16384,
        'resource_fraction': 0.5, 'limit_kind': 'configured_vcpu_and_ram'})
    forbidden = {'guestcontrol', 'controlvm', 'startvm', 'storageattach', 'unattended', 'createvm', 'createmedium', 'modifyvm'}
    calls = []
    identity = {}

    def tracking_run(self, *args, **kwargs):
        calls.append(tuple(args))
        if args and args[0] in forbidden:
            raise AssertionError('physical command ' + args[0])
        if args and args[0] == 'showvminfo':
            return 'UUID="' + identity['vm_id'] + '"\ndescription="' + identity['marker'] + '"\nVMState="poweroff"\n'
        return ''

    monkeypatch.setattr(VirtualBoxClient, 'run', tracking_run)
    with running_canvas(tmp_path) as (app, server):
        monkeypatch.setattr(app, 'model_catalog', lambda: {'models': ['sentra/test-one']})
        project_id = app.create_workspace('Dot_bridge')['id']
        runtime = app._runtime()
        run = runtime.run(project_id)
        if run['state'] != 'RUNNING':
            runtime.durable.transition_run(run['run_id'], runtime.owner, 'RUNNING')
        home = app.shell_bridge({'action': 'home', 'project_id': project_id})['value']
        scope = {'project_id': project_id, 'space_id': home['space']['space_id']}

        def call(action, **fields):
            code, body = request(server, '/api/shell/bridge', json_body={'action': action, **scope,
                'request_key': 'test-' + uuid.uuid4().hex, **fields})
            assert code == 200, body
            assert body['ok'] is True, body
            return body['value']

        root = dot(call, 'Bridge owner')
        conversation = call('conversation_create', dot_id=root['dot_id'])
        call('access_set', conversation_id=conversation['conversation_id'], mode='full')
        service = DotVmServices(app)
        params = {'dot_id': root['dot_id'], 'space_id': scope['space_id'], 'conversation_id': conversation['conversation_id']}
        service.dispatch(project_id, 'dot_vm_configure', {**params, 'os_family': 'linux', 'cpus': 2,
            'memory_mb': 2048, 'disk_gb': 32, 'iso_path': ''}, uuid.uuid4().hex)
        stored = service.store.get(project_id, root['dot_id'])
        identity['vm_id'] = stored['vm_id']
        identity['marker'] = stored['marker']
        base = Path(stored['base_folder'])
        assert str(tmp_path) in str(base)
        bootstrap = base / stored['name'] / 'bootstrap'
        bootstrap.mkdir(parents=True)
        intent = bootstrap / 'launch-intent.json'
        intent.write_text('{"recorded":true}', encoding='utf-8')
        before = intent.read_bytes()
        seen = []
        original = service.host.dispatch

        def spy(**kwargs):
            seen.append(kwargs)
            return original(**kwargs)

        monkeypatch.setattr(service.host, 'dispatch', spy)
        advanced = service.dispatch(project_id, 'dot_vm_execute', {**params, 'arguments': {
            'action': 'installation.advance', 'confirm_launch': True}}, 'bridge-advance-01')
        assert seen[-1]['capability_id'] == 'vm:manage'
        assert seen[-1]['arguments'] == {'action': 'installation.advance', 'confirm_launch': True}
        assert advanced['state'] == 'SUCCEEDED'
        assert advanced['evidence']['status'] == 'prior_attempt_not_replayed'
        assert advanced['evidence']['interface_action'] == 'installation.advance'
        assert advanced['evidence']['physical_effects_performed'] is False
        assert advanced['evidence']['automatic_retry'] is False
        assert intent.read_bytes() == before
        kept = service.store.get(project_id, root['dot_id'])
        assert kept['provisioning_status'] == 'pending_image'
        assert kept['installation_advance']['replays_launch_intent'] is False
        assert kept['installation_advance']['physical_effects_performed'] is False
        workspace = Path(app.store.workspace(project_id)['path'])
        chosen = workspace / 'chosen'
        other = workspace / 'other'
        chosen.mkdir()
        other.mkdir()
        (chosen / 'hello.txt').write_text('safe', encoding='utf-8')
        ledger = base / stored['name'] / 'imports' / 'ledger'
        ledger.mkdir(parents=True)
        receipt = {'request_key': 'import-key-0001', 'host_folder': str(chosen.resolve()), 'relative_path': '.',
            'receipt_state': 'SUCCEEDED', 'sha256': 'abc', 'status': 'project_imported',
            'guest_path': '/home/sentra/Imports/old/project', 'replayed': False, 'physical_effects_performed': True}
        (ledger / 'import-key-0001.receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        imported = service.dispatch(project_id, 'dot_vm_execute', {**params, 'arguments': {
            'action': 'project.import', 'host_folder': str(chosen), 'relative_path': '.',
            'request_key': 'import-key-0001'}}, 'bridge-import-0001')
        assert seen[-1]['capability_id'] == 'vm:guest'
        assert seen[-1]['arguments']['action'] == 'project.import'
        assert imported['state'] == 'SUCCEEDED'
        assert imported['evidence']['replayed'] is True
        assert imported['evidence']['physical_effects_performed'] is False
        assert imported['evidence']['receipt_state'] == 'SUCCEEDED'
        try:
            duplicate = service.dispatch(project_id, 'dot_vm_execute', {**params, 'arguments': {
                'action': 'project.import', 'host_folder': str(other), 'relative_path': '.',
                'request_key': 'import-key-0001'}}, 'bridge-import-0002')
        except ValueError as exc:
            assert 'duplicate import request' in str(exc)
        else:
            assert duplicate['state'] in {'FAILED', 'UNCERTAIN'}
            assert duplicate.get('evidence', {}).get('physical_effects_performed') is not True
        assert not any(args and args[0] in forbidden for args in calls)


def test_guest_run_attaches_real_guestcontrol_only_when_additions_are_live(tmp_path):
    """Production path resolves guestcontrol lazily, never using a host fallback."""
    cfg = _cfg(tmp_path)
    binding = _binding(tmp_path, cfg, tmp_path)
    calls = []

    class Client:
        runlevel = "0"

        def status(self, binding):
            return {"VMState": "running"}

        def guest_additions_runlevel(self, vm_id):
            assert vm_id == binding.vm_id
            return self.runlevel

        def run(self, *parts, **kwargs):
            calls.append((parts, kwargs))
            assert parts[:3] == ("guestcontrol", binding.vm_id, "run")
            assert kwargs["password"] == cfg["password"]
            assert cfg["password"] not in parts
            return "physical-guest-result"

    client = Client()
    executor = VirtualBoxExecutor(
        machine_id="m", owner_principal_id="a",
        bindings={"vm:guest": binding}, client=client)
    blocked = executor._execute(binding, {"action": "guest.run", "command": "echo ready"})
    assert blocked["blocked"] is True
    assert blocked["claims_guest_execution"] is False
    assert calls == []

    client.runlevel = "2"
    actual = executor._execute(binding, {"action": "guest.run", "command": "echo ready"})
    assert len(calls) == 1
    assert actual["guest_process_confirmed"] is True
    assert actual["execution_surface"] == "guest"
    assert actual["claims_guest_execution"] is True
    assert actual["stdout"] == "physical-guest-result"
