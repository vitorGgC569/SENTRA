from pathlib import Path
import hashlib
import json
import uuid

import pytest

from sentra_executors import virtualbox_bootstrap as bootstrap
from sentra_executors.virtualbox_seed import seed_iso
from sentra_executors.virtualbox_vm import VirtualBoxBinding, VirtualBoxExecutor


def test_seed_deterministic_bounded_and_never_overwrites(tmp_path):
    first, second = tmp_path/'a.iso', tmp_path/'b.iso'
    seed_iso(first, {'INSTALL.SH': b'echo safe\n'})
    seed_iso(second, {'INSTALL.SH': b'echo safe\n'})
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes()[32768:32775] == b'\x01CD001\x01'
    with pytest.raises(FileExistsError):
        seed_iso(first, {'INSTALL.SH': b'changed'})
    with pytest.raises(ValueError):
        seed_iso(tmp_path/'bad.iso', {'../X.SH': b'bad'})


def test_guest_script_guards_own_identity_and_single_empty_disk_before_formatting():
    identity = str(uuid.uuid4())
    script = bootstrap.install_script(identity, 64*1024**3, 'private-test').decode()
    before = script.split('sfdisk /dev/sda')[0]
    assert identity in before and 'product_uuid' in before
    assert 'wipefs -n' in before and 'lsblk -dn' in before
    assert '68719476736' in before and 'FSTYPE /)' in before
    assert 'autologin-user=sentra' in script and 'NOPASSWD: ALL' in script
    assert 'private-test' not in script
    assert 'SENTRA_INSTALL_COMPLETE_POWEROFF' in script
    assert '/dev/sdb' not in script


def test_no_prepare_effect_on_nonempty_running_or_other_os(monkeypatch, tmp_path):
    identity = str(uuid.uuid4())
    binding = VirtualBoxBinding(identity, 'marker', None)
    class Client:
        path = str(tmp_path/'VBoxManage.exe')
        def run(self, *args, **kwargs):
            raise AssertionError('must not mutate')
    for family, state, empty in [('linux','paused',True), ('linux','poweroff',False), ('windows','poweroff',True)]:
        monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: ({'VMState': state}, {'empty_observed': empty}))
        with pytest.raises(ValueError):
            bootstrap.prepare(Client(), binding, {'os_family':family, 'iso_path':'debian-live-13.7.0-amd64.iso'})


def test_launch_rechecks_disk_and_never_replays_intent(monkeypatch, tmp_path):
    identity = str(uuid.uuid4())
    folder = tmp_path/'owned'/'bootstrap'; folder.mkdir(parents=True)
    seed = folder/'seed.iso'; seed.write_bytes(b'seed')
    cfg = {'base_folder':str(tmp_path), 'name':'owned'}
    binding = VirtualBoxBinding(identity, 'marker', lambda:cfg)
    disk = {'empty_observed':True,'disk_uuid':'owned','metadata_sha256':'metadata'}
    admission = {'vm_id':identity,'disk_uuid':'owned','vdi_metadata_sha256':'metadata',
        'seed_sha256':hashlib.sha256(b'seed').hexdigest()}
    (folder/'admission.json').write_text(json.dumps(admission))
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: ({'VMState':'running','hardwareuuid':identity,'SATA-2-0':str(seed)}, disk))
    class Client:
        def input(self, *args):
            raise AssertionError('do not replay')
    (folder/'launch-intent.json').write_text('{}')
    with pytest.raises(FileExistsError):
        bootstrap.launch(Client(), binding, cfg)
    disk['empty_observed'] = False
    with pytest.raises(ValueError):
        bootstrap.launch(Client(), binding, cfg)


def test_bootstrap_actions_cannot_take_renderer_selected_scripts_or_disks():
    executor = VirtualBoxExecutor(machine_id='m', owner_principal_id='a', bindings={'vm:manage':object()})
    for action in ('installation.prepare','installation.launch'):
        request = type('Request', (), {'capability_id':'vm:manage', 'arguments':{'action':action, 'disk':'/dev/sdb'}})()
        with pytest.raises(ValueError):
            executor._validate(request, None)


