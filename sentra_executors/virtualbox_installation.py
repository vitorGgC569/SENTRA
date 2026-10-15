"""Read-only owned VDI evidence and fixed probes for persistent guest installs.

No host mounts, disk formatting, dependency installation or image downloads.
VDI layout references Oracle's VDICore.h; this parser supports only a dynamic,
non-differencing v1.1 base image and never guesses when metadata is unsupported.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import struct
import uuid

from .rpa import ExecutorFailure


def inspect_vdi(path, *, expected_uuid, expected_capacity):
    path = Path(path)
    with path.open('rb') as source:
        before = os.fstat(source.fileno())
        header = source.read(512)
        if len(header) != 512 or struct.unpack_from('<II', header, 64) != (0xBEDA107F, 0x10001):
            raise ValueError('unsupported VDI signature or version')
        header_size, image_type = struct.unpack_from('<II', header, 72)
        blocks_offset, data_offset = struct.unpack_from('<II', header, 340)
        capacity, block_size, extra, count, allocated = struct.unpack_from('<QIIII', header, 368)
        ident = str(uuid.UUID(bytes_le=header[392:408]))
        if (not 384 <= header_size <= 1024 or image_type != 1 or ident != str(uuid.UUID(expected_uuid))
                or capacity != expected_capacity or not 1 <= count <= 1048576 or allocated > count
                or block_size != 1048576 or extra != 0 or count != (capacity + block_size - 1) // block_size
                or header[424:456] != bytes(32) or blocks_offset < 72 + header_size
                or data_offset < blocks_offset + count * 4 or data_offset > before.st_size
                or data_offset + allocated * block_size > before.st_size):
            raise ValueError('VDI identity, base-image layout or capacity changed')
        source.seek(blocks_offset)
        table = source.read(count * 4)
        if len(table) != count * 4:
            raise ValueError('VDI block map truncated')
        indices = [index[0] for index in struct.iter_unpack('<I', table)]
        used = [index for index in indices if index < 0xFFFFFFFE]
        if len(used) != allocated or len(set(used)) != allocated or any(index >= allocated for index in used):
            raise ValueError('VDI block map changed or inconsistent')
        first = bytes(512)
        if indices[0] < 0xFFFFFFFE:
            source.seek(data_offset + indices[0] * block_size)
            first = source.read(512)
        # A partition table is evidence of data, never proof of an installed OS.
        partitioned = len(first) == 512 and first[510:512] == b'\x55\xaa' and any(
            first[offset + 4] != 0 and struct.unpack_from('<I', first, offset + 12)[0] > 0
            for offset in (446, 462, 478, 494))
        after = os.fstat(source.fileno())
        stable = (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
    return {'disk_uuid':ident, 'capacity_bytes':capacity, 'allocated_blocks':allocated,
        'total_blocks':count, 'file_bytes':before.st_size, 'metadata_stable':stable,
        'empty_observed':stable and allocated == 0,
        'partition_table_observed':stable and partitioned,
        'metadata_sha256':hashlib.sha256(header + table).hexdigest(),
        'installed_os_verified':False}


def owned_storage(client, binding, cfg):
    info = client.status(binding)
    if 'storage_binding' in cfg:
        from .virtualbox_storage_binding import enrolled_base_storage
        return enrolled_base_storage(client, binding, cfg, info)
    base = Path(cfg['base_folder']).resolve()
    folder = (base / cfg['name']).resolve()
    expected = (folder / 'system.vdi').resolve()
    if folder.parent != base or expected.parent != folder or Path(info.get('CfgFile', '')).parent.resolve() != folder:
        raise ExecutorFailure('virtualbox_owned_disk_path_changed')
    disks = client.disk_attachments(binding)
    if len(disks) != 1:
        raise ExecutorFailure('virtualbox_install_requires_one_owned_virtual_disk')
    disk = disks[0]
    if (disk['controller'] != 'SATA' or disk['port'] != 0 or disk['device'] != 0
            or Path(disk['location']).resolve() != expected or disk.get('parent_uuid')
            or info.get('SATA-ImageUUID-0-0') != disk['disk_uuid']):
        raise ExecutorFailure('virtualbox_disk_binding_changed')
    evidence = inspect_vdi(expected, expected_uuid=disk['disk_uuid'], expected_capacity=cfg['disk_gb'] * 1073741824)
    return info, evidence


_WINDOWS_KEY_FIELDS = ('product_key', 'windows_product_key', 'license_key')
_WINDOWS_CHANNELS = {'owner_supplied_iso', 'evaluation_unactivated', 'owner_attested_license'}


def observational_install(cfg, vm_id):
    """Read the owned verify receipt. This does not probe or reinstall the guest."""
    folder = Path(cfg.get('base_folder', '')) / cfg.get('name', '') / 'runbook-receipts'
    path = folder / '07-verify-guest.json'
    if path.is_symlink() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get('vm_id') != str(vm_id):
        return None
    if (data.get('status') != 'installed_guest_verified' or data.get('boot_mode') != 'installed_disk'
            or data.get('installed_os_verified') is not True or data.get('desktop_ready_verified') is not True
            or data.get('root_source') != '/dev/sda1' or not data.get('disk_uuid') or not data.get('root_uuid')):
        return None
    from .virtualbox_vm import NEXT_AUTHORIZED_GUEST_STEP
    return {'vm_id': str(vm_id), 'disk_uuid': data['disk_uuid'], 'root_source': data['root_source'],
        'root_uuid': data['root_uuid'], 'installed_os_verified': True, 'desktop_ready_verified': True,
        'boot_mode': 'installed_disk', 'observation_only': True, 'contemporary_probe': False,
        'receipt': 'runbook-receipts/07-verify-guest.json', 'replays_launch_intent': False,
        'next_authorized_step': NEXT_AUTHORIZED_GUEST_STEP}


def assess_windows_license(cfg):
    """Honest license posture. A product key is never stored, passed, or invented."""
    if any(name in cfg for name in _WINDOWS_KEY_FIELDS):
        raise ValueError('Windows product keys are not stored or accepted')
    record = cfg.get('windows_license')
    if record is None:
        return {'posture':'not_attested', 'channel':None, 'install_admitted':False,
            'evaluation_usable':False, 'activation_claimed':False, 'product_key_stored':False}
    if not isinstance(record, dict) or any(name in record for name in _WINDOWS_KEY_FIELDS) or record.get('product_key_stored') is not False:
        raise ValueError('Windows product keys are not stored or accepted')
    channel = record.get('channel')
    if channel not in _WINDOWS_CHANNELS:
        raise ValueError('honest Windows license channel required')
    if channel == 'owner_attested_license' and record.get('attested_by') != 'owner':
        raise ValueError('owner attestation required')
    return {'posture':channel, 'channel':channel, 'install_admitted':True,
        'evaluation_usable':channel == 'evaluation_unactivated',
        'activation_claimed':False, 'product_key_stored':False}


def installation_plan(client, binding, cfg):
    info, disk = owned_storage(client, binding, cfg)
    family = cfg['os_family']
    live = Path(cfg.get('iso_path') or '').name.lower().startswith('debian-live-')
    license_info = assess_windows_license(cfg) if family == 'windows' else None
    return {'vm_id':binding.vm_id, 'vm_state':info.get('VMState'), 'os_family':family,
        'username':_probe_account(cfg), 'disk':disk,
        'status':'empty_virtual_disk' if disk['empty_observed'] else 'disk_data_os_unverified',
        'installation_mode':'debian_live_calamares_or_debian_installer' if live else 'provider_unattended_or_manual_installer',
        'automatic_installation_ready':False, 'installed_os_verified':False,
        'guest_channel_ready':str(info.get('GuestAdditionsRunLevel', 0)) in {'2', '3'},
        'windows_usable':False, 'activation_claimed':False, 'product_key_stored':False,
        'license_posture':None if license_info is None else license_info['posture'],
        'blockers':(['running_guest_must_not_be_formatted'] if info.get('VMState') != 'poweroff' else [])
            + ([] if disk['empty_observed'] else ['disk_not_verified_empty'])
            + (['debian_live_installer_driver_not_admitted'] if live else ['installer_not_homologated'])
            + (['windows_installed_guest_verification_pending'] if family == 'windows' else [])
            + (['windows_license_not_attested'] if license_info and not license_info['install_admitted'] else []),
        'physical_effects_performed':False, 'automatic_retry':False}


LINUX_GUEST_PROBE = r'''root_source=$(findmnt -nr -o SOURCE /) || exit 20
root_type=$(findmnt -nr -o FSTYPE /) || exit 21
root_uuid=$(findmnt -nr -o UUID /) || exit 22
live=0
if test -d /run/live || grep -q 'boot=live' /proc/cmdline; then live=1; fi
identity=$(head -c 100 /etc/sentra-dot-vm-id 2>/dev/null || true)
manager=$(systemctl is-active display-manager 2>/dev/null || true)
session=absent
if pgrep -u @@ACCOUNT@@ -x xfce4-session >/dev/null 2>&1; then session=running; fi
printf 'SENTRA_ROOT_SOURCE=%s\nSENTRA_ROOT_TYPE=%s\nSENTRA_ROOT_UUID=%s\nSENTRA_LIVE=%s\nSENTRA_VM_ID=%s\nSENTRA_DISPLAY_MANAGER=%s\nSENTRA_XFCE_SESSION=%s\n' "$root_source" "$root_type" "$root_uuid" "$live" "$identity" "$manager" "$session"
'''


def classify_linux_guest(output, *, expected_vm_id):
    fields = {}
    for line in output.splitlines():
        if not line.startswith('SENTRA_') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in fields or len(value) > 400:
            raise ValueError('ambiguous installed guest probe')
        fields[key] = value
    required = {'SENTRA_ROOT_SOURCE','SENTRA_ROOT_TYPE','SENTRA_ROOT_UUID','SENTRA_LIVE','SENTRA_VM_ID','SENTRA_DISPLAY_MANAGER','SENTRA_XFCE_SESSION'}
    if fields.keys() != required:
        raise ValueError('incomplete installed guest probe')
    live = fields['SENTRA_LIVE'] != '0' or fields['SENTRA_ROOT_TYPE'] in {'overlay','aufs','squashfs','tmpfs'}
    root_bound = bool(re.fullmatch(r'/dev/sda[1-9][0-9]*', fields['SENTRA_ROOT_SOURCE'])) and bool(
        re.fullmatch(r'[0-9a-fA-F-]{8,64}', fields['SENTRA_ROOT_UUID']))
    verified = not live and root_bound and fields['SENTRA_VM_ID'] == str(uuid.UUID(expected_vm_id)) and fields['SENTRA_ROOT_TYPE'] == 'ext4'
    return {'status':'installed_guest_verified' if verified else 'live_guest' if live else 'installed_guest_unbound',
        'installed_os_verified':verified, 'boot_mode':'live' if live else 'disk_unverified' if not verified else 'installed_disk',
        'root_source':fields['SENTRA_ROOT_SOURCE'], 'root_uuid':fields['SENTRA_ROOT_UUID'],
        'desktop_ready_verified':verified and fields['SENTRA_DISPLAY_MANAGER']=='active' and fields['SENTRA_XFCE_SESSION']=='running'}


WINDOWS_GUEST_PROBE = r'''$user = 'absent'
if (Get-LocalUser -Name @@ACCOUNT@@ -ErrorAction SilentlyContinue) { $user = 'present' }
$explorer = 'absent'
if (Get-Process -Name explorer -ErrorAction SilentlyContinue) { $explorer = 'running' }
$status = 'unknown'
$products = @(Get-CimInstance -ClassName SoftwareLicensingProduct -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'Windows*' -and $null -ne $_.LicenseStatus })
if ($products.Count -ge 1) {
  switch ([int]$products[0].LicenseStatus) {
    0 { $status = 'Unlicensed' }
    1 { $status = 'Licensed' }
    2 { $status = 'OOBGrace' }
    3 { $status = 'OOTGrace' }
    4 { $status = 'NonGenuine' }
    5 { $status = 'Notification' }
    6 { $status = 'ExtendedGrace' }
    default { $status = 'unknown' }
  }
}
Write-Output ('SENTRA_USER=' + $user)
Write-Output ('SENTRA_EXPLORER=' + $explorer)
Write-Output ('SENTRA_LICENSE_STATUS=' + $status)
'''


def classify_windows_guest(output):
    fields = {}
    for line in output.splitlines():
        if not line.startswith('SENTRA_') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in fields or len(value) > 80:
            raise ValueError('ambiguous windows guest probe')
        fields[key] = value
    required = {'SENTRA_USER', 'SENTRA_EXPLORER', 'SENTRA_LICENSE_STATUS'}
    known = {'Licensed', 'Unlicensed', 'OOBGrace', 'OOTGrace', 'NonGenuine', 'Notification', 'ExtendedGrace'}
    if (fields.keys() != required or fields['SENTRA_USER'] not in {'present', 'absent'}
            or fields['SENTRA_EXPLORER'] not in {'running', 'absent'}
            or fields['SENTRA_LICENSE_STATUS'] not in known | {'unknown'}):
        raise ValueError('incomplete windows guest probe')
    status = fields['SENTRA_LICENSE_STATUS']
    installed = fields['SENTRA_USER'] == 'present' and status in known
    desktop = installed and fields['SENTRA_EXPLORER'] == 'running'
    return {'installed_os_verified':installed, 'desktop_ready_verified':desktop, 'license_status':status,
        'boot_mode':'installed_disk' if installed else 'windows_unverified'}


def windows_usable(classified, license_info):
    """Usable only from a guest observation. Attestation never invents activation."""
    if not classified.get('desktop_ready_verified'):
        return False
    if classified.get('license_status') == 'Licensed':
        return True
    return (classified.get('license_status') == 'Notification' and license_info.get('evaluation_usable') is True)


def _probe_account(cfg):
    from .virtualbox_project import _guest_account
    return _guest_account(cfg)


def _render_probe(template, cfg):
    account = _probe_account(cfg)
    rendered = template.replace('@@ACCOUNT@@', account)
    if '@@ACCOUNT@@' in rendered or account not in rendered:
        raise ValueError('guest probe account was not applied')
    return rendered


def verify_windows_guest(client, binding, cfg, disk):
    info = assess_windows_license(cfg)
    base = {'vm_id':binding.vm_id, 'disk_uuid':disk['disk_uuid'], 'license_posture':info['posture'],
        'activation_claimed':False, 'product_key_stored':False, 'automatic_retry':False, 'windows_usable':False}
    if not disk['partition_table_observed']:
        return {**base, 'status':'windows_verification_pending', 'installed_os_verified':False, 'desktop_ready_verified':False}
    output = client.run('guestcontrol', binding.vm_id, 'run', '--exe',
        r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe', '--username', _probe_account(cfg),
        '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 30000, '--',
        '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', _render_probe(WINDOWS_GUEST_PROBE, cfg),
        password=cfg['password'], timeout=40)
    classified = classify_windows_guest(output)
    return {**base, **classified, 'status':'windows_guest_observed',
        'windows_usable':windows_usable(classified, info),
        'activation_observed':classified['license_status'] == 'Licensed'}


def windows_guest_additions(client, binding, cfg):
    """Refuse Guest Additions until the guest shows a user and explorer.

    Attaching the local VBoxGuestAdditions.iso is only an effect of the injected
    client. A missing ISO fails closed. This path never marks windows_usable and
    never accepts or stores a product key. Desktop usability stays on
    verify_windows_guest.
    """
    license_info = assess_windows_license(cfg)
    if cfg.get('os_family') != 'windows':
        raise ValueError('windows guest additions require a windows guest')
    location = getattr(client, 'path', None)
    additions = None if not location else Path(location).parent / 'VBoxGuestAdditions.iso'
    if additions is None or additions.is_symlink() or not additions.is_file() or additions.name != 'VBoxGuestAdditions.iso':
        raise ValueError('local Oracle Guest Additions ISO required')
    info, disk = owned_storage(client, binding, cfg)
    output = client.run('guestcontrol', binding.vm_id, 'run', '--exe',
        r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe', '--username', _probe_account(cfg),
        '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 30000, '--',
        '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', _render_probe(WINDOWS_GUEST_PROBE, cfg),
        password=cfg['password'], timeout=40)
    classified = classify_windows_guest(output)
    user_present = any(line == 'SENTRA_USER=present' for line in output.splitlines())
    explorer_running = any(line == 'SENTRA_EXPLORER=running' for line in output.splitlines())
    base = {'vm_id':binding.vm_id, 'disk_uuid':disk['disk_uuid'], 'license_posture':license_info['posture'],
        'license_status':classified['license_status'], 'activation_claimed':False, 'product_key_stored':False,
        'automatic_retry':False, 'windows_usable':False,
        'installed_os_verified':classified['installed_os_verified'],
        'desktop_ready_verified':classified['desktop_ready_verified'],
        'user_present':user_present, 'explorer_running':explorer_running,
        'guest_additions_attached':False, 'additions_effect':None, 'physical_effects_performed':False,
        'guest_additions_runlevel':str(info.get('GuestAdditionsRunLevel', 0))}
    if not user_present or not explorer_running:
        return {**base, 'status':'windows_guest_additions_refused', 'reason':'guest_user_and_explorer_required'}
    medium = str(additions.resolve())
    client.run('storageattach', binding.vm_id, '--storagectl', 'SATA', '--port', 3, '--device', 0,
        '--type', 'dvddrive', '--medium', medium)
    return {**base, 'status':'windows_guest_additions_iso_attached', 'reason':None,
        'guest_additions_attached':True, 'physical_effects_performed':True,
        'additions_effect':{'via':'injected_client', 'command':'storageattach', 'controller':'SATA',
            'port':3, 'device':0, 'medium_name':'VBoxGuestAdditions.iso', 'medium':medium}}


def verify_guest(client, binding, cfg):
    _, disk = owned_storage(client, binding, cfg)
    if cfg['os_family'] == 'windows':
        return verify_windows_guest(client, binding, cfg, disk)
    if cfg['os_family'] != 'linux':
        return {'status':'windows_verification_pending', 'installed_os_verified':False, 'desktop_ready_verified':False,
            'windows_usable':False, 'activation_claimed':False, 'product_key_stored':False}
    if not disk['partition_table_observed']:
        return {'status':'owned_disk_not_verified_partitioned', 'vm_id':binding.vm_id,
            'disk_uuid':disk['disk_uuid'], 'installed_os_verified':False, 'desktop_ready_verified':False}
    output = client.run('guestcontrol', binding.vm_id, 'run', '--exe', '/bin/sh', '--username', _probe_account(cfg),
        '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 30000,
        '--', '-c', _render_probe(LINUX_GUEST_PROBE, cfg), password=cfg['password'], timeout=40)
    return {**classify_linux_guest(output, expected_vm_id=binding.vm_id), 'vm_id':binding.vm_id, 'disk_uuid':disk['disk_uuid']}


def configure_disk_boot(client, binding, cfg):
    info, disk = owned_storage(client, binding, cfg)
    if info.get('VMState') != 'poweroff' or not disk['partition_table_observed']:
        raise ValueError('disk boot requires a powered-off owned VM and stable partitioned virtual disk')
    client.run('modifyvm', binding.vm_id, '--boot1', 'disk', '--boot2', 'none', '--boot3', 'none', '--boot4', 'none')
    client.run('storageattach', binding.vm_id, '--storagectl', 'SATA', '--port', 1, '--device', 0,
        '--type', 'dvddrive', '--medium', 'none')
    for port in (2, 3):
        if info.get(f'SATA-{port}-0', 'none') != 'none':
            client.run('storageattach', binding.vm_id, '--storagectl', 'SATA', '--port', port, '--device', 0,
                '--type', 'dvddrive', '--medium', 'none')
    return {'vm_id':binding.vm_id, 'disk_uuid':disk['disk_uuid'], 'status':'disk_boot_configured',
        'boot_source':'owned_virtual_disk', 'installed_os_verified':False, 'desktop_ready_verified':False,
        'vm_started':False, 'disk_formatted':False}


def debian_postinstall_template(vm_id, *, kernel_parameters='', account='sentra'):
    """Prepare a reviewed guest-only script; does not partition or execute.

    VBox's installed Debian template already hashes stdin credentials; this
    supplement establishes the guest identity, desktop autologin and known boot
    parameters. Deployment must independently admit an empty target disk.
    """
    identity = str(uuid.UUID(vm_id))
    account = _probe_account({'username': account})
    if kernel_parameters not in {'','tsc=unstable clocksource=acpi_pm nohz=off maxcpus=1'}:
        raise ValueError('unsupported installed guest kernel parameters')
    return f'''#!/bin/sh
set -eu
test "$(id -u)" = 0
test ! -d /run/live
case "$(findmnt -nr -o SOURCE /)" in /dev/sda[1-9]*) ;; *) exit 30 ;; esac
id {account} >/dev/null
groupadd -r autologin || true
usermod -aG autologin {account} || true
printf '%s\\n' '{identity}' > /etc/sentra-dot-vm-id
install -d -m 755 /etc/lightdm/lightdm.conf.d /etc/default/grub.d
printf '%s\\n' '[Seat:*]' 'autologin-user={account}' 'autologin-user-timeout=0' 'user-session=xfce' > /etc/lightdm/lightdm.conf.d/60-sentra-dot.conf
printf '%s\\n' 'GRUB_CMDLINE_LINUX_DEFAULT="{kernel_parameters}"' > /etc/default/grub.d/60-sentra-dot.cfg
update-grub
systemctl enable lightdm
'''


def prepare_debian_installer_templates(plan, *, kernel_parameters=''):
    """Build reviewable guest templates only after a fresh empty-disk preflight.

    Does not write files, remaster media, admit partitioning or start an install.
    VBox must substitute the password hash and a separately admitted installer
    driver must deliver these files plus Guest Additions to the exact guest.
    """
    disk = plan.get('disk') or {}
    if (plan.get('os_family') != 'linux' or plan.get('vm_state') != 'poweroff'
            or disk.get('empty_observed') is not True or disk.get('metadata_stable') is not True):
        raise ValueError('fresh powered-off empty owned Linux VDI required for installer templates')
    ident = str(uuid.UUID(plan['vm_id']))
    disk_uuid = str(uuid.UUID(disk['disk_uuid']))
    account = _probe_account({'username': plan.get('username') or 'sentra'})
    postinstall = debian_postinstall_template(ident, kernel_parameters=kernel_parameters, account=account)
    preseed = f'''# Prepared only; owned VM {ident}, virtual disk {disk_uuid}.
# Delivery and physical partition admission are intentionally separate.
d-i debian-installer/locale string pt_BR.UTF-8
d-i keyboard-configuration/xkb-keymap select br
d-i time/zone string America/Sao_Paulo
d-i netcfg/choose_interface select auto
d-i netcfg/get_hostname string sentra-{ident[:8]}
d-i netcfg/get_domain string local
d-i passwd/root-login boolean false
d-i passwd/user-fullname string SENTRA Dot
d-i passwd/username string {account}
d-i passwd/user-password-crypted password @@VBOX_INSERT_USER_PASSWORD_SHACRYPT512@@
d-i passwd/user-default-groups string sudo audio video
d-i partman-auto/disk string /dev/sda
d-i partman-auto/method string regular
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
tasksel tasksel/first multiselect standard, desktop, xfce-desktop
d-i pkgsel/include string sudo build-essential dkms linux-headers-amd64
d-i grub-installer/only_debian boolean true
d-i grub-installer/bootdev string /dev/sda
d-i debian-installer/add-kernel-opts string {kernel_parameters}
d-i preseed/late_command string cp /cdrom/sentra-postinstall.sh /target/root/sentra-postinstall.sh && chmod 700 /target/root/sentra-postinstall.sh && in-target /bin/sh /root/sentra-postinstall.sh
d-i debian-installer/exit/poweroff boolean true
'''
    return {'status':'prepared_not_applied', 'vm_id':ident, 'disk_uuid':disk_uuid,
        'preseed_template':preseed, 'postinstall_script':postinstall,
        'remaining_delivery_steps':['admit_exact_empty_guest_disk_partitioning', 'deliver_preseed_and_postinstall_to_installer',
            'substitute_password_hash_privately', 'install_virtualbox_guest_additions', 'verify_boot_and_guest_identity'],
        'physical_effects_performed':False, 'automatic_installation_ready':False}
