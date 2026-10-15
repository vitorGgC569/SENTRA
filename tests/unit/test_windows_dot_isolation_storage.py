"""Pinned storage layouts using tiny synthetic VDIs, never real guest disks."""
import copy
import hashlib
import json
from pathlib import Path
import os
from dataclasses import replace
import pytest
from test_virtualbox_installation import client
from sentra_executors.rpa import ExecutorFailure
from sentra_executors.virtualbox_installation import owned_storage, installation_plan
from sentra_executors.virtualbox_storage_binding import storage_binding_candidate


@pytest.fixture
def legacy(tmp_path):
    c, binding, cfg, old, ident = client(tmp_path, allocated=True, partitioned=True)
    # These tests isolate storage layout validation. Canonical owner/CP approval
    # is exercised separately with real CentralEffectContext and artifacts.
    binding=replace(binding,storage_approval=lambda *_: True)
    # Configuration is in one owned folder; the legacy data disk is in another
    # exact directory. This reproduces the real mismatch without using its data.
    (old.parent / 'owned.vbox').write_text('<fixture/>')
    root = tmp_path / 'private-storage'; root.mkdir()
    disk = root / 'system-localiso2.vdi'
    old.rename(disk)
    actual = c.disk_attachments(binding)[0]
    c.disk_attachments = lambda b: [{**actual, 'location': str(disk)}]
    candidate = storage_binding_candidate(c, binding, cfg, storage_root=root)
    return c, binding, cfg, disk, candidate


def enroll(cfg, candidate):
    # Test fixture models a trusted host approval record. Production enrollment
    # must be performed by the owner-authorized config path after review; this
    # helper is not an application endpoint or a claim of actual CP approval.
    return {**cfg, 'storage_binding': {key: copy.deepcopy(candidate[key]) for key in ('schema','record','sha256')}
                                     | {'approval_operation_id': 'op-fixture-owner-storage-approval'}}


def test_nonstandard_disk_refused_without_exact_enrollment_and_candidate_is_inert(legacy):
    c, b, cfg, disk, candidate = legacy
    assert candidate['applied'] is candidate['authorization_granted'] is False
    with pytest.raises(ExecutorFailure): owned_storage(c, b, cfg)
    with pytest.raises(ExecutorFailure, match='trusted_storage_enrollment'):
        owned_storage(c, b, {**cfg, 'storage_binding': candidate})
    assert c.calls == [] and disk.exists()


def test_exact_host_enrolled_legacy_disk_enters_read_only_plan_without_false_os_claim(legacy):
    c, b, cfg, disk, candidate = legacy
    result = installation_plan(c, b, enroll(cfg, candidate))
    assert result['disk']['disk_uuid'] == candidate['record']['disk_uuid']
    assert result['disk']['storage_binding'] == 'host_enrolled_exact_base'
    assert result['disk']['storage_binding_sha256'] == candidate['sha256']
    assert result['disk']['guest_data_integrity_verified'] is False
    assert result['disk']['parent_chain_verified'] is False
    assert not result['installed_os_verified'] and not result['physical_effects_performed']
    assert c.calls == []


@pytest.mark.parametrize('field,value', [
    ('vm_id','11111111-1111-4111-8111-111111111111'), ('marker_sha256','b'*64),
    ('disk_uuid','22222222-2222-4222-8222-222222222222'), ('capacity_bytes',2*1073741824),
    ('identity_sha256','c'*64), ('file_inode',123), ('controller','IDE'), ('port',1),
    ('device',1), ('file_device',42), ('parent_chain',[{'uuid':'parent'}]),
])
def test_changed_or_recomputed_record_cannot_target_another_identity(legacy, field, value):
    c, b, cfg, disk, candidate = legacy
    configured = enroll(cfg, candidate)
    record = configured['storage_binding']['record']
    record[field] = value
    # Recomputing an unkeyed digest cannot make it match the live exact binding.
    configured['storage_binding']['sha256'] = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises((ExecutorFailure, ValueError)):
        owned_storage(c, b, configured)
    assert c.calls == []


def test_same_basename_in_another_directory_does_not_match_enrollment(legacy, tmp_path):
    c, b, cfg, disk, candidate = legacy
    foreign = tmp_path / 'foreign'; foreign.mkdir()
    copy_path = foreign / disk.name; copy_path.write_bytes(disk.read_bytes())
    actual = c.disk_attachments(b)[0]
    c.disk_attachments = lambda b: [{**actual,'location':str(copy_path)}]
    with pytest.raises(ExecutorFailure): owned_storage(c, b, enroll(cfg,candidate))
    assert c.calls == []