def test_prepare_restores_ejected_owned_iso_only_after_full_preflight(monkeypatch, tmp_path):
    identity = str(uuid.uuid4())
    image = tmp_path/'debian-live-13.7.0-amd64.iso'; image.write_bytes(b'configured-live')
    (tmp_path/'VBoxGuestAdditions.iso').write_bytes(b'additions')
    cfg = {'os_family':'linux', 'iso_path':str(image),
        'iso_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
        'base_folder':str(tmp_path), 'name':'owned', 'password':'test-private'}
    info = {'VMState':'poweroff','hardwareuuid':identity,'SATA-1-0':'emptydrive','SATA-2-0':'none','SATA-3-0':'none'}
    disk = {'empty_observed':True,'disk_uuid':'owned','metadata_sha256':'map','capacity_bytes':64*1024**3}
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args:(info,disk))
    monkeypatch.setattr(bootstrap, '_private_directory', lambda path:path.mkdir())
    class Client:
        path = str(tmp_path/'VBoxManage.exe')
        calls = []
        def run(self, *args, **kwargs): self.calls.append(args)
    client = Client()
    binding = VirtualBoxBinding(identity,'marker',lambda:cfg)
    info['SATA-1-0'] = str(tmp_path/'foreign.iso')
    with pytest.raises(ValueError, match='unexpected installation DVD'):
        bootstrap.prepare(client,binding,cfg)
    assert not client.calls and not (tmp_path/'owned'/'bootstrap').exists()
    info['SATA-1-0'] = 'emptydrive'
    info['SATA-2-0'] = str(tmp_path/'foreign-seed.iso')
    with pytest.raises(ValueError, match='seed drives already occupied'):
        bootstrap.prepare(client,binding,cfg)
    assert not client.calls
    info['SATA-2-0'] = 'none'
    image.write_bytes(b'changed')
    with pytest.raises(ValueError, match='ISO changed'):
        bootstrap.prepare(client,binding,cfg)
    assert not client.calls
    image.write_bytes(b'configured-live'); (tmp_path/'owned').mkdir()
    result = bootstrap.prepare(client,binding,cfg)
    assert result['status'] == 'installation_seed_prepared'
    assert client.calls[0][3:5] == ('SATA','--port')
    assert client.calls[0][5] == 1 and client.calls[0][-1] == str(image.resolve())
    assert len(client.calls) == 3


def test_guest_dmi_guard_admits_only_exact_smbios_uuid_serializations():
    # VBox hardwareuuid and Linux SMBIOS may differ in the byte order of
    # time_low/time_mid/time_hi; these are two encodings of the SAME UUID.
    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    alternate = 'cf74d9fc-dccc-3656-b7af-2f96024d5dde'
    script = bootstrap.install_script(identity, 64 * 1024**3, 'test-only').decode()
    prepartition = script.split('sfdisk /dev/sda')[0]
    assert ('case "$dmi_uuid" in ' + repr(identity) + '|' + repr(alternate)) in prepartition
    assert 'exit 33' in prepartition
    assert "product_uuid | tr '[:upper:]' '[:lower:]'" in prepartition
    assert '@@LEGACY_DMI@@' not in script
    assert prepartition.index('product_uuid') < prepartition.index('wipefs -n')
    assert prepartition.index('wipefs -n') < prepartition.index('SENTRA_INSTALL_ADMITTED')


def test_install_admission_rejects_changed_hardware_uuid_even_if_vm_id_matches():
    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    bootstrap._require_hardware_uuid({'hardwareuuid': identity.upper()}, identity)
    with pytest.raises(ValueError, match='hardware DMI UUID'):
        bootstrap._require_hardware_uuid({'hardwareuuid': 'cf74d9fc-dccc-3656-b7af-2f96024d5dde'}, identity)
    with pytest.raises(ValueError, match='hardware DMI UUID'):
        bootstrap._require_hardware_uuid({}, identity)


def test_prepare_and_launch_reject_foreign_dmi_hardware_before_effects(monkeypatch, tmp_path):
    identity = str(uuid.uuid4())
    binding = VirtualBoxBinding(identity, 'marker', None)
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: (
        {'VMState': 'poweroff', 'hardwareuuid': str(uuid.uuid4())},
        {'empty_observed': True}))
    class NoEffects:
        def run(self, *args, **kwargs):
            raise AssertionError('foreign SMBIOS must not mutate storage')
        def input(self, *args, **kwargs):
            raise AssertionError('foreign SMBIOS must not receive input')
    cfg = {'os_family': 'linux', 'iso_path': 'debian-live-13.7-amd64.iso',
        'base_folder': str(tmp_path), 'name': 'owned'}
    with pytest.raises(ValueError, match='hardware DMI UUID'):
        bootstrap.prepare(NoEffects(), binding, cfg)
    with pytest.raises(ValueError, match='hardware DMI UUID'):
        bootstrap.launch(NoEffects(), binding, cfg)
    assert not (tmp_path / 'owned').exists()


