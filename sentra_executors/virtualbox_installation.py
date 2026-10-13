"""Read-only owned VDI evidence and fixed probes for persistent guest installs.

No host mounts, disk formatting, dependency installation or image downloads.
VDI layout references Oracle's VDICore.h; this parser supports only a dynamic,
non-differencing v1.1 base image and never guesses when metadata is unsupported.
"""
from pathlib import Path
import hashlib
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


def installation_plan(client, binding, cfg):
    info, disk = owned_storage(client, binding, cfg)
    family = cfg['os_family']
    live = Path(cfg.get('iso_path') or '').name.lower().startswith('debian-live-')
    return {'vm_id':binding.vm_id, 'vm_state':info.get('VMState'), 'os_family':family, 'disk':disk,
        'status':'empty_virtual_disk' if disk['empty_observed'] else 'disk_data_os_unverified',
        'installation_mode':'debian_live_calamares_or_debian_installer' if live else 'provider_unattended_or_manual_installer',
        'automatic_installation_ready':False, 'installed_os_verified':False,
        'guest_channel_ready':str(info.get('GuestAdditionsRunLevel', 0)) in {'2', '3'},
        'blockers':(['running_guest_must_not_be_formatted'] if info.get('VMState') != 'poweroff' else [])
            + ([] if disk['empty_observed'] else ['disk_not_verified_empty'])
            + (['debian_live_installer_driver_not_admitted'] if live else ['installer_not_homologated'])
            + (['windows_installed_guest_verification_pending'] if family == 'windows' else []),
        'physical_effects_performed':False, 'automatic_retry':False}


LINUX_GUEST_PROBE = r'''root_source=$(findmnt -nr -o SOURCE /) || exit 20
root_type=$(findmnt -nr -o FSTYPE /) || exit 21
root_uuid=$(findmnt -nr -o UUID /) || exit 22
live=0
if test -d /run/live || grep -q 'boot=live' /proc/cmdline; then live=1; fi
identity=$(head -c 100 /etc/sentra-dot-vm-id 2>/dev/null || true)
manager=$(systemctl is-active display-manager 2>/dev/null || true)
session=absent
if pgrep -u sentra -x xfce4-session >/dev/null 2>&1; then session=running; fi
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


def verify_guest(client, binding, cfg):
    _, disk = owned_storage(client, binding, cfg)
    if cfg['os_family'] != 'linux':
        return {'status':'windows_verification_pending', 'installed_os_verified':False, 'desktop_ready_verified':False}
    if not disk['partition_table_observed']:
        return {'status':'owned_disk_not_verified_partitioned', 'vm_id':binding.vm_id,
            'disk_uuid':disk['disk_uuid'], 'installed_os_verified':False, 'desktop_ready_verified':False}
    output = client.run('guestcontrol', binding.vm_id, 'run', '--exe', '/bin/sh', '--username', 'sentra',
        '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 30000,
        '--', '-c', LINUX_GUEST_PROBE, password=cfg['password'], timeout=40)
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


def debian_postinstall_template(vm_id, *, kernel_parameters=''):
    """Prepare a reviewed guest-only script; does not partition or execute.

    VBox's installed Debian template already hashes stdin credentials; this
    supplement establishes the guest identity, desktop autologin and known boot
    parameters. Deployment must independently admit an empty target disk.
    """
    identity = str(uuid.UUID(vm_id))
    if kernel_parameters not in {'','tsc=unstable clocksource=acpi_pm nohz=off maxcpus=1'}:
        raise ValueError('unsupported installed guest kernel parameters')
    return f'''#!/bin/sh
set -eu
test "$(id -u)" = 0
test ! -d /run/live
case "$(findmnt -nr -o SOURCE /)" in /dev/sda[1-9]*) ;; *) exit 30 ;; esac
id sentra >/dev/null
groupadd -r autologin || true
usermod -aG autologin sentra || true
printf '%s\\n' '{identity}' > /etc/sentra-dot-vm-id
install -d -m 755 /etc/lightdm/lightdm.conf.d /etc/default/grub.d
printf '%s\\n' '[Seat:*]' 'autologin-user=sentra' 'autologin-user-timeout=0' 'user-session=xfce' > /etc/lightdm/lightdm.conf.d/60-sentra-dot.conf
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
    postinstall = debian_postinstall_template(ident, kernel_parameters=kernel_parameters)
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
d-i passwd/username string sentra
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