def test_replacement_with_same_uuid_and_bytes_still_changes_file_identity(legacy):
    c, b, cfg, disk, candidate = legacy
    replacement = disk.with_name('replacement.vdi')
    replacement.write_bytes(disk.read_bytes()); replacement.replace(disk)
    with pytest.raises(ExecutorFailure, match='identity_changed'):
        owned_storage(c,b,enroll(cfg,candidate))


def test_mutable_guest_data_and_vdi_modification_uuid_do_not_invalidate_geometry_pin(legacy):
    c, b, cfg, disk, candidate = legacy
    with disk.open('r+b') as output:
        output.seek(408);output.write(bytes.fromhex('112233445566778899aabbccddeeff00'))
        output.seek(8192+1024);output.write(b'Windows Setup writes guest data here')
    _, evidence = owned_storage(c,b,enroll(cfg,candidate))
    assert evidence['storage_binding_sha256'] == candidate['sha256']
    assert not evidence['guest_data_integrity_verified']


def test_base_parent_or_vdi_header_changes_cannot_sneak_in_as_same_file(legacy):
    c,b,cfg,disk,candidate = legacy
    with disk.open('r+b') as output:
        output.seek(424);output.write(bytes.fromhex('112233445566778899aabbccddeeff00'))
    with pytest.raises(ValueError, match='parent_chain_not_supported'):
        owned_storage(c,b,enroll(cfg,candidate))


def test_differencing_attachment_is_refused_until_full_parent_chain_is_supported(legacy):
    c,b,cfg,disk,candidate = legacy
    actual = c.disk_attachments(b)[0]
    c.disk_attachments = lambda b:[{**actual,'parent_uuid':'11111111-1111-4111-8111-111111111111'}]
    with pytest.raises(ExecutorFailure):owned_storage(c,b,enroll(cfg,candidate))


def test_same_file_behind_symbolic_link_is_not_an_enrolled_path(legacy, tmp_path):
    c,b,cfg,disk,candidate = legacy
    link=tmp_path/'linked.vdi'
    try:link.symlink_to(disk)
    except OSError:pytest.skip('OS symlink permission unavailable')
    actual=c.disk_attachments(b)[0]
    c.disk_attachments=lambda b:[{**actual,'location':str(link)}]
    with pytest.raises(ValueError, match='linked_storage_path'):
        owned_storage(c,b,enroll(cfg,candidate))


def test_invalid_enrollment_never_falls_back_to_the_old_disk(legacy):
    c,b,cfg,disk,candidate=legacy
    for envelope in (None, {}, {'schema':1}, {**enroll(cfg,candidate)['storage_binding'],'sha256':'0'*64}):
        with pytest.raises(ExecutorFailure):owned_storage(c,b,{**cfg,'storage_binding':envelope})
    assert c.calls == []


def test_hardlink_alias_of_writable_guest_disk_is_refused(legacy):
    c,b,cfg,disk,candidate=legacy
    alias=disk.with_name('aliased.vdi')
    os.link(disk,alias)
    with pytest.raises(ValueError,match='stable_storage_file_identity'):
        owned_storage(c,b,enroll(cfg,candidate))


def test_swap_during_read_does_not_certify_inventory_from_different_files(legacy,monkeypatch):
    import sentra_executors.virtualbox_installation as installation
    c,b,cfg,disk,candidate=legacy
    real_inspect=installation.inspect_vdi
    def swapped(*args,**kwargs):
        value=real_inspect(*args,**kwargs)
        replacement=disk.with_name('race-replacement.vdi')
        replacement.write_bytes(disk.read_bytes());replacement.replace(disk)
        return value
    monkeypatch.setattr(installation,'inspect_vdi',swapped)
    with pytest.raises(ExecutorFailure,match='changed_during_read'):
        owned_storage(c,b,enroll(cfg,candidate))


def test_legacy_system_vdi_path_is_unchanged_without_new_enrollment(tmp_path):
    c,b,cfg,path,ident=client(tmp_path,allocated=True,partitioned=True)
    _,evidence=owned_storage(c,b,cfg)
    assert evidence['disk_uuid']==ident and 'storage_binding' not in evidence
    assert c.calls == []