def test_reconcile_accepts_only_empty_disk_with_matching_admission_and_preserves_files(monkeypatch, tmp_path):
    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    folder = tmp_path / 'owned' / 'bootstrap'
    folder.mkdir(parents=True)
    seed = folder / 'seed.iso'
    seed.write_bytes(b'seed-content-v1')
    cfg = {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'test'}
    binding = VirtualBoxBinding(identity, 'marker', lambda: cfg)
    disk = {
        'empty_observed': True,
        'allocated_blocks': 0,
        'partition_table_observed': False,
        'metadata_stable': True,
        'disk_uuid': '9cf5e721-7cbd-48e9-9634-d2d709c9cb68',
        'metadata_sha256': 'meta-sha-1234',
        'capacity_bytes': 64 * 1024**3,
    }
    admission = {
        'vm_id': identity,
        'disk_uuid': '9cf5e721-7cbd-48e9-9634-d2d709c9cb68',
        'vdi_metadata_sha256': 'meta-sha-1234',
        'seed_sha256': hashlib.sha256(b'seed-content-v1').hexdigest(),
        'prepared_at': 1791800000.0,
    }
    (folder / 'admission.json').write_text(json.dumps(admission))
    (folder / 'launch-intent.json').write_text(json.dumps({'vm_id': identity, 'started_at': 1791800100.0}))

    info = {'VMState': 'running', 'hardwareuuid': identity, 'SATA-2-0': str(seed), 'SATA-3-0': 'additions.iso'}
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: (info, disk))

    calls = []
    class Client:
        def run(self, *args, **kwargs):
            calls.append(args)

    client = Client()
    receipt = bootstrap.reconcile_failed_attempt(client, binding, cfg, detach_storage=False, request_key='req-1')
    assert receipt['status'] == 'reconciled_failed_attempt'
    assert receipt['reason'] == 'install_failed_before_partition'
    assert receipt['vm_id'] == identity
    assert receipt['disk_uuid'] == disk['disk_uuid']
    assert receipt['storage_detached'] is False
    assert not calls  # detach_storage was False

    # Check bootstrap folder was moved, not deleted
    assert not folder.exists()
    archived = Path(receipt['archived_attempt'])
    assert archived.is_dir()
    assert (archived / 'seed.iso').read_bytes() == b'seed-content-v1'
    assert json.loads((archived / 'admission.json').read_text())['vm_id'] == identity
    assert json.loads((archived / 'launch-intent.json').read_text())['vm_id'] == identity
    assert json.loads((archived / 'reconciliation.json').read_text())['status'] == 'reconciled_failed_attempt'


def test_reconcile_detach_storage_flag_executes_storageattach(monkeypatch, tmp_path):
    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    folder = tmp_path / 'owned' / 'bootstrap'
    folder.mkdir(parents=True)
    seed = folder / 'seed.iso'
    seed.write_bytes(b'seed-content-v2')
    cfg = {'base_folder': str(tmp_path), 'name': 'owned', 'password': 'test'}
    binding = VirtualBoxBinding(identity, 'marker', lambda: cfg)
    disk = {
        'empty_observed': True,
        'allocated_blocks': 0,
        'partition_table_observed': False,
        'metadata_stable': True,
        'disk_uuid': 'disk-uuid-1',
        'metadata_sha256': 'meta-sha-1',
    }
    admission = {
        'vm_id': identity,
        'disk_uuid': 'disk-uuid-1',
        'vdi_metadata_sha256': 'meta-sha-1',
        'seed_sha256': hashlib.sha256(b'seed-content-v2').hexdigest(),
    }
    (folder / 'admission.json').write_text(json.dumps(admission))
    (folder / 'launch-intent.json').write_text(json.dumps({'vm_id': identity, 'started_at': 1791800200.0}))

    info = {'VMState': 'poweroff', 'hardwareuuid': identity, 'SATA-2-0': str(seed), 'SATA-3-0': 'additions.iso'}
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: (info, disk))

    calls = []
    class Client:
        def run(self, *args, **kwargs):
            calls.append(args)

    client = Client()
    receipt = bootstrap.reconcile_failed_attempt(client, binding, cfg, detach_storage=True, request_key='req-detach')
    assert receipt['storage_detached'] is True
    assert len(calls) == 2
    assert calls[0][3:6] == ('SATA', '--port', 2) and calls[0][-1] == 'none'
    assert calls[1][3:6] == ('SATA', '--port', 3) and calls[1][-1] == 'none'


def test_reconcile_refuses_allocated_blocks_or_divergent_hash(monkeypatch, tmp_path):
    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    folder = tmp_path / 'owned' / 'bootstrap'
    folder.mkdir(parents=True)
    seed = folder / 'seed.iso'
    seed.write_bytes(b'seed')
    cfg = {'base_folder': str(tmp_path), 'name': 'owned'}
    binding = VirtualBoxBinding(identity, 'marker', lambda: cfg)
    disk = {
        'empty_observed': True,
        'allocated_blocks': 0,
        'partition_table_observed': False,
        'metadata_stable': True,
        'disk_uuid': 'disk-uuid-1',
        'metadata_sha256': 'meta-sha-1',
    }
    admission = {
        'vm_id': identity,
        'disk_uuid': 'disk-uuid-1',
        'vdi_metadata_sha256': 'meta-sha-1',
        'seed_sha256': hashlib.sha256(b'seed').hexdigest(),
    }
    (folder / 'admission.json').write_text(json.dumps(admission))
    (folder / 'launch-intent.json').write_text(json.dumps({'vm_id': identity}))

    info = {'VMState': 'running', 'hardwareuuid': identity}
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: (info, disk))

    class Client:
        def run(self, *args, **kwargs):
            raise AssertionError('no mutations on refusal')

    client = Client()

    # Refuse if allocated blocks > 0
    disk['allocated_blocks'] = 128
    with pytest.raises(ValueError, match='strictly empty'):
        bootstrap.reconcile_failed_attempt(client, binding, cfg)
    assert folder.exists()

    # Refuse if partitioned
    disk['allocated_blocks'] = 0
    disk['partition_table_observed'] = True
    with pytest.raises(ValueError, match='strictly empty'):
        bootstrap.reconcile_failed_attempt(client, binding, cfg)
    assert folder.exists()

    # Refuse if metadata hash differs
    disk['partition_table_observed'] = False
    disk['metadata_sha256'] = 'different-hash'
    with pytest.raises(ValueError, match='admission metadata mismatch'):
        bootstrap.reconcile_failed_attempt(client, binding, cfg)
    assert folder.exists()

    # Refuse if foreign hardware UUID
    disk['metadata_sha256'] = 'meta-sha-1'
    info['hardwareuuid'] = str(uuid.uuid4())
    with pytest.raises(ValueError, match='hardware DMI UUID'):
        bootstrap.reconcile_failed_attempt(client, binding, cfg)
    assert folder.exists()


def test_reconcile_idempotence_by_request_key(monkeypatch, tmp_path):
    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    folder = tmp_path / 'owned' / 'bootstrap'
    folder.mkdir(parents=True)
    seed = folder / 'seed.iso'
    seed.write_bytes(b'seed')
    cfg = {'base_folder': str(tmp_path), 'name': 'owned'}
    binding = VirtualBoxBinding(identity, 'marker', lambda: cfg)
    disk = {
        'empty_observed': True,
        'allocated_blocks': 0,
        'partition_table_observed': False,
        'metadata_stable': True,
        'disk_uuid': 'disk-1',
        'metadata_sha256': 'meta-1',
    }
    admission = {
        'vm_id': identity,
        'disk_uuid': 'disk-1',
        'vdi_metadata_sha256': 'meta-1',
        'seed_sha256': hashlib.sha256(b'seed').hexdigest(),
    }
    (folder / 'admission.json').write_text(json.dumps(admission))
    (folder / 'launch-intent.json').write_text(json.dumps({'vm_id': identity, 'started_at': 1000.0}))

    info = {'VMState': 'poweroff', 'hardwareuuid': identity}
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: (info, disk))

    class Client:
        def run(self, *args): pass

    client = Client()
    first = bootstrap.reconcile_failed_attempt(client, binding, cfg, request_key='idempotent-key')
    # Second call when bootstrap folder is already moved
    second = bootstrap.reconcile_failed_attempt(client, binding, cfg, request_key='idempotent-key')
    assert first['archived_attempt'] == second['archived_attempt']
    assert first['status'] == second['status'] == 'reconciled_failed_attempt'


def test_install_script_contains_dmi_readback_and_autologin_group():
    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    script = bootstrap.install_script(identity, 64 * 1024**3, 'test-pw').decode()
    assert 'READBACK_DMI_UUID=$dmi_uuid' in script
    assert 'test -r /sys/class/dmi/id/product_uuid' in script
    assert 'groupadd -r autologin' in script
    assert 'usermod -aG autologin' in script
    assert 'systemctl enable vboxadd' in script


def test_runbook_dry_run_and_execute_simulation(monkeypatch, tmp_path):
    from scripts.commander import debian_persistent_runbook as runbook

    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    vm_dir = tmp_path / 'owned'
    bootstrap_dir = vm_dir / 'bootstrap'
    bootstrap_dir.mkdir(parents=True)
    seed = bootstrap_dir / 'seed.iso'
    seed.write_bytes(b'seed-runbook')
    iso = tmp_path / 'debian-live-13.7.0-amd64-xfce.iso'
    iso.write_bytes(b'live-iso-content')
    additions = tmp_path / 'VBoxGuestAdditions.iso'
    additions.write_bytes(b'additions-content')

    disk = {
        'empty_observed': True,
        'allocated_blocks': 0,
        'partition_table_observed': False,
        'metadata_stable': True,
        'disk_uuid': 'disk-rb',
        'metadata_sha256': 'meta-rb',
        'capacity_bytes': 64 * 1024**3,
    }
    admission = {
        'vm_id': identity,
        'disk_uuid': 'disk-rb',
        'vdi_metadata_sha256': 'meta-rb',
        'seed_sha256': hashlib.sha256(b'seed-runbook').hexdigest(),
        'prepared_at': 100.0,
    }
    (bootstrap_dir / 'admission.json').write_text(json.dumps(admission))
    (bootstrap_dir / 'launch-intent.json').write_text(json.dumps({'vm_id': identity, 'started_at': 101.0}))

    cfg = {
        'base_folder': str(tmp_path),
        'name': 'owned',
        'disk_gb': 64,
        'os_family': 'linux',
        'iso_path': str(iso),
        'iso_sha256': hashlib.sha256(b'live-iso-content').hexdigest(),
        'password': 'private-runbook-test',
    }
    binding = VirtualBoxBinding(identity, 'marker', lambda: cfg)

    calls = []
    class Client:
        path = str(additions)
        vm_state = 'poweroff'
        sata_2 = 'none'
        sata_3 = 'none'

        def status(self, b):
            return {
                'VMState': self.vm_state,
                'hardwareuuid': identity,
                'SATA-1-0': 'emptydrive',
                'SATA-2-0': self.sata_2,
                'SATA-3-0': self.sata_3,
                'GuestAdditionsRunLevel': 1 if self.vm_state == 'running' else 0,
            }

        def run(self, *args, **kwargs):
            calls.append(args)
            if args[0] == 'storageattach':
                port = int(args[args.index('--port') + 1])
                medium = str(args[args.index('--medium') + 1])
                if port == 2:
                    self.sata_2 = medium
                elif port == 3:
                    self.sata_3 = medium
            elif args[0] == 'startvm':
                self.vm_state = 'running'
            elif args[0] == 'controlvm' and len(args) > 2 and args[2] == 'poweroff':
                self.vm_state = 'poweroff'
            return ''

        def input(self, *args, **kwargs):
            calls.append(('input', args))
            self.vm_state = 'poweroff'

    client = Client()
    monkeypatch.setattr('sentra_executors.virtualbox_installation.owned_storage', lambda *args: (client.status(binding), disk))
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: (client.status(binding), disk))
    monkeypatch.setattr(runbook, 'owned_storage', lambda *args: (client.status(binding), disk))
    monkeypatch.setattr(bootstrap, '_private_directory', lambda p: p.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(runbook.time, 'sleep', lambda s: None)
    receipts_dir = tmp_path / 'receipts'

    # 1. DRY RUN
    dry_summary = runbook.run_sequence(client, binding, cfg, execute=False, receipts_dir=receipts_dir, settling_delay=0)
    assert dry_summary['status'] == 'DRY_RUN_PLAN_COMPLETE'
    assert not calls  # NO mutations executed in dry run
    assert (receipts_dir / '01-reconcile-dryrun.json').is_file()
    assert (receipts_dir / 'runbook-summary.json').is_file()

    # 2. EXECUTE SIMULATION
    # Monkeypatch verify_guest and configure_disk_boot for simulated run
    monkeypatch.setattr(runbook, 'configure_disk_boot', lambda *a, **k: {'status': 'disk_boot_configured', 'installed_os_verified': False, 'desktop_ready_verified': False})
    monkeypatch.setattr(runbook, 'verify_guest', lambda *a, **k: {'status': 'installed_guest_verified', 'installed_os_verified': True, 'desktop_ready_verified': True})

    exec_summary = runbook.run_sequence(client, binding, cfg, execute=True, receipts_dir=receipts_dir, settling_delay=0)
    assert exec_summary['status'] == 'SUCCEEDED'
    assert (receipts_dir / '01-reconcile.json').is_file()
    assert (receipts_dir / '02-prepare.json').is_file()
    assert (receipts_dir / '03-launch.json').is_file()
    assert (receipts_dir / '04-observe.json').is_file()
    assert (receipts_dir / '05-configure-disk-boot.json').is_file()
    assert (receipts_dir / '06-boot.json').is_file()
    assert (receipts_dir / '07-verify-guest.json').is_file()


def test_reconcile_running_vm_detaches_storage_only_after_poweroff(monkeypatch, tmp_path):
    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    folder = tmp_path / 'owned' / 'bootstrap'
    folder.mkdir(parents=True)
    seed = folder / 'seed.iso'
    seed.write_bytes(b'seed-running-test')
    iso = tmp_path / 'debian-live-13.7.0-amd64-xfce.iso'
    iso.write_bytes(b'live-iso')
    cfg = {'base_folder': str(tmp_path), 'name': 'owned', 'iso_path': str(iso)}
    binding = VirtualBoxBinding(identity, 'marker', lambda: cfg)
    disk = {
        'empty_observed': True,
        'allocated_blocks': 0,
        'partition_table_observed': False,
        'metadata_stable': True,
        'disk_uuid': 'disk-running',
        'metadata_sha256': 'meta-running',
    }
    admission = {
        'vm_id': identity,
        'disk_uuid': 'disk-running',
        'vdi_metadata_sha256': 'meta-running',
        'seed_sha256': hashlib.sha256(b'seed-running-test').hexdigest(),
    }
    (folder / 'admission.json').write_text(json.dumps(admission))
    (folder / 'launch-intent.json').write_text(json.dumps({'vm_id': identity, 'started_at': 200.0}))

    class StrictClient:
        vm_state = 'running'
        sata_2 = str(seed)
        sata_3 = 'additions.iso'
        calls = []

        def status(self, b):
            return {
                'VMState': self.vm_state,
                'hardwareuuid': identity,
                'SATA-1-0': str(iso.resolve()),
                'SATA-2-0': self.sata_2,
                'SATA-3-0': self.sata_3,
            }

        def run(self, *args, **kwargs):
            self.calls.append(args)
            if args[0] == 'storageattach':
                if self.vm_state == 'running':
                    raise RuntimeError('storageattach rejected: drive is not hotpluggable while VM is running')
                port = int(args[args.index('--port') + 1])
                medium = str(args[args.index('--medium') + 1])
                if port == 2: self.sata_2 = medium
                elif port == 3: self.sata_3 = medium
            elif args[0] == 'controlvm' and args[2] == 'poweroff':
                self.vm_state = 'poweroff'
            return ''

    client = StrictClient()
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: (client.status(binding), disk))
    monkeypatch.setattr(bootstrap.time, 'sleep', lambda s: None)

    receipt = bootstrap.reconcile_failed_attempt(client, binding, cfg, detach_storage=True, request_key='k-strict')
    assert receipt['storage_detached'] is True
    assert client.sata_2 == 'none' and client.sata_3 == 'none'
    assert client.vm_state == 'poweroff'
    # Verified poweroff was called before storageattach
    actions = [c[0] for c in client.calls]
    assert actions.index('controlvm') < actions.index('storageattach')


def test_launch_fails_without_recording_intent_when_live_readiness_times_out(monkeypatch, tmp_path):
    from scripts.commander import debian_persistent_runbook as runbook

    identity = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
    vm_dir = tmp_path / 'owned'
    bootstrap_dir = vm_dir / 'bootstrap'
    bootstrap_dir.mkdir(parents=True)
    seed = bootstrap_dir / 'seed.iso'
    seed.write_bytes(b'seed-timeout-test')
    iso = tmp_path / 'debian-live-13.7.0-amd64-xfce.iso'
    iso.write_bytes(b'live-iso')
    (tmp_path / 'VBoxGuestAdditions.iso').write_bytes(b'additions')

    disk = {'empty_observed': True, 'allocated_blocks': 0, 'partition_table_observed': False, 'metadata_stable': True, 'disk_uuid': 'd', 'metadata_sha256': 'm', 'capacity_bytes': 64*1024**3}
    admission = {'vm_id': identity, 'disk_uuid': 'd', 'vdi_metadata_sha256': 'm', 'seed_sha256': hashlib.sha256(b'seed-timeout-test').hexdigest()}
    (bootstrap_dir / 'admission.json').write_text(json.dumps(admission))
    (bootstrap_dir / 'launch-intent.json').write_text(json.dumps({'vm_id': identity}))

    cfg = {'base_folder': str(tmp_path), 'name': 'owned', 'os_family': 'linux', 'iso_path': str(iso), 'iso_sha256': hashlib.sha256(b'live-iso').hexdigest(), 'password': 'pw'}
    binding = VirtualBoxBinding(identity, 'marker', lambda: cfg)

    class UnreadyClient:
        path = str(tmp_path / 'VBoxGuestAdditions.iso')
        calls = []
        vm_state = 'poweroff'
        def status(self, b):
            return {'VMState': self.vm_state, 'hardwareuuid': identity, 'SATA-1-0': str(iso.resolve()), 'SATA-2-0': 'none', 'SATA-3-0': 'none', 'GuestAdditionsRunLevel': 0}
        def run(self, *args, **kwargs):
            self.calls.append(args)
            if args and args[0] == 'startvm':
                self.vm_state = 'running'
            return ''

    client = UnreadyClient()
    monkeypatch.setattr('sentra_executors.virtualbox_installation.owned_storage', lambda *args: (client.status(binding), disk))
    monkeypatch.setattr(bootstrap, 'owned_storage', lambda *args: (client.status(binding), disk))
    monkeypatch.setattr(runbook, 'owned_storage', lambda *args: (client.status(binding), disk))
    monkeypatch.setattr(runbook.time, 'sleep', lambda s: None)

    receipts_dir = tmp_path / 'receipts'
    summary = runbook.run_sequence(client, binding, cfg, execute=True, receipts_dir=receipts_dir, readiness_timeout=0.01, settling_delay=0)
    assert summary['status'] == 'failed'
    assert summary['steps']['launch']['status'] == 'failed_not_started'
    # Intent file was not created in the new bootstrap dir
    new_bootstrap = vm_dir / 'bootstrap'
    assert not (new_bootstrap / 'launch-intent.json').exists()


def test_load_dot_vm_config_unseals_credentials_and_fails_closed(tmp_path):
    from scripts.commander import debian_persistent_runbook as runbook
    import sqlite3
    from sentra_core.conversations import _encode

    db_path = tmp_path / 'shell.sqlite3'
    with sqlite3.connect(str(db_path)) as db:
        db.execute('CREATE TABLE shell_dot_vms(owner TEXT, project TEXT, root TEXT, cpus INT, memory_mb INT, body TEXT)')
        body = _encode({'vm_id': 'real-uuid-1234', 'password': 'unsealed-secret-password', 'name': 'SENTRA-Dot-real'})
        db.execute('INSERT INTO shell_dot_vms VALUES(?, ?, ?, ?, ?, ?)', ('owner', 'proj', 'root', 2, 4096, body))

    rec = runbook.load_dot_vm_config('real-uuid-1234', durable_root=tmp_path)
    assert rec['vm_id'] == 'real-uuid-1234'
    assert rec['password'] == 'unsealed-secret-password'
    assert rec['name'] == 'SENTRA-Dot-real'

    with pytest.raises(KeyError):
        runbook.load_dot_vm_config('non-existent-uuid', durable_root=tmp_path)


